import os, json, re, traceback, asyncio, shutil
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from services import functions, wq_functions, waq_models
from config import PROJECT_ROOT
import numpy as np, pandas as pd

router = APIRouter()
MISSING_VALUE = -999.0
HYD_FIELDS = {
    'attrPath': 'attr_path', 'volPath': 'vol_path', 'ptrPath': 'ptr_path', 'areaPath': 'area_path',
    'flowPath': 'flow_path', 'lengthPath': 'length_path', 'srfPath': 'srf_path', 'vdfPath': 'vdf_path',
    'temPath': 'tem_path', 'salPath': 'sal_path', 'nSegments': 'n_segments',
    'exchangeX': 'exchange_x', 'exchangeZ': 'exchange_z', 'timeStep1': 'time_step1', 'timeStep2': 'time_step2',
}


def _scenario_name(name) -> str:
    """Validate a scenario name coming from the client, so it cannot point outside the scenario folder."""
    name = str(name or '').strip()
    if name.endswith('.json'): name = name[:-5]
    if not name or name in ('.', '..') or any(c in name for c in '/\\:') or '\x00' in name:
        raise ValueError(f"Invalid scenario name '{name}'.")
    return name

def _scenario_folder(project_name: str) -> str:
    return os.path.normpath(os.path.join(PROJECT_ROOT, project_name, 'output', 'scenarios'))

def _usefors_include(folder: str) -> str:
    return f"INCLUDE 'includes_deltashell/load_data_tables/{folder}.usefors'"

@router.post("/select_hyd")
async def select_hyd(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    folder, time_zone = [PROJECT_ROOT, project_name, "DFM_DELWAQ", 'FlowFM.hyd'], body.get('timeZone')
    path = os.path.normpath(os.path.join(*folder))
    if os.path.exists(path):
        return JSONResponse({"status": 'ok', "content": wq_functions.hydReader(path, time_zone)})
    message = f"Error: Cannot find .hyd file in project '{project_name}'.\nPlease run a hydrodynamic simulation first."
    return JSONResponse({"status": 'error', "message": message})

def _parse_time_table(time_table: str, time_zone: str) -> list:
    """Turn the DATA_ITEM blocks written by /wq_time_to_waq back into rows [time, location, substance, value]."""
    rows = []
    for part in re.split('DATA_ITEM', time_table or ''):
        lines = [line.strip() for line in part.strip().split('\n') if line.strip()]
        if len(lines) < 6: continue
        location, substances = lines[0], [s.replace("'", "") for s in lines[4].split()]
        for line in lines[5:]:
            values = line.split()
            time = pd.to_datetime(values[0], utc=True, format='%Y/%m/%d-%H:%M:%S')
            time = functions.utc_to_local(time, time_zone)
            for idx, substance in enumerate(substances):
                if idx + 1 >= len(values): break
                value = values[idx + 1]
                try:
                    if float(value) == MISSING_VALUE: continue
                except ValueError: continue
                rows.append([time, location, substance, value])
    return rows

@router.post("/load_waq")
async def load_waq(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        name, time_zone = _scenario_name(body.get('waqName')), body.get('timeZone')
        path = os.path.normpath(os.path.join(_scenario_folder(project_name), f"{name}.json"))
        if not os.path.exists(path): return JSONResponse({"status": 'error', "message": 'Configuration file not found.'})
        with open(path, 'r', encoding=functions.encoding_detect(path)) as f:
            files = json.load(f)
        data = {
            'key': files['key'], 'name': files['folderName'], 'mode': files['mode'],
            'obs': files['obsPoints'], 'loads': files['loadsData'],
            'time_data': _parse_time_table(files['timeTable'], time_zone),
            'times': files['timeTable'], 'usefors': files['usefors'],
            'initial': files['initial'], 'scheme': files['scheme'],
            'maxiter': files['maxiter'], 'tolerance': files['tolerance'],
            'useforsFrom': files['useforsFrom'], 'useforsTo': files['useforsTo'],
        }
        return JSONResponse({"status": 'ok', "content": data})
    except Exception as e: 
        print('/load_waq:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}"})

@router.post("/clone_waq")
async def clone_waq(request: Request, user=Depends(functions.basic_auth)):
    extend_task = None
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        old_name, new_name = body.get('oldName'), body.get('newName')
        project_folder = _scenario_folder(project_name)
        redis = request.app.state.redis
        lock = redis.lock(f"{project_name}:clone_waq", timeout=60, blocking_timeout=10)
        async with lock:
            extend_task = asyncio.create_task(functions.auto_extend(lock))
            old_path = os.path.normpath(os.path.join(project_folder, f"{old_name}.json"))
            new_path = os.path.normpath(os.path.join(project_folder, f"{new_name}.json"))
            if not os.path.exists(old_path): 
                return JSONResponse({"status": 'error', "message": f"Scenario '{new_name}' already exists."})
            with open(old_path, 'r', encoding=functions.encoding_detect(old_path)) as f:
                data = json.load(f)
            data['folderName'] = new_name
            for sep in ('\\', '/'):
                old_inc = f"includes_deltashell{sep}load_data_tables{sep}{old_name}.usefors"
                data['timeTable'] = data['timeTable'].replace(old_inc, f"includes_deltashell/load_data_tables/{new_name}.usefors")
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            return JSONResponse({"message": f"WAQ scenario '{new_name}' was cloned successfully!"})
    except Exception as e:
        print('/clone_waq:\n==============')
        traceback.print_exc()
        return JSONResponse({"message": f"Error: {str(e)}"})
    finally:
        if extend_task:
            extend_task.cancel()
            try: await extend_task
            except asyncio.CancelledError: pass

# Delete a file
@router.post("/delete_waq")
async def delete_waq(request: Request, user=Depends(functions.basic_auth)):
    extend_task = None
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        redis, name = request.app.state.redis, _scenario_name(body.get('name'))
        scenario_folder = _scenario_folder(project_name)
        waq_folder = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, 'output', 'WAQ'))
        lock = redis.lock(f"{project_name}:delete_waq", timeout=300)
        async with lock:
            extend_task = asyncio.create_task(functions.auto_extend(lock))
            file_name = os.path.normpath(os.path.join(scenario_folder, f"{name}.json"))
            if not os.path.exists(file_name): 
                return JSONResponse({"status": 'error', "message": f"Path '{file_name}' does not exist."})
            if os.path.isdir(waq_folder):
                for f in os.listdir(waq_folder):
                    if os.path.splitext(f)[0] != name and f != name: continue
                    temp_path = os.path.normpath(os.path.join(waq_folder, f))
                    if os.path.isdir(temp_path): shutil.rmtree(temp_path)
                    else: functions.safe_remove(temp_path)
            functions.safe_remove(file_name)
            return JSONResponse({"message": f"Scenario '{name}' was deleted successfully!"})
    except Exception as e:
        print('/delete_waq:\n==============')
        traceback.print_exc()
        return JSONResponse({"message": f"Error: {str(e)}"})
    finally:
        if extend_task:
            extend_task.cancel()
            try: await extend_task
            except asyncio.CancelledError: pass

@router.post("/select_waq")
async def select_waq(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        path = _scenario_folder(project_name)
        files = sorted(f[:-5] for f in os.listdir(path) if f.endswith('.json')) if os.path.isdir(path) else []
        if len(files) == 0: return JSONResponse({"status": 'error', 'message': 'Files not found.'})
        return JSONResponse({"status": 'ok', "content": files})
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}"})

@router.post("/wq_time_from_waq")
async def wq_time_from_waq(request: Request):
    try:
        body = await request.json()
        model = waq_models.get_model(body.get('key'))
        return JSONResponse({"status": 'ok', "froms": list(model.substances)})
    except Exception as e:
        return JSONResponse({"status": 'error', "message":  f"Error: {str(e)}"})

@router.post("/wq_time_to_waq")
async def wq_time(request: Request):
    try:
        body = await request.json()
        load_data, time_data = body.get('loadsData') or [], body.get('timeData') or []
        folder, time_zone = _scenario_name(body.get('folderName')), body.get('timeZone')
        # Check whether the location in time-series is in the load data
        loads = [x[0] for x in load_data]
        if not any(row[1] in loads for row in time_data):
            return JSONResponse({"status": 'error', 
                "message": 'Error: No Location found in the table.\nThe field "Location" has to be defined in the table "List of Loads".'})        
        # Read data: rows are [local time, location, substance, value]
        df = pd.DataFrame([row[1:4] for row in time_data], columns=['source', 'substance', 'value'])
        df['time'] = pd.to_datetime([functions.local_to_utc(row[0], time_zone) for row in time_data], utc=True)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df[df['source'].isin(loads)]
        result, substances_used = [], []
        for source, group in df.groupby('source', sort=True):
            # One column per substance; if the same time is entered twice the last value wins
            table = group.pivot_table(index='time', columns='substance', values='value', aggfunc='last', dropna=False).sort_index()
            substances = [str(s) for s in table.columns]
            substances_used += [s for s in substances if s not in substances_used]
            table = table.fillna(MISSING_VALUE).astype(float)
            lines = ["DATA_ITEM", str(source), "CONCENTRATIONS", _usefors_include(folder),
                     "TIME LINEAR DATA", ' '.join(f"'{s}'" for s in substances)]
            for time, values in zip(table.index.strftime('%Y/%m/%d-%H:%M:%S'), table.values.tolist()):
                lines.append(' '.join([time] + [str(v) for v in values]))
            result.append('\n'.join(lines))
        if not result:
            return JSONResponse({"status": 'error', "message": 'The inputed time-series data is not found in the table.'})
        return JSONResponse({"status": 'ok', "content": '\n\n\n'.join(result), "tos": substances_used})
    except Exception as e: return JSONResponse({"status": 'error', "message":  f"Error: {str(e)}"})

@router.post("/waq_config_writer")
async def waq_config_writer(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        redis, file_name = request.app.state.redis, body.get('folderName')
        hyd_path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "DFM_DELWAQ", 'FlowFM.hyd'))
        if not os.path.exists(hyd_path):
            return JSONResponse({"status": 'error', "message": f"Cannot find .hyd file in project '{project_name}'."})
        hyd = wq_functions.hydReader(hyd_path, None)
        for field, hyd_key in HYD_FIELDS.items():
            if hyd_key in hyd: body[field] = hyd[hyd_key]
            else: body.pop(field, None)
        body.setdefault('exchangeY', 0)
        body['folderName'] = file_name
        lock = redis.lock(f"{project_name}:waq_config", timeout=10)
        async with lock:
            config_path = _scenario_folder(project_name)
            os.makedirs(config_path, exist_ok=True)
            config_file = os.path.normpath(os.path.join(config_path, f"{file_name}.json"))
            # Write to a temporary file first so a failed write never leaves a half-written scenario
            tmp_file = config_file + '.tmp'
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(body, f, indent=4)
            os.replace(tmp_file, config_file)
            return JSONResponse({"status": 'ok', "message": f"Configurations of model '{file_name}' saved successfully."})
    except Exception as e: return JSONResponse({"status": 'error', "message":  f"Error: {str(e)}"})
