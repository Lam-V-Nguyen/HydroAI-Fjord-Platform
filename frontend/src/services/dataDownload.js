import { setupTabs } from "./tabManager.js";
import { initMap } from "./visualizationMap.js";
import { getDataFromTable, signalSender, jsonLoader, fillTable,
    formatDate, moveWindow, closeWindow, deleteTable, getUser
} from "./commonFunctions.js";
import { plotTimeSeries } from "./chartManager.js";
import { L, getLastTimeZone } from "./constant.js";

const hoverTooltip = L.tooltip({
    permanent: false, direction: 'bottom',
    sticky: true, offset: [0, 10], className: 'custom-tooltip'
});
window._uploadedGISFiles = {}; window._gisFileIdCounter = 0;

const $ = (id) => document.getElementById(id);
const obj = { 
    plotDataContainer: $("plot-station-window"), plotDataHeader: $("plot-station-header"),
    plotDataCloseBtn: $("close-station-plot"), selectBox: $("select-object"),
    checkboxList: $("checkbox-list"), dropdown: $("select-object"), downloadInterval: $("interval-download"),
    stationSelectedTable: $("station-selected-table"), plotStart: $("start-plot"), 
    plotEnd: $("end-plot"), plotInterval: $("interval-plot"), downloadBtn: $("download-btn"), 
    downloadStart: $("start-download"), downloadEnd: $("end-download"),
    typeSelector: $("type-download"), plotContainer: $("plot-container"), 
    stationTable: $("station-table"), waterFlowCheckbox: $("water-flow-checkbox"),
    waterLevelCheckbox: $("water-level-checkbox"), rainfallCheckbox: $("rainfall-checkbox"),
    dataGISBtn: $("upload-gis-btn"), dataGISFile: $("data-gis-file"), dataGISContainer: $("data-gis-container"),
    clientId: $("regnbyge-client-id"), clientSecret: $("regnbyge-client-secret"), 
    clientRemember: $("regnbyge-remember-btn"), 
    clientUserName: $("regnbyge-client-username"), clientPassword: $("regnbyge-client-password"),
    // overFlowCheckbox: $("overflow-checkbox"), temperatureCheckbox: $("temperature-checkbox"),
    // evaporationCheckbox: $("evaporation-checkbox"), weirCheckbox: $("weir-checkbox"),
    stationSelectedLabel: $("station-selected-label"), resertStationBtn: $("reset-station-btn"),
    downloadListContainer: $("download-list-container"), downloadListArea: $("download-list"),
    // ERA5 options
    era5LocationBtn: $("era5-location-btn"), era5Lat: $("era5-latitude"), 
    era5Lon: $("era5-longitude"), era5WindSpeed: $("wind-speed-checkbox"),
    era5WWindU: $("wind-u-checkbox"), era5WWindV: $("wind-v-checkbox"),
    era5Start: $("era5-start"), era5End: $("era5-end"), era5Table: $("era5-table"), 
    era5LogContainer: $("era5-log-container"), era5LogText: $("era5-log-text"),
    era5DownloadBtn: $("era5-download-btn"), era5SaveBtn: $("era5-save-btn")
};

let activeProject = null, plotChecked = true, waterFlowLayer = null, 
    waterLevelLayer = null, overFlowLayer = null, tempLayer = null, preLayer = null,
    weirLayer = null, evaLayer = null, currentProject = null, era5Checked = false,
    name = null, secret = null, userName = null, password = null;

setupTabs(document); await getProject();
const mapObj = await initMap('leaflet-map-data');
savePassword(); await loadClient(); updateManager();


async function getProject() { 
    const userName = await getUser();
    currentProject = userName.split('/').pop();
}

function savePassword() {
    document.querySelectorAll('.toggle-password').forEach(btn => {
        btn.addEventListener('click', function(e) {
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
    obj.clientRemember.addEventListener('click', async() => {
        name = obj.clientId.value; secret = obj.clientSecret.value; 
        userName = obj.clientUserName.value; password = obj.clientPassword.value;
        if (name === '' || secret === '' || userName === '' || password=== '') {
            alert('Please check registration information and try again.\nInformation is NOT saved.'); return;
        }
        const content = { projectName: currentProject, clientName: name,
            clientSecret: secret, clientUsername: userName, clientPassword: password
        };
        const response = await jsonLoader('save_client', content);
        alert(response.message); if (response.status === "error") { return; }
    });

}

async function loadClient () {
    const response = await jsonLoader('load_client', { projectName: currentProject });
    name = response.content.client_id;
    secret = response.content.client_secret;
    userName = response.content.client_username;
    password = response.content.client_password;
    obj.clientId.value = name; obj.clientSecret.value = secret;
    obj.clientUserName.value = userName; obj.clientPassword.value = password;
}


function updateManager() {
    const startOfDay = new Date(), now = new Date();
    startOfDay.setHours(0, 0, 0, 0);
    moveWindow(obj.plotDataHeader, obj.plotDataContainer);
    closeWindow(obj.plotDataCloseBtn, obj.plotDataContainer);
    hightlightRows(obj.stationSelectedTable);
    obj.plotStart.value = formatDate(startOfDay); obj.plotEnd.value = formatDate(now);
    obj.downloadStart.value = formatDate(startOfDay); obj.downloadEnd.value = formatDate(now);
    obj.era5Start.value = formatDate(startOfDay); obj.era5End.value = formatDate(now);
    obj.selectBox.addEventListener("click", () => { obj.checkboxList.style.display === 'block'; });
    document.addEventListener('click', (event) => {
        if (!obj.dropdown.contains(event.target)) obj.checkboxList.style.display = 'none';
    });
    // Toggle sub tabs
    document.querySelectorAll('[data-tab]').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.getAttribute('data-tab');
            if (tabName === 'regnbyge-tab-2') { 
                plotChecked = true; deleteTable(obj.stationSelectedTable); 
            }
            else if (tabName === 'regnbyge-tab-3') { plotChecked = false; }
            else if (tabName === 'era5-tab') {
                // Clear map
                plotChecked = true; deleteTable(obj.stationSelectedTable); 
                obj.waterFlowCheckbox.checked = false;
                obj.waterFlowCheckbox.dispatchEvent(new Event('change'));
                obj.waterLevelCheckbox.checked = false;
                obj.waterLevelCheckbox.dispatchEvent(new Event('change'));
                obj.rainfallCheckbox.checked = false;
                obj.rainfallCheckbox.dispatchEvent(new Event('change'));
            }
            setTimeout(() => { mapObj.invalidateSize(); }, 10);
            obj.stationSelectedLabel.style.display = 'none';
            updateLayerTooltips(waterFlowLayer); updateLayerTooltips(waterLevelLayer);
            updateLayerTooltips(overFlowLayer); updateLayerTooltips(tempLayer);
            updateLayerTooltips(preLayer); updateLayerTooltips(evaLayer); 
            updateLayerTooltips(weirLayer);
        });
    });
    // Work on Regnbyge option
    obj.waterFlowCheckbox.addEventListener('change', async (e) => { 
        const filter = ['flow'];
        if (e.target.checked === true) {
            waterFlowLayer = await loadStations(
                currentProject, e.target, obj.stationTable, 'water flow', 
                'flow', waterFlowLayer, filter
            );
        } else { 
            waterFlowLayer = clearMap(waterFlowLayer);
            removeStationsByType(obj.stationTable, filter);
        }
    });
    obj.waterLevelCheckbox.addEventListener('change', async (e) => {
        const filter = ['overflow'];
        if (e.target.checked === true) {
            waterLevelLayer = await loadStations(
                currentProject, e.target, obj.stationTable, 'water level', 
                'level', waterLevelLayer, filter
            );
        } else { 
            waterLevelLayer = clearMap(waterLevelLayer);
            removeStationsByType(obj.stationTable, filter);
        }
    });
    obj.rainfallCheckbox.addEventListener('change', async (e) => {
        const filter = ['permanent', 'permanentTemp'];
        if (e.target.checked === true) {
            preLayer = await loadStations(
                currentProject, e.target, obj.stationTable, 'rainfall', 
                'rain', preLayer, filter
            );
        } else { 
            preLayer = clearMap(preLayer);
            removeStationsByType(obj.stationTable, filter);
        }
    });
    obj.typeSelector.addEventListener('change', () => {
        selectStations(obj.typeSelector.value, obj.stationSelectedTable, obj.stationSelectedLabel);
    });
    obj.downloadBtn.addEventListener('click', async () => { 
        const tableData = getDataFromTable(obj.stationSelectedTable, true);
        const n = obj.stationSelectedTable.querySelectorAll('tr.selected').length;
        if (tableData.rows.length === 0 || n === 0) { 
            alert('No station selected. Please select a station from the map first.'); return; 
        }
        const startTime = obj.downloadStart.value, endTime = obj.downloadEnd.value,
            downloadType = obj.typeSelector.value, interval = obj.downloadInterval.value;
        if (startTime === '' || endTime === '') { 
            alert('Please select start and end time to download.'); return; 
        }
        try { 
            const dirHandle = await window.showDirectoryPicker();
            obj.downloadListContainer.style.display = 'flex'; obj.downloadListArea.value = '';
            for (const file of tableData.rows) {
                const name = `${file[0]}_${startTime.replace(' ', '_')}-${endTime.replace(' ', '_')}`;
                obj.downloadListArea.value += `Downloading: ${name} ...\n`;
                const contents = { mode: downloadType, downloadInterval: interval, timeZone: getLastTimeZone(),
                    startTime: startTime, endTime: endTime, id: [Number(file[1].trim())] };
                const response = await jsonLoader('download_station', contents);
                if (response.status === 'error') { 
                    alert(response.message);
                    obj.downloadListArea.value += `Error downloading: [${response.message}] \n`;
                    obj.downloadListArea.value += `Downloading [${name}] is skipped.\n`;
                    continue; 
                }
                let nameSaved = name.replace('Å', 'Aa').replace('å', 'aa').replace('Æ', 'Ae').replace('æ', 'ae');
                nameSaved = nameSaved.replace('Ø', 'oo').replace(/[^a-zA-Z0-9_\-]/g, '_');
                nameSaved = `${nameSaved}.csv`;
                if (dirHandle !== null) {
                    const fileHandle = await dirHandle.getFileHandle(nameSaved, {create: true});
                    const writable = await fileHandle.createWritable();
                    await writable.write("\uFEFF" + response.content);
                    await writable.close();
                } else { 
                    const blob = new Blob([response.content], { type: 'text/csv;charset=utf-8;' });
                    const url = URL.createObjectURL(blob);
                    const link = document.createElement('a');
                    link.setAttribute('href', url);
                    link.setAttribute('download', nameSaved);
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                }
                obj.downloadListArea.value += `Saved file: ${nameSaved}.\n`;
            }
            obj.downloadListArea.value += '\nDownload complete.'; alert('Download complete.');
        } catch (error) { 
            alert(error.message || error); obj.downloadListContainer.style.display = 'none';
            obj.downloadListArea.value = ''; return;
        }
    });
    obj.resertStationBtn.addEventListener('click', async () => {
        if (obj.waterFlowCheckbox.checked === false && 
            obj.waterLevelCheckbox.checked === false && 
            obj.rainfallCheckbox.checked === false) {
            alert('No station type selected. Please select at least one type first.'); return;
        }
        const ok = confirm('Do you want to delete the selected stations?');
        if (!ok) return;
        signalSender('showOverlay', 'Deleting Station(s). Please wait...');
        const contents = { 
            projectName: currentProject, flow: obj.waterFlowCheckbox.checked, 
            level: obj.waterLevelCheckbox.checked, rain: obj.rainfallCheckbox.checked
        };
        const response = await jsonLoader('reset_station', contents);
        obj.waterFlowCheckbox.checked = false; waterFlowLayer = clearMap(waterFlowLayer);
        obj.waterLevelCheckbox.checked = false; waterLevelLayer = clearMap(waterLevelLayer);
        obj.rainfallCheckbox.checked = false; preLayer = clearMap(preLayer);           
        alert(response.message); signalSender('hideOverlay');
    });
    // Regnbyge upload GIS data
    obj.dataGISBtn.addEventListener('click', () => { obj.dataGISFile.click(); });
    obj.dataGISFile.addEventListener('change', async (event) => {
        const value = event.target.value;
        const file = event.target.files[0]; if (!file) return;
        const filename = file?.name || "";
        signalSender('showOverlay', `Uploading GIS data '${filename}'. Please wait...`);
        const formData = new FormData(); formData.append('file', file);
        const response = await fetch('/data_upload_gis', { method: 'POST', body: formData });
        const data = await response.json(); signalSender('hideOverlay');
        if (data.status === "error") { return; }
        event.target.value = '';
        await addGISFileToList(obj.dataGISContainer, filename, data.content);
    });
    // Work on ERA5
    obj.era5LocationBtn.addEventListener('click', () => { era5Checked = true; });
    obj.era5WindSpeed.addEventListener('change', (e) => {
        if (e.target.checked === true) { 
            obj.era5WWindU.checked = true ; obj.era5WWindV.checked = true;
        }
    });
    obj.era5DownloadBtn.addEventListener('click', async () => {
        const lat = obj.era5Lat.value, lon = obj.era5Lon.value;
        if (lat === '' || lon === '') { 
            alert('Please select a location.'); return; 
        }
        const startTime = obj.era5Start.value, endTime = obj.era5End.value;
        if (startTime === '' || endTime === '') { 
            alert('Please select start and end time to download.'); return; 
        }
        const selectedValues = [...document.querySelectorAll(
            '#era5-variables-grid input[type="checkbox"]:checked'
        )].map(checkbox => ({
            value: checkbox.value, label: checkbox.getAttribute('data-label'),
            des: checkbox.parentElement.textContent.trim()
        }));
        if (selectedValues.length === 0) { 
            alert('Please select at least one variable to download.'); return; 
        }
        try {
            const statusRes = await jsonLoader('check_download_status_era5', {projectName: currentProject});
            if (statusRes.status === "running") { alert("Weather download is already running."); return; }
            obj.era5LogText.value = ''; obj.era5LogContainer.style.display = 'flex';
            obj.era5SaveBtn.style.display = 'none'; obj.era5Table.style.display = 'none';
            const contents = { 
                projectName: currentProject, lat: lat, lon: lon, 
                startTime: startTime, endTime: endTime, timeZone: getLastTimeZone(), 
                variables: selectedValues.map(v => v.value)
            };
            const data = await jsonLoader('download_era5', contents);
            if (data.status === 'error') { alert(data.message); return; }
            updateLog(currentProject, obj.era5LogText, 2, 'era5', async () => {
                alert('Downloading weather completed.');
                const content_csv = {projectName: currentProject, timeZone: getLastTimeZone()};
                const csv = await jsonLoader('upload_era5_csv', content_csv);
                if (csv.status === 'error') { alert(csv.message); return; }
                addDataToTable(obj.era5Table, csv.columns, csv.content);
                obj.era5SaveBtn.style.display = 'block';
                obj.era5LogContainer.style.display = 'none';
                obj.era5Table.style.display = 'table';
            });
        } catch (error) { 
            alert(error.message || error); 
            obj.era5SaveBtn.style.display = 'none'; return;
        }
    });
    obj.era5SaveBtn.addEventListener('click', async () => {
        const data = getDataFromTable(obj.era5Table, true);
        if (data.rows.length === 0) { alert('No data to save.'); return; }
        const response = await jsonLoader('save_era5', {data: data});
        if (response.status === 'ok') { 
            await saveCSVSmart(response.content, `era5_${Date.now()}.csv`); 
        }
        alert(response.message);
    });
    mapOptions(mapObj);
}

async function addGISFileToList(container, filename, geojson){
    const id = `gis_${window._gisFileIdCounter++}`;
    window._uploadedGISFiles[id] = {
        name: filename, geojson: geojson,
        layer: null, checked: false,
    };
    const emptyMsg = container.querySelector('.gis-empty');
    if (emptyMsg) emptyMsg.remove();
    const item = document.createElement('div');
    item.className = 'gis-file-item';
    item.dataset.gisId = id;
    item.innerHTML = `
        <input type="checkbox" id="chk_${id}" data-gis-id="${id}">
        <label class="gis-file-name" for="chk_${id}" title="${filename}">
            ${filename}
        </label>
        <span class="gis-file-remove" data-gis-id="${id}" title="Remove">×</span>
    `;
    container.appendChild(item); container.style.display = 'block';
    item.querySelector('input[type="checkbox"]').addEventListener('change', (e) => {
        toggleGISLayer(id, e.target.checked);
    });
    item.querySelector('.gis-file-remove').addEventListener('click', () => {
        removeGISFile(container, id);
    });
    return id;
}

function createGISLayer(geojson, name) {
    if (!window.L) return null;
    const hue1 = Math.floor(Math.random() * 360), hue2 = Math.floor(Math.random() * 360);
    const fillColor = `hsl(${hue1}, 70%, 50%)`, color = `hsl(${hue2}, 70%, 50%)`;
    return L.geoJSON(geojson, {
        style: {
            color: color, weight: 2, fillColor: fillColor,
            opacity: 1, fillOpacity: 0.2,
        },
        onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            const popupContent = Object.entries(props)
                .slice(0, 10)
                .map(([k, v]) => `<b>${k}</b>: ${v}`)
                .join('<br>');
            if (popupContent) {
                layer.bindPopup(`<b>${name}</b><hr>${popupContent}`);
            }
        },
    });
}

function removeGISFile(container, id) {
    const fileInfo = window._uploadedGISFiles[id];
    if (!fileInfo) return;
    if (fileInfo.layer && mapObj) {
        mapObj.removeLayer(fileInfo.layer);
    }
    const item = container.querySelector(`.gis-file-item[data-gis-id="${id}"]`);
    if (item) item.remove();
    delete window._uploadedGISFiles[id];
    if (Object.keys(window._uploadedGISFiles).length === 0) {
        container.style.display = 'none';
    }
}

function toggleGISLayer(id, checked) {
    const fileInfo = window._uploadedGISFiles[id];
    if (!fileInfo) return; fileInfo.checked = checked;
    if (checked) {
        if (!fileInfo.layer) {
            fileInfo.layer = createGISLayer(fileInfo.geojson, fileInfo.name);
        }
        if (fileInfo.layer && mapObj) { fileInfo.layer.addTo(mapObj); }
    } else {
        if (fileInfo.layer && mapObj) { mapObj.removeLayer(fileInfo.layer); }
    }
}

function addDataToTable(table, header, data) {
    table.querySelector('thead')?.remove();
    table.querySelector('tbody')?.remove();
    const thead = document.createElement('thead');
    const trHead = document.createElement('tr');
    header.forEach(col => {
        const th = document.createElement('th');
        th.textContent = col; trHead.appendChild(th);
    });
    thead.appendChild(trHead); table.prepend(thead);
    const tbody = document.createElement('tbody');
    table.appendChild(tbody);
    fillTable(data, table, true);
}

export function updateLog(currentProject, info, seconds, key, onFinish, reloadLog = false) {
    const new_key = `${currentProject}_${key}`; let lastOffset = 0; activeProject = new_key; 
    async function loop() {
        if (activeProject !== new_key) return;
        try {
            const res = await fetch(
                `/log_tail_download_era5/${currentProject}?offset=${lastOffset}&log_file=log.txt`
            );
            const statusRes = await jsonLoader('check_download_status_era5', {projectName: currentProject});
            if (res.ok) {
                const data = await res.json();
                if (Array.isArray(data.lines)) {
                    if (reloadLog) { info.value = data.lines.join("\n");
                    } else {
                        for (const line of data.lines) { info.value += line + "\n"; }
                    }
                }
                if (!reloadLog) { lastOffset = data.offset; }
            }
            if (statusRes.status !== "running") {
                if (statusRes.message) { info.value += "\n" + statusRes.message + "\n"; }
                if (statusRes.status === 'finished' && onFinish) { await onFinish(); }
                return;
            }
        } catch (error) { alert(error); return; }
        setTimeout(loop, seconds * 1000);
    }
    loop();
}

async function saveCSVSmart(csvString, suggestedName) {
    // Try File System Access API
    if (window.showSaveFilePicker) {
        try {
            const handle = await window.showSaveFilePicker({
                suggestedName,
                types: [{ description: 'CSV', accept: { 'text/csv': ['.csv'] } }]
            });
            const writable = await handle.createWritable();
            await writable.write(csvString);
            await writable.close(); return true;
        } catch (err) {
            if (err.name === 'AbortError') return false; // user cancel
            console.warn('Picker failed, fallback to download:', err);
        }
    }
    // Fallback: <a download>
    const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = suggestedName;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
    return true;
}

function mapOptions(mapObject) {
    mapObject.on('mousemove', function (e) { 
        if (!plotChecked && (waterFlowLayer || waterLevelLayer || overFlowLayer || tempLayer || preLayer || weirLayer || evaLayer)) {
            const html = `- Left-click to select station and add to the download list.<br>- Right-click to remove the last station.`;
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            mapObject.openTooltip(hoverTooltip);
        } else if (era5Checked) {
            mapObject.getContainer().style.cursor = "crosshair";
            const html = `Select average location.`;
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            mapObject.openTooltip(hoverTooltip);
        } else { if (hoverTooltip) mapObject.closeTooltip(hoverTooltip); }
    });
    mapObject.on('click', async function (e) {
        if (era5Checked) {
            const lat = e.latlng.lat.toFixed(1), lon = e.latlng.lng.toFixed(1);
            obj.era5Lat.value = lat; obj.era5Lon.value = lon; 
            mapObject.getContainer().style.cursor = ""; era5Checked = false;
        }
    });
    mapObject.on('contextmenu', async function (e) { 
        e.originalEvent.preventDefault();
        if (!plotChecked) { 
            const tableData = getDataFromTable(obj.stationSelectedTable, true);
            if (!tableData || !tableData.rows || tableData.rows.length === 0) return;
            // Remove the last station
            const newRows = tableData.rows.slice(0, -1);
            fillTable(newRows, obj.stationSelectedTable, true);
        }
    });
}

function hightlightRows(table) {
    const tbody = table.querySelector('tbody');
    const trList = Array.from(tbody.querySelectorAll('tr'));
    let lastSelectedIndex = null;
    tbody.addEventListener('click', (event) => {
        const tr = event.target.closest('tr');
        if (!tr) return;
        const index = trList.indexOf(tr);
        if (event.shiftKey && lastSelectedIndex !== null) { // Shift click
            const [start, end] = [lastSelectedIndex, index].sort((a, b) => a - b);
            for (let i = start; i <= end; i++) {
                trList[i].classList.add('selected');
            }
        } else if (event.ctrlKey || event.metaKey) { // Ctrl/Cmd click
            tr.classList.toggle('selected');
        } else { // Single click
            if (tr.classList.contains('selected')) { tr.classList.remove('selected'); }
            else { tr.classList.add('selected'); }
        }
        lastSelectedIndex = index;
        const n = obj.stationSelectedTable.querySelectorAll('tr.selected').length;
        obj.stationSelectedLabel.innerHTML = `Station(s) selected: ${n}`;
    });
}

function updateLayerTooltips(layerGroup) {
    if (!layerGroup) return;
    layerGroup.eachLayer(layer => {
        if (!layer.feature) return;
        const feature = layer.feature; let note = '';
        if (plotChecked) {
            note = `<hr style="border-top: 1px solid #0414f5; margin: 5px 0;">
                <span style="display:block;font-weight:bold;text-align:center;">
                Click to plot raw data</span>`;
        }
        const content = `
            <div style="font-size:14px;border-radius:10px;">
                <span style="display:block;text-align:center;font-weight:bold;">
                    ${feature.properties.name || 'No name'}
                </span>
                <hr style="border-top:1px solid #0414f5;margin:5px 0;">
                ${Object.entries(feature.properties).filter(([key]) => key !== 'name' && key !== 'mode')
                    .map(([key, value]) => `• ${key}: ${value}<br>`).join('')}
                ${note}
            </div>`;
        layer.setTooltipContent(content);
    });
}

async function loadStations(projectName, target, table, label, type, layer, filter) {
    const data = getDataFromTable(table, true);
    const filtered = data.rows.filter(row => !filter.includes(row[1])); layer = clearMap(layer);
    if (target.checked) {
        signalSender('showOverlay', `Getting ${label} stations from Regnbyge.no.\nThis takes a while (especially the first time).\nPlease wait ...`);
        const contents = { 
            projectName: projectName, key: type, clientID: name,
            clientSecret: secret, clientUserName: userName, clientPassword: password
        };
        const response = await jsonLoader('init_station', contents);
        signalSender('hideOverlay');
        if (response.status === "error") { alert(response.message); target.checked = false; return; }
        const stationNames = response.content.name, stationLocations = response.content.point;
        layer = await pointPloter(stationLocations, type);
        stationNames.forEach(item => filtered.push(item));
    }
    deleteTable(table); fillTable(filtered, table, true);
    if (filtered.length > 0) { obj.plotContainer.style.display = 'flex';
    } else { obj.plotContainer.style.display = 'none'; }
    return layer;
}

function removeStationsByType(table, filter) {
    const data = getDataFromTable(table, true);
    const remaining = data.rows.filter(row => !filter.includes(row[1]));
    deleteTable(table);
    if (remaining.length > 0) { fillTable(remaining, table, true); }
}

async function pointPloter(points, pointType) {
    let iconUrl = `/src_frontend/images/station.png?v=${Date.now()}`, note = '';
    if (pointType === 'flow') { iconUrl = `/src_frontend/images/water_flow.png?v=${Date.now()}`; }
    else if (pointType === 'level') { iconUrl = `/src_frontend/images/water_level.png?v=${Date.now()}`; }
    else if (pointType === 'rain') { iconUrl = `/src_frontend/images/rain.png?v=${Date.now()}`; }
    const timeZone = getLastTimeZone();
    const tempLayer = L.geoJSON(points, {
        pointToLayer: (_, latlng) => {
            const marker = L.marker(latlng, {
                icon: L.icon({
                    iconUrl: iconUrl, iconSize: [20, 20], iconAnchor: [10, 10]
                }),
            });
            return marker;
        },
        onEachFeature: (feature, layer) => {
            layer.on('click', async () => { 
                const id = feature.properties.id, name = feature.properties.name;
                if (plotChecked) {
                    const mode = feature.properties.mode, interval = obj.plotInterval.value;
                    const startTime = obj.plotStart.value, endTime = obj.plotEnd.value;
                    if (startTime === '' || endTime === '') { alert('Please select a time range to plot.'); return; }
                    const titleY = obj.plotInterval.selectedOptions[0].text;
                    signalSender('showOverlay', 
                        `Getting '${obj.plotInterval.selectedOptions[0].text}' for station '${name}'.\nThis takes a while. Please wait...`
                    );
                    const contents = { 
                        id: [id], name: name, mode: mode, timeZone: timeZone,
                        startTime: startTime, endTime: endTime, interval: interval,
                        clientID: name, clientSecret: secret, clientUserName: userName, 
                        clientPassword: password
                    };
                    const response = await jsonLoader('plot_station', contents);
                    signalSender('hideOverlay');
                    if (response.status === "error") { alert(response.message); return; }
                    const chartTitle = `Station: ${name}`, titleX = 'Time';
                    await plotTimeSeries(
                        obj.plotDataContainer, chartTitle, response.content, name, titleX, titleY
                    );
                } else {
                    const type = feature.properties.type;
                    const data = [name, String(id), type];
                    const tableData = getDataFromTable(obj.stationSelectedTable, true);
                    const exitCheck = tableData.rows.some(row => row.length === data.length &&
                        row.every((value, index) => value === data[index]));
                    if (!exitCheck) { fillTable([data], obj.stationSelectedTable, false); }
                    selectStations(obj.typeSelector.value, obj.stationSelectedTable, obj.stationSelectedLabel);
                }
            });
            if (plotChecked) {
                note = `<hr style="border-top: 1px solid #5d5d61ff; margin: 5px 0 5px 0;">
                    <span style="display: block; font-weight: bold; text-align: center; line-height: 1.0;">Click to plot time-series data</span>`
            } else { note = ''; }
            const tooltip = `<div style="font-size: 14px; border-radius: 10px;">
                <span style="display: block; text-align: center; font-weight: bold; line-height: 1.0;">${feature.properties.name || 'No name'}</span>
                <hr style="border-top: 1px solid #5d5d61ff; margin: 5px 0 5px 0;">
                ${Object.entries(feature.properties).filter(([key]) => key !== 'name' && key !== 'mode')
                .map(([key, value]) => `<span>• ${key}: ${value}</span><br>`).join('')}${note}
            </div>`;
            layer.bindTooltip(tooltip, { sticky: true, permanent: false, direction: 'bottom', opacity: 1, offset: [0, 10] });
        }
    }).addTo(mapObj);
    const bounds = tempLayer.getBounds();
    if (bounds.isValid()) { 
        setTimeout(() => { mapObj.invalidateSize(); mapObj.fitBounds(bounds); }, 0);
    }
    return tempLayer;
}

function selectStations(dataType, table, label) {
    const checkList = [dataType];
    if (dataType === 'permanent') { checkList.push('permanentTemp'); }
    const checkSet = new Set(checkList);
    const rows = table.querySelectorAll('tbody tr');
    let selectedCount = 0;
    rows.forEach(row => {
        const cells = row.querySelectorAll('td');
        if (cells.length < 3) return;
        const input = cells[2].querySelector('input');
        if (!input) return;
        const value = input.value.trim();
        if (checkSet.has(value)) { selectedCount++; row.classList.add('selected');
        } else { row.classList.remove('selected'); }
    });
    if (label.style.display === 'none') { label.style.display = 'flex'; }
    label.innerHTML = `Station(s) selected: ${selectedCount}`;
}

function clearMap(layer) {
    if (layer) { mapObj.removeLayer(layer); }
    return null;
}