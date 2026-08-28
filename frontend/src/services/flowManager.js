import { setupTabs } from "./tabManager.js";
import { flowId } from "./constant.js";
import { getUser, signalSender, sendRequest, initRequestListener, 
    nameChecker, csvUploader, getProjectList, jsonLoader, fillTable, 
    deleteTable, addRowToTable, getDataFromTable, formatDate, updateLog
} from "./commonFunctions.js";
import { catchmentDelineation, geoJSONExporter, 
    setElementsEnabled, setElementsDisplayed
} from "./flowFunctions.js";
import { projectRender } from "./projectManager.js";


const $ = (id) => document.getElementById(id);
const obj = {
    projectList: $('project-list'), projectName: $('project-name'), projectCreator: $('create-btn'),
    waterInputText: $('water-input-text'), waterInputFile: $('water-input-file'), waterBtn: $('water-btn'),
    catchmentInputFile: $('catchment-input-file'), terrainBtn: $('terrain-btn'), 
    terrainInputFile: $('terrain-input-file'), terrainInputText: $('terrain-input-text'), 
    streamBtn: $('stream-btn'), threshold: $('threshold'), pourpointContainer: $('pourpoint-container'), 
    pourpointCheckbox: $('pourpoint-checkbox'), exportContainer: $('export-container'), 
    exportCatchmentBtn: $('export-catchment-btn'), exportPointBtn: $('export-pourpoint-btn'), pourpointLat: $('pourpoint-lat'), 
    pourpointLon: $('pourpoint-lon'), dist: $('pourpoint-dist'), catchmentRadio: $('catchment-layer'), 
    soilBtn: $('soil-btn'), soilSource: $('soil-source'), soilTable: $('soil-attributes-table'), 
    soilAttributeContainer: $('soil-attribute-container'), soilDownloadContainer: $('soil-download-container'),
    downloadSoilBtn: $('download-soil-btn'), soilCheckerBtn: $('check-soil-btn'), 
    soilLayer: $('soil-layer'), soilLog: $('soil-download-text'),
    landBtn: $('land-btn'), landSource: $('land-source'), landLoaderBtn: $('land-load-btn'),
    riverContainer: $('river-container'), riverUploadBtn: $('river-upload-btn'),    
    riverInputFile: $('river-input-file'), riverInputText: $('river-input-text'),     
    riverThreshold: $('river-threshold'), riverCheckbox: $('river-checker-checkbox'),    
    riverLakeUploadBtn: $('lake-upload-btn'), riverCatchmentUploadBtn: $('lake-catchment-upload-btn'),
    lakeInputFile: $('lake-input-file'), riverLakeClipBtn: $('river-clip-lake-btn'),  
    riverCatchmentClipBtn: $('river-clip-catchment-btn'), invalidDriverBtn: $('river-invalid-checker-btn'),
    invalidRiverTable: $('invalid-river-table'), inValidDiverIds: $('invalid-river-id'),
    saveRiverProjectBtn: $('river-save-project-btn'), riverDeleteBtn: $('river-delete-btn'), 
    validRiverTable: $('valid-river-table'), assignRiverBtn: $('river-assign-btn'), saveRiverFileBtn: $('river-save-file-btn'),
    weatherCSVContainer: $('weather-csv-container'), weatherStationContainer: $('weather-station-container'),
    weatherBtn: $('weather-btn'), weatherInputFile: $('weather-input-file'), weatherInputText: $('weather-input-text'), 
    weatherTable: $('weather-table'), weatherStationSelector: $('weather-station'), saveWeatherBtn: $('weather-save-btn'), 
    weatherSourceContainer: $('weather-source-container'), downloadWeatherBtn: $('weather-download-btn'),
    weatherStationStartContainer: $('weather-station-start'), weatherStationEndContainer: $('weather-station-end'), 
    weatherStart: $('weather-start-date'), weatherEnd: $('weather-end-date'), weatherLog: $('weather-download-text'),
    weatherCatchmentContainer: $('weather-catchment-container'), weatherCatchmentBtn: $('weather-catchment-btn'),
    weatherTableContainer: $('weather-table-container'), weatherDownloadContainer: $('weather-download-container'),
}

let currentProject, minTerrain = null, maxTerrain = null,
    lastRadio = null, isTerrain = false, isStream = false;

initRequestListener(); setupTabs(document); await getProject();
settingManager(); windowListener(); topographyManager();
soilManager(); landManager(); riverManager(); weatherManager(); 

async function getProject() { 
    const userName = await getUser(); currentProject = userName.split('/').pop();
    const respond = await getProjectList(`${currentProject}/flows`, '');
    await projectRender(obj.projectName, obj.projectList, respond);
}

function settingManager() {
    // Create new flow project
    obj.projectCreator.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (!name || name.trim() === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const content = { projectName: currentProject, flowName: name, key: 'create' };
        const data = await jsonLoader('flow_project', content);
        if (data.status === 'error' || data.status === 'create') { alert(data.message); return; }
        obj.waterInputText.value = data.content['water']; obj.terrainInputText.value = data.content['dtm'];
    });
    // Add water layer
    obj.waterInputFile.addEventListener('change', async (e) => {
        const file = e.target.files[0]; if (!file) return;
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const formData = new FormData();
        formData.append('file', file); formData.append('flowName', name); 
        formData.append('projectName', currentProject);
        try {
            signalSender('Uploading and processing water data.\nPlease wait...');
            const response = await fetch('/water_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.content.message); return; }
            const content = { 
                key: 'mapPlotter', layerKey: 'lakeLayer_Vector', 
                data: data.content.water_area, type: 'river', reset: true
            };
            await sendRequest('flowOptions', content); alert(data.content.message);
            obj.waterInputText.value = file.name; e.target.value = '';
        } catch (error) { alert(`Uploading water layer failed: ${error.message}`); }
    });
    obj.waterBtn.addEventListener('click', async () => { obj.waterInputFile.click(); });
}

function topographyManager() {
    // Upload catchment
    obj.catchmentInputFile.addEventListener('change', async (e) => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please define scenario name (in tab "Settings").'); return; }
        const file = e.target.files[0]; if (!file) return; 
        const formData = new FormData(); formData.append('file', file);
        formData.append('flowName', name); formData.append('projectName', currentProject);
        try {
            signalSender('showOverlay', 'Uploading catchment data. Please wait...');
            const response = await fetch('/geojson_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            const content = { 
                key: 'drawLayer', layerKey: 'catchmentLayer_Vector', data: data.content, reset: false
            };
            await sendRequest('flowOptions', content );
        } catch (error) { alert(`Uploading catchment failed: ${error.message}`); }
        finally { e.target.value = ''; }
    });
    // Work on terrain
    obj.terrainBtn.addEventListener('click', async () => {
        obj.terrainInputText.value = ''; obj.terrainInputFile.value = '';
        await sendRequest('flowOptions', { key: 'clearAll' });
        obj.terrainInputFile.click();
    });
    obj.terrainInputFile.addEventListener('change', async (e) => { 
        const file = e.target.files[0]; if (!file) return;
        const value = obj.projectName.value.trim();
        if (!value || value.trim() === '') { alert('Please define scenario name.'); return; }
        const formData = new FormData();
        formData.append('file', file); formData.append('flowName', value); 
        formData.append('projectName', currentProject);
        try {
            signalSender('Uploading and processing terrain data.\nPlease wait...');
            const response = await fetch('/terrain_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            minTerrain = data.content.min, maxTerrain = data.content.max;
            const content = { 
                key: 'drawLayer', data: data.content.tile_url, layerKey: 'terrainLayer',
                reset: true, min: minTerrain, max: maxTerrain
            };
            await sendRequest('flowOptions', content);
            obj.terrainInputText.value = file.name; e.target.value = ''; isTerrain = true;
        } catch (error) { alert(`Uploading terrain failed: ${error.message}`); }
        lastRadio = document.querySelector('input[name="terrain"][value="terrain-raw"]');
        if (lastRadio) lastRadio.checked = true;
    });
    // Detect streams
    obj.streamBtn.addEventListener('click', async () => {
        const layerCheck = obj.terrainInputText.value, name = obj.projectName.value.trim();
        if (layerCheck === '') { alert('Please upload terrain data first.'); return; }
        if (name === '') { alert('Please define scenario name (in tab "Settings").'); return; }
        try {
            signalSender('showOverlay', 'Detecting streams. Please wait ...');
            const contents = { 
                projectName: currentProject, filename: layerCheck, 
                flowName: name, threshold: obj.threshold.value 
            };
            const data = await jsonLoader('stream_upload', contents);
            signalSender('hideOverlay');
            if (data.status === "error") { alert(data.message); return; }
            const content = { 
                key: 'drawLayer', data: data.content.tile_url, layerKey: 'streamLayer', 
                min: data.content.min, max: data.content.max, reset: true
            };
            await sendRequest('flowOptions', content);
            obj.pourpointContainer.style.display = 'flex';
        } catch (error) { alert(`Detecting streams failed: ${error.message}`); }
        lastRadio = document.querySelector('input[name="terrain"][value="terrain-stream"]');
        if (lastRadio) lastRadio.checked = true;
    });
    lastRadio = document.querySelector('input[name="terrain"]:checked'); 
    document.querySelectorAll('input[name="terrain"]').forEach(radio => {
        radio.addEventListener('change', async (e) => {
            let content = {};
            const terrainValue = obj.terrainInputText.value;
            const value = e.target.value;            
            if (terrainValue === '' && value !== 'hide-all') { 
                alert('Please upload terrain data first.'); 
                e.target.checked = false; 
                lastSelectedRadio.checked = true; 
                await sendRequest('flowOptions', { key: 'clearAll' }); return; 
            }
            if (value === 'hide-all') { content = { key: 'clearAll' };
            } else if (value === 'terrain-raw') {
                const terrainCheck = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'terrainLayer' });
                isTerrain = terrainCheck.exist;
                content = { 
                    key: 'drawLayer', layerKey: 'terrainLayer', 
                    min: minTerrain, max: maxTerrain, reset: true
                };
            } else if (value === 'terrain-stream') {
                if (!isTerrain) {
                    alert('Please upload terrain data first.'); 
                    lastRadio.checked = true; e.target.checked = false; return; 
                }
                const streamCheck = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'streamLayer' });
                isStream = streamCheck.exist;
                if (!isStream) { alert('Please run "Extract streams" first.'); 
                    lastRadio.checked = true; e.target.checked = false; return; 
                }
                content = { key: 'drawLayer', layerKey: 'streamLayer', min: 0, max: 1, reset: true };
            } else if (value === 'terrain-catchment') {
                if (!isStream || obj.pourpointLat.value === '' || obj.pourpointLon.value === '') {
                    alert('Please run "Extract streams" and/or select a pourpoint first.'); 
                    lastRadio.checked = true; e.target.checked = false; return;
                }
                content = { key: 'drawLayer', layerKey: 'catchmentLayer_Vector', reset: true };
            }
            lastRadio = e.target; await sendRequest('flowOptions', content);
        });
    });
    obj.pourpointCheckbox.addEventListener('change', async (e) => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please define scenario name (in tab "Settings").'); return; }
        const radio = document.querySelector('input[name="terrain"][value="terrain-catchment"]');
        obj.pourpointLat.value = ''; obj.pourpointLon.value = '';
        if (e.target.checked) {
            const layerCheck = obj.terrainInputText.value;
            lastRadio.checked = true; if (radio) radio.checked = false;
            if (layerCheck === '') { 
                alert('No terrain data uploaded. Please:\n1. Upload terrain data.\n2. Extract Streams.');
                e.target.checked = false; return;
            }
            obj.pourpointContainer.style.display = 'flex';
            try { 
                const content = { key: 'pourpoint', checked: e.target.checked };
                const response = await sendRequest('flowOptions', content);
                const lat = Number(response.result.lat).toFixed(12);
                const lon = Number(response.result.lng).toFixed(12);
                obj.pourpointLat.value = lat; obj.pourpointLon.value = lon;
                const data =  await catchmentDelineation(
                    currentProject, name, layerCheck, lat, lon,obj.dist.value
                );
                if (data !== null) {
                    const content = { 
                        key: 'drawLayer', layerKey: 'catchmentLayer_Vector', data: data, reset: true
                    };
                    await sendRequest('flowOptions', content); e.target.checked = false;
                    if (radio) { radio.checked = true; }
                } else {
                    obj.pourpointContainer.style.display = 'none'; 
                    obj.exportContainer.style.display = 'none';
                    e.target.checked = false;
                }
            } catch (error) { 
                e.target.checked = false; obj.pourpointLat.value = '';
                obj.pourpointLon.value = ''; 
                await sendRequest('flowOptions', { key: 'pourpointCancel' });
            }
        }
    });
    obj.exportCatchmentBtn.addEventListener('click', async () => { 
        const layerCheck = obj.terrainInputText.value;
        if (layerCheck === '') { alert('Please upload terrain data first.'); return; }
        const layer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'catchmentLayer_Vector' });
        if (layer.data === null) { alert('Please select pourpoint and create a catchment first.'); return; }
        await geoJSONExporter(layer.data, 'catchment.geojson');
    });
    obj.exportPointBtn.addEventListener('click', async () => { 
        const lat = Number(obj.pourpointLat.value);
        const lon = Number(obj.pourpointLon.value);
        if (lat === '' || lon === '') { alert('Please select a pourpoint first.'); return; }
        const point = {
            type: "FeatureCollection",
            features: [
                {
                    type: "Feature",
                    properties: {name: "Pourpoint"},
                    geometry: {
                        type: "Point", coordinates: [lon, lat]
                    }
                }
            ]
        };
        await geoJSONExporter(point, 'pourpoint.geojson');
    });
}

function soilManager() {
    obj.soilBtn.addEventListener('click', () => obj.catchmentInputFile.click());
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
        } catch (error) { 
            alert(`Uploading soil data failed: ${error.message}`);
            obj.soilSource.value = '';
        }
    });
    obj.soilCheckerBtn.addEventListener('click', async () => {
        const name = obj.projectName.value;
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        obj.soilAttributeContainer.style.display = 'block'; obj.soilDownloadContainer.style.display = 'none';
        signalSender('showOverlay', 'Getting soil layers.\nPlease wait...');
        const content = { 
            projectName: currentProject, flowName: name 
        };
        const request = await jsonLoader('check_soil', content);
        if (request.status === 'error') {
            signalSender('hideOverlay'); alert(request.message); return; 
        }
        let defaultOption = `<option value="" selected>--- Select a layer ---</option>`;
        if (request.content.length === 0) { 
            obj.soilLayer.innerHTML = defaultOption;
            alert('No soil layer detected.'); return;
        }
        const options = request.content.map(
            row => `<option value="${row.value}">${row.label}</option>`
        ).join('');
        obj.soilLayer.innerHTML = defaultOption + options;
        signalSender('hideOverlay'); alert(`Soil layers loaded: ${request.content.length}`);
    });
    obj.downloadSoilBtn.addEventListener('click', async () => {
        const name = obj.projectName.value;
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const data = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'catchmentLayer_Vector' });
        if (data.data === null) { alert('Please check/upload a catchment first.'); return; }
        const value = obj.soilSource.value;
        if (value === '') { alert('Please select a source first.'); return; }
        const terrain = obj.terrainInputText.value;
        if (terrain === '') { alert('Please upload terrain data first.'); return; }
        obj.soilAttributeContainer.style.display = 'none'; obj.soilDownloadContainer.style.display = 'flex';
        obj.soilLog.value = '';
        const content = { 
            projectName: currentProject, key: 'soil', data: data.data, 
            flowName: name, waterArea: obj.waterInputText.value
        };
        const request = await jsonLoader('start_download_soil', content);
        if (request.status === 'error') { alert(request.message); return; }
        updateLog(currentProject, obj.soilLog, 2, 'soil', async () => {
            alert('Downloading soil data completed.');
        });
    });
    obj.soilLayer.addEventListener('change', async (e) => { 
        const value = e.target.value; if (value === '') return;
        const name = obj.projectName.value; 
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        signalSender('showOverlay', 'Uploading and processing soil data. Please wait ...');
        const contents = { 
            projectName: currentProject, flowName: name, layerName: value
        };
        const data = await jsonLoader('soil_upload', contents);
        signalSender('hideOverlay');
        if (data.status === "error") { alert(data.message); return; }
        const content = { 
            key: 'drawLayer', layerKey: 'soilLayer', reset: true, 
            data: data.content.tile_url, min: data.content.min, max: data.content.max
        };
        await sendRequest('flowOptions', content );
    });
}

function landManager() {
    obj.landBtn.addEventListener('click',  () => { obj.catchmentInputFile.click(); });
    obj.landLoaderBtn.addEventListener('click', async () => { 
        const name = obj.projectName.value;
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const value = obj.landSource.value;
        if (value === '') { alert('Please select a Land Cover source first.'); return; }
        const data = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'catchmentLayer_Vector' });
        if (data.data === null) { alert('Please check/upload a catchment first.'); return; }
        signalSender('showOverlay', 'Getting and processing land cover layers.\nPlease wait...');
        const content = { 
            projectName: currentProject, key: 'land', flowName: name, data: data.data
        };
        const request = await jsonLoader('data_upload', content); signalSender('hideOverlay');
        if (request.status === 'error') { alert(request.message); return; }
        const contents = { 
            key: 'mapPlotter', layerKey: 'landLayer_Vector', 
            data: request.content, type: 'land', reset: true
        };
        await sendRequest('flowOptions', contents);
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
                    obj.riverLakeUploadBtn, obj.riverLakeClipBtn
                );
            } else if (value === 'river-vector') { 
                obj.riverContainer.style.display = 'none';
                setElementsEnabled(false, 
                    obj.riverCatchmentUploadBtn, obj.riverCatchmentClipBtn, 
                    obj.riverLakeUploadBtn, obj.riverLakeClipBtn
                );
            }
        });
    });
    obj.riverUploadBtn.addEventListener('click', () => { obj.riverInputFile.click(); });
    obj.riverInputFile.addEventListener('change', async (e) => {
        const name = obj.projectName.value;
        if (name === '') { 
            alert('Please select a scenario from the tab "Settings" first.'); return; 
        }
        const riverOption = document.querySelector('input[name="river"]:checked').value;
        const threshold = Number(obj.riverThreshold.value);
        if (riverOption === 'river-raster' && threshold <= 0) {
            alert('Please select a threshold value greater than 0.'); return;
        }
        const file = e.target.files[0]; if (!file) return;
        const formData = new FormData(); formData.append('threshold', threshold);
        formData.append('file', file); formData.append('key', riverOption);
        formData.append('projectName', currentProject); formData.append('flowName', name);
        try {
            signalSender('showOverlay', 'Uploading terrain and processing river data.\nPlease wait...');
            const response = await fetch('/river_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            const content = { 
                key: 'mapPlotter', layerKey: 'riverLayer_Vector', 
                data: data.content, type: 'river', reset: true
            };
            await sendRequest('flowOptions', content);
            obj.riverInputText.value = file.name; obj.riverCheckbox.checked = true;
        } catch (error) { 
            alert(`Uploading river data failed: ${error.message}`);
            obj.riverInputText.value = ''; obj.riverCheckbox.checked = false;
        } finally { e.target.value = ''; }
    });
    obj.riverCheckbox.addEventListener('change', async (e) => {
        const layerChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
        if (e.target.checked) { 
            if (!layerChecker.exist) { 
                alert('Please upload/create a river layer first.');
                e.target.checked = false; return; 
            } else { await sendRequest('flowOptions', { key: 'drawLayer', layerKey: 'riverLayer_Vector' }); }
        } else { 
            await sendRequest('flowOptions', { key: 'hideLayer', layerKey: 'riverLayer_Vector' });
            const content = ['Segment ID', 'Width', 'Depth'];
            deleteTable(obj.invalidRiverTable); addRowToTable(obj.invalidRiverTable, content);
        }
    });
    obj.riverCatchmentUploadBtn.addEventListener('click', () => { obj.catchmentInputFile.click(); });
    obj.riverLakeUploadBtn.addEventListener('click', () => { obj.lakeInputFile.click(); });
    obj.lakeInputFile.addEventListener('change', async (event) => {
        const name = obj.projectName.value.trim(); 
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const file = event.target.files[0]; if (!file) return; 
        const formData = new FormData(); formData.append('file', file);
        formData.append('flowName', name); formData.append('projectName', currentProject);
        try {
            signalSender('showOverlay', 'Uploading lake boundary. Please wait...');
            const response = await fetch('/geojson_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            const content = { 
                key: 'mapPlotter', layerKey: 'lakeLayer_Vector', 
                data: data.content, type: 'river', reset: false
            };
            await sendRequest('flowOptions', content);
        } catch (error) { alert(`Uploading lake boundary failed: ${error.message}`); }
        finally { event.target.value = ''; }
    });
    obj.riverLakeClipBtn.addEventListener('click', async () => {
        const riverChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
        if (!riverChecker.exist) { alert('Please upload/create a river layer first.'); return; }
        const lakeChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'lakeLayer_Vector' });
        if (!lakeChecker.exist) { alert('Please upload a lake boundary.'); return; }
        const riverLayer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'riverLayer_Vector' });
        const lakeLayer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'lakeLayer_Vector' });
        const content = { 
            baseLayer: riverLayer.data, clipLayer: lakeLayer.data, getArea: 'outside' 
        };
        signalSender('showOverlay', 'Clipping river layer to lake boundary.\nPlease wait...');
        const request = await jsonLoader('polygon_clip', content); signalSender('hideOverlay');
        if (request.status === 'error') { alert(request.message); return; }
        const contents = { 
            key: 'mapPlotter', layerKey: 'riverLayer_Vector', 
            data: request.content, type: 'river', reset: true
        };
        await sendRequest('flowOptions', contents); obj.riverCheckbox.checked = true;
    });
    obj.riverCatchmentClipBtn.addEventListener('click', async () => {
        const riverChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
        if (!riverChecker.exist) { alert('Please upload/create a river layer first.'); return; }
        const catchmentChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'catchmentLayer_Vector' });
        if (!catchmentChecker.exist) { alert('Please upload a catchment boundary.'); return; }
        const riverLayer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'riverLayer_Vector' });
        const catchmentLayer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'catchmentLayer_Vector' });
        const content = { 
            baseLayer: riverLayer.data, clipLayer: catchmentLayer.data, getArea: 'inside' 
        };
        signalSender('showOverlay', 'Clipping river layer to catchment boundary.\nPlease wait...');
        const request = await jsonLoader('polygon_clip', content); signalSender('hideOverlay');
        if (request.status === 'error') { alert(request.message); return; }
        const contents = { 
            key: 'mapPlotter', layerKey: 'riverLayer_Vector', 
            data: request.content, type: 'river', reset: true
        };
        await sendRequest('flowOptions', contents); obj.riverCheckbox.checked = true;
    });
    obj.invalidDriverBtn.addEventListener('click', async () => { 
        const layerChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
        if (!layerChecker.exist) { alert('Please upload/create a river layer first.'); return; }
        const content = ['Segment ID','Width','Depth'];
        deleteTable(obj.invalidRiverTable); addRowToTable(obj.invalidRiverTable, content);
        await sendRequest('flowOptions', { key: 'invalidCheck', layerKey: 'riverLayer_Vector', type: 'river' });
    });
    obj.riverDeleteBtn.addEventListener('click', async () => {
        const riverChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
        if (!riverChecker.exist) { alert('Please upload/create a river layer first.'); return; }
        const data = getDataFromTable(obj.invalidRiverTable, true).rows, id = obj.inValidDiverIds.value;
        if (data.length === 0) { alert('Please select a segment of the river on map to delete.'); return; }
        await sendRequest('flowOptions', { 
            key: 'deleteItem', layerKey: 'riverLayer_Vector', id: id, type: 'river' 
        });
        const selectData = data.filter(v => Number(v[0]) !== Number(id));
        const firstValues = selectData.map(arr => arr[0]);
        obj.inValidDiverIds.textContent = '';
        firstValues.forEach(id => {
            const option = document.createElement('option');
            option.value = id; option.textContent = id;
            obj.inValidDiverIds.appendChild(option);
        });
        deleteTable(obj.invalidRiverTable); addRowToTable(obj.invalidRiverTable, ['Segment ID','Width','Depth']);
    });
    obj.assignRiverBtn.addEventListener('click', async () => { 
        const riverChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
        if (!riverChecker.exist) { alert('Please upload/create a river layer first.'); return; }
        const data = getDataFromTable(obj.invalidRiverTable, true).rows;
        if (data.length === 0) { alert('Please select a segment of the river on map to edit.'); return; }
        const id = obj.inValidDiverIds.value;
        const selectData = data.filter(v => Number(v[0]) === Number(id));
        if (selectData.length === 0) { alert(`Cannot find the selected segment '${id}' in the table.`); return; }
        if (selectData[0].some(v => !v.trim() || Number.isNaN(Number(v)))) {
            alert('Values in the table must be numeric.'); return;
        }
        const response = await sendRequest('flowOptions', { 
            key: 'assignType', layerKey: 'riverLayer_Vector', id: id, data: selectData[0], type: 'river' 
        });
        obj.inValidDiverIds.textContent = '';
        response.ids.forEach(id => {
            const option = document.createElement('option');
            option.value = id; option.textContent = id;
            obj.inValidDiverIds.appendChild(option);
        });
        deleteTable(obj.invalidRiverTable); fillTable(response.data, obj.invalidRiverTable, true);
    });
    obj.saveRiverProjectBtn.addEventListener('click', async () => { 
        const name = obj.projectName.value.trim();
        if (!name || name.trim() === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const layer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'riverLayer_Vector' });
        if (layer.data === null) { alert('Layer is empty. Please upload/create a river layer first.'); return; }
        const dataRows = getDataFromTable(obj.validRiverTable, true);
        if (dataRows.rows.length === 0) { alert('No valid segments found. Please check the valid table.'); return; }
        const segments = dataRows.rows.map(row => Number(row[0]));
        signalSender('showOverlay', 'Saving river layer to project. Please wait...');
        const content = { projectName: currentProject, flowName: name, data: layer.data, segments: segments };
        const data = await jsonLoader('river_saver', content);
        signalSender('hideOverlay'); alert(data.message);
    });
    obj.saveRiverFileBtn.addEventListener('click', async () => { 
        const riverChecker = await sendRequest('flowOptions', { key: 'layerChecker', layerKey: 'riverLayer_Vector' });
        if (!riverChecker.exist) { alert('Please upload/create a river layer first.'); return; }
        const layer = await sendRequest('flowOptions', { key: 'getLayer', layerKey: 'riverLayer_Vector' });
        if (layer.data === null) { alert('Layer is empty. Please upload/create a river layer first.'); return; }
        const dataRows = getDataFromTable(obj.validRiverTable, true);
        if (dataRows.rows.length === 0) { alert('No valid segments found. Please check the valid table.'); return; }
        const segments = dataRows.rows.map(row => Number(row[0]));
        const selectedSet = new Set(segments);
        const filterObj = {...layer,
            data:{
                ...layer.data,
                features: layer.data.features.filter(
                    feature => selectedSet.has(feature.properties?.description)
                )
            }
        }
        await geoJSONExporter(filterObj.data, 'river.geojson');
    });
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
            if (startTime === '') { alert('Please select a start date first.'); return; }
            if (endTime === '') { alert('Please select an end date first.'); return; }
            const statusRes = await jsonLoader('check_download_status', {projectName: currentProject});
            if (statusRes.status === "running") { alert("Weather download is already running."); return; }
            obj.weatherLog.value = '';
            const content = { 
                projectName: currentProject, flowName: name,
                data: data.data, start: startTime, end: endTime
            };
            const start = await jsonLoader('start_download_weather', content);
            if (start.status === "error") { alert(start.message); return; }
            updateLog(currentProject, obj.weatherLog, 2, 'weather', async () => {
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
        signalSender('showOverlay', 'Generating weather data.\nPlease wait...');
        const content = { 
            projectName: currentProject, flowName: name, data: data
        };
        const request = await jsonLoader('save_flow_weather', content);
        signalSender('hideOverlay'); alert(request.message);
    });
}

function windowListener() {
    // Check whether map widget exists
    const layout = localStorage.getItem('grid-layout');
    const hasMap = layout ? JSON.parse(layout).some(item => item.id === flowId):false;
    const content = { id: flowId, title: 'Flow Estimation Map' };
    if (!hasMap) signalSender('addMapWidget', content);
    window.addEventListener('message', (e) => {
        if (e.data?.type === 'updateUIDelay') {
            const content = e.data.content;
            if (content.key === 'river') { 
                const inValidIds = obj.inValidDiverIds;
                const invalidTable = obj.invalidRiverTable;
                const validTable = obj.validRiverTable;
                inValidIds.textContent = '';
                content.invalidIDs.forEach(id => {
                    const option = document.createElement('option');
                    option.value = id; option.textContent = id;
                    inValidIds.appendChild(option);
                });
                deleteTable(invalidTable); deleteTable(validTable);
                content.inValidData.forEach(row => { fillTable([row], invalidTable, false); });
                content.validData.forEach(row => { fillTable([row], validTable, false); });
            };
            signalSender('hideOverlay');
        }
    });
}