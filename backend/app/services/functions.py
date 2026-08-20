import os, json, chardet, asyncio, stat, time, re, shapely, shutil, base64
from config import ALLOWED_USERS
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import Depends, HTTPException, status
from redis.asyncio.lock import Lock
from scipy.spatial import cKDTree
from scipy.ndimage import distance_transform_edt, gaussian_filter
from config import PROJECT_ROOT
from uuid import uuid4
import numpy as np, xarray as xr, pandas as pd
import geopandas as gpd, dask.array as da
from services import constants

variablesNames = constants.variablesNames
units = constants.units

def encoding_detect(file_path: str) -> str:
    """Detect the encoding of a file."""
    encoding = 'utf-8'
    if not os.path.exists(file_path) or not os.path.isfile(file_path): return encoding
    with open(file_path, 'rb') as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        encoding = result['encoding']
    return encoding

USERS = json.load(open(ALLOWED_USERS, "r", encoding=encoding_detect(ALLOWED_USERS)))

def basic_auth(credentials: HTTPBasicCredentials=Depends(HTTPBasic())):
    username, password = credentials.username, credentials.password
    if username not in USERS or USERS[username] != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorized", headers={"WWW-Authenticate": "Basic"}
        )
    return username

def project_definer(old_name, username='admin'):
    new_name = f'{username}/{old_name}' if username!='admin' else 'demo'
    name_id = f'{new_name}/{uuid4()}'
    if old_name == '': new_name = new_name.rstrip('/')
    return new_name, name_id

def safe_remove(path, retries=10, delay=1):
    for _ in range(retries):
        try:
            os.remove(path)
            return
        except PermissionError:
            time.sleep(delay)
    raise Exception(f"Cannot delete file: {path}")

def numberFormatter(arr: np.array, decimals: int=2) -> list:
    try:
        arr = np.asarray(arr, dtype=float)
        result = np.empty(arr.shape, dtype=object)
        finite_mask = np.isfinite(arr)
        abs_arr = np.abs(arr)
        # Make a mask for large numbers
        large_mask = finite_mask & (abs_arr >= 1)
        result[large_mask] = np.round(arr[large_mask], decimals)
        # Make a mask for small numbers
        small_mask = finite_mask & (abs_arr < 1) & (arr != 0)
        fmt = f"%.{decimals}e"
        result[small_mask] = [float(fmt % v) for v in arr[small_mask]]
        # Make a mask for zero
        zero_mask = finite_mask & (arr == 0)
        result[zero_mask] = 0.0
        # NaN -> None
        nan_mask = ~finite_mask
        result[nan_mask] = None
        return np.reshape(result, arr.shape)
    except: return list(arr)
    
def interpolation_Z(grid_net: gpd.GeoDataFrame, x_coords: np.ndarray, y_coords: np.ndarray,
    z_values: np.ndarray, n_neighbors: int=2, geo_type: str='polygon') -> np.ndarray:
    gdf_known = gpd.GeoDataFrame(geometry=gpd.points_from_xy(x_coords, y_coords), crs = grid_net.crs)
    gdf_known = gdf_known.to_crs(gdf_known.estimate_utm_crs())
    gdf_points = grid_net.copy().to_crs(grid_net.estimate_utm_crs())
    if geo_type == 'polygon': gdf_points['geometry'] = gdf_points['geometry'].centroid
    tree = cKDTree(list(zip(gdf_known['geometry'].x, gdf_known['geometry'].y)))
    dists, idx = tree.query(list(zip(gdf_points['geometry'].x, gdf_points['geometry'].y)), k = n_neighbors)
    weight = 1 / (dists + 1e-10)**2
    value = np.sum(weight * z_values[idx], axis=1)/np.sum(weight, axis=1)
    return numberFormatter(value)

def unstructuredGridCreator(data_map: xr.Dataset) -> gpd.GeoDataFrame:
    # Use dask array to speed up, keep lazy-load
    node_x = data_map['mesh2d_node_x'].data
    node_y = data_map['mesh2d_node_y'].data
    face_nodes = data_map['mesh2d_face_nodes'].data
    coords = da.stack([node_x, node_y], axis=1)
    faces = xr.where(np.isnan(face_nodes), 0, face_nodes).astype(int)-1
    counts = da.sum(faces != -1, axis=1)
    if hasattr(coords, 'compute'): coords = coords.compute()
    if hasattr(faces, 'compute'): faces = faces.compute()
    if hasattr(counts, 'compute'): counts = counts.compute()
    # Compute to create polygons
    polygons = [shapely.geometry.Polygon(coords[face[:count]]) for face, count in zip(faces, counts)]
    # Check coordinate reference system
    if 'projected_coordinate_system' in data_map.variables:
        crs_code = data_map['projected_coordinate_system'].attrs.get('EPSG_code')
        # Convert to WGS84 if not already
        grid = gpd.GeoDataFrame(geometry=polygons, crs=crs_code).to_crs(epsg=4326)
    else: grid = gpd.GeoDataFrame(geometry=polygons, crs="EPSG:4326")
    return grid










