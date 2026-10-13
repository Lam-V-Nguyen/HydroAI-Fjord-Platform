import { setupTabs } from "./tabManager.js";
import { getLastTimeZone } from "./constant.js";
import { getUser, signalSender, sendRequest, displayTerrain, drawColorbar, 
    nameChecker, csvUploader, getProjectList, jsonLoader, fillTable, initRequestListener,
    deleteTable, addRowToTable, getDataFromTable, formatDate, updateLog
} from "./commonFunctions.js";
import { geoJSONExporter, mapPlotter, isInvalidNumber, 
    setElementsEnabled, setElementsDisplayed
} from "./flowFunctions.js";
import { projectRender } from "./projectManager.js";
import { initMap } from "./visualizationMap.js";

const hoverTooltip = L.tooltip({
    permanent: false, direction: 'bottom',
    sticky: true, offset: [0, 10], className: 'custom-tooltip'
});

const $ = (id) => document.getElementById(id);
const obj = {
    projectName: $('project-name'), projectList: $('project-list'), projectCreator: $('create-btn'),
    projectDelete: $('delete-btn'), terrainBtn: $('terrain-btn'), terrainInputFile: $('terrain-input-file'), 
    terrainInputText: $('terrain-input-text'), terrainName: $('dem-text'), colorBar: $('custom-colorbar'),
    uploadContainer: $('upload-container'), downloadContainer: $('download-container'), 
    terrainDrawBtn: $('flow-draw-btn'), terrainTopLeft: $('flow-top-left'), terrainBottomRight: $('flow-bottom-right'),
    terrainDownloadBtn: $('flow-terrain-download-btn'), terrainResolution: $('flow-terrain-resolution'),
    streamBtn: $('stream-btn'), threshold: $('threshold'), snapDistance: $('snap-dist'), 
    catchmentRadio: $('catchment-radio'), catchmentCheckbox: $('catchment-checkbox'), 
    catchmentLat: $('catchment-lat'), catchmentLon: $('catchment-lon'), clipCatchmentBtn: $('clip-catchment-btn'), 
    exportCatchmentBtn: $('export-catchment-btn'), waterUploadBtn: $('water-upload-btn'), 
    waterCheckbox: $('water-checkbox'), waterDeleteBtn: $('water-delete-btn'), waterInputText: $('water-input-text'), 
    waterInputFile: $('water-input-file'), catchmentInputFile: $('catchment-input-file'), soilCheckbox: $('soil-checkbox'),
    soilSource: $('soil-source'), soilCheckerBtn: $('check-soil-btn'), soilTable: $('soil-attributes-table'), 
    soilDownload: $('soil-download'), soilLayer: $('soil-layer'), downloadSoilBtn: $('download-soil-btn'), 
    soilLog: $('soil-download-text'), landSource: $('land-source'), landLoaderBtn: $('land-load-btn'), 
    landCheckbox: $('land-checkbox'), riverContainer: $('river-container'), riverUploadBtn: $('river-upload-btn'), 
    riverInputFile: $('river-input-file'), riverThreshold: $('river-threshold'), riverCheckbox: $('river-checker-checkbox'), 
    riverCatchmentUploadBtn: $('lake-catchment-upload-btn'), riverCatchmentClipBtn: $('river-clip-catchment-btn'), 
    riverLakeClipBtn: $('river-clip-lake-btn'), invalidRiverBtn: $('river-invalid-btn'), riverTable: $('river-table'), 
    riverTableContainer: $('river-table-container'), riverIds: $('river-id'),
    

    
    
    
    
    
    
    
    
    
    
    
    
       
       
       
    
     
    
    // 
    // saveRiverProjectBtn: $('river-save-project-btn'), riverDeleteBtn: $('river-delete-btn'), 
    // validRiverTable: $('valid-river-table'), assignRiverBtn: $('river-assign-btn'), saveRiverFileBtn: $('river-save-file-btn'),
    weatherCSVContainer: $('weather-csv-container'), weatherStationContainer: $('weather-station-container'),
    weatherBtn: $('weather-btn'), weatherInputFile: $('weather-input-file'), weatherInputText: $('weather-input-text'), 
    weatherTable: $('weather-table'), weatherStationSelector: $('weather-station'), saveWeatherBtn: $('weather-save-btn'), 
    weatherSourceContainer: $('weather-source-container'), downloadWeatherBtn: $('weather-download-btn'), interval: $('weather-interval'),
    weatherStationStartContainer: $('weather-station-start'), weatherStationEndContainer: $('weather-station-end'), 
    weatherStart: $('weather-start-date'), weatherEnd: $('weather-end-date'), weatherLog: $('weather-download-text'),
    weatherCatchmentContainer: $('weather-catchment-container'), weatherCatchmentBtn: $('weather-catchment-btn'),
    weatherTableContainer: $('weather-table-container'), weatherDownloadContainer: $('weather-download-container'),
}

let currentProject, demLayer = null, drawChecker = '', mapContainer = null, pointCollections = [], 
    currentPolygon = null, polygonMarkers = [], streamLayer = null, lastRadio = null, 
    terrainTileURL = '', terrainMinMax = null, terrainBounds = null, html = '',
    streamTileURL = '', streamMinMax = null, streamBounds = null, catchmentLayer = null,
    catchmentTileURL = '', catchmentBounds = null, pointLayer = null, waterLayer = null,
    soilLayer = null, soilTileURL = '', soilBounds = null, soilMinMax = null,
    landLayer = null, landContent = null,
    riverLayer = null;


// initRequestListener(); windowListener(); 
setupTabs(document); await getProject(); 
const mapObj = await initMap('leaflet-map-flow-preparation'); 
mapOptions(mapObj); settingManager(); topographyManager();
soilManager(); landManager(); riverManager(); 
// weatherManager(); 

async function getProject() { 
    const userName = await getUser(); currentProject = userName.split('/').pop();
    const respond = await getProjectList(currentProject, '', 'getProjects', 'flows');
    await projectRender(obj.projectName, obj.projectList, respond);
}

function settingManager() {
    // Create new flow project
    obj.projectCreator.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (!name || name === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const content = { projectName: currentProject, flowName: name };
        const data = await jsonLoader('flow_project', content);
        if (data.status === 'error' || data.status === 'create') { alert(data.message); return; }
        obj.waterInputText.value = data.content['water']; obj.terrainName.value = data.content['dtm'];
        if (data.content['water'] !== '') { setElementsEnabled(true, obj.riverLakeClipBtn);
        } else { setElementsEnabled(false, obj.riverLakeClipBtn); }
        const soilData = data.content['soil'];
        let defaultOption = `<option value="" selected>--- Select a layer ---</option>`;
        if (soilData.length > 0) { 
            const options = soilData.map(
                row => `<option value="${row.value}">${row.label}</option>`
            ).join('');
            obj.soilLayer.innerHTML = defaultOption + options; obj.soilSource.value = "isric";
        } else { obj.soilLayer.innerHTML = defaultOption; }
    });
    obj.projectDelete.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (!name || name === '') { alert('Please define scenario.'); return; }
        signalSender('showOverlay', `Deleting scenario '${name}'. Please wait...`);
        const content = { projectName: currentProject, flowName: name };
        const data = await jsonLoader('delete_project_flow', content);
        obj.projectName.value = ''; await getProject();
        signalSender('hideOverlay'); alert(data.message);
        obj.waterInputText.value = ''; obj.terrainName.value = '';
    });
    // Add water layer
    obj.waterUploadBtn.addEventListener('click', async () => { obj.waterInputFile.click(); });  
    obj.waterInputFile.addEventListener('change', async (e) => {
        const name = obj.projectName.value.trim(); resetMap();
        if (name === '') { alert('Please define scenario name first.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const file = e.target.files[0]; if (!file) return;
        const formData = new FormData(); formData.append('projectName', currentProject);
        formData.append('file', file); formData.append('flowName', name); 
        try {
            signalSender('Uploading and processing water data.\nPlease wait...');
            const response = await fetch('/water_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.content.message); return; }
            waterLayer = await mapPlotter(data.content.water_area, mapObj, 'Water Body');
            obj.waterInputText.value = file.name; e.target.value = '';
        } catch (error) { alert(`Uploading water layer failed: ${error.message}`); }
    });
    obj.waterCheckbox.addEventListener('change', async (e) => {
        const name = obj.projectName.value.trim(), water = obj.waterInputText.value.trim();
        if (name === '' || water === '') { 
            alert('Please define scenario name and water layer first.');
            e.target.checked = false; return; 
        }
        if (e.target.checked && water !== '' && name !== '') {
            signalSender('Uploading water data.\nPlease wait...');
            const content = { projectName: currentProject, flowName: name, water: water, key: 'water' };
            const data = await jsonLoader('data_upload', content); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            waterLayer = await mapPlotter(data.content, mapObj, 'Water Body');
        } else { 
            if (waterLayer) { waterLayer.remove(); }
        }
    });
    // Delete water layer
    obj.waterDeleteBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please define scenario name first.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        try {
            signalSender('showOverlay', 'Deleting water layer. Please wait...');
            const content = { projectName: currentProject, flowName: name };
            const data = await jsonLoader('water_delete', content);
            signalSender('hideOverlay'); alert(data.message); obj.waterInputText.value = '';
            if (data.status === 'error') { return; }
            if (waterLayer) { waterLayer = clearMap(waterLayer, mapObj); }
        } catch (error) { alert(`Deleting water layer failed: ${error.message}`); }
    });
    // Upload catchment
    obj.catchmentInputFile.addEventListener('change', async (e) => {
        const file = e.target.files[0]; if (!file) return;
        const formData = new FormData(); formData.append('file', file);
        try {
            signalSender('showOverlay', 'Uploading catchment data. Please wait...');
            const response = await fetch('/geojson_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            catchmentLayer = await mapPlotter(data.content, mapObj, 'Catchment');
        } catch (error) { alert(`Uploading catchment failed: ${error.message}`); }
        finally { e.target.value = ''; }
    });
}

function topographyManager() {
    // Work with terrain option
    document.querySelectorAll('input[name="terrain-import"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const value = e.target.value;
            if (value === 'upload') { 
                obj.uploadContainer.style.display = 'flex';
                obj.downloadContainer.style.display = 'none';
            } else if (value === 'download') {
                obj.uploadContainer.style.display = 'none';
                obj.downloadContainer.style.display = 'flex';
            }
        });
    });
    // Work on terrain
    obj.terrainBtn.addEventListener('click', async () => {
        obj.terrainInputText.value = ''; obj.terrainInputFile.value = '';
        resetMap(); obj.terrainInputFile.click();
    });    
    obj.terrainInputFile.addEventListener('change', async (e) => { 
        const file = e.target.files[0]; if (!file) return;
        const value = obj.projectName.value.trim(); const name = 'dem.tif';
        if (!value || value === '') { alert('Please define scenario name first.'); return; }
        try {
            signalSender('Uploading and processing terrain data.\nPlease wait...');
            const formData = new FormData(); formData.append('projectName', currentProject);
            formData.append('file', file); formData.append('flowName', value);
            const response = await fetch('/upload_terrain_flow', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            terrainMinMax = data.content.min_max; terrainBounds = data.content.bounds;
            terrainTileURL = data.content.tile_url; demLayer = clearMap(demLayer, mapObj);
            demLayer = await displayTerrain(mapObj, terrainTileURL, terrainBounds);
            await drawColorbar(obj.colorBar, terrainMinMax, 'DEM', 'terrain');
            obj.terrainName.value = name; obj.terrainInputText.value = file.name; e.target.value = '';
        } catch (error) { alert(`Uploading terrain failed: ${error.message}`); }
        lastRadio = document.querySelector('input[name="terrain"][value="terrain-raw"]');
        if (lastRadio) lastRadio.checked = true;
    });    
    obj.terrainDrawBtn.addEventListener('click', async () => {
        const value = obj.projectName.value.trim();
        if (value === '') { alert('Please define scenario name first.'); return; }
        drawChecker = 'dem'; demLayer = clearMap(demLayer, mapObj);
        obj.terrainTopLeft.value = ''; obj.terrainBottomRight.value = '';
        obj.terrainName.value = ''; obj.colorBar.style.display = 'none';
        pointCollections = []; polygonMarkers.forEach(marker => marker.remove()); polygonMarkers = [];
        if (currentPolygon && currentPolygon !== null) { currentPolygon.remove(); currentPolygon = null; }
        setTimeout(() => { mapObj.invalidateSize(); }, 10);
        mapObj.closeTooltip(hoverTooltip);
    });
    obj.terrainDownloadBtn.addEventListener('click', async () => {
        const value = obj.projectName.value.trim(), key = 'dem';
        const resolution = obj.terrainResolution.value, folder = `flows/${value}`;
        if (value === '') { alert('Please define scenario name first.'); return; }
        const topLeft = obj.terrainTopLeft.value, bottomRight = obj.terrainBottomRight.value;
        if (topLeft === '' || bottomRight === '') { alert('Please define the area on map first.'); return; }
        try {
            const content = { projectName: currentProject, resolution: resolution, 
                topLeft: topLeft, bottomRight: bottomRight, key: key, folder: folder
            };
            signalSender('showOverlay', 'Downloading DEM for the selected area. Please wait...');
            const request = await jsonLoader('download_dem', content); signalSender('hideOverlay');
            if (request.status === 'error') { alert(request.message); return; }
            polygonMarkers.forEach(marker => marker.remove()); polygonMarkers = [];
            if (currentPolygon && currentPolygon !== null) { 
                currentPolygon.remove(); currentPolygon = null;
            }
            signalSender('Uploading terrain data.\nPlease wait...');
            const formData = new FormData(); formData.append('projectName', currentProject);
            formData.append('folder', folder); formData.append('fileName', key);
            const response = await fetch('/upload_terrain', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            terrainMinMax = data.content.min_max; terrainBounds = data.content.bounds;
            terrainTileURL = data.content.tile_url; demLayer = clearMap(demLayer, mapObj);
            if (streamLayer) { mapObj.removeLayer(streamLayer); }
            demLayer = await displayTerrain(mapObj, terrainTileURL, terrainBounds);
            await drawColorbar(obj.colorBar, terrainMinMax, 'DEM', 'terrain');
            obj.terrainName.value = `${key}.tif`;
        } catch (error) { `Downloading DEM failed: ${error.message}`; }
    });
    // Detect streams
    obj.streamBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please define scenario name first.'); return; }
        const dtmName = obj.terrainName.value.trim();
        if (dtmName === '') { alert('Please upload terrain or download terrain first.'); return; }
        const threshold = obj.threshold.value;
        if (threshold === '') { alert('Please enter the threshold value.'); return; }
        try {
            signalSender('showOverlay', 'Detecting streams. Please wait ...');
            const contents = { 
                projectName: currentProject, folder: `flows/${name}`,
                fileName: dtmName.replace('.tif', ''), threshold: threshold
            };
            const data = await jsonLoader('hyd_stream_upload', contents);
            signalSender('hideOverlay');
            if (data.status === "error") { alert(data.message); return; }
            if (demLayer) { mapObj.removeLayer(demLayer); }
            streamMinMax = data.content.min_max; streamBounds = data.content.bounds;
            streamTileURL = data.content.tile_url; streamLayer = clearMap(streamLayer, mapObj);
            streamLayer = await displayTerrain(mapObj, streamTileURL, streamBounds);
            await drawColorbar(obj.colorBar, streamMinMax, 'Stream', 'terrain');
        } catch (error) { alert(`Detecting streams failed: ${error.message}`); }
        lastRadio = document.querySelector('input[name="terrain"][value="terrain-stream"]');
        if (lastRadio) lastRadio.checked = true;
    });
    lastRadio = document.querySelector('input[name="terrain"]:checked'); 
    document.querySelectorAll('input[name="terrain"]').forEach(radio => {
        radio.addEventListener('change', async (e) => {
            const value = e.target.value; resetMap();
            if (value === 'terrain-raw') {
                if (demLayer) { demLayer.addTo(mapObj); }
                else { demLayer = await displayTerrain(mapObj, terrainTileURL, terrainBounds); }
                await drawColorbar(obj.colorBar, terrainMinMax, 'DEM', 'terrain');
            } else if (value === 'terrain-stream') {
                if (streamLayer) { streamLayer.addTo(mapObj); }
                else { streamLayer = await displayTerrain(mapObj, streamTileURL, streamBounds); }
                await drawColorbar(obj.colorBar, streamMinMax, 'Stream', 'terrain');
            } else if (value === 'terrain-catchment') {
                if (catchmentLayer) { catchmentLayer.addTo(mapObj); }
                if (streamLayer) { streamLayer.addTo(mapObj); }
                if (pointLayer) { pointLayer.addTo(mapObj); }
                else { catchmentLayer = await displayTerrain(mapObj, catchmentTileURL, catchmentBounds); }
            }
            lastRadio = e.target;
        });
    });
    obj.catchmentCheckbox.addEventListener('change', async (e) => {
        if (obj.projectName.value.trim() === '') { 
            alert('Please define scenario name first.'); e.target.checked = false; return; 
        }
        if (obj.terrainName.value.trim() === '') { 
            alert('Please upload DEM first.'); e.target.checked = false; return; 
        }
        if (obj.snapDistance.value === '') { 
            alert('Please define snap distance first.'); e.target.checked = false; return; 
        }
        obj.catchmentLat.value = ''; obj.catchmentLon.value = '';
        if (!streamLayer) { 
            alert('Create stream layer first.'); e.target.checked = false; return; 
        }
        if (e.target.checked) { 
            drawChecker = 'catchment'; obj.catchmentRadio.style.display = 'block';
            if (catchmentLayer) { catchmentLayer.addTo(mapObj); }
        } else { 
            drawChecker = ''; obj.catchmentRadio.style.display = 'none';
            if (pointLayer) { pointLayer = clearMap(pointLayer, mapObj); }
            if (catchmentLayer) { catchmentLayer.remove() }; lastRadio.checked = true;
        }
    });
    obj.clipCatchmentBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please select a scenario first.'); return; }
        if (catchmentLayer === null) { alert('Please check/upload a catchment first.'); return; }
        try {
            signalSender('showOverlay', 'Clipping DEM to catchment.\nPlease wait...');
            const content = { 
                projectName: currentProject, flowName: name, catchment: catchmentLayer.toGeoJSON()
            };
            const request = await jsonLoader('clip_dem', content); 
            signalSender('hideOverlay'); alert(request.message);
        } catch (error) { alert(`Clipping DEM to catchment failed: ${error.message}`); }
    });
    obj.exportCatchmentBtn.addEventListener('click', async () => { 
        if (!catchmentLayer || !mapObj.hasLayer(catchmentLayer)) { 
            alert('Please define the catchment first.'); return; 
        }
        await geoJSONExporter(catchmentLayer.toGeoJSON(), 'catchment.geojson');
    });
}

function soilManager() {
    obj.soilSource.addEventListener('change', async (e) => { 
        const value = e.target.value;
        if (value === '') { 
            deleteTable(obj.soilTable);
            const content = ["Soil type", "Soil depth", "Value"];
            addRowToTable(obj.soilTable, content); return;
        } 
        try { 
            signalSender('showOverlay', 'Getting soil data.\nPlease wait...');
            const request = await jsonLoader('data_upload', { key: 'soil' });
            signalSender('hideOverlay');
            if (request.status === 'error') { alert(request.message); return; }
            fillTable(request.content, obj.soilTable, true);
        } catch (error) { alert(`Uploading soil data failed: ${error.message}`); }
    });
    obj.soilCheckerBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please select a scenario first.'); return; }
        obj.soilTable.style.display = 'block'; obj.soilDownload.style.display = 'none';
        try {
            signalSender('showOverlay', 'Getting soil layers.\nPlease wait...');
            const content = { projectName: currentProject, flowName: name };
            const request = await jsonLoader('check_soil', content); signalSender('hideOverlay'); 
            let defaultOption = `<option value="" selected>--- Select a layer ---</option>`;
            if (request.status === 'error' || request.content.length === 0) { 
                alert(request.message); obj.soilLayer.innerHTML = defaultOption; return; 
            }
            const options = request.content.map(
                row => `<option value="${row.value}">${row.label}</option>`
            ).join('');
            obj.soilLayer.innerHTML = defaultOption + options;
        alert(`Number of soil layers loaded: ${request.content.length}`);
        } catch (error) { alert(`Downloading soil data failed: ${error.message}`); }
    });
    obj.downloadSoilBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please select a scenario first.'); return; }
        const value = obj.soilSource.value;
        if (value === '') { alert('Please select a soil source data first.'); return; }
        const terrain = obj.terrainName.value.trim();
        if (terrain === '') { alert('Please upload terrain data first.'); return; }
        try {
            obj.soilTable.style.display = 'none'; obj.soilDownload.style.display = 'flex';
            obj.soilLog.value = '';
            const content = { 
                projectName: currentProject, key: 'soil', flowName: name, 
                waterArea: obj.waterInputText.value.trim(), soilSource: value
            };
            const request = await jsonLoader('start_download_soil', content);
            if (request.status === 'error') { alert(request.message); return; }
            updateLog(currentProject, obj.soilLog, 2, 'soil', async () => {
                alert('Downloading soil data completed.'); obj.soilCheckerBtn.click();
            });
        } catch (error) { alert(`Downloading soil data failed: ${error.message}`); }
    });
    obj.soilLayer.addEventListener('change', async (e) => { 
        const value = e.target.value; if (value === '') { return; }
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please select a scenario first.'); return; }
        try {
            signalSender('showOverlay', 'Uploading and processing soil data. Please wait ...');
            const contents = { 
                projectName: currentProject, flowName: name, layerName: value
            };
            const data = await jsonLoader('soil_upload', contents); signalSender('hideOverlay');
            if (data.status === "error") { alert(data.message); return; }
            resetMap(); obj.soilCheckbox.checked = true;
            soilTileURL = data.content.tile_url; soilBounds = data.content.bounds;
            soilMinMax = data.content.min_max; obj.colorBar.style.display = 'block';
            soilLayer = await displayTerrain(mapObj, soilTileURL, soilBounds);
            await drawColorbar(obj.colorBar, soilMinMax, 'Soil Type', 'terrain');
        } catch (error) { 
            alert(`Uploading soil data failed: ${error.message}`); 
            obj.soilCheckbox.checked = false; obj.colorBar.style.display = 'none';
        }
    });
    obj.soilCheckbox.addEventListener('change', async (e) => { 
        const name = obj.projectName.value.trim();
        if (name === '') { 
            alert('Please select a scenario first.');
            e.target.checked = false; return; 
        }
        if (e.target.checked) {
            const value = obj.soilLayer.value;
            if (value === '') { 
                alert('Please select a soil layer first.'); 
                e.target.checked = false; return; 
            }
            if (soilLayer) { soilLayer.addTo(mapObj); }
            else { soilLayer = await displayTerrain(mapObj, soilTileURL, soilBounds); }
            await drawColorbar(obj.colorBar, soilMinMax, 'Soil Type', 'terrain');
            obj.colorBar.style.display = 'block';
        } else { mapObj.removeLayer(soilLayer); obj.colorBar.style.display = 'none'; }
    });
}

function landManager() {
    obj.landLoaderBtn.addEventListener('click', async () => { 
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please select a scenario from first.'); return; }
        const value = obj.landSource.value;
        if (landLayer) {
            if (!confirm(
                `Land cover data is already loaded.\n` + 
                `Toggle the checkbox 'Show/Hide Land Cover' to show or hide the layer.\n\n` +
                `Are you sure you want to reload?`
            )) { return; }
        }
        try {
            signalSender('showOverlay', 'Getting and processing land cover layers.\nPlease wait...');
            const content = { 
                projectName: currentProject, key: 'land-load', flowName: name, landSource: value
            };
            const request = await jsonLoader('data_upload', content); signalSender('hideOverlay');
            if (request.status === 'error') { alert(request.message); return; }
            resetMap(); obj.landCheckbox.checked = true; landContent = request.content;
            landLayer = await mapPlotter(landContent, mapObj, 'Land Cover');
        } catch (error) { 
            alert(`Uploading land cover data failed: ${error.message}`); 
            obj.landCheckbox.checked = false;
        }
        obj.colorBar.style.display = 'none';
    });
    obj.landCheckbox.addEventListener('change', async (e) => { 
        if (e.target.checked) { 
            const name = obj.projectName.value.trim();
            if (name === '') { 
                alert('Please select a scenario first.');
                e.target.checked = false; return; 
            }
            if (landLayer) { landLayer.addTo(mapObj); }
            else {
                signalSender('showOverlay', 'Getting land cover layers.\nPlease wait...');
                const content = { 
                    projectName: currentProject, key: 'land-open', flowName: name
                };
                const request = await jsonLoader('data_upload', content); signalSender('hideOverlay');
                if (request.status === 'error') { alert(request.message); e.target.checked = false; return; }
                resetMap(); e.target.checked = true;
                landLayer = await mapPlotter(request.content, mapObj, 'Land Cover');
            }
        } else { mapObj.removeLayer(landLayer); }
        obj.colorBar.style.display = 'none';
    });
}

function riverManager() {
    document.querySelectorAll('input[name="river"]').forEach(radio => { 
        radio.addEventListener('change', (e) => {
            const value = e.target.value;
            if (value === 'river-raster') { 
                obj.riverContainer.style.display = 'flex';
                setElementsEnabled(true, 
                    obj.riverCatchmentUploadBtn, obj.riverCatchmentClipBtn,
                );
                if (obj.waterInputText.value.trim() !== '') {
                    setElementsEnabled(true, obj.riverLakeClipBtn);
                } else {
                    setElementsEnabled(false, obj.riverLakeClipBtn);
                }
                obj.riverUploadBtn.innerHTML = 'Upload DEM (*.tif)';
            } else if (value === 'river-vector') { 
                obj.riverContainer.style.display = 'none';
                setElementsEnabled(false, 
                    obj.riverCatchmentUploadBtn, obj.riverCatchmentClipBtn, obj.riverLakeClipBtn
                );
                obj.riverUploadBtn.innerHTML = 'Upload River (*.geojson)';
            }
        });
    });
    obj.riverUploadBtn.addEventListener('click', () => { obj.riverInputFile.click(); });
    obj.riverInputFile.addEventListener('change', async (e) => {
        const riverOption = document.querySelector('input[name="river"]:checked').value;
        const threshold = Number(obj.riverThreshold.value.trim());
        if (riverOption === 'river-raster' && isInvalidNumber(threshold)) {
            alert('Please select a valid threshold value.'); return;
        }
        const file = e.target.files[0]; if (!file) return;
        const formData = new FormData(); formData.append('file', file);
        formData.append('key', riverOption); formData.append('threshold', threshold);
        try {
            signalSender('showOverlay', 'Uploading terrain and processing river data.\nPlease wait...');
            const response = await fetch('/river_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            resetMap(); riverLayer = await mapPlotter(data.content, mapObj, 'River');
            obj.riverCheckbox.checked = true;
        } catch (error) { 
            alert(`Uploading river data failed: ${error.message}`);
            obj.riverCheckbox.checked = false;
        } finally { e.target.value = ''; }
    });
    obj.riverCheckbox.addEventListener('change', async (e) => {
        if (e.target.checked) { 
            if (!riverLayer) { 
                alert('Please upload/create a river layer first.'); 
                e.target.checked = false; return; 
            } else { riverLayer.addTo(mapObj); }
        } else { 
            if (riverLayer) { mapObj.removeLayer(riverLayer); }
    //         const content = ['Segment ID', 'Width', 'Depth'];
    //         deleteTable(obj.riverTable); addRowToTable(obj.riverTable, content);
        }
    });
    obj.riverCatchmentUploadBtn.addEventListener('click', () => { obj.catchmentInputFile.click(); });
    obj.riverCatchmentClipBtn.addEventListener('click', async () => {
        if (!riverLayer) { alert('Please upload/create a river layer first.'); return; }
        if (!catchmentLayer) { alert('Please upload a catchment.'); return; }
        const content = { 
            baseLayer: riverLayer.toGeoJSON(), clipLayer: catchmentLayer.toGeoJSON(), getArea: 'inside' 
        };
        signalSender('showOverlay', 'Clipping river layer to catchment boundary.\nPlease wait...');
        const request = await jsonLoader('polygon_clip', content); signalSender('hideOverlay');
        if (request.status === 'error') { alert(request.message); return; }
        resetMap(); riverLayer = await mapPlotter(request.content, mapObj, 'River');
        obj.riverCheckbox.checked = true;
    });
    obj.riverLakeClipBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please select a scenario from first.'); return; }
        if (!riverLayer) { alert('Please upload/create a river layer first.'); return; }
        const waterBodies = obj.waterInputText.value.trim();
        if (waterBodies === '') { alert('Please upload a water area in tab "Water Bodies".'); return; }
        signalSender('showOverlay', 'Getting water bodies data.\nPlease wait...');
        const res = {
            projectName: currentProject, key: 'water-body', flowName: name, waterArea: waterBodies,
        }
        const data = await jsonLoader('data_upload', res); signalSender('hideOverlay');
        if (data.status === 'error') { alert(data.message); return; }
        waterLayer = await mapPlotter(data.content, mapObj, 'Water Body');
        const content = { 
            baseLayer: riverLayer.toGeoJSON(), clipLayer: waterLayer.toGeoJSON(), getArea: 'outside' 
        };
        signalSender('showOverlay', 'Clipping river layer to water area.\nPlease wait...');
        const request = await jsonLoader('polygon_clip', content); signalSender('hideOverlay');
        if (request.status === 'error') { alert(request.message); return; }
        resetMap(); riverLayer = await mapPlotter(request.content, mapObj, 'River');
        obj.riverCheckbox.checked = true;
    });
    obj.invalidRiverBtn.addEventListener('click', async () => { 
        if (!riverLayer) { alert('Please upload/create a river layer first.'); return; }
        signalSender('showOverlay', 'Checking for invalid polygons.\nPlease wait...');
        const validContent = [], invalidContent = [], invalidIDs = [];
        riverLayer.eachLayer((layer) => { 
            const props = layer.feature?.properties;
            const id = props?.description;
            const width = props?.Width, depth = props?.Depth;
            const widthInvalid = isInvalidNumber(width);
            const depthInvalid = isInvalidNumber(depth);
            const check = widthInvalid || depthInvalid;
            // Highlight invalid polygons
            if (check) {
                layer.setStyle({ color: 'red', weight: 3 });
                const values = [id, width ?? 'None', depth ?? 'None'];
                invalidContent.push(values); invalidIDs.push(id);
            } else {
                layer.setStyle({ color: 'green', weight: 3 });
                const values = [id, width, depth];
                validContent.push(values);
            }
            layer.on('click', (e) => { 
                L.DomEvent.stopPropagation(e);
                obj.riverIds.textContent = '';
                const option = document.createElement('option');
                option.value = id; option.textContent = id;
                obj.riverIds.appendChild(option);
                obj.riverTableContainer.style.display = 'block';
                fillTable([[id, width, depth]], obj.riverTable, true);
            });
        }); signalSender('hideOverlay');
        if (invalidIDs.length === 0) { 
            alert(`All river segments are valid.`); obj.riverTableContainer.style.display = 'none';
        } else { 
            alert(`Number of invalid river segments: ${invalidIDs.length}.`);
            invalidIDs.forEach(id => {
                const option = document.createElement('option');
                option.value = id; option.textContent = id;
                obj.riverIds.appendChild(option);
            });
            fillTable(invalidContent, obj.riverTable, true);
            obj.riverTableContainer.style.display = 'block';
        }
    });
    // obj.riverDeleteBtn.addEventListener('click', async () => {
    //     const riverChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
    //     if (!riverChecker.exist) { alert('Please upload/create a river layer first.'); return; }
    //     const data = getDataFromTable(obj.riverTable, true).rows, id = obj.inValidDiverIds.value;
    //     if (data.length === 0) { alert('Please select a segment of the river on map to delete.'); return; }
    //     await sendRequest('flowOptions', { 
    //         key: 'deleteItem', layerKey: 'riverLayer_Vector', id: id, type: 'river' 
    //     });
    //     const selectData = data.filter(v => Number(v[0]) !== Number(id));
    //     const firstValues = selectData.map(arr => arr[0]);
    //     obj.inValidDiverIds.textContent = '';
    //     firstValues.forEach(id => {
    //         const option = document.createElement('option');
    //         option.value = id; option.textContent = id;
    //         obj.inValidDiverIds.appendChild(option);
    //     });
    //     deleteTable(obj.riverTable); addRowToTable(obj.riverTable, ['Segment ID','Width','Depth']);
    // });
    // obj.assignRiverBtn.addEventListener('click', async () => { 
    //     const riverChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
    //     if (!riverChecker.exist) { alert('Please upload/create a river layer first.'); return; }
    //     const data = getDataFromTable(obj.riverTable, true).rows;
    //     if (data.length === 0) { alert('Please select a segment of the river on map to edit.'); return; }
    //     const id = obj.inValidDiverIds.value;
    //     const selectData = data.filter(v => Number(v[0]) === Number(id));
    //     if (selectData.length === 0) { alert(`Cannot find the selected segment '${id}' in the table.`); return; }
    //     if (selectData[0].some(v => !v.trim() || Number.isNaN(Number(v)))) {
    //         alert('Values in the table must be numeric.'); return;
    //     }
    //     const response = await sendRequest('flowOptions', { 
    //         key: 'assignType', layerKey: 'riverLayer_Vector', id: id, data: selectData[0], type: 'river' 
    //     });
    //     obj.inValidDiverIds.textContent = '';
    //     response.ids.forEach(id => {
    //         const option = document.createElement('option');
    //         option.value = id; option.textContent = id;
    //         obj.inValidDiverIds.appendChild(option);
    //     });
    //     deleteTable(obj.riverTable); fillTable(response.data, obj.riverTable, true);
    // });
    // obj.saveRiverProjectBtn.addEventListener('click', async () => { 
    //     const name = obj.projectName.value.trim();
    //     if (!name || name.trim() === '') { alert('Please define scenario name.'); return; }
    //     if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
    //     const layer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'riverLayer_Vector' });
    //     if (layer.data === null) { alert('Layer is empty. Please upload/create a river layer first.'); return; }
    //     const dataRows = getDataFromTable(obj.validRiverTable, true);
    //     if (dataRows.rows.length === 0) { alert('No valid segments found. Please check the valid table.'); return; }
    //     const segments = dataRows.rows.map(row => Number(row[0]));
    //     signalSender('showOverlay', 'Saving river layer to project. Please wait...');
    //     const content = { projectName: currentProject, flowName: name, data: layer.data, segments: segments };
    //     const data = await jsonLoader('river_saver', content);
    //     signalSender('hideOverlay'); alert(data.message);
    // });
    // obj.saveRiverFileBtn.addEventListener('click', async () => { 
    //     const riverChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
    //     if (!riverChecker.exist) { alert('Please upload/create a river layer first.'); return; }
    //     const layer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'riverLayer_Vector' });
    //     if (layer.data === null) { alert('Layer is empty. Please upload/create a river layer first.'); return; }
    //     const dataRows = getDataFromTable(obj.validRiverTable, true);
    //     if (dataRows.rows.length === 0) { alert('No valid segments found. Please check the valid table.'); return; }
    //     const segments = dataRows.rows.map(row => Number(row[0]));
    //     const selectedSet = new Set(segments);
    //     const filterObj = {...layer,
    //         data:{
    //             ...layer.data,
    //             features: layer.data.features.filter(
    //                 feature => selectedSet.has(feature.properties?.description)
    //             )
    //         }
    //     }
    //     await geoJSONExporter(filterObj.data, 'river.geojson');
    // });
}

function weatherManager() {
    const startOfDay = new Date(), now = new Date(); startOfDay.setHours(0, 0, 0, 0);
    document.querySelectorAll('input[name="weather"]').forEach(item => {
        item.addEventListener('change', (e) => {
            if (e.target.value === 'weather-csv') { 
                setElementsDisplayed(true, 
                    obj.weatherCSVContainer, obj.weatherTableContainer,
                );
                setElementsDisplayed(false, 
                    obj.weatherDownloadContainer, obj.weatherStationContainer,
                    obj.downloadWeatherBtn, obj.weatherSourceContainer,
                    obj.weatherCatchmentContainer, obj.weatherStationStartContainer,
                    obj.weatherStationEndContainer
                );
            } else {
                setElementsDisplayed(false, 
                    obj.weatherCSVContainer, obj.weatherTableContainer,
                );
                setElementsDisplayed(true, 
                    obj.weatherDownloadContainer, obj.weatherStationContainer,
                    obj.downloadWeatherBtn, obj.weatherSourceContainer,
                    obj.weatherCatchmentContainer, obj.weatherStationStartContainer,
                    obj.weatherStationEndContainer
                );
            }
        });
    });
    obj.weatherBtn.addEventListener('click', () => { obj.weatherInputFile.click(); });
    obj.weatherInputFile.addEventListener('change', async (e) => {
        const name = obj.projectName.value;
        if (name === '') { 
            alert('Please select a scenario from the tab "Settings" first.'); return; 
        }
        signalSender('showOverlay', 'Uploading weather data from CSV file.\nPlease wait...');
        try { await csvUploader(e, obj.weatherInputText, obj.weatherTable, 7);
        } finally { signalSender('hideOverlay'); }
    });
    obj.weatherStationSelector.addEventListener('change', async(e) => {
        const value = e.target.value;
        if (!value || value === '') {
            obj.weatherStationStartContainer.style.display = 'none';
            obj.weatherStationEndContainer.style.display = 'none';
            obj.downloadWeatherBtn.style.display = 'none'; return;
        }
        obj.weatherStationStartContainer.style.display = 'flex';
        obj.weatherStationEndContainer.style.display = 'flex';
        obj.downloadWeatherBtn.style.display = 'flex';
        obj.weatherStart.value = formatDate(startOfDay); 
        obj.weatherEnd.value = formatDate(now);
    });
    obj.weatherCatchmentBtn.addEventListener('click', () => obj.catchmentInputFile.click());
    obj.downloadWeatherBtn.addEventListener('click', async () => {
        const value = obj.weatherStationSelector.value, name = obj.projectName.value;
        if (!value || value === '') { 
            alert('Please select a weather station first.'); return; 
        }
        if (name === '') { 
            alert('Please select a scenario from the tab "Settings" first.'); return; 
        }
        if (value == 'era5') {
            const data = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'catchmentLayer_Vector' });
            if (data.data === null) { alert('Please upload a catchment first.'); return; }
            const startTime = obj.weatherStart.value, endTime = obj.weatherEnd.value;
            if (startTime === '' || endTime === '') { alert('Please select a time range first.'); return; }
            const keyChecker = 'weather';
            const contentChecker = {projectName: currentProject, key: keyChecker};
            const statusRes = await jsonLoader('check_download_status', contentChecker);
            if (statusRes.status === "running") { alert("Weather download is running."); return; }
            obj.weatherLog.value = '';
            const content = { 
                projectName: currentProject, flowName: name, timeZone: getLastTimeZone(),
                data: data.data, start: startTime, end: endTime, keyChecker: keyChecker
            };
            const start = await jsonLoader('start_download_weather', content);
            if (start.status === "error") { alert(start.message); return; }
            updateLog(currentProject, obj.weatherLog, 2, keyChecker, async () => {
                alert('Downloading weather completed.');
            });
        }
    });
    obj.saveWeatherBtn.addEventListener('click', async () => {
        const name = obj.projectName.value;
        if (name === '') { 
            alert('Please select a scenario from the tab "Settings" first.'); return; 
        }
        const data = getDataFromTable(obj.weatherTable, true);
        if (data.length === 0) { alert('Please upload weather data first.'); return; }
        signalSender('showOverlay', 'Creating weather data. Please wait...');
        const content = { 
            projectName: currentProject, flowName: name, 
            data: data, timeZone: getLastTimeZone(), interval: interval.value
        };
        const request = await jsonLoader('save_flow_weather', content);
        signalSender('hideOverlay'); alert(request.message);
    });
}



function mapOptions(map) {
    mapContainer = map.getContainer();
    map.on('mousemove', function (e) {
        if (drawChecker === 'dem') {
            mapContainer.style.cursor = "crosshair";
            html = 'Draw an area on map to download DEM.';
            if (polygonMarkers.length > 0) { html += '<br/>Right-click to finish drawing.'; }
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            map.openTooltip(hoverTooltip);
        } else if (drawChecker == 'catchment') {
            mapContainer.style.cursor = "crosshair";
            html = 'Select point on stream network to define catchment area.';
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            map.openTooltip(hoverTooltip);
        }
        if (drawChecker === '') { 
            map.closeTooltip(hoverTooltip); mapContainer.style.cursor = ''; 
        }
    });
    map.on('click', async function (e) {
        if (drawChecker === 'dem') {
            pointCollections.push(e.latlng);
            const marker = L.circleMarker(e.latlng, {
                radius: 4, color: '#2563eb', 
                fillColor: '#ffffff', fillOpacity: 1, weight: 2
            }).addTo(map);
            polygonMarkers.push(marker);
            if (pointCollections.length >= 3) {
                if (currentPolygon) { currentPolygon.setLatLngs(pointCollections);
                } else {
                    currentPolygon = L.polygon(pointCollections, {
                        color: '#2563eb', weight: 2,
                        fillColor: '#3b82f6', fillOpacity: 0.2
                    }).addTo(map);
                }
            }
            hoverTooltip.setLatLng(e.latlng).setContent('Right-click to finish drawing.');
            map.openTooltip(hoverTooltip);
        } else if (drawChecker === 'catchment') {
            const radio = document.querySelector('input[name="terrain"][value="terrain-catchment"]');
            try { 
                const lat = Number(e.latlng.lat).toFixed(8), lon = Number(e.latlng.lng).toFixed(8);
                const name = obj.projectName.value.trim(), dem = obj.terrainName.value.trim().replace(".tif", "");
                obj.catchmentLat.value = lat; obj.catchmentLon.value = lon;
                const content = { 
                    projectName: currentProject, folder: `flows/${name}`, fileName: dem,
                    lat: lat, lon: lon, snapDistance: Number(obj.snapDistance.value), 
                }
                signalSender('showOverlay', 'Defining catchment. Please wait...');
                const data = await jsonLoader('catchment_definer', content); 
                signalSender('hideOverlay');
                if (data.status === 'error') { alert(data.message); return; }
                if (demLayer) { mapObj.removeLayer(demLayer); }
                catchmentLayer = clearMap(catchmentLayer, mapObj);
                catchmentLayer = L.geoJSON(data.content, {
                    style: { color: 'blue', weight: 2, fillColor: '#10b9d6', fillOpacity: 0.5 }
                }).addTo(mapObj);
                pointLayer = clearMap(pointLayer, mapObj);
                pointLayer = L.circleMarker(e.latlng, {
                    radius: 4, fillColor: 'blue', color: 'red', weight: 2, opacity: 1, fillOpacity: 1
                }).addTo(mapObj);
                if (radio) { radio.checked = true; }
            } catch (error) { 
                obj.catchmentCheckbox.checked = false; lastRadio.checked = true; alert(error.message); 
            }
        }
    });
    map.on('contextmenu', async function (e) {
        if (drawChecker !== 'dem') return;
        e.originalEvent.preventDefault();
        if (pointCollections.length < 3) { alert('At least 3 points are required to create a polygon.'); return; }
        drawChecker = ''; mapContainer.style.cursor = ""; hoverTooltip.closeTooltip();
        const bounds = L.latLngBounds(pointCollections);
        obj.terrainTopLeft.value = `(${Number(bounds.getNorth()).toFixed(8)}, ${Number(bounds.getWest()).toFixed(8)})`;
        obj.terrainBottomRight.value = `(${Number(bounds.getSouth()).toFixed(8)}, ${Number(bounds.getEast()).toFixed(8)})`;
    });
}

function clearMap(layer, map) {
    if (layer) { map.removeLayer(layer); }
    return null;
}

function resetMap(){
    // Hide all layers
    const layers = [
        demLayer, streamLayer, catchmentLayer, pointLayer, waterLayer,
        soilLayer, landLayer, riverLayer
    ];
    layers.forEach((layer) => { if (layer) layer.remove(); });
    obj.colorBar.style.display = 'none'; obj.waterCheckbox.checked = false;
    obj.soilCheckbox.checked = false; obj.landCheckbox.checked = false;
    obj.riverCheckbox.checked = false;
    const temp = document.querySelector('input[name="terrain"][value="hide-all"]');
    if (temp) temp.checked = true;
}

// function windowListener() {
//     // // Check whether map widget exists
//     // const layout = localStorage.getItem('grid-layout');
//     // const hasMap = layout ? JSON.parse(layout).some(item => item.id === flowId):false;
//     // const content = { id: flowId, title: 'Flow Estimation Map' };
//     // if (!hasMap) signalSender('addMapWidget', content);
//     window.addEventListener('message', (e) => {
//         if (e.data?.type === 'updateUIDelay') {
//             const content = e.data.content;
//             if (content.key === 'River') { 
//                 console.log(content);
//                 const inValidIds = obj.inValidDiverIds;
//                 const validTable = obj.riverTable;
//                 inValidIds.textContent = '';
//                 content.invalidIDs.forEach(id => {
//                     const option = document.createElement('option');
//                     option.value = id; option.textContent = id;
//                     inValidIds.appendChild(option);
//                 });
//                 // deleteTable(invalidTable); deleteTable(validTable);
//                 // content.inValidData.forEach(row => { fillTable([row], invalidTable, false); });
//                 // content.validData.forEach(row => { fillTable([row], validTable, false); });
//             };
//             signalSender('hideOverlay');
//         }
//     });
// }