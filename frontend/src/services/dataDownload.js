import { setupTabs } from "./tabManager.js";
import { initMap } from "./visualizationMap.js";
import { getDataFromTable, signalSender, jsonLoader, fillTable,
    formatDate, moveWindow, closeWindow, deleteTable, getUser
} from "./commonFunctions.js";
import { plotTimeSeries } from "./chartManager.js";
import { L } from "./constant.js";

const hoverTooltip = L.tooltip({
    permanent: false, direction: 'bottom',
    sticky: true, offset: [0, 10], className: 'custom-tooltip'
});

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
    // overFlowCheckbox: $("overflow-checkbox"), temperatureCheckbox: $("temperature-checkbox"),
    // evaporationCheckbox: $("evaporation-checkbox"), weirCheckbox: $("weir-checkbox"),
    stationSelectedLabel: $("station-selected-label"), resertStationBtn: $("reset-station-btn"),
    downloadListContainer: $("download-list-container"), downloadListArea: $("download-list")
};

let plotChecked = true, waterFlowLayer = null, waterLevelLayer = null,
    overFlowLayer = null, tempLayer = null, preLayer = null,
    weirLayer = null, evaLayer = null, currentProject = null;

setupTabs(document); await getProject();
const mapObj = await initMap('leaflet-map-data');
updateManager(); 


async function getProject() { 
    const userName = await getUser();
    currentProject = userName.split('/').pop();
}

function updateManager() {
    const startOfDay = new Date(), now = new Date();
    startOfDay.setHours(0, 0, 0, 0);
    moveWindow(obj.plotDataHeader, obj.plotDataContainer);
    closeWindow(obj.plotDataCloseBtn, obj.plotDataContainer);
    hightlightRows(obj.stationSelectedTable);
    obj.plotStart.value = formatDate(startOfDay); obj.plotEnd.value = formatDate(now);
    obj.downloadStart.value = formatDate(startOfDay); obj.downloadEnd.value = formatDate(now);
    obj.selectBox.addEventListener("click", () => { obj.checkboxList.style.display === 'block'; });
    document.addEventListener('click', (event) => {
        if (!obj.dropdown.contains(event.target)) obj.checkboxList.style.display = 'none';
    });
    // Toggle sub tabs
    document.querySelectorAll('[data-tab]').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.getAttribute('data-tab');
            if (tabName === 'rosim-tab-1') { 
                plotChecked = true; deleteTable(obj.stationSelectedTable); 
            }
            else if (tabName === 'rosim-tab-2') { plotChecked = false; }
            setTimeout(() => { mapObj.invalidateSize(); }, 10);
            obj.stationSelectedLabel.style.display = 'none';
            updateLayerTooltips(waterFlowLayer); updateLayerTooltips(waterLevelLayer);
            updateLayerTooltips(overFlowLayer); updateLayerTooltips(tempLayer);
            updateLayerTooltips(preLayer); updateLayerTooltips(evaLayer); 
            updateLayerTooltips(weirLayer);
        });
    });
    obj.waterFlowCheckbox.addEventListener('change', async (e) => { 
        if (e.target.checked === true) {
            waterFlowLayer = await loadStations(
                currentProject, e.target, obj.stationTable, 'water flow', 'flow', waterFlowLayer
            );
        } else { waterFlowLayer = clearMap(waterFlowLayer); deleteTable(obj.stationTable); }
    });
    obj.waterLevelCheckbox.addEventListener('change', async (e) => {
        if (e.target.checked === true) {
            waterLevelLayer = await loadStations(
                currentProject, e.target, obj.stationTable, 'water level', 'level', waterLevelLayer
            );
        } else { waterLevelLayer = clearMap(waterLevelLayer); deleteTable(obj.stationTable); }
    });
    obj.rainfallCheckbox.addEventListener('change', async (e) => {
        if (e.target.checked === true) {
            preLayer = await loadStations(
                currentProject, e.target, obj.stationTable, 'rainfall', 'rain', preLayer
            );
        } else { preLayer = clearMap(preLayer); deleteTable(obj.stationTable); }
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
        try { 
            const dirHandle = await window.showDirectoryPicker();
            obj.downloadListContainer.style.display = 'flex'; obj.downloadListArea.value = '';
            for (const file of tableData.rows) {
                const name = `${file[0]}_${startTime.replace(' ', '_')}-${endTime.replace(' ', '_')}`;
                obj.downloadListArea.value += `Downloading: ${name} ...\n`;
                const contents = { mode: downloadType, downloadInterval: interval,
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
    mapOptions(mapObj);
}

function mapOptions(mapObject) {
    mapObject.on('mousemove', function (e) { 
        if (!plotChecked && (waterFlowLayer || waterLevelLayer || overFlowLayer || tempLayer || preLayer || weirLayer || evaLayer)) {
            const html = `- Left click to select station to add the download list.<br>- Right click to remove the last station.`;
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            mapObject.openTooltip(hoverTooltip);
        } else { if (hoverTooltip) mapObject.closeTooltip(hoverTooltip); }
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
        const feature = layer.feature;
        let note = '';
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

async function loadStations(projectName, target, table, label, type, layer) {
    const data = getDataFromTable(table, true); let filter = [];
    if (type === 'rain') { filter = ['permanent', 'permanentTemp']; }
    else if (type === 'flow') { filter = ['flow']; }
    else if (type === 'level') { filter = ['overflow']; }
    const fillter = data.rows.filter(row => !filter.includes(row[1])); layer = clearMap(layer);
    if (target.checked) {
        signalSender('showOverlay', `Getting ${label} stations from Regnbyge.no.\nThis takes a while (especially the first time).\nPlease wait ...`);
        const contents = { projectName: projectName, key: type };
        const response = await jsonLoader('init_station', contents);
        signalSender('hideOverlay');
        if (response.status === "error") { alert(response.message); target.checked = false; return; }
        const stationNames = response.content.name, stationLocations = response.content.point;
        layer = await pointPloter(stationLocations, type);
        stationNames.forEach(item => fillter.push(item));
    }
    deleteTable(table); fillTable(fillter, table, true);
    if (fillter.length > 0) { obj.plotContainer.style.display = 'flex';
    } else { obj.plotContainer.style.display = 'none'; }
    return layer;
}

async function pointPloter(points, pointType) {
    let iconUrl = `/src_frontend/images/station.png?v=${Date.now()}`, note = '';
    if (pointType === 'flow') { iconUrl = `/src_frontend/images/water_flow.png?v=${Date.now()}`; }
    else if (pointType === 'level') { iconUrl = `/src_frontend/images/water_level.png?v=${Date.now()}`; }
    else if (pointType === 'rain') { iconUrl = `/src_frontend/images/rain.png?v=${Date.now()}`; }
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
                    const mode = feature.properties.mode;
                    const startTime = obj.plotStart.value, endTime = obj.plotEnd.value, interval = obj.plotInterval.value;
                    const titleY = obj.plotInterval.selectedOptions[0].text;
                    signalSender('showOverlay', `Getting '${obj.plotInterval.selectedOptions[0].text}' for station '${name}'.\nThis takes a while. Please wait...`);
                    const contents = { 
                        id: [id], name: name, mode: mode, startTime: startTime, 
                        endTime: endTime, interval: interval 
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