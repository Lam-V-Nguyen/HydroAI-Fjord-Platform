import os, json, traceback, rasterio, shutil, asyncio, tempfile
import sknw, rioxarray, zipfile, pyflwdir, threading
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse
import geopandas as gpd, numpy as np, pandas as pd
from config import PROJECT_ROOT, SOURCE_BACKEND
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from shapely.geometry import LineString
from shapely.ops import unary_union, linemerge
from shapely import force_2d
from pyflwdir import dem
from skimage.morphology import skeletonize
from services import functions, flow_functions, data_functions
from rasterio.io import MemoryFile
from contextlib import suppress


router, process_lock = APIRouter(), threading.Lock()


@router.post("/flow_project")
async def flow_project(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    try:
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name, content, content['water'], content['dtm'] = body.get('flowName'), {}, '', ''
        flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", flow_name))
        if not os.path.exists(flow_dir):
            os.makedirs(flow_dir, exist_ok=True)
            return JSONResponse({'status': 'create', 'message': f"Project '{flow_name}' created successfully."})
        water_dir = os.path.join(flow_dir, 'water_area')
        if os.path.exists(water_dir):
            file_water = [f for f in os.listdir(water_dir) if f.endswith(".geojson")]
            content['water'] = file_water[0] if len(file_water) > 0 else ''
        files = [f for f in os.listdir(flow_dir) if f.endswith("_filled.tif")]
        content['dtm'] = ''
        if len(files) > 0 and os.path.exists(os.path.join(flow_dir, files[0].replace("_filled", ""))):
            content['dtm'] = files[0].replace("_filled", "")
        soil_dir, soil_dict = os.path.join(flow_dir, 'soil'), []
        if os.path.exists(soil_dir):
            soils = [f for f in os.listdir(soil_dir) if f.endswith(".tif") and f != 'soilthickness.tif']
            if len(soils) > 0:
                for soil in soils:
                    soil_type, soil_depth = soil.split('.')[0].split('_')
                    temp = [
                        flow_functions.soil_type_reverse[soil_type],
                        flow_functions.soil_depth_reverse[soil_depth]
                    ]
                    soil_dict.append({'value': soil.removesuffix('.tif'), 'label': (' - ').join(temp)})
                soil_dict.append({'value': 'soilthickness', 'label': 'soilthickness'})
                content['soil'] = soil_dict
        else: content['soil'] = []
        forcing_path = os.path.normpath(os.path.join(flow_dir, 'forcing', 'forcing.json'))
        try:
            with open(forcing_path) as f:
                forcing = json.load(f)
                start, end, interval = forcing['start'], forcing['end'], forcing['interval']
            content['forcing'] = {'start': start, 'end': end, 'interval': interval}
        except: content['forcing'] = {'start': '', 'end': '', 'interval': '1h'}
        return JSONResponse({'content': content})
    except Exception as e:
        print('/flow_project:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/delete_project_flow")
async def delete_project_flow(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name, redis = body.get('flowName'), request.app.state.redis
        flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", flow_name))
        lock, extend_task = redis.lock(f"{project_name}:delete_flow", timeout=600), None
        async with lock:
            extend_task = asyncio.create_task(functions.auto_extend(lock))
            if not os.path.exists(flow_dir): 
                return JSONResponse({"status": 'error', "message": f"Project '{project_name}' does not exist."})
            shutil.rmtree(flow_dir, onerror=functions.remove_readonly)
            if hasattr(request.app.state, "project_cache"): request.app.state.project_cache.pop(project_name, None)
            return JSONResponse({"status": "ok", "message": f"Project '{flow_name}' was deleted successfully."})
    except Exception as e:
        print('/delete_project_flow:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}"})
    finally:
        if extend_task:
            extend_task.cancel()
            try: await extend_task
            except asyncio.CancelledError: pass

@router.post("/water_upload")
async def water_upload(projectName: str = Form(...), file: UploadFile = File(...), 
    flowName: str = Form(...), user=Depends(functions.basic_auth)):
    try:
        project_name, _ = functions.project_definer(projectName, user)
        flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows"))
        water_dir = os.path.normpath(os.path.join(flow_dir, flowName, "water_area"))
        if os.path.exists(water_dir): shutil.rmtree(water_dir)
        os.makedirs(water_dir, exist_ok=True)
        water_path = os.path.normpath(os.path.join(water_dir, file.filename))
        with open(water_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file.file.close()
        content = {
            'message': 'Water area uploaded successfully.',
            "water_area": json.loads(gpd.read_file(water_path).to_json())
        }
        return JSONResponse({'status': 'ok', 'content': content})
    except Exception as e:
        print('/water_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/water_delete")
async def water_delete(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name = body.get('flowName')
        flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", flow_name, 'water_area'))
        if not os.path.exists(flow_dir):
            return JSONResponse({'status': 'ok', 'message': "Water area has already been deleted."})
        shutil.rmtree(flow_dir)
        return JSONResponse({'status': 'ok', 'message': "Water area is deleted successfully."})
    except Exception as e:
        print('/water_delete:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/upload_terrain_flow")
async def upload_terrain_flow(file: UploadFile = File(...), flowName: str = Form(...),
    projectName: str = Form(...), user=Depends(functions.basic_auth)):
    try:
        project_name, _ = functions.project_definer(projectName, user)
        flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", flowName))
        os.makedirs(flow_dir, exist_ok=True)
        terrain_path = os.path.normpath(os.path.join(flow_dir, 'dem.tif'))
        with open(terrain_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        raw_dir = os.path.normpath(os.path.join(flow_dir, 'raw'))
        os.makedirs(raw_dir, exist_ok=True)
        raw_path = os.path.normpath(os.path.join(raw_dir, 'dtm_raw.tif'))
        content = data_functions.prepare_terrain(project_name, terrain_path, raw_path)
        return JSONResponse(content)
    except Exception as e:
        print('/upload_terrain_flow:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})
    finally: await file.close()

@router.post("/clip_dem")
async def clip_dem(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name, catchment = body.get('flowName'), body.get('catchment')
        flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", flow_name))
        terrain_path = os.path.normpath(os.path.join(flow_dir, 'raw', 'dtm_raw.tif'))
        if not os.path.exists(terrain_path):
            return JSONResponse({'status': 'error', 'message': "Cannot find terrain data. Please upload terrain first."})
        catchment_WGS84 = gpd.GeoDataFrame.from_features(catchment['features'], crs="EPSG:4326")
        with rioxarray.open_rasterio(terrain_path) as src:
            terrain = src.squeeze(drop=True).load()
        catchment_reprojected = catchment_WGS84.to_crs(terrain.rio.crs)
        buffer = 10*terrain.rio.resolution()[0] if not terrain.rio.crs.is_geographic else 0.001
        catchment_buffer = catchment_reprojected.buffer(buffer)
        minx, miny, maxx, maxy = catchment_buffer.total_bounds
        terrain_clipped = terrain.rio.clip_box(minx, miny, maxx, maxy)
        terrain_values, nodata = terrain_clipped.values, -9999.0
        height, width = terrain_clipped.rio.height, terrain_clipped.rio.width
        crs, transform = terrain_clipped.rio.crs, terrain_clipped.rio.transform()
        profile = {
            "driver": "GTiff", "count": 1, "dtype": np.float32, "crs": crs,
            "height": height, "width": width, "transform": transform
        }
        flow_functions.write_geotif(terrain_values, profile, terrain_path, nodata)
        return JSONResponse({"status": "ok", "message": f"DEM was clipped successfully."})
    except Exception as e:
        print('/clip_dem:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/geojson_upload")
async def geojson_upload(file: UploadFile = File(...)):
    try:
        catchment = gpd.read_file(file.file)
        if catchment.empty: 
            return JSONResponse({'status': 'error', 'message': 'Incorrect catchment file. Please upload another.'})
        if catchment.crs != "EPSG:4326": catchment = catchment.to_crs("EPSG:4326")
        return JSONResponse({'status': 'ok', 'content': json.loads(catchment.to_json())})
    except Exception as e:
        print('/geojson_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})
    finally: await file.close()

@router.post("/data_upload")
async def data_upload(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        status, key = 'ok', body.get('key')
        if key == "soil":
            soil_type, soil_depth, content = flow_functions.soils[0], flow_functions.soils[1], []
            for soil in soil_type:
                for depth in soil_depth:
                    content.append([soil, depth, 'cm'])
            return JSONResponse({'status': 'ok', 'content': content})
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", body.get('flowName'))
        if key == "water":
            water_path = os.path.normpath(os.path.join(flow_dir, 'water_area', body.get('water')))
            if not os.path.exists(water_path):
                return JSONResponse({'status': 'error', 'message': "Cannot find water area data. Please upload water area first."})
            gdf = gpd.read_file(water_path)
            content = json.loads(gdf.to_json())
        elif key == "land-open":
            land_path = os.path.normpath(os.path.join(flow_dir, 'landcover', 'corine.tif'))
            if not os.path.exists(land_path):
                return JSONResponse({'status': 'error', 'message': "Cannot find land cover data. Please upload land cover first."})
            table_path = os.path.normpath(os.path.join(flow_dir, 'landcover', 'corine.csv'))
            if not os.path.exists(table_path):
                return JSONResponse({'status': 'error', 'message': "Cannot find look up table for land cover data. Please upload land cover first."})
            df = pd.read_csv(table_path)
            catchment_path = os.path.normpath(os.path.join(flow_dir, 'catchment', 'catchment.geojson'))
            if not os.path.exists(catchment_path):
                return JSONResponse({'status': 'error', 'message': "Cannot find catchment data. Please define catchment first."})
            catchment = gpd.read_file(catchment_path)
            terrain_path = os.path.normpath(os.path.join(flow_dir, 'raw', 'dtm_raw.tif'))
            if not os.path.exists(terrain_path):
                return JSONResponse({'status': 'error', 'message': "Cannot find terrain data. Please process terrain first."})
            with rasterio.open(terrain_path) as src:
                resolution_x, resolution_y = src.res
                buffer = max(abs(resolution_x), abs(resolution_y))
                catchment_projected = catchment.to_crs(src.crs)
                catchment_buffer = catchment_projected.buffer(buffer)
            gdf = data_functions.raster_vector(land_path, df, catchment_buffer)
            if len(gdf) == 0: return JSONResponse({'status': 'error', 'message': 'No Land Cover data found.'})
            content = json.loads(gdf.to_json())
        elif key == "land-load":
            if body.get('landSource') == "corine":
                terrain_path = os.path.normpath(os.path.join(flow_dir, 'raw', 'dtm_raw.tif'))
                if not os.path.exists(terrain_path):
                    return JSONResponse({'status': 'error', 'message': "Cannot find terrain data. Please upload terrain first."})
                catchment_path = os.path.normpath(os.path.join(flow_dir, 'catchment', 'catchment.geojson'))
                if not os.path.exists(catchment_path):
                    return JSONResponse({'status': 'error', 'message': "Cannot find catchment data in the scenario.\nDefine catchment first."})
                catchment = gpd.read_file(catchment_path)
                with rioxarray.open_rasterio(terrain_path) as src:
                    terrain = src.squeeze(drop=True).load()
                with rasterio.open(terrain_path) as src:
                    nodata, profile, dem_array = src.nodata, src.profile, src.read(1)
                    resolution_x, resolution_y = src.res
                    buffer = max(abs(resolution_x), abs(resolution_y))
                    catchment_projected = catchment.to_crs(src.crs)
                    catchment_buffer = catchment_projected.buffer(buffer)
                profile_writer, NODATA_FLWDR = profile.copy(), 255
                mask_nan = np.isnan(dem_array) | (dem_array == nodata)
                # Create land cover nc file
                land_dir = os.path.normpath(os.path.join(flow_dir, 'landcover'))
                if not os.path.exists(land_dir): os.makedirs(land_dir)
                # Land cover data from CORINE 2018
                corine_path = os.path.normpath(
                    os.path.join(SOURCE_BACKEND, 'flow_samples', 'landcover', 'U2018_CLC2018_V2020_20u1.zip')
                )
                with zipfile.ZipFile(corine_path, "r") as zip_ref:
                    name = os.path.basename(corine_path).replace(".zip", ".tif")
                    with zip_ref.open(name) as f:
                        with MemoryFile(f.read()) as memfile:
                            corine = rioxarray.open_rasterio(memfile).squeeze()
                            corine_match = corine.rio.reproject_match(terrain, resampling=Resampling.nearest)
                land_corine = corine_match.values.astype(np.uint8)
                land_corine[mask_nan] = NODATA_FLWDR
                land_path = os.path.normpath(os.path.join(land_dir, 'corine.tif'))
                profile_writer.update(dtype=np.uint8)
                flow_functions.write_geotif(land_corine, profile_writer, land_path, NODATA_FLWDR)
                # Save look up table
                df = pd.read_csv(os.path.normpath(os.path.join(SOURCE_BACKEND, 'flow_samples', 'landcover', 'corine_mapping.csv')))
                mask_csv = df['corine'] != 999
                df.loc[~mask_csv, 'corine'], df.loc[~mask_csv, 'landuse'] = 48, -999.0
                df.loc[mask_csv, 'corine'] = np.arange(1, len(df.loc[mask_csv, 'corine']) + 1).astype(np.uint8)
                df.to_csv(os.path.normpath(os.path.join(land_dir, 'corine.csv')), index=False)
                # Compute LAI
                lai_path = os.path.normpath(os.path.join(land_dir, "corine_lai.csv"))
                flow_functions.create_LAI(land_corine, terrain, lai_path, NODATA_FLWDR)
                # Convert raster to GeoDataFrame
                gdf = data_functions.raster_vector(land_path, df, catchment_buffer)
                if len(gdf) == 0: return JSONResponse({'status': 'error', 'message': 'No Land Cover data found.'})
                content = json.loads(gdf.to_json())
        elif key == "water-body":
            water_path = os.path.normpath(os.path.join(flow_dir, 'water_area', body.get('waterArea')))
            if not os.path.exists(water_path):
                return JSONResponse({'status': 'error', 'message': 'No water area data found. Please upload water area first.'})
            gdf = gpd.read_file(water_path)
            if gdf.crs != "EPSG:4326": gdf = gdf.to_crs("EPSG:4326")
            content = json.loads(gdf.to_json())
        return JSONResponse({'status': status, 'content': content})
    except Exception as e:
        print('/data_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/check_soil")
async def check_soil(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        projectName, flow_name = body.get('projectName'), body.get('flowName')
        project_name, _ = functions.project_definer(projectName, user)
        flow_dir, content = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", flow_name)), []
        directory = os.path.normpath(os.path.join(flow_dir, "soil"))
        if not os.path.exists(directory): 
            return JSONResponse({'status': 'error', 'message': 'No soil data found. Please download soil data first.'})
        files = [f for f in os.listdir(directory) if f.endswith('.tif') and f != 'soilthickness.tif']
        for file in files:
            soil_type, soil_depth = file.split('.')[0].split('_')
            temp = [
                flow_functions.soil_type_reverse[soil_type],
                flow_functions.soil_depth_reverse[soil_depth]
            ]
            content.append({
                'value': file.removesuffix('.tif'), 'label': (' - ').join(temp)
            })
        content.append({'value': 'soilthickness', 'label': 'soilthickness'})
        if len(content) != 43: 
            return JSONResponse({
                'status': 'error', 'message': 'Not all soil data found. Please check your soil data.'
            })
        return JSONResponse({'status': 'ok', 'content': content})
    except Exception as e:
        print('/check_soil:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/soil_upload")
async def soil_upload(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name, layer = body.get('flowName'), body.get('layerName')
        file_name = f"flows/{flow_name}/soil/{layer}.tif"
        soil_path = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, file_name))
        with rioxarray.open_rasterio(soil_path) as src:
            soil = src.squeeze(drop=True)
            min = int(soil.where(soil != src.rio.nodata).min())
            max = int(soil.where(soil != src.rio.nodata).max())
        with rasterio.open(soil_path) as src:
            west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        bounds = [[south, west], [north, east]]
        tile_url = f"/{project_name}/{file_name}/{{z}}/{{x}}/{{y}}.png"
        contents = {"tile_url": tile_url, "bounds": bounds, "min_max": [min, max]}
        return JSONResponse({'status': 'ok', 'content': contents})
    except Exception as e:
        print('/soil_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/river_upload")
async def river_upload(file: UploadFile = File(...), key: str = Form(...), threshold: float = Form(...)):
    river_path = None
    try:
        filename = file.filename or ""
        ext = os.path.splitext(filename)[1].lower()
        if key == "river-raster" and ext != ".tif":
            return JSONResponse({'status': 'error', 'message': 'Raster data must be in *.tif format.'})
        if key == "river-vector" and ext != ".geojson":
            return JSONResponse({'status': 'error', 'message': 'Vector data must be in *.geojson format.'})
        if key not in ("river-raster", "river-vector"):
            return JSONResponse({"status": "error", "message": "Invalid river data type."})
        if ext == ".tif":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tif") as temp_file:
                temp_file.write(file.file.read())
                river_path = temp_file.name
            with rasterio.open(river_path) as src:
                dem_array = src.read(1).astype(np.float32)
                crs, transform = src.crs, src.transform
            filled_array, _ = dem.fill_depressions(elevtn=dem_array, max_depth=-1)
            flw = pyflwdir.from_dem(filled_array, transform=transform, latlon=crs.is_geographic)
            flwacc = flw.accuflux(filled_array)
            mask = (flwacc >= float(threshold)).astype(np.uint8)
            skeleton = skeletonize(mask).astype(np.uint8)
            graph = sknw.build_sknw(skeleton, multi=False) 
            del skeleton, mask, flwacc
            lines = []
            for s, e in graph.edges():
                pts = graph[s][e]['pts']  # Nx2 array: row, col
                # Convert row, col to x, y CRS
                xy_pts = [transform * (c, r) for r, c in pts]
                lines.append(LineString(xy_pts))
            merged = linemerge(unary_union(lines))
            if merged.geom_type == "LineString": lines = [merged]
            else: lines = list(merged.geoms)
            gdf = gpd.GeoDataFrame(geometry=lines, crs=crs)
            gdf = gdf.reindex(columns=['Width', 'Depth', 'geometry'])
            gdf = gdf[gdf.is_valid].reset_index(drop=True)
            # Process river
            gdf["geometry"] = gdf.geometry.apply(lambda g: force_2d(g))
        elif ext == ".geojson":
            gdf = gpd.read_file(file.file)
            columns = {col.lower(): col for col in gdf.columns}
            if 'width' not in columns or 'depth' not in columns:
                return JSONResponse({'status': 'error', 'message': 'River data must have "Width" and "Depth" columns.'})
            width_col, depth_col = columns['width'], columns['depth']
            gdf = gdf.rename(columns={width_col: 'Width', depth_col: 'Depth'})
            gdf = gdf[['Width', 'Depth', 'geometry']]
        # functions.safe_remove(river_path)
        if gdf.empty: 
            message = "No river is detected.\nPlease check the input vector."
            return JSONResponse({'status': 'error', 'message': message})
        if 'description' not in gdf.columns: gdf.insert(0, 'description', range(1, len(gdf) + 1))
        if gdf.crs != "EPSG:4326": gdf = gdf.to_crs("EPSG:4326")
        return JSONResponse({'status': 'ok', 'content': json.loads(gdf.to_json())})
    except Exception as e:
        print('/river_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})
    finally:
        if river_path and os.path.isfile(river_path):
            try: functions.safe_remove(river_path)
            except OSError: traceback.print_exc()
        await file.close()

@router.post("/polygon_clip")
async def polygon_clip(request: Request):
    try:
        body = await request.json()
        base_layer, clip_layer = body.get('baseLayer'), body.get('clipLayer')
        base_layer = gpd.GeoDataFrame.from_features(base_layer, crs="EPSG:4326")
        clip_layer = gpd.GeoDataFrame.from_features(clip_layer, crs="EPSG:4326")
        get_area = body.get('getArea')
        # Clip the base layer to the clip layer
        if get_area == 'inside': clipped_layer = gpd.clip(base_layer, clip_layer)
        elif get_area == 'outside': clipped_layer = base_layer.overlay(clip_layer, how='difference')
        if clipped_layer.empty: return JSONResponse({'status': 'error', 'message': 'No data found.'})
        clip_layer = clip_layer.explode(index_parts=False)
        clipped_layer = clipped_layer[clipped_layer.geometry.geom_type == 'LineString']
        clipped_layer = clipped_layer.reset_index(drop=True)
        clipped_layer['description'] = clipped_layer.index + 1
        return JSONResponse({'status': 'ok', 'content': json.loads(clipped_layer.to_json())})
    except Exception as e:
        print('/polygon_clip:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/river_saver")
async def river_saver(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name, data = body.get('flowName'), body.get('data')
        flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", flow_name))
        river_dir = os.path.normpath(os.path.join(flow_dir, 'river'))
        os.makedirs(river_dir, exist_ok=True)
        gdf = gpd.GeoDataFrame.from_features(data['features'], crs="EPSG:4326")
        gdf = gdf.drop(columns=['description'])
        # Write file
        river_gpkg = os.path.normpath(os.path.join(river_dir, 'river.gpkg'))
        result_new = gdf.rename(columns={'Width': 'rivwth', 'Depth': 'rivdph'})
        # Convert to dtm crs
        terrain_path = os.path.normpath(os.path.join(flow_dir, 'raw', 'dtm_raw.tif'))
        if not os.path.exists(terrain_path):
            return JSONResponse({'status': 'error', 'message': "Cannot find terrain data. Please process terrain first."})
        with rioxarray.open_rasterio(terrain_path) as src:
            terrain = src.squeeze(drop=True).load()
        result_new = result_new.to_crs(terrain.rio.crs)
        result_new.to_file(river_gpkg, driver='GPKG')
        df = pd.read_csv(os.path.normpath(os.path.join(SOURCE_BACKEND, 'flow_samples', 'river_manning_mapping.csv')))
        df.to_csv(os.path.normpath(os.path.join(river_dir, 'river_manning.csv')), index=False)
        return JSONResponse({'status': 'ok', 'message': 'River data saved successfully.'})
    except Exception as e:
        print('/river_saver:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/save_flow_weather")
async def save_flow_weather(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name, data = body.get('flowName'), dict(body.get('data'))
        flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", flow_name))
        forcing_dir = os.path.normpath(os.path.join(flow_dir, 'forcing'))
        time_zone, interval = body.get('timeZone'), body.get('interval')
        redis, start, end = request.app.state.redis, body.get('start'), body.get('end')
        raw_path = os.path.normpath(os.path.join(flow_dir, 'raw', 'dtm_raw.tif'))
        if not os.path.exists(raw_path):
            return JSONResponse({'status': 'error', 'message': "Cannot find terrain data. Please process terrain first."})
        if os.path.exists(forcing_dir): functions.safe_remove(forcing_dir)
        os.makedirs(forcing_dir, exist_ok=True)
        forcing = {'start': start, 'end': end, 'interval': interval}
        forcing_path = os.path.join(forcing_dir, 'forcing.json')
        with open(forcing_path, 'w') as f:
            json.dump(forcing, f)
        df = pd.DataFrame.from_records(data['rows'], columns=data['columns'])
        df['Time'] = functions.local_to_utc(df['Time'], time_zone)
        df = df.set_index('Time')
        required_columns = [
            "Precipitation (mm)", "Temperature (°C)", "Shortwave Radiation (W/m²)",
            "Longwave Radiation (W/m²)", "Wind Speed (m/s)", "Pressure (Pa)",
        ]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return JSONResponse({"status": "error", "message": f"Missing weather columns: {', '.join(missing_columns)}"})
        lock = redis.lock(f"{project_name}:save-weather", timeout=120, blocking_timeout=300)
        async with lock:
            renew_task = asyncio.create_task(data_functions.renew_redis_lock(lock, ttl=120, interval=30))
            try:
                await asyncio.to_thread(data_functions.write_forcing, raw_path, forcing_dir, df, interval)
                if renew_task.done() and not renew_task.result():
                    return JSONResponse({'status': 'error', 'message': 'Failed to renew redis lock.'})
            finally:
                renew_task.cancel()
                with suppress(asyncio.CancelledError): await renew_task
            return JSONResponse({'status': 'ok', 'message': 'Weather data saved successfully.'})
    except Exception as e:
        print('/save_flow_weather:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})



# @router.post("/delete_river")
# async def delete_river(request: Request):
#     try:
#         body = await request.json()
#         length = float(body.get('length'))
#         data = gpd.GeoDataFrame.from_features(body.get('river')['features'], crs="EPSG:4326")
#         data_UTM = data.copy().to_crs(data.estimate_utm_crs())
#         data_UTM['length'] = data_UTM['geometry'].length
#         data_UTM = data_UTM[data_UTM['length'] >= length]
#         data_UTM = data_UTM.drop(columns=['length'])
#         data_UTM = data_UTM.to_crs("EPSG:4326")
#         n = len(data) - len(data_UTM)
#         content = json.loads(data_UTM.to_json())
#         return JSONResponse({'status': 'ok', 'content': content, 'numDeleted': n})
#     except Exception as e:
#         print('/delete_river:\n==============')
#         traceback.print_exc()
#         return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

# @router.post("/check_stream_points")
# async def check_stream_points(request: Request, user=Depends(functions.basic_auth)):
#     try:
#         body = await request.json()
#         project_name, project_id = functions.project_definer(body.get('projectName'), user)
#         flow_dir = os.path.normpath(os.path.join(PROJECT_ROOT, project_name, "flows", body.get('flowName')))
#         redis, lat, lon = request.app.state.redis, float(body.get('lat')), float(body.get('lon'))
#         lock = redis.lock(f"{project_id}:wflow_stream-point", timeout=1000, blocking_timeout=10)
#         async with lock:
#             strord_path = os.path.normpath(os.path.join(flow_dir, 'hydro', "strord.tif"))
#             with rasterio.open(strord_path) as strord_src:
#                 src_crs = strord_src.crs
#             gdf = gpd.GeoDataFrame(geometry=gpd.points_from_xy([lon], [lat]), crs='EPSG:4326')
#             gdf = gdf.to_crs(src_crs)
#             center_xy = [gdf.geometry.x[0], gdf.geometry.y[0]]
#             candidates = flow_functions.get_candidates_from_strord(strord_path, center_xy)
#             if len(candidates) == 0:
#                 return JSONResponse({'status': 'error', 'message': "No candidate found."})
#             candidates = candidates.to_crs('EPSG:4326')
#             candidates['lat'], candidates['lon'] = candidates.geometry.y, candidates.geometry.x
#             candidates['id'] = candidates['id']
#             candidates = candidates[['id', 'lat', 'lon', 'distance_m']].values.tolist()
#             selected = int(0.2*len(candidates))
#             content = {'points': len(candidates), 'data': candidates, 'selected': selected}
#             return JSONResponse({"content": content})
#     except Exception as e:
#         print('/check_stream_points:\n==============')
#         traceback.print_exc()
#         return JSONResponse({'status': 'error', 'message': f"Error: {e}"})
