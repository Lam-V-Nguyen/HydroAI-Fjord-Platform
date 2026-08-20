import os, pickle, warnings, optuna
from config import SOURCE_BACKEND
import geopandas as gpd, numpy as np
from shapely.geometry import Polygon, MultiPolygon
from meshkernel import MeshKernel, GeometryList, OrthogonalizationParameters
from meshkernel.errors import MeshKernelError
from services import functions
import xarray as xr, dask.array as da
from pyproj import CRS
warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.ERROR)


def initLakes(lake_path=None, depth_path=None):
    # Load lake database
    lake_dir = os.path.join(SOURCE_BACKEND, 'lakes_database')
    if lake_path is not None:
        lake_db_path = os.path.normpath(os.path.join(lake_dir, 'lakes.shp'))
        if os.path.exists(lake_db_path):
            lake_db = gpd.read_file(lake_db_path)
            if lake_db.crs != 'EPSG:4326': lake_db = lake_db.to_crs(crs='EPSG:4326')
            lake_db = lake_db.dropna(subset=['name', 'region', 'geometry'])
            lake_db['name'] = lake_db['name'].fillna('Unnamed Lake')
            lake_db['region'] = lake_db['region'].where(lake_db['region'].notna(), 
                'Unknown Municipality' + lake_db["id"].fillna(-1).astype(str))
            lake_db['id'] = lake_db['id'].astype('int64')
        with open(lake_path, 'wb') as f: pickle.dump(lake_db, f)
    if depth_path is not None:
        depth_db_path = os.path.normpath(os.path.join(lake_dir, 'depth.shp'))
        depth_db = gpd.read_file(depth_db_path)
        depth_db['id'] = depth_db['id'].astype('int64')
        depth_db.set_index('id', inplace=True)
        if depth_db.crs != 'EPSG:4326': depth_db = depth_db.to_crs(crs='EPSG:4326')
        depth_db['depth'] = depth_db['depth'].astype(float)
        with open(depth_path, 'wb') as f: pickle.dump(depth_db, f)

def remove_holes(geom, cell_size=0):
    geom = geom.buffer(0)
    if (cell_size == None): cell_size = geom.area
    if geom.geom_type == "Polygon":
        kept_interiors = [ring for ring in geom.interiors if Polygon(ring).area >= cell_size]
        return Polygon(geom.exterior, kept_interiors)
    elif geom.geom_type == "MultiPolygon":
        polygons = []
        for poly in geom.geoms:
            kept_interiors = [ring for ring in poly.interiors if Polygon(ring).area >= cell_size]
            polygons.append(Polygon(poly.exterior, kept_interiors))
        return MultiPolygon(polygons)
    else: return geom

def sort_face_ccw(nodes, x, y):
    xs, ys = x[nodes], y[nodes]
    cx, cy = xs.mean(), ys.mean()
    angles = np.arctan2(ys - cy, xs - cx)
    return nodes[np.argsort(angles)]

def meshkernel_to_Ugrid(mk: MeshKernel, crs: str):
    mesh = mk.mesh2d_get()
    node_x = np.asarray(mesh.node_x, dtype=np.float64)
    node_y = np.asarray(mesh.node_y, dtype=np.float64)
    edge_x = np.asarray(mesh.edge_x, dtype=np.float64)
    edge_y = np.asarray(mesh.edge_y, dtype=np.float64)
    edge_nodes = mesh.edge_nodes.reshape((-1, 2)).astype(np.int32)  # 0-based
    face_nodes_flat = mesh.face_nodes.astype(np.int32)
    nodes_per_face = mesh.nodes_per_face.astype(np.int32)
    face_x = np.asarray(mesh.face_x, dtype=np.float64)
    face_y = np.asarray(mesh.face_y, dtype=np.float64)
    nEdges, nFaces = edge_x.size, face_x.size
    max_n = int(nodes_per_face.max()) if nFaces > 0 else 0
    face_nodes = np.full((nFaces, max_n), np.nan, dtype=np.float64)
    if nFaces > 0:
        offset = np.zeros(nFaces, dtype=int)
        offset[1:] = np.cumsum(nodes_per_face[:-1])
        for i, n in enumerate(nodes_per_face):
            if n < 3: continue
            nodes = face_nodes_flat[offset[i]:offset[i] + n]
            # remove duplicates, keep order
            _, idx = np.unique(nodes, return_index=True)
            nodes = nodes[np.sort(idx)]
            if nodes.size < 3: continue
            nodes = sort_face_ccw(nodes, node_x, node_y)
            face_nodes[i, :nodes.size] = nodes + 1
    edge_faces = np.full((nEdges, 2), -1, dtype=np.int32)
    if nEdges > 0 and nFaces > 0:
        edge_dict = {tuple(sorted(edge_nodes[i])): i for i in range(nEdges)}
        offset = np.zeros(nFaces, dtype=int)
        offset[1:] = np.cumsum(nodes_per_face[:-1])
        for fidx in range(nFaces):
            n = nodes_per_face[fidx]
            nodes = face_nodes_flat[offset[fidx]:offset[fidx] + n]
            for i in range(n):
                n1, n2 = nodes[i], nodes[(i + 1) % n]
                key = tuple(sorted((n1, n2)))
                eidx = edge_dict.get(key)
                if eidx is None: continue
                if edge_faces[eidx, 0] == -1: edge_faces[eidx, 0] = fidx
                elif edge_faces[eidx, 1] == -1: edge_faces[eidx, 1] = fidx
    ds = xr.Dataset()
    crs_obj = CRS.from_user_input(crs)
    if crs_obj.is_geographic: grid_mapping_name = 'latitude_longitude'
    else: grid_mapping_name = 'transverse_mercator'
    ds["crs"] = xr.DataArray(0,
        attrs={
            "grid_mapping_name": grid_mapping_name,
            "crs_wkt": crs_obj.to_wkt(),
        }
    )
    ds["mesh2d_edge_x"] = (("mesh2d_nEdges",), da.from_array(edge_x))
    ds["mesh2d_edge_y"] = (("mesh2d_nEdges",), da.from_array(edge_y))
    ds["mesh2d_edge_nodes"] = (("mesh2d_nEdges", "Two"), da.from_array(edge_nodes))
    ds["mesh2d_face_nodes"] = ( ("mesh2d_nFaces", "mesh2d_nMax_face_nodes"), da.from_array(face_nodes))
    ds["mesh2d_edge_faces"] = (("mesh2d_nEdges", "Two"), da.from_array(edge_faces))    
    ds["mesh2d_face_x"] = (("mesh2d_nFaces",), da.from_array(face_x))
    ds["mesh2d_face_y"] = (("mesh2d_nFaces",), da.from_array(face_y))
    ds["mesh2d_node_x"] = (("mesh2d_nNodes",), da.from_array(node_x))
    ds["mesh2d_node_y"] = (("mesh2d_nNodes",), da.from_array(node_y))
    ds["mesh2d_node_x"].attrs["grid_mapping"] = "crs"
    ds["mesh2d_node_y"].attrs["grid_mapping"] = "crs"
    x_bnd = np.full_like(face_nodes, np.nan, dtype=np.float64)
    y_bnd = np.full_like(face_nodes, np.nan, dtype=np.float64)
    for i in range(nFaces):
        fn = face_nodes[i]
        valid = ~np.isnan(fn)
        if valid.sum() < 3: continue
        idx = fn[valid].astype(int) - 1
        x_bnd[i, valid] = node_x[idx]
        y_bnd[i, valid] = node_y[idx]
    ds["mesh2d_face_x_bnd"] = (("mesh2d_nFaces", "mesh2d_nMax_face_nodes"), da.from_array(x_bnd))
    ds["mesh2d_face_y_bnd"] = (("mesh2d_nFaces", "mesh2d_nMax_face_nodes"), da.from_array(y_bnd))
    # ---- UGRID topology variable ----
    ds["mesh2d"] = xr.DataArray(0,
        attrs={
            "cf_role": "mesh_topology", "topology_dimension": 2,
            "long_name": "Topology data of 2D mesh",
            "node_coordinates": "mesh2d_node_x mesh2d_node_y",
            "node dimensions": "mesh2d_nNodes", 
            "max_face_nodes_dimension": "mesh2d_nMax_face_nodes",
            "edge_node_connectivity": "mesh2d_edge_nodes",
            "edge_dimensions": "mesh2d_nEdges",
            "face_node_connectivity": "mesh2d_face_nodes",
            "edge_face_connectivity": "mesh2d_edge_faces",
            "face_dimension": "mesh2d_nFaces",
            "face_coordinates": "mesh2d_face_x mesh2d_face_y",
            "edge_coordinates": "mesh2d_edge_x mesh2d_edge_y",
        },
    )
    ds["mesh2d"].attrs["grid_mapping"] = "crs"
    ds = ds.set_coords(["mesh2d_node_x", "mesh2d_node_y"])
    return ds

def netCDF_creator(mk: MeshKernel, depth: gpd.GeoDataFrame=None):
    mesh = mk.mesh2d_get()
    node_x, node_y = mesh.node_x, mesh.node_y
    crs = depth.crs if depth is not None else "EPSG:4326"
    if depth is not None:
        if depth.crs == 'EPSG:4326': depth = depth.to_crs(crs)
        temp_grid = gpd.GeoDataFrame(geometry=gpd.points_from_xy(node_x, node_y), crs=depth.crs)
        node_z = functions.interpolation_Z(
            temp_grid, depth["geometry"].x, depth["geometry"].y, 
            depth["depth"].values, n_neighbors=2, geo_type='point'
        )
    else: node_z = np.zeros(len(node_x))
    # Convert to Ugrid
    grid_uds = meshkernel_to_Ugrid(mk, crs)
    grid_uds['mesh2d_node_z'] = (("mesh2d_nNodes",), da.from_array(node_z.astype(np.float64)))    
    grid_uds.attrs.update({ "institution": 'Private', "references": 'vanlnNTNU@gmail.com'})
    return grid_uds

def Bayesian_Optimization(polygon:GeometryList, space: dict, iterations: int=500,
                          progress_callback=None, stop_checker=None):
    """
    Bayesian Optimization using Optuna to minimize the maximum orthogonality.
    """
    best_value, best_type, best_level = float('inf'), "", float('inf')
    def objective_function(trial: optuna.trial.Trial):
        try:
            type_choice = trial.suggest_categorical("mode", space['mode'])
            level = trial.suggest_float("level", space['level'][0], space['level'][1])
            outer_iterations = trial.suggest_int(
                "outer_iterations", space['outer_iterations'][0], 
                space['outer_iterations'][1]
            )
            boundary_iterations = trial.suggest_int(
                "boundary_iterations", space['boundary_iterations'][0], 
                space['boundary_iterations'][1]
            )
            inner_iterations = trial.suggest_int(
                "inner_iterations", space['inner_iterations'][0], 
                space['inner_iterations'][1]
            )
            smoothing_factor = trial.suggest_float(
                "smoothing_factor", space['smoothing_factor'][0], 
                space['smoothing_factor'][1]
            )
            mk, iteration = MeshKernel(), trial.number + 1
            if type_choice == 'auto': mk.mesh2d_make_triangular_mesh_from_polygon(polygon)
            else: mk.mesh2d_make_triangular_mesh_from_polygon(polygon, scale_factor=float(level))        
            ortho_params = OrthogonalizationParameters(
                outer_iterations=outer_iterations, boundary_iterations=boundary_iterations,
                inner_iterations=inner_iterations,
                orthogonalization_to_smoothing_factor=smoothing_factor
            )        
            mk.mesh2d_compute_orthogonalization(
                project_to_land_boundary_option=False,
                orthogonalization_parameters=ortho_params, land_boundaries=polygon
            )        
            orth = mk.mesh2d_get_orthogonality().values
            orth_valid = orth[orth != -999]
            if len(orth_valid) == 0: return 1e6
            min_value, mean_value, max_value = np.min(orth_valid), np.mean(orth_valid), np.max(orth_valid)
            nonlocal best_value, best_type, best_level
            if max_value < best_value:
                best_type, best_level, best_value = type_choice, level, max_value
            # Update progress
            if progress_callback:
                progress_callback(
                    iteration=iteration, min_value=min_value, mean_value=mean_value,
                    best_type=best_type, best_level=best_level,
                    current_ortho=max_value, best_ortho=best_value
                )
            if stop_checker and stop_checker():
                trial.study.stop()
                return best_value
        except MeshKernelError: return 1e6
        except Exception: return 1e6
        if max_value <= 0.01 or trial.number >= iterations: trial.study.stop()
        return max_value
    sampler = optuna.samplers.TPESampler(seed=42, multivariate=True)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.optimize(objective_function, n_trials=iterations, show_progress_bar=False)
    return study.best_params

def mk_from_params(params, polygon):
    mk = MeshKernel()
    if params['mode'] == 'auto': mk.mesh2d_make_triangular_mesh_from_polygon(polygon)
    else: mk.mesh2d_make_triangular_mesh_from_polygon(polygon, scale_factor=float(params['level']))
    ortho_params = OrthogonalizationParameters(
        outer_iterations=params['outer_iterations'],
        boundary_iterations=params['boundary_iterations'],
        inner_iterations=params['inner_iterations'],
        orthogonalization_to_smoothing_factor=params['smoothing_factor']
    )
    mk.mesh2d_compute_orthogonalization(
        project_to_land_boundary_option=False,
        orthogonalization_parameters=ortho_params,
        land_boundaries=polygon
    )
    return mk