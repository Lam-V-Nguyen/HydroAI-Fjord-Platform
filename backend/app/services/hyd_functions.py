import os, datetime, re, traceback, asyncio
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from services import functions
from config import PROJECT_ROOT, SOURCE_BACKEND
import numpy as np, pandas as pd

router = APIRouter()

# Get parameters for an existing scenario
@router.post("/get_scenario")
async def get_scenario(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
        in_dir, data = os.path.normpath(os.path.join(project_dir, "input")), {}
        if os.path.exists(in_dir):
            mdu_path = os.path.normpath(os.path.join(in_dir, "FlowFM.mdu"))
            if not os.path.exists(mdu_path):
                return JSONResponse({"status": 'error', "message": f"Scenario '{body.get('projectName')}' doesn't have an *.mdu file."})
            with open(mdu_path, 'r', encoding=functions.encoding_detect(mdu_path)) as f:
                for raw_line in f:
                    line = raw_line.split("#")[0].strip()
                    if line.startswith('AngLat'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2: data["avgLat"] = parts[1].strip()
                    elif line.startswith('NetFile'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2: data["gridPath"] = parts[1].strip()
                    elif line.startswith('Kmx'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2: data["nLayers"] = parts[1].strip()
                    elif line.startswith('TStart'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            temp = datetime.datetime.fromtimestamp(int(parts[1].strip()))
                            data["startDate"] = temp.strftime("%Y-%m-%d %H:%M:%S")
                    elif line.startswith('TStop'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            temp = datetime.datetime.fromtimestamp(int(parts[1].strip()))
                            data["stopDate"] = temp.strftime("%Y-%m-%d %H:%M:%S")
                    elif line.startswith('ObsFile'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            obs_path = os.path.normpath(os.path.join(in_dir, parts[1].strip()))
                            with open(obs_path, 'r', encoding=functions.encoding_detect(obs_path)) as f:
                                lines = f.readlines()
                            data["obsPointTable"] = [[z.replace("'", ""), y, x] 
                                for x, y, z in [line.split() for line in lines if len(line.split()) == 3]]
                    elif line.startswith('CrsFile'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            crs_path = os.path.normpath(os.path.join(in_dir, parts[1].strip()))
                            with open(crs_path, 'r', encoding=functions.encoding_detect(crs_path)) as f:
                                lines = f.readlines()
                            data["crossSectionTable"] = [[z, y, x] 
                                for x, y, z in [line.split() for line in lines if len(line.split()) == 3]]
                    elif line.startswith('ExtForceFileNew'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            boundary_path = os.path.normpath(os.path.join(in_dir, parts[1].strip()))
                            boundary, boundary_names, forcing = [], [], []
                            with open(boundary_path, 'r', encoding=functions.encoding_detect(boundary_path)) as f:
                                for line1 in f:
                                    if line1.strip().startswith('locationFile'):
                                        parts = line1.split("=")
                                        if len(parts) >= 2 and parts[1] not in boundary_names:
                                            file_path = os.path.normpath(os.path.join(in_dir, parts[1].replace("\n", "")))
                                            with open(file_path, 'r', encoding=functions.encoding_detect(file_path)) as f:
                                                line_files = f.readlines()
                                            boundary.append([[z, y, x] for x, y, z in [line.split() for line in line_files if len(line.split()) == 3]])
                                            boundary_names.append(parts[1])
                                    elif line1.strip().startswith('forcingFile'):
                                        parts = line1.split("=")
                                        if len(parts) >= 2 and parts[1] not in forcing: forcing.append(parts[1])
                            data["boundaryTable"] = boundary[0]
                    elif line.startswith('DtUser'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            values = functions.seconds_datetime(int(parts[1].strip()))
                            data["userTimestepDate"], data["userTimestepTime"] = values[0], values[1]
                    elif line.startswith('DtNodal'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            values = functions.seconds_datetime(int(parts[1].strip()))
                            data["nodalTimestepDate"], data["nodalTimestepTime"] = values[0], values[1]
                    elif line.startswith('HisInterval'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            temp = parts[1].strip()
                            seconds = int(temp.split(" ")[0].strip())
                            values = functions.seconds_datetime(seconds)
                            data["hisIntervalDate"], data["hisIntervalTime"] = values[0], values[1]
                            temp_start = int(temp.split(" ")[1].strip())
                            temp_stop = int(temp.split(" ")[2].strip())
                            start = datetime.datetime.fromtimestamp(temp_start)
                            stop = datetime.datetime.fromtimestamp(temp_stop)
                            data["hisStart"] = start.strftime("%Y-%m-%d %H:%M:%S")
                            data["hisStop"] = stop.strftime("%Y-%m-%d %H:%M:%S")
                    elif line.startswith('MapInterval'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            temp = parts[1].strip()
                            seconds = int(temp.split(" ")[0].strip())
                            values = functions.seconds_datetime(seconds)
                            data["mapIntervalDate"], data["mapIntervalTime"] = values[0], values[1]
                            temp_start = int(temp.split(" ")[1].strip())
                            temp_stop = int(temp.split(" ")[2].strip())
                            start = datetime.datetime.fromtimestamp(temp_start)
                            stop = datetime.datetime.fromtimestamp(temp_stop)
                            data["mapStart"] = start.strftime("%Y-%m-%d %H:%M:%S")
                            data["mapStop"] = stop.strftime("%Y-%m-%d %H:%M:%S")
                    elif line.startswith('WaqInterval'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            temp = parts[1].strip()
                            seconds = int(temp.split(" ")[0].strip())
                            values = functions.seconds_datetime(seconds)
                            data["wqIntervalDate"], data["wqIntervalTime"] = values[0], values[1]
                            temp_start = int(temp.split(" ")[1].strip())
                            temp_stop = int(temp.split(" ")[2].strip())
                            start = datetime.datetime.fromtimestamp(temp_start)
                            stop = datetime.datetime.fromtimestamp(temp_stop)
                            data["wqStart"] = start.strftime("%Y-%m-%d %H:%M:%S")
                            data["wqStop"] = stop.strftime("%Y-%m-%d %H:%M:%S")
                    elif line.startswith('StatsInterval'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            values = functions.seconds_datetime(int(parts[1].strip()))
                            data["statisticDate"], data["statisticTime"] = values[0], values[1]
                    elif line.startswith('TimingsInterval'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2:
                            values = functions.seconds_datetime(int(parts[1].strip()))
                            data["timingDate"], data["timingTime"] = values[0], values[1]
                    elif line.startswith('WaterLevIni'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2: data["initWaterLevel"] = parts[1].strip()
                    elif line.startswith('InitialSalinity'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2: data["initSalinity"] = parts[1].strip()
                    elif line.startswith('Temperature'):
                        parts = [p.strip() for p in line.split("=") if p.strip()]
                        if len(parts) == 2: data["initTemperature"] = parts[1].strip()
            data["meteoPath"], meteos, data["meteoName"] = '', [], "FlowFM_meteo.tim"
            meteo_path = os.path.normpath(os.path.join(in_dir, data["meteoName"]))
            if os.path.exists(meteo_path):
                with open(meteo_path, 'r', encoding=functions.encoding_detect(meteo_path)) as f:
                    lines = f.readlines()
                for line in lines:
                    line = line.replace("\n", "")
                    if len(line.strip().split()) != 5: continue
                    temp = line.strip().split()
                    temp[0] = datetime.datetime.fromtimestamp(int(temp[0].strip())*60).strftime("%Y-%m-%d %H:%M:%S")
                    meteos.append(temp)
                data["meteoPath"] = meteos
            data["weatherPath"], weathers, data["weatherType"], data["weatherName"] = '', [], '', "windxy.tim"
            weather_path = os.path.normpath(os.path.join(in_dir, data["weatherName"]))
            if os.path.exists(weather_path):
                with open(weather_path, 'r', encoding=functions.encoding_detect(weather_path)) as f:
                    lines = f.readlines()
                for line in lines:
                    line = line.replace("\n", "")
                    if not line.strip(): continue
                    temp = line.strip().split()
                    temp[0] = datetime.datetime.fromtimestamp(int(temp[0].strip())*60).strftime("%Y-%m-%d %H:%M:%S")
                    weathers.append(temp)
                if len(temp) == 3: data["weatherType"] = "wind-magnitude-direction"
                data["weatherPath"] = weathers
            return JSONResponse({"status": 'ok', "content": data})
        else: return JSONResponse({"status": 'new'})
    except Exception as e:
        print('/get_scenario:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}\nConsider running the scenario again."})

# Get list of source from .ext file
@router.post("/init_source")
async def init_source(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    path, key = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input", "FlowFM.ext")), body.get('key')
    if os.path.exists(path):
        with open(path, 'r', encoding=functions.encoding_detect(path)) as f:
            content = f.read()
        parts = re.split(r'\n\s*\n', content)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) == 0: 
            os.remove(path)
            return JSONResponse({"status": 'error', "content": [], "type": []})
        lts = [re.search(r'FILENAME=(.+?)\.pli', p).group(1) for p in parts if re.search(r'FILENAME=(.+?)\.pli', p)]
        if len(lts) == 0: return JSONResponse({"status": 'error', "content": [], "type": []})        
        if not key == '':
            check = [i[0] for i in key]
            item_remove = [p for p in lts if p not in check]
            if len(item_remove) > 0:
                item_remove = item_remove[0]
                temp_path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))
                for part in parts:
                    if item_remove in part:
                        parts.remove(part)
                        pli_path = os.path.normpath(os.path.join(temp_path, f"{item_remove}.pli"))
                        tim_path = os.path.normpath(os.path.join(temp_path, f"{item_remove}.tim"))
                        if os.path.exists(pli_path): os.remove(pli_path)
                        if os.path.exists(tim_path): os.remove(tim_path)
            with open(path, 'w', encoding=functions.encoding_detect(path)) as file:
                joined_parts = '\n\n'.join(parts)
                file.write(f"\n{joined_parts}\n")
        status, data, type = 'ok', [], []
        for part in parts:
            if 'QUANTITY=discharge_salinity_temperature_sorsin' in part:
                match = re.search(r'FILENAME=(.+?)\.pli', part)
                if match:
                    data.append(match.group(1))
                    type.append('discharge_salinity_temperature_sorsin')
    else: status, data, type = 'error', [], []
    return JSONResponse({"status": status, "content": data, "type": type})

# Update boundary conditions
@router.post("/update_boundary")
async def update_boundary(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        subBoundaryName = body.get('subBoundaryName')
        boundary_name, data_boundary = body.get('boundaryName'), body.get('boundaryData')
        boundary_type, data_sub = body.get('boundaryType'), body.get('subBoundaryData')
        if boundary_type == 'Contaminant': unit = '-'; quantity = 'tracerbndContaminant'
        else: unit = 'm'; quantity = 'waterlevelbnd'
        # Parse date
        config = {
            'sub_boundary': subBoundaryName, 'boundary_type': quantity, 
            'unit': unit, 'ref_date': '1970-01-01 00:00:00'
            }
        temp_file = os.path.normpath(os.path.join(SOURCE_BACKEND, 'templates', 'hyd', 'BC.bc'))
        temp, bc = [], [boundary_name]
        for row in data_sub:
            row[0] = int(row[0]/1000.0); temp.append(row)
        lines = [f"{int(x)}  {y}" for x, y in temp]
        config['data'] = '\n'.join(lines)
        path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))
        # Write new format boundary file (*_bnd.ext)
        ext_path = os.path.normpath(os.path.join(path, "FlowFM_bnd.ext"))
        file_content = '[boundary]\n' + f'quantity={quantity}\n' + \
            f'locationFile={boundary_name}.pli\n' + f'forcingFile={boundary_type}.bc'
        if os.path.exists(ext_path):
            with open(ext_path, encoding=functions.encoding_detect(ext_path)) as f:
                content = f.read()
            parts = re.split(r'(?=\[boundary\])', content)
            parts = [p.strip() for p in parts if p.strip()]
            if (any(boundary_type in part for part in parts)): 
                index = parts.index([part for part in parts if boundary_type in part][0])
                parts[index] = file_content
            else: parts.append(file_content)
            with open(ext_path, 'w', encoding=functions.encoding_detect(ext_path)) as file:
                joined_parts = '\n\n'.join(parts)
                file.write(f"\n{joined_parts}\n")
                file.flush()
                os.fsync(file.fileno())
        else:   
            with open(ext_path, 'w', encoding=functions.encoding_detect(ext_path)) as file:
                file.write(f"\n{file_content}\n")
                file.flush()
                os.fsync(file.fileno())
        # Write boundary file (*.pli)
        boundary_file = os.path.normpath(os.path.join(path, f"{boundary_name}.pli"))
        bc.append(f'    {len(data_boundary)}    2')
        for row in data_boundary:
            temp = f'{row[2]}    {row[1]}    {row[0]}'
            bc.append(temp)
        with open(boundary_file, 'w', encoding=functions.encoding_detect(boundary_file)) as file:
            file.write('\n'.join(bc))
            file.flush()
            os.fsync(file.fileno())
        # Write boundary conditions file
        file_path = os.path.normpath(os.path.join(path, f"{boundary_type}.bc"))
        update_content = functions.fileWriter(temp_file, config)
        if os.path.exists(file_path):
            with open(file_path, encoding=functions.encoding_detect(file_path)) as f:
                content = f.read()
            parts = re.split(r'(?=\[forcing\])', content)  # Split the file content
            parts = [p.strip() for p in parts if p.strip()]  # Remove empty parts
            if (any(subBoundaryName in part for part in parts)): 
                index = parts.index([part for part in parts if subBoundaryName in part][0])
                parts[index] = update_content
            else: parts.append(update_content)                
            with open(file_path, 'w', encoding=functions.encoding_detect(file_path)) as file:
                joined_parts = '\n\n'.join(parts)
                file.write(joined_parts)
                file.flush()
                os.fsync(file.fileno())
        else:
            file_content = functions.fileWriter(temp_file, config)
            with open(file_path, 'w', encoding=functions.encoding_detect(file_path)) as file:
                file.write(file_content + '\n')
                file.flush()
                os.fsync(file.fileno())
        status, message = 'ok', f"Saved successfully: 'Sub-boundary: {subBoundaryName} - Type: {boundary_type}'."
    except Exception as e:
        print('/update_boundary:\n==============')
        traceback.print_exc()
        status, message = 'error', f"Error: {str(e)}"
    return JSONResponse({"status": status, "message": message})

# Get boundary properties
@router.post("/get_boundary_params")
async def get_boundary_params(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        boundary_name, boundary_type = body.get('boundaryName'), body.get('boundaryType')     
        input_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))
        type_path = os.path.normpath(os.path.join(input_dir, f"{boundary_type}.bc"))
        if not os.path.exists(type_path): return JSONResponse({"status": 'new'})
        with open(type_path, 'r', encoding=functions.encoding_detect(type_path)) as f:
            lines = f.readlines()
        current_data, check, content = [], False, []
        for line in lines:
            if not line.strip(): continue
            if line.startswith("Name"):
                temp_name = line.split("=", 1)[1].strip()
                if temp_name == boundary_name: check = True
            if line[0].isdigit() and check: current_data.append(line.replace("\n", ""))
            if line.startswith("[forcing]"): check = False
        for line in current_data:
            temp = line.strip().split()
            val = datetime.datetime.fromtimestamp(int(temp[0]))
            content.append([val.strftime("%Y-%m-%d %H:%M:%S"), temp[1]])
        if not content: return JSONResponse({"status": 'new'})
        return JSONResponse({"status": 'ok', "content": content})   
    except Exception as e:
        print('/get_boundary_params:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f'Error: {str(e)}'})

# Check boundary conditions
@router.post("/check_condition")
async def check_condition(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    force_name = body.get('forceName')
    path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))
    status, ext_path = 'error', os.path.normpath(os.path.join(path, force_name))
    if os.path.exists(ext_path): status = 'ok'
    return JSONResponse({"status": status})
   
# View boundary conditions
@router.post("/view_boundary")
async def view_boundary(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        boundary_type = body.get('boundaryType')        
        path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))
        # Read file
        path = os.path.normpath(os.path.join(path, f"{boundary_type}.bc"))
        with open(path, 'r', encoding=functions.encoding_detect(path)) as f:
            data = ''.join(f.readlines())
        status, message = 'ok', ""
    except FileNotFoundError:
        status, message, data = 'error', '- No boundary condition found.\n- Boundary is not created yet.', None
    except Exception as e:
        print('/view_boundary:\n==============')
        traceback.print_exc()
        status, message, data = 'error', f"Error: {str(e)}", None
    return JSONResponse({"status": status, "message": message, "content": data})

# Delete boundary conditions
@router.post("/delete_boundary")
async def delete_boundary(request: Request, user=Depends(functions.basic_auth)):
    try:
        body, message = await request.json(), "Deleted boundary conditions.\n"
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        boundary_name = body.get('boundaryName')
        path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))
        water_lelvel_path = os.path.normpath(os.path.join(path, "WaterLevel.bc"))
        contaminant_path = os.path.normpath(os.path.join(path, "Contaminant.bc"))
        ext_path = os.path.normpath(os.path.join(path, "FlowFM_bnd.ext"))
        # Delete file
        for boundary in boundary_name:
            boundary_path = os.path.normpath(os.path.join(path, f"{boundary}.pli"))
            if os.path.exists(boundary_path):
                os.remove(boundary_path)
                message += f"- Deleted successfully: {boundary}'.pli.\n"
        if os.path.exists(ext_path):
            os.remove(ext_path)
            message += "- Deleted successfully: FlowFM_bnd.ext.\n"
        if os.path.exists(water_lelvel_path):
            os.remove(water_lelvel_path)
            message += "- Deleted successfully: WaterLevel.bc.\n"
        if os.path.exists(contaminant_path):
            os.remove(contaminant_path)
            message += "- Deleted successfully: Contaminant.bc."
        return JSONResponse({"status": 'ok', "message": message})
    except Exception as e:
        print('/delete_boundary:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f'Error: {str(e)}'})

# Save source to CSV file
@router.post("/save_source")
async def save_source(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        lat, lon, BCCheck = body.get('lat'), body.get('lon'), body.get('BC')
        data, source_name = body.get('data'), body.get('nameSource')
        redis = request.app.state.redis
        lock = redis.lock(f"{project_name}:save_source:{source_name}", timeout=10)
        path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))        
        async with lock:
            os.makedirs(path, exist_ok=True)
            update_content = 'QUANTITY=discharge_salinity_temperature_sorsin\n' + \
                f'FILENAME={source_name}.pli\n' + 'FILETYPE=9\n' + 'METHOD=1\n' + 'OPERAND=O\n' + 'AREA=1'
            # Write old format boundary file (*.ext)
            ext_path = os.path.normpath(os.path.join(path, "FlowFM.ext"))
            if os.path.exists(ext_path):
                with open(ext_path, 'r', encoding=functions.encoding_detect(ext_path)) as f:
                    content = f.read()
                blocks = re.split(r'\n\s*\n', content)
                blocks = [p.strip() for p in blocks if p.strip()]
                updated = False
                for i, block in enumerate(blocks):
                    if f'FILENAME={source_name}.pli' in block:
                        blocks[i] = update_content
                        updated = True
                        break
                if not updated:
                    blocks.append(update_content)
                new_content = '\n\n'.join(blocks)
            else: new_content = f"\n{update_content}\n"
            with open(ext_path, 'w', encoding=functions.encoding_detect(ext_path)) as f:
                f.write(new_content.strip() + "\n")
            # Write .pli file
            pli_path = os.path.normpath(os.path.join(path, f"{source_name}.pli"))
            with open(pli_path, 'w', encoding=functions.encoding_detect(pli_path)) as f:
                f.write(f'{source_name}\n')
                f.write('    1    2\n')
                f.write(f"{lon}  {lat}\n")
            # Write .tim file
            tim_path = os.path.normpath(os.path.join(path, f"{source_name}.tim"))
            with open(tim_path, 'w', encoding=functions.encoding_detect(tim_path)) as f:
                for row in data:
                    try: t = float(row[0])/(1000.0*60.0)
                    except Exception: t = 0
                    if int(BCCheck)==1: values = [str(t)] + [str(r) for r in row[1:]]
                    else: values = [str(t)] + [str(r) for r in row[1:-1]]
                    f.write('  '.join(values) + '\n')
            return JSONResponse({"status": 'ok', "message": f"Source '{source_name}' saved successfully."})
    except Exception as e:
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}"})

# Save observations data to project
@router.post("/save_obs")
async def save_obs(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        data, key, file_name = body.get('data'), body.get('key'), body.get('fileName')
        path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "input"))
        redis = request.app.state.redis
        lock = redis.lock(f"{project_name}:save_obs:{file_name}", timeout=10)
        def write_file(path, file_name, data, key):
            file_path = os.path.normpath(os.path.join(path, file_name))
            with open(file_path, 'w', encoding=functions.encoding_detect(file_path)) as f:
                if key == 'obs':
                    for line in data:
                        f.write(f"{line[2]}  {line[1]}  '{line[0]}'\n")
                elif key == 'crs':
                    name = file_name.replace('_crs.pli', '')
                    data = np.array(data)
                    f.write(f"{name}\n")
                    f.write(f"    {data.shape[0]}    2\n")
                    for line in data:
                        f.write(f"{line[2]}  {line[1]}  {line[0]}\n")
        async with lock:
            await asyncio.to_thread(write_file, path, file_name, data, key)
            status, message = 'ok', 'Observations saved successfully.'
    except Exception as e:
        status, message = 'error', f"Error: {str(e)}"
    return JSONResponse({"status": status, "message": message})

# Save meteo data to project
@router.post("/save_meteo")
async def save_meteo(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    content = 'QUANTITY=humidity_airtemperature_cloudiness_solarradiation\n' + \
            'FILENAME=FlowFM_meteo.tim\n' + 'FILETYPE=1\n' + 'METHOD=1\n' + 'OPERAND=O'
    # Time difference in minutes
    status, message = functions.contentWriter(project_name, "FlowFM_meteo.tim", body.get('data'), content, 'min')
    return JSONResponse({"status": status, "message": message})

# Save meteo data to project
@router.post("/save_weather")
async def save_weather(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    content = 'QUANTITY=windxy\n' + 'FILENAME=windxy.tim\n' + 'FILETYPE=2\n' + 'METHOD=1\n' + 'OPERAND=+'
    # Time difference in minutes
    status, message = functions.contentWriter(project_name, "windxy.tim", body.get('data'), content, 'min')
    return JSONResponse({"status": status, "message": message})

# Create MDU file
@router.post("/generate_mdu")
async def generate_mdu(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        params = dict(body.get('params'))
        project_name, _ = functions.project_definer(params['project_name'], user)
        status, message = 'ok', f"Scenario '{project_name}' is created/modified successfully!"
        # Create MDU file
        project_path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, 'input'))
        mdu_path = os.path.normpath(os.path.join(SOURCE_BACKEND, 'templates', 'hyd', 'MDUFile.mdu'))
        file_content = functions.fileWriter(mdu_path, params)
        # Write file
        path = os.path.normpath(os.path.join(project_path, 'FlowFM.mdu'))
        with open(path, 'w', encoding=functions.encoding_detect(path)) as file:
            file.write(file_content)
    except Exception as e:
        print('/generate_mdu:\n==============')
        traceback.print_exc()
        status, message = 'error', f"Error: {str(e)}"
    return JSONResponse({"status": status, "message": message})

@router.post("/get_result")
async def get_result(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        project_dir = os.path.join(PROJECT_ROOT, project_name)
        csv_path = os.path.join(project_dir, body.get('fileName'))
        if not os.path.exists(csv_path):
            return JSONResponse({"status": 'error', "message": 'Data path not found.'})
        meteo = pd.read_csv(csv_path)
        functions.safe_remove(csv_path)
        return JSONResponse({"content": meteo.values.tolist()})
    except Exception as e:
        print('/get_result:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}"})
