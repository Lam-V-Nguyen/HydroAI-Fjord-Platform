import { setupTabs } from "./tabManager.js";
import { projectRender } from "./projectManager.js";
import { hydPrepareMapId } from "./constant.js";
import { 
    getUser, signalSender, iframeConnector, updateLog, 
    jsonLoader, fillTable, getDataFromTable, saveCSV
} from "./commonFunctions.js";

const $ = (id) => document.getElementById(id);
const obj = {
    sourceLocation: $('hyd-source-picker-btn'), sourceLat: $('hyd-source-lat'), 
    sourceLon: $('hyd-source-lon'), sourceTable: $('hyd-source-table'), 
    sourceSave: $('hyd-source-save-btn'), 



    meteoLocation: $('meteo-picker-btn'), meteoLat: $('meteo-lat'), meteoLon: $('meteo-lon'),
    meteoStart: $('hyd-meteo-start-date'), meteoEnd: $('hyd-meteo-end-date'),
    meteoDownload: $('meteo-download-btn'), meteoLog: $('meteo-text'), 
    meteoTable: $('meteo-table'), meteoSave: $('meteo-save-btn'), weatherLon: $('weather-lon'),
    weatherLocation: $('weather-picker-btn'), weatherLat: $('weather-lat'), 
    weatherStart: $('hyd-weather-start-date'), weatherEnd: $('hyd-weather-end-date'),
    weatherDownload: $('weather-download-btn'), weatherLog: $('weather-text'),
    weatherTable: $('weather-table'), weatherSave: $('weather-save-btn')
}

let currentProject;

setupTabs(document); checkMap(); await getProject(); 
sourceManagement(); meteoManagement(); weatherManagement();

async function getProject() { 
    const userName = await getUser(); currentProject = userName.split('/').pop();
}

function checkMap() {
    // Check whether map widget exists
    const layout = localStorage.getItem('grid-layout');
    const hasMap = layout ? JSON.parse(layout).some(item => item.id === hydPrepareMapId):false;
    const content = { id: hydPrepareMapId, title: 'Map for Hydrodynamic Preparation' };
    if (!hasMap) signalSender('addMapWidget', content);
}

function sourceManagement() {
    iframeConnector(obj.sourceLocation, [obj.sourceLat, obj.sourceLon], 'pickLatLon');
    obj.sourceSave.addEventListener('click', async () => {
        const lat = obj.sourceLat.value, lon = obj.sourceLon.value;
        if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
        const latNew = Number(lat).toFixed(17), lonNew = Number(lon).toFixed(17)
        const data = getDataFromTable(obj.sourceTable, true);
        if (data.rows.length === 0) {alert('No data found in the table.'); return;}
        try {
            const header = [
                latNew,lonNew,'','','','\nTime [yyyy/MM/dd HH:mm:ss]',
                'Discharge [m3/s]','Salinity [ppt]','Temperature [°C]','Contaminant [kg/m3]'
            ];
            await saveCSV('source.csv', header, data.rows);
            alert(`Save file successfully.`);
        } catch (e) { alert(e);}
    });
}






function meteoManagement() {
    // Update location
    iframeConnector(obj.meteoLocation, [obj.meteoLat, obj.meteoLon], 'pickLatLon');
    obj.meteoDownload.addEventListener('click', async () => {
        const lat = obj.meteoLat.value, lon = obj.meteoLon.value, key = 'meteo';
        if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
        const start = obj.meteoStart.value, end = obj.meteoEnd.value;
        if (start === '' || end === '') { alert('Please select start/end date(s).'); return; }
        const statusRes = await jsonLoader('check_download_status', {projectName: currentProject});
        if (statusRes.status === "running") { alert("Meteo download is already running."); return; }
        obj.meteoLog.value = '';
        const content = { 
            projectName: currentProject, lat: lat, lon: lon, start: start, end: end, key: key
        };
        const request = await jsonLoader('start_meteo', content);
        if (request.status === 'error') { alert(request.message); return; }
        updateLog(currentProject, obj.meteoLog, 2, 'meteo_log', async () => {
            const res =  { projectName: currentProject, fileName: `${key}.csv` };
            const weather = await jsonLoader('get_result', res);
            if (weather.status === 'error') { alert(weather.message); return; }
            fillTable(weather.content, obj.meteoTable);
            alert('Downloading meteo data completed.');
        });
    });
    obj.meteoSave.addEventListener('click', async () => {
        const data = getDataFromTable(obj.meteoTable, true);
        if (data.rows.length === 0) {alert('No meteo observation found.'); return;}
        try {
            const header = [
                'Time [yyyy/MM/dd HH:mm:ss]','Humidity [%]','Air temperature [°C]',
                'Cloud coverage [%]','Solar radiation [W/m2]'
            ];
            await saveCSV('meteo.csv', header, data.rows);
            alert(`Save file successfully.`);
        } catch (e) { alert(e);}
    });
}

function weatherManagement() {
    // Update location
    iframeConnector(obj.weatherLocation, [obj.weatherLat, obj.weatherLon], 'pickLatLon');
    obj.weatherDownload.addEventListener('click', async () => {
        const lat = obj.weatherLat.value, lon = obj.weatherLon.value, key = 'wind';
        if (lat === '' || lon === '') { alert('Please select a location on map.'); return; }
        const start = obj.weatherStart.value, end = obj.weatherEnd.value;
        if (start === '' || end === '') { alert('Please select start/end date(s).'); return; }
        const statusRes = await jsonLoader('check_download_status', {projectName: currentProject});
        if (statusRes.status === "running") { alert("Wind download is already running."); return; }
        obj.weatherLog.value = '';
        const content = { 
            projectName: currentProject, lat: lat, lon: lon, start: start, end: end, key: key
        };
        const request = await jsonLoader('start_meteo', content);
        if (request.status === 'error') { alert(request.message); return; }
        updateLog(currentProject, obj.weatherLog, 2, 'wind_log', async () => {
            const res = { projectName: currentProject, fileName: `${key}.csv` };
            const wind = await jsonLoader('get_result', res);
            if (wind.status === 'error') { alert(wind.message); return; }
            fillTable(wind.content, obj.weatherTable);
            alert('Downloading wind data completed.');
        });
    });
    obj.weatherSave.addEventListener('click', async () => {
        const data = getDataFromTable(obj.weatherTable, true);
        if (data.rows.length === 0) {alert('No wind observation found.'); return;}
        try {
            const header = ['Time [yyyy/MM/dd HH:mm:ss]','Magnitude [m/s]','Angle [deg]'];
            await saveCSV('wind.csv', header, data.rows);
            alert(`Save file successfully.`);
        } catch (e) { alert(e);}
    });
}