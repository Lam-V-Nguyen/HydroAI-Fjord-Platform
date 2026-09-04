import profile

from sqlalchemy import values

from config import PROJECT_ROOT, DELFT_PATH
from services import functions
import os, shutil, subprocess, json, pickle, warnings, logging, optuna
from functools import partial
import numpy as np, pandas as pd, xarray as xr
import matplotlib.pyplot as plt, seaborn as sns
import matplotlib.dates as mdates
from scipy.stats import qmc
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
from sklearn.base import clone
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

def split_temp_from_depth(df: pd.DataFrame, depth_selection: list,
        depth_col: str = 'depth', temp_col: str = 'temperature', 
        upper_limit: float = 5.0, lower_limit: float = 1.5
    ) -> pd.DataFrame:
    df.index = pd.to_datetime(df.index)
    df = df.loc[df.index.notna()]
    df = df.sort_index().reset_index(drop=True)
    df[temp_col] = pd.to_numeric(df[temp_col], errors='coerce')
    # df[temp_col] = df[temp_col].interpolate(method='linear', limit_direction='both')
    df[depth_col] = pd.to_numeric(df[depth_col], errors='coerce')
    # df[depth_col] = df[depth_col].interpolate(method='linear', limit_direction='both')
    df['new_profile'] = ((df["depth"] < lower_limit) & (df["depth"].shift(1) > upper_limit))
    df['profile_id'] = df['new_profile'].cumsum()
    df[temp_col] = df.groupby("profile_id")[temp_col].transform(lambda x: x.interpolate(method='linear', limit_direction='both'))
    df[depth_col] = df.groupby("profile_id")[depth_col].transform(lambda x: x.interpolate(method='linear', limit_direction='both'))
    temp_measured = (
        df.groupby("profile_id", group_keys=False)
        .apply(lambda g: interpolate_profile_to_depths(g, depth_selection))
        .reset_index(drop=True).sort_values("TIMESTAMP").reset_index(drop=True)
    )
    return temp_measured








# Setup functions
def generate_lhs_samples(parameters_range, n_samples, seed=42):
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

# Remove outliers from the measured data using rolling window method
def remove_rolling_outliers(df: pd.DataFrame, column: str, window: int = 20, n_std: float = 3.0) -> pd.DataFrame:
    df_clean = df.copy()
    rolling_mean = df_clean[column].rolling(window=window, center=True, min_periods=3).mean()
    rolling_std = df_clean[column].rolling(window=window, center=True, min_periods=3).std()
    lower = rolling_mean - n_std * rolling_std
    upper = rolling_mean + n_std * rolling_std
    mask = (df_clean[column] >= lower) & (df_clean[column] <= upper) | df_clean[column].isna()
    return df_clean[mask].copy()

def compute_weighted_rmse(depths: list, rmse_list: list, method: str = 'equal') -> float:
    if method not in {"equal", "surface", "deep"}:
        raise ValueError(
            f"Unknown weighting method: {method}. "
            "Choose 'equal', 'surface', or 'deep'."
        )
    depth_arr, rmse_arr = np.array(depths), np.array(rmse_list)
    valid = np.isfinite(depth_arr) & np.isfinite(rmse_arr) & (rmse_arr >= 0)
    if not valid.any(): return np.nan
    v_depths, v_rmse = depth_arr[valid], rmse_arr[valid]
    if method == 'surface': weights = 1.0 / v_depths
    elif method == 'deep': weights = v_depths
    elif method == 'equal': weights = np.ones(len(v_depths))
    weights = weights / weights.sum()
    score = np.sqrt(np.sum(weights * v_rmse ** 2))
    return score

def interpolate_profile_to_depths(group, depths):
    g = group.sort_values("depth").drop_duplicates("depth").reset_index(drop=True)
    d_arr, t_arr = g["depth"].to_numpy(), g["temperature"].to_numpy()
    if len(d_arr) < 2: return pd.DataFrame()
    t_start = g["TIMESTAMP"].iloc[0]
    dt_sec = (g["TIMESTAMP"] - t_start).dt.total_seconds().to_numpy()
    rows = []
    for d in depths:
        if d_arr.min() <= d <= d_arr.max():
            temp_interp = float(np.interp(d, d_arr, t_arr))
            el_sec = float(np.interp(d, d_arr, dt_sec))
            ts = t_start + pd.to_timedelta(el_sec, unit="s").round("1s")
            row = {"TIMESTAMP": ts}
            for depth_col in depths:
                row[f"obs_{depth_col}"] = temp_interp if depth_col == d else np.nan
            rows.append(row)
    return pd.DataFrame(rows)

def run(mdu_path, path, dir, log_path):
    bat_path = os.path.normpath(os.path.join(DELFT_PATH, "dflowfm/scripts/run_dflowfm.bat"))
    new_path = os.path.normpath(os.path.join(dir, mdu_path))
    command = ["cmd.exe", "/c", bat_path, "--autostartstop", new_path]
    functions.append_log(log_path, "=" * 80)
    functions.append_log(log_path, f"[STARTING] {mdu_path}")
    functions.append_log(log_path, "=" * 80)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=path)
    error_detected = False
    # Stream logs
    for line in process.stdout:
        line = line.strip()
        if not line: continue
        functions.append_log(log_path, line)
        # Catch error messages
        if "forrtl:" in line.lower() or "error" in line.lower(): error_detected = True
    return_code = process.wait()
    functions.append_log(log_path, "=" * 80)
    if return_code == 0 and not error_detected:
        functions.append_log(log_path, f"[COMPLETED] {mdu_path}")
        functions.append_log(log_path, "=" * 80)
        return True
    else:
        functions.append_log(log_path,f"[FAILED] {mdu_path}, exit code={return_code}")
        functions.append_log(log_path, "=" * 80)
        return False

def read_and_interpolate_his(case_output_dir, station_name, depths):
    his_file = os.path.join(case_output_dir, 'output', 'FlowFM_his.nc')
    if not os.path.exists(his_file): return pd.DataFrame()
    with xr.open_dataset(his_file) as ds:
        names = [n.decode('utf-8').strip() if isinstance(n, bytes) else str(n).strip() for n in ds['station_name'].values]
        if station_name not in names: return pd.DataFrame()
        st_idx = names.index(station_name)
        t_his = ds['temperature'].isel(stations=st_idx).values
        z_his = ds['zcoordinate_c'].isel(stations=st_idx).values
        wl_his = ds['waterlevel'].isel(stations=st_idx).values
        sim_times = pd.to_datetime(ds['time'].values)
    n_steps = len(sim_times)
    sim_interp = np.full((n_steps, len(depths)), np.nan)
    for i in range(n_steps):
        t_row, z_row, wl = t_his[i, :], z_his[i, :], wl_his[i]
        tgt_elev = wl - np.asarray(depths)
        mask = np.isfinite(t_row) & np.isfinite(z_row)
        if mask.sum() >= 2:
            z_valid, t_valid = z_row[mask], t_row[mask]
            order = np.argsort(z_valid)
            z_sorted, t_sorted = z_valid[order], t_valid[order]
            in_bounds = (tgt_elev >= z_sorted.min()) & (tgt_elev <= z_sorted.max())
            sim_interp[i, in_bounds] = np.interp(tgt_elev[in_bounds], z_sorted, t_sorted)
    df_sim = pd.DataFrame(sim_interp, columns=[f"sim_{d}" for d in depths], index=sim_times).reset_index().rename(columns={"index": "TIMESTAMP"})
    return df_sim










