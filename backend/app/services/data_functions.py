import os, dotenv, base64, requests
import traceback, sys, shutil, cdsapi, calendar
import pandas as pd, xarray as xr, numpy as np
from services import functions, flow_functions
from pathlib import Path
from services.flow_functions import StreamToLogger
from datetime import datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta

variables = {
    'total_precipitation': 'tp', # Precipitation
    '2m_temperature': 't2m', # Temperature
    '10m_u_component_of_wind': 'u10', '10m_v_component_of_wind': 'v10', # Wind
    'surface_pressure': 'sp',  # Pressure
    'surface_solar_radiation_downwards': 'ssrd', # Shortwave radiation
    'surface_thermal_radiation_downwards': 'strd', # Longwave radiation
    'total_cloud_cover': 'tcc', # Cloud cover
}

var_revert = {
    'tp': 'Total Precipitation (mm)', 't2m': 'Temperature (degC)',
    'u10': 'Wind (u Component) (m/s)', 'v10': 'Wind (v Component) (m/s)',
    'sp': 'Surface Pressure (Pa)', 'tcc': 'Total Cloud Cover (%)',
    'ssrd': 'Shortwave Radiation (W/m^2)', 'strd': 'Longwave Radiation (W/m^2)',
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

def era5_downloader(api_key:str, dir:str, processes:dict, key_process:str, vars:list, 
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
    try:
        logger.info("Weather downloader started")
        logger.info(f"Location: lat={lat}, lon={lon}")
        logger.info("="*70)
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        start_time = functions.local_to_utc(start, time_zone).replace(tzinfo=None)
        end_time = functions.local_to_utc(end, time_zone).replace(tzinfo=None)
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
            vals = {key: variables[key] for key in vars if key in variables.keys()}
            for key, var in vals.items():
                logger.info("="*35)
                logger.info(f"Downloading variable: {var}")
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
        logger.info("")
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
        logger.info("="*40)
        df_result.index = functions.utc_to_local(df_result.index, time_zone)
        df_result.index.name = 'Time'
        columns = df_result.columns.tolist()
        if 'tp' in columns: df_result['tp'] *= 1000
        if 't2m' in columns: df_result['t2m'] -= 273.15
        if 'tcc' in columns: df_result['tcc'] *= 100
        if 'ssrd' in columns: df_result['ssrd'] /= 3600
        if 'strd' in columns: df_result['strd'] /= 3600
        if 'wind_speed' in vars:
            df_result['wind_speed'] = np.sqrt(df_result['u10']**2 + df_result['v10']**2)
            df_result['wind_direction'] = np.arctan2(df_result['v10'], df_result['u10'])
        csv_path = os.path.join(dir, 'era5_data.csv')
        df_result = df_result.reset_index()
        df_result.to_csv(csv_path, index=False)
        logger.info(f"Saved CSV to: {csv_path}")
        logger.info(f"Saved forcing file successfully")
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        logger.info("Temporary monthly files removed")
        logger.handlers[0].flush()
        processes[key_process] = {"status": "finished", "message": "Weather download completed successfully.\n\n"}
    except Exception as e:
        print('/era5_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Weather download failed")
        processes[key_process] = {"status": "failed", "message": str(e)}
    finally:
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)

def met_downloader(api_key:str, url:str, dir:str, processes:dict, key_process:str, 
    ids:list, columns:list, vars:list, interval:str, start:str, end:str, time_zone:str):
    log_path = os.path.join(dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    logger = flow_functions.setup_logger("met", log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    start_local = pd.Timestamp(start).tz_localize(time_zone)
    end_local = pd.Timestamp(end).tz_localize(time_zone) + pd.Timedelta(days=1)
    start_time, end_time = start_local.tz_convert('UTC'), end_local.tz_convert('UTC')
    vars_new = [v.replace('PT1H', interval) for v in vars]
    try:
        logger.info("Weather downloader started.")
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        logger.info("="*60)
        all_observations = []
        for station in ids:
            station_id = station[0]
            logger.info(f"Downloading data for station: {station_id}")
            for i in range(len(vars_new)):
                element = vars_new[i]
                logger.info(f"Station: {station_id}, Element: {element}")
                params = {
                    "sources": station_id, "elements": element, 
                    "referencetime": f"{start_time.strftime('%Y-%m-%d')}/{end_time.strftime('%Y-%m-%d')}"
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
                    result['sourceId'], result['elementId'] = station_id, columns[i]
                    result = result[result["timeResolution"] == interval].copy()
                    all_observations.append(result)
                except requests.exceptions.RequestException as e:
                    logger.exception(f"Request failed for {station_id} | {element}: {e}")
            logger.info("*"*40)
        df = pd.concat(all_observations, ignore_index=True) if all_observations else pd.DataFrame()
        if df.empty:
            logger.error("No data downloaded")
            processes[key_process] = {"status": "failed", "message": "No data downloaded"}
            return
        df = df[['Time', 'sourceId', 'elementId', 'value']]
        df = df.pivot_table(
            index=["Time", "sourceId"], columns="elementId", values="value", aggfunc="first"
        ).reset_index()
        df.columns.name = None
        df["Time"] = pd.to_datetime(df["Time"], utc=True)
        df = df[(df["Time"] >= start_time) & (df["Time"] < end_time)].copy()
        df['Time'] = functions.utc_to_local(df['Time'], time_zone)
        if "Air Pressure (Pa)" in df.columns: df["Air Pressure (Pa)"] *= 100
        if "Cloud cover (%)" in df.columns: df["Cloud cover (%)"] = cloud_cover_to_percent(df["Cloud cover (%)"])
        csv_path = os.path.normpath(os.path.join(dir, 'met_data.csv'))
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