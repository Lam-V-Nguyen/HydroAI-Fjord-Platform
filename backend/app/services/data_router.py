import os, pickle, json, traceback, asyncio, threading
from fastapi import APIRouter, Request, Depends, Query, UploadFile, File
from fastapi.responses import JSONResponse
from services import functions, data_functions
from config import PROJECT_ROOT
import geopandas as gpd, pandas as pd, numpy as np
from services.data_functions import Regnbyge as regnbyge

router, processes = APIRouter(), {}

@router.post("/save_client")
async def save_client(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        client_name, client_secret = body.get('clientName', ''), body.get('clientSecret', '')
        client_username, client_password = body.get('clientUsername', ''), body.get('clientPassword', '')
        source_dir = os.path.join(PROJECT_ROOT, project_name, "Regnbyge")
        if not os.path.exists(source_dir): os.makedirs(source_dir)
        path = os.path.join(source_dir, 'regnbyge.json')
        content = {'client_id': client_name, 'client_secret': client_secret,
            'client_username': client_username, 'client_password': client_password
        }
        with open(path, 'w', encoding='utf-8', errors='ignore') as f:
            json.dump(content, f)
        return JSONResponse({'message': 'Registration information is saved successfully.'})
    except Exception as e:
        print('/save_client:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/load_client")
async def load_client(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    source_dir = os.path.join(PROJECT_ROOT, project_name, "Regnbyge")
    path = os.path.join(source_dir, 'regnbyge.json')
    content = {'client_id': '', 'client_secret': '',
        'client_username': '', 'client_password': ''
    }
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = json.load(f)
    return JSONResponse({'content': content})
    
@router.post("/reset_station")
async def reset_station(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        source_dir = os.path.join(PROJECT_ROOT, project_name, "Regnbyge")
        flow_checked, level_checked, rain_checked = body.get('flow'), body.get('level'), body.get('rain')
        if flow_checked: functions.safe_remove(os.path.join(source_dir, 'flow.pkl'))
        if level_checked: functions.safe_remove(os.path.join(source_dir, 'level.pkl'))
        if rain_checked: functions.safe_remove(os.path.join(source_dir, 'rain.pkl'))
        return JSONResponse({'message': 'Station(s) reset successfully.'})
    except Exception as e:
        print('/reset_station:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/init_station")
async def init_station(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        key, client_name = body.get('key'), body.get('clientName', '')
        client_secret, client_username = body.get('clientSecret', ''), body.get('clientUserName', '')
        client_password = body.get('clientPassword', '')
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        source_dir = os.path.join(PROJECT_ROOT, project_name, "Regnbyge")
        if not os.path.exists(source_dir): os.makedirs(source_dir)
        path = os.path.normpath(os.path.join(source_dir, f'{key}.pkl'))
        if not os.path.exists(path):
            obj = regnbyge(client_name, client_secret, client_username, client_password)
            print("Loading data from Regnbyge.no ...")
            token = obj.get_Token()
            if token is None: return JSONResponse({'status': 'error', 'message': f"Error: Could not get token."})
            df = obj.get_Station(key)
            if not df.empty:
                geometry = gpd.points_from_xy(df['x'], df['y'])
                station = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:32633')
                station = station.drop(columns=['x', 'y'])
                station['mode'] = key
                if 'geoX' in station.columns: station = station.drop(columns=['geoX'])
                if 'geoY' in station.columns: station = station.drop(columns=['geoY'])
                station = station.to_crs('EPSG:4326')
                with open(path, 'wb') as f: pickle.dump(station, f)
        else:
            with open(path, 'rb') as f: station = pickle.load(f)
        if station.empty: return JSONResponse({'status': 'error', 'message': f"No '{key}' data available."})
        name = station[['name', 'type']].values.tolist()
        content = {'name': name, 'point': json.loads(station.to_json())}
        return JSONResponse({'status': 'ok', 'content': content})
    except Exception as e:
        print('/init_station:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/plot_station")
async def plot_station(request: Request):
    try:
        body = await request.json()
        id, mode, client_name = body.get('id'), body.get('mode'), body.get('clientName', '')
        name, time_zone, client_password = body.get('name'), body.get('timeZone'), body.get('clientPassword', '')
        client_secret, client_username = body.get('clientSecret', ''), body.get('clientUserName', '')
        start, end, interval = body.get('startTime'), body.get('endTime'), body.get('interval')
        start_utc = functions.local_to_utc(start, time_zone)
        end_utc = functions.local_to_utc(end, time_zone)
        if start_utc >= end_utc:
            return JSONResponse({'status': 'error', 'message': "Error: 'Start time' must be earlier than 'End time'."})
        obj = regnbyge(client_name, client_secret, client_username, client_password)
        df = obj.get_Values(mode, id, start_utc, end_utc, interval)
        if df.empty:
            return JSONResponse({'status': 'error', 'message': f"No data available for station '{name}' between '{start}' and '{end}'."})
        if 'id' in df.columns: df = df.drop(columns=['id'])
        # Convert time back to local time zone
        df['timestamp'] = functions.utc_to_local(df['timestamp'], time_zone)
        content = {'columns': df.columns.tolist(), 'rows': df.values.tolist()}
        return JSONResponse({'status': 'ok', 'content': content})
    except Exception as e:
        print('/plot_station:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/download_station")
async def download_station(request: Request):
    try:
        body = await request.json()
        mode, download_interval = body.get('mode'), body.get('downloadInterval')
        start, end = body.get('startTime'), body.get('endTime')
        id, time_zone = body.get('id'), body.get('timeZone')
        client_name, client_secret = body.get('clientName', ''), body.get('clientSecret', '')
        client_username, client_password = body.get('clientUserName', ''), body.get('clientPassword', '')
        start_utc = functions.local_to_utc(start, time_zone)
        end_utc = functions.local_to_utc(end, time_zone)
        if start_utc >= end_utc:
            return JSONResponse({'status': 'error', 'message': "Error: 'Start time' must be earlier than 'End time'"})
        obj = regnbyge(client_name, client_secret, client_username, client_password)
        df = obj.get_Values(mode, id, start_utc, end_utc, download_interval)
        if df.empty: 
            return JSONResponse({'status': 'error', 'message': f"No data available between '{start}' and '{end}'."})
        if 'id' in df.columns: df = df.drop(columns=['id'])
        df['timestamp'] = functions.utc_to_local(df['timestamp'], time_zone)
        csv_string = df.to_csv(index=False)
        return JSONResponse({'status': 'ok', 'content': csv_string})
    except Exception as e:
        print('/download_station:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.get("/log_tail_download_era5/{project_name}")
async def log_tail_download_era5(project_name: str, offset: int = Query(0),
    log_file: str = Query(""), user=Depends(functions.basic_auth)):
    project_name, _ = functions.project_definer(project_name, user)
    log_path, lines = os.path.join(PROJECT_ROOT, project_name, log_file), []
    log_path = os.path.normpath(log_path)
    if not os.path.exists(log_path): return {"lines": lines, "offset": 0, "reset": False}
    file_size = os.path.getsize(log_path)
    reset = offset > file_size
    if reset: offset = 0
    with open(log_path, "r", encoding=functions.encoding_detect(log_path), errors="replace") as f:
        f.seek(offset)
        data = f.read()
        new_offset = f.tell()
    return {"lines": data.splitlines(), "offset": new_offset, "reset": reset}

@router.post("/data_upload_gis")
async def data_upload_gis(file: UploadFile = File(...)):
    try:
        gdf = gpd.read_file(file.file)
        if gdf.crs is None or gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        return JSONResponse({"status": "ok", "content": json.loads(gdf.to_json())})
    except Exception as e:
        print('/data_upload_gis:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": str(e)})
    finally: 
        await file.close()



@router.post("/check_download_status_era5")
async def check_download_status_era5(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    key = f"{project_name}:era5"
    info = processes.get(key)
    if info is None:
        return JSONResponse({"status": "idle", "message": "No download running."})
    status, message = info["status"], info.get("message", "")
    if status in ("finished", "failed", "error"):
        asyncio.create_task(functions.delete_process(processes, key, 1))
    return JSONResponse({"status": status, "message": message})

@router.post("/download_era5")
async def download_era5(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    dir = os.path.join(PROJECT_ROOT, project_name)
    redis, key_process = request.app.state.redis, f"{project_name}:era5"
    lock = redis.lock(key_process, timeout=1000, blocking_timeout=10)
    async with lock:
        # Check if process already running
        if key_process in processes and processes[key_process]["status"] == "running":
            return JSONResponse({"status": "running", "message": 'Data downloading in progress.'})
        lat, lon, time_zone = float(body.get('lat')), float(body.get('lon')), body.get('timeZone')
        start, end, variables = body.get('startTime'), body.get('endTime'), body.get('variables')
        processes[key_process] = {"status": "running", "message": "Preparing download..."}
        threading.Thread(
            target=data_functions.era5_downloader, 
            args=(dir, processes, key_process, variables, lat, lon, start, end, time_zone), daemon=True
        ).start()
    return JSONResponse({"status": "ok", "message": "Weather downloading started"})

@router.post("/upload_era5_csv")
async def upload_era5_csv(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        time_zone = body.get('timeZone')
        path = os.path.join(PROJECT_ROOT, project_name, "era5_data.csv")
        if not os.path.exists(path): 
            return JSONResponse({'status': 'error', 'message': 'No data found.\nPlease download data first.'})
        df = pd.read_csv(path)
        df['time'] = pd.to_datetime(df['index'], utc=True)
        df['time'] = functions.utc_to_local(df['time'], time_zone)
        columns = [data_functions.var_revert[x] for x in df.columns]
        content = df.values.tolist()
        df = df.rename(columns={'time': 'Time'})
        functions.safe_remove(path)
        return JSONResponse({'status': 'ok', 'columns': columns, 'content': content})
    except Exception as e:
        print('/upload_era5_csv:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/save_era5")
async def save_era5(request: Request):
    try:
        body = await request.json()
        data = body.get('data')
        df = pd.DataFrame(data['rows'], columns=data['columns'])
        df = df.dropna(subset=['Time'], how='all')
        df = df.replace([np.inf, -np.inf], np.nan)
        csv_string = df.to_csv(index=False)
        return JSONResponse({'status': 'ok', 'message': 'Saved successfully.', 'content': csv_string})
    except Exception as e:
        print('/save_era5:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})
