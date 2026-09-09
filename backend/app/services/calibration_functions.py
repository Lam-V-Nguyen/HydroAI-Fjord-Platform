from config import DELFT_PATH
from services import functions
import os, shutil, subprocess, pickle
import warnings, logging, optuna, re, json
from functools import partial
import numpy as np, pandas as pd, xarray as xr
from scipy.stats import qmc
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import (
    RBF, Matern, RationalQuadratic, WhiteKernel, ConstantKernel as C
)
from optuna.importance import MeanDecreaseImpurityImportanceEvaluator
from optuna.pruners import MedianPruner
from sklearn.ensemble import RandomForestRegressor
warnings.filterwarnings('ignore', category=UserWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def get_values_from_mdu(mdu_content: list, key: str) -> list:
    _, line = next((i, line) for i, line in enumerate(mdu_content) if line.strip().startswith(key))
    if line is None: return None
    value = line.split('=')[1].strip().split('#')[0].strip()
    return value

# Setup functions
def generate_lhs_samples(parameters_range, n_samples, seed=42) -> pd.DataFrame:
    param_names = list(parameters_range.keys())
    sampler = qmc.LatinHypercube(d=len(param_names), seed=seed, optimization='random-cd')
    sample_lhs = sampler.random(n=n_samples)
    lower_bounds = [parameters_range[p][0] for p in param_names]
    upper_bounds = [parameters_range[p][1] for p in param_names]
    sample_scaled = qmc.scale(sample_lhs, lower_bounds, upper_bounds)
    return pd.DataFrame(sample_scaled, columns=param_names, index=np.arange(1, n_samples + 1))

def modify_mdu_key(mdu_lines: list, key: str, value: str = '') -> list:
    mdu = mdu_lines.copy()
    index, line = next((i, line) for i, line in enumerate(mdu) if line.strip().startswith(key))
    new = line.split('=')
    new1 = new[1].split('#')
    mdu[index] = f'{new[0]}= {value.ljust(len(new1[0])-2)} #{new1[1]}'
    return mdu

def clip_data(df: pd.DataFrame, time_column:str='Time', start:str=None, end:str=None) -> dict:
    if df.empty: return {}
    df[time_column], content = pd.to_datetime(df[time_column], utc=True), {}
    if not start is None and not end is None:
        start, end = pd.to_datetime(start, utc=True), pd.to_datetime(end, utc=True)
        df = df[(df[time_column] >= start) & (df[time_column] <= end)]
    if df.empty: return {}
    start_time, end_time = df[time_column].iloc[0], df[time_column].iloc[-1]
    content['start'] = start_time.strftime('%Y-%m-%d %H:%M:%S')
    content['end'] = end_time.strftime('%Y-%m-%d %H:%M:%S')
    df = df.replace([np.inf, -np.inf], np.nan)
    df[time_column] = df[time_column].dt.strftime('%Y-%m-%d %H:%M:%S')
    content['data'] = df.astype(object).where(df.notna(), None).to_numpy().tolist()
    return content

def split_temp_from_depth(df:pd.DataFrame, depths:list, time_col:str, upper:float=5.0, lower:float=1.5) -> pd.DataFrame:
    try:
        df["temperature"] = pd.to_numeric(df["temperature"], errors='coerce')
        df["depth"] = pd.to_numeric(df["depth"], errors='coerce')
        df = df[[time_col, "temperature", "depth"]].dropna(subset=[time_col])
        df['new_profile'] = ((df["depth"] < lower) & (df["depth"].shift(1) > upper))
        df['profile_id'] = df['new_profile'].cumsum()
        obs_df = (
            df.groupby("profile_id", group_keys=False)
            .apply(lambda g: interpolate_profile_to_depths(g, depths, time_col))
            .sort_values(time_col).reset_index(drop=True)
        )
        obs_df = obs_df.replace({np.nan: None})
        return obs_df
    except Exception: return pd.DataFrame()

def run_iteration(directory: str, processes: dict, body: dict, key: str) -> None:
    try:
        processes[key]["status"], processes[key]["progress"] = "running", 0.0
        processes[key]["message"] = "Iteration data for calibration ..."
        processes[key]["history"] += processes[key]["message"] + '\n'
        sample_dir = os.path.join(directory, "calibration")
        os.makedirs(sample_dir, exist_ok=True)
        scenario_dir = os.path.join(sample_dir, "scenarios")
        os.makedirs(scenario_dir, exist_ok=True)
        n_samples, values = body.get("iterationNumber"), body.get("params")
        params = {key: [l, u] for key, l, u in values}
        # Store parameters
        param_path = os.path.join(sample_dir, 'parameters.json')
        with open(param_path, 'w', encoding='utf-8') as f:
            json.dump(params, f, indent=4)
        # Resample data
        processes[key]["progress"] = 100.0
        processes[key]["message"] = 'Resampling started.'
        processes[key]["history"] += processes[key]["message"] + '\n'
        # Create Latin Hypercube Sampling (LHS) design for the parameters
        processes[key]["progress"] = 0.0
        processes[key]["message"] = 'Creating parameter samples using Latin Hypercube Sampling...'
        processes[key]["history"] += processes[key]["message"] + '\n'
        df_params = generate_lhs_samples(parameters_range=params, n_samples=n_samples)
        df_params.to_csv(os.path.join(sample_dir, 'parameter_samples.csv'))
        processes[key]["progress"] = 100.0
        processes[key]["message"] = 'Parameter samples created.'
        processes[key]["history"] += processes[key]["message"] + '\n'
        # Read mdu file
        processes[key]["progress"] = 0.0
        processes[key]["message"] = 'Modifying MDU file.'
        processes[key]["history"] += processes[key]["message"] + '\n'
        input_dir = os.path.join(directory, "input")
        mdu_file = [f for f in os.listdir(input_dir) if f.endswith(".mdu")][0]
        if not mdu_file:
            processes[key]["status"] = "failed"
            processes[key]["message"] = f"MDU file not found in project '{body.get('projectName')}'"
            processes[key]["history"] += processes[key]["message"] + '\n'
        mdu_path = os.path.join(input_dir, mdu_file)
        with open(mdu_path, 'r', encoding='utf-8', errors='ignore') as f:
            mdu_content = f.readlines()
        his_interval = get_values_from_mdu(mdu_content, 'HisInterval')
        his_interval = his_interval.split()[0] if his_interval else '21600'
        mdu_content = modify_mdu_key(mdu_content, 'WaqInterval', '0')
        mdu_content = modify_mdu_key(mdu_content, 'RstInterval', '0')
        mdu_content = modify_mdu_key(mdu_content, 'RestartFile', '')
        mdu_content = modify_mdu_key(mdu_content, 'HisInterval', str(his_interval))
        # Optimize his parameters
        processes[key]["message"] += 'Optimizing HIS parameters ...\n'
        vars_to_keep = {'Wrihis_temperature', 'Wrihis_waterlevel_s1'}
        for idx, line in enumerate(mdu_content):
            processes[key]["progress"] = (idx + 1) / len(mdu_content) * 100
            if line.strip().startswith(('Wrihis_', 'Wrimap_')) and '=' in line:
                var_name = line.split('=')[0].strip()
                val = '1' if var_name in vars_to_keep else '0'
                mdu_content = modify_mdu_key(mdu_content, var_name, val)
        processes[key]["progress"] = 100.0
        processes[key]["message"] = 'Completed optimizing HIS parameters.'
        processes[key]["history"] += processes[key]["message"] + '\n'
        # Create different scenarios
        processes[key]["progress"] = 0.0
        processes[key]["message"] = 'Creating different scenarios ...'
        processes[key]["history"] += processes[key]["message"] + '\n'
        parent_mdu_dir = os.path.dirname(mdu_path)
        common_files = [f for f in os.listdir(parent_mdu_dir) 
            if os.path.isfile(os.path.join(parent_mdu_dir, f)) and not f.endswith('.mdu')
        ]
        # Store different scenarios
        for case_id, row in df_params.iterrows():
            processes[key]["progress"] = (case_id + 1) / len(df_params) * 100
            case_dir = os.path.join(scenario_dir, str(case_id))
            os.makedirs(case_dir, exist_ok=True)
            # Copy files
            for f in common_files:
                shutil.copy(os.path.join(parent_mdu_dir, f), os.path.join(case_dir, f))
            # Update MDU
            mdu_case = mdu_content.copy()
            mdu_case = modify_mdu_key(
                mdu_case, 'MapInterval', str(his_interval) if case_id == 1 else '0'
            )
            for p_name, p_val in row.items():
                val_str = f"{p_val:.5e}" if isinstance(p_val, float) else str(p_val)
                mdu_case = modify_mdu_key(mdu_case, p_name, val_str)
            with open(os.path.join(case_dir, 'FlowFM.mdu'), 'w', encoding='utf-8') as f:
                f.writelines(mdu_case)
        processes[key]["message"] = f"Successfully created {n_samples} resamples."
        processes[key]["history"] += f"\n{processes[key]['message']}"
        processes[key]["status"], processes[key]["progress"] = "finished", 100.0
    except Exception as e:
        info = processes.get(key)
        if info: 
            info["status"], info["message"] = "failed", f"Error: {str(e)}"
            info["history"] += f"Error: {str(e)}"
            info["progress"] = info.get("progress", 0.0)

def run_calibration(processes: dict, key: str, scenario_dir: str, scenarios: list, log_path: str) -> None:
    try:
        bat_path = os.path.normpath(os.path.join(DELFT_PATH, "dflowfm/scripts/run_dflowfm.bat"))
        if not os.path.exists(bat_path):
            processes[key]["status"] = "error"
            processes[key]["message"] = "Executable file not found"
            functions.append_log(log_path, f"[ERROR] Executable file not found: {bat_path}")
            return
        percent_re = re.compile(r'(?P<percent>\d{1,3}(?:\.\d+)?)\s*%')
        correct_cases, error_cases, total_simulations = [], [], len(scenarios)
        functions.append_log(log_path, "")
        functions.append_log(log_path, "=" * 80)
        functions.append_log(log_path, "[SIMULATION STARTED]")
        functions.append_log(log_path, "=" * 80)
        functions.append_log(log_path, f"[INFO] Total simulations: {total_simulations}")
        functions.append_log(log_path, "")
        for index, case_id in enumerate(scenarios, start=1):
            # Check whether job still exists
            if key not in processes:
                functions.append_log(log_path, "[WARNING] Calibration process was removed.")
                return
            # Current scenario
            processes[key]["current"], processes[key]["progress"] = index, 0.0
            c_dir = os.path.join(scenario_dir, str(case_id))
            mdu_path = os.path.join(c_dir, "FlowFM.mdu")
            functions.append_log(log_path, "")
            functions.append_log(log_path, "=" * 80)
            functions.append_log(log_path,
                f"[SCENARIO {index}/{total_simulations}] Starting scenario {case_id}"
            )
            functions.append_log(log_path, f"[STARTING] {mdu_path}")
            functions.append_log(log_path, "=" * 80)
            # Check MDU file
            if not os.path.exists(mdu_path):
                error_message = f"MDU file not found in scenario {case_id}"
                processes[key]["message"] = error_message
                functions.append_log(log_path, f"[ERROR] {error_message}")
                error_cases.append(mdu_path)
                # Continue with the next scenario
                continue
            command = ["cmd.exe", "/c", bat_path, "--autostartstop", mdu_path]
            process, error_detected = None, False
            try:
                # Run the process
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=c_dir)
                # Stream logs
                for line in process.stdout:
                    if key not in processes:
                        functions.append_log(log_path, "[WARNING] Calibration process was removed.")
                        functions.kill_process(process)
                        return
                    line = line.strip()
                    if not line: continue
                    functions.append_log(log_path, line)
                    # Catch Delft3D errors
                    if "forrtl:" in line.lower() or "error" in line.lower():
                        error_detected = True
                        processes[key]["message"] = f"Scenario {case_id} failed: {line}"
                        functions.append_log(log_path, f"[ERROR] Scenario {case_id}: {line}")
                        # Kill current Delft3D process
                        res = functions.kill_process(process)
                        functions.append_log(log_path, res["message"])
                        break
                    # Check for progress
                    match_pct = percent_re.search(line)
                    if match_pct: 
                        processes[key]["progress"] = float(match_pct.group("percent"))
                return_code = process.wait()
            except Exception as e:
                error_detected, return_code = True, -1
                functions.append_log(
                    log_path, f"[ERROR] Exception while running scenario {case_id}: {e}"
                )
                if process is not None:
                    try:
                        res = functions.kill_process(process)
                        functions.append_log(log_path, res["message"])
                    except Exception: pass
            # Evaluate current scenario
            functions.append_log(log_path, "=" * 80)
            if return_code == 0 and not error_detected:
                correct_cases.append(mdu_path)
                functions.append_log(log_path, f"[COMPLETED] {mdu_path}")
                functions.append_log(log_path, "=" * 80)
            else:
                error_cases.append(mdu_path)
                functions.append_log(log_path,f"[FAILED] {mdu_path}, exit code={return_code}")
                functions.append_log(log_path, "=" * 80)
        # Summarize results
        functions.append_log(log_path, "\n\n")
        functions.append_log(log_path, "=" * 80)
        functions.append_log(log_path, "[SIMULATION SUMMARY]")
        functions.append_log(log_path, "=" * 80)
        functions.append_log(log_path, f"[SUMMARY] Total simulations : {len(scenarios)}")
        functions.append_log(log_path, f"[SUMMARY] Successful        : {len(correct_cases)}")
        functions.append_log(log_path, f"[SUMMARY] Failed            : {len(error_cases)}")
        if error_cases:
            functions.append_log(log_path, "[SUMMARY] Failed scenarios:")
            for case in error_cases:
                functions.append_log(log_path, f"  - {case}")
        functions.append_log(log_path, "=" * 80)
        functions.append_log(log_path, "[SIMULATION COMPLETED]")
        functions.append_log(log_path, "=" * 80)
        functions.append_log(log_path, "\n\n")
    except Exception as e:
        if processes[key]:
            processes[key]["status"] = "failed"
            processes[key]["message"] = f"Internal error: {e}"
        functions.append_log(log_path, f"[INTERNAL ERROR] {e}")

def get_station_from_his_file(his_path: str) -> list:
    if not os.path.exists(his_path): return []
    if his_path.endswith('.nc'): ds = xr.open_dataset(his_path)
    elif his_path.endswith(".zarr"): ds = xr.open_zarr(his_path)
    with ds:
        names = [
            n.decode('utf-8').strip() if isinstance(n, bytes) else str(n).strip() 
            for n in ds['station_name'].values
        ]
    return names

def interpolate_profile_to_depths(group: pd.DataFrame, depths: list, time_col="Time") -> pd.DataFrame:
    g = group.sort_values("depth").drop_duplicates("depth").reset_index(drop=True)
    d_arr, t_arr = g["depth"].to_numpy(), g["temperature"].to_numpy()
    if len(d_arr) < 2: return pd.DataFrame()
    t_start = g[time_col].iloc[0]
    dt_sec = (g[time_col] - t_start).dt.total_seconds().to_numpy()
    rows = []
    for d in depths:
        d_num = float(d)
        if d_arr.min() <= d_num <= d_arr.max():
            temp_interp = float(np.interp(d_num, d_arr, t_arr))
            el_sec = float(np.interp(d_num, d_arr, dt_sec))
            ts = t_start + pd.to_timedelta(el_sec, unit="s").round("1s")
            row = {time_col: ts}
            for depth_col in depths:
                row[f"obs_{depth_col}"] = temp_interp if depth_col == d else np.nan
            rows.append(row)
    return pd.DataFrame(rows)

def read_and_interpolate_his(his_path: str, station_name: str, depths: list, time_col="Time") -> pd.DataFrame:
    try:
        if not os.path.exists(his_path): return pd.DataFrame()
        names = get_station_from_his_file(his_path)
        if station_name not in names: return pd.DataFrame()
        st_idx = names.index(station_name)
        if his_path.endswith('.nc'): ds = xr.open_dataset(his_path)
        elif his_path.endswith(".zarr"): ds = xr.open_zarr(his_path)
        else: return pd.DataFrame()
        with ds:
            t_his = ds['temperature'].isel(stations=st_idx).values
            z_his = ds['zcoordinate_c'].isel(stations=st_idx).values
            wl_his = ds['waterlevel'].isel(stations=st_idx).values
            sim_times = pd.to_datetime(ds['time'].values, utc=True)
        depth_num = np.asarray(depths, dtype=float)
        n_steps = len(sim_times)
        sim_interp = np.full((n_steps, len(depths)), np.nan)
        for i in range(n_steps):
            t_row, z_row, wl = t_his[i, :], z_his[i, :], wl_his[i]
            tgt_elev = wl - depth_num
            mask = np.isfinite(t_row) & np.isfinite(z_row)
            if mask.sum() < 2: continue
            z_valid, t_valid = z_row[mask], t_row[mask]
            order = np.argsort(z_valid)
            z_sorted, t_sorted = z_valid[order], t_valid[order]
            in_bounds = (tgt_elev >= z_sorted.min()) & (tgt_elev <= z_sorted.max())
            sim_interp[i, in_bounds] = np.interp(tgt_elev[in_bounds], z_sorted, t_sorted)
        df_sim = pd.DataFrame(
            sim_interp, columns=[f"sim_{d}" for d in depths], index=pd.Index(sim_times, name=time_col)
        )
        return df_sim
    except Exception: return pd.DataFrame()

# Remove outliers from the measured data using rolling window method
def remove_rolling_outliers(df: pd.DataFrame, column: str, window: int=20, n_std: float=3.0) -> pd.DataFrame:
    df_clean = df.copy()
    rolling_mean = df_clean[column].rolling(window=window, center=True, min_periods=3).mean()
    rolling_std = df_clean[column].rolling(window=window, center=True, min_periods=3).std()
    lower = rolling_mean - n_std * rolling_std
    upper = rolling_mean + n_std * rolling_std
    mask = (df_clean[column] >= lower) & (df_clean[column] <= upper) | df_clean[column].isna()
    return df_clean[mask].copy()

def target_score(target_method: str, obs: pd.Series, sim: pd.Series) -> float:
    if target_method == "RMSE": score = np.sqrt(mean_squared_error(obs, sim))
    elif target_method == "R2": score = r2_score(obs, sim)
    return score

def compute_weighted_rmse(depths: list, target: list, method: str = 'equal') -> float:
    depth_arr, rmse_arr = np.array([float(d) for d in depths]), np.array(target)
    valid = np.isfinite(depth_arr) & np.isfinite(rmse_arr) & (rmse_arr >= 0)
    if not valid.any(): return np.nan
    v_depths, v_rmse = depth_arr[valid], rmse_arr[valid]
    if method == 'surface': weights = 1.0 / v_depths
    elif method == 'deep': weights = v_depths
    elif method == 'equal': weights = np.ones(len(v_depths))
    weights = weights / weights.sum()
    score = np.sqrt(np.sum(weights * v_rmse ** 2))
    return score

def surrogate_model(processes: dict, key: str, df: pd.DataFrame, 
    model: str, directory: str, log_path: str) -> None:
    try:
        functions.append_log(log_path, "Building surrogate model...")
        functions.append_log(log_path, "===============================")
        functions.append_log(log_path, "Starting model training...")
        columns = df.columns.tolist()
        col_name = columns[-1]
        X, y = df.drop(columns=[col_name]), df[[col_name]]
        if model == "gaussian-process":
            # Standardization
            scaler_X = StandardScaler()
            X_scaled = scaler_X.fit_transform(X)
            y = y.values.ravel()
            functions.append_log(log_path, "Preparing kernels...")
            kernels_to_test = [
                (C(1.0, (1e-3, 1e3)) * RBF(1.0, (1e-3, 1e2)), 'RBF'),
                (C(1.0, (1e-3, 1e3)) * RBF(1.0, (1e-2, 1e2)) + WhiteKernel(1e-3, (1e-10, 1e-1)), 'RBF + White'),
                (C(1.0, (1e-3, 1e3)) * Matern(1.0, nu=1.5, length_scale_bounds=(1e-3, 1e2)), 'Matern_1.5'),
                (C(1.0, (1e-3, 1e3)) * Matern(1.0, nu=2.5, length_scale_bounds=(1e-3, 1e2)), 'Matern_2.5'),
                (C(1.0, (1e-3, 1e3)) * RationalQuadratic(1.0, 1.0, length_scale_bounds=(1e-9, 1e6)), 'RationalQuadratic')
            ]
            best_log_likelihood, best_kernel = -np.inf, None
            for kernel_obj, k_name in kernels_to_test:
                functions.append_log(log_path, f"Testing kernel: {k_name} - {kernel_obj}...")
                gpr = GaussianProcessRegressor(
                    kernel=kernel_obj, n_restarts_optimizer=30, 
                    alpha=1e-6, normalize_y=True, random_state=42
                )
                gpr.fit(X_scaled, y)
                if gpr.log_marginal_likelihood_value_ > best_log_likelihood:
                    best_log_likelihood = gpr.log_marginal_likelihood_value_
                    best_kernel, best_name = kernel_obj, k_name
            functions.append_log(log_path, f"Best kernel: {best_name} - {best_kernel}")
            functions.append_log(log_path, "Retraining model with best kernel...")
            final_gpr = GaussianProcessRegressor(
                kernel=kernel_obj, n_restarts_optimizer=30, 
                alpha=1e-6, normalize_y=True, random_state=42
            )
            final_gpr.fit(X_scaled, y)
            # Save model
            model_dir = os.path.normpath(os.path.join(directory, 'model'))
            if os.path.exists(model_dir):
                functions.append_log(log_path, f"Removing old model: {model_dir}.")
                shutil.rmtree(model_dir)
            functions.append_log(log_path, "Saving model...")
            os.makedirs(model_dir, exist_ok=True)
            objects = [('scaler_X', scaler_X), ('gpr_model', final_gpr)]
            for scaler, data in objects:
                functions.append_log(log_path, f"Saving {scaler}...")
                with open(os.path.join(model_dir, f'{scaler}.pkl'), "wb") as f:
                    pickle.dump(data, f)
            functions.append_log(log_path, f"Saved model: {model_dir}.")
            functions.append_log(log_path, "Model training completed.")
            functions.append_log(log_path, "===============================")
            processes[key]["status"] = "finished"
            processes[key]["message"] = "Model training completed."
    except Exception as e:
        if processes[key]:
            processes[key]["status"] = "failed"
            processes[key]["message"] = f"Internal error: {e}"
        functions.append_log(log_path, f"[INTERNAL ERROR] {e}")

def optuna_objective(trial, scaler_x, model, p_ranges):
    trial_params = {}
    for p, bounds in p_ranges.items():
        trial_params[p] = trial.suggest_float(p, bounds[0], bounds[1])
    df_in = pd.DataFrame([trial_params], columns=list(p_ranges.keys()))
    x_sc = scaler_x.transform(df_in)
    pred_sc = model.predict(x_sc)
    return pred_sc[0]

def optuna_callback(study, trial, processes, key, log_path):
    functions.append_log(log_path,
        f"Trial {trial.number}: value={trial.value:.6f}, "
        f"best={study.best_value:.6f}, params={trial.params}"
    )
    processes[key]["current"] = trial.number
    complete = trial.number / processes[key]["total"] * 100
    processes[key]["progress"] = f"{complete:.1f}"

def run_optuna(processes: dict, key: str, direction: str,
    iterations: int, params_path: str, optuna_path: str, importance_path: str,
    scaler_path: str, model_path: str, log_path: str) -> None:
    try:
        with open(params_path, "r", encoding="utf-8") as f:
            parameters = json.load(f)
        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        params = {name: parameters[name] for name in scaler.feature_names_in_}
        optuna_func = partial(
            optuna_objective, scaler_x=scaler, model=model, p_ranges=params
        )
        study = optuna.create_study(
            sampler=optuna.samplers.TPESampler(seed=42), direction=direction, 
            pruner=MedianPruner(n_startup_trials=10, n_warmup_steps=20),
            study_name='delft3d_fm_calibration'
        )
        callback = partial(optuna_callback, processes=processes, key=key, log_path=log_path)
        study.optimize(optuna_func, n_trials=iterations, callbacks=[callback])
        df_trials = study.trials_dataframe()
        df_trials.to_csv(optuna_path) # Save optuna results
        # Compute importance values
        try:
            importance = optuna.importance.get_param_importances(
                study, evaluator=MeanDecreaseImpurityImportanceEvaluator()
            )
        except Exception:
            param_cols = [c for c in df_trials.columns if c.startswith('params_')]
            X_tr = df_trials[param_cols].fillna(df_trials[param_cols].mean())
            y_tr = df_trials['value'].fillna(df_trials['value'].max())
            rf = RandomForestRegressor(n_estimators=100, random_state=42)
            rf.fit(X_tr, y_tr)
            clean_names = [c.replace('params_', '') for c in param_cols]
            importance = dict(zip(clean_names, rf.feature_importances_))
        sorted_importance = dict(sorted(importance.items(), key=lambda item: item[1]))
        # Store parameters
        with open(importance_path, 'w', encoding='utf-8') as f:
            json.dump(sorted_importance, f, indent=4)
        processes[key]["best_params"] = study.best_params
        processes[key]["status"] = "finished"
        processes[key]["message"] = "Optimization completed."
    except Exception as e:
        if processes[key]:
            processes[key]["status"] = "failed"
            processes[key]["message"] = f"Internal error: {e}"
        functions.append_log(log_path, f"[INTERNAL ERROR] {e}")
