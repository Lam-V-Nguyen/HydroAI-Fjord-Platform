import os, json, traceback, mercantile, rasterio, shutil, matplotlib
import io, sknw, shapely, rioxarray, zipfile, pyflwdir, threading
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, Response, Query
from fastapi.responses import JSONResponse
import geopandas as gpd, numpy as np, pandas as pd, xarray as xr
from config import PROJECT_ROOT, WHITEBOX_DIR, SOURCE_BACKEND
from dotenv import load_dotenv
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
from rasterio.features import shapes
from rasterio.transform import rowcol
from shapely.geometry import shape, LineString
from shapely.ops import unary_union, linemerge
from shapely import force_2d
from PIL import Image
from pyflwdir import dem
from skimage.morphology import skeletonize
from services import functions, flow_functions, hyd_functions
from whitebox.whitebox_tools import WhiteboxTools
from rasterio.io import MemoryFile
from pathlib import Path

load_dotenv()
wtb = WhiteboxTools()
wtb.set_verbose_mode(False)
wtb.set_whitebox_dir(WHITEBOX_DIR)

router, processes, process_lock = APIRouter(), {}, threading.Lock()


@router.post("/flow_project")
async def flow_project(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    try:
        flow_name, key = body.get('flowName'), body.get('key')
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows")
        os.makedirs(flow_dir, exist_ok=True)
        dir, content = os.path.join(flow_dir, flow_name), {}
        if key == 'create':
            if not os.path.exists(dir):
                os.makedirs(dir, exist_ok=True)
                return JSONResponse({'status': 'create', 'message': f"Project '{flow_name}' created successfully."})
            water_dir = os.path.join(dir, 'water_area')
            file_water = [f for f in os.listdir(water_dir) if f.endswith(".geojson")]
            content['water'] = file_water[0] if len(file_water) > 0 else ''
            files = [f for f in os.listdir(dir) if f.endswith("_filled.tif")]
            dtm_file = files[0].replace("_filled", "") if len(files) > 0 else ''
            dtm_path = os.path.join(dir, dtm_file)
            content['dtm'] = dtm_file if os.path.exists(dtm_path) else ''
        elif key == 'open':
            forcing_path = os.path.join(dir, 'forcing', 'weather_forcing.nc')
            if not os.path.exists(forcing_path):
                return JSONResponse({'status': 'error', 'message': f"Forcing file not found."})
            with xr.open_dataset(forcing_path) as forcing:
                start, end = forcing.time.values[0], forcing.time.values[-1]
            dt_start = pd.Timedelta(start).tz_localize('UTC')
            dt_end = pd.Timedelta(end).tz_localize('UTC')
            content['start'] = dt_start.strftime('%Y-%m-%d %H:%M:%S')
            content['end'] = dt_end.strftime('%Y-%m-%d %H:%M:%S')
        return JSONResponse({'content': content})
    except Exception as e:
        print('/flow_project:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/water_upload")
async def water_upload(file: UploadFile = File(...), flowName: str = Form(...),
    projectName: str = Form(...), user=Depends(functions.basic_auth)):
    try:
        project_name, _ = functions.project_definer(projectName, user)
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows")
        if not os.path.exists(flow_dir): os.makedirs(flow_dir, exist_ok=True)
        water_dir = os.path.join(flow_dir, flowName, "water_area")
        if os.path.exists(water_dir): shutil.rmtree(water_dir)
        os.makedirs(water_dir, exist_ok=True)
        water_path = os.path.join(water_dir, file.filename)
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

@router.get("/{name:path}/terrain/{key}/{folder}/{filename}/{z}/{x}/{y}.png")
def terrain_tiles(name: str, key: str, folder: str, filename: str, z: int, x: int, y: int):
    try:
        project = name
        tif_folder = os.path.join(PROJECT_ROOT, project, 'flows', folder)
        tif_path = os.path.join(tif_folder, filename)
        # Get min and max
        meta_path = tif_path.replace("_cog.tif", ".json").replace("_streams.tif", ".json")
        if key == "soil":
            tif_path = os.path.join(tif_folder, key, filename)         
            meta_path = os.path.join(tif_folder, key, 'soil.json')
        if not os.path.exists(tif_path):
            return JSONResponse({"status": 'error', "message": f"File not found: {tif_path}"})
        with open(meta_path) as f:
            meta = json.load(f)
        global_min, global_max = float(meta[key].get("min", 0)), float(meta[key].get("max", 0))
        bounds = mercantile.xy_bounds(x, y, z)
        dst_transform = rasterio.transform.from_bounds(
            bounds.left, bounds.bottom, bounds.right, bounds.top, 256, 256
        )
        dst = np.full((256, 256), np.nan, dtype=np.float32)
        with rasterio.open(tif_path) as src:
            reproject( source=rasterio.band(src, 1), destination=dst,
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=dst_transform, dst_crs="EPSG:3857",
                resampling=Resampling.bilinear, dst_nodata=np.nan
            )
        if np.all(np.isnan(dst)): return Response(status_code=204)
        valid_mask = ~np.isnan(dst)
        norm = np.zeros_like(dst)
        if global_max > global_min:
            norm[valid_mask] = (dst[valid_mask] - global_min) / (global_max - global_min)
        else: norm[:] = 0
        norm = np.clip(norm, 0, 1)
        # rgba_map = cm.get_cmap("terrain")(norm)
        rgba_map = matplotlib.colormaps['terrain'](norm)
        rgb = (rgba_map[:, :, :3] * 255).astype(np.uint8)
        alpha = (valid_mask * 255).astype(np.uint8)
        rgba = np.dstack([rgb, alpha])
        img, buf = Image.fromarray(rgba, mode="RGBA"), io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception as e:
        print('/terrain_tiles:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/terrain_upload")
async def terrain_upload(file: UploadFile = File(...), flowName: str = Form(...),
    projectName: str = Form(...), user=Depends(functions.basic_auth)):
    try:
        project_name, _ = functions.project_definer(projectName, user)
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flowName)
        os.makedirs(flow_dir, exist_ok=True)
        terrain_path = os.path.join(flow_dir, file.filename)
        with open(terrain_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file.file.close()
        # Convert to COG
        dst_crs, cog_path = "EPSG:3857", os.path.splitext(terrain_path)[0] + "_cog.tif"
        with rasterio.open(terrain_path) as src:
            if src.crs is None:
                return JSONResponse({'status': 'error', 'message': "TIF file has no CRS"})
            transform, width, height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds
            )
            profile = src.profile.copy()
            profile.update({"crs": dst_crs, "transform": transform, "width": width,
                "height": height, "driver": "COG", "compress": "LZW", "tiled": True,
                "blockxsize": 256, "blockysize": 256
            })
            with rasterio.open(cog_path, "w", **profile) as dst:
                reproject(
                    source=rasterio.band(src, 1), destination=rasterio.band(dst, 1),
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=transform, dst_crs=dst_crs,
                    resampling=Resampling.bilinear
                )
        # Get min and max
        with rasterio.open(cog_path) as src:
            data = src.read(1, masked=True)
            global_min, global_max = float(data.min()), float(data.max())
        del data
        meta_path, meta = os.path.splitext(terrain_path)[0] + ".json", {}
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f: meta = json.load(f)
        meta['raw'] = {"min": global_min, "max": global_max}
        with open(meta_path, "w") as f: json.dump(meta, f)
        tile_url = f"/{project_name}/terrain/raw/{flowName}/{os.path.basename(cog_path)}/{{z}}/{{x}}/{{y}}.png"
        contents = {"tile_url": tile_url, "min": global_min, "max": global_max}
        return JSONResponse({'status': 'ok', 'content': contents})
    except Exception as e:
        print('/terrain_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/stream_upload")
async def stream_upload(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        file_name, threshold = body.get('filename'), body.get('threshold')
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        folder, key, flow_name = file_name.rstrip(".tif"), "streams", body.get('flowName')
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flow_name)
        dtm_path = os.path.join(flow_dir, file_name)
        fill_name, stream_name = folder + "_filled.tif", folder + "_streams.tif"
        flwdir_name, flwacc_name = folder + "_flowdir.tif", folder + "_flowacc.tif"
        fill_path = os.path.join(flow_dir, fill_name)
        if os.path.exists(fill_path): functions.safe_remove(fill_path)
        wtb.fill_depressions(dem=dtm_path, output=fill_path)
        flw_path = os.path.join(flow_dir, flwdir_name)
        if os.path.exists(flw_path): functions.safe_remove(flw_path)
        wtb.d8_pointer(dem=fill_path, output=flw_path)
        flwacc_path = os.path.join(flow_dir, flwacc_name)
        if os.path.exists(flwacc_path): functions.safe_remove(flwacc_path)
        wtb.d8_flow_accumulation(i=fill_path, output=flwacc_path, out_type="cells")
        stream_path = os.path.join(flow_dir, stream_name)
        if os.path.exists(stream_path): functions.safe_remove(stream_path)
        wtb.extract_streams(flow_accum=flwacc_path, output=stream_path, threshold=threshold)
        meta_path, meta = dtm_path.replace(".tif", ".json"), {}
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f: meta = json.load(f)
        meta[key] = {"min": 0, "max": 1}
        with open(meta_path, "w") as f: json.dump(meta, f)
        tile_url = f"/{project_name}/terrain/{key}/{flow_name}/{stream_name}/{{z}}/{{x}}/{{y}}.png"
        contents = {"tile_url": tile_url, "min": 0, "max": 1}
        return JSONResponse({'status': 'ok', 'content': contents})
    except Exception as e:
        print('/stream_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/data_upload")
async def data_upload(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        key = body.get('key')
        if key == "soil":
            content, soil_type, soil_depth = [], flow_functions.soils[0], flow_functions.soils[1]
            for soil in soil_type:
                for depth in soil_depth:
                    content.append([soil, depth, 'cm'])
            if len(content) == 0: return JSONResponse({'status': 'error', 'message': 'No data found.'})
            return JSONResponse({'status': 'ok', 'content': content})
        elif key == "land":
            project_name, _ = functions.project_definer(body.get('projectName'), user)
            flow_name, data = body.get('flowName'), body.get('data')
            flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flow_name)
            raw_path = os.path.join(flow_dir, 'raw', 'dtm_raw.tif')
            if not os.path.exists(raw_path): 
                return JSONResponse({'status': 'error', 'message': "Cannot find DTM data. Please upload DTM data first."})
            terrain_da = rioxarray.open_rasterio(raw_path).squeeze()
            with rasterio.open(raw_path) as src:
                nodata, profile, dem_array = src.nodata, src.profile, src.read(1)
            profile_writer, NODATA_FLWDR = profile.copy(), 255
            mask_nan = np.isnan(dem_array) | (dem_array == nodata)
            catchment_WGS84 = gpd.GeoDataFrame.from_features(data['features'], crs="EPSG:4326")
            catchment_buffer = catchment_WGS84.buffer(0.001)
            # Create land cover nc file
            land_dir = os.path.join(flow_dir, 'landcover')
            if not os.path.exists(land_dir): os.makedirs(land_dir)
            # Land cover data from CORINE 2018
            corine_path = os.path.join(SOURCE_BACKEND, 'flow_samples', 'landcover', 'U2018_CLC2018_V2020_20u1.zip')
            with zipfile.ZipFile(corine_path, "r") as zip_ref:
                name = os.path.basename(corine_path).replace(".zip", ".tif")
                with zip_ref.open(name) as f:
                    with MemoryFile(f.read()) as memfile:
                        corine = rioxarray.open_rasterio(memfile).squeeze()
                        corine_match = corine.rio.reproject_match(terrain_da, resampling=Resampling.nearest)
            land_corine = corine_match.values.astype(np.uint8)
            land_corine[mask_nan] = NODATA_FLWDR
            land_path = os.path.join(land_dir, 'corine.tif')
            profile_writer.update(dtype=np.uint8)
            flow_functions.write_geotif(land_corine, profile_writer, land_path, NODATA_FLWDR)
            # Save look up table
            df = pd.read_csv(os.path.join(SOURCE_BACKEND, 'flow_samples', 'landcover', 'corine_mapping.csv'))
            mask_csv = df['corine'] != 999
            df.loc[~mask_csv, 'corine'], df.loc[~mask_csv, 'landuse'] = 48, -999.0
            df.loc[mask_csv, 'corine'] = np.arange(1, len(df.loc[mask_csv, 'corine']) + 1).astype(np.uint8)
            df.to_csv(os.path.join(land_dir, 'corine.csv'), index=False)
            # Compute LAI
            lai_path = os.path.join(land_dir, "corine_lai.csv")
            flow_functions.create_LAI(land_corine, terrain_da, lai_path, NODATA_FLWDR)
            # Convert raster to GeoDataFrame
            land = rioxarray.open_rasterio(land_path).squeeze()
            data, transform = land.values, land.rio.transform()
            results = (
                {'geometry': geom, 'properties': {'value': value}}
                for geom, value in shapes(data, transform=transform)
            )
            gdf = gpd.GeoDataFrame.from_features(list(results))
            if len(gdf) == 0: return JSONResponse({'status': 'error', 'message': 'No Land Cover data found.'})
            gdf.set_crs(land.rio.crs, inplace=True)
            gdf['value'] = gdf['value'].astype(int)
            # Remove nodata
            gdf = gdf[~gdf.value.isin([land.rio.nodata])].reset_index(drop=True)
            # Assign values to landcover
            gdf = gdf.merge(df, left_on='value', right_on='corine', how='left')
            gdf = gdf.rename(columns={'value': 'id'})
            if gdf.crs != "EPSG:4326": gdf = gdf.to_crs("EPSG:4326")
            # Clip to catchment
            gdf = gpd.clip(gdf, catchment_buffer)
            return JSONResponse({'status': 'ok', 'content': json.loads(gdf.to_json())})
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
        flow_dir, content = os.path.join(PROJECT_ROOT, project_name, "flows", flow_name), []
        dir = os.path.join(flow_dir, "soil")
        if not os.path.exists(dir): return JSONResponse({'status': 'error', 'message': 'No soil data found'})
        files = [f for f in os.listdir(dir) if f.endswith('.tif') and f != 'soilthickness.tif']
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

# Download soil
@router.post("/start_download_soil")
async def start_download_soil(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, project_id = functions.project_definer(body.get('projectName'), user)
    flow_name, data, water_area = body.get('flowName'), body.get('data'), body.get('waterArea')
    terrain_path = os.path.join(PROJECT_ROOT, project_name, "flows", flow_name, 'raw', 'dtm_raw.tif')
    if not os.path.exists(terrain_path):
        return JSONResponse({'status': 'error', 'message': "Cannot find terrain data. Process terrain data in the tab 'Topography' first."})
    redis = request.app.state.redis
    lock = redis.lock(f"{project_id}:soil", timeout=1000, blocking_timeout=10)
    async with lock:
        # Check if simulation already running
        if project_name in processes and processes[project_name]["status"] == "running":
            return JSONResponse({"status": "running", "message": 'Data downloading in progress.'})
        catchment_WGS84 = gpd.GeoDataFrame.from_features(data['features'], crs="EPSG:4326")
        processes[project_name] = {"status": "running", "message": "Preparing download..."}
        threading.Thread(
            target=flow_functions.soil_downloader, 
            args=(project_name, processes, flow_name, catchment_WGS84, water_area, terrain_path), daemon=True
        ).start()
    return JSONResponse({'status': 'ok', 'message': "Soil downloading started"})

@router.post("/soil_upload")
async def soil_upload(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        key, flow_name, layer = "soil", body.get('flowName'), body.get('layerName')
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flow_name, key)
        file_name, json_name = layer + ".tif", 'soil.json'
        soil_path = os.path.join(flow_dir, file_name)
        soil = rioxarray.open_rasterio(soil_path).squeeze()
        min = int(soil.where(soil != soil.rio.nodata).min().item())
        max = int(soil.max().values)
        meta_path, meta = os.path.join(flow_dir, json_name), {}
        meta[key] = {"min": min, "max": max}
        with open(meta_path, "w") as f: json.dump(meta, f)
        tile_url = f"/{project_name}/terrain/{key}/{flow_name}/{file_name}/{{z}}/{{x}}/{{y}}.png"
        contents = {"tile_url": tile_url, "min": min, "max": max}
        return JSONResponse({'status': 'ok', 'content': contents})
    except Exception as e:
        print('/soil_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/geojson_upload")
async def geojson_upload(file: UploadFile = File(...), projectName: str = Form(...),
    flowName: str = Form(...), user=Depends(functions.basic_auth)):
    try:
        catchment = gpd.read_file(file.file)
        if catchment.empty: return JSONResponse({'status': 'error', 'message': 'No data found.'})
        if not projectName or not flowName:
            return JSONResponse({'status': 'error', 'message': 'Project name and flow name are required.'})
        project_name, _ = functions.project_definer(projectName, user)
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flowName)
        raw_dir = os.path.join(flow_dir, 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        raw_path = os.path.join(raw_dir, 'dtm_raw.tif')
        if not os.path.exists(raw_path):
            files = [f for f in os.listdir(flow_dir) if f.endswith("_filled.tif")]
            if len(files) == 0:
                return JSONResponse({'status': 'error', 'message': "Cannot find terrain data. Please upload terrain data in the tab 'Topography'."})
            terrain_path = os.path.join(flow_dir, f'{files[0].replace("_filled", "")}')
            terrain = rioxarray.open_rasterio(terrain_path).squeeze()
            catchment_reprojected = catchment.to_crs(terrain.rio.crs)
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
            flow_functions.write_geotif(terrain_values, profile, raw_path, nodata)
        if catchment.crs != "EPSG:4326": catchment = catchment.to_crs("EPSG:4326")
        return JSONResponse({'status': 'ok', 'content': json.loads(catchment.to_json())})
    except Exception as e:
        print('/geojson_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/catchment")
async def catchment(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        file_name, lat, lon = body.get('filename'), body.get('lat'), body.get('lon')
        snap_distance, folder = float(body.get('snapDistance')), file_name.rstrip(".tif")
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", body.get('flowName'))
        os.makedirs(flow_dir, exist_ok=True)
        flw_path = os.path.join(flow_dir, f"{folder}_flowdir.tif")
        stream_path = os.path.join(flow_dir, f"{folder}_streams.tif")
        with rasterio.open(stream_path) as src:
            crs = src.crs
        # Create outlet point for catchment
        outlet_dir = os.path.join(flow_dir, "outlet")
        if not os.path.exists(outlet_dir): os.makedirs(outlet_dir, exist_ok=True)
        outlet_path = os.path.join(outlet_dir, "outlet.shp")
        if os.path.exists(outlet_path): functions.safe_remove(outlet_path)
        outlet = gpd.GeoDataFrame(geometry=[shapely.geometry.Point(lon, lat)], crs="EPSG:4326")
        outlet = outlet.to_crs(crs)
        outlet.to_file(outlet_path)
        # Create pour point
        snap_path = os.path.join(outlet_dir, "snapped.shp")
        if os.path.exists(snap_path): functions.safe_remove(snap_path)
        catchment_path = os.path.join(flow_dir, "catchment.tif")
        if os.path.exists(catchment_path): functions.safe_remove(catchment_path)
        wtb.jenson_snap_pour_points(pour_pts=outlet_path, streams=stream_path, output=snap_path, snap_dist=snap_distance)
        wtb.watershed(d8_pntr=flw_path, pour_pts=snap_path, output=catchment_path)
        with rasterio.open(catchment_path) as src:
            data = src.read(1).astype("uint8")
            transform = src.transform
        results = [shape(geom) for geom, val in shapes(data, transform=transform) if val == 1]
        geom = flow_functions.remove_holes(unary_union(results))
        catchment = gpd.GeoDataFrame(geometry=[geom], crs=crs)
        catchment.to_file(os.path.join(outlet_dir, "catchment.geojson"), driver="GeoJSON")
        # Delete temporary files
        functions.safe_remove(catchment_path)
        if catchment.empty: return JSONResponse({'status': 'error', 'message': 'No catchment found.'})
        if catchment.crs != "EPSG:4326": catchment = catchment.to_crs("EPSG:4326")
        return JSONResponse({'status': 'ok', 'content': json.loads(catchment.to_json())})
    except Exception as e:
        print('/catchment:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

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
        clipped_layer = clipped_layer.reset_index(drop=True)
        clipped_layer['description'] = clipped_layer.index + 1
        return JSONResponse({'status': 'ok', 'content': json.loads(clipped_layer.to_json())})
    except Exception as e:
        print('/polygon_clip:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/river_upload")
async def river_upload(file: UploadFile = File(...), projectName: str = Form(...),
    key: str = Form(...), threshold: float = Form(...), 
    flowName: str = Form(...), user=Depends(functions.basic_auth)):
    try:
        project_name, _ = functions.project_definer(projectName, user)
        river_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flowName, 'river')
        os.makedirs(river_dir, exist_ok=True)
        file_ext = file.filename.split(".")
        ext = file_ext[-1].lower()
        if key == "river-raster" and not ext in ["tif"]:
            return JSONResponse({'status': 'error', 'message': 'Flow accumulation data must be in *.tif format.'})
        if key == "river-vector" and not ext in ["geojson"]:
            return JSONResponse({'status': 'error', 'message': 'Vector data must be in *.geojson format.'})
        river_path = os.path.join(river_dir, file.filename)
        with open(river_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        if file_ext[-1].lower() in ["tif"]:
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
            gdf = gpd.GeoDataFrame(geometry=lines, crs=src.crs)
            gdf = gdf.reindex(columns=['Width', 'Depth', 'geometry'])
            gdf = gdf[gdf.is_valid].reset_index(drop=True)
            # Process river
            gdf["geometry"] = gdf.geometry.apply(lambda g: force_2d(g))
        elif file_ext[-1].lower() in ["geojson"]: 
            gdf = gpd.read_file(river_path)
            columns = {col.lower(): col for col in gdf.columns}
            if 'width' not in columns or 'depth' not in columns:
                return JSONResponse({'status': 'error', 'message': 'River data must have "Width" and "Depth" columns.'})
            width_col, depth_col = columns['width'], columns['depth']
            gdf = gdf.rename(columns={width_col: 'Width', depth_col: 'Depth'})
            gdf = gdf[['Width', 'Depth', 'geometry']]
        functions.safe_remove(river_path)
        if gdf.empty: 
            message = "No river is detected.\nPlease check the input raster."
            return JSONResponse({'status': 'error', 'message': message})
        if 'description' not in gdf.columns: gdf.insert(0, 'description', range(1, len(gdf) + 1))
        if gdf.crs != "EPSG:4326": gdf = gdf.to_crs("EPSG:4326")
        return JSONResponse({'status': 'ok', 'content': json.loads(gdf.to_json())})
    except Exception as e:
        print('/river_upload:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/river_saver")
async def river_saver(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name, data = body.get('flowName'), body.get('data')
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flow_name)
        id_selected, river_dir = body.get('segments'), os.path.join(flow_dir, 'river')
        if not os.path.exists(river_dir): os.makedirs(river_dir)
        gdf = gpd.GeoDataFrame.from_features(data['features'], crs="EPSG:4326")
        result = gdf[gdf['description'].isin(id_selected)]
        result = result.drop(columns=['description'])
        # Write file
        river_gpkg = os.path.join(river_dir, 'river.gpkg')
        result_new = result.rename(columns={'Width': 'rivwth', 'Depth': 'rivdph'})
        # Convert to dtm crs
        tif_files = list(Path(flow_dir).glob("*.tif"))
        derived_suffixes = {"_cog", "_filled", "_flowacc", "_flowdir", "_streams"}
        candidates = [
            f for f in tif_files
            if not any(f.stem.endswith(suffix) for suffix in derived_suffixes)
        ]
        if len(candidates) != 1:
            return JSONResponse({
                'status': 'error', 'message': "Cannot file terrain data. Please process terrain first."
            })
        terrain_path = os.path.join(flow_dir, candidates[0])
        terrain = rioxarray.open_rasterio(terrain_path).squeeze()
        result_new = result_new.to_crs(terrain.rio.crs)
        result_new.to_file(river_gpkg, driver='GPKG')
        df = pd.read_csv(os.path.join(SOURCE_BACKEND, 'flow_samples', 'river_manning_mapping.csv'))
        df.to_csv(os.path.join(river_dir, 'river_manning.csv'), index=False)
        return JSONResponse({'status': 'ok', 'message': 'River data saved successfully.'})
    except Exception as e:
        print('/river_saver:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/delete_river")
async def delete_river(request: Request):
    try:
        body = await request.json()
        length = float(body.get('length'))
        data = gpd.GeoDataFrame.from_features(body.get('river')['features'], crs="EPSG:4326")
        data_UTM = data.copy().to_crs(data.estimate_utm_crs())
        data_UTM['length'] = data_UTM['geometry'].length
        data_UTM = data_UTM[data_UTM['length'] >= length]
        data_UTM = data_UTM.drop(columns=['length'])
        data_UTM = data_UTM.to_crs("EPSG:4326")
        n = len(data) - len(data_UTM)
        content = json.loads(data_UTM.to_json())
        return JSONResponse({'status': 'ok', 'content': content, 'numDeleted': n})
    except Exception as e:
        print('/delete_river:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

# Check if download is running
@router.post("/check_download_status")
async def check_download_status(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, _ = functions.project_definer(body.get('projectName'), user)
    info = processes.get(project_name)
    if info is None:
        return JSONResponse({"status": "idle", "message": "No download running."})
    status, message = info["status"], info.get("message", "")
    if status in ("finished", "failed", "error"): processes.pop(project_name, None)
    return JSONResponse({"status": status, "message": message})

@router.get("/log_tail_download/{project_name}")
async def log_tail_download(project_name: str, offset: int = Query(0),
    log_file: str = Query(""), user=Depends(functions.basic_auth)):
    project_name, _ = functions.project_definer(project_name, user)
    log_path, lines = os.path.join(PROJECT_ROOT, project_name, log_file), []
    log_path = os.path.normpath(log_path)
    if not os.path.exists(log_path): return {"lines": lines, "offset": 0, "reset": False}
    file_size = os.path.getsize(log_path)
    reset = offset > file_size
    if reset: offset = 0
    with open(log_path, "r", encoding=functions.encoding_detect(log_path), errors="replace") as f:
        f.seek(offset)
        data = f.read()
        new_offset = f.tell()
    return {"lines": data.splitlines(), "offset": new_offset, "reset": reset}




# Download weather
@router.post("/start_download_weather")
async def start_download_weather(request: Request, user=Depends(functions.basic_auth)):
    body = await request.json()
    project_name, project_id = functions.project_definer(body.get('projectName'), user)
    redis, flow_name, data = request.app.state.redis, body.get('flowName'), body.get('data')
    lock = redis.lock(f"{project_id}:weather", timeout=1000, blocking_timeout=10)
    async with lock:
        # Check if process already running
        if project_name in processes and processes[project_name]["status"] == "running":
            return JSONResponse({"status": "running", "message": 'Data downloading in progress.'})
        catchment_WGS84 = gpd.GeoDataFrame.from_features(data['features'], crs="EPSG:4326")
        start, end = body.get('start'), body.get('end')
        processes[project_name] = {"status": "running", "message": "Preparing download..."}
        threading.Thread(
            target=flow_functions.weather_downloader, 
            args=(project_name, processes, flow_name, start, end, catchment_WGS84), daemon=True
        ).start()
    return JSONResponse({"status": "ok", "message": "Weather downloading started"})

@router.post("/save_flow_weather")
async def save_flow_weather(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, _ = functions.project_definer(body.get('projectName'), user)
        flow_name, data = body.get('flowName'), dict(body.get('data'))
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flow_name)
        forcing_dir = os.path.join(flow_dir, 'forcing')
        os.makedirs(forcing_dir, exist_ok=True)
        df = pd.DataFrame.from_records(data['rows'], columns=data['columns'])
        df['Time'] = pd.to_datetime(df['Time'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
        df = df.set_index('Time')
        # # Resample
        # weather_new = weather_new.resample('1H').interpolate(method='time')
        # Create forcing nc file
        time, time_step = df.index.to_numpy(), 'hours'
        out_path, datasets = os.path.join(forcing_dir, "weather_forcing.nc"), {}
        raw_path = os.path.join(flow_dir, 'raw', 'dtm_raw.tif')
        with rasterio.open(raw_path) as src:
            dem_array, crs = src.read(1), src.crs
            transform, nodata = src.transform, src.nodata
        mask_nan = np.isnan(dem_array) | (dem_array == nodata)
        ny, nx = dem_array.shape[0], dem_array.shape[1]
        forcing = {
            'precip': ['Precipitation (mm)', 'mm'], 'temp': ['Temperature (°C)', 'degC'],
            'kin': ['Shortwave Radiation (W/m²)', 'W/m^2'], 'kout': ['Longwave Radiation (W/m²)', 'W/m^2'],
            'wind': ['Wind Speed (m/s)', 'm/s'], 'press_msl': ['Pressure (Pa)', 'Pa']
        }
        for var, (col, unit) in forcing.items():
            data = df[col].values.astype(np.float32)
            data_3d = flow_functions.create_forcing(time, ny, nx, data, mask_nan, True)
            datasets[var] = (('time', 'y', 'x'), data_3d, {'units': unit})
        x_coords = transform.c + (np.arange(nx) + 0.5) * transform.a
        y_coords = transform.f + (np.arange(ny) + 0.5) * transform.e
        ds_final = xr.Dataset(
            data_vars=datasets, coords={"time": time, "y": y_coords, "x": x_coords}
        )
        ds_final = ds_final.rio.set_spatial_dims(x_dim="x", y_dim="y")
        ds_final = ds_final.rio.write_crs(crs)
        ds_final["time"].encoding = {
            "units": f"{time_step} since 1900-01-01 00:00:00",
            "calendar": "proleptic_gregorian", "dtype": "float64"
        }
        encoding = {
            var: {"zlib": True, "complevel": 4, "shuffle": True, "chunksizes": (1, 256, 256)}
            for var in ds_final.data_vars
        }
        ds_final.to_netcdf(out_path, engine='netcdf4', encoding=encoding)
        return JSONResponse({'status': 'ok', 'message': 'Weather data saved successfully.'})
    except Exception as e:
        print('/save_flow_weather:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/wflow_model")
async def wflow_model(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, project_id = functions.project_definer(body.get('projectName'), user)
        key, flow_name = body.get('key'), body.get('flowName')
        flow_dir = os.path.join(PROJECT_ROOT, project_name, "flows", flow_name)
        redis, model_name = request.app.state.redis, 'wflow_model'
        lock = redis.lock(f"{project_id}:wflow_{key}", timeout=1000, blocking_timeout=10)
        async with lock:
            if key == "check":
                if project_name in processes and processes[project_name]["status"] == "running":
                    return JSONResponse({"status": "running", "message": 'Checking inputs for Wflow is in progress.'})
                processes[project_name] = {"status": "running", "message": "Checking inputs for Wflow..."}
                threading.Thread(
                    target=flow_functions.wflow_check, 
                    args=(project_name, processes, flow_name, float(body.get('upArea'))), daemon=True
                ).start()
                outlet_path = os.path.join(flow_dir, "outlet", "outlet.shp")
                if os.path.exists(outlet_path):
                    snapped = gpd.read_file(outlet_path)
                    if snapped.crs != "EPSG:4326": snapped = snapped.to_crs("EPSG:4326")
                    lat, lon = snapped.geometry[0].y, snapped.geometry[0].x
                else: lat, lon = '', ''
                return JSONResponse({"status": "ok", 'content': [lat, lon]})
            elif key == "prepare":
                with process_lock:
                    if project_name in processes and processes[project_name]["status"] == "running":
                        return JSONResponse({"status": "running", "message": 'Preparing Wflow model.'})
                    processes[project_name] = {"status": "running", "message": "Preparing Wflow model..."}
                step, start, end = int(body.get('step')), body.get('start'), body.get('end')
                lib_path = os.path.normpath(os.path.join(SOURCE_BACKEND, 'flow_samples', 'config.yml'))
                des_path = os.path.normpath(os.path.join(flow_dir, 'config.yml'))
                shutil.copy(lib_path, des_path)
                data_lib = [os.path.normpath(des_path)]
                params_input, params_output = body.get('params_input'), body.get('params_output')
                lulc_fn, lulc_mapping, lai_fn = 'corine', 'corine_mapping', 'lai_corine'
                # lulc_function, lulc_mapping_fn, lai_fn = 'esa_worldcover', 'esa_worldcover_mapping', 'lai_esa'
                lat, lon = float(body.get('lat')), float(body.get('lon'))
                terrain_path = os.path.normpath(os.path.join(flow_dir, 'raw', 'dtm_raw.tif'))
                with rasterio.open(terrain_path) as src:
                    transform, crs = src.transform, src.crs
                # Adjust pourpoint to the largest basin
                strord_path = os.path.join(flow_dir, 'hydro', "strord.tif")
                with rasterio.open(strord_path) as strord_src:
                    rows, cols = np.where(strord_src.read(1) == strord_src.read(1).max())
                if len(rows) == 0:
                    status, message = "error", 'No pour point found. Please check your catchment.'
                    processes[project_name] = {"status": status, "message": message}
                    return JSONResponse({"status": status, "message": message})
                gdf = gpd.GeoDataFrame(geometry=gpd.points_from_xy([lon], [lat]), crs='EPSG:4326')
                if gdf.crs != crs: gdf = gdf.to_crs(crs)
                row, col = rowcol(transform, gdf.geometry.x, gdf.geometry.y)
                row, col = row[0], col[0]
                dist2 = (rows - row)**2 + (cols - col)**2
                idx = np.argmin(dist2)
                row_new, col_new, resolution = rows[idx], cols[idx], transform.a
                x, y = rasterio.transform.xy(transform, row_new, col_new)
                soil_layers, region = [50, 100, 150, 300, 400, 600], {'subbasin': [x, y]}
                threading.Thread(
                    target=flow_functions.prepare_hydromt, 
                    args=(
                        project_name, processes, flow_name, model_name, start, end, step, data_lib, region, 
                        resolution, soil_layers, params_input, params_output, lulc_fn, lulc_mapping, lai_fn
                    ), daemon=False).start()
                return JSONResponse({"status": "ok", 'message': 'Preparing Wflow model started.'})
            elif key == "run":
                if project_name in processes and processes[project_name]["status"] == "running":
                    return JSONResponse({"status": "running", "message": 'Running Wflow model.'})
                processes[project_name] = {"status": "running", "message": "Running Wflow model..."}                
                # Check parameters
                nan_vars, path = [], os.path.join(flow_dir, model_name, "static_grid.nc")
                if not os.path.exists(path):
                    status, message = "error", f"Static grid file not found at {path}"
                    processes[project_name] = {"status": status, "message": message}
                    return JSONResponse({"status": status, "message": message})
                with xr.open_dataset(path) as ds:
                    for item in ds.data_vars:
                        if np.unique(ds[item].values).size == 1 and np.isnan(np.unique(ds[item].values)[0]):
                            nan_vars.append(item)                
                if len(nan_vars) > 0:
                    status, message = "error", f"NaN values found in {nan_vars}"
                    processes[project_name] = {"status": status, "message": message}
                    return JSONResponse({"status": status, "message": message})
                threading.Thread(
                    target=flow_functions.run_hydromt, 
                    args=(project_name, processes, flow_dir, model_name), daemon=False
                ).start()
                return JSONResponse({"status": "ok", "message": "Model run started."})
    except Exception as e:
        print('/wflow_model:\n==============')
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': f"Error: {e}"})

@router.post("/start_meteo")
async def start_meteo(request: Request, user=Depends(functions.basic_auth)):
    try:
        body = await request.json()
        project_name, project_id = functions.project_definer(body.get('projectName'), user)
        redis, start, end = request.app.state.redis, body.get('start'), body.get('end')
        lat, lon, key = body.get('lat'), body.get('lon'), body.get('key')
        lock = redis.lock(f"{project_id}:meteo", timeout=1000, blocking_timeout=10)
        async with lock:
            # Check if process already running
            if project_name in processes and processes[project_name]["status"] == "running":
                return JSONResponse({"status": "running", "message": 'Data downloading in progress.'})
            processes[project_name] = {"status": "running", "message": "Preparing download meteo.."}
            if key == 'meteo': target = hyd_functions.meteo_downloader
            elif key == 'wind': target = hyd_functions.wind_downloader
            threading.Thread(
                target=target, args=(project_name, processes, lat, lon, start, end, key), daemon=True
            ).start()
        return JSONResponse({"status": "ok", "message": "Meteo downloading started", 'content': body})
    except Exception as e:
        print('/start_download_meteo:\n==============')
        traceback.print_exc()
        return JSONResponse({"status": 'error', "message": f"Error: {str(e)}"})