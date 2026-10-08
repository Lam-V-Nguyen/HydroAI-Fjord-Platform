import os, shutil, traceback, sys, cdsapi, calendar, requests
from config import PROJECT_ROOT
from services import flow_functions, functions
from datetime import datetime
from pathlib import Path
import pandas as pd, xarray as xr, numpy as np, geopandas as gpd
from services.flow_functions import StreamToLogger
from dateutil.relativedelta import relativedelta

dataset, resolution, delta = 'reanalysis-era5-single-levels', 0.25, 0.125

def meteo_downloader(project_name, source, file_name, processes, process_key, lat, lon, start, end, time_zone, key):
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
        start_time = functions.local_to_utc(start, time_zone)
        end_time = functions.local_to_utc(end, time_zone)
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
                    df = pd.DataFrame(index=pd.to_datetime(ds['valid_time'].values, utc=True))
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
        weather.index = functions.utc_to_local(weather.index, time_zone)
        weather.to_csv(csv_path)
        logger.info(f"Meteo saved: {csv_path}")
        if os.path.exists(download_dir): shutil.rmtree(download_dir)
        logger.info("Temporary monthly files removed")
        logger.handlers[0].flush()
        processes[process_key] = {"status": "finished", "message": "\nMeteo download completed.\n\n"}
    except Exception as e:
        print('/meteo_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Meteo download failed")
        processes[process_key] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)
        if os.path.exists(log_path): functions.safe_remove(log_path)

def wind_downloader(project_name, source, processes, process_key, lat, lon, start, end, time_zone, key):
    project_dir = os.path.join(PROJECT_ROOT, project_name)
    log_path = os.path.normpath(os.path.join(project_dir, "log.txt"))
    if os.path.exists(log_path): os.remove(log_path)
    logger = flow_functions.setup_logger(key, log_path)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StreamToLogger(logger), StreamToLogger(logger)
    start_local = pd.Timestamp(start).tz_localize(time_zone)
    end_local = pd.Timestamp(end).tz_localize(time_zone) + pd.Timedelta(days=1)
    start_time, end_time = start_local.tz_convert('UTC'), end_local.tz_convert('UTC')
    if (start_time >= end_time): 
        logger.info("Start time must be before end time.")
        processes[process_key] = {"status": "failed", "message": "Start time must be before end time."}
    try:
        if (source == "nve-gts"):
            logger.info("Wind downloader started from NVE GTS.")
            logger.info(f"Starting time: {start}   --   Ending time: {end}")
            gdf = gpd.GeoDataFrame(
                geometry=gpd.points_from_xy([float(lon)], [float(lat)]), crs="EPSG:4326"
            ).to_crs("EPSG:25833")
            x, y = int(gdf.geometry.x.values[0]), int(gdf.geometry.y.values[0])
            start_date, end_date = start_time.strftime('%Y-%m-%d'), end_time.strftime('%Y-%m-%d')
            url = os.getenv('NVE_GTS_URL')
            themes = {'windSpeed10m1h': 'Wind Speed_10m (m/s)', 'windDirection10m1h': 'Wind Direction_10m (°)'}
            data_dict, timestamps = {}, None
            for theme_id, item in themes.items():
                logger.info(f"Downloading data for theme: {theme_id}")
                url_data = f"{url}/{x}/{y}/{start_date}/{end_date}/{theme_id}.json"
                res = requests.get(url_data, timeout=60)
                res.raise_for_status()
                data = res.json()
                if timestamps is None:
                    start = pd.to_datetime(data["StartDate"], format="%d.%m.%Y %H:%M:%S")
                    resolution = pd.Timedelta(minutes=data["TimeResolution"])
                    timestamps = pd.date_range(start=start, periods=len(data["Data"]), freq=resolution)
                data_dict[item] = data["Data"]
            df = pd.DataFrame(data_dict)
            df.insert(0, "Time", timestamps)
            df = df.sort_values("Time").reset_index(drop=True)
            df["Time"] = pd.to_datetime(df["Time"], utc=True)
            df = df[(df["Time"] >= start_time) & (df["Time"] < end_time)].copy()
            df['Time'] = functions.utc_to_local(df['Time'], time_zone)
            csv_path = os.path.normpath(os.path.join(project_dir, f'{key}.csv'))
            df.to_csv(csv_path, index=False)
            logger.info(f"Saved CSV to: {csv_path}")
            logger.info(f"Saved weather file successfully.")
            logger.handlers[0].flush()
            processes[process_key] = {"status": "finished", "message": "Weather download completed successfully.\n\n"}
        elif (source == "era5"):
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
            
            logger.info("Wind downloader started")
            logger.info(f"Starting time: {start}   --   Ending time: {end}")
            
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
            weather.index = functions.utc_to_local(weather.index, time_zone)
            weather.to_csv(csv_path)
            logger.info(f"Wind saved: {csv_path}")
            if os.path.exists(download_dir): shutil.rmtree(download_dir)
            logger.info("Temporary monthly files removed")
            logger.handlers[0].flush()
            processes[process_key] = {"status": "finished", "message": "\nWind download completed.\n\n"}
    except Exception as e:
        print('/wind_downloader:\n==============')
        traceback.print_exc()
        logger.exception("Weather download failed.")
        processes[process_key] = {"status": "failed", "message": str(e)}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)