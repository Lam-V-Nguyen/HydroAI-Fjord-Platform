import os, dotenv, base64, requests
import traceback, sys, shutil, cdsapi, calendar
import pandas as pd, xarray as xr, numpy as np
from services import functions, flow_functions
from pathlib import Path
from services.flow_functions import StreamToLogger
from datetime import datetime
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
    'time': 'Time', 'wind_speed': 'Wind Speed (m/s)', 
    'wind_direction': 'Wind Direction (degrees)'
}

class Regnbyge():
    def __init__(self) -> None:
        dotenv.load_dotenv()
        self.url = os.getenv('FLOW_URL')
        self.client = os.getenv('FLOW_CLIENT_ID')
        self.client_secret = os.getenv('FLOW_CLIENT_SECRET')
        self.username = os.getenv('FLOW_USERNAME')
        self.password = os.getenv('FLOW_PASSWORD')
        self.token = self.get_Token()

    def get_Token(self):
        # Encode client_id:client_secret to Base64
        auth_string = f"{self.client}:{self.client_secret}"
        auth_bytes = auth_string.encode('utf-8')
        auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')
        # Define the headers
        headers = {'Authorization': f'Basic {auth_base64}',
                   'Accept': 'application/json',
                   'Content-Type': 'application/x-www-form-urlencoded'}
        # Define the body parameters (in x-www-form-urlencoded format)
        body = {'username': self.username, 'password': self.password,
                'scope': 'openid regnbyge', 'grant_type': 'password'}
        token_url = os.getenv('FLOW_URL_TOKEN')
        response = requests.request("POST", token_url, headers=headers, data=body)
        if response.status_code == 200: return response.json().get('access_token')
        else: return None

    def get_Station(self, variable):
        headers = {'Accept': 'application/json', 'Authorization': f'Bearer {self.token}'}
        url_objects = f'{self.url}/{variable}'
        response = requests.request("GET", url_objects, headers=headers)
        ids, rows = response.json(), []
        if not ids: return pd.DataFrame()
        for station_id in ids:
            url = f'{url_objects}/{station_id}'
            res = requests.get(url, headers=headers)
            if res.status_code == 200: rows.append(res.json())
        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows)
        # Delete columns with all NaN values
        df.dropna(axis=1, how='all', inplace=True)
        # Delete rows with all NaN values
        df.dropna(axis=0, how='all', inplace=True)
        df.reset_index(inplace=True, drop=True)
        df = df.where(pd.notnull(df), None)
        return df
    
    def get_Values(self, variable:str, ids:list, from_date, end_date, agg:str='Raw'):
        '''
        agg: Raw, Minute, FiveMinute, Hour, Day
        fromDate, toDate: 'YYYY-mm-dd HH:MM:SS' in UTC
        '''
        start, end = from_date.isoformat(), end_date.isoformat()
        headers = {'accept': 'application/json', 'Authorization': f'Bearer {self.token}'}
        payload = {"ids": ids, "from": start, "to": end, "aggregation": agg}
        url = f'{self.url}/{variable}/values'
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except requests.RequestException: return pd.DataFrame()
        data, data_value = pd.DataFrame(), response.json()
        for item in data_value:
            if 'measurements' not in item or not item['measurements']: continue
            df_value = pd.DataFrame(item['measurements'])
            if variable=='flow': # Using Flow
                df = pd.DataFrame(data={'timestamp':pd.to_datetime(df_value['t'].values),
                    'level (m)':df_value['l'].values, 'velocity (m/s)':df_value['v'].values,
                    'discharge (m³/s)':df_value['q'].values})
            elif variable=='level': # Using Level
                df = pd.DataFrame(data={'timestamp':pd.to_datetime(df_value['t'].values),
                    'level (m)':df_value['l'].values})
            elif variable=='rain': # Using Rainfall
                df = pd.DataFrame(data={'timestamp':pd.to_datetime(df_value['t'].values),
                    'rainfall (m)':df_value['r'].values})
            # elif variable=='overflow': # Using Overflow
            #     pass
            # elif variable=='temperature': # Using Temperature
            #     pass

            # elif variable=='evaporation': # Using Evaporation
            #     pass
            # elif variable=='weir': # Using Weir
            #     pass
            df['id'] = item['id']
            if df.drop(columns=['timestamp']).isna().all().all(): continue
            data = pd.concat([data, df], ignore_index=True)
        data = data.reset_index(drop=True)
        data = data.replace(float("nan"), None) # Fill NaN values
        return data

def era5_downloader(dir:str, processes:dict, key_process:str, vars:list, 
    lat:float, lon:float, start:str, end:str, time_zone:str, buffer:float=0.01):
    # Prepare forcing data from the global model ARE5
    # Source: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download
    # Remove old log
    log_path = os.path.join(dir, "log.txt")
    if os.path.exists(log_path): os.remove(log_path)
    logger = flow_functions.setup_logger("cdsapi", log_path)
    CDS_url, CDS_key = os.getenv('CDS_URL'), os.getenv('CDS_API_KEY')
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
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        start_time = functions.local_to_utc(start, time_zone).replace(tzinfo=None)
        end_time = functions.local_to_utc(end, time_zone).replace(tzinfo=None)
        # Download ERA5 data
        logger.info("Downloading ERA5 data...")
        client = cdsapi.Client(quiet=False, debug=False)
        current = start_time.replace(day=1)
        monthly_frames = []
        while current <= end_time:
            logger.info("=========================================================")
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
                logger.info("=========================================================")
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
        logger.info("=========================================================")
        logger.info("Checking valid files...")
        # Filter valid files
        logger.info(f"Year: {year}, Month: {month}")
        n = len(files) + len(bad_files)
        logger.info(f"Number of valid files: {len(files)}/{n}")
        logger.info(f"Number of invalid files: {len(bad_files)}/{n}")
        if len(bad_files) > 0:
            logger.info("Bad files:")
            for f in bad_files: logger.info(f" - {os.path.basename(f)}")
        logger.info("=========================================================")
        df_result.index = functions.utc_to_local(df_result.index, time_zone)
        month_df.index.name = 'Time'
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
        df_result.to_csv(csv_path, index=True)
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