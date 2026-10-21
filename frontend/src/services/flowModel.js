import { setupTabs } from "./tabManager.js";
import { getUser, signalSender, getProjectList, jsonLoader, updateLog, nameChecker
} from "./commonFunctions.js";
import { projectRender } from "./projectManager.js";
import { getLastTimeZone } from "./constant.js";


const $ = (id) => document.getElementById(id);
const obj = {
    projectList: $('project-list'), projectName: $('project-name'), projectOpener: $('open-btn'),
    modelInterval: $('model-step'), modelStart: $('model-start'), modelEnd: $('model-end'),
    modelCheckBtn: $('model-check-btn'), modelLogText: $('model-log'), 
    modelLat: $('model-lat'), modelLon: $('model-lon'), modelRunBtn: $('model-run-btn')
}
const intervalOption = {'1h': 3600, '1d': 86400, '1w': 604800, '1ME': 18144000};

let currentProject;


setupTabs(document); await getProject(); modelManager();


async function getProject() { 
    const userName = await getUser(); currentProject = userName.split('/').pop();
    const respond = await getProjectList(`${currentProject}/flows`, '');
    await projectRender(obj.projectName, obj.projectList, respond);
}

function modelManager() {
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
    obj.modelCheckBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim(), key = 'wflow_check';
        if (!name || name === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        try {
            obj.modelLogText.value = '';
            const content = { 
                projectName: currentProject, flowName: name, key: 'check', 
                keyChecker: key, timeZone: getLastTimeZone(), 
            };
            const request = await jsonLoader('wflow_model', content);
            if (request.status === 'error') { alert(request.message); return; }
            updateLog(currentProject, obj.modelLogText, 2, key, async () => {
                alert('Checking model parameters completed.');
                obj.modelLat.value = request.content.lat_lon[0];
                obj.modelLon.value = request.content.lat_lon[1];
            });
        } catch (error) { alert(`Checking model parameters failed: ${error.message}`); }
    });
    obj.modelRunBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim(), keyChecker = 'wflow_run';
        if (!name || name === '') { alert('Please define scenario name.'); return; }
        if (nameChecker(name)) { alert('Scenario name contains invalid characters.'); return; }
        const start = obj.modelStart.value, end = obj.modelEnd.value;
        if (start === '' || end === '') { alert('Please select a start and end date.'); return; }
        const lat = obj.modelLat.value, lon = obj.modelLon.value;
        if (lat === '' || lon === '') { alert('Please add a upstream location on map first.'); return; }
        try {
            const contentCheck = { projectName: currentProject, key: keyChecker };
            const statusRes = await jsonLoader('check_download_status', contentCheck);
            if (statusRes.status === "running") { alert("Running Wflow model is in progress."); return; }
            obj.modelLogText.value = '';
            const params_in = Object.fromEntries(
                [...document.querySelectorAll(".input-parameters input")]
                .map(input => [input.id, Number(input.value)])
            );
            const params_out = Object.fromEntries(
                [...document.querySelectorAll(".output-parameters input")]
                .map(output => [output.id, output.checked])
            );
            const content = { 
                projectName: currentProject, flowName: name, key: 'run', 
                start: start, end: end, timeZone: getLastTimeZone(), 
                keyChecker: keyChecker, step: obj.modelInterval.value, lat: lat, lon: lon, 
                params_input: params_in, params_output: params_out
            };
            const request = await jsonLoader('wflow_model', content);
            if (request.status === 'error') { alert(request.message); return; }
            updateLog(currentProject, obj.modelLogText, 3, keyChecker, async () => {
                alert('Running Wflow model completed.'); 
            }, true);
        } catch (error) { alert(`Running Wflow model failed: ${error.message}`); }
    });
}