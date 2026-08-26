import os, dotenv, rasterio, zipfile, rioxarray, sys, pyflwdir
import logging, cdsapi, calendar, gc, shutil, traceback, subprocess
import geopandas as gpd, numpy as np, pandas as pd, xarray as xr
from shapely.geometry import Polygon, MultiPolygon
from scipy.spatial import cKDTree
from netCDF4 import Dataset, date2num
from rasterio.io import MemoryFile
from rasterio.enums import Resampling
from rasterio.features import rasterize
from services import functions, flow_functions
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
from hydromt_wflow import WflowSbmModel
from pyflwdir import dem
from config import PROJECT_ROOT, WFLOW_PATH

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

class StreamToLogger:
    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level
    def write(self, buf):
        if not buf: return
        for line in buf.rstrip().splitlines():
            self.logger.log(self.level, line.rstrip())
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
            # IDW
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
        np.column_stack(
            [gdf_known.geometry.x, gdf_known.geometry.y]
        )
    )
    dists, idx = tree.query(
        np.column_stack(
            [gdf_points.geometry.x, gdf_points.geometry.y]
        ), k=n_neighbors,
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
        data = np.broadcast_to(
            values[:, None, None], (nt, ny, nx),
        ).astype(np.float32)
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
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    return logger

def weather_downloader(project_name, processes, flow_name, start, end, catchment, buffer=BUFFER):
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
    # Setup variables
    variables = {
        'total_precipitation': 'tp', # Precipitation
        '2m_temperature': 't2m', # Temperature
        '10m_u_component_of_wind': 'u10', '10m_v_component_of_wind': 'v10', # Wind
        'surface_pressure': 'sp',  # Pressure
        'surface_solar_radiation_downwards': 'ssrd', # Shortwave radiation
        'surface_thermal_radiation_downwards': 'strd', # Longwave radiation
    }
    forcing_path = os.path.join(forcing_dir, "weather_forcing.nc")
    if os.path.exists(forcing_path): functions.safe_remove(forcing_path)
    forcing = {
        'precip': ['tp', 'mm'], 'temp': ['t2m', 'degC'],
        'kin': ['ssrd', 'W/m^2'], 'kout': ['strd', 'W/m^2'],
        'wind': ['', 'm/s'], 'press_msl': ['sp', 'Pa']
    }
    dataset = 'reanalysis-era5-single-levels'
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    try:
        logger.info("Weather downloader started")
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
        start_time = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(end, '%Y-%m-%d %H:%M:%S')
        lon_min, lat_min, lon_max, lat_max = catchment.total_bounds
        north, east = max(lat_min, lat_max), max(lon_min, lon_max)
        south, west = min(lat_min, lat_max), min(lon_min, lon_max)
        area = [north + buffer, west - buffer, south - buffer, east + buffer]
        logger.info(f"Bounding box: {area}")
        if os.path.exists(forcing_path):
            functions.safe_remove(forcing_path)
            logger.info("Removing old forcing data...")
        start_time = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(end, '%Y-%m-%d %H:%M:%S')
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
                timestamps = pd.to_datetime(ref_ds['valid_time'][:]).to_numpy()
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
            n_time, chunk_size, overlap = len(timestamps), 24, 2        
            for var, (col, unit) in forcing.items():
                logger.info(f"Processing {var}")
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
                        processes[project_name] = {"status": "failed", "message": "No valid data found for interpolation."}
                    t0, t1 = start, min(start + chunk_size, n_time)
                    chunk_start = t0 - start_eff
                    chunk_end = chunk_start + (t1 - t0)
                    chunk = data_3d[chunk_start:chunk_end]
                    chunk = np.nan_to_num(chunk, nan=0.0)
                    chunk = np.where(mask_nan[None, :, :], 0.0, chunk)
                    nc_vars[var][t0:t1, :, :] = chunk
                    del data, data_3d, chunk
                    if var == "wind": del u, v
                if var == "wind":
                    ds_u.close()
                    ds_v.close()
                else: ds.close()
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
        logger.info(f"Saved forcing file successfully: {forcing_path}")
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        logger.info("Temporary monthly files removed")
        logger.handlers[0].flush()
        processes[project_name] = {"status": "finished", "message": "Weather download completed successfully.\n\n\n"}
    except Exception as e:
        print('/weather_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Weather download failed")
        processes[project_name] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

def soil_downloader(project_name, processes, flow_name, catchment, water, dtm_path, buffer=BUFFER):
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
        processes[project_name] = {"status": "finished", "message": "\nSoil data downloaded successfully.\n\n"}
    except Exception as e:
        print('/soil_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Data download failed")
        processes[project_name] = {"status": "failed", "message": str(e)}
    finally:
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

def wflow_check(project_name, processes, flow_name, uparea_km=10):
    project_dir = os.path.join(PROJECT_ROOT, project_name)
    flow_dir = os.path.join(project_dir, "flows", flow_name)
    # Work with log
    log_path = os.path.join(project_dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)    
    try:
        logger = setup_logger("wflow", log_path)
        logger.info("Checking wflow inputs...")
        logger.info("===============================")
        logger.info("Checking weather forcing data...")
        forcing_path = os.path.join(flow_dir, 'forcing', 'weather_forcing.nc')
        if not os.path.exists(forcing_path):
            logger.info("Weather forcing data not found.")
            processes[project_name] = {"status": "failed", "message": "Weather forcing data not found."}
        logger.info(f"Found weather forcing data at: {forcing_path}")
        logger.info("===============================")
        logger.info("Checking terrain data...")
        terrain_path = os.path.join(flow_dir, 'raw', 'dtm_raw.tif')
        if not os.path.exists(terrain_path):
            logger.info("Terrain data not found.")
            processes[project_name] = {"status": "failed", "message": "Terrain data not found."}
        logger.info(f"Found terrain data at: {terrain_path}")
        logger.info("===============================")
        with rasterio.open(terrain_path) as src:
            dem_array, crs, nodata = src.read(1), src.crs, src.nodata
            transform, profile = src.transform, src.profile
            height, width = src.height, src.width
        logger.info("Checking water area data...")
        water_path = os.path.join(flow_dir, 'water_area', 'water_area.geojson')
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
        logger.info("===============================")
        logger.info("Checking river data...")
        river_dir = os.path.join(flow_dir, 'river')
        river_files = [f for f in os.listdir(river_dir)]
        if len(river_files) != 2:
            logger.info("Number of river files is not equal to 2.")
            processes[project_name] = {"status": "failed", "message": "Please upload river data."}
        logger.info(f"Found river data at: {river_dir}")
        logger.info("===============================")
        logger.info("Creating template hydro data...")
        # Prepare template raster dataset
        hydro_dir = os.path.join(flow_dir, 'hydro')
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
        river_path = os.path.join(river_dir, 'river.gpkg')
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
        logger.info("===============================")
        logger.info("Checking landcover data...")
        landcover_dir = os.path.join(flow_dir, 'landcover')
        landcover_files = [f for f in os.listdir(landcover_dir)]
        if len(landcover_files) != 3:
            logger.info("Number of landcover files is not equal to 3.")
            processes[project_name] = {"status": "failed", "message": "Please download landcover data."}
        logger.info(f"Found landcover data at: {landcover_dir}")
        logger.info("===============================")
        logger.info("Checking soil data...")
        soil_dir = os.path.join(flow_dir, 'soil')
        soil_files = [f for f in os.listdir(soil_dir)]
        if len(soil_files) != 43:
            logger.info("Number of soil files is not equal to 43.")
            processes[project_name] = {"status": "failed", "message": "Please download soil data."}
        logger.info(f"Found soil data at: {soil_dir}")
        logger.info("===============================")
        logger.handlers[0].flush()
        processes[project_name] = {"status": "finished", "message": "\nChecking Wflow inputs completed.\n\n"}
    except Exception as e:
        print('/wflow_check:\n==============')
        traceback.print_exc()
        logger.exception("Check of wflow failed")
        processes[project_name] = {"status": "failed", "message": str(e)}
    finally:
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

def prepare_hydromt(project_name, processes, flow_name, model_name, start, end, step, data_lib, region, resolution,
    soil_layers, params_input, params_output, lulc_function='corine', lulc_mapping_fn='corine_mapping', lai_fn='lai_corine'):
    project_dir = os.path.join(PROJECT_ROOT, project_name)
    flow_dir = os.path.join(project_dir, "flows", flow_name)
    mod_path = os.path.join(flow_dir, model_name)
    if os.path.exists(mod_path): shutil.rmtree(mod_path)
    os.makedirs(mod_path)
    # Set up logger
    log_path = os.path.join(project_dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    logger = setup_logger("hydromt", log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    try:
        logger.info("Starting hydromt...")
        # Prepare model
        if os.path.exists(mod_path): shutil.rmtree(mod_path)
        os.makedirs(mod_path, exist_ok=True)
        model = WflowSbmModel(
            root=mod_path, config_filename='wflow_sbm.toml', data_libs=data_lib, mode='w'
        )
        # Setup configurations
        configs = {
            "time.starttime": datetime.strptime(start, "%Y-%m-%d %H:%M:%S").isoformat(), 
            "time.endtime": datetime.strptime(end, "%Y-%m-%d %H:%M:%S").isoformat(), 
            "time.timestepsecs": step,
            # Reference: https://deltares.github.io/Wflow.jl/dev/model_docs/model_settings.html
            'model.type': 'sbm', # model type: [sbm, sbm_gwf]
            'model.cold_start__flag': True,  # Initialize model with cold (cold_start__flag = true) or warm state
            # Unit cell length of input rasters in lat/lon degree (cell_length_in_meter__flag = false) or in meter
            'model.cell_length_in_meter__flag': False, 'model.reservoir__flag': False, #Include reservoir modelling
            'model.water_mass_balance__flag': False, # Include water mass balance error computations
            'model.snow_gravitational_transport__flag': True, # Include gravitational lateral snow transport
            'model.glacier__flag': False, # Include glacier modelling
            'model.soil_infiltration_reduction__flag': False, # Enable reduction factor applied to the soil infiltration capacity
            'model.snow__flag': True, # Include snow modelling
            # Saturated hydraulic conductivity depth profile for SBM soil model
            # optional, one of ("exponential", "exponential_constant", "layered", "layered_exponential"), default is "exponential"
            'model.saturated_hydraulic_conductivity_profile': 'exponential',
            'model.land_routing': 'kinematic_wave', # Routing approach for overland flow: ["kinematic_wave", "local_inertial"]
            'model.river_routing': 'kinematic_wave', # Routing approach for river flow: ["kinematic_wave", "local_inertial"]
            'model.river_kinematic_wave__time_step': 900, 'model.land_kinematic_wave__time_step': 3600,
            'model.kinematic_wave__adaptive_time_step_flag': False, # Enable kinematic wave adaptive (internal) time stepping
            'output.netcdf_grid.path': 'output.nc', 'output.netcdf_grid.compressionlevel': 2,
        }
        # ========== Output variables ==========
        # Source: https://deltares.github.io/Wflow.jl/previews/PR586/model_docs/parameters_routing.html
        # Overland flow variables
        if params_output['overland_flow']:
            configs['output.netcdf_grid.variables.land_surface_water__volume_flow_rate'] = 'overland_flow'  # Overland discharge (average over timestep)	m³ s⁻¹
        if params_output['overland_depth']:
            configs['output.netcdf_grid.variables.land_surface_water__depth'] = 'overland_depth'  # Overland depth (average over timestep)	m
        if params_output['overland_volume']:
            configs['output.netcdf_grid.variables.land_surface_water__volume'] = 'overland_volume', # Overland volume (average over timestep)	m³
        # Soil variables
        if params_output['soil_evapotranspiration']:
            configs['output.netcdf_grid.variables.land_surface__evapotranspiration_volume_flux'] = 'soil_evapotranspiration',  # Total actual evapotranspiration	mm
        if params_output['soil_storage_total']:
            configs['output.netcdf_grid.variables.land_water~storage~total__depth'] = 'soil_storage_total',  # Total water storage (excluding floodplains, lakes and reservoirs)	mm
        if params_output['soil_infiltration_volume']:
            configs['output.netcdf_grid.variables.soil_water__infiltration_volume_flux'] = 'soil_infiltration_volume',  # Actual infiltration into the unsaturated zone	mm Δt⁻¹
        if params_output['soil_transpiration_volume']:
            configs['output.netcdf_grid.variables.soil_water__transpiration_volume_flux'] = 'soil_transpiration_volume',  # Transpiration from vegetation	mm Δt⁻¹
        if params_output['soil_runoff']:
            configs['output.netcdf_grid.variables.soil_surface_water__runoff_volume_flux'] = 'soil_runoff',  # Total surface runoff from infiltration and saturation excess	mm Δt⁻¹
        if params_output['soil_net_runoff']:
            configs['output.netcdf_grid.variables.soil_surface_water__net_runoff_volume_flux'] = 'soil_net_runoff',  # Net surface runoff (after open water evaporation)	mm Δt⁻¹
        if params_output['soil_water_volume_fraction']:
            configs['output.netcdf_grid.variables.soil_layer_water__volume_fraction'] = 'soil_water_volume_fraction',  # Volumetric water content per soil layer (including residual water content and saturated zone)
        if params_output['soil_water_volume_percentage']:
            configs['output.netcdf_grid.variables.soil_layer_water__volume_percentage'] = 'soil_water_volume_percentage',  # Volumetric water content per soil layer (including residual water content and saturated zone)	%
        if params_output['soil_water_rootzone_volume_fraction']:
            configs['output.netcdf_grid.variables.soil_water_root-zone__volume_fraction'] = 'soil_water_rootzone_volume_fraction',  # Volumetric water content in root zone (including residual water content and saturated zone)
        if params_output['soil_water_rootzone_volume_percentage']:
            configs['output.netcdf_grid.variables.soil_water_root-zone__volume_percentage'] = 'soil_water_rootzone_volume_percentage',  # Volumetric water content in root zone (including residual water content and saturated zone)	%
        if params_output['soil_water_rootzone_depth']:
            configs['output.netcdf_grid.variables.soil_water_root-zone__depth'] = 'soil_water_rootzone_depth',  # Root water storage in unsaturated and saturated zone (excluding residual water content)	mm
        if params_output['soil_water_unsatzone_depth']:
            configs['output.netcdf_grid.variables.soil_water_unsat-zone__depth'] = 'soil_water_unsatzone_depth',  # Amount of water in the unsaturated store	mm
        if params_output['soil_water_satzone_capillary_volume_flux']:
            configs['output.netcdf_grid.variables.soil_water_sat-zone_top__capillary_volume_flux'] = 'soil_water_satzone_capillary_volume_flux',  # Actual capillary rise	mm Δt⁻¹
        if params_output['soil_water_satzone_recharge_volume_flux']:
            configs['output.netcdf_grid.variables.soil_water_sat-zone_top__recharge_volume_flux'] = 'soil_water_satzone_recharge_volume_flux',  # Downward flux from unsaturated to saturated zone	mm Δt⁻¹
        if params_output['soil_water_satzone_net_recharge_volume_flux']:
            configs['output.netcdf_grid.variables.soil_water_sat-zone_top__net_recharge_volume_flux'] = 'soil_water_satzone_net_recharge_volume_flux',  # Net recharge to saturated zone	mm Δt⁻¹
        if params_output['soil_water_satzone_leakage_volume_flux']:
            configs['output.netcdf_grid.variables.soil_water_sat-zone_bottom__leakage_volume_flux'] = 'soil_water_satzone_leakage_volume_flux',  # Actual leakage from saturated store	mm Δt⁻¹
        if params_output['soil_water_satzone_depth']:
            configs['output.netcdf_grid.variables.soil_water_sat-zone_top__depth'] = 'soil_water_satzone_depth',  # Pseudo-water table depth (top of the saturated zone)	mm
        # Lake variables
        if params_output['lake_volume']:
            configs['output.netcdf_grid.variables.lake_water__volume'] = 'lake_volume', # Lake volume (average over timestep), m³
        if params_output['lake_level']:
            configs['output.netcdf_grid.variables.lake_water_surface__elevation'] = 'lake_level', # Lake water level (average over timestep), m
        if params_output['lake_outflow']:
            configs['output.netcdf_grid.variables.lake_water~outgoing__volume_flow_rate'] = 'lake_outflow', # Outflow of the lake (average over timestep)	m³ s⁻¹
        if params_output['lake_inflow']:
            configs['output.netcdf_grid.variables.lake_water~incoming__volume_flow_rate'] = 'lake_inflow', # Inflow into the lake (average over timestep)	m³ s⁻¹
        if params_output['lake_evaporation']:
            configs['output.netcdf_grid.variables.lake_water__evaporation_volume_flux'] = 'lake_evaporation', # Average actual evaporation over the lake area	mm Δt⁻¹
        if params_output['lake_precipitation']:
            configs['output.netcdf_grid.variables.lake_water__precipitation_volume_flux'] = 'lake_precipitation', # Average precipitation over the lake area	mm Δt⁻¹
        if params_output['lake_potential_evaporation']:
            configs['output.netcdf_grid.variables.lake_water__potential_evaporation_volume_flux'] = 'lake_potential_evaporation', # Average potential evaporation over the lake area	mm Δt⁻¹
        # Reservoir variables
        if params_output['reservoir_volume']:
            configs['output.netcdf_grid.variables.reservoir_water__volume'] = 'reservoir_volume', # Reservoir volume (average over the timestep)	m³
        if params_output['reservoir_outflow']:
            configs['output.netcdf_grid.variables.reservoir_water~outgoing__volume_flow_rate'] = 'reservoir_outflow', # Outflow of the reservoir (average over the timestep)	m³ s⁻¹
        if params_output['reservoir_inflow']:
            configs['output.netcdf_grid.variables.reservoir_water~incoming__volume_flow_rate'] = 'reservoir_inflow', # Inflow into the reservoir (average over the timestep)	m³ s⁻¹
        if params_output['reservoir_evaporation']:
            configs['output.netcdf_grid.variables.reservoir_water__evaporation_volume_flux'] = 'reservoir_evaporation', # Average actual evaporation over the reservoir area	mm Δt⁻¹
        if params_output['reservoir_precipitation']:
            configs['output.netcdf_grid.variables.reservoir_water__precipitation_volume_flux'] = 'reservoir_precipitation', # Average precipitation over the reservoir area	mm Δt⁻¹
        if params_output['reservoir_potential_evaporation']:
            configs['output.netcdf_grid.variables.reservoir_water__potential_evaporation_volume_flux'] = 'reservoir_potential_evaporation', # Average potential evaporation over the reservoir area	mm Δt⁻¹
        # River variables (Kinematic wave)
        if params_output['river_discharge']:
            configs['output.netcdf_grid.variables.river_water__volume_flow_rate'] = 'river_discharge', # River discharge (average over timestep)	m³ s⁻¹
        if params_output['river_depth']:
            configs['output.netcdf_grid.variables.river_water__depth'] = 'river_depth', # River depth (average over timestep)	m
        if params_output['river_volume']:
            configs['output.netcdf_grid.variables.river_water__volume'] = 'river_volume', # River volume (average over timestep)	m³
        if params_output['river_lateral_inflow']:
            configs['output.netcdf_grid.variables.river_water_inflow~lateral__volume_flow_rate'] = 'river_lateral_inflow', # Lateral inflow into the river (average over timestep)	m³ s⁻¹
        # Snow variables
        if params_output['snow_water']:
            configs['output.netcdf_grid.variables.snowpack__leq-depth'] = 'snow_water',  # Liquid-water equivalent of snow pack (SWE)	mm
        if params_output['snow_melt']:
            configs['output.netcdf_grid.variables.snowpack_meltwater__volume_flux'] = 'snow_melt',  # Amount of snow melt	mm Δt⁻¹
        if params_output['snow_runoff']:
            configs['output.netcdf_grid.variables.snowpack_water__runoff_volume_flux'] = 'snow_runoff',  # Runoff from snowpack	mm Δt⁻¹
        # Glacier variables
        if params_output['glacier_melt']:
            configs['output.netcdf_grid.variables.glacier_ice__melt_volume_flux'] = 'glacier_melt',  # Melt from the glacier	mm Δt⁻¹
        # Vegetation variables
        if params_output['vegetation_stemflow']:
            configs['output.netcdf_grid.variables.vegetation_canopy_water__stemflow_volume_flux'] = 'vegetation_stemflow',  # Stemflow	mm Δt⁻¹
        if params_output['vegetation_throughfall']:
            configs['output.netcdf_grid.variables.vegetation_canopy_water__throughfall_volume_flux'] = 'vegetation_throughfall',  # Throughfall	mm Δt⁻¹
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
            river_upa=10, # Minimum upstream area threshold for the river map [km2]
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
        logger.info(f"Prepare HydroMT completed.\n")
        logger.handlers[0].flush()
        processes[project_name] = {"status": "finished", "message": "\nPrepare HydroMT completed."}
    except Exception as e:
        print('/prepare_hydromt:\n==============')
        traceback.print_exc()
        logger.exception("Prepare HydroMT failed")
        processes[project_name] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

def run_hydromt(project_name, processes, flow_dir, model_name):
    model_dir = os.path.join(flow_dir, model_name)
    # Set up logger
    log_path = os.path.join(flow_dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    logger = setup_logger("hydromt", log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    try:
        logger.info("Running HydroMT...")
        logger.info("===============================")
        wflow_path = os.path.normpath(os.path.join(WFLOW_PATH, "wflow_cli", "bin", "wflow_cli.exe"))
        toml_path = os.path.normpath(os.path.join(model_dir, "wflow_sbm.toml"))
        cmd = [wflow_path, toml_path]
        process = subprocess.Popen(
            cmd, cwd=model_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        for line in process.stdout: logger.info(line.strip())
        process.wait()
        logger.info(f"Run HydroMT completed with return code: {process.returncode}")
        logger.info(f"Run HydroMT completed.\n")
        processes[project_name] = {"status": "finished", "message": "\nRun HydroMT completed."}
    except Exception as e:
        print('/run_hydromt:\n==============')
        traceback.print_exc()
        logger.exception("Run HydroMT failed")
        processes[project_name] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.flush()
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

# def weather_init(id:str) -> gpd.GeoDataFrame:
#     if id == 'ntnu':
#         data = {
#             'name': 'Norwegian University of Science and Technology',
#             'county': 'MØRE OG ROMSDAL', 'municipality': 'ÅLESUND', 
#             'stationHolders': 'NTNU I ÅLESUND',
#             'geometry': Point((6.4797, 62.4848))
#         }
#         gdf = gpd.GeoDataFrame(data=[data], geometry='geometry', crs="EPSG:4326")
#     elif id == 'eklima':
#         url = f'{MET_url}/sources/v0.jsonld'
#         headers = {'Accept': 'application/json'}
#         response = requests.request("GET", url, 
#             headers=headers, auth=HTTPBasicAuth(MET_client_id, ''))
#         columns = ['id', 'name', 'county', 'municipality', 'stationHolders', 'geometry']
#         if response.status_code != 200 or 'data' not in response.json():
#             return gpd.GeoDataFrame()
#         df = pd.DataFrame(response.json()['data'])[columns]
#         df['geometry'] = df['geometry'].apply(lambda x: Point(*x['coordinates']) if isinstance(x, dict) else None)
#         df.dropna(subset=['geometry'], inplace=True)
#         gdf = gpd.GeoDataFrame(df, crs="EPSG:4326")
#     elif id == 'nve':
#         url = f'{NVE_url}/Stations'
#         headers = {'Accept': 'application/json', "X-API-Key": NVE_client_id}
#         response = requests.request("GET", url, headers=headers, params={"Active": 1})
#         if response.status_code != 200 or 'data' not in response.json():
#             return gpd.GeoDataFrame()
#         columns = [
#             'stationId', 'stationName', 'latitude', 
#             'longitude', 'councilName', 'countyName', 'owner'
#             ]
#         allowed_params, filtered_data = {0, 2, 4, 8, 9, 11}, []
#         for station in response.json()['data']:
#             filtered_series = [
#                 s for s in station.get("seriesList", [])
#                 if s.get("parameter") in allowed_params
#             ]
#             if filtered_series:
#                 new_station = station.copy()
#                 new_station["seriesList"] = filtered_series
#                 filtered_data.append(new_station)
#         df = pd.DataFrame(filtered_data)[columns]
#         if df.empty: return gpd.GeoDataFrame()
#         columns_renamed = {
#             'stationId': 'id', 'stationName': 'name', 'councilName': 'municipality', 
#             'countyName': 'county', 'owner': 'stationHolders'
#         }
#         df.rename(columns=columns_renamed, inplace=True)
#         gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs='EPSG:4326')
#         gdf.drop(columns=['latitude', 'longitude'], inplace=True)
#     return gdf

# def weather_downloader(source:str, stationId:str, start:datetime, end:datetime) -> tuple:
#     start_time = start.strftime('%Y-%m-%dT%H:%M:%SZ')
#     end_time = end.strftime('%Y-%m-%dT%H:%M:%SZ')
#     if source == 'ntnu':
#         content = []




#     elif source == 'eklima':
#         # Reference: https://frost.met.no/elementtable
#         url = f'{MET_url}/observations/v0.jsonld'
#         headers = {'Accept': 'application/json'}
#         columns = [
#             "mean(air_temperature PT1H)", "mean(wind_speed PT1H)", 
#             "mean(surface_air_pressure PT1H)", "mean(relative_humidity PT1H)",
#             "sum(precipitation_amount PT1H)", 
#             "mean(surface_downwelling_shortwave_flux_in_air PT1H)",
#             'mean(surface_downwelling_longwave_flux_in_air PT1H)'
#         ]
#         params = {
#             "sources": stationId, "elements": ",".join(columns),
#             "referencetime": f"{start_time}/{end_time}"
#         }
#         response = requests.request("GET", url, params=params,
#             headers=headers, auth=HTTPBasicAuth(MET_client_id, ''))
#         data, rows = response.json()["data"], []
#         for item in data:
#             time = item['referenceTime']
#             for obs in item['observations']:
#                 rows.append({
#                     "timestamp": time, 'element': obs['elementId'],
#                     "value": obs['value'], 'timeResolution': obs['timeResolution'],
#                     "height": obs.get('level', {}).get('value'), "qualityCode": obs.get('qualityCode')
#                 })
#         df = pd.DataFrame(rows)
#         df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
#         df = df[df['timeResolution'] == 'PT1H'].reset_index(drop=True)
#         weather_df = pd.DataFrame(data={'timestamp': df['timestamp'].unique()})
#         pre_mask = (df['element'] == 'sum(precipitation_amount PT1H)')
#         df.loc[pre_mask, 'precipitation'] = df.loc[pre_mask, 'value']
#         pre_df = df[~df['precipitation'].isna()]
#         weather_df = weather_df.merge(pre_df[['timestamp', 'precipitation']], how='left', on='timestamp')
#         temp_mask = (df['element'] == 'mean(air_temperature PT1H)') & (df['height'] == 2)
#         df.loc[temp_mask, 'temperature'] = df.loc[temp_mask, 'value']
#         temp_df = df[~df['temperature'].isna()]
#         weather_df = weather_df.merge(temp_df[['timestamp', 'temperature']], how='left', on='timestamp')
#         short_mask = (df['element'] == 'mean(surface_downwelling_shortwave_flux_in_air PT1H)')
#         df.loc[short_mask, 'short_wave_radiation'] = df.loc[short_mask, 'value']
#         short_df = df[~df['short_wave_radiation'].isna()]
#         weather_df = weather_df.merge(short_df[['timestamp', 'short_wave_radiation']], how='left', on='timestamp')
#         long_mask = (df['element'] == 'mean(surface_downwelling_longwave_flux_in_air PT1H)')
#         df.loc[long_mask, 'long_wave_radiation'] = df.loc[long_mask, 'value']
#         long_df = df[~df['long_wave_radiation'].isna()]
#         weather_df = weather_df.merge(long_df[['timestamp', 'long_wave_radiation']], how='left', on='timestamp')
#         wind_mask = (df['element'] == 'mean(wind_speed PT1H)') & (df['height'] == 10)
#         df.loc[wind_mask, 'wind_speed'] = df.loc[wind_mask, 'value']
#         wind_df = df[~df['wind_speed'].isna()]
#         weather_df = weather_df.merge(wind_df[['timestamp', 'wind_speed']], how='left', on='timestamp')
#         humidity_mask = (df['element'] == 'mean(relative_humidity PT1H)')
#         df.loc[humidity_mask, 'humidity'] = df.loc[humidity_mask, 'value']
#         humidity_df = df[~df['humidity'].isna()]
#         weather_df = weather_df.merge(humidity_df[['timestamp', 'humidity']], how='left', on='timestamp')
#         pressure_mask = (df['element'] == 'mean(surface_air_pressure PT1H)')
#         df.loc[pressure_mask, 'pressure'] = df.loc[pressure_mask, 'value']
#         pressure_df = df[~df['pressure'].isna()]
#         weather_df = weather_df.merge(pressure_df[['timestamp', 'pressure']], how='left', on='timestamp')
#     elif source == 'nve':
#         # Reference: https://hydapi.nve.no/swagger/index.html?urls.primaryName=V1
#         url, weather_df = f'{NVE_url}/Observations', pd.DataFrame()
#         weather_df['time'] = pd.date_range(start=start_time, end=end_time, freq='H').strftime('%Y-%m-%d %H:%M:%S')
#         headers = {'Accept': 'application/json', "X-API-Key": NVE_client_id}
#         # Get observations
#         observations = ['precipitation', 'temperature', 'short_wave_radiation',
#             'long_wave_radiation', 'wind_speed', 'humidity', 'pressure']
#         for obs in observations:
#             params = {
#                 "StationId": str(stationId), "Parameter": NVE_codes[obs], 
#                 "ResolutionTime": 60, "ReferenceTime": f"{start_time}/{end_time}"
#             }
#             response = requests.request("GET", url, params=params, headers=headers)
#             obs_data = response.json().get('data', [])
#             if response.status_code == 200 and obs_data:
#                 observations = obs_data[0].get('observations', [])
#                 if observations:
#                     temp_df = pd.DataFrame(observations)[['time', 'value']]
#                     temp_df.rename(columns={'value': obs}, inplace=True)
#                     weather_df = weather_df.merge(temp_df, how='left', on='time')
#                     continue
#             weather_df[obs] = None
#     # Check for missing values
#     missing = 1 if weather_df.isna().sum().sum() > 0 else 0
#     # Fill missing values with None
#     weather_df = weather_df.replace([np.inf, -np.inf], None)
#     weather_df = weather_df.astype(object)
#     weather_df = weather_df.where(weather_df.notna(), None)
#     content = weather_df.values.tolist()
#     return content, missing



# # Fix invalid soil polygon
# soil_UTM = soil.to_crs(terrain.rio.crs)
# soil_cols = ['soil', 'theta_s', 'theta_r', 'k_sat_ver', 'soil_depth', 'conductivity_decay', 'brooks_corey']
# soil_UTM = fix_invalid_polygon(soil_UTM, soil_cols)
# soil_layers = ['theta_s', 'theta_r', 'k_sat_ver', 'soil_depth', 'conductivity_decay', 'brooks_corey']
# soil_UTM = soil_UTM[soil_layers + ['geometry']]
# soil_UTM = soil_UTM.rename(columns={
#     'theta_s': 'thetaS', 'theta_r': 'thetaR', 'k_sat_ver': 'KsatVer', 'soil_depth': 'SoilThickness', 
#     'conductivity_decay': 'f', 'brooks_corey': 'brooks_corey'
# })
# # for value in soil_layers:
# #     soil_path = os.path.normpath(os.path.join('test/data/soil', f'{value}.tif'))
# #     write_tif(soil_path, terrain, soil_UTM, value)


        # save_dir = os.path.normpath(os.path.join(flow_dir, folder))
        # os.makedirs(save_dir, exist_ok=True)
        # file_ext = file.filename.split(".")
        # soil_path = os.path.normpath(os.path.join(save_dir, file.filename))
        # with open(soil_path, "wb") as buffer:
        #     shutil.copyfileobj(file.file, buffer)
        # if file_ext[-1].lower() in ["tif"]:
        #     with rasterio.open(soil_path) as src:
        #         data = src.read(1)
        #         mask = data != src.nodata
        #         data = data.astype(np.int32)
        #         results = ({ "geometry": shape(geom), key: func_codes.get(value, "")
        #         } for geom, value in shapes(data, mask=mask, transform=src.transform))
        #         geoms = list(results)
        #     del data
        #     gdf = gpd.GeoDataFrame(geoms, crs=src.crs)
        # elif file_ext[-1].lower() in ["geojson"]: 
        #     gdf = gpd.read_file(soil_path)
        # if gdf.empty: return JSONResponse({'status': 'error', 'message': 'No data found.'})
        # if key not in gdf.columns: gdf.insert(1, key, 'None')
        # mapped = gdf[key].map(lambda x: func_types.get(x, ["None"] * len(new_cols)))
        # gdf[new_cols] = pd.DataFrame(mapped.tolist(), columns=new_cols)
        # gdf[key] = np.where(gdf[key]=='', 'None', gdf[key])
        # gdf[key] = gdf[key].astype(str)
        # if '_id' not in gdf.columns: gdf.insert(0, '_id', range(1, len(gdf) + 1))
        # gdf = gdf[['_id', key, 'geometry'] + new_cols]
        # for col in new_cols:
        #     gdf[col] = pd.to_numeric(gdf[col], errors='coerce')
        # if gdf.crs != "EPSG:4326": gdf = gdf.to_crs("EPSG:4326")

# # Download soil data 2020 from ISRIC: https://files.isric.org/soilgrids/latest/data/
# soil_types = {
#     'clay': 'clyppt', 'sand': 'sndppt', 'silt': 'sltppt', 
#     'bdod': 'bd', 'soc': 'oc', 'phh2o': 'ph'
# }
# depths = {
#     '0-5cm_mean': 'sl1', '5-15cm_mean': 'sl2', '15-30cm_mean': 'sl3',
#     '30-60cm_mean': 'sl4', '60-100cm_mean': 'sl5', '100-200cm_mean': 'sl6'
# }
# soils = {
#     'clay': 1, 'sand': 1, 'silt': 1, 'bdod': 100, 'soc': 10, 'phh2o': 10
# }
# bbox = (float(min_lon), float(min_lat), float(max_lon), float(max_lat))
# for item, name in tqdm(soil_types.items(), total=len(soil_types), desc='Downloading soil data'):
#     wcs = WebCoverageService(f'https://maps.isric.org/mapserv?map=/map/{item}.map', version='1.0.0')
#     scale = soils[item]
#     for type, value in depths.items():
#         idx = f'{item}_{type}'
#         response = wcs.getCoverage(
#             identifier=idx, crs='EPSG:4326', bbox=bbox, format='image/tiff',
#             resx=0.0025, resy=0.0025, timeout=120
#         )
#         with MemoryFile(response.read()) as memfile:
#             with rioxarray.open_rasterio(memfile) as src_xr:
#                 data_xr = src_xr.squeeze()
#                 data_xr = data_xr.rio.reproject_match(ref, resampling=Resampling.bilinear)
#                 data_xr = np.where(data_xr == data_xr.rio.nodata, nodata, data_xr)
#         soil_array = data_xr
#         # Interpolate data
#         mask_valid = soil_array != nodata
#         soil_values = flow_functions.interpolate_extrapolate(soil_array, ~mask_valid, True)
#         soil_values[mask_nan] = nodata
#         mask_land = (soil_values != nodata) & (~np.isnan(soil_values)) & (~mask_lake)
#         soil_values[mask_land] = soil_values[mask_land] / scale
#         soil_values[~mask_land] = nodata
#         soil_values = np.round(soil_values, 2).astype(np.float32)
#         path = os.path.join(soil_dir, f'{name}_{value}.tif')
#         flow_functions.write_geotiff(soil_values, profile, path)
# ref.close()
# # # Create soil thickness
# # soil_thickness_path = os.path.normpath(os.path.join(soil_dir, 'soilthickness.tif'))
# # soil_thickness = rasterize(
# #     shapes=[(geom, 200) for geom in area_clip], dtype=np.float32,
# #     out_shape=(height, width), transform=transform, fill=255
# # )
# # profile_thickness = profile.copy()
# # profile_thickness.update({'dtype': np.uint8, 'nodata': 255, 'count': 1, 'compress': 'lzw'})
# # flow_functions.write_geotiff(soil_thinkness, profile_thickness, soil_thinkness_path)



# # ============= QGIS python plugin: Process LAI downloaded from EarthData Search =============
# from pathlib import Path
# from datetime import datetime, timedelta
# from collections import defaultdict
# import numpy as np
# from osgeo import gdal

# input_dir = r"C:\Users\vanln\Downloads\MCD15A3H_061-20260618_172802"
# output_dir = r"C:\Users\vanln\Downloads\MCD15A3H_061-20260618_172802\monthly_lai"
# Path(output_dir).mkdir(exist_ok=True)

# def get_lai_subdataset(hdf_file):
#     ds = gdal.Open(hdf_file)
#     for sds_name, sds_desc in ds.GetSubDatasets():
#         if "Lai_500m" in sds_name:
#             return sds_name
#     raise Exception(f"Cannot find Lai_500m in {hdf_file}")

# monthly_files = defaultdict(list)
# for file in Path(input_dir).glob("*.hdf"):
#     parts = file.name.split(".")
#     julian = parts[1]  # A2018001
#     year = int(julian[1:5])
#     doy = int(julian[5:])
#     date = datetime(year, 1, 1) + timedelta(days=doy - 1)
#     monthly_files[(date.year, date.month)].append(str(file))

# for (year, month), files in sorted(monthly_files.items()):
#     print(f"Processing {year}-{month:02d}")
#     arrays = []
#     template_ds = None
#     for hdf_file in files:
#         lai_sds = get_lai_subdataset(hdf_file)
#         ds = gdal.Open(lai_sds)
#         arr = ds.ReadAsArray().astype(np.float32)
#         # MODIS fill value
#         arr[arr >= 249] = np.nan
#         arrays.append(arr)
#         if template_ds is None:
#             template_ds = ds
#     monthly_mean = np.nanmean(arrays, axis=0)
#     # scale factor LAI = 0.1
#     monthly_mean = monthly_mean * 0.1
#     outfile = (
#         Path(output_dir)
#         / f"LAI_{year}_{month:02d}.tif"
#     )
#     driver = gdal.GetDriverByName("GTiff")
#     out_ds = driver.Create(
#         str(outfile),
#         template_ds.RasterXSize,
#         template_ds.RasterYSize,
#         1,
#         gdal.GDT_Float32,
#         options=["COMPRESS=LZW"]
#     )
#     out_ds.SetGeoTransform(
#         template_ds.GetGeoTransform()
#     )
#     out_ds.SetProjection(
#         template_ds.GetProjection()
#     )
#     band = out_ds.GetRasterBand(1)
#     band.WriteArray(monthly_mean)
#     band.SetNoDataValue(-9999)
#     out_ds.FlushCache()
#     out_ds = None
#     print(f"Saved: {outfile}")
# print("DONE")


# ########################### Get landcover data from ESA worldcover
# user_name, password = os.getenv('ESA_USERNAME'), os.getenv('ESA_PASSWORD')
# catalogue = Catalogue().authenticate_non_interactive(user_name, password)
# area = catchment.copy()
# if area.crs != 'EPSG:4326': area = area.to_crs('EPSG:4326')
# minx, miny, maxx, maxy = area.total_bounds
# bbox = Polygon.from_bounds(minx, miny, maxx, maxy)
# download_dir = os.path.join(land_dir, 'downloads')
# if os.path.exists(download_dir): shutil.rmtree(download_dir)
# # Get name of landcover layer
# collections = catalogue.get_collections()
# layers = [
#     # 'urn:eop:VITO:ESA_WorldCover_10m_2020_V1', 
#     'urn:eop:VITO:ESA_WorldCover_10m_2021_V2'
# ]
# # Search for products in the WorldCover collection
# product = catalogue.get_products(layers, geometry=bbox)
# catalogue.download_products(product, download_dir, force=True)
# pattern = os.path.join(download_dir, "**", "*_Map.tif")
# files = glob.glob(pattern, recursive=True)
# if len(files) == 0: raise ValueError("No *_Map.tif files found in directory")
# if len(files) == 1:
#     src_files = [rasterio.open(files[0])]
#     mosaic, transform = src_files[0].read(), src_files[0].transform
# elif len(files) > 1:
#     src_files = [rasterio.open(f) for f in files]
#     # Merge (mosaic)
#     mosaic, transform = merge(src_files)
# # Copy metadata
# out_meta = src_files[0].meta.copy()
# out_meta.update({
#     "height": mosaic.shape[1], "width": mosaic.shape[2],
#     "transform": transform, "compress": "lzw"
# })
# merge_path = os.path.join(land_dir, 'merged.tif')
# with rasterio.open(merge_path, "w", **out_meta) as dest:
#     dest.write(mosaic)
# # Close files
# for src in src_files: src.close()
# shutil.rmtree(download_dir)
# # Clip raster to catchment
# land_path = os.path.join(land_dir, 'esa_worldcover.tif')
# land_temp = rioxarray.open_rasterio(merge_path).squeeze()
# land_match = land_temp.rio.reproject_match(terrain_da, resampling=Resampling.nearest)
# land_esa = land_match.values.astype(np.uint8)
# esa_nodata = land_match.rio.nodata
# if esa_nodata is not None:
#     land_esa[land_esa == esa_nodata] = NODATA_FLWDR
# land_esa[mask_nan] = NODATA_FLWDR
# flow_functions.write_geotif(land_esa, profile_writer, land_path, NODATA_FLWDR)
# del land_temp
# gc.collect()
# functions.safe_remove(merge_path)
# # Save look up table
# csv_path = r"backend\src\flow_samples\landcover\esa_worldcover_mapping.csv"
# df, lai_name, land_arr = pd.read_csv(csv_path), "esa", land_esa
# df.to_csv(os.path.join(land_dir, 'esa_worldcover.csv'), index=False)


# # Create soil thickness
# with rasterio.open(terrain_path) as src:
#     meta = src.meta.copy()
# meta.update({"dtype": "float32", "nodata": -9999.0})
# data = np.ones((meta["height"], meta["width"]), dtype="float32") * 100
# data[data == meta["nodata"]] = 100
# with rasterio.open(os.path.join(soil_dir, 'soilthickness.tif'), "w", **meta) as dst:
#     dst.write(data, 1)
# # Download soil data from ISRIC: https://files.isric.org/soilgrids/latest/data/
# soil_types, soil_depths = flow_functions.soil_types, flow_functions.soil_depths
# for item, name in soil_types.items():
#     wcs = WebCoverageService(f'https://maps.isric.org/mapserv?map=/map/{item}.map', version='1.0.0')
#     for type, value in soil_depths.items():
#         idx, soil_name = f'{item}_{type}', f'{name}_{value}'
#         response = wcs.getCoverage(
#             identifier=idx, crs='EPSG:4326', bbox=bbox,
#             format='image/tiff', resx=0.0025, resy=0.0025
#         )
#         with MemoryFile(response.read()) as memfile:
#             with memfile.open() as src:
#                 data = rioxarray.open_rasterio(src, masked=True)
#                 data_reprojected = data.rio.reproject_match(terrain)
#             data_reprojected.rio.to_raster(os.path.join(soil_dir, f'{soil_name}.tif'))

