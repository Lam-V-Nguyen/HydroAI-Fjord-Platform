import traceback, asyncio, os, shutil, json, msgpack
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from config import PROJECT_ROOT
from services import functions
import numpy as np


router = APIRouter()

@router.post("/auth_check")
async def auth_check(user=Depends(functions.basic_auth)):
    output = 'ok' if user == 'admin' else 'error'
    return {"user": user, "output": output}

# Create a new project with necessary folders
@router.post("/setup_new_project")
async def setup_new_project(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
        os.makedirs(project_dir, exist_ok=True)
        folders = ['GIS', 'output', 'output/config', 'output/HYD', 'output/WAQ', 'flows']
        for folder in folders:
            folder_path = os.path.normpath(os.path.join(project_dir, folder))
            if not os.path.exists(folder_path): os.makedirs(folder_path, exist_ok=True)
        status, message = project_name, f"Scenario '{body.get('projectName')}' created successfully!"
    except Exception as e:
        print('/setup_new_project:\n==============')
        traceback.print_exc()
        status, message = 'error', f"Error: {str(e)}"
    return JSONResponse({"status": status, "message": message})

# Copy a project
@router.post("/copy_project")
async def copy_project(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        old_name, _ = functions.project_definer(body.get('oldName'), user)
        new_name, _ = functions.project_definer(body.get('newName'), user)
        project_folder = os.path.normpath(os.path.join(PROJECT_ROOT, old_name))
        redis = request.app.state.redis
        extend_task, lock = None, redis.lock(f"{old_name}:copy_project", timeout=600)
        async with lock:
            # Optional: auto-extend lock if deletion may take long
            extend_task = asyncio.create_task(functions.auto_extend(lock))
            if not os.path.exists(project_folder): 
                return JSONResponse({"status": 'error', "message": f"Project '{old_name}' does not exist."})
            shutil.copytree(project_folder, os.path.normpath(os.path.join(PROJECT_ROOT, new_name)))
            return JSONResponse({"message": f"HYD scenario '{new_name}' was cloned successfully!"})
    except Exception as e:
        print('/copy_project:\n==============')
        traceback.print_exc()
        return JSONResponse({"message": f"Error: {str(e)}"})
    finally:
        if extend_task:
            extend_task.cancel()
            try: await extend_task
            except asyncio.CancelledError: pass

# Delete a project
@router.post("/delete_project")
async def delete_project(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        redis = request.app.state.redis
        name = project_name if '/' not in project_name else project_name.split('/')[-1]
        lock = redis.lock(f"{project_name}:delete_project", timeout=600)
        project_folder, extend_task = os.path.normpath(os.path.join(PROJECT_ROOT, project_name)), None
        async with lock:
            # Optional: auto-extend lock if deletion may take long
            extend_task = asyncio.create_task(functions.auto_extend(lock))
            if not os.path.exists(project_folder): 
                return JSONResponse({"status": 'error', "message": f"Project '{project_name}' does not exist."})
            shutil.rmtree(project_folder, onerror=functions.remove_readonly)
            if hasattr(request.app.state, "project_cache"): request.app.state.project_cache.pop(project_name, None)
            return JSONResponse({"status": "ok", "message": f"Project '{name}' was deleted successfully."})
    except Exception as e:
        print('/delete_project:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}"})
    finally:
        if extend_task:
            extend_task.cancel()
            try: await extend_task
            except asyncio.CancelledError: pass

@router.post("/select_project")
async def select_project(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        key, folder_check = body.get('key'), body.get('folder_check')
        project_name, _ = functions.project_definer(body.get('filename'), user)
        project_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name))
        if key == 'getProjects':
            project = [p.name for p in os.scandir(project_dir) if p.is_dir()]
            project = [p for p in project if os.path.exists(os.path.normpath(os.path.join(project_dir, p, folder_check)))]
            data = sorted(project)
        elif key == 'getWAQs': # List the scenarios for water quality
            scenario_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, 'output', 'scenarios'))
            project = [p.name for p in os.scandir(scenario_dir)]
            project = [p.replace('.json', '') for p in project if os.path.exists(os.path.normpath(os.path.join(scenario_dir, p)))]
            data = sorted(project)
        # elif key == 'getFiles': # List the files
        #     project_folder = os.path.normpath(os.path.join(PROJECT_STATIC_ROOT, project_name))
        #     hyd_folder = os.path.normpath(os.path.join(project_folder, "output", 'HYD'))
        #     waq_folder = os.path.normpath(os.path.join(project_folder, "output", 'WAQ'))
        #     hyd_files, waq_files = [], []
        #     if os.path.exists(hyd_folder):
        #         hyd_files = [f for f in os.listdir(hyd_folder) if f.endswith(".zarr")]
        #         hyd_files = set([f.replace('_his.zarr', '').replace('_map.zarr', '') for f in hyd_files])
        #     if os.path.exists(waq_folder):
        #         waq_files = [
        #             (entry.name, entry.stat().st_ctime)
        #             for entry in os.scandir(waq_folder)
        #             if entry.is_file() and entry.name.endswith(".json")
        #         ]
        #         waq_files.sort(key=lambda x: x[1], reverse=True)
        #         waq_files = [name.replace('.json', '') for name, _ in waq_files]
        #     data = {'hyd': list(hyd_files), 'waq': waq_files}
        return JSONResponse({"content": data})
    except Exception as e:
        print('/select_project:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}"})




















