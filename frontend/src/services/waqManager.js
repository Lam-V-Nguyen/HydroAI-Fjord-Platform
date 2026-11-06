import { waqMapId, origin, getLastTimeZone } from "./constant.js";
import { setupTabs } from "./tabManager.js";
import { getProjectList, jsonLoader, fillTable, deleteTable, addRowToTable, signalSender,
    nameChecker, iframeConnector, getDataFromTable, copyPaste, removeRowFromTable
} from "./commonFunctions.js";
import { projectRender } from "./projectManager.js";
import { toUTC } from "./projectSaver.js";

const DEFAULT_SCHEME = '15', DEFAULT_MAXITER = '500', DEFAULT_TOLERANCE = '1E-07';
const POINT_HEADER = ['Name', 'Latitude', 'Longitude'];
const TIME_HEADER = ['YYYY-MM-DD HH:MM:SS', 'PointName', 'Substance', 'Value'];
const TIME_PATTERN = /^\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(:\d{2})?$/;
const USEFOR_PATTERN = /^USEFOR\s+'([^']+)'\s+'([^']+)'$/;

let projectSelected = [], waqContent = [], loadedScenario = '';

const $ = (id) => document.getElementById(id);
const obj = {
    descriptionTab: $('desription-tab'), controlTab: $('control-tab'),
    projectName: $('project-name'), projectList: $('project-list'),
    waqSelector: $('waq-name'), waqLabel: $('label-waq'),
    projectCreator: $('create-btn'), projectCloner: $('duplicate-btn'),
    projectRemover: $('remove-btn'), hydFilename: $('hyd-filename'), 
    nLayers: $('n-layer'), startTime: $('start-time'), stopTime: $('stop-time'),
    sourcesContainer: $('wq-sources-container'), sourcesTable: $('wq-sources-table'),
    obsPointName: $('wq-obs-point'), obsPointPicker: $('wq-obs-picker'),
    obsPointRemove: $('wq-obs-remove'), obsPointTable: $('wq-obs-table'),
    loadsPointName: $('wq-loads-point'), loadsPointPicker: $('wq-loads-picker'),
    loadsPointRemove: $('wq-loads-remove'), loadsPointTable: $('wq-loads-table'),
    timeTable: $('wq-time-series-table'), timeTableAddRow: $('time-series-add-row'),
    inputFile: $('input-csv'), csvTable: $('time-series-csv'),
    removeTable: $('time-series-remove'), timePreviewContainer: $('wq-textarea-container'),
    timePreview: $('wq-data-view'), physicalSelector: $('wq-physical'),
    physicalName: $('wq-physical-name'), usesforFromPhysical: $('wq-physical-usefors-from'),
    usesforToPhysical: $('wq-physical-usefors-to'), usesforPhysical: $('wq-usefors-physical'),
    initialFromPhysical: $('wq-physical-initial-from'), initialToPhysical: $('wq-physical-initial'),
    initialAreaPhysical: $('wq-initial-physical'), schemePhysical: $('wq-scheme-physical'),
    maxInterPhysical: $('max-iterations-physical'), tolerancePhysical: $('tolerance-physical'),
    chemicalSelector: $('wq-chemical'), chemicalName: $('wq-chemical-name'),
    usesforFromChemical: $('wq-chemical-usefors-from'), usesforToChemical: $('wq-chemical-usefors-to'),
    usesforChemical: $('wq-usefors-chemical'), initialFromChemical: $('wq-chemical-initial-from'),
    initialToChemical: $('wq-chemical-initial'), initialAreaChemical: $('wq-initial-chemical'),
    schemeChemical: $('wq-scheme-chemical'), maxInterChemical: $('max-iterations-chemical'),
    toleranceChemical: $('tolerance-chemical'), microbialSelector: $('wq-microbial'),
    microbialName: $('wq-microbial-name'), usesforFromMirobial: $('wq-microbial-usefors-from'),
    usesforToMirobial: $('wq-microbial-usefors-to'), usesforMicrobial: $('wq-usefors-microbial'),
    initialFromMirobial: $('wq-microbial-initial-from'), initialToMirobial: $('wq-microbial-initial'),
    initialAreaMirobial: $('wq-initial-microbial'), schemeMicrobial: $('wq-scheme-microbial'),
    maxInterMirobial: $('max-iterations-microbial'), toleranceMirobial: $('tolerance-microbial'),
};

const tabs = {
    physical: {
        selector: $('wq-physical'), name: $('wq-physical-name'),
        useforsFrom: $('wq-physical-usefors-from'), useforsTo: $('wq-physical-usefors-to'),
        usefors: $('wq-usefors-physical'), initialFrom: $('wq-physical-initial-from'),
        initialValue: $('wq-physical-initial'), initialArea: $('wq-initial-physical'),
        scheme: $('wq-scheme-physical'), maxiter: $('max-iterations-physical'),
        tolerance: $('tolerance-physical'),
    },
    chemical: {
        selector: $('wq-chemical'), name: $('wq-chemical-name'),
        useforsFrom: $('wq-chemical-usefors-from'), useforsTo: $('wq-chemical-usefors-to'),
        usefors: $('wq-usefors-chemical'), initialFrom: $('wq-chemical-initial-from'),
        initialValue: $('wq-chemical-initial'), initialArea: $('wq-initial-chemical'),
        scheme: $('wq-scheme-chemical'), maxiter: $('max-iterations-chemical'),
        tolerance: $('tolerance-chemical'),
    },
    microbial: {
        selector: $('wq-microbial'), name: $('wq-microbial-name'),
        useforsFrom: $('wq-microbial-usefors-from'), useforsTo: $('wq-microbial-usefors-to'),
        usefors: $('wq-usefors-microbial'), initialFrom: $('wq-microbial-initial-from'),
        initialValue: $('wq-microbial-initial'), initialArea: $('wq-initial-microbial'),
        scheme: $('wq-scheme-microbial'), maxiter: $('max-iterations-microbial'),
        tolerance: $('tolerance-microbial'),
    },
};
const tabOf = (key) => tabs[String(key || '').replace(/^wq-/, '')];

setupTabs(document); projectOptions(); waqManager();

function setOptions(select, items) {
    select.replaceChildren(...(items || []).map(item => new Option(item, item)));
}
 
function renderWaqList(selected = '') {
    obj.waqSelector.replaceChildren(new Option('-- New WAQ model --', ''),
        ...waqContent.map(name => new Option(name, name)));
    obj.waqSelector.value = selected;
}
 
function setScenarioButtons(visible) {
    obj.projectCloner.style.display = visible ? "flex" : "none";
    obj.projectRemover.style.display = visible ? "flex" : "none";
}
 
function showDescription() {
    obj.controlTab.style.display = "none"; obj.descriptionTab.style.display = "block";
}
 
function clearPreview() {
    obj.timePreview.value = ''; obj.timePreviewContainer.style.display = 'none';
}
 
function clearTimeTable() {
    deleteTable(obj.timeTable); addRowToTable(obj.timeTable, TIME_HEADER); clearPreview();
}
 
function resetTab(t) {
    t.selector.value = ''; t.name.value = '';
    [t.useforsFrom, t.useforsTo, t.initialFrom].forEach(select => select.replaceChildren());
    t.usefors.value = ''; t.initialArea.value = ''; t.initialValue.value = '0';
    t.scheme.value = DEFAULT_SCHEME; t.maxiter.value = DEFAULT_MAXITER; t.tolerance.value = DEFAULT_TOLERANCE;
}
 
function sendPointsToMap() {
    window.parent.postMessage({ type: 'waqPoint', content: getDataFromTable(obj.obsPointTable, true) }, origin);
    window.parent.postMessage({ type: 'loadsPoint', content: getDataFromTable(obj.loadsPointTable, true) }, origin);
}
 
// Show the overlay while fn runs and always hide it again, also when the request fails
async function withOverlay(message, fn) {
    signalSender('showOverlay', message);
    try { return await fn(); }
    catch (err) { return { status: 'error', message: `Error: ${err?.message || err}` }; }
    finally {
        signalSender('hideOverlay');
        await new Promise(resolve => setTimeout(resolve, 100)); // let the overlay close before an alert
    }
}

const isBlank = (value) => String(value ?? '').trim() === '';
const toNumber = (value) => (isBlank(value) ? NaN : Number(value));
// Rows that are entirely empty (e.g. the placeholder row) are ignored
const tableRows = (table) => (getDataFromTable(table, true).rows || []).filter(row => row.some(v => !isBlank(v)));
 
function showErrors(errors) {
    const shown = errors.slice(0, 10);
    if (errors.length > shown.length) shown.push(`... and ${errors.length - shown.length} more.`);
    alert(shown.join('\n'));
}
 
function validatePoints(rows, label) {
    const errors = [], seen = new Set();
    rows.forEach((row, i) => {
        const name = String(row[0] ?? '').trim(), lat = toNumber(row[1]), lon = toNumber(row[2]);
        if (name === '') errors.push(`${label}, row ${i + 1}: name is empty.`);
        else if (/['"]/.test(name)) errors.push(`${label}, row ${i + 1}: name "${name}" must not contain quotes.`);
        else if (seen.has(name)) errors.push(`${label}: name "${name}" is used more than once.`);
        seen.add(name);
        if (!(Math.abs(lat) <= 90) || !(Math.abs(lon) <= 180))
            errors.push(`${label}, row ${i + 1}: latitude/longitude is not a valid number.`);
    });
    return errors;
}
 
function validateTimeRows(rows, loadNames) {
    const errors = [], loads = new Set(loadNames);
    rows.forEach((row, i) => {
        const [time, location, substance, value] = row.map(v => String(v ?? '').trim());
        if (!TIME_PATTERN.test(time)) errors.push(`Time series, row ${i + 1}: time "${time}" must be YYYY-MM-DD HH:MM:SS.`);
        if (!loads.has(location)) errors.push(`Time series, row ${i + 1}: location "${location}" is not in the list of loads.`);
        if (substance === '' || /['"\s]/.test(substance)) errors.push(`Time series, row ${i + 1}: substance "${substance}" is empty or contains quotes/spaces.`);
        if (!Number.isFinite(toNumber(value))) errors.push(`Time series, row ${i + 1}: value "${value}" is not a number.`);
    });
    return errors;
}
 
function validateScenarioName(name) {
    if (name === '') { alert('Please specify the scenario name.'); return false; }
    if (nameChecker(name)) { alert(`Scenario name "${name}" contains invalid characters.`); return false; }
    return true;
}

async function loadScenario(projectName, waqName) {
    const data = await jsonLoader('load_waq', { projectName, waqName, timeZone: getLastTimeZone() });
    if (data.status === "error") { alert(data.message || `Cannot load scenario '${waqName}'.`); return; }
    const c = data.content, t = tabs[c.mode];
    if (!t) { alert(`Scenario '${waqName}' has an unknown model group '${c.mode}'.`); return; }
    if (c.obs.length > 0) { fillTable(c.obs, obj.obsPointTable, true); }
    fillTable(c.loads, obj.loadsPointTable, true);
    deleteTable(obj.timeTable); fillTable(c.time_data, obj.timeTable, true);
    t.selector.value = c.key; t.name.value = c.name;
    t.usefors.value = c.usefors; t.initialArea.value = c.initial;
    t.scheme.value = c.scheme; t.maxiter.value = c.maxiter; t.tolerance.value = c.tolerance;
    setOptions(t.useforsFrom, c.useforsFrom); setOptions(t.initialFrom, c.useforsFrom);
    setOptions(t.useforsTo, c.useforsTo);
    // Restore the saved simulation window and layers (older scenarios do not have them)
    if (c.startTime) { obj.startTime.value = c.startTime; }
    if (c.stopTime) { obj.stopTime.value = c.stopTime; }
    if (c.nLayers) { obj.nLayers.value = c.nLayers; }
    obj.timePreviewContainer.style.display = 'flex';
    obj.timePreview.value = c.times; loadedScenario = waqName;
}

async function projectOptions(){
    projectSelected = await getProjectList();
    await projectRender(obj.projectName, obj.projectList, projectSelected);
    obj.projectName.style.pointerEvents = "auto";
    obj.projectName.addEventListener('click', async () => {
        if (projectSelected.length === 0) { return; }
        obj.projectList.innerHTML = '';
        projectSelected.forEach(p => {
            const li = document.createElement("li");
            li.textContent = p;
            li.addEventListener('mousedown', () => {
                obj.projectName.value = p; obj.projectList.style.display = "none";
            });
            obj.projectList.appendChild(li);
        });
        obj.projectList.style.display = "block";
    });
    obj.projectName.addEventListener('input', (e) => { 
        const value = e.target.value.trim();
        if (value === '') {
            showDescription(); waqContent = []; loadedScenario = '';
            obj.waqSelector.replaceChildren();
            obj.waqSelector.style.display = "none"; 
            obj.waqLabel.style.display = "none";
            setScenarioButtons(false);
        }
        projectRender(obj.projectName, obj.projectList, projectSelected);
    });
    obj.projectName.addEventListener('blur', () => { 
        setTimeout(() => { obj.projectList.style.display = "none"; }, 5);
    });
    obj.projectList.addEventListener('mousedown', async () => {
        const name = obj.projectName.value.trim();
        showDescription(); loadedScenario = ''; setScenarioButtons(false);
        const data = name ? await jsonLoader('select_waq', { projectName: name }) : { status: 'error' };
        waqContent = data.status === 'error' ? [] : data.content;
        if (!name || data.status === "error") { 
            obj.waqSelector.style.display = "none"; renderWaqList('');
            obj.waqLabel.style.display = "none"; return; 
        }
        renderWaqList('');
        obj.waqSelector.style.display = "flex"; obj.waqLabel.style.display = "flex";
    });
    obj.waqSelector.addEventListener('change', async (e) => { 
        setScenarioButtons(e.target.value !== ''); showDescription();
    });    
    // Create a new WAQ scenario, or open the selected one
    obj.projectCreator.addEventListener('click', async () => {
        const name = obj.projectName.value.trim();
        if (!name) { alert('Please select a HYD Scenario from the list.'); return; }
        // Find .hyd file
        const data = await jsonLoader('select_hyd', { projectName: name, timeZone: getLastTimeZone() });
        if (data.status === "error") { alert(data.message); return; }
        // Show tabs
        obj.controlTab.style.display = "block"; obj.descriptionTab.style.display = "none";
        obj.sourcesContainer.style.display = data.content.sink_sources.length > 0 ? "block":"none";
        fillTable(data.content.sink_sources, obj.sourcesTable, true);
        // Assign values
        obj.hydFilename.value = data.content.filename;
        if (data.content.n_layers) { obj.nLayers.value = data.content.n_layers; }
        obj.startTime.value = data.content.start_time; 
        obj.stopTime.value = data.content.stop_time;
        // Plot grid on map
        const content = { 
            projectName: name, gridName: data.content.grid, key: 'waq', opacity: 0.2
        }
        iframeConnector(null, null, 'gridPlot', content);        
        // Set default values
        deleteTable(obj.obsPointTable); deleteTable(obj.loadsPointTable);
        addRowToTable(obj.obsPointTable, POINT_HEADER);
        addRowToTable(obj.loadsPointTable, POINT_HEADER);
        deleteTable(obj.timeTable); addRowToTable(obj.timeTable, ['Time', 'Location', 'Substance', 'Value']);
        Object.values(tabs).forEach(resetTab); clearPreview(); loadedScenario = '';
        const waqValue = obj.waqSelector.value;
        if (waqValue !== '') { await loadScenario(name, waqValue); }
        sendPointsToMap();
    });
    // Clone scenario
    obj.projectCloner.addEventListener('click', async () => { 
        const name = obj.waqSelector.value;
        if (!name) { alert('Please select a WAQ scenario first.'); return; }
        const answer = prompt('Please enter a name for the new WAQ scenario.');
        if (answer === null) { alert('Please define the clone scenario name.'); return; }
        const newName = answer.trim();
        if (!validateScenarioName(newName)) { return; }
        if (waqContent.includes(newName)) { alert(`Scenario '${newName}' already exists.`); return; }
        const data = await withOverlay(`Cloning WAQ scenario '${name}' to '${newName}'. Please be patient...`,
            () => jsonLoader('clone_waq', { projectName: obj.projectName.value.trim(), oldName: name, newName: newName }));
        if (data.status === "error") { alert(data.message); return; }
        waqContent = [...waqContent, newName].sort();
        renderWaqList(newName); setScenarioButtons(true); showDescription(); alert(data.message);
    });
    // Delete scenario
    obj.projectRemover.addEventListener('click', async () => {
        const name = obj.projectName.value.trim(), waqName = obj.waqSelector.value;
        if (!waqName) { alert('Please select a WAQ scenario first.'); return; }
        if (!confirm(`Are you sure you want to delete scenario '${waqName}'?`)) { return; }
        const data = await withOverlay(`Deleting WAQ scenario '${waqName}'. Please be patient...`,
            () => jsonLoader('delete_waq', { projectName: name, name: waqName }));
        if (data.status === "error") { alert(data.message); return; }
        waqContent = waqContent.filter(item => item !== waqName);
        renderWaqList(''); setScenarioButtons(false);
        showDescription(); loadedScenario = ''; alert(data.message);
    });
}

async function processTimeSeries(t) {
    const folderName = t.name.value.trim();
    if (!t.selector.value) { alert('Please specify type of simulation.'); return null; }
    if (!validateScenarioName(folderName)) { return null; }
    const loads = tableRows(obj.loadsPointTable);
    if (loads.length === 0) {
        alert("No loads data found in the table.\nPlease check the load table in tab 'Point Settings'.");
        clearPreview(); return null;
    }
    const timeRows = tableRows(obj.timeTable);
    if (timeRows.length === 0) {
        alert("No time-series data found in the table.\nPlease check the table 'Time-Series Preparation'.");
        clearPreview(); return null;
    }
    const errors = [...validatePoints(loads, 'List of loads'),
        ...validateTimeRows(timeRows, loads.map(row => String(row[0]).trim()))];
    if (errors.length > 0) { showErrors(errors); return null; }
    const data = await jsonLoader('wq_time_to_waq', {
        folderName, loadsData: loads, timeData: timeRows, timeZone: getLastTimeZone()
    });
    if (data.status === "error") { clearPreview(); alert(data.message); return null; }
    obj.timePreview.value = data.content; obj.timePreviewContainer.style.display = 'flex';
    setOptions(t.useforsTo, data.tos);
    // Keep only the assignments whose time-series substance still exists
    t.usefors.value = t.usefors.value.split('\n').filter(line => {
        const match = line.trim().match(USEFOR_PATTERN);
        return match && data.tos.includes(match[2]);
    }).join('\n');
    return data;
}

async function waqManager(){
    // Check whether map widget exists
    let hasMap = false;
    try {
        const layout = localStorage.getItem('grid-layout');
        hasMap = layout ? JSON.parse(layout).some(item => item.id === waqMapId) : false;
    } catch { hasMap = false; }
    if (!hasMap) signalSender('addMapWidget', { id: waqMapId, title: 'Water Quality Scenario Map' });
    // Update location
    iframeConnector(obj.obsPointPicker, [obj.obsPointName, obj.obsPointTable],
        'waqPoint', () => getDataFromTable(obj.obsPointTable, true), ''
    );
    iframeConnector(obj.loadsPointPicker, [obj.loadsPointName, obj.loadsPointTable],
        'loadsPoint', () => getDataFromTable(obj.loadsPointTable, true), ''
    );
    // Copy and paste to tables
    copyPaste(obj.obsPointTable, 3); copyPaste(obj.loadsPointTable, 3);
    copyPaste(obj.timeTable, 4); copyPaste(obj.sourcesTable, 3);
    // Remove point from table
    obj.obsPointRemove.addEventListener('click', () => {
        const name = obj.obsPointName.value.trim();
        if (name === '') { alert('Please enter name of observation point from list to remove.'); return; }
        removeRowFromTable(obj.obsPointTable, name); obj.obsPointName.value = ''; sendPointsToMap();
    });
    obj.loadsPointRemove.addEventListener('click', () => {
        const name = obj.loadsPointName.value.trim();
        if (name === '') { alert('Please enter name of loads point from list to remove.'); return; }
        removeRowFromTable(obj.loadsPointTable, name); 
        obj.loadsPointName.value = ''; sendPointsToMap();
    });
    // Update when user change Combobox
    Object.values(tabs).forEach(substanceChanger);
    // Add new row to table
    obj.timeTableAddRow.addEventListener('click', () => { addRowToTable(obj.timeTable, TIME_HEADER); });
    // Delete table
    obj.removeTable.addEventListener('click', clearTimeTable);
    // Upload CSV
    obj.csvTable.addEventListener('click', () => { obj.inputFile.click(); });
    obj.inputFile.addEventListener('change', () => {
        const file = obj.inputFile.files[0]; if (!file) { return; }
        const reader = new FileReader();
        reader.onload = (e) => {
            const lines = String(e.target.result).replace(/^/, '').split(/\r?\n/);
            const columns = lines[0].split(/\t|,/);
            if (columns.length !== 4) { 
            alert(`The current table has ${columns.length} columns.\nNumber of columns must be 4.`); 
                obj.inputFile.value = ''; return; 
            }
            const rows = lines.slice(1).filter(row => row.trim() !== '');
            fillTable(rows.map(row => row.split(/\t|,/).slice(0, 4).map(v => v.trim())), obj.timeTable, true);
            clearPreview(); obj.inputFile.value = "";
        };
        reader.onerror = () => { alert(`Cannot read file '${file.name}'.`); obj.inputFile.value = ''; };
        reader.readAsText(file, 'UTF-8');
    });
    // Check function to process time-series
    document.querySelectorAll('.wq-process-time-series').forEach(btn => {
        btn.addEventListener('click', async () => { processTimeSeries(tabOf(btn.id)); });
    });
    // Update USEFORS data
    document.querySelectorAll('.wq-usefors').forEach(btn => {
        btn.addEventListener('click', () => {
            const t = tabOf(btn.dataset.info);
            const from = t.useforsFrom.value, to = t.useforsTo.value;
            if (!from || !to) { 
                alert('Please select both the model substance and the time-series substance.'); return; 
            }
            const lines = t.usefors.value.split('\n').filter(line => line.trim() !== '');
            lines.push(`USEFOR '${from}' '${to}'`);
            t.usefors.value = [...new Set(lines)].join('\n');
        });
    });
    // Add or replace an initial condition
    document.querySelectorAll('.wq-initial').forEach(btn => {
        btn.addEventListener('click', () => {
            const t = tabOf(btn.dataset.info);
            const from = t.initialFrom.value, value = t.initialValue.value.trim();
            if (!from) { alert('Please select a substance.'); return; }
            const number = toNumber(value);
            if (!Number.isFinite(number) || number < 0) { alert('The initial value must be a number >= 0.'); return; }
            // One line per substance: a new value replaces the old one
            const lines = t.initialArea.value.split('\n')
                .filter(line => line.trim() !== '' && line.trim().split(/\s+/)[0] !== from);
            lines.push(`${from} ${value}`);
            t.initialArea.value = lines.join('\n');
        });
    });
    // Save water quality simulation
    document.querySelectorAll('.wq-simulation').forEach(btn => {
        btn.addEventListener('click', async () => { saveScenario(btn.dataset.info); });
    });
}

function substanceChanger(t){
    t.selector.addEventListener('change', async () => {
        [t.useforsFrom, t.useforsTo, t.initialFrom].forEach(select => select.replaceChildren());
        t.usefors.value = ''; t.initialArea.value = ''; t.initialValue.value = '0';
        t.scheme.value = DEFAULT_SCHEME; t.maxiter.value = DEFAULT_MAXITER; t.tolerance.value = DEFAULT_TOLERANCE;
        clearPreview();
        const key = t.selector.value;
        if (!key) { t.name.value = ''; return; }
        // The backend accepts the model key directly ("simple-oxygen")
        const data = await jsonLoader('wq_time_from_waq', { key });
        if (data.status === "error") { alert(data.message); return; }
        if (t.name.value.trim() === '') { t.name.value = data.name || key; }
        setOptions(t.useforsFrom, data.froms); setOptions(t.initialFrom, data.froms);
        // Substances differ between models: ask before clearing what the user typed
        if (tableRows(obj.timeTable).length > 0 &&
            confirm('The substances of the new model may differ. Clear the time-series table?')) {
            clearTimeTable();
        }
    });
}

async function saveScenario(mode) {
    const t = tabOf(mode), name = obj.projectName.value.trim();
    if (!name) { alert('Please define project.'); return; }
    const hydPath = obj.hydFilename.value.trim();
    if (!hydPath) { alert('Please define hydrological (*.hyd) file.'); return; }
    const start = obj.startTime.value, stop = obj.stopTime.value, timeZone = getLastTimeZone();
    if (!start || !stop) { alert("The fields 'Start time' and 'Stop time' are required"); return; }
    const startMs = Date.parse(String(start).replace(' ', 'T')), stopMs = Date.parse(String(stop).replace(' ', 'T'));
    if (Number.isFinite(startMs) && Number.isFinite(stopMs) && startMs >= stopMs) {
        alert("'Start time' must be before 'Stop time'."); return;
    }
    const nLayers = obj.nLayers.value.trim();
    if (!nLayers) { alert("The field 'Nr. sigma layers' is required"); return; }
    const folderName = t.name.value.trim();
    if (!t.selector.value) { alert('Please specify type of simulation.'); return; }
    if (!validateScenarioName(folderName)) { return; }
    if (waqContent.includes(folderName) && folderName !== loadedScenario &&
        !confirm(`Scenario '${folderName}' already exists. Do you want to overwrite it?`)) { return; }
    const sources = tableRows(obj.sourcesTable), obsPoints = tableRows(obj.obsPointTable);
    const loadsData = tableRows(obj.loadsPointTable);
    if (loadsData.length === 0) { alert('No loads data found. Please add at least one load.'); return; }
    const errors = [...validatePoints(obsPoints, 'Observation points'), ...validatePoints(loadsData, 'List of loads')];
    if (errors.length > 0) { showErrors(errors); return; }
    if (t.maxiter.value === '' || !(parseInt(t.maxiter.value) > 0)) { alert('Please define maximum number of iterations.'); return; }
    if (t.tolerance.value === '' || !(parseFloat(t.tolerance.value) > 0)) { alert('Please define tolerance.'); return; }
    // Rebuild the time table from the current tables and name, so the saved table is never stale
    const processed = await processTimeSeries(t); if (!processed) { return; }
    const useforLines = t.usefors.value.split('\n').map(line => line.trim()).filter(Boolean);
    if (useforLines.length === 0) { alert("The field 'Assigned Substance' must have at least one value"); return; }
    const badLine = useforLines.find(line => !USEFOR_PATTERN.test(line));
    if (badLine) { alert(`Invalid line in 'Assigned Substance':\n${badLine}`); return; }
    // Paths, segment and exchange counts are read from the .hyd file by the server
    const params = { mode, projectName: name, key: t.selector.value, folderName,
        hydName: hydPath, nLayers, startTime: toUTC(start, timeZone), stopTime: toUTC(stop, timeZone),
        useforsFrom: Array.from(t.useforsFrom.options).map(o => o.value),
        useforsTo: Array.from(t.useforsTo.options).map(o => o.value),
        usefors: useforLines.join('\n'), sources, obsPoints, loadsData,
        timeTable: obj.timePreview.value.trim(), initial: t.initialArea.value.trim(),
        maxiter: t.maxiter.value, tolerance: t.tolerance.value, scheme: t.scheme.value
    };
    const result = await withOverlay("Saving water quality configurations.\nPlease wait...",
        () => jsonLoader('waq_config_writer', params));
    if (result.status === 'error') { alert(result.message); return; }
    if (!waqContent.includes(folderName)) { waqContent = [...waqContent, folderName].sort(); }
    renderWaqList(folderName); setScenarioButtons(true);
    obj.waqSelector.style.display = "flex"; obj.waqLabel.style.display = "flex";
    loadedScenario = folderName; alert(result.message);
}