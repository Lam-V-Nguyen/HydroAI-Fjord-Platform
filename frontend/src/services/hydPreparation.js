import { setupTabs } from "./tabManager.js";
import { getLastTimeZone } from "./constant.js";
import { getUser, signalSender, updateLog, deleteTable, jsonLoader,
    getDataFromTable, saveCSV, formatDate, addDataToTable, 
    addRowToTable, drawColorbar, displayTerrain, saveFileSmart
} from "./commonFunctions.js";
import { initMap, pointPloter } from "./visualizationMap.js";

const hoverTooltip = L.tooltip({
    permanent: false, direction: 'bottom',
    sticky: true, offset: [0, 10], className: 'custom-tooltip'
});

const $ = (id) => document.getElementById(id);
const obj = {
    sourceRemember: $('nve-remember-btn'), sourceAPIKey: $('nve-client-id'),
    sourceBtn: $('nve-stations-btn'), sourceStart: $('nve-start'), sourceEnd: $('nve-end'),
    stationID: $('station-id'), stationName: $('station-name'), basinArea: $('basin-area'), 
    downloadBtn: $('nve-download-btn'), dischargeContainer: $('discharge-container'),
    dischargeLogText: $('discharge-log-text'), dischargeLogContainer: $('discharge-log-container'),
    dischargeTable: $('discharge-table'), sourceLocation: $('hyd-source-picker-btn'), 
    sourceLat: $('hyd-source-lat'), sourceLon: $('hyd-source-lon'), colorBar: $('custom-colorbar'),
    sourceInitTemp: $('hyd-source-temperature'), sourceInitSalinity: $('hyd-source-salinity'),
    sourceDrawBtn: $('hyd-source-draw-btn'), sourceTopLeft: $('hyd-source-top-left'), 
    sourceBottomRight: $('hyd-source-bottom-right'), sourceDEM: $('hyd-source-terrain-download-btn'), 
    sourceDEMResolution: $('hyd-source-terrain-resolution'),
    sourceThreshold: $('hyd-source-threshold'), sourceFlowBtn: $('hyd-source-flow-btn'),
    sourceArea: $('hyd-source-area'), sourceContainer: $('hyd-source-container'),
    sourceComputeBtn: $('hyd-source-compute-btn'), sourceTable: $('hyd-source-table'), 
    sourceSave: $('hyd-source-save-btn'), meteoLocation: $('meteo-picker-btn'), 
    meteoLat: $('meteo-lat'), meteoLon: $('meteo-lon'), meteoSource: $('hyd-meteo-station'), 
    meteoTable: $('meteo-table'), meteoLog: $('meteo-log-text'), meteoDownload: $('meteo-download-btn'), 
    meteoSave: $('meteo-save-btn'), meteoLogContainer: $('meteo-log-container'),
    weatherLocation: $('weather-picker-btn'), weatherLat: $('weather-lat'), weatherLon: $('weather-lon'), 
    weatherSource: $('hyd-weather-station'), weatherDownload: $('weather-download-btn'), 
    weatherLog: $('weather-text'), weatherTable: $('weather-table'), weatherSave: $('weather-save-btn')
}

let currentProject, nveLayer = null, nveSelected = false, picker = '', mapContainer = null,
    pointCollections = [], drawChecked = false, currentPolygon = null, polygonMarkers = [],
    demLayer = null, streamLayer = null, subbasinLayer = null, pointLayer = null, catchmentLayer = null;

setupTabs(document); await getProject();
const mapObj = await initMap('leaflet-map-hyd-preparation');
nveSourceManagement(); sourceManagement(); meteoManagement(); 
weatherManagement(); mapOptions(mapObj);

async function getProject() { 
    const userName = await getUser(); currentProject = userName.split('/').pop();
}

function savePassword() {
    document.querySelectorAll('.toggle-password').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            const input = this.parentElement.querySelector('input');
            if (!input) { return; }
            if (input.type === 'password') {
                input.type = 'text'; this.textContent = '🙈';
            } else {
                input.type = 'password'; this.textContent = '👁️';
            }
        });
    });
    obj.sourceRemember.addEventListener('click', async () => {
        const nameID = obj.sourceAPIKey.value;
        if (nameID === '') {
            alert('Please add NVE API Key and try again.\nInformation is NOT saved.'); return;
        }
        const content = { projectName: currentProject, key: 'nve' };
        const response = await jsonLoader('save_client', content);
        alert(response.message); if (response.status === "error") { return; }
    });
}
async function loadClient(key) {
    const content = { projectName: currentProject, key: key };
    const response = await jsonLoader('load_client', content);
    obj.sourceAPIKey.value = response.content.client_id;
}

async function nveSourceManagement(){
    savePassword(); await loadClient('nve');
    const now = new Date(); now.setHours(0, 0, 0, 0);
    const start = new Date(now); start.setDate(start.getDate() - 15);
    const end = new Date(now); end.setDate(end.getDate() - 2);
    obj.sourceStart.value = formatDate(start);
    obj.sourceEnd.value = formatDate(end);
    // Toggle sub tabs
    document.querySelectorAll('[data-tab]').forEach(tab => {
        tab.addEventListener('click', async () => {
            const tabName = tab.getAttribute('data-tab');
            if (tabName !== 'hyd-tab-2') {
                polygonMarkers.forEach(marker => marker.remove()); polygonMarkers = [];
                if (currentPolygon && currentPolygon !== null) { 
                    currentPolygon.remove(); currentPolygon = null; 
                }
            }
            setTimeout(() => { mapObj.invalidateSize(); }, 10);
            mapObj.closeTooltip(hoverTooltip);
        });
    });
    obj.sourceBtn.addEventListener('click', async () => {
        if (nveLayer !== null) { 
            if (!mapObj.hasLayer(nveLayer)) { nveLayer.addTo(mapObj); }
            picker = ''; mapContainer.style.cursor = ""; return;
        }
        const apiKey = obj.sourceAPIKey.value;
        if (apiKey === '') { alert('Please enter your NVE API key.'); return; }
        signalSender('showOverlay', 'Getting stations from NVE. Please wait...');
        const content = { projectName: currentProject, key: 'nve', clientName: apiKey };
        const data = await jsonLoader('stations_nve', content); signalSender('hideOverlay');
        if (data.status === 'error') { alert(data.message); return; }
        const contents = {
            getSelectedLayer: () => nveLayer, 
            setSelectedLayer: (layer) => { nveLayer = layer; },
            getSelected: () => nveSelected, table: null, label: null, key: 'data-preparation', 
            params: { stationID: obj.stationID, stationName: obj.stationName, basinArea: obj.basinArea }
        }
        nveLayer = clearMap(nveLayer, mapObj);
        nveLayer = await pointPloter('nve', data.content.point, mapObj, contents);
    });
    obj.downloadBtn.addEventListener('click', async () => {
        const apiKey = obj.sourceAPIKey.value, key = 'nve';
        if (!apiKey || apiKey === '') { alert('Please enter your NVE API key.'); return; }
        const stationID = obj.stationID.value;
        if (stationID === '') { alert('Please select a station from NVE first.'); return; }
        const start = obj.sourceStart.value, end = obj.sourceEnd.value;
        if (start === '' || end === '') { alert('Please select start/end date(s).'); return; }
        obj.dischargeContainer.style.display = 'block'; obj.dischargeLogText.value = '';
        try {
            const contentChecker = {projectName: currentProject, key: key};
            const statusRes = await jsonLoader('check_download_status', contentChecker);
            if (statusRes.status === "running") { alert("NVE data download is running."); return; }
            const contents = {
                projectName: currentProject, api_key: apiKey, ids: [[stationID]], 
                interval: 60, startTime: start, endTime: end, timeZone: getLastTimeZone(),
                variables: ['1001'], columns: ['Discharge (m³/s)'], key: key
            };
            const data = await jsonLoader('download_nve', contents);
            if (data.status === 'error') { alert(data.message); return; }
            updateLog(currentProject, obj.dischargeLogText, 2, key, async () => {
                alert('Downloading discharge data completed.');
                const content_csv = { 
                    projectName: currentProject, fileName: `${key}.csv`, ignore_stationName: true
                };
                const csv = await jsonLoader('upload_weather_csv', content_csv);
                if (csv.status === 'error') { 
                    alert(csv.message); deleteTable(obj.dischargeTable); return; 
                }
                addDataToTable(obj.dischargeTable, csv.columns, csv.content);
                obj.dischargeLogContainer.style.display = 'none';
                obj.dischargeTable.style.display = 'table';
            });
        } catch (error) {
            alert(error.message || error); 
            obj.dischargeLogContainer.style.display = 'flex';
            obj.dischargeTable.style.display = 'none'; return;
        }
    });
}

async function sourceManagement() {
    obj.sourceDrawBtn.addEventListener('click', () => { 
        picker = 'source-draw'; pointCollections = [];
        drawChecked = true; demLayer = clearMap(demLayer, mapObj);
        if (currentPolygon && currentPolygon !== null) { 
            currentPolygon.remove(); currentPolygon = null; 
        }
        polygonMarkers.forEach(marker => marker.remove()); polygonMarkers = [];
        pointLayer = clearMap(pointLayer, mapObj); catchmentLayer = clearMap(catchmentLayer, mapObj);
        if (nveLayer && mapObj.hasLayer(nveLayer)) { mapObj.removeLayer(nveLayer); }
    });
    obj.sourceDEM.addEventListener('click', async () => { 
        if (obj.colorBar) { obj.colorBar.style.display = 'none'; }
        const resolution = obj.sourceDEMResolution.value, key = 'dem';
        const topLeft = obj.sourceTopLeft.value, bottomRight = obj.sourceBottomRight.value;
        if (topLeft === '' || bottomRight === '') { alert('Please define the area on map first.'); return; }
        try {
            const content = { projectName: currentProject, resolution: resolution, 
                topLeft: topLeft, bottomRight: bottomRight, key: key, folder: 'dems'
            };
            signalSender('showOverlay', 'Downloading DEM for the selected area. Please wait...');
            const request = await jsonLoader('download_dem', content); signalSender('hideOverlay');
            if (request.status === 'error') { alert(request.message); return; }
            polygonMarkers.forEach(marker => marker.remove()); polygonMarkers = [];
            if (currentPolygon && currentPolygon !== null) { 
                currentPolygon.remove(); currentPolygon = null;
            }
            signalSender('showOverlay', 'Uploading terrain data.\nPlease wait...');
            const formData = new FormData(); formData.append('projectName', currentProject);
            formData.append('folder', `${key}s`); formData.append('fileName', key); 
            const response = await fetch('/upload_terrain', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            demLayer = await displayTerrain(mapObj, data.content.tile_url, data.content.bounds);
            await drawColorbar(obj.colorBar, data.content.min_max, 'DEM', 'terrain');
        } catch (error) { `Downloading DEM failed: ${error.message}`; }
    });
    obj.sourceFlowBtn.addEventListener('click', async () => { 
        const threshold = obj.sourceThreshold.value, key = 'dem';
        if (threshold === '') { alert('Please define threshold to detect streams.'); return; }
        if (demLayer === null) { alert('Please download terrain data first.'); return; }
        try {
            signalSender('showOverlay', 'Detecting streams. Please wait ...');
            const contents = { 
                projectName: currentProject, folder: `${key}s`, fileName: key, threshold: threshold
            };
            const data = await jsonLoader('hyd_stream_upload', contents); signalSender('hideOverlay');
            if (data.status === "error") { alert(data.message); return; }
            demLayer = clearMap(demLayer, mapObj); streamLayer = clearMap(streamLayer, mapObj);
            streamLayer = await displayTerrain(mapObj, data.content.tile_url, data.content.bounds);
            await drawColorbar(obj.colorBar, data.content.min_max, 'Stream', 'terrain');
        } catch (error) { alert(`Detecting streams failed: ${error.message}`); }
    });
    obj.sourceLocation.addEventListener('click', () => { 
        if (streamLayer === null) { alert('Please detect streams first.'); return; }
        if (subbasinLayer !== null) { subbasinLayer = clearMap(subbasinLayer, mapObj); }
        picker = 'source'; obj.sourceContainer.style.display = 'none';
    });
    obj.sourceComputeBtn.addEventListener('click', async () => {
        const lat = obj.sourceLat.value, lon = obj.sourceLon.value;
        if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
        const subArea = obj.sourceArea.value;
        if (subArea === '') { 
            alert('Selected hydrological source is not appropriate. Please select another source.'); return; 
        }
        const start = obj.sourceStart.value, end = obj.sourceEnd.value;
        if (start === '' || end === '') { alert('Please select start/end date(s).'); return; }
        const dischargeData = getDataFromTable(obj.dischargeTable, true);
        if (dischargeData.rows.length === 0) { alert('Please compute discharge first.'); return; }
        const basinArea = obj.basinArea.value;
        if (basinArea === '') { alert('Please define basin station from NVE dataset.'); return; }
        const initTemp = obj.sourceInitTemp.value;
        if (initTemp === '') { alert('Please define initial temperature.'); return; }
        const initSalinity = obj.sourceInitSalinity.value;
        if (initSalinity === '') { alert('Please define initial salinity.'); return; }
        try {
            deleteTable(obj.sourceTable); obj.sourceContainer.style.display = 'block';
            dischargeData.rows.forEach(row => {
                const discharge = Number(row[1]) * Number(subArea) / Number(basinArea);
                const values = [row[0], discharge.toFixed(3), initSalinity, initTemp];
                addRowToTable(obj.sourceTable, values, true);
            });
        } catch (error) { 
            alert(`Computing subbasin failed: ${error.message}`);
            obj.sourceContainer.style.display = 'none'; return;
        }
    });
    obj.sourceSave.addEventListener('click', async () => {
        const lat = obj.sourceLat.value, lon = obj.sourceLon.value;
        if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
        const data = getDataFromTable(obj.sourceTable, true);
        if (data.rows.length === 0) {alert('No data found in the table.'); return;}
        try {
            const content = [[lat, lon, '', '', ''], data.columns, ...data.rows];
            const csv = content.map(row => row.join(',')).join('\n');
            await saveFileSmart(csv, `source_${Number(lat).toFixed(4)}_${Number(lon).toFixed(4)}.csv`);
            alert(`Save file successfully.`);
        } catch (e) { alert(`Failed to save discharge data:\n${e.message}`); }
    });
}

function meteoManagement() {
    obj.meteoLocation.addEventListener('click', () => { picker = 'meteo'; });
    obj.meteoSource.addEventListener('change', () => {
        obj.meteoLog.value = ''; deleteTable(obj.meteoTable);
        const row = ["YYYY-MM-DD HH:MM:SS", "Humidity", 
            "Air temperature", "Cloud coverage", "Solar radiation"];
        addRowToTable(obj.meteoTable, row);
    });
    obj.meteoDownload.addEventListener('click', async () => {
        const lat = obj.meteoLat.value, lon = obj.meteoLon.value;
        const key = 'meteo', dataService = obj.meteoSource.value;
        if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
        const start = obj.sourceStart.value, end = obj.sourceEnd.value;
        if (start === '' || end === '') { alert('Please select start/end date(s).'); return; }
        try {
            const contentChecker = {projectName: currentProject, key: key};
            const statusRes = await jsonLoader('check_download_status', contentChecker);
            if (statusRes.status === "running") { alert("Meteo download is running."); return; }
            obj.meteoLog.value = '';
            const content = { 
                projectName: currentProject, lat: lat, lon: lon, dataService: dataService,
                start: start, end: end, key: key, timeZone: getLastTimeZone()
            };
            const request = await jsonLoader('start_meteo', content);
            if (request.status === 'error') { alert(request.message); return; }
            updateLog(currentProject, obj.meteoLog, 2, key, async () => {
                alert('Downloading meteo data completed.');
                const res = { projectName: currentProject, fileName: `${key}.csv` };
                signalSender('showOverlay', 'Uploading meteological data to table. Please wait...');
                const meteo = await jsonLoader('upload_weather_csv', res); signalSender('hideOverlay');
                if (meteo.status === 'error') { alert(meteo.message); return; }
                addDataToTable(obj.meteoTable, meteo.columns, meteo.content);
                obj.meteoLogContainer.style.display = 'none';
                obj.meteoTable.style.display = 'table';
            });
        } catch (error) {
            alert(error.message || error); return;
        }
    });
    obj.meteoSave.addEventListener('click', async () => {
        const data = getDataFromTable(obj.meteoTable, true);
        if (data.rows.length === 0) {alert('No meteo observation found.'); return;}
        try {
            await saveCSV('meteo.csv', data.columns, data.rows);
            alert(`Save file successfully.`);
        } catch (e) { alert(`Failed to save meteo data:\n${e.message}`);}
    });
}

function weatherManagement() {
    obj.weatherLocation.addEventListener('click', () => { picker = 'weather'; });
    obj.weatherSource.addEventListener('change', () => {
        obj.weatherLog.value = ''; deleteTable(obj.weatherTable);
        addRowToTable(obj.weatherTable, ["YYYY-MM-DD HH:MM:SS", "Wind Speed", "Wind Direction"]);
    });
    obj.weatherDownload.addEventListener('click', async () => {
        const lat = obj.weatherLat.value, lon = obj.weatherLon.value;
        const key = 'wind', dataService = obj.weatherSource.value;
        if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
        const start = obj.sourceStart.value, end = obj.sourceEnd.value;
        if (start === '' || end === '') { alert('Please select start/end date(s).'); return; }
        try {
            const contentChecker = {projectName: currentProject, key: key};
            const statusRes = await jsonLoader('check_download_status', contentChecker);
            if (statusRes.status === "running") { alert("Wind download is running."); return; }
            obj.weatherLog.value = '';
            const content = { 
                projectName: currentProject, lat: lat, lon: lon, dataService: dataService, 
                start: start, end: end, key: key, timeZone: getLastTimeZone()
            };
            const request = await jsonLoader('start_meteo', content);
            if (request.status === 'error') { alert(request.message); return; }
            updateLog(currentProject, obj.weatherLog, 2, key, async () => {
                alert('Downloading wind data completed.');
                const res = { projectName: currentProject, fileName: `${key}.csv` };
                signalSender('showOverlay', 'Uploading weather data to table. Please wait...');
                const wind = await jsonLoader('upload_weather_csv', res); signalSender('hideOverlay');
                if (wind.status === 'error') { alert(wind.message); return; }
                addDataToTable(obj.weatherTable, wind.columns, wind.content);
            });
        } catch (error) {
            alert(error.message || error); return;
        }
    });
    obj.weatherSave.addEventListener('click', async () => {
        const data = getDataFromTable(obj.weatherTable, true);
        if (data.rows.length === 0) {alert('No wind observation found.'); return;}
        try {
            await saveCSV('wind.csv', data.columns, data.rows);
            alert(`Save file successfully.`);
        } catch (e) { alert(`Failed to save wind data:\n${e.message}`);}
    });
}

function mapOptions(map) {
    mapContainer = map.getContainer();
    map.on('mousemove', function (e) {
        if (picker === 'weather' || picker === 'meteo' || picker === 'source') {
            mapContainer.style.cursor = "crosshair";
            const html = `Click on map to select location.`;
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            map.openTooltip(hoverTooltip);
        }
        if (picker === 'source-draw') {
            mapContainer.style.cursor = "crosshair";
            const message = pointCollections.length === 0
                ? 'Draw a polygon on map to define area.'
                : 'Right-click to finish drawing.';
            hoverTooltip.setLatLng(e.latlng).setContent(message);
            map.openTooltip(hoverTooltip);
        }
        if (picker === '') { map.closeTooltip(hoverTooltip);}
    });
    map.on('click', async function (e) {
        if (nveLayer) {
            nveLayer.closeTooltip(); nveLayer.unbindTooltip();
            const layer = nveLayer;
            if (layer._hoverTooltip) {
                layer.bindTooltip(layer._hoverTooltip, {
                    sticky: true, permanent: false,
                    direction: 'bottom', opacity: 1, offset: [0, 10]
                });
            }
            nveLayer = null;
        }
        if (picker === 'weather') {
            obj.weatherLat.value = e.latlng.lat; 
            obj.weatherLon.value = e.latlng.lng;
            picker = ''; hoverTooltip.closeTooltip(); 
        } else if (picker === 'meteo') {
            obj.meteoLat.value = e.latlng.lat; 
            obj.meteoLon.value = e.latlng.lng;
            picker = ''; hoverTooltip.closeTooltip(); 
        } else if (picker === 'source') {
            pointLayer = clearMap(pointLayer, map); const key = 'dem';
            pointLayer = L.circleMarker(e.latlng, {
                radius: 4, fillColor: 'blue', color: 'red', weight: 2, opacity: 1, fillOpacity: 1
            }).addTo(map);
            signalSender('showOverlay', 'Generating catchment. Please wait ...');
            const contents = {
                projectName: currentProject, lat: e.latlng.lat, lon: e.latlng.lng, 
                folder: `${key}s`, fileName: key, snapDistance: 50
            }
            const response = await jsonLoader('catchment_definer', contents); signalSender('hideOverlay');
            if (response.status === "error") { alert(response.message); return; }
            catchmentLayer = clearMap(catchmentLayer, map);
            catchmentLayer = L.geoJSON(response.content, {
                style: { color: 'blue', weight: 2, fillColor: '#10b9d6', fillOpacity: 0.5 }
            }).addTo(map);
            obj.sourceLat.value = e.latlng.lat; obj.sourceLon.value = e.latlng.lng;
            obj.sourceArea.value = response.area; picker = ''; hoverTooltip.closeTooltip();
        } else if (picker === 'source-draw' && drawChecked) {
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
        }
        mapContainer.style.cursor = "";
    });
    map.on('contextmenu', async function (e) {
        if (picker !== 'source-draw' || !drawChecked) return;
        e.originalEvent.preventDefault();
        if (drawChecked) {
            if (pointCollections.length < 3) { alert('At least 3 points are required to create a polygon.'); return; }
            drawChecked = false; picker = ''; mapContainer.style.cursor = ""; hoverTooltip.closeTooltip();
            const bounds = L.latLngBounds(pointCollections);
            obj.sourceTopLeft.value = `(${Number(bounds.getNorth()).toFixed(8)}, ${Number(bounds.getWest()).toFixed(8)})`;
            obj.sourceBottomRight.value = `(${Number(bounds.getSouth()).toFixed(8)}, ${Number(bounds.getEast()).toFixed(8)})`;
        }
    });
}
function clearMap(layer, map) {
    if (layer) { map.removeLayer(layer); }
    return null;
}