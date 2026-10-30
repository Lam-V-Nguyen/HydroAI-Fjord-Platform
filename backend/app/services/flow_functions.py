import os, dotenv, rasterio, zipfile, rioxarray, sys, pyflwdir, re, stat, time, psutil
import logging, cdsapi, calendar, gc, shutil, traceback, subprocess, dask
import geopandas as gpd, numpy as np, pandas as pd, xarray as xr
from shapely.geometry import Polygon, MultiPolygon, box, shape
from scipy.spatial import cKDTree
from scipy.ndimage import distance_transform_edt
from netCDF4 import Dataset, date2num
from rasterio.io import MemoryFile
from rasterio.enums import Resampling
from rasterio.features import rasterize, shapes
from services import functions, flow_functions, wflow_config
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pyflwdir import dem
from config import PROJECT_ROOT, WFLOW_PATH
from dask.distributed import get_client

if "bool" not in np.__dict__: np.bool = np.bool_

dotenv.load_dotenv()
MET_url, MET_client_id = os.getenv('MET_ProstAPI_URL'), os.getenv('MET_ProstAPI_CLIENT_ID')
NVE_url, NVE_client_id = os.getenv('NVE_URL'), os.getenv('NVE_API_KEY')
NODATA_DEM, NODATA_INT, NODATA_SOIL_THICKNESS= -9999.0, 0, -99999
ISRIC_URL = "https://files.isric.org/soilgrids/former/2017-03-10/data/"

soils = [
    ['Clay', 'Sand', 'Silt', 'Bulk density', 'Soil organic carbon', 'Soil pH'],
    ['0', '5', '15', '30', '60', '100', '200']
]
soil_types = {
    'bulk density': ['BLDFIE_M', 'bd', 1000, np.float32, -9999.0, "g/cm3"],
    'clay': ['CLYPPT_M', 'clyppt', 1, np.float32, -9999.0, "%"], 
    'sand': ['SNDPPT_M', 'sndppt', 1, np.float32, -9999.0, "%"],
    'silt': ['SLTPPT_M', 'sltppt', 1, np.float32, -9999.0, "%"],  
    'organic carbon': ['ORCDRC_M', 'oc', 10, np.float32, -9999.0, "%"], 
    'pH': ['PHIHOX_M', 'ph', 10, np.float32, -9999.0, "-"]
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
    'toa_incident_solar_radiation': 'tisr', # Longwave radiation
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

def write_geotif(array, profile, output_path, nodata=NODATA_DEM, units=None):
    temp_path = output_path + ".tmp.tif"
    try:
        array[np.isnan(array)] = nodata
        array = array.astype(profile["dtype"])
        output_profile = profile.copy()
        output_profile.update({
            "driver": "GTiff", "count": 1,
            "dtype": array.dtype, "nodata": nodata
        })
        with rasterio.open(temp_path, "w", **output_profile) as dst:
            dst.write(array, 1)
            if units: dst.update_tags(units=units)
        os.replace(temp_path, output_path)
    finally:
        if os.path.exists(temp_path):
            try: functions.safe_remove(temp_path)
            except OSError: traceback.print_exc()

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
    log_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Remove old handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.flush()
        handler.close()
    # Create a new file handler
    file_handler = logging.FileHandler(
        log_path, mode="a", encoding="utf-8", delay=False
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)
    logger.info("Logger initialized: %s", log_path)
    file_handler.flush()
    return logger

def weather_downloader(project_name, flow_name, processes, process_key, api_key, start, end, time_zone, buffer=0.01):
    # Prepare forcing data from the global model ARE5
    # Source: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download
    # Remove old log
    project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
    flow_dir = os.path.normpath(os.path.join(project_dir, "flows", flow_name))
    log_path = os.path.normpath(os.path.join(project_dir, "log.txt"))
    if os.path.exists(log_path): os.remove(log_path)
    logger, CDS_url = setup_logger("cdsapi", log_path), os.getenv('CDS_URL')
    config_path = Path.home() / '.cdsapirc'
    if not config_path.exists():
        logger.info("Creating .cdsapirc ...")
        config_path.write_text(f"url: {CDS_url}\nkey: {api_key}\n", encoding='utf-8')
        logger.info(f"Created at: {config_path}")
    forcing_dir = os.path.normpath(os.path.join(flow_dir, 'forcing'))
    os.makedirs(forcing_dir, exist_ok=True)
    download_dir = os.path.normpath(os.path.join(forcing_dir, 'download'))
    if not os.path.exists(download_dir): os.makedirs(download_dir)
    forcing_path = os.path.normpath(os.path.join(forcing_dir, "weather_forcing.nc"))
    forcing = {
        'precip': ['tp', 'mm'], 'temp': ['t2m', 'degC'],
        'kin': ['ssrd', 'W/m^2'], 'kout': ['tisr', 'W/m^2'],
        'wind': ['', 'm/s'], 'press_msl': ['sp', 'hPa']
    }
    dataset, nc = 'reanalysis-era5-single-levels', None
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    start_time = functions.local_to_utc(start, time_zone).replace(tzinfo=None)
    end_time = functions.local_to_utc(end, time_zone).replace(tzinfo=None)
    if (start_time >= end_time):
        logger.info("Start time must be before end time.")
        processes[process_key] = {"status": "failed", "message": "Start time must be before end time."}
        return
    try:
        logger.info("Weather downloader started.")
        logger.info("Preparing output NetCDF...")
        raw_path = os.path.normpath(os.path.join(flow_dir, "raw", "dtm_raw.tif"))      
        with rasterio.open(raw_path) as src:
            dem_array, crs = src.read(1), src.crs
            transform, nodata = src.transform, src.nodata
            height, width = src.height, src.width
        mask_nan = np.isnan(dem_array) | (dem_array == nodata)
        mask_nan = mask_nan.astype(bool)
        ny, nx = dem_array.shape[0], dem_array.shape[1]
        catchment_path = os.path.normpath(os.path.join(flow_dir, 'catchment', "catchment.geojson"))
        if not os.path.exists(catchment_path):
            logger.info("No catchment found.")
            processes[process_key] = {"status": "failed", "message": "No catchment found. Please process terrain first."}
            return
        catchment = gpd.read_file(catchment_path)
        if catchment.crs != "EPSG:4326": catchment = catchment.to_crs("EPSG:4326")
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
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
        logger.info("Creating NetCDF file...")
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
            logger.info(f"Creating variable {var}...")
            nc_vars[var] = nc.createVariable(
                var, "f4", ("time", "y", "x"), zlib=True, complevel=4, fill_value=-9999.0,
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
                logger.info(f"Downloading {var} for {year}-{month:02d}...")
                request = {
                    'product_type': 'reanalysis', 'variable': [key],
                    'year': [str(year)], 'month': [f"{month:02d}"], 'day': days,
                    'time': [f"{h:02d}:00" for h in range(24)], 'area': area,
                    'data_format': 'netcdf', 'download_format': 'unarchived'
                }
                out_file = f"{year}_{month:02d}_{var}.nc"
                out_path = os.path.normpath(os.path.join(download_dir, out_file))
                client.retrieve(dataset, request, out_path)
                # Check valid files
                if flow_functions.is_valid_netcdf(out_path, var): files.append(out_path)
                else: bad_files.append(out_path)
                month_files.append(out_path)
            logger.info("ERA5 download completed successfully")
            # Check valid files
            logger.info(""*20)
            logger.info("Checking valid files...")
            # Filter valid files
            logger.info(f"Year: {year}, Month: {month}")
            n = len(files) + len(bad_files)
            logger.info(f"Number of valid files: {len(files)}/{n}")
            logger.info(f"Number of invalid files: {len(bad_files)}/{n}")
            if len(bad_files) > 0:
                logger.info("Bad files:")
                for f in bad_files: logger.info(f" - {os.path.basename(f)}")
            logger.info("="*20)
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
                        u_file = os.path.normpath(os.path.join(download_dir,f"{year}_{month:02d}_u10.nc"))
                        v_file = os.path.normpath(os.path.join(download_dir,f"{year}_{month:02d}_v10.nc"))
                        ds_u, ds_v = Dataset(u_file), Dataset(v_file)
                    else: ds = Dataset(os.path.normpath(os.path.join(download_dir, f"{year}_{month:02d}_{col}.nc")))
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
                        elif var == "press_msl": data /= 100
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
                            return
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
        logger.info("Temporary monthly files removed.")
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

def burn(geoms, height, width, transform):
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return None
    return rasterize([(g, 1) for g in geoms], out_shape=(height, width), 
        transform=transform, fill=0, dtype="uint8").astype(bool)

def soil_downloader(project_name:str, processes:dict, process_key:str, flow_name:str, 
    soil_source:str, water:str, dtm_path:str, catchment_path:str):
    project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
    flow_dir = os.path.normpath(os.path.join(project_dir, "flows", flow_name))
    soil_dir = os.path.normpath(os.path.join(flow_dir, "soil"))
    os.makedirs(soil_dir, exist_ok=True)
    # Work with log
    log_path = os.path.normpath(os.path.join(project_dir, "log.txt"))
    if os.path.exists(log_path): os.remove(log_path)
    logger, ref = None, None
    try:
        if os.path.exists(log_path): os.remove(log_path)
        logger = setup_logger("soil", log_path)
        # Download soil data 2017 from ISRIC: https://files.isric.org/soilgrids/former/2017-03-10/
        logger.info("Preparing data download...")
        logger.info("Reading dtm data...")
        with rasterio.open(dtm_path) as src:
            dtm = src.read(1, masked=True)
            nodata, profile = src.nodata, src.profile
            crs, transform = src.crs, src.transform
            height, width = src.height, src.width
            resolution_x, resolution_y = src.res
        if os.path.exists(catchment_path) and os.path.getsize(catchment_path) > 0:
            catchment = gpd.read_file(catchment_path)
            catchment_projected = catchment.to_crs(crs)
            buffer = max(abs(resolution_x), abs(resolution_y))
            catchment_buffer = catchment_projected.buffer(buffer)
            catch_array = rasterize(
                shapes=[geom for geom in catchment_buffer.geometry], dtype=np.uint8,
                out_shape=(height, width), transform=transform, fill=0, default_value=1
            )
        else:
            valid_mask = ~np.ma.getmaskarray(dtm)
            if nodata is None: valid_mask = np.isfinite(dtm.data)
            polygons = [
                shape(geom)
                for geom, value in shapes(
                    valid_mask.astype(np.uint8), mask=valid_mask, transform=transform
                ) if value == 1
            ]
            if not polygons:
                logger.error(f"DTM has no valid cells: {dtm_path}")
                raise ValueError(f"DTM has no valid cells: {dtm_path}")
            catchment_buffer = gpd.GeoDataFrame(geometry=[gpd.GeoSeries(polygons).union_all()], crs=crs)
            catch_array = rasterize(
                shapes=catchment_buffer.geometry, out_shape=(height, width),
                transform=transform, dtype=np.uint8, fill=0, default_value=1
            )
        mask_catchment = catch_array == 1
        catchment_buffer_wgs84 = catchment_buffer.to_crs("EPSG:4326")
        pad = 0.01
        min_lon, min_lat, max_lon, max_lat = catchment_buffer_wgs84.total_bounds
        water_path, mask_lake = os.path.normpath(os.path.join(flow_dir, 'water_area', water)), None
        if water and os.path.exists(water_path) and os.path.getsize(water_path) > 0:
            lake = gpd.read_file(water_path)
            lake_reproj = lake.to_crs(crs)
            lake_array = rasterize(
                shapes=[geom for geom in lake_reproj.geometry], dtype=np.uint8,
                out_shape=(height, width), transform=transform, fill=0, default_value=1
            )
            mask_lake = lake_array == 1
        def read_isric(url):
            with rioxarray.open_rasterio(url) as src:
                data_xr = src.rio.clip_box(minx=min_lon-pad, miny=min_lat-pad,
                                           maxx=max_lon+pad, maxy=max_lat+pad)
                data_xr = data_xr.rio.reproject_match(ref, resampling=Resampling.nearest)
                isric_nodata = data_xr.rio.nodata
                data_xr = data_xr.load()
            arr = data_xr[0].values.astype(np.float64)
            valid = np.isfinite(arr)
            if isric_nodata is not None: valid &= arr != isric_nodata
            if not valid.any():
                logger.error(f"No valid ISRIC data in area: {url}")
                raise ValueError(f"No valid ISRIC data in area: {url}")
            return arr, valid
        if soil_source == "isric":
            soil_depths = flow_functions.soil_depths
            soil_types, depths = flow_functions.soil_types, list(soil_depths.values())
            # Get raster information
            ref = rioxarray.open_rasterio(dtm_path).squeeze()
            # Soil thickness
            logger.info("Creating soil thickness data...")
            soil_thickness_url = f"{ISRIC_URL}BDRICM_M_250m_ll.tif"
            soil_thickness_array, mask_valid = read_isric(soil_thickness_url)
            # Interpolate data
            logger.info("Interpolating soil thickness data...")
            soil_thickness_values = flow_functions.interpolate_extrapolate(soil_thickness_array, ~mask_valid, True)
            soil_thickness_values = np.where(np.isfinite(soil_thickness_values), soil_thickness_values, NODATA_SOIL_THICKNESS)
            soil_thickness_values = soil_thickness_values.astype(np.int32)
            # Clip to catchment & lake
            soil_thickness_values[~mask_catchment] = NODATA_SOIL_THICKNESS
            if mask_lake is not None: soil_thickness_values[mask_lake] = NODATA_SOIL_THICKNESS
            soil_thickness_path = os.path.normpath(os.path.join(soil_dir, 'soilthickness.tif'))
            profile_writer = profile.copy()
            profile_writer.update(dtype=np.int32)
            flow_functions.write_geotif(soil_thickness_values, profile_writer, soil_thickness_path, NODATA_SOIL_THICKNESS, 'cm')
            logger.info(f"Saving soil thickness data to: {soil_thickness_path}")
            # Download soil data
            for _, values in soil_types.items():
                file, name, scale, dtype, nodata_soil, unit = values[0], values[1], values[2], values[3], values[4], values[5]
                for depth in depths:
                    file_url = f'{ISRIC_URL}{file}_{depth}_250m_ll.tif'
                    logger.info(f"Downloading: {file}_{depth}_250m_ll.tif...")
                    soil_array, mask_valid = read_isric(file_url)
                    # Interpolate data
                    logger.info(f"Interpolating {file}_{depth}_250m_ll.tif...")
                    soil_values = flow_functions.interpolate_extrapolate(soil_array, ~mask_valid, True)
                    soil_values = soil_values / scale
                    soil_values = np.where(np.isfinite(soil_values), soil_values, nodata_soil)
                    if mask_lake is not None: soil_values[mask_lake] = nodata_soil
                    soil_values[~mask_catchment] = nodata_soil
                    path = os.path.normpath(os.path.join(soil_dir, f'{name}_{depth}.tif'))
                    profile_writer.update(dtype=dtype)
                    flow_functions.write_geotif(soil_values, profile_writer, path, nodata_soil, unit)
                    logger.info(f"Saved downloaded data to: {path}")
        else:
            logger.error(f"Unsupported soil_source: {soil_source}")
            raise ValueError(f"Unsupported soil_source: {soil_source}")
        logger.handlers[0].flush()
        processes[process_key] = {"status": "finished", "message": "\nSoil data downloaded successfully.\n\n"}
    except Exception as e:
        print('/soil_downloader:\n==============')
        traceback.print_exc()
        if logger: logger.exception("Data download failed.")
        processes[process_key] = {"status": "failed", "message": str(e)}
    finally:
        if ref is not None:
            try: ref.close()
            except Exception: pass
        if logger:
            for h in logger.handlers[:]:
                try:
                    h.flush()
                    h.close()
                finally: logger.removeHandler(h)

def water_masks(water_path, crs, transform, shape, mode="sea", logger=None):
    """mode: 'none', 'sea', 'all'"""
    if not water_path or not os.path.isfile(water_path): return None, None
    water = gpd.read_file(water_path)
    water = water[water.geometry.notna() & ~water.geometry.is_empty]
    if water.empty: return None, None
    water = water.to_crs(crs)
    water["geometry"] = water.geometry.make_valid()
    height, width = shape
    def _burn(gdf):
        if gdf.empty: return None
        return rasterize(((g, 1) for g in gdf.geometry), out_shape=shape, 
            transform=transform, fill=0, dtype="uint8").astype(bool)
    if mode == "none": return None, _burn(water)
    if mode == "all": return _burn(water), None
    left, top = transform.c, transform.f
    right, bottom = left + width * transform.a, top + height * transform.e
    edge = box(left, min(top, bottom), right, max(top, bottom)).exterior.buffer(abs(transform.a))
    touches = water.intersects(edge)
    if logger: logger.info(f"Water polygons: {int(touches.sum())} open water (excluded), "
        f"{int((~touches).sum())} inland lakes (kept).")
    return _burn(water[touches]), _burn(water[~touches])

def hydro_creator(directory:str, dem_path:str, area_km2:float, logger:logging.Logger, 
    river_path:str, water_path:str, water_mode:str="sea"):
    with rasterio.open(dem_path) as src:
        dem_array = src.read(1)
        crs, nodata = src.crs, src.nodata
        transform, profile = src.transform, src.profile
        height, width = src.height, src.width

    if nodata is None: nodata = -9999.0
    dem_array[np.isnan(dem_array)] = nodata
    mask_exclude, mask_lake = water_masks(water_path, crs, transform, (height, width), water_mode, logger)
    if mask_exclude is not None:
        logger.info(f"Excluding {int(mask_exclude.sum())} water cells from the model domain...")
        dem_array[mask_exclude] = nodata
        if not np.any(dem_array != nodata):
            raise ValueError("No land cells left after masking water area.")
    logger.info("Filling depressions...")
    filled_array, flwdir_array = dem.fill_depressions(elevtn=dem_array, max_depth=-1, nodata=nodata)
    logger.info("Creating flow directions...")
    flw = pyflwdir.from_dem(filled_array, transform=transform, latlon=crs.is_geographic, nodata=nodata)
    NODATA_FLWDR, NODATA_BASIN = 255, 0
    # Create basins
    logger.info("Creating basins...")
    basins_array = flw.basins()
    unique, counts = np.unique(basins_array, return_counts=True)
    largest_basin_id = unique[np.argmax(counts)]
    basins_mask = (basins_array == largest_basin_id)
    basins_array[basins_mask], basins_array[~basins_mask] = 1, NODATA_BASIN
    logger.info("Creating elevation profile...")
    elevtn_array = filled_array.copy()
    # Create slope
    logger.info("Creating slope...")
    dx, dy = transform.a, abs(transform.e)
    valid = filled_array != nodata
    if (~valid).any():
        idx = distance_transform_edt(~valid, return_distances=False, return_indices=True)
        grad_src = filled_array[tuple(idx)]
    else: grad_src = filled_array
    # Gradient elevation
    gy, gx = np.gradient(grad_src, dy, dx)
    slope_array = np.sqrt(gx**2 + gy**2).astype(np.float32)
    slope_array[~valid] = nodata
    # Create stream order
    logger.info("Creating stream order...")
    uparea_array = flw.upstream_area(unit='km2')
    # Create stream mask and stream order
    stream_mask = (uparea_array >= area_km2)
    strord_array = flw.stream_order(type='strahler', mask=stream_mask)
    # Create upstream grid
    logger.info("Creating upstream grid...")
    upstream_array = flw.upstream_area(unit='cell')
    # Create river width
    logger.info("Creating river width...")
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
        file_path = os.path.normpath(os.path.join(directory, file))
        logger.info(f"Creating data: {file_path}")
        logger.info(f"Writing data to: {file_path}")
        flow_functions.write_geotif(array[0], profile_writer, file_path, array[1])

def wflow_check(project_name:str, processes:dict, process_key:str, flow_name:str, area:float=10, water_mode:str="sea"):
    project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
    model_dir = os.path.normpath(os.path.join(project_dir, "flows", flow_name))
    # Work with log
    log_path = os.path.normpath(os.path.join(project_dir, "log.txt"))
    if os.path.exists(log_path): os.remove(log_path)
    try:
        logger = setup_logger("wflow", log_path)
        logger.info("Checking wflow inputs...")
        logger.info("="*60)
        logger.info("Checking weather forcing data...")
        forcing_path = os.path.normpath(os.path.join(model_dir, 'forcing', 'weather_forcing.nc'))
        if not os.path.exists(forcing_path):
            logger.info("Weather forcing data not found.")
            processes[process_key] = {"status": "failed", "message": "Weather forcing data not found."}
            return
        logger.info(f"Found weather forcing data at: {forcing_path}")
        logger.info("="*60)
        logger.info("Checking terrain data...")
        terrain_path = os.path.normpath(os.path.join(model_dir, 'raw', 'dtm_raw.tif'))
        if not os.path.exists(terrain_path):
            logger.info("Terrain data not found.")
            processes[process_key] = {"status": "failed", "message": "Terrain data not found."}
            return
        logger.info(f"Found terrain data at: {terrain_path}")
        logger.info("="*60)
        logger.info("Checking water area data...")
        water_dir = os.path.join(model_dir, 'water_area')
        water_files = [f for f in os.listdir(water_dir) if f.endswith(".geojson")] if os.path.isdir(water_dir) else []
        if len(water_files) == 0:
            logger.warning("Water area data not found. Water area will not be masked.")
            water_path = None
        else:
            water_path = os.path.normpath(os.path.join(water_dir, water_files[0]))
            logger.info(f"Found water area data at: {water_path}")
        logger.info("="*60)
        logger.info("Checking river data...")
        river_dir = os.path.normpath(os.path.join(model_dir, 'river'))
        river_files = [f for f in os.listdir(river_dir)]
        if len(river_files) != 2:
            logger.info("Number of river files is not equal to 2.")
            processes[process_key] = {"status": "failed", "message": "Please upload river data."}
            return
        river_path = os.path.normpath(os.path.join(river_dir, 'river.gpkg'))
        logger.info(f"Found river data at: {river_dir}")
        logger.info("="*60)
        logger.info("Checking template hydro data...")
        # Prepare template raster dataset
        hydro_dir = os.path.normpath(os.path.join(model_dir, 'hydro'))
        if os.path.exists(hydro_dir):
            logger.info(f"Deleting hydro data at: {hydro_dir}")
            shutil.rmtree(hydro_dir)
        os.makedirs(hydro_dir, exist_ok=True)
        logger.info(f"Creating template hydro data at: {hydro_dir}")
        hydro_creator(hydro_dir, terrain_path, area, logger, river_path, water_path, water_mode)
        logger.info("Write hydro data completed.")
        logger.info("=" * 60)
        logger.info("Checking landcover data...")
        landcover_dir = os.path.normpath(os.path.join(model_dir, 'landcover'))
        landcover_files = [f for f in os.listdir(landcover_dir)]
        if len(landcover_files) != 3:
            logger.info("Number of landcover files is not equal to 3.")
            processes[process_key] = {"status": "failed", "message": "Please download landcover data."}
            return
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
            return
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

def prepare_hydromt(project_name, flow_name, model_folder, start, end, step, time_zone, data_lib, 
    region, uparea, resolution, soil_layers, params_input, params_output, log_path, 
    lulc_function, lulc_mapping_fn, lai_fn, logger=None):
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
    error, model, configs, dropped = None, None, {}, {}
    try:
        logger.info("Starting hydromt for preparation...")
        # Prepare model
        logger.info("Creating model instance...")
        model = wflow_config.model_init(mod_path, data_lib)
        # Setup configurations
        configs = {}
        # Setup time
        logger.info(f"Model time configuration.")
        configs['time'] = wflow_config.model_time(start, end, step, time_zone)
        logger.info(f"Model Settings.")
        configs['model'] = wflow_config.model_setting(step)
        # ========== Output variables ==========
        logger.info(f"Setup outputs configuration.")
        configs['dir_output'] = 'run_default'
        model.setup_config(configs)
        # Setup base map
        logger.info(f"Setup basemaps configuration.")
        model = wflow_config.model_basemap(model, region, resolution)
        # Setup rivers
        logger.info(f"Setup river configuration.")
        model = wflow_config.model_river(model, uparea)
        # Setup soil maps
        logger.info(f"Setup soil configuration.")
        model = wflow_config.model_soil(model, soil_layers)
        # Setup land use
        logger.info(f"Setup land use configuration.")
        model = wflow_config.model_landuse(model, lulc_function, lulc_mapping_fn, lai_fn)
        # Setup forcing
        logger.info(f"Setup weather forcing.")
        model = wflow_config.model_forcing(model)
        # === Constant parameters ===
        logger.info(f"Setup constant parameters.")
        model = wflow_config.model_constant_pars(model, params_input)
        # === Cold states ===
        logger.info(f"Setup cold states.")
        model.setup_cold_states()
        # === Remove invalid values ===
        wflow_config.sanitize_model(model, logger)
        # === Write model ===
        logger.info(f"Model writer configurations.")
        dropped = wflow_config.model_writer(model, configs, params_output, logger)
        if dropped: logger.warning(f"{len(dropped)} selected output(s) were skipped: {sorted(dropped)}")
        logger.info(f"Validating model 'wflow_sbm.toml'.")
        toml_path = os.path.join(mod_path, 'wflow_sbm.toml')
        wflow_config.model_validate_config(toml_path, logger)
        logger.info(f"Prepare HydroMT completed.")
        logger.handlers[0].flush()
    except Exception as e:
        print('/prepare_hydromt:\n==============')
        traceback.print_exc()
        logger.exception("Prepare HydroMT failed: %s", e)
        error = e
    finally:
        _cleanup_model(model, logger)
        model = None
        for h in logger.handlers:
            try: h.flush()
            except Exception: pass
        sys.stdout, sys.stderr = old_stdout, old_stderr
    if error is not None: raise error
    return dropped

def run_hydromt(project_name: str, flow_name:str, model_folder:str, log_path:str, logger=None):
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
    except Exception as e:
        print('/run_hydromt:\n==============')
        traceback.print_exc()
        logger.exception("Prepare HydroMT failed: %s", e)
        error = e
    finally:
        for h in logger.handlers[:]:
            try: h.flush()
            except Exception: pass
            h.close()
            logger.removeHandler(h)
        sys.stdout, sys.stderr = old_stdout, old_stderr
    if error is not None: raise error

def wflow_run(project_name:str, processes:dict, process_key:str, flow_name:str, model_folder:str, df:pd.DataFrame, 
    crs:str, start:str, end:str, step:int, time_zone:str, data_lib:list, resolution:int, soil_layers:list, 
    params_input:dict, params_output:dict, lulc_function:str, lulc_mapping_fn:str, lai_fn:str, uparea:float=10.0):
    # lulc_function, lulc_mapping_fn, lai_fn = 'esa_worldcover', 'esa_worldcover_mapping', 'lai_esa'
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
            logger.info("="*70)
            logger.info(f"Checking candidate: {temp_name} [{temp_lat}, {temp_lon}]")
            logger.info("="*70)
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
                x, y = round(gdf.geometry.x[0], 1), round(gdf.geometry.y[0], 1)
                # https://deltares.github.io/hydromt/v0.8.0/_generated/hydromt.workflows.basin_mask.parse_region.html
                region = {'subbasin': [x, y], 'uparea': uparea}
                # Prepare model
                dropped = prepare_hydromt(project_name, flow_name, model_folder, 
                    start, end, step, time_zone, data_lib, region, uparea,
                    resolution, soil_layers, params_input, params_output, log_path,
                    lulc_function, lulc_mapping_fn, lai_fn, logger
                )
                if dropped: processes[process_key] = {"status": "failed", "message": dropped}
                prepare_ok = True
                # Check parameters
                path = os.path.normpath(os.path.join(model_dir, model_folder, "static_grid.nc"))
                if not os.path.exists(path): raise FileNotFoundError(f"Static grid not found: {path}")
                nan_vars = []
                with xr.open_dataset(path) as ds:
                    for item in ds.data_vars:
                        vals = np.unique(ds[item].values)
                        if vals.size == 1 and np.isnan(vals[0]):
                            nan_vars.append(item)                
                if nan_vars: raise ValueError(f"NaN values in: {nan_vars}")
                # Run model
                logger.info("="*70)
                run_hydromt(project_name, flow_name, model_folder, log_path)
                logger.info(f"Candidate '{temp_name}' SUCCESS.")
                candidate_results.append({"point": temp_name, "lat": temp_lat, "lon": temp_lon, "status": "success"})
                success_point = temp_name
                logger.info("="*70)
                logger.info(f"Model run SUCCEEDED with candidate: {temp_name} [{temp_lat}, {temp_lon}]")
                logger.info("Process completed. Stopping candidate iteration.")
                logger.info("="*70)
                break
            except Exception as e:
                logger.exception("Run HydroMT failed for candidate '%s'.",temp_name )
                candidate_results.append({
                    "point": temp_name, "lat": temp_lat, "lon": temp_lon,
                    "status": "failed", "error": str(e), "traceback": traceback.format_exc()
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
            last_error = (
                candidate_results[-1].get("error", "Unknown error") if candidate_results else "No candidate was processed."
            )
            processes[process_key] = {
                "status": "failed", "message": (
                    f"All {n_failed} candidates failed. No valid model could be run.\n"f"Last error: {last_error}"
                ), "results": candidate_results,
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
