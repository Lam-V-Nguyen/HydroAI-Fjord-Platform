import { setupTabs } from "./tabManager.js";
import { getUser, signalSender, getProjectList, jsonLoader, updateLog } from "./commonFunctions.js";
import { projectRender } from "./projectManager.js";


const $ = (id) => document.getElementById(id);
const obj = {
    projectList: $('project-list'), projectName: $('project-name'), projectCreator: $('create-btn'),
    modelSteps: $('model-step'), modelStart: $('model-start'), modelEnd: $('model-end'),
    modelPourpointBtn: $('model-pourpoint-btn'), modelLat: $('model-lat'), modelLon: $('model-lon'),
    pourpointFile: $('model-pourpoint-file'), modelArea: $('model-area'), modelCheckBtn: $('model-check-btn'), 
    modelPrepareBtn: $('model-prepare-btn'), modelRunBtn: $('model-run-btn'), modelLog: $('model-text')
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
        const content = { projectName: currentProject, flowName: name, key: 'open' };
        signalSender('Reading forcing data to get start and end dates.\nPlease wait...');
        const data = await jsonLoader('flow_project', content); signalSender('hideOverlay');
        if (data.status === 'error') { alert(data.message); return; }
        obj.modelStart.value = data.content['start']; obj.modelEnd.value = data.content['end'];
    });
    obj.modelCheckBtn.addEventListener('click', async () => {
        const name = obj.projectName.value;
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const statusRes = await jsonLoader('check_download_status', {projectName: currentProject});
        if (statusRes.status === "running") { alert("Check model is running."); return; }
        const upArea = obj.modelArea.value;
        if (upArea === '') { alert('Please specify area of upstream.'); return;}
        obj.modelLog.value = '';
        const content = { projectName: currentProject, flowName: name, key: 'check', upArea: upArea };
        const request = await jsonLoader('wflow_model', content);
        if (request.status === 'error') { alert(request.message); return; }
        updateLog(currentProject, obj.modelLog, 2, 'wflow_check', async () => {
            alert('Checking Wflow model completed.');
        });
        obj.modelLat.value = request.content[0]; obj.modelLon.value = request.content[1];
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
    obj.modelPrepareBtn.addEventListener('click', async () => {
        const name = obj.projectName.value;
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        const startTime = obj.modelStart.value, endTime = obj.modelEnd.value;
        if (startTime === '') { alert('Please select a start date first.'); return; }
        if (endTime === '') { alert('Please select an end date first.'); return; }
        const lat = obj.modelLat.value, lon = obj.modelLon.value;
        if (lat === '' || lon === '') { alert('Please add pourpoint first.'); return; }
        const params_in = Object.fromEntries(
            [...document.querySelectorAll(".input-parameters input")]
                .map(input => [input.id, Number(input.value)])
        );
        const params_out = Object.fromEntries(
            [...document.querySelectorAll(".output-parameters input")]
                .map(input => [input.id, input.checked])
        );
        obj.modelLog.value = '';
        const content = { 
            projectName: currentProject, flowName: name, key: 'prepare', 
            start: startTime, end: endTime, step: obj.modelSteps.value,
            lat: lat, lon: lon, params_input: params_in, params_output: params_out
        };
        const request = await jsonLoader('wflow_model', content);
        if (request.status === 'error') { alert(request.message); return; }
        updateLog(currentProject, obj.modelLog, 5, 'wflow_prepare', async () => {
            alert('Preparing Wflow model completed.'); }, true
        );
    });
    obj.modelRunBtn.addEventListener('click', async() => {
        const name = obj.projectName.value;
        if (name === '') { alert('Please select a scenario from the tab "Settings" first.'); return; }
        obj.modelLog.value = '';
        const content = { projectName: currentProject, flowName: name, key: 'run' };
        const request = await jsonLoader('wflow_model', content);
        if (request.status === 'error') { alert(request.message); return; }
        updateLog(currentProject, obj.modelLog, 1, 'wflow_run', async () => {
            alert('Running Wflow model completed.'); }, true
        );
    });
}