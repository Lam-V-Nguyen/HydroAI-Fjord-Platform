import { setupTabs } from "./tabManager.js";
import { projectRender } from "./projectManager.js";
import { getProjectList, signalSender, jsonLoader, fillTable
} from "./commonFunctions.js";


const $ = (id) => document.getElementById(id);
const obj = {
    projectList: $('project-list'), projectName: $('project-name'), projectBtn: $('project-btn'),
    simulationStartDate: $('sim-start-date'), simulationEndDate: $('sim-end-date'),
    observationBtn: $('observation-btn'), observationFile: $('observation-file'),
    observationStartDate: $('observation-start-date'), observationEndDate: $('observation-end-date'),
    observationTable: $('observation-table'), observationName: $('observation-name')
}

let currentProject;

setupTabs(document); await getProject(); calibrationManager();

async function getProject() { 
    const respond = await getProjectList('', 'input');
    await projectRender(obj.projectName, obj.projectList, respond);
}

function calibrationManager() {
    obj.projectBtn.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (name === '') { alert('Please select a scenario first.'); return; }
        currentProject = name; signalSender('Reading information from project "' + name + '". Please wait...');
        const content = { projectName: currentProject };
        const data = await jsonLoader('calibration_project', content); signalSender('hideOverlay');
        if (data.status === 'error') { alert(data.message); return; }
        obj.simulationStartDate.value = data.content['start'];
        obj.simulationEndDate.value = data.content['end'];
    });
    obj.observationBtn.addEventListener('click', () => obj.observationFile.click());
    obj.observationFile.addEventListener('change', async (e) => {
        if (currentProject === undefined) { alert('Please select a scenario first.'); return; }
        const simStart = obj.simulationStartDate.value; const simEnd = obj.simulationEndDate.value;
        if (simStart === '' || simEnd === '') { alert('Please read the start/end of HYD scenario.'); return; }
        const file = e.target.files[0]; if (!file) return;
        const formData = new FormData(); formData.append('file', file); 
        formData.append('projectName', currentProject);
        formData.append('simStart', simStart); formData.append('simEnd', simEnd);
        try {
            signalSender('showOverlay', 'Reading observation data. Please wait...');
            const response = await fetch('/obs_calibration_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            fillTable(data.content.data, obj.observationTable);
            obj.observationName.value = file.name;
            obj.observationStartDate.value = data.content['start'];
            obj.observationEndDate.value = data.content['end']; 
        } catch (error) { alert(`Uploading observation data failed: ${error.message}`); }
        finally { e.target.value = ''; signalSender('hideOverlay'); }
    });


}


