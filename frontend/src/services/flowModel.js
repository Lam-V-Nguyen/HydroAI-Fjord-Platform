import { setupTabs } from "./tabManager.js";
import { getUser, signalSender, getProjectList, jsonLoader, 
    updateLog, fillTable, getDataFromTable, nameChecker, displayTerrain
} from "./commonFunctions.js";
import { projectRender } from "./projectManager.js";
import { CENTER, ZOOM, getLastTimeZone } from "./constant.js";
import { initMap } from "./visualizationMap.js";

const hoverTooltip = L.tooltip({
    permanent: false, direction: 'bottom',
    sticky: true, offset: [0, 10], className: 'custom-tooltip'
});

const $ = (id) => document.getElementById(id);
const obj = {
    projectList: $('project-list'), projectName: $('project-name'), projectOpener: $('open-btn'),
    modelInterval: $('model-step'), modelStart: $('model-start'), modelEnd: $('model-end'),
    upstreamArea: $('upstream-area'), upstreamBtn: $('upstream-check-btn'), 
    upstreamCheckbox: $('upstream-checkbox'), modelLat: $('model-lat'), modelLon: $('model-lon'),
    
    
    
    modelCheckBtn: $('model-check-btn'), modelLog: $('model-log'), modelRunBtn: $('model-run-btn')




    // modelPourpointBtn: $('model-pourpoint-btn'), 
    // pourpointFile: $('model-pourpoint-file'), 
    // pointStream: $('stream-points'), pointStreamBtn: $('stream-points-btn'),
    // pointStreamTable: $('stream-points-table'), pointSelected: $('stream-points-selected'),
    
}
const intervalOption = {'1h': 3600, '1d': 86400, '1w': 604800, '1ME': 18144000};

let currentProject, mapLayer = null, layerChecker = false, pointLayer = null;


setupTabs(document); await getProject();
const mapObj = await initMap('leaflet-map-flow-checking'); 
mapOptions(mapObj); modelManager();


async function getProject() { 
    const userName = await getUser(); currentProject = userName.split('/').pop();
    const respond = await getProjectList(`${currentProject}/flows`, '');
    await projectRender(obj.projectName, obj.projectList, respond);
}

function modelManager() {
    // Toogle between tabs
    document.querySelectorAll('#sub-main-tabs').forEach(tab => {
        tab.addEventListener('click', () => { autoResize(obj.modelLog); });
    });



    obj.projectOpener.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (!name || name === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const content = { projectName: currentProject, flowName: name };
        signalSender('Reading forcing data to get start and end dates.\nPlease wait...');
        const data = await jsonLoader('flow_project', content); signalSender('hideOverlay');
        if (data.status === 'error') { alert(data.message); return; }
        const forcing = data.content['forcing'];
        obj.modelStart.value = forcing.start; obj.modelEnd.value = forcing.end;
        obj.modelInterval.value = intervalOption[forcing.interval];
    });
    obj.upstreamBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim(), area = obj.upstreamArea.value.trim();
        if (!name || name === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        if (!area || area === '') { alert('Please define area of upstream.'); return; }
        try {
            const content = { projectName: currentProject, flowName: name, area: area };
            const request = await jsonLoader('upstream_area', content);
            if (request.status === 'error') { alert(request.message); return; }
            if (mapLayer) { mapLayer = mapObj.removeLayer(mapLayer); mapLayer = null; }
            mapLayer = await displayTerrain(mapObj, request.content.tile_url, request.content.bounds);
        } catch (error) { alert(`Getting upstream area failed: ${error.message}`); }
    });
    obj.upstreamCheckbox.addEventListener('change', async (e) => { layerChecker = e.target.checked; });
    obj.modelCheckBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim(), key = 'wflow_check';
        if (!name || name === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const upstreamArea = obj.upstreamArea.value;
        if (upstreamArea === '') { alert('Please specify area of upstream.'); return; }
        try {
            const content = { 
                projectName: currentProject, flowName: name, key: 'check', 
                keyChecker: key, timeZone: getLastTimeZone()
            };
            const request = await jsonLoader('wflow_model', content);
            if (request.status === 'error') { alert(request.message); return; }
            autoResize(obj.modelLog);
        } catch (error) { alert(`Checking model parameters failed: ${error.message}`); }
    });
    // obj.modelPourpointBtn.addEventListener('click', () => obj.pourpointFile.click());
    // obj.pourpointFile.addEventListener('change', async (e) => {
    //     const file = e.target.files[0]; if (!file) return; 
    //     const formData = new FormData(); formData.append('file', file);
    //     const name = obj.projectName.value;
    //     if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
    //     formData.append('flowName', name); formData.append('projectName', currentProject);
    //     try {
    //         signalSender('showOverlay', 'Uploading pourpoint data. Please wait...');
    //         const response = await fetch('/geojson_upload', { method: 'POST', body: formData });
    //         const data = await response.json(); signalSender('hideOverlay');
    //         if (data.status === 'error') { alert(data.message); return; }
    //         const coords = data.content["features"][0]["geometry"]["coordinates"]
    //         obj.modelLat.value = coords[1]; obj.modelLon.value = coords[0];
    //     } catch (error) { alert(`Uploading pourpoint failed: ${error.message}`); }
    //     finally { e.target.value = ''; }
    // });
    // obj.pointStreamBtn.addEventListener('click', async () => {
    //     const name = obj.projectName.value;
    //     if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
    //     const lat = obj.modelLat.value, lon = obj.modelLon.value;
    //     if (lat === '' || lon === '') { alert('Please add a pourpoint first.'); return; }
    //     signalSender('showOverlay', 'Getting number of stream points from strord data.\nPlease wait...');
    //     const content = { 
    //         projectName: currentProject, flowName: name, lat: lat, lon: lon,
    //     };
    //     const request = await jsonLoader('check_stream_points', content);
    //     signalSender('hideOverlay');
    //     if (request.status === 'error') { alert(request.message); return; }
    //     obj.pointStream.value = request.content.points;
    //     fillTable(request.content.data, obj.pointStreamTable, true);
    //     obj.pointSelected.value = request.content.selected;
    // });
    obj.modelRunBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim(), keyChecker = 'wflow_run';
        if (!name || name === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const start = obj.modelStart.value, end = obj.modelEnd.value;
        if (start === '' || end === '') { alert('Please select a start and end date.'); return; }
        const upstreamArea = obj.upstreamArea.value;
        if (upstreamArea === '') { alert('Please specify area of upstream.'); return; }
        try {
            const contentCheck = { projectName: currentProject, key: keyChecker };
            const statusRes = await jsonLoader('check_download_status', contentCheck);
            if (statusRes.status === "running") { alert("Running Wflow model is in progress."); return; }
        //     const lat = obj.modelLat.value, lon = obj.modelLon.value;
        //     if (lat === '' || lon === '') { alert('Please add a pourpoint first.'); return; }
        //     const pointTotal = getDataFromTable(obj.pointStreamTable, true);
        //     if (pointTotal.rows.length === 0) {
        //         alert("No stream point found. Please hit the button 'Stream Points' first."); return; 
        //     }
        //     const pointCount = obj.pointSelected.value;
        //     if (pointCount === '') {
        //         alert("No candidate points selected. Please specify nearnest point to the pourpoint first."); return; 
        //     }
        //     const result = pointTotal.rows.slice(0, Number(pointCount));
            const params_in = Object.fromEntries(
                [...document.querySelectorAll(".input-parameters input")].map(input => [input.id, Number(input.value)])
            );
            const params_out = Object.fromEntries(
                [...document.querySelectorAll(".output-parameters input")].map(input => [input.id, input.checked])
            );
            const content = { 
                projectName: currentProject, flowName: name, key: 'run', 
                start: start, end: end, timeZone: getLastTimeZone(),
                keyChecker: keyChecker, step: obj.modelInterval.value,
                upArea: upstreamArea, 
                // points: result, lat: lat, lon: lon, 
                params_input: params_in, params_output: params_out
            };
            const request = await jsonLoader('wflow_model', content); obj.modelLog.value = '';
            if (request.status === 'error') { alert(request.message); return; }
            updateLog(currentProject, obj.modelLog, 3, keyChecker, async () => {
                alert('Running Wflow model completed.'); 
            }, true);
        } catch (error) { alert(`Running Wflow model failed: ${error.message}`); }
    });
}

function mapOptions(map) {
    const mapElement = map.getContainer();
    const mapContainer = mapElement.parentElement;
    if (map._resizeObserver) {map._resizeObserver.disconnect();}
    map._resizeObserver = new ResizeObserver(() => {
        if (mapContainer.clientWidth > 0 && mapContainer.clientHeight > 0) {
            map.invalidateSize({ pan: false });
        }
    });
    map._resizeObserver.observe(mapContainer); 
    requestAnimationFrame(() => {
        map.invalidateSize({ pan: false }); map.setView(CENTER, ZOOM, { animate: false });
    });
    map.on('mousemove', function (e) {
        if (layerChecker) {
            mapElement.style.cursor = 'crosshair';
            hoverTooltip.setLatLng(e.latlng).setContent('Select point.');
            map.openTooltip(hoverTooltip);
        } else {
            map.closeTooltip(hoverTooltip); mapElement.style.cursor = '';
        }
    });
    map.on('click', async function (e) {
        if (layerChecker) {
            const lat = Number(e.latlng.lat).toFixed(8), lon = Number(e.latlng.lng).toFixed(8);
            obj.modelLat.value = lat; obj.modelLon.value = lon;
            if (pointLayer) { mapObj.removeLayer(pointLayer); }
            pointLayer = L.circleMarker(e.latlng, {
                radius: 4, fillColor: 'blue', color: 'red', weight: 2, opacity: 1, fillOpacity: 1
            }).addTo(mapObj);
            layerChecker = false; mapElement.style.cursor = ''; obj.upstreamCheckbox.checked = false;
        }
    });
}

function autoResize(objElement) {
    objElement.style.height = 'auto';
    objElement.style.height = `${objElement.scrollHeight}px`;
}