import os, json, logging
from config import SOURCE_BACKEND
from services import functions, waq_models
from waq_models import WaqModel
import geopandas as gpd, xarray as xr, numpy as np
from shapely.geometry import Point
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
WRITE_ENCODING = 'utf-8'


def hydReader(hyd_path: str, time_zone: str) -> dict:
    # Read the hyd file
    data, check, sinks = {'filename': 'FlowFM.hyd'}, False, []
    with open(hyd_path, 'r', encoding=functions.encoding_detect(hyd_path)) as f:
        lines = f.readlines()
    for line in lines:
        if "number-hydrodynamic-layers" in line: data['n_layers'] = line.split()[1]
        if "hydrodynamic-start-time" in line:
            temp = line.split()[1].replace("'", "")
            dt = datetime.strptime(temp, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
            data['start_time'] = functions.utc_to_local(dt, time_zone)
        if "hydrodynamic-stop-time" in line:
            temp = line.split()[1].replace("'", "")
            dt = datetime.strptime(temp, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
            data['stop_time'] = functions.utc_to_local(dt, time_zone)
        if "hydrodynamic-timestep" in line:
            data['time_step1'] = int(line.split()[1].replace("'", ""))
        if "conversion-timestep" in line:
            data['time_step2'] = int(line.split()[1].replace("'", ""))
        if "number-water-quality-segments-per-layer" in line:
            data['n_segments'] = int(line.split()[1])
        if "number-water-quality-layers" in line:
            data['n_layer'] = int(line.split()[1])
        if "attributes-file" in line:
            data['attr_path'] = line.split()[1].replace("'", "")
        if "volumes-file" in line:
            data['vol_path'] = line.split()[1].replace("'", "")
        if "number-horizontal-exchanges" in line:
            data['exchange_x'] = int(line.split()[1])
        if "number-vertical-exchanges" in line:
            data['exchange_z'] = int(line.split()[1])
        if "waqgeom-file" in line or "grid-coordinates-file" in line:
            data['grid'] = line.split()[1].replace("'", "")
        if "pointers-file" in line:
            data['ptr_path'] = line.split()[1].replace("'", "")
        if "areas-file" in line:
            data['area_path'] = line.split()[1].replace("'", "")
        if "flows-file" in line:
            data['flow_path'] = line.split()[1].replace("'", "")
        if "lengths-file" in line:
            data['length_path'] = line.split()[1].replace("'", "")
        if "sink-sources" in line: check = True
        if check and "sink-sources" not in line:
            temp = line.split()
            sinks.append([temp[-1], temp[-2], temp[-3]])
        if "end-sink-sources" in line: check = False
        if "horizontal-surfaces-file" in line:
            data['srf_path'] = line.split()[1].replace("'", "")
        if "vert-diffusion-file" in line:
            data['vdf_path'] = line.split()[1].replace("'", "")
        if "temperature-file" in line:
            data['tem_path'] = line.split()[1].replace("'", "")
        if "salinity-file" in line:
            data['sal_path'] = line.split()[1].replace("'", "")
    data['sink_sources'] = sinks
    if 'n_layer' in data and isinstance(data['n_layer'], int):
        data['n_segments'] = data['n_segments'] * data['n_layer']
    else: data['n_layer'] = 0
    return data
    
def segmentFinder(lat:float, lon:float, grid:gpd.GeoDataFrame) -> int:
    if grid.empty: return 0
    # Convert the grid to WGS84 if not already
    if grid.crs != '4326': grid = grid.to_crs(epsg=4326)
    # Find the segment that the point is in
    pt = Point(lon, lat)
    mash = grid.contains(pt)
    polygon = grid.loc[mash]
    if polygon.empty: return 0
    return int(polygon.index[0]) + 1

def ddhhmmss_to_seconds(value) -> int:
    s = str(value).strip().strip("'").zfill(8)
    dd, hh, mm, ss = int(s[:-6]), int(s[-6:-4]), int(s[-4:-2]), int(s[-2:])
    return ((dd * 24 + hh) * 60 + mm) * 60 + ss

def seconds_to_ddhhmmss(seconds: int) -> str:
    dd, r = divmod(int(seconds), 86400)
    hh, r = divmod(r, 3600)
    mm, ss = divmod(r, 60)
    return f"{dd:03d}{hh:02d}{mm:02d}{ss:02d}"

def _recordTimes(path: str, n_values: int) -> tuple:
    rec = np.dtype([('t', '<i4'), ('v', '<f4', (n_values,))])
    size = os.path.getsize(path)
    if size % rec.itemsize != 0:
        raise ValueError(f"{os.path.basename(path)}: size {size} is not a multiple of record size {rec.itemsize}")
    data = np.memmap(path, dtype=rec, mode='r')
    t_first, t_last, n_rec = int(data['t'][0]), int(data['t'][-1]), len(data)
    del data
    return t_first, t_last, n_rec

def hydDataWindow(vol_path: str, flow_path: str, n_segments: int, noq: int, ref_time: datetime) -> tuple:
    v_first, v_last, _ = _recordTimes(vol_path, n_segments)
    f_first, f_last, _ = _recordTimes(flow_path, noq)
    first = ref_time + timedelta(seconds=max(v_first, f_first))
    last = ref_time + timedelta(seconds=min(v_last, f_last))
    return first, last

def hydTimeInfo(hyd_path: str) -> dict:
    keys, info = {'conversion-ref-time': 'ref_time', 'conversion-start-time': 'start_time',
        'conversion-stop-time': 'stop_time', 'conversion-timestep': 'conv_step'}, {}
    with open(hyd_path, 'r', encoding=functions.encoding_detect(hyd_path)) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2 or parts[0] not in keys: continue
            value = parts[1].strip("'")
            if parts[0] == 'conversion-timestep':
                info['conv_step'] = ddhhmmss_to_seconds(value)
            else:
                info[keys[parts[0]]] = datetime.strptime(value, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    missing = [k for k in keys.values() if k not in info]
    if missing: raise ValueError(f"Missing in .hyd file: {missing}")
    return info

def simWindowChecker(parameters: dict, noq: int) -> tuple:
    info = hydTimeInfo(parameters['hyd_path'])
    conv = info['conv_step']
    first, last = hydDataWindow(
        parameters['vol_path'], parameters['flow_path'],
        int(parameters['n_segments']), noq, info['ref_time']
    )
    dt_calc = ddhhmmss_to_seconds(parameters['t_calc']) if parameters.get('t_calc') else conv
    dt_out = ddhhmmss_to_seconds(parameters['t_output'])
    if dt_calc <= 0 or dt_out <= 0:
        raise ValueError("Timesteps must be positive.")
    if dt_calc > conv or conv % dt_calc != 0:
        raise ValueError(f"Integration timestep ({dt_calc}s) must be <= and divide the "
            f"hydrodynamic coupling interval ({conv}s).")
    if dt_out % dt_calc != 0:
        raise ValueError(f"Output timestep ({dt_out}s) must be a multiple of the integration timestep ({dt_calc}s).")
    t_start, t_stop, msgs = parameters['t_start'], parameters['t_stop'], []
    if t_start < first or t_start >= last:
        raise ValueError(f"WAQ start {t_start:%Y-%m-%d %H:%M} UTC is outside the hydrodynamic data "
            f"({first:%Y-%m-%d %H:%M} – {last:%Y-%m-%d %H:%M} UTC).")
    safe_stop = last - timedelta(seconds=conv)
    target = min(t_stop, safe_stop)
    n_steps = int((target - t_start).total_seconds() // dt_calc)
    if n_steps < 1:
        raise ValueError("WAQ simulation window is too short after aligning to the hydrodynamic data.")
    new_stop = t_start + timedelta(seconds=n_steps * dt_calc)
    if new_stop != t_stop:
        msgs.append(f"Stop time adjusted from {t_stop:%Y-%m-%d %H:%M} to {new_stop:%Y-%m-%d %H:%M} UTC "
            f"(last hydrodynamic record: {last:%Y-%m-%d %H:%M} UTC).")
    return t_start, new_stop, dt_calc, dt_out, ' '.join(msgs)

def poiInspector(ptr_path: str, n_vertical: int) -> dict:
    raw = np.fromfile(ptr_path, dtype=np.int32)
    if raw.size % 4 != 0:
        raise ValueError(f"Unexpected .poi size: {raw.size} ints (not divisible by 4)")
    poi = raw.reshape(-1, 4)
    noq = poi.shape[0]
    min_ptr = int(poi[:, :2].min())
    return {
        'noq': noq, 'exchange_x': noq - int(n_vertical), 'n_boundaries': -min_ptr if min_ptr < 0 else 0
    }

def _locate_points(points: list, grid: gpd.GeoDataFrame) -> tuple:
    """Split [name, lat, lon, ...] rows into (found as (row, segment), names outside the grid)."""
    found, outside = [], []
    for row in points:
        segment = segmentFinder(row[1], row[2], grid)
        if segment == 0: outside.append(str(row[0]))
        else: found.append((row, segment))
    return found, outside

def _fwd(path: str) -> str:
    """Path with forward slashes, accepted by DELWAQ on both Windows and Linux."""
    return str(path).replace(os.sep, "/")

def _common_blocks(parameters: dict, grid: gpd.GeoDataFrame, 
    poi_info: dict, output_folder: str, notes: list) -> tuple:
    """Include files shared by every model (blocks 1-8, except substances and model processes).
    Returns (include contents, metadata saved next to the .inp)."""
    inc, meta = {}, {}
    # ######################## Block 1 ########################
    inc['B1_t0'] = "'T0: 1970.01.01 00:00:00  (scu=       1s)'"
    inc['B2_numsettings'] = f'{parameters["scheme"]}.70 ; integration option\n; detailed balance options'
    # ######################## Block 2 ########################
    # Block 2: simulation and output timers
    t_start, t_stop, dt_calc, dt_out, time_msg = simWindowChecker(parameters, poi_info['noq'])
    if time_msg: notes.append(time_msg)
    start_utc, stop_utc = t_start.strftime('%Y/%m/%d-%H:%M:%S'), t_stop.strftime('%Y/%m/%d-%H:%M:%S')
    calc_str, out_str = seconds_to_ddhhmmss(dt_calc), seconds_to_ddhhmmss(dt_out)
    inc['B2_simtimers'] = [f"{start_utc} ; start time", f"{stop_utc} ; stop time",
        "0 ; timestep constant", f"{calc_str} ; timestep"]
    inc['B2_outputtimers'] = [';  output control (see DELWAQ-manual)', ';  yyyy/mm/dd-hh:mm:ss  yyyy/mm/dd-hh:mm:ss  dddhhmmss']
    for kind in ('balance', 'map', 'his'):
        inc['B2_outputtimers'].append(f'{start_utc} {stop_utc} {out_str} ;  start, stop and step for {kind} output')
    # Block 2: monitoring locations. The count must equal the number of locations written,
    # so points outside the grid are dropped before counting.
    obs, obs_outside = _locate_points(list(parameters['obs_data'] or []), grid)
    if obs_outside:
        notes.append(f"Observation point(s) outside the model grid were skipped: {', '.join(obs_outside)}.")
    inc['B2_outlocs'] = [f'{len(obs)} ; nr of monitor locations']
    inc['B2_outlocs'] += [f"'{row[0]}' 1\n{segment}" for row, segment in obs]
    if obs: meta['wq_obs'] = [row for row, _ in obs]
    # ######################## Block 3 ########################
    # Block 3: grid, segments, attributes, volumes
    hyd_dir = os.path.dirname(parameters['hyd_path'])
    inc['B3_ugrid'] = f"UGRID '{_fwd(os.path.normpath(os.path.join(hyd_dir, 'FlowFM_waqgeom.nc')))}'"
    inc['B3_nrofseg'] = f"{parameters['n_segments']} ; number of segments"
    inc['B3_attributes'] = f"INCLUDE '{_fwd(parameters['attr_path'])}' ; attributes file"
    inc['B3_volumes'] = f"-2 ; volumes will be interpolated from a binary file\n'{_fwd(parameters['vol_path'])}' ; volumes file from hyd file"
    # ######################## Block 4 ########################
    # Block 4: exchanges
    inc['B4_nrofexch'] = f"{poi_info['exchange_x']} 0 {parameters['exchange_z']} ; number of exchanges in three directions"
    inc['B4_pointers'] = f"0 ; pointers from binary file.\n'{_fwd(parameters['ptr_path'])}' ; pointers file"
    inc['B4_cdispersion'] = "1 0.0 1E-07 ; constant dispersion"
    inc['B4_area'] = f"-2 ; areas will be interpolated from a binary file\n'{_fwd(parameters['area_path'])}' ; areas file"
    inc['B4_flows'] = f"-2 ; flows from binary file\n'{_fwd(parameters['flow_path'])}' ; flows file"
    inc['B4_length'] = f"0 ; Lengths from binary file\n'{_fwd(parameters['length_path'])}' ; lengths file"
    # ######################## Block 5 ########################
    # Block 5: boundaries
    inc['B5_boundlist'] = [";'NodeID' 'Comment field' 'Boundary name used for data grouping'"]
    names = [p[0] for p in parameters['sources']] if parameters.get('sources') else []
    for i in range(poi_info['n_boundaries']):
        group = names[i % len(names)] if names else f"Bnd_{i+1}"
        inc['B5_boundlist'].append(f"'{i+1}' '' '{group}'")
    inc['B5_boundaliases'], inc['B5_bounddata'] = '', ''
    # ######################## Block 6 ########################
    # Block 6: loads. A load outside the grid would silently remove mass from the model,
    # and its time series in the .tbl file would point to an unknown load, so stop instead.
    loads, loads_outside = _locate_points(list(parameters['loads_data'] or []), grid)
    if loads_outside:
        raise ValueError(f"Load location(s) outside the model grid: {', '.join(loads_outside)}. "
            "Move them inside the grid or remove them from the list of loads.")
    inc['B6_loads'] = [f'{len(loads)} ; Number of loads', ';SegmentID  Load-name  Comment  Load-type']
    inc['B6_loads'] += [f"{segment} '{row[0]}' '' ''" for row, segment in loads]
    inc['B6_loads_aliases'] = [f"USEDATA_ITEM '{row[0]}' FORITEM\n'{row[0]}'" for row, _ in loads]
    if loads: meta['wq_loads'] = [row for row, _ in loads]
    tbl_path = os.path.normpath(os.path.join(output_folder, 
        'includes_deltashell', 'load_data_tables', f'{parameters["folder_name"]}.tbl'))
    inc['B6_loads_data'] = f"INCLUDE '{_fwd(tbl_path)}'"
    # ######################## Block 7 ########################
    # Block 7: parts shared by all models
    inc['B7_functions'], inc['B7_dispersion'] = '', ''
    inc['B7_parameters'] = (f"PARAMETERS\n'Surf'\nALL\nBINARY_FILE '{_fwd(parameters['srf_path'])}'"
        " ; from horizontal-surfaces-file key in hyd file")
    inc['B7_vdiffusion'] = ["CONSTANTS 'ACTIVE_VertDisp' DATA 1.0", "SEG_FUNCTIONS", "'VertDisper'", "ALL",
        f"BINARY_FILE '{_fwd(parameters['vdf_path'])}'"]
    inc['B7_numerical_options'] = [
        "CONSTANTS 'CLOSE_ERR' DATA 1 ; If defined, allow delwaq to correct water volumes to keep concentrations continuous",
        "CONSTANTS 'NOTHREADS' DATA 2 ; Number of threads used by delwaq",
        "CONSTANTS 'DRY_THRESH' DATA 0.001 ; Dry cell threshold",
        f"CONSTANTS 'maxiter' DATA {int(parameters['maxiter'])} ; Maximum number of iterations",
        f"CONSTANTS 'tolerance' DATA {parameters['tolerance']} ; Convergence tolerance",
        "CONSTANTS 'iteration report' DATA 0 ; Write iteration report (when 1) or not (when 0)",
    ]
    # ######################## Block 8 ########################
    # Block 8: initial conditions ("NAME value" pairs, missing ones default to 0)
    init_values = {}
    for item in parameters.get('initial_set') or []:
        parts = str(item).split()
        if len(parts) >= 2: init_values[parts[0]] = parts[1]
    initial_list = list(parameters.get('initial_list') or [])
    inc['B8_initials'] = ["MASS/M2", "INITIALS"] + [f"'{name}'" for name in initial_list] + ["DEFAULTS"]
    inc['B8_initials'] += [init_values.get(name) or "0" for name in initial_list]
    return inc, meta

def _model_blocks(model: WaqModel, parameters: dict, sample_path: str) -> dict:
    """Include files that depend on the selected model (B1 substances, B7 processes/constants, B9 output)."""
    inc = {}
    b1_path = os.path.normpath(os.path.join(sample_path, model.b1_file))
    with open(b1_path, 'r', encoding=functions.encoding_detect(b1_path)) as f:
        inc['B1_sublist'] = f.read()
    # A process is switched on by the presence of ACTIVE_<name>; 1 is the conventional value.
    inc['B7_processes'] = [f"CONSTANTS 'ACTIVE_{p}' DATA 1" for p in model.processes]
    inc['B7_constants'] = [f"CONSTANTS '{name}' DATA {value}" for name, value in model.constants.items()]
    segfunctions = []
    for name, path_key in model.segfunctions:
        if not parameters.get(path_key):
            raise ValueError(f"Model '{model.title}' needs '{path_key}' from the .hyd file, "
                "but the hydrodynamic run did not write it.")
        segfunctions.append(f"SEG_FUNCTIONS\n'{name}'\nALL\nBINARY_FILE '{_fwd(parameters[path_key])}'")
    inc['B7_segfunctions'] = segfunctions
    header = ["2 ; perform default output and extra parameters listed below",
        f"{len(model.outputs)} ; number of parameters listed"]
    inc['B9_Hisvar'] = header + [f"'{p}' 'volume'" for p in model.outputs]
    inc['B9_Mapvar'] = header + [f"'{p}'" for p in model.outputs]
    return inc

def _write_text(path: str, content) -> None:
    if isinstance(content, (list, tuple)): content = '\n'.join(content)
    with open(path, 'w', encoding=WRITE_ENCODING) as f:
        f.write(content)

def wqPreparation(parameters:dict, key:str, output_folder:str, includes_folder:str) -> tuple:
    """Write the include files and the .inp file for one water quality scenario.
    Returns (inp_path, message). On failure inp_path is None and message holds the error."""
    try:
        model = waq_models.get_model(key)
        sample_path = os.path.normpath(os.path.join(SOURCE_BACKEND, 'templates', 'waq'))
        # params_INP, params_INC, model_type = {}, {}, {"model_type": key}
        grid_path = os.path.normpath(os.path.join(os.path.dirname(parameters['hyd_path']), 'FlowFM_waqgeom.nc'))
        data = xr.open_dataset(grid_path, chunks={'time': 1}, decode_times=False)
        try: grid = functions.unstructuredGridCreator(data)
        finally: data.close()
        poi_info = poiInspector(parameters['ptr_path'], parameters['exchange_z'])
        notes = []
        inc, meta = _common_blocks(parameters, grid, poi_info, output_folder, notes)
        inc.update(_model_blocks(model, parameters, sample_path))
        # Write the include files
        for name, content in inc.items():
            _write_text(os.path.normpath(os.path.join(includes_folder, f'{name}.inc')), content)
        # Save the model type and the locations actually used (read back when showing results)
        model_info = {"model_type": model.key, **meta}
        model_path = os.path.normpath(os.path.join(output_folder, f'{parameters["folder_name"]}.json'))
        with open(model_path, 'w', encoding=WRITE_ENCODING) as f:
            json.dump(model_info, f, indent=4)
        # Write the .inp file from the template
        inp_temp = os.path.normpath(os.path.join(sample_path, 'INPFile.inp'))
        with open(inp_temp, 'r', encoding=functions.encoding_detect(inp_temp)) as f:
            content_inp = f.read()
        for placeholder, value in {'time_step': 86400}.items():  # system clock unit is 1 s
            content_inp = content_inp.replace(f'{{{placeholder}}}', str(value))
        inp_path = os.path.normpath(os.path.join(output_folder, f'{parameters["folder_name"]}.inp'))
        _write_text(inp_path, content_inp)
        return inp_path, ' '.join(notes)
    except Exception as e:
        logger.exception(f"wqPreparation failed: {str(e)}")
        return None, str(e)