import os, dotenv, base64, requests, math, rasterio, rioxarray, pyflwdir
import traceback, sys, shutil, cdsapi, calendar, json, asyncio
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.shutil import copy as rio_copy # type: ignore
from shapely.geometry import Point, shape
from rasterio.enums import Resampling
from rasterio.features import shapes
import pandas as pd, xarray as xr, numpy as np, geopandas as gpd
from config import PROJECT_ROOT
from services import functions, flow_functions
from pathlib import Path
from services.flow_functions import StreamToLogger
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
import dask.array as da
from pyflwdir import dem
from numbers import Number


variables = {
    'total_precipitation': 'tp', # Precipitation
    '2m_temperature': 't2m', # Temperature
    '10m_u_component_of_wind': 'u10', '10m_v_component_of_wind': 'v10', # Wind
    'surface_pressure': 'sp',  # Pressure
    'surface_solar_radiation_downwards': 'ssrd', # Shortwave radiation
    'toa_incident_solar_radiation': 'tisr', # Longwave radiation
    'total_cloud_cover': 'tcc', # Cloud cover
}

var_revert = {
    'tp': 'Total Precipitation (mm)', 't2m': 'Temperature (degC)',
    'u10': 'Wind (u Component) (m/s)', 'v10': 'Wind (v Component) (m/s)',
    'sp': 'Surface Pressure (hPa)', 'tcc': 'Total Cloud Cover (%)',
    'ssrd': 'Shortwave Radiation (W/m^2)', 'tisr': 'Longwave Radiation (W/m^2)',
    'Time': 'Time', 'wind_speed': 'Wind Speed (m/s)',
    'wind_direction': 'Wind Direction (degrees)'
}

class Regnbyge():
    def __init__(self, name, secret, username, password) -> None:
        dotenv.load_dotenv()
        self.url = os.getenv('FLOW_URL')
        self.token_url = os.getenv('FLOW_URL_TOKEN')
        self.client, self.client_secret = name, secret
        self.username, self.password = username, password
        self.token = self.get_Token()
        if self.token is None:
            raise RuntimeError(
                f"Cannot get access token. Check credentials for client '{name}'."
            )

    def get_Token(self):
        # Encode client_id:client_secret to Base64
        auth_string = f"{self.client}:{self.client_secret}"
        auth_bytes = auth_string.encode('utf-8')
        auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')
        # Define the headers
        headers = {
            'Authorization': f'Basic {auth_base64}',
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        # Define the body parameters (in x-www-form-urlencoded format)
        body = {'username': self.username, 'password': self.password,
                'scope': 'openid regnbyge', 'grant_type': 'password'}
        response = requests.request("POST", self.token_url, headers=headers, data=body, timeout=30)
        if response.status_code == 200: return response.json().get('access_token')
        else: return None

    def get_Station(self, variable):
        headers = {'Accept': 'application/json', 'Authorization': f'Bearer {self.token}'}
        url_objects = f'{self.url}/{variable}'
        response = requests.request("GET", url_objects, headers=headers, timeout=30)
        ids, rows = response.json(), []
        if not ids: return pd.DataFrame()
        for station_id in ids:
            url = f'{url_objects}/{station_id}'
            try:
                res = requests.get(url, headers=headers, timeout=30)
                if res.status_code == 200: rows.append(res.json())
                else: print(f"Station {station_id}: HTTP {res.status_code}")
            except requests.RequestException as e: print(f"Station {station_id}: {e}")
        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows)
        # Delete columns with all NaN values
        df.dropna(axis=1, how='all', inplace=True)
        # Delete rows with all NaN values
        df.dropna(axis=0, how='all', inplace=True)
        df.reset_index(inplace=True, drop=True)
        df = df.astype(object).where(pd.notnull(df), None)
        return df
    
    def get_Values(self, variable:str, ids:list, from_date, end_date, agg:str='Raw'):
        '''
        agg: Raw, Minute, FiveMinute, Hour, Day
        fromDate, toDate: time in UTC
        '''
        if not self.token: raise RuntimeError("No access token available. Call get_Token() first.")
        if not ids: return pd.DataFrame()
        if from_date.tzinfo is None:
            start = from_date.replace(tzinfo=timezone.utc).isoformat()
        else: start = from_date.isoformat()
        if end_date.tzinfo is None:
            end = end_date.replace(tzinfo=timezone.utc).isoformat()
        else: end = end_date.isoformat()
        headers = {'accept': 'application/json', 'Authorization': f'Bearer {self.token}'}
        payload = {"ids": ids, "from": start, "to": end, "aggregation": agg}
        url = f'{self.url}/{variable}/values'
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
        except requests.RequestException: return pd.DataFrame()
        data, data_value = pd.DataFrame(), response.json()
        for item in data_value:
            measurements = item.get('measurements', [])
            if not isinstance(measurements, list):
                print(f"Unexpected measurements type: {type(measurements)}")
                continue
            df_value = pd.DataFrame(measurements)
            if len(df_value) == 0: continue
            timestamp = pd.to_datetime(df_value['t'].values, utc=True)
            if variable=='flow': # Using Flow
                df = pd.DataFrame(data={'timestamp': timestamp,
                    'level (m)':df_value['l'].values, 'velocity (m/s)':df_value['v'].values,
                    'discharge (m³/s)':df_value['q'].values})
            elif variable=='level': # Using Level
                df = pd.DataFrame(data={'timestamp': timestamp,
                    'level (m)':df_value['l'].values})
            elif variable=='rain': # Using Rainfall
                df = pd.DataFrame(data={'timestamp': timestamp,
                    'rainfall (m)':df_value['r'].values})
            # elif variable=='overflow': # Using Overflow
            #     pass
            # elif variable=='temperature': # Using Temperature
            #     pass

            # elif variable=='evaporation': # Using Evaporation
            #     pass
            # elif variable=='weir': # Using Weir
            #     pass
            else: continue
            df['id'] = item['id']
            if df.drop(columns=['timestamp']).isna().all().all(): continue
            data = pd.concat([data, df], ignore_index=True)
        data = data.reset_index(drop=True)
        data = data.replace(float("nan"), None) # Fill NaN values
        return data

def era5_downloader(key:str, api_key:str, dir:str, processes:dict, key_process:str, vars:list, 
    lat:float, lon:float, start:str, end:str, time_zone:str, buffer:float=0.01):
    # Prepare forcing data from the global model ARE5
    # Source: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download
    # Remove old log
    log_path = os.path.join(dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    logger = flow_functions.setup_logger("cdsapi", log_path)
    CDS_url, CDS_key = os.getenv('CDS_URL'), api_key
    config_path = Path.home() / '.cdsapirc'
    if not config_path.exists():
        logger.info("Creating .cdsapirc ...")
        config_path.write_text(f"url: {CDS_url}\nkey: {CDS_key}\n", encoding='utf-8')
        logger.info(f"Created at: {config_path}")
    download_dir = os.path.join(dir, 'download')
    if os.path.exists(download_dir): shutil.rmtree(download_dir)
    os.makedirs(download_dir, exist_ok=True)
    area = [lat + buffer, lon - buffer, lat - buffer, lon + buffer]
    dataset, df_result = 'reanalysis-era5-single-levels', pd.DataFrame()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    start_time = functions.local_to_utc(start, time_zone).replace(tzinfo=None)
    end_time = functions.local_to_utc(end, time_zone).replace(tzinfo=None)
    if (start_time >= end_time):
        logger.info("Start time must be before end time.")
        processes[key_process] = {"status": "failed", "message": "Start time must be before end time."}
    try:
        logger.info("ERA5 downloader started")
        logger.info(f"Location: lat={lat}, lon={lon}")
        logger.info("="*70)
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        # Download ERA5 data
        logger.info("Downloading ERA5 data...")
        client = cdsapi.Client(quiet=False, debug=False)
        current = start_time.replace(day=1)
        monthly_frames = []
        while current <= end_time:
            logger.info("="*35)
            logger.info(f"Downloading month: {current}")
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
            month_data = {}
            vals = {item: variables[item] for item in vars if item in variables.keys()}
            for idx, var in vals.items():
                logger.info("="*35)
                logger.info(f"Downloading variable: {var}")
                request = {
                    'product_type': 'reanalysis', 'variable': [idx],
                    'year': [str(year)], 'month': [f"{month:02d}"], 'day': days,
                    'time': [f"{h:02d}:00" for h in range(24)], 'area': area,
                    'data_format': 'netcdf', 'download_format': 'unarchived'
                }
                out_file = f"{year}_{month:02d}_{var}.nc"
                out_path = os.path.join(download_dir, out_file)
                client.retrieve(dataset, request, out_path)
                # Check valid files
                if flow_functions.is_valid_netcdf(out_path, var): 
                    files.append(out_path)
                    with xr.open_dataset(out_path) as ds:
                        time_dim = 'valid_time' if 'valid_time' in ds.dims else 'time'
                        timestamps = pd.to_datetime(ds[time_dim].values, utc=True)
                        ds_point = ds.sel(latitude=lat, longitude=lon, method='nearest')
                        data_var = [v for v in ds_point.data_vars
                            if v not in ('latitude', 'longitude', 'time', 'valid_time', 'number')][0]
                        values = ds_point[data_var].values.squeeze()
                    month_data[var] = (timestamps, values)
                    # os.remove(out_path)
                else: bad_files.append(out_path)
                month_files.append(out_path)
            if month_data:
                month_series = {}
                for var in month_data:
                    timestamps, values = month_data[var]
                    month_series[var] = pd.Series(values, index=pd.DatetimeIndex(timestamps))
                month_df = pd.DataFrame(month_series)
                month_df.index.name = 'time'
                monthly_frames.append(month_df)
            current += relativedelta(months=1)
        if monthly_frames:
            df_result = pd.concat(monthly_frames).sort_index()
            df_result = df_result[~df_result.index.duplicated(keep='first')]
            start_ts = pd.Timestamp(start_time).tz_localize('UTC')
            end_ts = pd.Timestamp(end_time).tz_localize('UTC')
            df_result = df_result[(df_result.index >= start_ts) & (df_result.index <= end_ts)]
            logger.info(f"Final DataFrame shape: {df_result.shape}")
        logger.info("ERA5 download completed successfully")
        # Check valid files
        logger.info("="*40)
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
        df_result.index = functions.utc_to_local(df_result.index, time_zone)
        df_result.index.name = 'Time'
        columns = df_result.columns.tolist()
        if 'tp' in columns: df_result['tp'] *= 1000
        if 't2m' in columns: df_result['t2m'] -= 273.15
        if 'tcc' in columns: df_result['tcc'] *= 100
        if 'ssrd' in columns: df_result['ssrd'] /= 3600
        if 'tisr' in columns: df_result['tisr'] /= 3600
        if 'wind_speed' in vars:
            df_result['wind_speed'] = np.sqrt(df_result['u10']**2 + df_result['v10']**2)
            df_result['wind_direction'] = np.arctan2(df_result['v10'], df_result['u10'])
        csv_path = os.path.normpath(os.path.join(dir, f'{key}.csv'))
        df_result = df_result.reset_index()
        df_result.to_csv(csv_path, index=False)
        logger.info(f"Saved CSV to: {csv_path}")
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        logger.info("Temporary monthly files removed.")
        logger.handlers[0].flush()
        processes[key_process] = {"status": "finished", "message": "Weather download completed successfully.\n\n"}
    except Exception as e:
        print('/era5_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Weather download failed.")
        processes[key_process] = {"status": "failed", "message": str(e)}
    finally:
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)

def met_downloader(key:str, api_key:str, url:str, dir:str, processes:dict, key_process:str, 
    ids:list, columns:list, vars:list, start:str, end:str, time_zone:str):
    log_path = os.path.join(dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    logger = flow_functions.setup_logger("met", log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    start_local = pd.Timestamp(start).tz_localize(time_zone)
    end_local = pd.Timestamp(end).tz_localize(time_zone) + pd.Timedelta(days=1)
    start_time, end_time = start_local.tz_convert('UTC'), end_local.tz_convert('UTC')
    if (start_time >= end_time): 
        logger.info("Start time must be before end time.")
        processes[key_process] = {"status": "failed", "message": "Start time must be before end time."}
    start_date, end_date = start_time.strftime('%Y-%m-%d'), end_time.strftime('%Y-%m-%d')
    try:
        logger.info("MET downloader started.")
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        logger.info("="*60)
        all_observations = []
        for station in ids:
            station_id = station[0]
            logger.info(f"Downloading data for station: {station_id}")
            for i in range(len(vars)):
                element = vars[i]
                logger.info(f"Station: {station_id}, Element: {element}")
                params = {
                    "sources": station_id, "elements": element, 
                    "referencetime": f"{start_date}/{end_date}"
                }
                try:
                    response = requests.get(url, params=params, auth=(api_key, ''), timeout=60)
                    if response.status_code != 200:
                        logger.info(f"Request failed for {station_id} | {element}: {response.status_code}")
                        continue
                    response.raise_for_status()
                    data = response.json()
                    records = data.get('data', [])
                    if not records: 
                        logger.info(f"  {element}: empty -> NaN")
                        continue
                    stations = pd.DataFrame(records)
                    stations = stations.explode('observations', ignore_index=True)
                    obs = pd.json_normalize(stations['observations'])
                    if obs.empty: 
                        logger.info(f"  {element}: empty -> NaN")
                        continue
                    result = pd.concat([
                        stations[['sourceId', 'referenceTime']].reset_index(drop=True),
                        obs.reset_index(drop=True)
                    ], axis=1)
                    result['Time'] = pd.to_datetime(stations['referenceTime'], utc=True)
                    result['stationId'], result['elementId'] = station_id, columns[i]
                    result = result[result["timeResolution"] == "PT1H"].copy()
                    all_observations.append(result)
                except requests.exceptions.RequestException as e:
                    logger.exception(f"Request failed for {station_id} | {element}: {e}")
            logger.info("*"*40)
        df = pd.concat(all_observations, ignore_index=True) if all_observations else pd.DataFrame()
        if df.empty:
            logger.error("No data downloaded")
            processes[key_process] = {"status": "failed", "message": "No data downloaded"}
            return
        df = df[['Time', 'stationId', 'elementId', 'value']]
        df = df.pivot_table(
            index=["Time", "stationId"], columns="elementId", values="value", aggfunc="first"
        ).reset_index()
        df.columns.name = None
        df["Time"] = pd.to_datetime(df["Time"], utc=True)
        df = df[(df["Time"] >= start_time) & (df["Time"] < end_time)].copy()
        df['Time'] = functions.utc_to_local(df['Time'], time_zone)
        if "Air Pressure (hPa)" in df.columns: df["Air Pressure (hPa)"] *= 100
        if "Cloud cover (%)" in df.columns: df["Cloud cover (%)"] = cloud_cover_to_percent(df["Cloud cover (%)"])
        csv_path = os.path.normpath(os.path.join(dir, f'{key}.csv'))
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved CSV to: {csv_path}")
        logger.info(f"Saved weather file successfully.")
        logger.handlers[0].flush()
        processes[key_process] = {"status": "finished", "message": "Weather download completed successfully.\n\n"}
    except Exception as e:
        print('/met_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Weather download failed.")
        processes[key_process] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
def cloud_cover_to_percent(series):
    """
    Convert total cloud cover from MET code (0-8) to percentage.
    0  -> 0%
    8  -> 100%
    -3 -> NaN
    9  -> NaN
    """
    values = pd.to_numeric(series, errors="coerce")
    # Invalid/special codes
    values = values.replace([-3, 9], np.nan)
    # Keep only valid values from 0 to 8
    values = values.where(values.between(0, 8), np.nan)
    # Convert 0-8 -> 0-100%
    return values / 8 * 100

def nve_downloader(key:str, api_key:str, url:str, dir:str, processes:dict, key_process:str, 
    ids:list, columns:list, vars:list, interval:int, start:str, end:str, time_zone:str):
    log_path = os.path.join(dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    logger = flow_functions.setup_logger(key, log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    start_local = pd.Timestamp(start).tz_localize(time_zone)
    end_local = pd.Timestamp(end).tz_localize(time_zone) + pd.Timedelta(days=1)
    start_time, end_time = start_local.tz_convert('UTC'), end_local.tz_convert('UTC')
    if (start_time >= end_time): 
        logger.info("Start time must be before end time.")
        processes[key_process] = {"status": "failed", "message": "Start time must be before end time."}
    try:    
        csv_path = os.path.normpath(os.path.join(dir, f'{key}.csv'))
        headers = { "X-API-Key": api_key, "Accept": "application/json" }
        start_date = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_date = end_time.strftime('%Y-%m-%dT%H:%M:%SZ')    
        logger.info("NVE downloader started.")
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        logger.info("="*60)
        all_observations = []
        for station in ids:
            station_id = station[0]
            logger.info(f"Downloading data for station: {station_id}")
            for i in range(len(vars)):
                element = vars[i]
                logger.info(f"Station: {station_id}, Element: {element}")
                params = {
                    "StationId": station_id, "Parameter": element, "ResolutionTime": interval,
                    "ReferenceTime": f"{start_date}/{end_date}"
                }
                try:
                    response = requests.get(url, params=params, headers=headers, timeout=60)
                    if response.status_code != 200:
                        logger.info(f"Request failed for {station_id} | {element}: {response.status_code}")
                        continue
                    response.raise_for_status()
                    data = response.json()
                    records = data.get('data', [])
                    if not records: 
                        logger.info(f"  {element}: empty -> NaN")
                        continue
                    stations = pd.DataFrame(records)
                    stations = stations.explode('observations', ignore_index=True)
                    obs = pd.json_normalize(stations['observations'])
                    if obs.empty:
                        logger.info(f"  {element}: empty -> NaN")
                        continue
                    obs = obs[['time', 'value']]
                    obs['Time'] = pd.to_datetime(obs['time'], utc=True)
                    obs['stationId'], obs[columns[i]] = station_id, obs['value']
                    obs = obs[['Time', 'stationId', columns[i]]]
                    all_observations.append(obs)
                except requests.exceptions.RequestException as e:
                    logger.exception(f"Request failed for {station_id} | {element}: {e}")
            logger.info("*"*40)
        df = pd.concat(all_observations, ignore_index=True) if all_observations else pd.DataFrame()
        if df.empty:
            logger.error("No data downloaded")
            processes[key_process] = {"status": "failed", "message": "No data downloaded."}
            return
        df['Time'] = functions.utc_to_local(df['Time'], time_zone)
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved data to: {csv_path}")
        logger.info(f"Saved data file successfully.")
        logger.handlers[0].flush()
        processes[key_process] = {"status": "finished", "message": "Data download completed successfully.\n\n"}
    except Exception as e:
        print('/nve_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Data download failed.")
        processes[key_process] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)

def dem_downloader(directory:str, key:str, resolution:int, boundary:gpd.GeoDataFrame, target_crs=None):
    try:
        path = os.path.normpath(os.path.join(directory, f'{key}.tif'))
        temp_path, output_temp_path = path + ".source.tif", path + ".tmp.tif"
        url = os.getenv('DEM_URL')
        if not url: return {'status': 'error', 'message': 'DEM URL is not defined.'}
        if os.path.exists(temp_path): return {'status': 'ok', 'message': 'DEM file already exists.'}
        if resolution <= 0: return {'status': 'error', 'message': 'Resolution must be greater than 0.'}
        if boundary.crs != "EPSG:25833": boundary = boundary.to_crs("EPSG:25833")
        [xmin, ymin, xmax, ymax] = boundary.total_bounds
        width = max(1, math.ceil((xmax - xmin) / resolution))
        height = max(1, math.ceil((ymax - ymin) / resolution))
        params = {
            "SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCoverage",
            "COVERAGE": "nhm_dtm_topo_25833", "FORMAT": "GeoTIFF",
            "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
            "WIDTH": str(width), "HEIGHT": str(height), "CRS": "EPSG:25833"
        }
        response = requests.get(url, params=params, timeout=180)
        if response.ok and response.content[:4] in (b"II*\x00", b"MM\x00*"):
            with open(temp_path, "wb") as f: f.write(response.content)
            with rasterio.open(temp_path) as src:
                if src.crs is None: return {'status': 'error', 'message': 'DEM file has no CRS.'}
                if (target_crs is None or src.crs == rasterio.crs.CRS.from_user_input(target_crs)):
                    output_path = temp_path
                else:
                    dst_crs = rasterio.crs.CRS.from_user_input(target_crs)
                    transform, width, height = calculate_default_transform(
                        src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=resolution
                    )
                    profile = src.profile.copy()
                    profile.update({
                        'crs': dst_crs, 'transform': transform, 'width': width,
                        'height': height, 'compress': 'deflate',
                    })
                    with rasterio.open(output_temp_path, 'w', **profile) as dst:
                        for band_idx in range(1, src.count + 1):
                            reproject(
                                source=rasterio.band(src, band_idx),
                                destination=rasterio.band(dst, band_idx),
                                src_transform=src.transform, src_crs=src.crs,
                                dst_transform=transform, dst_crs=dst_crs,
                                dst_nodata=src.nodata, resampling=Resampling.bilinear
                            )
                    output_path = output_temp_path
            os.replace(output_path, path)
            for temp_file in (temp_path, output_temp_path):
                if os.path.exists(temp_file): functions.safe_remove(temp_file)
            return {'status': 'ok', 'message': 'Download DEM and reprojection completed successfully.'}
        else: return {'status': 'error', 'message': 'Download DEM failed. Try again with lower resolution.'}
    except Exception as e:
        print('/dem_downloader:\n==============')
        traceback.print_exc()
        for temp_file in (
            os.path.join(directory, f"{key}.tif.source.tif"),
            os.path.join(directory, f"{key}.tif.tmp.tif")
        ):
            if os.path.exists(temp_file):
                try: functions.safe_remove(temp_file)
                except OSError: pass
        return {"status": 'error', "message": str(e)}

def prepare_terrain(project_name:str, dem_path:str):
    # Convert to COG
    dst_crs, base_path = "EPSG:3857", os.path.splitext(dem_path)[0]
    temp_path, cog_path = base_path + "_temp.tif", base_path + "_cog.tif"
    with rasterio.open(dem_path) as src:
        if src.crs is None:
            return {'status': 'error', 'message': "TIF file has no CRS"}
        dem = src.read(1, masked=True)
        if dem.count() == 0:
            return {"status": "error", "message": "DEM contains no valid elevation values"}
        min, max = round(float(dem.min()), 2), round(float(dem.max()), 2)
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        profile = src.profile.copy()
        profile.update({"driver": "GTiff", "crs": dst_crs, "transform": transform,
            "width": width, "height": height, "compress": "LZW",
            "tiled": True, "blockxsize": 256, "blockysize": 256
        })
        with rasterio.open(temp_path, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1), destination=rasterio.band(dst, 1),
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=transform, dst_crs=dst_crs, resampling=Resampling.bilinear
            )
    try: rio_copy(temp_path, cog_path, driver="COG", compress="LZW", blocksize=256)
    finally:
        if os.path.exists(temp_path): functions.safe_remove(temp_path)
    with rasterio.open(cog_path) as src:
        west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    bounds = [[south, west], [north, east]]
    project_root = os.path.abspath(os.path.join(PROJECT_ROOT, project_name))
    cog_abs_path = os.path.abspath(cog_path)
    if os.path.commonpath([project_root, cog_abs_path]) != project_root:
        return {"status": "error", "message": "COG file is outside the project directory"}
    relative_path = os.path.relpath(cog_abs_path, project_root).replace(os.sep, "/")
    tile_url = f"/{project_name}/{relative_path}/{{z}}/{{x}}/{{y}}.png"
    content = {"tile_url": tile_url, "bounds": bounds, 'min_max': [min, max]}
    return {'status': 'ok', 'content': content}

def stream_detector(project_name:str, folder:str, dem_name:str, threshold:int):
    try:
        directory = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, folder))
        dem_path = os.path.normpath(os.path.join(directory, f"{dem_name}.tif"))
        if not os.path.exists(dem_path):
            return {'status': 'error', 'message': f'Filled DEM file not found. Please upload DEM again.'}
        # Fill depressions
        with rasterio.open(dem_path) as src:
            dem_array, crs, nodata = src.read(1), src.crs, src.nodata
            transform, profile = src.transform, src.profile
        if nodata is None or (isinstance(nodata, (float, np.floating)) and np.isnan(nodata)):
            nodata = -9999.0
        valid_mask = np.isfinite(dem_array)
        if src_nodata := profile.get("nodata"): valid_mask &= dem_array != src_nodata
        dem_array = dem_array.astype(np.float32, copy=True)
        dem_array[~valid_mask] = nodata
        filled_array, flwdir_array = dem.fill_depressions(elevtn=dem_array, max_depth=-1, nodata=nodata)
        flw = pyflwdir.from_dem(filled_array, transform=transform, latlon=crs.is_geographic, nodata=nodata)
        # Create stream order
        strord_array = flw.stream_order(type='strahler')
        strord_array = np.where((strord_array>=threshold), strord_array, 0).astype(np.int16)
        NODATA_FLWDR, NODATA_BASIN, strord_name = 255, 0, f"{dem_name}_strord.tif"
        files = {
            f"{dem_name}_filled.tif": [filled_array, nodata, np.float32],
            strord_name: [strord_array, NODATA_BASIN, np.int16],
            f"{dem_name}_flowdir.tif": [flwdir_array, NODATA_FLWDR, np.uint8],
        }
        profile_writer = profile.copy()
        for file, array in files.items():
            profile_writer.update({'dtype': array[2]})
            file_path = os.path.normpath(os.path.join(directory, file))
            flow_functions.write_geotif(array[0], profile_writer, file_path, array[1])
        with rasterio.open(dem_path) as src:
            west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        bounds = [[south, west], [north, east]]
        tile_url = f"/{project_name}/{folder}/{strord_name}/{{z}}/{{x}}/{{y}}.png"
        contents = {"tile_url": tile_url, "bounds": bounds, 'min_max': [0, 1]}
        return {'status': 'ok', 'content': contents}
    except Exception as e: 
        print('/stream_detector:\n==============')
        traceback.print_exc()
        return {'status': 'error', 'message': str(e)}

def catchment_detector(directory:str, dem_name:str, lat:float, lon:float):
    flw_path = os.path.normpath(os.path.join(directory, f"{dem_name}_flowdir.tif"))
    with rasterio.open(flw_path, "r") as src:
        flwdir, transform, crs = src.read(1), src.transform, src.crs
    flw = pyflwdir.from_array(flwdir, ftype="d8", transform=transform, latlon=crs.is_geographic, cache=True)
    point = gpd.GeoDataFrame([{'geometry': Point(lon, lat)}], crs='EPSG:4326')
    point = point.to_crs(crs)
    x, y = point.geometry.x[0], point.geometry.y[0]
    basin_raster = flw.basins(xy=(x, y))
    raster_shapes = shapes(
        basin_raster.astype("int32"), mask=basin_raster > 0, transform=transform
    )
    geoms = [shape(geom) for geom, value in raster_shapes if value > 0]
    catchment = gpd.GeoDataFrame(geometry=geoms, crs=crs)
    if catchment.empty: return {'status': 'error', 'message': 'No catchment found.'}
    area = round(catchment["geometry"].area.sum() / 1000000, 6)
    catchment = catchment.to_crs("EPSG:4326")
    return {'status': 'ok', 'content': json.loads(catchment.to_json()), 'area': area}

def raster_vector(raster_path:str, lookup_table:pd.DataFrame, catchment:gpd.GeoDataFrame):
    with rioxarray.open_rasterio(raster_path) as src:
        land = src.squeeze(drop=True).load()
    data, transform = land.values, land.rio.transform()
    results = (
        {'geometry': geom, 'properties': {'value': value}}
        for geom, value in shapes(data, transform=transform)
    )
    gdf = gpd.GeoDataFrame.from_features(list(results))
    if len(gdf) == 0: return gpd.GeoDataFrame()
    gdf.set_crs(land.rio.crs, inplace=True)
    gdf['value'] = gdf['value'].astype(int)
    # Remove nodata
    gdf = gdf[~gdf.value.isin([land.rio.nodata])].reset_index(drop=True)
    # Assign values to landcover
    gdf = gdf.merge(lookup_table, left_on='value', right_on='corine', how='left')
    gdf = gdf.rename(columns={'value': 'id'})
    # Clip to catchment
    gdf = gpd.clip(gdf, catchment)
    if gdf.crs != "EPSG:4326": gdf = gdf.to_crs("EPSG:4326")
    gdf = gdf.explode(index_parts=False)
    gdf = gdf[gdf.geometry.geom_type == 'Polygon']
    gdf = gdf.reset_index(drop=True)
    return gdf

async def renew_redis_lock(lock, ttl=120, interval=30):
    while True:
        await asyncio.sleep(interval)
        try:
            await lock.extend(ttl, replace_ttl=True)
        except Exception: return False

def write_forcing(directory:str, start:str, end:str, time_zone:str, interval:int, df:pd.DataFrame):
    forcing_dir = os.path.normpath(os.path.join(directory, 'forcing'))
    raw_path = os.path.normpath(os.path.join(directory, 'raw', 'dtm_raw.tif'))
    try:
        if not os.path.exists(raw_path):
            return {'status': 'error', 'message': "Cannot find terrain data. Please process terrain first."}
        if os.path.exists(forcing_dir): functions.safe_remove(forcing_dir)
        os.makedirs(forcing_dir, exist_ok=True)
        forcing = {'start': start, 'end': end, 'interval': interval}
        forcing_path = os.path.join(forcing_dir, 'forcing.json')
        with open(forcing_path, 'w', encoding='utf-8', errors='ignore') as f:
            json.dump(forcing, f)
        df = df.dropna(subset=['Time'])
        df['Time'] = functions.local_to_utc(df['Time'], time_zone)
        df["Time"] = pd.to_datetime(df["Time"], errors="coerce", utc=True)
        invalid_mask = df["Time"].isna()
        invalid_count = int(invalid_mask.sum())
        if invalid_count:
            error_rows = df.loc[invalid_mask].to_csv(index=False, header=False, sep=',', lineterminator='\n')
            return {'status': 'error', 'message': f"WARNING: Removed {invalid_count} rows with invalid timestamps.n\n\n{error_rows}"}
        df = df.loc[df["Time"].notna()].copy()
        if df.empty:
            return {"status": "error", "message": "No valid timestamps remain after datetime conversion."}
        df = df.set_index("Time")
        df.index.name = "Time"
        df = df.sort_index()
        required_columns = [
            "Precipitation (mm)", "Temperature (°C)", "Shortwave Radiation (W/m²)",
            "Longwave Radiation (W/m²)", "Wind Speed (m/s)", "Pressure (hPa)",
        ]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return {"status": "error", "message": f"Missing weather columns: {', '.join(missing_columns)}"}
        # Resampling
        precip_col = "Precipitation (mm)"    
        for col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce")
        if df.index.has_duplicates:
            df = df.groupby(level=0).mean(numeric_only=True).sort_index()
        if precip_col in df.columns:
            precip = df[precip_col].resample(interval).sum(min_count=1)
        resampled = df.resample(interval).asfreq()
        resampled = resampled.loc[resampled.index.notna()].copy()
        resampled = resampled.sort_index()
        # Interpolate numeric variables.
        numeric_cols = resampled.select_dtypes(include="number").columns
        other_cols = resampled.columns.difference(numeric_cols)
        if len(numeric_cols):
            resampled[numeric_cols] = resampled[numeric_cols].interpolate(
                method="time", limit_area="inside"
            )
        if len(other_cols): resampled[other_cols] = resampled[other_cols].ffill()
        # Restore precipitation using its separately aggregated values.
        if precip_col in df.columns: resampled[precip_col] = precip.reindex(resampled.index)
        df = resampled.ffill().bfill().reset_index()
        # Create forcing nc file
        time = pd.to_datetime(df['Time'], utc=True).dt.tz_localize(None).to_numpy(dtype=np.datetime64)
        out_path, datasets = os.path.normpath(os.path.join(forcing_dir, "weather_forcing.nc")), {}
        with rasterio.open(raw_path) as src:
            dem_array, crs = src.read(1), src.crs
            transform, nodata = src.transform, src.nodata
        mask_nan = ~np.isfinite(dem_array)
        if nodata is not None: mask_nan |= (dem_array == nodata)
        ny, nx = dem_array.shape[0], dem_array.shape[1]
        chunksizes = (1, min(256, ny), min(256, nx))
        mask_da = da.from_array(mask_nan, chunks=chunksizes[1:])
        forcing = {
            'precip': ['Precipitation (mm)', 'mm'], 'temp': ['Temperature (°C)', 'degC'],
            'kin': ['Shortwave Radiation (W/m²)', 'W/m^2'], 'kout': ['Longwave Radiation (W/m²)', 'W/m^2'],
            'wind': ['Wind Speed (m/s)', 'm/s'], 'press_msl': ['Pressure (hPa)', 'hPa']
        }
        for var, (col, unit) in forcing.items():
            values = df[col].to_numpy().astype(np.float32)
            values_da = da.from_array(values, chunks=(24,))
            data_3d = da.broadcast_to(values_da[:, None, None], shape=(len(values), ny, nx),)
            data_3d = da.where(mask_da[None, :, :], np.float32(0.0), data_3d,)
            datasets[var] = (('time', 'y', 'x'), data_3d, {'units': unit})
        x_coords = transform.c + (np.arange(nx) + 0.5) * transform.a
        y_coords = transform.f + (np.arange(ny) + 0.5) * transform.e
        ds_final = xr.Dataset(data_vars=datasets, coords={"time": time, "y": y_coords, "x": x_coords})
        ds_final = ds_final.rio.set_spatial_dims(x_dim="x", y_dim="y")
        ds_final = ds_final.rio.write_crs(crs, inplace=False)
        for var in datasets:
            ds_final[var].attrs["grid_mapping"] = "spatial_ref"
        # Add CRS metadata explicitly
        crs_attrs = ds_final["spatial_ref"].attrs
        ds_final.attrs["crs"] = crs.to_string()
        ds_final.attrs["spatial_ref"] = crs_attrs.get("spatial_ref", crs.to_wkt())
        ds_final["time"].encoding = {
            "units": "hours since 1900-01-01 00:00:00",
            "calendar": "proleptic_gregorian", "dtype": "int64",
            "zlib": True, "complevel": 4, "shuffle": True,
        }
        encoding = {
            var: {"zlib": True, "complevel": 4, "shuffle": True, 
                "chunksizes": chunksizes, "_FillValue": -9999.0, "dtype": "float32"
            } for var in ds_final.data_vars
        }
        ds_final = ds_final.chunk({"time": 1, "y": chunksizes[1], "x": chunksizes[2]})
        ds_final.to_netcdf(out_path, engine='netcdf4', encoding=encoding)
        return {"status": "completed", "message": "Weather forcing data saved successfully."}
    except Exception as e:
        print('/write_forcing:\n==============')
        traceback.print_exc()
        return {"status": "failed", "message": str(e)}

def sanitize_nc_attrs(ds, logger=None):
    valid = (str, bytes, Number, np.number, np.ndarray, list, tuple)
    for name in [None, *ds.variables]:
        obj = ds if name is None else ds[name]
        for k in [k for k, v in obj.attrs.items() if not isinstance(v, valid)]:
            v = obj.attrs.pop(k)
            if logger: logger.warning(f"Removed attr '{k}' from {name or 'dataset'}: {v}")