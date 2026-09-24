import os, dotenv, rasterio, zipfile, rioxarray, sys, pyflwdir, re, stat, time, psutil
import logging, cdsapi, calendar, gc, shutil, traceback, subprocess, dask
import geopandas as gpd, numpy as np, pandas as pd, xarray as xr
from shapely.geometry import Polygon, MultiPolygon, Point
from scipy.spatial import cKDTree
from netCDF4 import Dataset, date2num
from rasterio.io import MemoryFile
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import xy as rasterio_xy
from services import functions, flow_functions
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
from hydromt_wflow import WflowSbmModel
from pyflwdir import dem
from config import PROJECT_ROOT, WFLOW_PATH
from dask.distributed import get_client

if "bool" not in np.__dict__: np.bool = np.bool_

dotenv.load_dotenv()
MET_url, MET_client_id = os.getenv('MET_ProstAPI_URL'), os.getenv('MET_ProstAPI_CLIENT_ID')
NVE_url, NVE_client_id = os.getenv('NVE_URL'), os.getenv('NVE_API_KEY')
NODATA_DEM, NODATA_INT, BUFFER = -9999.0, 0, 0.01

soils = [
    ['Clay', 'Sand', 'Silt', 'Bulk density', 'Soil organic carbon', 'Soil pH'],
    ['0', '5', '15', '30', '60', '100', '200']
]
soil_types = {
    'bulk density': ['BLDFIE_M', 'bd', 1000, np.int16, -32768],
    'clay': ['CLYPPT_M', 'clyppt', 1, np.uint8, 255], 
    'sand': ['SNDPPT_M', 'sndppt', 1, np.uint8, 255],
    'silt': ['SLTPPT_M', 'sltppt', 1, np.uint8, 255],  
    'organic carbon': ['OCDENS_M', 'oc', 1, np.int16, -32768], 
    'pH': ['PHIHOX_M', 'ph', 10, np.uint8, 255]
}
soil_depths = {
    '0cm': 'sl1', '5cm': 'sl2', '15cm': 'sl3', '30cm': 'sl4', 
    '60cm': 'sl5', '100cm': 'sl6', '200cm': 'sl7'
}
soil_type_reverse = {
    'clyppt': 'Clay', 'sndppt': 'Sand', 'sltppt': 'Silt', 
    'bd': 'Bulk density', 'oc': 'Soil organic carbon', 'ph': 'Soil pH'
}
soil_depth_reverse = {v: k for k, v in soil_depths.items()}
variables = {
    'total_precipitation': 'tp', # Precipitation
    '2m_temperature': 't2m', # Temperature
    '10m_u_component_of_wind': 'u10', '10m_v_component_of_wind': 'v10', # Wind
    'surface_pressure': 'sp',  # Pressure
    'surface_solar_radiation_downwards': 'ssrd', # Shortwave radiation
    'surface_thermal_radiation_downwards': 'strd', # Longwave radiation
}

class StreamToLogger:
    PROGRESS_PATTERN = re.compile(r'\[\s*[#=]*\s*\]\s*\|\s*\d+%\s*Completed\s*\|')
    def __init__(self, logger, level=logging.INFO, log_path=None):
        self.logger = logger
        self.level = level
        self.log_path = log_path
    def update_logger(self, new_logger):
        self.logger = new_logger
    def write(self, buf):
        if not buf: return
        if '\r' in buf or self.PROGRESS_PATTERN.search(buf):
            progress = buf.split('\r')[-1].strip()
            if progress and self.PROGRESS_PATTERN.search(progress):
                self._update_progress(progress)
                return
        buf = buf.strip()
        if not buf: return
        for line in buf.splitlines():
            self.logger.log(self.level, line.rstrip())
    def _update_progress(self, progress):
        if not self.log_path: return
        # Format exactly like logging.Formatter
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        record = logging.LogRecord(
            name=self.logger.name, level=self.level, pathname="",
            lineno=0, msg=progress, args=(), exc_info=None
        )
        new_line = formatter.format(record)
        try:
            with open(self.log_path, "r+", encoding="utf-8") as f:
                lines = f.readlines()
                progress_index = None
                for i in range(len(lines) - 1, -1, -1):
                    if self.PROGRESS_PATTERN.search(lines[i]):
                        progress_index = i
                        break
                if progress_index is not None:
                    lines[progress_index] = new_line + "\n"
                else: lines.append(new_line + "\n")
                f.seek(0)
                f.writelines(lines)
                f.truncate()
        except OSError: pass
    def flush(self):
        pass

def interpolate_extrapolate(data, mask_nan, get_nearest=False, power=2, max_neighbors=8):
    h, w = data.shape
    mask_valid = ~mask_nan
    y_valid, x_valid = np.where(mask_valid)
    valid_values = data[mask_valid]
    y_fill, x_fill = np.where(mask_nan)
    n_points, n_fill = len(valid_values), len(y_fill)
    result = data.copy()
    if n_points == 0: return np.full((h, w), np.nan)
    if n_fill == 0: return result
    points_valid = np.column_stack((x_valid, y_valid))
    points_fill = np.column_stack((x_fill, y_fill))
    tree = cKDTree(points_valid)
    if not get_nearest: # interpolate using IDW
        k = min(max_neighbors, n_points)
        distances, indices = tree.query(points_fill, k=k)
        if k == 1: filled_values = valid_values[indices]
        else:
            distances = np.maximum(distances, 1e-8)
            weights = 1.0 / (distances ** power)
            weights = weights / weights.sum(axis=1, keepdims=True)
            neighbor_values = valid_values[indices]
            filled_values = np.sum(weights * neighbor_values, axis=1)
        result[y_fill, x_fill] = filled_values
    else: # get nearest neighbor
        distances, indices = tree.query(points_fill, k=1)
        nearest_values = valid_values[indices]
        result[y_fill, x_fill] = nearest_values
    return result

def remove_holes(geom):
    if isinstance(geom, Polygon): return Polygon(geom.exterior)
    elif isinstance(geom, MultiPolygon):
        return MultiPolygon([Polygon(p.exterior) for p in geom.geoms])
    else: return geom

def write_geotif(array, profile, output_path, nodata=NODATA_DEM):
    array[np.isnan(array)] = nodata
    array = array.astype(profile["dtype"])
    profile.update(nodata=nodata)
    with rasterio.open(output_path, 'w', **profile) as dst:
        dst.write(array, 1)

def create_LAI(arr_2D, terrain, out_path, nodata=255):
    # Compute LAI
    lai_path = r"backend\src\flow_samples\landcover\LAI_Norway.zip"
    if os.path.exists(out_path): os.remove(out_path)
    land_flat, water_classes = arr_2D.ravel(), [40, 41, 44]
    valid_mask = (land_flat != nodata)
    land_valid = land_flat[valid_mask]
    unique_classes = np.unique(land_valid)
    df = pd.DataFrame(index=unique_classes.astype(int))
    with zipfile.ZipFile(lai_path, "r") as zip_ref:
        tif_names = [n for n in zip_ref.namelist() if n.endswith(".tif")]
        for name in tif_names:
            with zip_ref.open(name) as f:
                with MemoryFile(f.read()) as memfile:
                    month = name.split("_")[2].replace(".tif", "")
                    lai = rioxarray.open_rasterio(memfile).squeeze()
                    lai_match = lai.rio.reproject_match(terrain, resampling=Resampling.nearest)
                    lai_arr = lai_match.values.astype(np.float32)
                    lai_arr[lai_arr < -1000] = np.nan
                    lai_flat = lai_arr.ravel()
                    lai_valid = lai_flat[valid_mask]
                    lai_valid[np.isin(land_valid, water_classes)] = 0
                    tmp = pd.DataFrame({"type": land_valid, "lai": lai_valid})
                    df[int(month)] = np.round(tmp.groupby("type")["lai"].mean(), 3)
    df = df.reindex(sorted(df.columns), axis=1)
    df.index.name = os.path.basename(out_path).replace("_lai.csv", "")
    df.to_csv(out_path, index=True)

def is_valid_netcdf(path, var):
    try:
        with xr.open_dataset(path) as ds:
           vars = list(ds.data_vars)
           if len(vars) == 0 or var not in vars: return False
        return True
    except Exception:
        return False

def prepare_interpolator(grid_net, x_coords, y_coords, n_neighbors=2, geo_type="point"):
    gdf_known = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(x_coords, y_coords), crs=grid_net.crs,
    )
    utm = grid_net.estimate_utm_crs()
    gdf_known = gdf_known.to_crs(utm)
    gdf_points = grid_net.to_crs(utm).copy()
    if geo_type == "polygon": gdf_points.geometry = gdf_points.geometry.centroid
    tree = cKDTree(
        np.column_stack([gdf_known.geometry.x, gdf_known.geometry.y])
    )
    dists, idx = tree.query(
        np.column_stack([gdf_points.geometry.x, gdf_points.geometry.y]), k=n_neighbors
    )
    weight = 1.0 / (dists + 1e-10) ** 2
    weight /= weight.sum(axis=1, keepdims=True)
    return idx, weight

def create_forcing(values, ny, nx, mask_nan, single_value, idx=None, weight=None):
    values = np.asarray(values, dtype=np.float32)
    nt = values.shape[0]
    values = values.reshape(nt, -1)
    if single_value:
        if values.shape[1] != 1: return None
        values = values[:, 0]
        data = np.broadcast_to(values[:, None, None], (nt, ny, nx)).astype(np.float32)
    else:
        interp = values[:, idx]
        interp = np.sum(interp * weight[None, :, :], axis=2)
        data = interp.reshape(nt, ny, nx).astype(np.float32)
    data[..., mask_nan] = 0
    return data

def setup_logger(name, log_path: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers: return logger
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    return logger

def weather_downloader(project_name, processes, process_key, flow_name, start, end, time_zone, catchment, buffer=BUFFER):
    # Prepare forcing data from the global model ARE5
    # Source: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download
    # Remove old log
    project_dir = os.path.join(PROJECT_ROOT, project_name)
    flow_dir = os.path.join(project_dir, "flows", flow_name)
    log_path = os.path.join(project_dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    logger = setup_logger("cdsapi", log_path)
    CDS_url, CDS_key = os.getenv('CDS_URL'), os.getenv('CDS_API_KEY')
    config_path = Path.home() / '.cdsapirc'
    if not config_path.exists():
        logger.info("Creating .cdsapirc ...")
        config_path.write_text(f"url: {CDS_url}\nkey: {CDS_key}\n", encoding='utf-8')
        logger.info(f"Created at: {config_path}")
    forcing_dir = os.path.join(flow_dir, 'forcing')
    os.makedirs(forcing_dir, exist_ok=True)
    download_dir = os.path.join(forcing_dir, 'download')
    if not os.path.exists(download_dir): os.makedirs(download_dir)
    forcing_path = os.path.join(forcing_dir, "weather_forcing.nc")
    forcing = {
        'precip': ['tp', 'mm'], 'temp': ['t2m', 'degC'],
        'kin': ['ssrd', 'W/m^2'], 'kout': ['strd', 'W/m^2'],
        'wind': ['', 'm/s'], 'press_msl': ['sp', 'Pa']
    }
    dataset, nc = 'reanalysis-era5-single-levels', None
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    try:
        logger.info("Weather downloader started.")
        logger.info("Preparing output NetCDF...")
        raw_path = os.path.join(flow_dir, "raw", "dtm_raw.tif")      
        with rasterio.open(raw_path) as src:
            dem_array, crs = src.read(1), src.crs
            transform, nodata = src.transform, src.nodata
            height, width = src.height, src.width        
        mask_nan = np.isnan(dem_array) | (dem_array == nodata)
        mask_nan = mask_nan.astype(bool)
        ny, nx = dem_array.shape[0], dem_array.shape[1]
        if catchment.crs != "EPSG:4326": catchment = catchment.to_crs("EPSG:4326")
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        start_time = functions.local_to_utc(start, time_zone).replace(tzinfo=None)
        end_time = functions.local_to_utc(end, time_zone).replace(tzinfo=None)
        lon_min, lat_min, lon_max, lat_max = catchment.total_bounds
        north, east = max(lat_min, lat_max), max(lon_min, lon_max)
        south, west = min(lat_min, lat_max), min(lon_min, lon_max)
        area = [north + buffer, west - buffer, south - buffer, east + buffer]
        logger.info(f"Bounding box: {area}")
        if os.path.exists(forcing_path):
            functions.safe_remove(forcing_path)
            logger.info("Removing old forcing data...")
        time_index, time_step = 0, 'hours'
        x_coords = transform.c + (np.arange(width) + 0.5) * transform.a
        y_coords = transform.f + (np.arange(height) + 0.5) * transform.e
        nc = Dataset(forcing_path, "w", format="NETCDF4")
        nc.createDimension("time", None)
        nc.createDimension("y", ny)
        nc.createDimension("x", nx)
        time_var = nc.createVariable("time", "f8", ("time",))
        time_var.units = f"{time_step} since 1900-01-01 00:00:00"
        time_var.calendar = "proleptic_gregorian"
        y_var = nc.createVariable("y", "f4", ("y",))
        x_var = nc.createVariable("x", "f4", ("x",))
        y_var[:], x_var[:], nc_vars = y_coords, x_coords, {}
        crs_var = nc.createVariable("crs", "i4")
        if crs.is_geographic: crs_var.grid_mapping_name = "latitude_longitude"
        else: crs_var.grid_mapping_name = "transverse_mercator"
        crs_var.crs_wkt = crs.to_wkt()
        try: crs_var.epsg_code = crs.to_epsg()
        except Exception: pass
        for var, (_, unit) in forcing.items():
            nc_vars[var] = nc.createVariable(
                var, "f4", ("time", "y", "x"), zlib=True, complevel=7, fill_value=-9999.0,
                shuffle=True, chunksizes=(24, 128, 128), least_significant_digit=2
            )
            nc_vars[var].units, nc_vars[var].grid_mapping = unit, "crs"
        # Download ERA5 data
        logger.info("Downloading ERA5 data...")
        client = cdsapi.Client(quiet=False, debug=False)
        current = start_time.replace(day=1)
        while current <= end_time:
            files, bad_files, month_files = [], [], []
            year, month = current.year, current.month
            last_day = calendar.monthrange(year, month)[1]
            month_start = datetime(year, month, 1)
            month_end = datetime(year, month, last_day, 23)
            # Clip by requested range
            actual_start = max(start_time, month_start)
            actual_end = min(end_time, month_end)
            # Days to download
            days = [f"{d:02d}" for d in range(actual_start.day, actual_end.day + 1)]
            for key, var in variables.items():
                request = {
                    'product_type': 'reanalysis', 'variable': [key],
                    'year': [str(year)], 'month': [f"{month:02d}"], 'day': days,
                    'time': [f"{h:02d}:00" for h in range(24)], 'area': area,
                    'data_format': 'netcdf', 'download_format': 'unarchived'
                }
                out_file = f"{year}_{month:02d}_{var}.nc"
                out_path = os.path.join(download_dir, out_file)
                client.retrieve(dataset, request, out_path)
                # Check valid files
                if flow_functions.is_valid_netcdf(out_path, var): files.append(out_path)
                else: bad_files.append(out_path)
                month_files.append(out_path)
            logger.info("ERA5 download completed successfully")
            # Check valid files
            logger.info("\n=========================================================")
            logger.info("Checking valid files...")
            # Filter valid files
            logger.info(f"Year: {year}, Month: {month}")
            n = len(files) + len(bad_files)
            logger.info(f"Number of valid files: {len(files)}/{n}")
            logger.info(f"Number of invalid files: {len(bad_files)}/{n}")
            if len(bad_files) > 0:
                logger.info("Bad files:")
                for f in bad_files: logger.info(f" - {os.path.basename(f)}")
            logger.info("=========================================================\n")
            logger.info("Processing monthly forcing ...")
            ref_file = next(f for f in month_files if f.endswith("_tp.nc"))
            with xr.open_dataset(ref_file) as ref_ds:
                timestamps = pd.to_datetime(ref_ds['valid_time'][:], utc=True).to_numpy()
                lat, lon = ref_ds['latitude'][:], ref_ds['longitude'][:]
            x_known, y_known, gdf = None, None, None
            single_value = lat.size * lon.size == 1
            if not single_value:
                lon2d, lat2d = np.meshgrid(lon, lat)
                gdf_known = gpd.GeoDataFrame(
                    geometry=gpd.points_from_xy(lon2d.ravel(), lat2d.ravel()), crs='EPSG:4326'
                ).to_crs(crs)
                x_known, y_known = gdf_known.geometry.x.values, gdf_known.geometry.y.values
                x, y = np.meshgrid(x_coords, y_coords)
                gdf = gpd.GeoDataFrame(geometry=gpd.points_from_xy(x.ravel(), y.ravel()), crs=crs)
                idx, weight = prepare_interpolator(gdf, x_known, y_known, geo_type="point")
            else: idx, weight = None, None
            n_time, chunk_size, overlap = len(timestamps), 24, 2        
            for var, (col, unit) in forcing.items():
                logger.info(f"Processing {var}")
                ds = ds_u = ds_v = None
                try:
                    if var == 'wind':
                        u_file = os.path.join(download_dir,f"{year}_{month:02d}_u10.nc")
                        v_file = os.path.join(download_dir,f"{year}_{month:02d}_v10.nc")
                        ds_u, ds_v = Dataset(u_file), Dataset(v_file)
                    else: ds = Dataset(os.path.join(download_dir, f"{year}_{month:02d}_{col}.nc"))
                    for start in range(0, n_time, chunk_size):
                        start_eff = max(0, start - overlap)
                        end_eff = min(n_time, start + chunk_size + overlap)
                        if var == "wind":
                            u = ds_u["u10"][start_eff:end_eff].astype(np.float32)
                            v = ds_v["v10"][start_eff:end_eff].astype(np.float32)
                            data = np.hypot(u, v)
                        else: data = ds[col][start_eff:end_eff].astype(np.float32)
                        if var == "precip": data *= 1000
                        elif var == "temp": data -= 273.15
                        elif var in ("kin", "kout"): data /= 3600
                        if np.isnan(data).any():
                            da = xr.DataArray(data, dims=("valid_time", "latitude", "longitude"))
                            da = da.interpolate_na(dim="valid_time", method="linear")
                            da = da.ffill("valid_time").bfill("valid_time")
                            da = da.fillna(0.0)
                            data = da.values.astype(np.float32)
                        # Interpolate
                        data_3d = create_forcing(data, ny, nx, mask_nan, single_value, idx, weight)
                        if data_3d is None:
                            logger.info("FAILED: No valid data found for interpolation")
                            processes[process_key] = {"status": "failed", "message": "No valid data found for interpolation."}
                        t0, t1 = start, min(start + chunk_size, n_time)
                        chunk_start = t0 - start_eff
                        chunk_end = chunk_start + (t1 - t0)
                        chunk = data_3d[chunk_start:chunk_end]
                        chunk = np.nan_to_num(chunk, nan=0.0)
                        chunk = np.where(mask_nan[None, :, :], 0.0, chunk)
                        nc_vars[var][t0:t1, :, :] = chunk
                        del data, data_3d, chunk
                        if var == "wind": del u, v
                finally:
                    if ds is not None:
                        try: ds.close()
                        except Exception: pass
                    if ds_u is not None:
                        try: ds_u.close()
                        except Exception: pass
                    if ds_v is not None:
                        try: ds_v.close()
                        except Exception: pass
            logger.info("\n")
            for i, t in enumerate(timestamps):
                time_var[time_index + i] = date2num(pd.Timestamp(t).to_pydatetime(), time_var.units, time_var.calendar)
            time_index += n_time
            # Cleanup
            gc.collect()
            for f in month_files: functions.safe_remove(f)
            # Next month
            current += relativedelta(months=1)
        nc.close()
        nc = None
        gc.collect()
        logger.info(f"Saved forcing file successfully: {forcing_path}")
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        logger.info("Temporary monthly files removed")
        logger.handlers[0].flush()
        processes[process_key] = {"status": "finished", "message": "Weather download completed successfully.\n\n\n"}
    except Exception as e:
        print('/weather_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Weather download failed")
        processes[process_key] = {"status": "failed", "message": str(e)}
    finally:
        if nc is not None:
            try:
                nc.close()
                logger.info("NetCDF file closed.")
            except Exception as e:
                logger.warning(f"Error closing NetCDF: {e}")
                processes[process_key] = {"status": "failed", "message": f"Error closing NetCDF: {e}"}
        gc.collect()
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            try:
                h.flush()
                h.close()
            except Exception: pass
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

def soil_downloader(project_name, processes, process_key, flow_name, catchment, water, dtm_path, buffer=BUFFER):
    project_dir = os.path.join(PROJECT_ROOT, project_name)
    flow_dir = os.path.join(project_dir, "flows", flow_name)
    # Work with log
    log_path = os.path.join(project_dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    try:
        logger = setup_logger("soil", log_path)
        # Download soil data 2017 from ISRIC: https://files.isric.org/soilgrids/former/2017-03-10/
        logger.info("Preparing data download...")
        soil_dir = os.path.join(flow_dir, "soil")
        if os.path.exists(soil_dir): shutil.rmtree(soil_dir)
        os.makedirs(soil_dir, exist_ok=True)
        catchment_WGS84 = catchment.copy()
        if catchment_WGS84.crs != "EPSG:4326": catchment_WGS84 = catchment_WGS84.to_crs('EPSG:4326')
        catchment_buffer = catchment_WGS84.buffer(buffer)
        min_lon, min_lat, max_lon, max_lat = catchment_buffer.total_bounds
        soil_depths = flow_functions.soil_depths
        soil_types, depths = flow_functions.soil_types, list(soil_depths.values())
        logger.info("Reading dtm data...")
        with rasterio.open(dtm_path) as src:
            nodata, profile = src.nodata, src.profile
            crs, transform = src.crs, src.transform
            height, width = src.height, src.width
        base_url = "https://files.isric.org/soilgrids/former/2017-03-10/data/"
        # Soil thickness
        logger.info("Creating soil thickness data...")
        soil_thickness_url, NODATA_SOIL_THICKNESS = f"{base_url}BDRICM_M_250m_ll.tif", -99999
        # Get raster information
        ref = rioxarray.open_rasterio(dtm_path).squeeze()
        with rioxarray.open_rasterio(soil_thickness_url) as src:
            data_xr = src.rio.clip_box(minx=min_lon, miny=min_lat, maxx=max_lon, maxy=max_lat)
            data_xr = data_xr.rio.reproject_match(ref, resampling=Resampling.nearest)
            nodata = data_xr.rio.nodata
        soil_thickness_array = data_xr[0].values
        # Interpolate data
        logger.info("Interpolating soil thickness data...")
        mask_valid = soil_thickness_array != nodata
        soil_thickness_values = flow_functions.interpolate_extrapolate(soil_thickness_array, ~mask_valid, True)
        soil_thickness_values = soil_thickness_values.astype(np.int32)
        # Clip to lake
        water_path, mask_lake = os.path.join(flow_dir, 'water_area', water), None
        if os.path.exists(water_path) and os.path.getsize(water_path) > 0:
            lake = gpd.read_file(water_path)
            lake_reproj = lake.to_crs(crs)
            lake_array = rasterize(
                shapes=[geom for geom in lake_reproj.geometry], dtype=np.float32,
                out_shape=(height, width), transform=transform, fill=nodata
            )
            mask_lake = (lake_array != nodata)
        if mask_lake is not None: soil_thickness_values[mask_lake] = NODATA_SOIL_THICKNESS
        soil_thickness_path = os.path.join(soil_dir, 'soilthickness.tif')
        profile_writer = profile.copy()
        profile_writer.update(dtype=np.int32)
        flow_functions.write_geotif(soil_thickness_values, profile_writer, soil_thickness_path, NODATA_SOIL_THICKNESS)
        logger.info(f"Saving soil thickness data to: {soil_thickness_path}")
        # Download soil data
        for _, values in soil_types.items():
            file, name, scale, dtype, nodata_soil, bulk_density = values[0], values[1], values[2], values[3], values[4], None
            for depth in depths:
                file_url = f'{base_url}{file}_{depth}_250m_ll.tif'
                logger.info(f"Downloading: {file}_{depth}_250m_ll.tif...")
                with rioxarray.open_rasterio(file_url) as src:
                    data_xr = src.rio.clip_box(minx=min_lon, miny=min_lat, maxx=max_lon, maxy=max_lat)
                    data_xr = data_xr.rio.reproject_match(ref, resampling=Resampling.nearest)
                    nodata = data_xr.rio.nodata
                soil_array = data_xr[0].values
                # Interpolate data
                mask_valid = soil_array != nodata
                logger.info(f"Interpolating {file}_{depth}_250m_ll.tif...")
                soil_values = flow_functions.interpolate_extrapolate(soil_array, ~mask_valid, True)
                if name == 'BLDFIE_M': bulk_density = soil_values + 1e-6
                if name == 'OCDENS_M':
                    # Convert Organic Carbon Density (kg/m³) to Organic Carbon Content (%)
                    soil_values = soil_values / bulk_density * 100
                soil_values = soil_values / scale
                if mask_lake is not None: soil_values[mask_lake] = nodata_soil
                path = os.path.join(soil_dir, f'{name}_{depth}.tif')
                profile_writer.update(dtype=dtype)
                flow_functions.write_geotif(soil_values, profile_writer, path, nodata_soil)
                logger.info(f"Saved downloaded data to: {path}")
        logger.handlers[0].flush()
        processes[process_key] = {"status": "finished", "message": "\nSoil data downloaded successfully.\n\n"}
    except Exception as e:
        print('/soil_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Data download failed")
        processes[process_key] = {"status": "failed", "message": str(e)}
    finally:
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

def wflow_check(project_name, processes, process_key, flow_name, uparea_km=10):
    project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
    model_dir = os.path.normpath(os.path.join(project_dir, "flows", flow_name))
    # Work with log
    log_path = os.path.normpath(os.path.join(project_dir, "log.txt"))
    if os.path.exists(log_path): os.remove(log_path)    
    try:
        logger = setup_logger("wflow", log_path)
        logger.info("Checking wflow inputs...")
        logger.info("=" * 60)
        logger.info("Checking weather forcing data...")
        forcing_path = os.path.normpath(os.path.join(model_dir, 'forcing', 'weather_forcing.nc'))
        if not os.path.exists(forcing_path):
            logger.info("Weather forcing data not found.")
            processes[process_key] = {"status": "failed", "message": "Weather forcing data not found."}
        logger.info(f"Found weather forcing data at: {forcing_path}")
        logger.info("=" * 60)
        logger.info("Checking terrain data...")
        terrain_path = os.path.normpath(os.path.join(model_dir, 'raw', 'dtm_raw.tif'))
        if not os.path.exists(terrain_path):
            logger.info("Terrain data not found.")
            processes[process_key] = {"status": "failed", "message": "Terrain data not found."}
        logger.info(f"Found terrain data at: {terrain_path}")
        logger.info("=" * 60)
        with rasterio.open(terrain_path) as src:
            dem_array, crs, nodata = src.read(1), src.crs, src.nodata
            transform, profile = src.transform, src.profile
            height, width = src.height, src.width
        logger.info("Checking water area data...")
        water_path = os.path.normpath(os.path.join(model_dir, 'water_area', 'water_area.geojson'))
        if not os.path.exists(water_path):
            mask_lake = None
            logger.info("Water area data not found.")
        else:
            lake = gpd.read_file(water_path)
            lake_reproj = lake.to_crs(crs)
            lake_array = rasterize(
                shapes=[geom for geom in lake_reproj.geometry], dtype=np.float32,
                out_shape=(height, width), transform=transform, fill=nodata
            )
            mask_lake = (lake_array != nodata)
        logger.info(f"Found water area data at: {water_path}")
        logger.info("=" * 60)
        logger.info("Checking river data...")
        river_dir = os.path.normpath(os.path.join(model_dir, 'river'))
        river_files = [f for f in os.listdir(river_dir)]
        if len(river_files) != 2:
            logger.info("Number of river files is not equal to 2.")
            processes[process_key] = {"status": "failed", "message": "Please upload river data."}
        logger.info(f"Found river data at: {river_dir}")
        logger.info("=" * 60)
        logger.info("Creating template hydro data...")
        # Prepare template raster dataset
        hydro_dir = os.path.normpath(os.path.join(model_dir, 'hydro'))
        if not os.path.exists(hydro_dir): os.makedirs(hydro_dir)
        # Fill depressions
        filled_array, flwdir_array = dem.fill_depressions(elevtn=dem_array, max_depth=-1)
        flw = pyflwdir.from_dem(filled_array, transform=transform, latlon=crs.is_geographic)
        if mask_lake is not None: filled_array[mask_lake] = dem_array[mask_lake] # Replace lake elevation
        # Create basins
        NODATA_FLWDR, NODATA_BASIN = 255, 0
        basins_array = flw.basins()
        unique, counts = np.unique(basins_array, return_counts=True)
        largest_basin_id = unique[np.argmax(counts)]
        basins_mask = (basins_array == largest_basin_id)
        basins_array[basins_mask], basins_array[~basins_mask] = 1, NODATA_BASIN
        elevtn_array = filled_array.copy()
        # Create slope
        dx, dy = transform.a, abs(transform.e)
        # Gradient elevation
        gradient_array = filled_array.copy()
        gy, gx = np.gradient(gradient_array, dy, dx)
        slope_array = np.sqrt(gx**2 + gy**2)
        # Create stream order
        uparea_array = flw.upstream_area(unit='km2')
        # Create stream mask and stream order
        stream_mask = (uparea_array >= uparea_km)
        strord_array = flw.stream_order(type='strahler', mask=stream_mask)
        # Create upstream grid
        upstream_array = flw.upstream_area(unit='cell')
        # Create river width
        river_path = os.path.normpath(os.path.join(river_dir, 'river.gpkg'))
        river = gpd.read_file(river_path).to_crs(crs)
        shape = ((geom, value) for geom, value in zip(river.geometry, river["rivwth"]))
        rivwth_array = rasterize(
            shapes=shape, out_shape=(profile["height"], profile["width"]),
            transform=transform, fill=nodata, dtype=np.float32
        )
        files_float = {
            'elevtn.tif': [elevtn_array, nodata, np.float32],
            'flwdir.tif': [flwdir_array, NODATA_FLWDR, np.uint8],
            'lndslp.tif': [slope_array, nodata, np.float32],
            'basins.tif': [basins_array, NODATA_BASIN, np.int32], 
            'uparea.tif': [uparea_array, nodata, np.float32],
            'strord.tif': [strord_array, NODATA_BASIN, np.int16],
            'upgrid.tif': [upstream_array, NODATA_BASIN, np.int32],
            'rivwth.tif': [rivwth_array, nodata, np.float32]
        }
        profile_writer = profile.copy()
        for file, array in files_float.items():
            profile_writer.update({'dtype': array[2]})
            file_path = os.path.normpath(os.path.join(hydro_dir, file))
            if not os.path.exists(file_path):
                logger.info(f"Writing data to: {file_path}")
                flow_functions.write_geotif(array[0], profile_writer, file_path, array[1])
            else: logger.info(f"File already exists: {file_path}")
        logger.info("Write hydro data completed.")
        logger.info("=" * 60)
        logger.info("Checking landcover data...")
        landcover_dir = os.path.normpath(os.path.join(model_dir, 'landcover'))
        landcover_files = [f for f in os.listdir(landcover_dir)]
        if len(landcover_files) != 3:
            logger.info("Number of landcover files is not equal to 3.")
            processes[process_key] = {"status": "failed", "message": "Please download landcover data."}
        logger.info(f"Found landcover data at: {landcover_dir}")
        logger.info("=" * 60)
        logger.info("Checking soil data...")
        soil_dir = os.path.normpath(os.path.join(model_dir, 'soil'))
        soil_files = [f for f in os.listdir(soil_dir) if f.endswith('.tif')]
        if len(soil_files) != 43:
            message = """
                *******************************************************************************
                *  NUMBER OF SOIL FILES ARE NOT EQUAL TO 43. PLEASE DOWNLOAD SOIL DATA AGAIN  *
                *******************************************************************************
            """
            logger.info(f"\n\n\n{message}\n")
            processes[process_key] = {"status": "failed", "message": "Please download soil data."}
        logger.info(f"Found soil data at: {soil_dir}")
        logger.info("=" * 60)
        logger.handlers[0].flush()
        processes[process_key] = {"status": "finished", "message": "\nChecking Wflow inputs completed.\n\n"}
    except Exception as e:
        print('/wflow_check:\n==============')
        traceback.print_exc()
        logger.exception("Check of wflow failed.")
        processes[process_key] = {"status": "failed", "message": str(e)}
    finally:
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)

def get_candidates_from_strord(strord_path, center_xy):
    with rasterio.open(strord_path) as src:
        strord, nodata = src.read(1), src.nodata
        transform, src_crs = src.transform, src.crs
    if nodata is not None: mask = (strord > 0) & (strord != nodata)
    else: mask = strord > 0
    rows, cols = np.where(mask)
    if len(rows) == 0: return []
    xs, ys = rasterio_xy(transform, rows, cols)
    xs, ys = np.array(xs), np.array(ys)
    strord_vals = strord[rows, cols]
    cx, cy = center_xy
    dist = (xs - cx)**2 + (ys - cy)**2
    order = np.argsort(dist)
    xs, ys = xs[order], ys[order]
    strord_vals = strord_vals[order]
    dist = dist[order]
    gdf = gpd.GeoDataFrame(
        {'id': np.arange(start=1, stop=len(xs)+1), 'distance_m': np.round(dist, 2)},
        geometry=[Point(x, y) for x, y in zip(xs, ys)], crs=src_crs,
    )
    return gdf

def _safe_rmtree(path, max_retries=5, delay=1.0, logger=None):
    if not os.path.exists(path): return True
    def _log(msg):
        if logger:
            try: logger.info(msg)
            except: pass
    for attempt in range(max_retries):
        try:
            gc.collect()
            try:
                from dask.distributed import get_client
                get_client().close()
            except Exception: pass
            gc.collect()
            def _on_error(func, path, exc_info):
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except Exception: pass
            shutil.rmtree(path, onerror=_on_error)
            _log(f"Deleted {path}")
            return True
        except PermissionError as e:
            _log(f"Attempt {attempt+1}/{max_retries}: {e}")
            if attempt < max_retries - 1: time.sleep(delay * (attempt + 1))
            else: return False
        except FileNotFoundError:
            return True
        except Exception as e:
            _log(f"Attempt {attempt+1}/{max_retries}: {e}")
            if attempt < max_retries - 1: time.sleep(delay)
            else: return False
    return False

def _cleanup_model(model, logger=None):
    if model is None: return
    def _log(msg):
        if logger:
            try: logger.info(msg)
            except: pass
    try:
        for attr in ("staticmaps", "forcing", "states", "geoms", "tables", "config"):
            obj = getattr(model, attr, None)
            if obj is None: continue
            if hasattr(obj, "close"):
                try: 
                    obj.close()
                    _log(f"Closed {attr}")
                except Exception as e: _log(f"Error closing {attr}: {e}")
            data = getattr(obj, "data", None)
            if data is not None and hasattr(data, "close"):
                try: 
                    data.close()
                    _log(f"Closed {attr}.data")
                except Exception as e:
                    _log(f"Error closing {attr}.data: {e}")
        try:
            dc = getattr(model, '_data_catalog', None)
            if dc is not None and hasattr(dc, "close"):
                dc.close()
        except Exception: pass
        if hasattr(model, "_datasets"):
            try:
                for ds in model._datasets.values():
                    if hasattr(ds, "close"):
                        ds.close()
            except Exception: pass
    except Exception as e:
        _log(f"Cleanup model error: {e}")
    finally:
        try:
            del model
        except Exception: pass
        gc.collect()
        try:
            from dask.distributed import get_client
            client = get_client()
            client.close()
        except Exception: pass
        gc.collect()

def _cleanup_after_failure(model_dir, model_folder, logger=None):
    def _log(msg):
        if logger:
            try: logger.info(msg)
            except: pass
    mod_path = os.path.normpath(os.path.join(model_dir, model_folder))
    try:
        from dask.distributed import get_client
        client = get_client()
        client.close()
    except Exception: pass
    for _ in range(3):
        gc.collect()
    try:
        target = os.path.normpath(mod_path).lower()
        open_files = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for f in proc.open_files():
                    if target in os.path.normpath(f.path).lower():
                        open_files.append((proc.info['pid'], proc.info['name'], f.path))
            except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        if open_files:
            _log(f"{len(open_files)} file handles still open:")
            for pid, name, path in open_files[:10]:
                _log(f"  PID {pid} ({name}): {path}")
    except ImportError: pass
    except Exception: pass

def prepare_hydromt(project_name, processes, process_key, flow_name, model_folder, 
    start, end, step, time_zone, data_lib, upstream_area, region, resolution, soil_layers, 
    params_input, params_output, log_path, lulc_function, lulc_mapping_fn, lai_fn, logger=None):
    project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
    model_dir = os.path.normpath(os.path.join(project_dir, "flows", flow_name))
    mod_path = os.path.normpath(os.path.join(model_dir, model_folder))
    if logger is None: logger = setup_logger("hydromt", log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    stream_logger = StreamToLogger(logger, log_path=log_path)
    sys.stdout, sys.stderr = stream_logger, stream_logger
    # Clean up existing model directory
    if os.path.exists(mod_path): _safe_rmtree(mod_path, logger=logger)
    os.makedirs(mod_path, exist_ok=True)
    error, model, configs = None, None, {}
    try:
        logger.info("Starting hydromt for preparation...")
        # Prepare model
        logger.info("Creating model instance...")
        model = WflowSbmModel(
            root=mod_path, config_filename='wflow_sbm.toml', data_libs=data_lib, mode='w'
        )
        start_utc = functions.local_to_utc(start, time_zone).replace(tzinfo=None)
        end_utc = functions.local_to_utc(end, time_zone).replace(tzinfo=None)
        # Setup configurations
        configs = {}
        # Setup time
        time_temp = configs.setdefault('time', {})
        time_temp['starttime'], time_temp['endtime'], time_temp['timestepsecs'] = start_utc, end_utc, step
        # Reference: https://deltares.github.io/Wflow.jl/dev/model_docs/model_settings.html
        model_temp = configs.setdefault('model', {})
        model_temp['type'] = 'sbm' # model type: [sbm, sbm_gwf]
        model_temp['cold_start__flag'] = True  # Initialize model with cold (cold_start__flag = true) or warm state
        # Unit cell length of input rasters in lat/lon degree (cell_length_in_meter__flag = false) or in meter
        model_temp['cell_length_in_meter__flag'] = False
        model_temp['reservoir__flag'] = False #Include reservoir modelling
        model_temp['water_mass_balance__flag'] = False # Include water mass balance error computations
        model_temp['snow_gravitational_transport__flag'] = True # Include gravitational lateral snow transport
        model_temp['glacier__flag'] = False # Include glacier modelling
        model_temp['soil_infiltration_reduction__flag'] = False # Enable reduction factor applied to the soil infiltration capacity
        model_temp['snow__flag'] = True # Include snow modelling
        # Saturated hydraulic conductivity depth profile for SBM soil model
        # optional, one of ("exponential", "exponential_constant", "layered", "layered_exponential"), default is "exponential"
        model_temp['saturated_hydraulic_conductivity_profile'] = 'exponential'
        model_temp['land_routing'] = 'kinematic_wave' # Routing approach for overland flow: ["kinematic_wave", "local_inertial"]
        model_temp['river_routing'] = 'kinematic_wave' # Routing approach for river flow: ["kinematic_wave", "local_inertial"]
        model_temp['river_kinematic_wave__time_step'] = 900
        model_temp['land_kinematic_wave__time_step'] = 3600
        model_temp['kinematic_wave__adaptive_time_step_flag'] = False # Enable kinematic wave adaptive (internal) time stepping
        # ========== Output variables ==========
        output_temp = model_temp.setdefault('netcdf_grid', {})
        output_temp['path'] = 'output.nc'
        output_temp['compressionlevel'] = 2
        # Source: https://deltares.github.io/Wflow.jl/previews/PR586/model_docs/parameters_routing.html
        var_temp = output_temp.setdefault('variables', {})
        # Overland flow variables
        if params_output['overland_flow']:
            var_temp['land_surface_water__volume_flow_rate'] = 'overland_flow'  # Overland discharge (average over timestep)	m³ s⁻¹
        if params_output['overland_depth']:
            var_temp['land_surface_water__depth'] = 'overland_depth'  # Overland depth (average over timestep)	m
        if params_output['overland_volume']:
            var_temp['land_surface_water__volume'] = 'overland_volume' # Overland volume (average over timestep)	m³
        # Soil variables
        if params_output['soil_evapotranspiration']:
            var_temp['land_surface__evapotranspiration_volume_flux'] = 'soil_evapotranspiration'  # Total actual evapotranspiration	mm
        if params_output['soil_storage_total']:
            var_temp['land_water~storage~total__depth'] = 'soil_storage_total'  # Total water storage (excluding floodplains, lakes and reservoirs)	mm
        if params_output['soil_infiltration_volume']:
            var_temp['soil_water__infiltration_volume_flux'] = 'soil_infiltration_volume'  # Actual infiltration into the unsaturated zone	mm Δt⁻¹
        if params_output['soil_transpiration_volume']:
            var_temp['soil_water__transpiration_volume_flux'] = 'soil_transpiration_volume'  # Transpiration from vegetation	mm Δt⁻¹
        if params_output['soil_runoff']:
            var_temp['soil_surface_water__runoff_volume_flux'] = 'soil_runoff'  # Total surface runoff from infiltration and saturation excess	mm Δt⁻¹
        if params_output['soil_net_runoff']:
            var_temp['soil_surface_water__net_runoff_volume_flux'] = 'soil_net_runoff'  # Net surface runoff (after open water evaporation)	mm Δt⁻¹
        if params_output['soil_water_volume_fraction']:
            var_temp['soil_layer_water__volume_fraction'] = 'soil_water_volume_fraction'  # Volumetric water content per soil layer (including residual water content and saturated zone)
        if params_output['soil_water_volume_percentage']:
            var_temp['soil_layer_water__volume_percentage'] = 'soil_water_volume_percentage'  # Volumetric water content per soil layer (including residual water content and saturated zone)	%
        if params_output['soil_water_rootzone_volume_fraction']:
            var_temp['soil_water_root-zone__volume_fraction'] = 'soil_water_rootzone_volume_fraction'  # Volumetric water content in root zone (including residual water content and saturated zone)
        if params_output['soil_water_rootzone_volume_percentage']:
            var_temp['soil_water_root-zone__volume_percentage'] = 'soil_water_rootzone_volume_percentage'  # Volumetric water content in root zone (including residual water content and saturated zone)	%
        if params_output['soil_water_rootzone_depth']:
            var_temp['soil_water_root-zone__depth'] = 'soil_water_rootzone_depth'  # Root water storage in unsaturated and saturated zone (excluding residual water content)	mm
        if params_output['soil_water_unsatzone_depth']:
            var_temp['soil_water_unsat-zone__depth'] = 'soil_water_unsatzone_depth'  # Amount of water in the unsaturated store	mm
        if params_output['soil_water_satzone_capillary_volume_flux']:
            var_temp['soil_water_sat-zone_top__capillary_volume_flux'] = 'soil_water_satzone_capillary_volume_flux'  # Actual capillary rise	mm Δt⁻¹
        if params_output['soil_water_satzone_recharge_volume_flux']:
            var_temp['soil_water_sat-zone_top__recharge_volume_flux'] = 'soil_water_satzone_recharge_volume_flux'  # Downward flux from unsaturated to saturated zone	mm Δt⁻¹
        if params_output['soil_water_satzone_net_recharge_volume_flux']:
            var_temp['soil_water_sat-zone_top__net_recharge_volume_flux'] = 'soil_water_satzone_net_recharge_volume_flux'  # Net recharge to saturated zone	mm Δt⁻¹
        if params_output['soil_water_satzone_leakage_volume_flux']:
            var_temp['soil_water_sat-zone_bottom__leakage_volume_flux'] = 'soil_water_satzone_leakage_volume_flux'  # Actual leakage from saturated store	mm Δt⁻¹
        if params_output['soil_water_satzone_depth']:
            var_temp['soil_water_sat-zone_top__depth'] = 'soil_water_satzone_depth'  # Pseudo-water table depth (top of the saturated zone)	mm
        # Lake variables
        if params_output['lake_volume']:
            var_temp['lake_water__volume'] = 'lake_volume' # Lake volume (average over timestep), m³
        if params_output['lake_level']:
            var_temp['lake_water_surface__elevation'] = 'lake_level' # Lake water level (average over timestep), m
        if params_output['lake_outflow']:
            var_temp['lake_water~outgoing__volume_flow_rate'] = 'lake_outflow' # Outflow of the lake (average over timestep)	m³ s⁻¹
        if params_output['lake_inflow']:
            var_temp['lake_water~incoming__volume_flow_rate'] = 'lake_inflow' # Inflow into the lake (average over timestep)	m³ s⁻¹
        if params_output['lake_evaporation']:
            var_temp['lake_water__evaporation_volume_flux'] = 'lake_evaporation' # Average actual evaporation over the lake area	mm Δt⁻¹
        if params_output['lake_precipitation']:
            var_temp['lake_water__precipitation_volume_flux'] = 'lake_precipitation' # Average precipitation over the lake area	mm Δt⁻¹
        if params_output['lake_potential_evaporation']:
            var_temp['lake_water__potential_evaporation_volume_flux'] = 'lake_potential_evaporation' # Average potential evaporation over the lake area	mm Δt⁻¹
        # Reservoir variables
        if params_output['reservoir_volume']:
            var_temp['reservoir_water__volume'] = 'reservoir_volume' # Reservoir volume (average over the timestep)	m³
        if params_output['reservoir_outflow']:
            var_temp['reservoir_water~outgoing__volume_flow_rate'] = 'reservoir_outflow' # Outflow of the reservoir (average over the timestep)	m³ s⁻¹
        if params_output['reservoir_inflow']:
            var_temp['reservoir_water~incoming__volume_flow_rate'] = 'reservoir_inflow' # Inflow into the reservoir (average over the timestep)	m³ s⁻¹
        if params_output['reservoir_evaporation']:
            var_temp['reservoir_water__evaporation_volume_flux'] = 'reservoir_evaporation' # Average actual evaporation over the reservoir area	mm Δt⁻¹
        if params_output['reservoir_precipitation']:
            var_temp['reservoir_water__precipitation_volume_flux'] = 'reservoir_precipitation' # Average precipitation over the reservoir area	mm Δt⁻¹
        if params_output['reservoir_potential_evaporation']:
            var_temp['reservoir_water__potential_evaporation_volume_flux'] = 'reservoir_potential_evaporation' # Average potential evaporation over the reservoir area	mm Δt⁻¹
        # River variables (Kinematic wave)
        if params_output['river_discharge']:
            var_temp['river_water__volume_flow_rate'] = 'river_discharge' # River discharge (average over timestep)	m³ s⁻¹
        if params_output['river_depth']:
            var_temp['river_water__depth'] = 'river_depth' # River depth (average over timestep)	m
        if params_output['river_volume']:
            var_temp['river_water__volume'] = 'river_volume' # River volume (average over timestep)	m³
        if params_output['river_lateral_inflow']:
            var_temp['river_water_inflow~lateral__volume_flow_rate'] = 'river_lateral_inflow' # Lateral inflow into the river (average over timestep)	m³ s⁻¹
        # Snow variables
        if params_output['snow_water']:
            var_temp['snowpack__leq-depth'] = 'snow_water'  # Liquid-water equivalent of snow pack (SWE)	mm
        if params_output['snow_melt']:
            var_temp['snowpack_meltwater__volume_flux'] = 'snow_melt'  # Amount of snow melt	mm Δt⁻¹
        if params_output['snow_runoff']:
            var_temp['snowpack_water__runoff_volume_flux'] = 'snow_runoff'  # Runoff from snowpack	mm Δt⁻¹
        # Glacier variables
        if params_output['glacier_melt']:
            var_temp['glacier_ice__melt_volume_flux'] = 'glacier_melt'  # Melt from the glacier	mm Δt⁻¹
        # Vegetation variables
        if params_output['vegetation_stemflow']:
            var_temp['vegetation_canopy_water__stemflow_volume_flux'] = 'vegetation_stemflow'  # Stemflow	mm Δt⁻¹
        if params_output['vegetation_throughfall']:
            var_temp['vegetation_canopy_water__throughfall_volume_flux'] = 'vegetation_throughfall'  # Throughfall	mm Δt⁻¹
        model.setup_config(configs)
        # Setup basemaps: https://deltares.github.io/hydromt_wflow/stable/api/_generated/hydromt_wflow.WflowSbmModel.setup_basemaps.html
        model.setup_basemaps(
            region=region, hydrography_fn='my_hydro', res=resolution, upscale_method='ihu' # 'ihu', 'eam', 'dmm'
        )
        # Setup rivers: https://deltares.github.io/hydromt_wflow/stable/api/_generated/hydromt_wflow.WflowSbmModel.setup_rivers.html
        output_names = {
            'river__length': 'river_length', 'river__width': 'river_width', 'river__slope': 'river_slope',
            'river_bank_water__depth': 'river_bank_depth', # Bankfull depth of river, default is 1.0 m
            'river_water_flow__manning_n_parameter': 'river_manning_n', # Manning's roughness, default is 0.036
            'river_bank_water__elevation': 'river_bank_elevation', 'river_location__mask': 'river_mask'
        }
        model.setup_rivers(
            hydrography_fn='my_hydro', river_geom_fn='river_network', 
            river_upa=upstream_area, # Minimum upstream area threshold for the river map [km2]
            rivdph_method='powlaw', # 'gvf', 'manning', 'powlaw'
            slope_len=2, #  Length over which the river slope is calculated [km]
            min_rivlen_ratio=0, min_rivdph=1.0, # Minimum river depth [m]
            min_rivwth=30, # Minimum river width [m]
            smooth_len=5000, # Length [m] over which to smooth the output river width and depth
            connectivity=8, river_routing='kinematic_wave', # 'kinematic_wave', 'local_inertial'
            elevtn_map='land_elevation', # Name of the elevation map in the current WflowBaseModel.staticmaps
            output_names=output_names
        )
        model.setup_river_roughness(
            rivman_mapping_fn='river_manning_mapping', # Name of the river manning n map in the current WflowBaseModel.river_maps
            strord_name='meta_streamorder', # Name of the stream order map in the current WflowBaseModel.staticmaps
            output_name='river_manning_n' # Mapping of output variable names.
        )
        # Setup soil maps: https://deltares.github.io/hydromt_wflow/stable/api/_generated/hydromt_wflow.WflowSbmModel.setup_soilmaps.html
        soil_names = {
            'soil__thickness': 'soil_thickness', 'soil_layer_water__brooks_corey_exponent': 'soil_brooks_corey_c',
            'soil_surface_water__vertical_saturated_hydraulic_conductivity': 'soil_ksat_vertical', 
            'soil_water__residual_volume_fraction': 'soil_theta_r', 'soil_water__saturated_volume_fraction': 'soil_theta_s', 
            'soil_water__vertical_saturated_hydraulic_conductivity_scale_parameter': 'soil_f'
        }
        model.setup_soilmaps(
            soil_fn='soilgrids', ptf_ksatver='brakensiek', # 'brakensiek', 'cosby'
            wflow_thicknesslayers=soil_layers, # Thickness of soil layers [mm] for wflow_sbm soil model
            output_names=soil_names
        )
        model.setup_laimaps_from_lulc_mapping(lulc_fn=lulc_function, lai_mapping_fn=lai_fn)
        # Setup land use maps: https://deltares.github.io/hydromt_wflow/stable/api/_generated/hydromt_wflow.WflowSbmModel.setup_lulcmaps.html
        lulc_variables = [
            'landuse', 'vegetation_kext', 'land_manning_n', 'soil_compacted_fraction', 
            'vegetation_root_depth', 'vegetation_leaf_storage', 'vegetation_wood_storage', 
            'land_water_fraction', 'vegetation_crop_factor', 'vegetation_feddes_alpha_h1', 
            'vegetation_feddes_h1', 'vegetation_feddes_h2', 'vegetation_feddes_h3_high', 
            'vegetation_feddes_h3_low', 'vegetation_feddes_h4'
        ]
        model.setup_lulcmaps(
            lulc_fn=lulc_function, lulc_mapping_fn=lulc_mapping_fn, lulc_vars=lulc_variables
        )
        # Setup forcing
        model.setup_precip_forcing(precip_fn='weather_forcing')
        model.setup_temp_pet_forcing(
            temp_pet_fn='weather_forcing', pet_method='debruin', # 'debruin', 'makkink', 'penman-monteith_rh_simple', 'penman-monteith_tdew'
            press_correction=True, temp_correction=True, wind_correction=True,
            wind_altitude=10, reproj_method='nearest', fillna_method='nearest',
            dem_forcing_fn='dtm', skip_pet=False
        )
        # === Constant parameters ===
        model.setup_constant_pars(
            subsurface_water__horizontal_to_vertical_saturated_hydraulic_conductivity_ratio = params_input['k_sat_ratio'],
            snowpack__degree_day_coefficient = params_input['dd_snow'],
            soil_surface_water__infiltration_reduction_parameter = params_input['inf_red'],
            vegetation_canopy_water__mean_evaporation_to_mean_precipitation_ratio = params_input['canopy_evap_ratio'],
            compacted_soil_surface_water__infiltration_capacity = params_input['inf_cap'],
            soil_water_saturated_zone_bottom__max_leakage_volume_flux = params_input['leak_max'],
            soil_wet_root__sigmoid_function_shape_parameter = params_input['soil_sigmoid'],
            atmosphere_air__snowfall_temperature_threshold = params_input['snowfall_t0'],
            atmosphere_air__snowfall_temperature_interval = params_input['snowfall_dt'],
            snowpack__melting_temperature_threshold = params_input['melt_t0_snow'],
            snowpack__liquid_water_holding_capacity = params_input['snow_liq_cap'],
            glacier_ice__degree_day_coefficient = params_input['dd_glacier'],
            glacier_firn_accumulation__snowpack_dry_snow_leq_depth_fraction = params_input['firn_dry_frac'],
            glacier_ice__melting_temperature_threshold = params_input['melt_t0_glacier']
        )
        # === Cold states ===
        model.setup_cold_states()
        # === Write model ===
        model.write(
            grid_filename='static_grid.nc', geoms_folder='staticgeoms', 
            forcing_filename='weather_forcing.nc', states_filename='output_state.nc'
        )
        logger.info(f"Prepare HydroMT completed.")
        logger.handlers[0].flush()
    except Exception as e:
        print('/prepare_hydromt:\n==============')
        traceback.print_exc()
        logger.exception(f"Prepare HydroMT failed: {str(e)}")
        processes[process_key] = {"status": "failed", "message": str(e)}
        error = e
    finally:
        _cleanup_model(model, logger)
        model = None
        for h in logger.handlers:
            try: h.flush()
            except Exception: pass
        sys.stdout, sys.stderr = old_stdout, old_stderr
    if error is not None: raise error

def run_hydromt(project_name, processes, process_key, flow_name, model_folder, log_path, logger=None):
    project_dir = os.path.join(PROJECT_ROOT, project_name)
    model_dir = os.path.normpath(os.path.join(project_dir, "flows", flow_name, model_folder))
    if logger is None: logger = setup_logger("hydromt", log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    stream_logger = StreamToLogger(logger, log_path=log_path)
    sys.stdout, sys.stderr = stream_logger, stream_logger
    error = None
    try:
        logger.info("Running HydroMT...")
        logger.info("=" * 36)
        wflow_path = os.path.normpath(os.path.join(WFLOW_PATH, "wflow_cli", "bin", "wflow_cli.exe"))
        toml_path = os.path.normpath(os.path.join(model_dir, "wflow_sbm.toml"))
        if not os.path.isfile(wflow_path):
            message = f"Wflow executable not found: {wflow_path}"
            logger.info("=" * 36)
            logger.info(message)
            logger.info("=" * 36)
            raise FileNotFoundError(message)
        if not os.path.isfile(toml_path):
            message = f"TOML config not found: {toml_path}"
            logger.info("=" * 36)
            logger.info(message)
            logger.info("=" * 36)
            raise FileNotFoundError(message)
        if not os.path.isdir(model_dir):
            message = f"Model dir not found: {model_dir}"
            logger.info("=" * 36)
            logger.info(message)
            logger.info("=" * 36)
            raise FileNotFoundError(message)
        cmd = [wflow_path, toml_path]
        process = subprocess.Popen(
            cmd, cwd=model_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        for line in process.stdout: 
            logger.info(line.strip())
            logger.handlers[0].flush()
        process.wait()
        logger.info("=" * 36)
        if process.returncode == 0:
            logger.info(f"Run HydroMT completed successfully.")
        else: 
            logger.info(f"Run HydroMT failed.")
            error = RuntimeError(f"wflow_cli exited with code: {process.returncode}")
        logger.info("=" * 36)
        logger.handlers[0].flush()
        if error is None: logger.info("Run HydroMT completed.")
    except Exception as e:
        print('/run_hydromt:\n==============')
        traceback.print_exc()
        logger.exception(f"Run HydroMT failed: {str(e)}")
        processes[process_key] = {"status": "failed", "message": str(e)}
        error = e
    finally:
        for h in logger.handlers[:]:
            try: h.flush()
            except Exception: pass
            h.close()
            logger.removeHandler(h)
        sys.stdout, sys.stderr = old_stdout, old_stderr
    if error is not None: raise error

def wflow_run(project_name, processes, process_key, flow_name, model_folder, df, crs,
    start, end, step, time_zone, data_lib, up_area, resolution, soil_layers,
    params_input, params_output, lulc_function, lulc_mapping_fn, lai_fn):
    project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
    model_dir = os.path.normpath(os.path.join(project_dir, "flows", flow_name))
    mod_path = os.path.normpath(os.path.join(model_dir, model_folder))
    # Set up logger
    log_path = os.path.normpath(os.path.join(project_dir, "log.txt"))
    if os.path.exists(log_path): os.remove(log_path)
    logger = setup_logger("hydromt", log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    stream_logger = StreamToLogger(logger, log_path=log_path)
    sys.stdout, sys.stderr = stream_logger, stream_logger    
    # Clean up existing model directory
    if os.path.exists(mod_path): _safe_rmtree(mod_path, logger=logger)
    os.makedirs(mod_path, exist_ok=True)
    candidate_results, success_point = [], None
    def _reset_log_file():
        try:
            for h in logger.handlers[:]:
                try:
                    h.flush()
                    h.close()
                except Exception: pass
                logger.removeHandler(h)
            if os.path.exists(log_path): os.remove(log_path)
            new_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            new_handler.setLevel(logging.INFO)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            new_handler.setFormatter(formatter)
            logger.addHandler(new_handler)
            stream_logger.update_logger(logger)
            logger.handlers[0].flush()
        except Exception: pass
    try:
        for idx, row in df.iterrows():
            temp_name, temp_lat, temp_lon = row['id'], row['lat'], row['lon']
            if idx > 0: _reset_log_file()
            logger.info("=" * 70)
            logger.info(f"Checking candidate: {temp_name} [{temp_lat}, {temp_lon}]")
            logger.info("=" * 70)
            try:
                client = get_client()
                client.close()
                del client
            except Exception: pass
            gc.collect()
            dask.config.set(scheduler='threads')
            prepare_ok = False
            try:
                gdf = gpd.GeoDataFrame(geometry=gpd.points_from_xy([temp_lon], [temp_lat]), crs='EPSG:4326')
                if gdf.crs != crs: gdf = gdf.to_crs(crs)
                x, y = round(gdf.geometry.x[0], 2), round(gdf.geometry.y[0], 2)
                region = {'subbasin': [x, y]}
                # Prepare model
                prepare_hydromt(project_name, processes, process_key, flow_name, model_folder, 
                    start, end, step, time_zone, data_lib, up_area, region, 
                    resolution, soil_layers, params_input, params_output, log_path,
                    lulc_function, lulc_mapping_fn, lai_fn, logger
                )
                prepare_ok = True
                # Check parameters
                path = os.path.normpath(os.path.join(model_dir, model_folder, "static_grid.nc"))
                if not os.path.exists(path):
                    raise FileNotFoundError(f"Static grid not found: {path}")
                nan_vars = []
                with xr.open_dataset(path) as ds:
                    for item in ds.data_vars:
                        vals = np.unique(ds[item].values)
                        if vals.size == 1 and np.isnan(vals[0]):
                            nan_vars.append(item)                
                if nan_vars:
                    raise ValueError(f"NaN values in: {nan_vars}")
                # Run model
                logger.info("=" * 70)
                run_hydromt(project_name, processes, process_key, flow_name, model_folder, log_path)
                logger.info(f"Candidate '{temp_name}' SUCCESS.")
                candidate_results.append({
                    "point": temp_name, "lat": temp_lat, "lon": temp_lon, "status": "success",
                })
                success_point = temp_name
                logger.info("=" * 70)
                logger.info(f"Model run SUCCEEDED with candidate: {temp_name} [{temp_lat}, {temp_lon}]")
                logger.info("Process completed. Stopping candidate iteration.")
                logger.info("=" * 70)
                break
            except Exception as e:
                logger.error(f"Run HydroMT failed for candidate '{temp_name}'.")
                candidate_results.append({
                    "point": temp_name, "lat": temp_lat, "lon": temp_lon,
                    "status": "failed", "error": str(e),
                })
                if not prepare_ok:
                    logger.error(f"Prepare data for hydromt failed - Skipping run_hydromt for candidate '{temp_name}'.")
                    logger.info("=" * 70)
                    logger.info("")
                _cleanup_after_failure(model_dir, model_folder, logger)
                gc.collect()
                continue
        if success_point is not None:
            processes[process_key] = {
                "status": "finished",
                "message": f"\n\nProcess completed successfully with candidate '{success_point}'.\n"
                    f"Total candidates tried: {len(candidate_results)}.",
                "success_point": success_point, "results": candidate_results,
            }
        else:
            n_failed = len(candidate_results)
            processes[process_key] = {
                "status": "finished",
                "message": f"\n\nAll {n_failed} candidates failed. No valid model could be run.",
                "results": candidate_results,
            }
    except Exception as e:
        processes[process_key] = {"status": "failed", "message": str(e)}
    finally:
        try:
            client = get_client()
            client.close()
        except Exception: pass
        gc.collect()
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
