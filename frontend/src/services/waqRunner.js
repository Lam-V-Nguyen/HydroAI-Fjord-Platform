import { getProjectList, jsonLoader } from "./commonFunctions.js";

const $ = (id) => document.getElementById(id);
const obj = { 
    scenarioSelector: $("options-scenario"), labelWAQ: $("label-waq"), 
    waqSelector: $("options-waq"), progressbar: $("progressbar"),
    progressText: $("progress-text"), runBtn: $("run-button"),
    textareaWrapper: $("form-row-textarea"), showCheckbox: $("show-checkbox"),
    infoArea: $("textarea"), checkboxContainer: $("checkbox-container")
};

let currentProject = null, logIntervalWAQ = null, lastOffsetWAQ = 0,
    WAQRunning = false, activeWAQProject = null;

waqComponents();

async function waqComponents() {
    const respond = await getProjectList('', 'input');
    if (!respond) { obj.scenarioSelector.innerHTML = `<option value="">--- No projects found ---</option>`; return; }
    const options = respond.map(name => `<option value="${name}">${name}</option>`).join('');
    const defaultOption = `<option value="" selected>--- No selected ---</option>`;
    obj.scenarioSelector.innerHTML = defaultOption + options;
    obj.showCheckbox.checked = false;
    obj.showCheckbox.addEventListener('change', (e) => { 
        if (e.target.checked && (obj.progressText.innerText === 'No simulation running' 
            || obj.progressText.innerText === 'Simulation completed successfully')) { obj.infoArea.value = ''; }
        obj.textareaWrapper.style.display = e.target.checked ? 'flex' : 'none';
    });
    obj.scenarioSelector.addEventListener('change', async() => {
        const projectName = obj.scenarioSelector.value;
        if (!projectName || projectName === '') {
            obj.progressText.innerText = ""; obj.progressbar.value = 0;
            obj.waqSelector.value = ''; obj.waqSelector.innerHTML = defaultOption;
            return;
        }
        // Work with WAQ simulation
        if (logIntervalWAQ) { clearInterval(logIntervalWAQ); logIntervalWAQ = null; }
        lastOffsetWAQ = 0; activeWAQProject = `${projectName}_${obj.waqSelector.value}`;
        const data = await jsonLoader('select_project', {filename: projectName, key: 'getWAQs', folder_check: 'input'});
        if (data.status === "error") { alert(data.message); obj.scenarioSelector.value = ''; return; }
        obj.waqSelector.innerHTML = data.content.map(name => `<option value="${name}">${name}</option>`).join('');
        const statusRes = await jsonLoader('check_sim_status_waq', {projectName: projectName, waqName: obj.waqSelector.value});
        if (statusRes.status === "running" || statusRes.status === "reorganizing") {
            const res = await fetch(`/sim_log_full/${projectName}?log_file=log_waq.txt`);
            if (res.ok) {
                const data = await res.json();
                obj.infoArea.value = data.content || ''; lastOffsetWAQ = data.offset;
            }
            obj.showCheckbox.checked = true; WAQRunning = true;
            // Run water quality simulation and Update logs every 1 second
            updateLogWAQ(projectName, obj.waqSelector.value, obj.progressbar, obj.progressText, obj.infoArea, 1);
        } else { obj.showCheckbox.checked = false; WAQRunning = false; }
        obj.progressText.innerText = statusRes.message; 
        obj.progressbar.value = statusRes.progress;
        obj.checkboxContainer.style.display = 'block'; 
        obj.showCheckbox.dispatchEvent(new Event('change'));
    });
    // Run new simulation
    obj.runBtn.addEventListener('click', async () => {
        currentProject = obj.scenarioSelector.value;
        if (!currentProject || currentProject === '') { alert('Please select a scenario.'); return; }
        // Check if WAQ simulation is running
        if (WAQRunning) { alert("Detected a WAQ simulation is running. Please wait until it finishes."); return; }
        const statusRes = await jsonLoader('check_sim_status_waq', {projectName: currentProject, waqName: obj.waqSelector.value});
        if (statusRes.status === "running") { alert("WAQ simulation is already running."); return; }
        const res = await jsonLoader('check_folder', {projectName: currentProject, folder: obj.waqSelector.value, key: 'waq'});
        if (res.status === "ok") { if (!confirm("Output exists. Re-run will overwrite it. Continue?")) return; }
        obj.progressText.innerText = 'Preparing data for the WAQ simulation...';
        obj.infoArea.value = ''; obj.progressbar.value = 0;
        const start = await jsonLoader('start_sim_waq', {projectName: currentProject, waqName: obj.waqSelector.value});
        if (start.status === "error") {alert(start.message); return;}
        updateLogWAQ(currentProject, obj.waqSelector.value, obj.progressbar, obj.progressText, obj.infoArea, 1);
    });
}

function updateLogWAQ(hydProject, waqProject, progress_bar, progress_text, info, seconds) {
    activeWAQProject = `${hydProject}_${waqProject}`;
    logIntervalWAQ = setInterval(async () => {
        if (activeWAQProject !== `${hydProject}_${waqProject}`) { clearInterval(logIntervalWAQ); logIntervalWAQ = null; }
        try {
            const statusRes = await jsonLoader('check_sim_status_waq', {projectName: hydProject, waqName: obj.waqSelector.value});
            progress_text.innerText = statusRes.message; progress_bar.value = statusRes.progress;
            if (statusRes.status !== "running" && statusRes.status !== "reorganizing") {
                info.value += statusRes.message;
                if (logIntervalWAQ) { clearInterval(logIntervalWAQ); logIntervalWAQ = null; }
            }
            const res = await fetch(`/sim_log_tail_waq/${hydProject}?offset=${lastOffsetWAQ}&log_file=log_waq.txt`);
            if (!res.ok) return;
            const data = await res.json(); if (info.value !== '') { info.value = ''; }
            for (const line of data.lines) { info.value += line + "\n"; }
            lastOffsetWAQ = data.offset;
        } catch (error) { clearInterval(logIntervalWAQ); logIntervalWAQ = null; }
    }, seconds * 1000);
}