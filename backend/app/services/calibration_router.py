import os, traceback, datetime, shutil
from fastapi import APIRouter, Request, Depends, Query
from fastapi import UploadFile, File, Form, BackgroundTasks
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
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
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
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
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

@router.post("/check_calibration")
async def check_calibration(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    key = f"{project_name}:{body.get('key')}"
    info = processes.get(key)
    if not info: 
        return JSONResponse({"status": "not_started", "progress": 0, "message": 'No calibration running.', "his": []})
    if info["status"] in ("finished", "stopped", "failed"):
        response = {"status": info["status"], "progress": info["progress"], "message": info["message"], "his": info["history"]}
        processes.pop(key, None)
        return JSONResponse(response)
    return JSONResponse({"status": info["status"], "progress": info["progress"], "message": info["message"], "his": info["history"]})

@router.post("/start_calibration_iteration")
async def start_calibration_iteration(request: Request, background_tasks: BackgroundTasks, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get("projectName"), user)
        dir = os.path.join(PROJECT_ROOT, project_name)
        redis, key = request.app.state.redis, f"{project_name}:{body.get('key')}"
        lock = redis.lock(key, timeout=1000, blocking_timeout=10)
        async with lock:
            # Check if iteration already running
            if key in processes and processes[key]["status"] == "running":
                info = processes[key]
                return JSONResponse({
                    "status": info["status"], "progress": info["progress"], 
                    "message": info["message"], "his": info["history"]
                })
            processes[key] = {
                "status": "running", "progress": 0.0, "history": '',
                "message": 'Iteration data for calibration ...'
            }
            background_tasks.add_task(
                calibration_functions.run_iteration, dir, processes, body, key
            )
        return JSONResponse({"status": "started", "progress": 0.0, "message": f"Iteration started.", "his": []})
    except Exception as e:
        print('/start_calibration_iteration:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'failed', 'message': f"Error: {e}"})

@router.post("/check_sim_status_calibration")
async def check_sim_status_calibration(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    process_key = f"{project_name}:{body.get('key')}"
    info = processes.get(process_key)
    if not info: 
        return JSONResponse({"status": "not_started", "progress": 0, 
            "message": 'No simulation running'
        })
    status, progress = info.get("status"), info.get("progress", 0.0)
    current, total = info.get("current", 0), info.get("total", 0)
    if status == "finished":
        return JSONResponse({"status": "finished", "progress": 100.0,
            "message": info.get("message", "Simulation completed.")
        })
    if status in ("failed", "error"):
        return JSONResponse({"status": status, "progress": progress,
            "message": info.get("message", "Simulation failed.")
        })
    complete = f'Simulation ({current}/{total}): {progress}% completed.'
    return JSONResponse({"status": status, "progress": progress, "message": complete})

@router.get("/calibration_log_full/{project_name}")
async def calibration_log_full(project_name: str, log_file: str = Query(""), user=Depends(functions.basic_auth)):
    project_name, _ = functions.project_definer(project_name, user)
    log_path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "calibration", log_file))
    if not os.path.exists(log_path): return {"content": ""}
    with open(log_path, "r", encoding=functions.encoding_detect(log_path), errors="replace") as f:
        content = f.read()
    return {"content": content, "offset": os.path.getsize(log_path)}

@router.get("/calibration_log_tail/{project_name}")
async def calibration_log_tail(project_name: str, offset: int = Query(0), 
    log_file: str = Query(""), user=Depends(functions.basic_auth)):
    project_name, _ = functions.project_definer(project_name, user)
    log_path, lines = os.path.join(PROJECT_ROOT, project_name, "calibration", log_file), []
    log_path = os.path.normpath(log_path)
    if not os.path.exists(log_path): return {"lines": lines, "offset": 0}
    with open(log_path, "r", encoding=functions.encoding_detect(log_path), errors="replace") as f:
        f.seek(offset)
        for line in f:
            lines.append(line.rstrip())
    return {"lines": lines, "offset": os.path.getsize(log_path)}

@router.post("/start_sim_calibration")
async def start_sim_calibration(request: Request, background_tasks: BackgroundTasks, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        redis, process_key = request.app.state.redis, f"{project_name}:{body.get('key')}"
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
        sample_dir = os.path.join(calibration_dir, body.get("samplingName"))
        if not os.path.exists(sample_dir):
            return JSONResponse({"status": "error", "message": f"Sampling directory not found. Please run resampling first."})
        scenario_dir = os.path.join(sample_dir, "scenarios")
        list_sorted = sorted([int(x) for x in os.listdir(scenario_dir) if os.path.isdir(os.path.join(scenario_dir, x))])
        if not list_sorted:
            return JSONResponse({"status": "error", "message": "No simulation scenarios found."})
        lock = redis.lock(process_key, timeout=1000, blocking_timeout=10)
        async with lock:
            info = processes.get(process_key)
            # Check if simulation already running
            if info and info["status"] == "running":
                complete = f'Simulation ({info["current"]}/{info["total"]}): {info["progress"]}% completed.'
                return JSONResponse({"status": "running", "progress": info["progress"], "message": complete})
            processes[process_key] = {"progress": 0.0, "status": "running",
                "message": "Preparing data for simulation...", "current": 0, "total": len(list_sorted),
            }
            info = processes[process_key]
        # Remove old log
        log_path = os.path.join(calibration_dir, "log.txt")
        if os.path.exists(log_path): os.remove(log_path)
        background_tasks.add_task(
            calibration_functions.run_calibration, processes, process_key, scenario_dir, list_sorted, log_path
        )
        return JSONResponse({"status": "ok", "message": f"Simulation {project_name} started"})
    except Exception as e:
        print('/start_sim_calibration:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/get_stations_calibration")
async def get_stations_calibration(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
        scenario_dir = os.path.join(calibration_dir, 'scenarios')
        if not os.path.exists(scenario_dir):
            return JSONResponse({"status": "error", "message": f"Scenario directory not found. Please run iteration first."})
        list_sorted = sorted([int(x) for x in os.listdir(scenario_dir) if os.path.isdir(os.path.join(scenario_dir, x))])
        if not list_sorted:
            return JSONResponse({"status": "error", "message": "No simulation scenarios found. Please run simulation first."})
        output_checked, his_path = False, ''
        for scenario in list_sorted:
            output_dir = os.path.join(scenario_dir, str(scenario), "output")
            if not os.path.exists(output_dir): continue
            output_path = os.path.join(output_dir, "FlowFM_his.nc")
            if os.path.exists(output_path):
                output_checked, his_path = True, output_path
                break
        if not output_checked or not os.path.exists(his_path): 
            return JSONResponse({"status": "error", "message": "No simulation output found. Please run simulation first."})
        content = calibration_functions.get_station_from_his_file(his_path)
        if len(content) == 0: return JSONResponse({"status": "error", "message": "No station data found in the simulation."})
        return JSONResponse({"status": "ok", "content": content})
    except Exception as e:
        print('/get_stations_calibration:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/summarize_calibration")
async def summarize_calibration(request: Request, user=Depends(functions.basic_auth)):
    try:
        body, time_col = await request.json(), 'Time'
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
        param_samples_path = os.path.join(calibration_dir, 'parameter_samples.csv')
        if not os.path.exists(param_samples_path):
            return JSONResponse({"status": "error", "message": f"Parameter samples file not found. Please run iteration first."})
        scenario_dir = os.path.join(calibration_dir, 'scenarios')
        if not os.path.exists(scenario_dir):
            return JSONResponse({"status": "error", "message": f"Scenario directory not found. Please run iteration first."})
        list_sorted = sorted([int(x) for x in os.listdir(scenario_dir) if os.path.isdir(os.path.join(scenario_dir, x))])
        if not list_sorted:
            return JSONResponse({"status": "error", "message": "No simulation scenarios found. Please run simulation first."})
        summary_dir = os.path.join(calibration_dir, 'summary')
        if os.path.exists(summary_dir): shutil.rmtree(summary_dir)
        os.makedirs(summary_dir, exist_ok=True)
        sim_start, sim_end = body.get('simStart'), body.get('simEnd')
        obs_start, obs_end = body.get('obsStart'), body.get('obsEnd')
        obs_station, depth_selection = body.get('station'), body.get('depthSelection')
        depths_selected = [x.strip() for x in depth_selection.split(",")]
        summary_list, target_method, weight_method = [], body.get('targetValue'), body.get('weightValue')
        df_params = pd.read_csv(param_samples_path, index_col=0)
        # Process measured data
        measured_df = pd.DataFrame(data=body.get('obsData'), columns=[time_col, 'temperature', 'depth'])
        measured_df[time_col] = pd.to_datetime(measured_df[time_col], utc=True)
        measured_df["temperature"] = pd.to_numeric(measured_df["temperature"], errors='coerce')
        measured_df["depth"] = pd.to_numeric(measured_df["depth"], errors='coerce')
        measured_df = measured_df[[time_col, "temperature", "depth"]].dropna(subset=[time_col])
        sim_start = datetime.strptime(sim_start, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        sim_end = datetime.strptime(sim_end, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        obs_start = datetime.strptime(obs_start, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        obs_end = datetime.strptime(obs_end, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        t_start, t_end = max(sim_start, obs_start), min (sim_end, obs_end)
        # Detect measurement periods
        measured_df = measured_df[(measured_df[time_col] >= t_start) & (measured_df[time_col] <= t_end)]
        measured_df['new_profile'] = ((measured_df["depth"] < 1.5) & (measured_df["depth"].shift(1) > 5.0))
        measured_df['profile_id'] = measured_df['new_profile'].cumsum()
        obs_df = (
            measured_df.groupby("profile_id", group_keys=False)
            .apply(lambda g: calibration_functions.interpolate_profile_to_depths(g, depths_selected, 'Time'))
            .reset_index(drop=True).sort_values(time_col).reset_index(drop=True)
        )
        obs_path = os.path.join(calibration_dir, f'obs_{obs_station}.csv')
        obs_df.to_csv(obs_path, index=False)
        for case_id in list_sorted:
            c_dir = os.path.join(scenario_dir, str(case_id))
            df_sim = calibration_functions.read_and_interpolate_his(c_dir, obs_station, depths_selected, 'Time')
            if df_sim.empty: continue
            summary_path = os.path.join(summary_dir, f"sim_{case_id}.csv")
            if os.path.exists(summary_path): os.remove(summary_path)
            df_sim.to_csv(summary_path, index=False)
            target = []
            for d in depths_selected:
                obs_col, sim_col = f"obs_{d}", f"sim_{d}"
                obs_series = obs_df[[time_col, obs_col]].dropna().set_index(time_col).sort_index()
                obs_series = obs_series[~obs_series.index.duplicated(keep='first')]
                obs_clean = calibration_functions.remove_rolling_outliers(obs_series, obs_col)
                comb = df_sim[[sim_col]].reindex(df_sim.index.union(obs_clean.index)).sort_index()
                comb[sim_col] = comb[sim_col].interpolate(method="time")
                aligned = comb.loc[obs_clean.index, [sim_col]].join(obs_clean).dropna()
                
                if len(aligned) > 0:
                    score = calibration_functions.target_score(target_method, aligned[obs_col], aligned[sim_col])
                    target.append(score)
                else: target.append(np.nan)
            # Compute weighted
            weighted = calibration_functions.compute_weighted_rmse(depths_selected, target, weight_method)
            row_params = df_params.loc[case_id].to_dict()
            row_params[target_method] = weighted
            summary_list.append(row_params)
        summary_df = pd.DataFrame(summary_list).dropna(subset=[target_method])
        summary_csv = os.path.join(calibration_dir, 'calibration_summary.csv')
        summary_df.to_csv(summary_csv, index=False)
        return JSONResponse({'status': 'ok', 'message': 'Calibration summary completed.'})
    except Exception as e:
        print('/summarize_calibration:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/correlation_calibration")
async def correlation_calibration(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
        correlation_path = os.path.join(calibration_dir, 'calibration_summary.csv')
        if not os.path.exists(correlation_path):
            return JSONResponse({"status": "error", "message": "Calibration summary not found. Please run summarize first."})
        summary_df = pd.read_csv(correlation_path)
        columns = summary_df.columns.tolist()
        return JSONResponse({'content': summary_df.to_dict(orient='records'), 'key': columns[-1]})
    except Exception as e:
        print('/correlation_calibration:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/check_optimization_status_calibration")
async def check_optimization_status_calibration(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    process_key = f"{project_name}:{body.get('key')}"
    info = processes.get(process_key)
    if not info:
        return JSONResponse({"status": "not_started", "progress": 0, 
            "message": 'No optimization running'
        })
    status, progress = info.get("status"), info.get("progress", 0.0)
    current, total = info.get("current", 0), info.get("total", 0)
    if status == "finished":
        processes.pop(process_key, None)
        return JSONResponse({"status": "finished", "progress": 100.0,
            "best_params": info.get("best_params"),
            "message": info.get("message", "Optimization completed.")
        })
    if status in ("failed", "error"):
        processes.pop(process_key, None)
        return JSONResponse({"status": status, "progress": progress,
            "best_params": '', "message": info.get("message", "Simulation failed.")
        })
    complete = f'Optimization ({current}/{total}): {progress}% completed.'
    return JSONResponse({"status": status, "progress": progress, "message": complete})

@router.post("/start_optimization_calibration")
async def start_optimization_calibration(request: Request, background_tasks: BackgroundTasks, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        redis, process_key = request.app.state.redis, f"{project_name}:{body.get('key')}"
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
        correlation_path = os.path.join(calibration_dir, 'calibration_summary.csv')
        if not os.path.exists(correlation_path):
            return JSONResponse({"status": "error", "message": "Calibration summary not found. Please run summarize first."})
        lock = redis.lock(process_key, timeout=1000, blocking_timeout=10)
        async with lock:
            info = processes.get(process_key)
            # Check if simulation already running
            if info and info["status"] == "running":
                complete = f'Simulation ({info["current"]}/{info["total"]}): {info["progress"]}% completed.'
                return JSONResponse({"status": "running", "progress": info["progress"], "message": complete})
            processes[process_key] = {"progress": 0.0, "status": "running", "current": 0, "total": 0,
                "message": "Preparing data for optimization...",
            }
            info = processes[process_key]
        summary_df = pd.read_csv(correlation_path)
        # Remove old log
        log_path = os.path.join(calibration_dir, "log.txt")
        if os.path.exists(log_path): os.remove(log_path)
        background_tasks.add_task(
            calibration_functions.surrogate_model, processes, process_key,
            summary_df, body.get("model"), calibration_dir, log_path
        )
        return JSONResponse({"status": "ok", "message": f"Simulation {project_name} started"})
    except Exception as e:
        print('/start_optimization_calibration:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/start_optimization_optuna")
async def start_optimization_optuna(request: Request, background_tasks: BackgroundTasks, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        redis, process_key = request.app.state.redis, f"{project_name}:{body.get('key')}"
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
        direction, iterations = body.get('direction'), int(body.get('iterations'))
        params_path = os.path.join(calibration_dir, 'parameters.json')
        if not os.path.exists(params_path):
            return JSONResponse({"status": "error", "message": "Parameter file not found. Please 'Run Iterations' first."})
        model_dir = os.path.join(calibration_dir, "model")
        if not os.path.exists(model_dir):
            return JSONResponse({"status": "error", "message": "Model not found. Please 'Run Surrogate Model' first."})
        scaler_path = os.path.join(model_dir, "scaler_X.pkl")
        model_path = os.path.join(model_dir, "gpr_model.pkl")
        if not os.path.exists(scaler_path) or not os.path.exists(model_path):
            return JSONResponse({"status": "error", "message": "Scaler/Surrogate model not found. Please 'Run Surrogate Model' first."})
        lock = redis.lock(process_key, timeout=1000, blocking_timeout=10)
        async with lock:
            info = processes.get(process_key)
            # Check if optimization already running
            if info and info["status"] == "running":
                complete = f'Optimization ({info["current"]}/{info["total"]}): {info["progress"]}% completed.'
                return JSONResponse({"status": "running", "progress": info["progress"], "message": complete})
            processes[process_key] = {"progress": 0.0, "status": "running", "current": 0, "total": iterations,
                "message": "Preparing data for optimization...","best_params": '',
            }
            info = processes[process_key]
        # Remove old log
        log_path = os.path.join(calibration_dir, "log.txt")
        optuna_path = os.path.join(calibration_dir, 'optuna.csv')
        if os.path.exists(log_path): os.remove(log_path)
        background_tasks.add_task(
            calibration_functions.run_optuna, processes, process_key, direction,
            iterations, params_path, optuna_path, scaler_path, model_path, log_path
        )
        return JSONResponse({"status": "ok", "message": f"Optimization {project_name} started"})
    except Exception as e:
        print('/start_optimization_optuna:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/plot_optuna")
async def plot_optuna(request: Request, background_tasks: BackgroundTasks, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
        optuna_path = os.path.join(calibration_dir, 'optuna.csv')
        if not os.path.exists(optuna_path):
            return JSONResponse({"status": "error", "message": "ile not found. Please 'Run Optimization' first."})
        optuna_df = pd.read_csv(optuna_path)
        optuna_df = optuna_df.replace({np.nan: None})
        return JSONResponse({"status": "ok", "content": optuna_df.to_dict(orient='records')})
    except Exception as e:
        print('/plot_optuna:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})








