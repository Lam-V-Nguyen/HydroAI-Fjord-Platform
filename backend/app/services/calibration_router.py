import os, traceback, datetime, shutil, json
from fastapi import APIRouter, Request, Depends, Query
from fastapi import UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse
from config import PROJECT_ROOT
from services import calibration_functions, functions
from datetime import timezone, datetime, timedelta
import pandas as pd, numpy as np
from sklearn.metrics import mean_squared_error, r2_score

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
        if not body.get('key') == '':
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
        df = pd.read_csv(path, low_memory=False)
        content = calibration_functions.clip_data(df, 'Time', simStart, simEnd)
        if len(content) == 0:
            return JSONResponse({'status': 'error', 
                'message': f"No data in the uploaded CSV file falls within the simulation dates ({simStart} to {simEnd})."
            })
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
        # Remove old log
        log_path = os.path.join(calibration_dir, "log.txt")
        if os.path.exists(log_path): os.remove(log_path)
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
        # Define period
        sim_start = datetime.strptime(sim_start, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        sim_end = datetime.strptime(sim_end, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        obs_start = datetime.strptime(obs_start, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        obs_end = datetime.strptime(obs_end, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        t_start, t_end = max(sim_start, obs_start), min (sim_end, obs_end)
        depths_selected = [x.strip() for x in depth_selection.split(",")]
        summary_list, target_method, weight_method = [], body.get('targetValue'), body.get('weightValue')
        df_params = pd.read_csv(param_samples_path, index_col=0)
        # Process measured data
        measured_df = pd.DataFrame(data=body.get('obsData'), columns=[time_col, 'temperature', 'depth'])
        measured_df[time_col] = pd.to_datetime(measured_df[time_col], utc=True)
        # Detect measurement periods
        measured_df = measured_df[(measured_df[time_col] >= t_start) & (measured_df[time_col] <= t_end)]
        obs_df = calibration_functions.split_temp_from_depth(measured_df, depths_selected, time_col)
        obs_path = os.path.join(calibration_dir, f'obs_{obs_station}.csv')
        obs_df.to_csv(obs_path, index=False)
        for case_id in list_sorted:
            c_dir = os.path.join(scenario_dir, str(case_id))
            his_file = os.path.join(c_dir, 'output', 'FlowFM_his.nc')
            df_sim = calibration_functions.read_and_interpolate_his(his_file, obs_station, depths_selected, time_col)
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
            "best_params": info.get("best_params"), "message": info.get("message", "Simulation failed.")
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
                "message": "Preparing data for optimization...", "best_params": '',
            }
            info = processes[process_key]
        # Remove old log
        log_path = os.path.join(calibration_dir, "log.txt")
        optuna_path = os.path.join(calibration_dir, 'optuna.csv')
        importance_path = os.path.join(calibration_dir, 'optuna_importance.csv')
        if os.path.exists(log_path): os.remove(log_path)
        background_tasks.add_task(
            calibration_functions.run_optuna, processes, process_key, direction, iterations, 
            params_path, optuna_path, importance_path, scaler_path, model_path, log_path
        )
        return JSONResponse({"status": "ok", "message": f"Optimization {project_name} started"})
    except Exception as e:
        print('/start_optimization_optuna:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/plot_optuna")
async def plot_optuna(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        calibration_dir = os.path.join(PROJECT_ROOT, project_name, "calibration")
        optuna_path = os.path.join(calibration_dir, 'optuna.csv')
        summary_path = os.path.join(calibration_dir, 'calibration_summary.csv')
        importance_path = os.path.join(calibration_dir, 'optuna_importance.csv')
        if not os.path.exists(optuna_path):
            return JSONResponse({"status": "error", "message": "ile not found. Please 'Run Optimization' first."})
        optuna_df, summary_df = pd.read_csv(optuna_path), pd.read_csv(summary_path)
        columns = summary_df.columns.to_list()
        optuna_df = optuna_df.replace({np.nan: None})
        with open(importance_path, 'r') as f:
            importance = json.load(f)
        importance = [[key, value] for key, value in importance.items()]
        return JSONResponse({
            "status": "ok", "content": optuna_df.to_dict(orient='records'), 
            "importance": importance, "target": columns[-1]
        })
    except Exception as e:
        print('/plot_optuna:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/save_scenario_calibration")
async def save_scenario_calibration(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_old, _ = functions.project_definer(body.get('oldProject'), user)
        project_new, _ = functions.project_definer(body.get('newProject'), user)
        redis, key = request.app.state.redis, f"{project_old}:{project_new}"
        lock = redis.lock(key, timeout=1000, blocking_timeout=10)
        async with lock:
            old_dir = os.path.join(PROJECT_ROOT, project_old, 'input')
            new_dir = os.path.join(PROJECT_ROOT, project_new, 'input')
            if not os.path.exists(new_dir): os.makedirs(new_dir, exist_ok=True)
            params = { i['abbreviation']: i['value'] for i in body.get('params')}
            # Copy files
            common_files = [
                f for f in os.listdir(old_dir) if os.path.isfile(os.path.join(old_dir, f))
            ]
            for f in common_files:
                shutil.copy(os.path.join(old_dir, f), os.path.join(new_dir, f))
            # Read and update mdu file
            new_path = os.path.join(new_dir, 'FlowFM.mdu')
            with open(new_path, 'r', encoding='utf-8', errors='ignore') as f:
                mdu_base = f.readlines()
            for name, val in params.items():
                try:
                    num = float(val)
                    val_str = f"{num:.5e}"
                except (ValueError, TypeError):
                    val_str = str(val)
                mdu_base = calibration_functions.modify_mdu_key(mdu_base, name, val_str)
            output_config = {"OutputDir": "DFM_OUTPUT", "WAQOutputDir": "DFM_DELWAQ"}
            for name, val in output_config.items():
                mdu_base = calibration_functions.modify_mdu_key(mdu_base, name, val)
            # Write new mdu file
            with open(new_path, 'w', encoding='utf-8') as f:
                f.writelines(mdu_base)
            return JSONResponse({"status": "ok", "message": f"Created scenario '{project_new}' successfully."})
    except Exception as e:
        print('/save_scenario_calibration:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/obs_comparison_upload")
async def obs_comparison_upload(file: UploadFile = File(...), simStart: str = Form(...), simEnd: str = Form(...)):
    try:
        df = pd.read_csv(file.file, low_memory=False)
        content = calibration_functions.clip_data(df, 'Time', simStart, simEnd)
        return JSONResponse({'status': 'ok', 'content': content})
    except Exception as e:
        print('/obs_comparison_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/get_stations_comparison")
async def get_stations_comparison(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        redis, key = request.app.state.redis, f"{project_name}:station"
        his_path = os.path.join(PROJECT_ROOT, project_name, "output", 'HYD', "FlowFM_his.zarr")
        lock = redis.lock(key, timeout=1000, blocking_timeout=10)
        async with lock:
            content = calibration_functions.get_station_from_his_file(his_path)
            if len(content) == 0: return JSONResponse({"status": "error", "message": "No station data found in the simulation."})
            return JSONResponse({"status": "ok", "content": content})
    except Exception as e:
        print('/get_stations_comparison:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})

@router.post("/comparison_plot")
async def comparison_plot(request: Request, user=Depends(functions.basic_auth)):
    try:
        body, time_col = await request.json(), 'Time'
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        station, obs_data = body.get('station'), body.get('obsData')
        redis, process_key = request.app.state.redis, f"{project_name}:comparison"
        lock = redis.lock(process_key, timeout=1000, blocking_timeout=10)
        async with lock:
            # Define period
            start_sim, end_sim = body.get('simStart'), body.get('simEnd')
            start_obs, end_obs = body.get('obsStart'), body.get('obsEnd')
            depths_selected = [x.strip() for x in body.get('depthSelection').split(",")]
            measured_df = pd.DataFrame(data=obs_data, columns=[time_col, 'temperature', 'depth'])
            measured_df[time_col] = pd.to_datetime(measured_df[time_col], utc=True)
            sim_start = datetime.strptime(start_sim, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            sim_end = datetime.strptime(end_sim, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            obs_start = datetime.strptime(start_obs, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            obs_end = datetime.strptime(end_obs, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            t_start, t_end = max(sim_start, obs_start), min (sim_end, obs_end)
            if t_start > t_end:
                return JSONResponse({
                    "status": "error", "message": "Simulation and observation periods do not overlap."
                })
            # Detect measurement periods
            measured_df = measured_df[(measured_df[time_col] >= t_start) & (measured_df[time_col] <= t_end)]
            obs_df = calibration_functions.split_temp_from_depth(measured_df, depths_selected, time_col)
            if len(obs_df) == 0: return JSONResponse({"status": "error", "message": f"No simulation found between: {start_obs} and {end_obs}"})
            his_file = os.path.join(PROJECT_ROOT, project_name, 'output', 'HYD', 'FlowFM_his.zarr')
            sim_df = calibration_functions.read_and_interpolate_his(his_file, station, depths_selected, time_col)
            if len(sim_df) == 0: return JSONResponse({"status": "error", "message": f"No simulation found between: {start_sim} and {end_sim}"})
            sim_df = sim_df[(sim_df.index >= t_start) & (sim_df.index <= t_end)]
            # Prepare observation timestamps
            sim_df, obs_df = sim_df.reset_index(), obs_df.reset_index(drop=True)
            metrics, merge, rmses, global_min, global_max = {}, {}, [], np.inf, -np.inf
            for depth in depths_selected:
                obs_col, sim_col = f"obs_{depth}", f"sim_{depth}"
                obs_series = (obs_df[[time_col, obs_col]]
                    .dropna().drop_duplicates(time_col).set_index(time_col).sort_index()
                )
                sim_series = (sim_df[[time_col, sim_col]]
                    .dropna().drop_duplicates(time_col).set_index(time_col).sort_index()
                )
                combined_index = sim_series.index.union(obs_series.index)
                sim_interp = sim_series.reindex(combined_index).sort_index()[sim_col].interpolate(method="time")
                aligned_df = sim_interp.loc[obs_series.index]
                merge_df = pd.DataFrame({
                    time_col: obs_series.index, obs_col: obs_series[obs_col].values, sim_col: aligned_df.values
                })
                merge_df[time_col] = merge_df[time_col].dt.strftime('%Y-%m-%d %H:%M:%S')
                merge[str(depth)] = merge_df.to_dict(orient="records")
                rmse = np.sqrt(mean_squared_error(merge_df[obs_col], merge_df[sim_col]))
                r2 = r2_score(merge_df[obs_col], merge_df[sim_col])
                metrics[str(depth)] = [round(rmse, 3), round(r2, 3)]
                local_min = min(merge_df[obs_col].min(), merge_df[sim_col].min())
                local_max = max(merge_df[obs_col].max(), merge_df[sim_col].max())
                global_min = min(global_min, local_min)
                global_max = max(global_max, local_max)
                rmses.append(rmse)
            obs_df[time_col] = obs_df[time_col].dt.strftime('%Y-%m-%d %H:%M:%S')
            sim_df[time_col] = sim_df[time_col].dt.strftime('%Y-%m-%d %H:%M:%S')
            total_rmse = calibration_functions.compute_weighted_rmse(depths_selected, rmses)
            content = {
                'sim': sim_df.to_dict(orient="records"), 'depth': depths_selected,
                'obs': obs_df.to_dict(orient="records"), 'metrics': metrics, 'station': station,
                "rmse": total_rmse, "merge": merge, "min_max": [global_min, global_max]
            }
            return JSONResponse({"status": "ok", "content": content})
    except Exception as e:
        print('/comparison_plot:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})
