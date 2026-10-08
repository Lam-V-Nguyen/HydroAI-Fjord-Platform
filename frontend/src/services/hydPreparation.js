import { setupTabs } from "./tabManager.js";
import { getLastTimeZone } from "./constant.js";
import { getUser, signalSender, iframeConnector, updateLog, deleteTable,
    jsonLoader, fillTable, getDataFromTable, saveCSV, formatDate, addDataToTable
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
    dischargeTable: $('discharge-table'),




    sourceLocation: $('hyd-source-picker-btn'), sourceLat: $('hyd-source-lat'), 
    sourceLon: $('hyd-source-lon'), sourceTable: $('hyd-source-table'), 
    sourceSave: $('hyd-source-save-btn'), 



    meteoLocation: $('meteo-picker-btn'), meteoLat: $('meteo-lat'), meteoLon: $('meteo-lon'),
    meteoStart: $('hyd-meteo-start-date'), meteoEnd: $('hyd-meteo-end-date'),
    meteoDownload: $('meteo-download-btn'), meteoLog: $('meteo-text'), 
    meteoTable: $('meteo-table'), meteoSave: $('meteo-save-btn'), 
    
    
    
    
    weatherLat: $('weather-lat'), weatherLon: $('weather-lon'), weatherLocation: $('weather-picker-btn'),
    weatherSource: $('hyd-weather-station'), weatherDownload: $('weather-download-btn'), 
    weatherLog: $('weather-text'), weatherTable: $('weather-table'), weatherSave: $('weather-save-btn')
}

let currentProject, nveLayer = null, nveSelected = false, picker = '', mapContainer = null;

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
        const nameID = obj.sourceNVEAPIKey.value;
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
    obj.sourceBtn.addEventListener('click', async () => {
        const apiKey = obj.sourceAPIKey.value;
        if (apiKey === '') { alert('Please enter your NVE API key.'); return; }
        signalSender('showOverlay', 'Getting stations from NVE. Please wait...');
        const content = { projectName: currentProject, key: 'nve', clientName: apiKey };
        const data = await jsonLoader('stations_nve', content); signalSender('hideOverlay');
        if (data.status === 'error') { alert(data.message); return; }
        nveLayer = clearMap(nveLayer, mapObj);
        const contents = {
            getSelectedLayer: () => nveLayer, 
            setSelectedLayer: (layer) => { nveLayer = layer; },
            getSelected: () => nveSelected, table: null, label: null,
            key: 'data-preparation', params: {
                stationID: obj.stationID, stationName: obj.stationName, basinArea: obj.basinArea
            }
        }
        nveLayer = await pointPloter('nve', data.content.point, mapObj, contents);
    });
    obj.downloadBtn.addEventListener('click', async () => {
        const apiKey = obj.sourceAPIKey.value;
        if (!apiKey || apiKey === '') { alert('Please enter your NVE API key.'); return; }
        const stationID = obj.stationID.value, basinArea = obj.basinArea.value;;
        if (stationID === '') { alert('Please select a station from NVE first.'); return; }
        if (basinArea === '') { alert('Please enter the basin area.'); return; }
        const start = obj.sourceStart.value, end = obj.sourceEnd.value;
        if (start === '' || end === '') { alert('Please select start/end date(s).'); return; }
        obj.dischargeContainer.style.display = 'block'; obj.dischargeLogText.value = '';
        try {
            const statusRes = await jsonLoader('check_download_status', { projectName: currentProject, key: 'nve' });
            if (statusRes.status === "running") { alert("NVE download is running."); return; }
            const contents = {
                projectName: currentProject, api_key: apiKey, ids: [[stationID]], 
                interval: 60, startTime: start, endTime: end, timeZone: getLastTimeZone(),
                variables: ['1001'], columns: ['Discharge (m³/s)']
            };
            const data = await jsonLoader('download_nve', contents);
            if (data.status === 'error') { alert(data.message); return; }
            updateLog(currentProject, obj.dischargeLogText, 2, 'nve', async () => {
                alert('Downloading weather completed.');
                const content_csv = { 
                    projectName: currentProject, fileName: 'nve_data.csv', ignore_stationName: true
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






    // iframeConnector(obj.sourceLocation, [obj.sourceLat, obj.sourceLon], 'pickLatLon');
    // obj.sourceSave.addEventListener('click', async () => {
    //     const lat = obj.sourceLat.value, lon = obj.sourceLon.value;
    //     if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
    //     const latNew = Number(lat).toFixed(17), lonNew = Number(lon).toFixed(17)
    //     const data = getDataFromTable(obj.sourceTable, true);
    //     if (data.rows.length === 0) {alert('No data found in the table.'); return;}
    //     try {
    //         const header = [
    //             latNew,lonNew,'','','','\nTime [yyyy/MM/dd HH:mm:ss]',
    //             'Discharge [m3/s]','Salinity [ppt]','Temperature [°C]','Contaminant [kg/m3]'
    //         ];
    //         await saveCSV('source.csv', header, data.rows);
    //         alert(`Save file successfully.`);
    //     } catch (e) { alert(e);}
    // });
}

function meteoManagement() {
    // // Update location
    // iframeConnector(obj.meteoLocation, [obj.meteoLat, obj.meteoLon], 'pickLatLon');
    // obj.meteoDownload.addEventListener('click', async () => {
    //     const lat = obj.meteoLat.value, lon = obj.meteoLon.value, key = 'meteo';
    //     if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
    //     const start = obj.meteoStart.value, end = obj.meteoEnd.value;
    //     if (start === '' || end === '') { alert('Please select start/end date(s).'); return; }
    //     const keyChecker = 'meteo_log'; 
    //     const contentChecker = {projectName: currentProject, key: keyChecker};
    //     const statusRes = await jsonLoader('check_download_status', contentChecker);
    //     if (statusRes.status === "running") { alert("Meteo download is running."); return; }
    //     obj.meteoLog.value = '';
    //     const content = { 
    //         projectName: currentProject, lat: lat, lon: lon,
    //         start: start, end: end, key: key, timeZone: getLastTimeZone()
    //     };
    //     const request = await jsonLoader('start_meteo', content);
    //     if (request.status === 'error') { alert(request.message); return; }
    //     updateLog(currentProject, obj.meteoLog, 2, keyChecker, async () => {
    //         const res =  { projectName: currentProject, fileName: `${key}.csv` };
            // signalSender('showOverlay', 'Uploading meteological data to table. Please wait...');
    //         const weather = await jsonLoader('get_result', res);
            // signalSender('hideOverlay');
    //         if (weather.status === 'error') { alert(weather.message); return; }
    //         fillTable(weather.content, obj.meteoTable);
    //         alert('Downloading meteo data completed.');
    //     });
    // });
    // obj.meteoSave.addEventListener('click', async () => {
    //     const data = getDataFromTable(obj.meteoTable, true);
    //     if (data.rows.length === 0) {alert('No meteo observation found.'); return;}
    //     try {
    //         const header = [
    //             'Time [yyyy/MM/dd HH:mm:ss]','Humidity [%]','Air temperature [°C]',
    //             'Cloud coverage [%]','Solar radiation [W/m2]'
    //         ];
    //         await saveCSV('meteo.csv', header, data.rows);
    //         alert(`Save file successfully.`);
    //     } catch (e) { alert(e);}
    // });
}

function weatherManagement() {
    obj.weatherLocation.addEventListener('click', () => { picker = 'weather'; });
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
                const wind = await jsonLoader('upload_weather_csv', res);
                signalSender('hideOverlay');
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
        if (picker === 'weather') {
            const html = `Click on map to select location.`;
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            map.openTooltip(hoverTooltip); mapContainer.style.cursor = "crosshair";
    //     } else if (era5Checked) {
    //         map.getContainer().style.cursor = "crosshair";
    //         const html = `Select average location.`;
    //         hoverTooltip.setLatLng(e.latlng).setContent(html);
    //         map.openTooltip(hoverTooltip);
    //     } else { if (hoverTooltip) map.closeTooltip(hoverTooltip); 
        }
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
            obj.weatherLat.value = e.latlng.lat; obj.weatherLon.value = e.latlng.lng;
            picker = ''; hoverTooltip.closeTooltip(); 
        }
        mapContainer.style.cursor = "";
    });
    // map.on('contextmenu', async function (e) {
    //     e.originalEvent.preventDefault();
    //     if (!plotChecked) {
    //         const tableData = getDataFromTable(obj.stationSelectedTable, true);
    //         if (!tableData || !tableData.rows || tableData.rows.length === 0) return;
    //         // Remove the last station
    //         const newRows = tableData.rows.slice(0, -1);
    //         fillTable(newRows, obj.stationSelectedTable, true);
    //     }
    // });
}
function clearMap(layer, map) {
    if (layer) { map.removeLayer(layer); }
    return null;
}