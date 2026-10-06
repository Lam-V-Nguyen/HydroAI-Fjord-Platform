import { setupTabs } from "./tabManager.js";
import { getUser, signalSender, getProjectList, jsonLoader, updateLog, fillTable, getDataFromTable 
} from "./commonFunctions.js";
import { projectRender } from "./projectManager.js";
import { getLastTimeZone } from "./constant.js";


const $ = (id) => document.getElementById(id);
const obj = {
    projectList: $('project-list'), projectName: $('project-name'), projectCreator: $('create-btn'),
    modelInterval: $('model-step'), modelStart: $('model-start'), modelEnd: $('model-end'),
    modelPourpointBtn: $('model-pourpoint-btn'), modelLat: $('model-lat'), modelLon: $('model-lon'),
    pourpointFile: $('model-pourpoint-file'), modelArea: $('model-area'), modelCheckBtn: $('model-check-btn'),
    pointStream: $('stream-points'), pointStreamBtn: $('stream-points-btn'),
    pointStreamTable: $('stream-points-table'), pointSelected: $('stream-points-selected'),
    modelRunBtn: $('model-run-btn'), modelLog: $('model-text')
}


let currentProject;


setupTabs(document); await getProject(); modelManager();

async function getProject() { 
    const userName = await getUser(); currentProject = userName.split('/').pop();
    const respond = await getProjectList(`${currentProject}/flows`, '');
    await projectRender(obj.projectName, obj.projectList, respond);
}

function modelManager() {
    obj.projectCreator.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const content = { projectName: currentProject, flowName: name, key: 'open', timeZone: getLastTimeZone() };
        signalSender('Reading forcing data to get start and end dates.\nPlease wait...');
        const data = await jsonLoader('flow_project', content); signalSender('hideOverlay');
        if (data.status === 'error') { alert(data.message); return; }
        obj.modelStart.value = data.content['start']; obj.modelEnd.value = data.content['end'];
        obj.modelInterval.value = data.content['interval'];
    });
    obj.modelCheckBtn.addEventListener('click', async () => {
        const name = obj.projectName.value, keyChecker = 'wflow_check';
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const contentCheck = {projectName: currentProject, key: keyChecker};
        const statusRes = await jsonLoader('check_download_status', contentCheck);
        if (statusRes.status === "running") { alert("Check model is running."); return; }
        const upArea = obj.modelArea.value;
        if (upArea === '') { alert('Please specify area of upstream.'); return; }
        const content = { 
            projectName: currentProject, flowName: name, key: 'check', 
            upArea: upArea, keyChecker: keyChecker, timeZone: getLastTimeZone()
        };
        const request = await jsonLoader('wflow_model', content);
        if (request.status === 'error') { alert(request.message); return; }
        obj.modelLog.value = '';
        updateLog(currentProject, obj.modelLog, 1, keyChecker, async () => {
            alert('Checking Wflow model completed.');
        });
        obj.modelLat.value = request.content.lat; obj.modelLon.value = request.content.lon;
    });
    obj.modelPourpointBtn.addEventListener('click', () => obj.pourpointFile.click());
    obj.pourpointFile.addEventListener('change', async (e) => {
        const file = e.target.files[0]; if (!file) return; 
        const formData = new FormData(); formData.append('file', file);
        const name = obj.projectName.value;
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        formData.append('flowName', name); formData.append('projectName', currentProject);
        try {
            signalSender('showOverlay', 'Uploading pourpoint data. Please wait...');
            const response = await fetch('/geojson_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            const coords = data.content["features"][0]["geometry"]["coordinates"]
            obj.modelLat.value = coords[1]; obj.modelLon.value = coords[0];
        } catch (error) { alert(`Uploading pourpoint failed: ${error.message}`); }
        finally { e.target.value = ''; }
    });
    obj.pointStreamBtn.addEventListener('click', async () => {
        const name = obj.projectName.value;
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const lat = obj.modelLat.value, lon = obj.modelLon.value;
        if (lat === '' || lon === '') { alert('Please add a pourpoint first.'); return; }
        signalSender('showOverlay', 'Getting number of stream points from strord data.\nPlease wait...');
        const content = { 
            projectName: currentProject, flowName: name, lat: lat, lon: lon,
        };
        const request = await jsonLoader('check_stream_points', content);
        signalSender('hideOverlay');
        if (request.status === 'error') { alert(request.message); return; }
        obj.pointStream.value = request.content.points;
        fillTable(request.content.data, obj.pointStreamTable, true);
        obj.pointSelected.value = request.content.selected;
    });
    obj.modelRunBtn.addEventListener('click', async () => {
        const name = obj.projectName.value, keyChecker = 'wflow_run';
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const contentCheck = {projectName: currentProject, key: keyChecker};
        const statusRes = await jsonLoader('check_download_status', contentCheck);
        if (statusRes.status === "running") { alert("Running Wflow model is in progress."); return; }
        const startTime = obj.modelStart.value, endTime = obj.modelEnd.value;
        if (startTime === '') { alert('Please select a start date first.'); return; }
        if (endTime === '') { alert('Please select an end date first.'); return; }
        const lat = obj.modelLat.value, lon = obj.modelLon.value;
        if (lat === '' || lon === '') { alert('Please add a pourpoint first.'); return; }
        const upArea = obj.modelArea.value;
        if (upArea === '') { alert('Please specify area of upstream.'); return;}
        const pointTotal = getDataFromTable(obj.pointStreamTable, true);
        if (pointTotal.rows.length === 0) {
            alert("No stream point found. Please hit the button 'Stream Points' first."); return; 
        }
        const pointCount = obj.pointSelected.value;
        if (pointCount === '') {
            alert("No candidate points selected. Please specify nearnest point to the pourpoint first."); return; 
        }
        const result = pointTotal.rows.slice(0, Number(pointCount));
        const params_in = Object.fromEntries(
            [...document.querySelectorAll(".input-parameters input")]
                .map(input => [input.id, Number(input.value)])
        );
        const params_out = Object.fromEntries(
            [...document.querySelectorAll(".output-parameters input")]
                .map(input => [input.id, input.checked])
        );
        const content = { 
            projectName: currentProject, flowName: name, key: 'run', 
            start: startTime, end: endTime, timeZone: getLastTimeZone(),
            points: result, step: obj.modelInterval.value, 
            lat: lat, lon: lon, upArea: upArea, keyChecker: keyChecker,
            params_input: params_in, params_output: params_out
        };
        const request = await jsonLoader('wflow_model', content);
        if (request.status === 'error') { alert(request.message); return; }
        obj.modelLog.value = '';
        updateLog(currentProject, obj.modelLog, 3, keyChecker, async () => {
            alert('Running Wflow model completed.'); 
        }, true);
    });
}