import os, traceback, datetime, json
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse
from config import PROJECT_ROOT
from services import calibration_functions, functions
from datetime import timezone, datetime, timedelta
import pandas as pd, numpy as np

router, processes = APIRouter(), {}

    
@router.post("/calibration_project")
async def calibration_project(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    try:
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        input_dir = os.path.join(PROJECT_ROOT, project_name, "input")
        mdu_path = os.path.join(input_dir, [f for f in os.listdir(input_dir) if f.endswith(".mdu")][0])
        if not os.path.exists(mdu_path):
            return JSONResponse({'status': 'error', 'message': f"MDU file not found in project '{project_name}'."})
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibrations")
        os.makedirs(calibration_dir, exist_ok=True)
        with open(mdu_path, 'r') as mdu_file:
            mdu_content = mdu_file.readlines()
        # Extract start and end dates from MDU file
        start_date = calibration_functions.get_values_from_mdu(mdu_content, 'TStart')
        end_date = calibration_functions.get_values_from_mdu(mdu_content, 'TStop')
        ref_date = calibration_functions.get_values_from_mdu(mdu_content, 'RefDate')
        unit = calibration_functions.get_values_from_mdu(mdu_content, 'Tunit')
        ref_dt = datetime.strptime(ref_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        if unit == 'S':
            start_dt = ref_dt + timedelta(seconds=int(start_date))
            end_dt = ref_dt + timedelta(seconds=int(end_date))
        elif unit == 'M':
            start_dt = ref_dt + timedelta(minutes=int(start_date))
            end_dt = ref_dt + timedelta(minutes=int(end_date))
        elif unit == 'H':
            start_dt = ref_dt + timedelta(hours=int(start_date))
            end_dt = ref_dt + timedelta(hours=int(end_date))
        start_date = start_dt.strftime('%Y-%m-%d %H:%M:%S')
        end_date = end_dt.strftime('%Y-%m-%d %H:%M:%S')
        content = {'start': start_date, 'end': end_date}
        return JSONResponse({'content': content})
    except Exception as e:
        print('/calibration_project:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/obs_calibration_upload")
async def obs_calibration_upload(file: UploadFile = File(...), projectName: str = Form(...), 
    simStart: str = Form(...), simEnd: str = Form(...), user=Depends(functions.basic_auth)):
    try:
        project_name, _ = functions.project_definer(projectName, user)
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibrations")
        path = os.path.join(calibration_dir, file.filename)
        with open(path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk: break
                f.write(chunk)
        df, content = pd.read_csv(path, low_memory=False), {}
        if df.empty: return JSONResponse({'status': 'error', 'message': "Uploaded CSV file is empty."})
        sim_start, sim_end = pd.to_datetime(simStart), pd.to_datetime(simEnd)
        time_column = df.columns[0]
        df[time_column] = pd.to_datetime(df[time_column])
        start_time, end_time = df[time_column].iloc[0], df[time_column].iloc[-1]
        content['start'] = pd.to_datetime(start_time).strftime('%Y-%m-%d %H:%M:%S')
        content['end'] = pd.to_datetime(end_time).strftime('%Y-%m-%d %H:%M:%S')
        df_filled = df[(df[time_column] >= sim_start) & (df[time_column] <= sim_end)]
        if df_filled.empty: 
            return JSONResponse({
                'status': 'error', 'message': f"No data in the uploaded CSV file falls within the simulation dates ({simStart} to {simEnd})."
            })
        df_filled = df_filled.replace([np.inf, -np.inf], np.nan)
        df_filled[time_column] = df_filled[time_column].dt.strftime('%Y-%m-%d %H:%M:%S')
        content['data'] = df_filled.astype(object).where(df_filled.notna(), None).to_numpy().tolist()
        return JSONResponse({'status': 'ok', 'content': content})
    except Exception as e:
        print('/obs_calibration_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})



















