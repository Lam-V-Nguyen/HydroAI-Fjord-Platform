import os, json, chardet, asyncio, stat, time, re, shapely, shutil, base64, signal, subprocess
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

def seconds_datetime(seconds: int) -> tuple:
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds = seconds % 60
    return days, f"{hours:02d}:{minutes:02d}:{seconds:02d}"

async def auto_extend(lock: Lock, interval: int = 10):
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                if not await lock.locked(): break
            except Exception: break
            try: await lock.extend()
            except Exception: break
    except asyncio.CancelledError: pass

def remove_readonly(func, path, excinfo):
    # Change the readonly bit, but not the file contents
    os.chmod(path, stat.S_IWRITE)
    func(path)

def append_log(log_path, text):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding=encoding_detect(log_path), errors="replace") as f:
        f.write(text.strip() + "\n")
        f.flush()


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
    polygons = [
        shapely.geometry.Polygon(coords[face[:count]]) 
        for face, count in zip(faces, counts)
    ]
    # Check coordinate reference system
    if 'projected_coordinate_system' in data_map.variables:
        crs_code = data_map['projected_coordinate_system'].attrs.get('EPSG_code')
        # Convert to WGS84 if not already
        grid = gpd.GeoDataFrame(geometry=polygons, crs=crs_code).to_crs(epsg=4326)
    elif 'crs' in data_map.variables:
        crs_wkt = data_map['crs'].attrs.get('crs_wkt')
        if crs_wkt: 
            grid = gpd.GeoDataFrame(geometry=polygons, crs=crs_wkt).to_crs(epsg=4326)
        elif 'EPSG_code' in data_map['crs'].attrs:
            grid = gpd.GeoDataFrame(geometry=polygons, crs=data_map['crs'].attrs['EPSG_code']).to_crs(epsg=4326)
        else: grid = gpd.GeoDataFrame(geometry=polygons, crs="EPSG:4326")
    else: grid = gpd.GeoDataFrame(geometry=polygons, crs="EPSG:4326")
    return grid

def fileWriter(template_path: str, params: dict) -> str:
    # Open the file and read its contents
    with open(template_path, 'r', encoding=encoding_detect(template_path)) as file:
        file_content = file.read()
    # Replace placeholders with actual values
    for key, value in params.items():
        file_content = file_content.replace(f'{{{key}}}', str(value))
    # Adjust the structure
    lines, result = [], []
    for line in file_content.split('\n'):
        if '#' in line and not line.strip().startswith('#'):
            left, right = line.split('#', 1)
            left, middle = left.split("=", 1)
            lines.append((left + " = ", middle.strip(), '#' + right.strip()))
        else: lines.append((line.strip(), "", ""))
    max_len = max(len(middle) for _, middle, _ in lines) + 1
    for left, middle, right in lines:
        result.append(left + middle.ljust(max_len) + right)
    result = "\n".join(result)
    return result

def contentWriter(project_name: str, filename: str, data: list, content: str, unit: str='sec') -> tuple:
    try:
        path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))
        # Write weather.tim file
        tim_path = os.path.normpath(os.path.join(path, filename))
        with open(tim_path, 'w', encoding=encoding_detect(tim_path)) as f:
            for row in data:
                if unit == 'sec': row[0] = int(row[0]/1000)
                elif unit == 'min': row[0] = int(row[0]/(1000*60))
                temp = '  '.join([str(r) for r in row])
                f.write(f"{temp}\n")
        # Add weather data to FlowFM.ext file
        ext_path = os.path.normpath(os.path.join(path, "FlowFM.ext"))
        if os.path.exists(ext_path):
            with open(ext_path, 'r', encoding=encoding_detect(ext_path)) as f:
                update_content = f.read()
            parts = re.split(r'\n\s*\n', update_content)
            parts = [p.strip() for p in parts if p.strip()]
            if (any(filename in part for part in parts)): 
                index = parts.index([part for part in parts if filename in part][0])
                parts[index] = content
            else: parts.append(content)
            with open(ext_path, 'w', encoding=encoding_detect(ext_path)) as file:
                joined_parts = '\n\n'.join(parts)
                file.write(f"\n{joined_parts}\n")
        else:
            with open(ext_path, 'w', encoding=encoding_detect(ext_path)) as f:
                f.write(f"\n{content}\n")
        status, message = 'ok', "Data is saved successfully."
    except Exception as e:
        status, message = 'error', f"Error: {str(e)}"
    return status, message

def postProcess(directory: str) -> dict:
    try:
        parent_path = os.path.dirname(directory)
        output_folder = os.path.normpath(os.path.join(parent_path, 'output'))
        os.makedirs(output_folder, exist_ok=True)
        output_HYD_path = os.path.normpath(os.path.join(output_folder, 'HYD'))
        # Create the directory output_HYD_path
        if os.path.exists(output_HYD_path): shutil.rmtree(output_HYD_path, onerror=remove_readonly)
        os.makedirs(output_HYD_path, exist_ok=True)
        subdirs = [d for d in os.listdir(directory) if os.path.isdir(os.path.normpath(os.path.join(directory, d)))]
        if not subdirs: return {'status': 'error', 'message': f'No simulation output folders found: {subdirs}.'}
        # Copy folder DFM_DELWAQ to the parent directory
        DFM_DELWAQ_from = os.path.normpath(os.path.join(directory, 'DFM_DELWAQ'))
        DFM_DELWAQ_to = os.path.normpath(os.path.join(parent_path, 'DFM_DELWAQ'))
        if os.path.exists(DFM_DELWAQ_to): shutil.rmtree(DFM_DELWAQ_to, onerror=remove_readonly)
        if os.path.exists(DFM_DELWAQ_from):
            shutil.copytree(DFM_DELWAQ_from, DFM_DELWAQ_to)
            shutil.rmtree(DFM_DELWAQ_from, onerror=remove_readonly)
        # Copy files to the directory output
        DFM_OUTPUT_folder = os.path.normpath(os.path.join(directory, 'DFM_OUTPUT'))
        if not os.path.exists(DFM_OUTPUT_folder):
            return {'status': 'error', 'message': 'No output folder found'}
        select_files = ['FlowFM.dia', 'FlowFM_his.nc', 'FlowFM_map.nc']
        found_files = [f for f in os.listdir(DFM_OUTPUT_folder) if f in select_files]
        if len(found_files) == 0: return {'status': 'error', 'message': 'No required files found in the output folder'}
        # Copy and Remove the outputs
        for f in found_files:
            src = os.path.normpath(os.path.join(DFM_OUTPUT_folder, f))
            # # Using .nc format
            # shutil.copy2(src, output_HYD_path)

            # Using .zarr format
            if f.endswith('.nc'):
                zarr_path = os.path.normpath(os.path.join(output_HYD_path, f.replace('.nc', '.zarr')))
                tmp_path = zarr_path + "_tmp"
                if os.path.exists(tmp_path): shutil.rmtree(tmp_path, onerror=remove_readonly)
                with xr.open_dataset(src, chunks='auto') as ds:
                    ds.to_zarr(tmp_path, mode='w', consolidated=True, compute=True)
                os.rename(tmp_path, zarr_path)
            else: shutil.copy2(src, output_HYD_path)
            safe_remove(src)
        # Clean DFM_OUTPUT folder
        if os.path.exists(DFM_OUTPUT_folder): shutil.rmtree(DFM_OUTPUT_folder, onerror=remove_readonly)
        return {'status': 'ok', 'message': 'Simulation completed successfully'}
    except Exception as e: return {'status': 'error', 'message': str(e)}

def kill_process(process):
    if not process: return {"status": "ok", "message": "No process to kill"}
    try:
        if process.poll() is not None: return {"status": "ok", "message": "Simulation stopped"}
        # Try terminate
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=5)
            return {"status": "ok", "message": "Simulation stopped"}
        except Exception: pass
        try:
            process.terminate()
            process.wait(timeout=5)
            return {"status": "ok", "message": "Simulation terminated."}
        except Exception: pass
        # Force kill for Windows
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return {"status": "ok", "message": "Simulation force killed"}
    except Exception as e: 
        return {"status": "error", "message": str(e)}

async def load_dataset_cached(project_cache, key, dm, dir_path, filename):
    if project_cache is None or not filename: return None
    path = os.path.normpath(os.path.join(dir_path, filename))
    if not os.path.exists(path): return None
    ds = dm.get(path)
    project_cache[key] = ds
    return ds
