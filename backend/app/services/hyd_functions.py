import os, shutil, traceback, sys, cdsapi, calendar
from config import PROJECT_ROOT
from services import flow_functions, functions
from datetime import datetime
from pathlib import Path
import pandas as pd, xarray as xr, numpy as np
from services.flow_functions import StreamToLogger
from dateutil.relativedelta import relativedelta

dataset, resolution, delta = 'reanalysis-era5-single-levels', 0.25, 0.125

def meteo_downloader(project_name, processes, lat, lon, start, end, key):
    project_dir = os.path.join(PROJECT_ROOT, project_name)
    log_path = os.path.normpath(os.path.join(project_dir, "log.txt"))
    if os.path.exists(log_path): os.remove(log_path)
    logger = flow_functions.setup_logger(key, log_path)
    CDS_url, CDS_key = os.getenv('CDS_URL'), os.getenv('CDS_API_KEY')
    config_path = Path.home() / '.cdsapirc'
    if not config_path.exists():
        logger.info("Creating .cdsapirc ...")
        config_path.write_text(f"url: {CDS_url}\nkey: {CDS_key}\n", encoding='utf-8')
        logger.info(f"Created at: {config_path}")
    download_dir = os.path.join(project_dir, 'download')
    if not os.path.exists(download_dir): os.makedirs(download_dir)
    # Setup variables
    variables = {
        '2m_temperature': 't2m', # Air Temperature
        '2m_dewpoint_temperature': 'd2m', # Dew Point Temperature
        'total_cloud_cover': 'tcc', # Cloud Cover
        'surface_solar_radiation_downwards': 'ssrd', # Shortwave radiation
    }
    weather, csv_path = pd.DataFrame(), os.path.join(project_dir, f"{key}.csv")
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    try:
        logger.info("Meteo downloader started")
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        start_time = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(end, '%Y-%m-%d %H:%M:%S')
        lat_new = round(float(lat) / resolution) * resolution
        lon_new = round(float(lon) / resolution) * resolution
        area = [lat_new + delta, lon_new - delta, lat_new - delta, lon_new + delta]
        # Download ERA5 data
        logger.info("Downloading ERA5 data...")
        client = cdsapi.Client(quiet=False, debug=False)
        current = start_time.replace(day=1)
        while current <= end_time:
            year, month = current.year, current.month
            last_day = calendar.monthrange(year, month)[1]
            month_start = datetime(year, month, 1)
            month_end = datetime(year, month, last_day, 23)
            # Clip by requested range
            actual_start = max(start_time, month_start)
            actual_end = min(end_time, month_end)
            # Days to download
            days = [f"{d:02d}" for d in range(actual_start.day, actual_end.day + 1)]
            df_temp = pd.DataFrame()
            for id, var in variables.items():
                logger.info(f"Downloading variable: {id}")
                request = {
                    'product_type': 'reanalysis', 'variable': [id],
                    'year': [str(year)], 'month': [f"{month:02d}"], 'day': days,
                    'time': [f"{h:02d}:00" for h in range(24)], 'area': area,
                    'data_format': 'netcdf', 'download_format': 'unarchived'
                }
                out_file = f"{year}_{month:02d}_{var}.nc"
                out_path = os.path.normpath(os.path.join(download_dir, out_file))
                client.retrieve(dataset, request, out_path)
                logger.info(f"Save data to: {out_path}")
                with xr.open_dataset(out_path) as ds:
                    df = pd.DataFrame(index=pd.to_datetime(ds['valid_time'].values))
                    df[var] = ds[var].values.flatten()
                df_temp = pd.concat([df_temp, df], axis=1)
                functions.safe_remove(out_path)
            weather = pd.concat([weather, df_temp], axis=0)
            current += relativedelta(months=1)
        weather['t2m'], weather['d2m'] = weather['t2m'] - 273.15, weather['d2m'] - 273.15
        weather['ssrd'], weather['tcc'] = weather['ssrd']/3600, weather['tcc']*100
        es = 6.112 * np.exp((17.67 * weather['t2m']) / (weather['t2m'] + 243.5))
        e = 6.112 * np.exp((17.67 * weather['d2m']) / (weather['d2m'] + 243.5))
        weather['Humidity [%]'] = np.clip(100 * e / es, 0, 100)
        weather = weather.drop(columns=['d2m'], axis=0)
        new_columns = {'t2m':'Air temperature [°C]', 'tcc': 'Cloud coverage [%]', 'ssrd': 'Solar radiation [W/m2]'}
        weather = weather.rename(columns=new_columns)
        weather = weather[['Humidity [%]', 'Air temperature [°C]', 'Cloud coverage [%]', 'Solar radiation [W/m2]']]
        weather.index.name = 'Time'
        weather.to_csv(csv_path)
        logger.info(f"Meteo saved: {csv_path}")
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        logger.info("Temporary monthly files removed")
        logger.handlers[0].flush()
        processes[project_name] = {"status": "finished", "message": "\nMeteo download completed.\n\n"}
    except Exception as e:
        print('/meteo_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Meteo download failed")
        processes[project_name] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

def wind_downloader(project_name, processes, lat, lon, start, end, key):
    project_dir = os.path.join(PROJECT_ROOT, project_name)
    log_path = os.path.normpath(os.path.join(project_dir, "log.txt"))
    if os.path.exists(log_path): os.remove(log_path)
    logger = flow_functions.setup_logger(key, log_path)
    CDS_url, CDS_key = os.getenv('CDS_URL'), os.getenv('CDS_API_KEY')
    config_path = Path.home() / '.cdsapirc'
    if not config_path.exists():
        logger.info("Creating .cdsapirc ...")
        config_path.write_text(f"url: {CDS_url}\nkey: {CDS_key}\n", encoding='utf-8')
        logger.info(f"Created at: {config_path}")
    download_dir = os.path.join(project_dir, 'download')
    if not os.path.exists(download_dir): os.makedirs(download_dir)
    # Setup variables
    variables = {
        '10m_u_component_of_wind': 'u10', '10m_v_component_of_wind': 'v10', # Wind
    }
    weather, csv_path = pd.DataFrame(), os.path.join(project_dir, f"{key}.csv")
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    try:
        logger.info("Wind downloader started")
        logger.info(f"Starting time: {start}   --   Ending time: {end}")
        start_time = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(end, '%Y-%m-%d %H:%M:%S')
        lat_new = round(float(lat) / resolution) * resolution
        lon_new = round(float(lon) / resolution) * resolution
        area = [lat_new + delta, lon_new - delta, lat_new - delta, lon_new + delta]
        # Download ERA5 data
        logger.info("Downloading ERA5 data...")
        client = cdsapi.Client(quiet=False, debug=False)
        current = start_time.replace(day=1)
        while current <= end_time:
            year, month = current.year, current.month
            last_day = calendar.monthrange(year, month)[1]
            month_start = datetime(year, month, 1)
            month_end = datetime(year, month, last_day, 23)
            # Clip by requested range
            actual_start = max(start_time, month_start)
            actual_end = min(end_time, month_end)
            # Days to download
            days = [f"{d:02d}" for d in range(actual_start.day, actual_end.day + 1)]
            df_temp = pd.DataFrame()
            for id, var in variables.items():
                logger.info(f"Downloading variable: {id}")
                request = {
                    'product_type': 'reanalysis', 'variable': [id],
                    'year': [str(year)], 'month': [f"{month:02d}"], 'day': days,
                    'time': [f"{h:02d}:00" for h in range(24)], 'area': area,
                    'data_format': 'netcdf', 'download_format': 'unarchived'
                }
                out_file = f"{year}_{month:02d}_{var}.nc"
                out_path = os.path.normpath(os.path.join(download_dir, out_file))
                client.retrieve(dataset, request, out_path)
                logger.info(f"Save data to: {out_path}")
                with xr.open_dataset(out_path) as ds:
                    df = pd.DataFrame(index=pd.to_datetime(ds['valid_time'].values))
                    df[var] = ds[var].values.flatten()
                df_temp = pd.concat([df_temp, df], axis=1)
                functions.safe_remove(out_path)
            weather = pd.concat([weather, df_temp], axis=0)
            current += relativedelta(months=1)
        weather['Magnitude [m/s]'] = np.sqrt(weather['u10']**2 + weather['v10']**2)
        angle = (np.degrees(np.arctan2(-weather['u10'], -weather['v10'])) + 360) % 360
        weather['Angle [deg]'] = angle.round(1)
        weather = weather.drop(columns=['u10', 'v10'], axis=0)
        weather = weather[['Magnitude [m/s]', 'Angle [deg]']]
        weather.index.name = 'Time'
        weather.to_csv(csv_path)
        logger.info(f"Wind saved: {csv_path}")
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        logger.info("Temporary monthly files removed")
        logger.handlers[0].flush()
        processes[project_name] = {"status": "finished", "message": "\nWind download completed.\n\n"}
    except Exception as e:
        print('/wind_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Wind download failed")
        processes[project_name] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)



