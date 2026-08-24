import { toUTC } from "./projectSaver.js";
import { origin } from "./constant.js";


// const pendingRequests = new Map();

let zIndex = 3000, activeProject = null, lastOffset = 0;

export function startLoading(str = '') {
    const loadingContainer = document.querySelector('.loading-container');
    if (!loadingContainer) return;
    loadingContainer.querySelector('.loading-text').textContent = str;
    loadingContainer.style.display = 'flex'; 
}

export function stopLoading() { 
    const loadingContainer = document.querySelector('.loading-container');
    if (!loadingContainer) return;
    loadingContainer.style.display = "none";
}

export function signalSender(key, contents={}) {
    window.parent.postMessage({type: key, content: contents}, origin);
}

export async function htmlLoader(functionName){
    const response = await fetch(`/${functionName}`);
    if (!response.ok) { return null; }
    const data = await response.text();
    return data;
}

export async function jsonLoader(functionName, content){
    const response = await fetch(`/${functionName}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(content)});
    const data = await response.json();
    return data;
}

export function getUser(){
    return new Promise((resolve) => {
        function handler(event) {
            if (event.data.type === 'USER') {
                window.removeEventListener('message', handler);
                resolve(event.data.content);
            }
        }
        window.addEventListener('message', handler);
        window.parent.postMessage({type: "GET_USER"}, "*");
    });
}

export function moveWindow(header, container) {
    let dragging = false, offsetX = 0, offsetY = 0;
    const onMouseMove = (e) => {
        const x = e.clientX - offsetX;
        const y = e.clientY - offsetY;
        container.style.left = `${x}px`;
        container.style.top = `${y}px`;
    };
    header.addEventListener('mousedown', (e) => {
        // e.preventDefault();
        dragging = true; 
        container.style.cursor = 'move';
        document.body.style.userSelect = 'none';
        zIndex++; container.style.zIndex = zIndex;
        offsetX = e.clientX - container.offsetLeft;
        offsetY = e.clientY - container.offsetTop;
        document.addEventListener('mousemove', onMouseMove);
    });
    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const x = e.clientX - offsetX; const y = e.clientY - offsetY;
        container.style.left = `${x}px`; 
        container.style.top = `${y}px`;
    });
    document.addEventListener('mouseup', () => { 
        dragging = false;
        document.removeEventListener('mousemove', onMouseMove);
    });
}

export function closeWindow(btn, container) {
    btn.addEventListener('click', () => {
        container.style.display = "none";
    });
}

export function formatDate(date) {
    const pad = (n) => String(n).padStart(2, '0');
    const Y = date.getFullYear();
    const M = pad(date.getMonth() + 1);
    const D = pad(date.getDate());
    const h = pad(date.getHours());
    const m = pad(date.getMinutes());
    const s = pad(date.getSeconds());
    return `${Y}-${M}-${D} ${h}:${m}:${s}`;
}

export function deleteTable(table, name=null, type=''){
    const tbody = table.querySelector("tbody"); tbody.innerHTML = ""; 
    if (name != null) name.value = '';
    if (type != '') window.parent.postMessage({type: type}, origin);
}

export function getDataFromTable(table, isZeroIndexString=false){
    const columns = Array.from(
        table.querySelectorAll("thead th")).map(th => th.textContent.trim()
    );
    const rows = Array.from(table.querySelectorAll("tbody tr")).map(tr => {
        return Array.from(tr.querySelectorAll("td input")).map((input, idx) => {
            const val = input.value.trim();
            if (isZeroIndexString) return val; // Keep as string
            // Convert to number if possible
            if (idx === 0 && val) {
                const isoString = val.replace(/\//g, "-").replace("T", " ");
                return toUTC(isoString);
            }
            if (!isNaN(val) && val !== "") return parseFloat(val);
            return val;
        });
    })
    // Remove empty rows
    .filter(row => row.some(cell => cell !== "" && cell !== null && cell !== undefined));
    return {columns, rows};
}

export function fillTable(data2D, table, clear=true){
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    if (!data2D || data2D.length === 0) {
        if (clear) { tbody.innerHTML = ''; }
        return;
    }
    // Remove entire table if clear is true
    if (clear) { tbody.innerHTML = '';
    } else { 
        // Remove empty rows
        const existingRows = Array.from(tbody.querySelectorAll("tr"));
        existingRows.forEach(row => {
            const inputs = Array.from(row.querySelectorAll("input"));
            const isEmptyRow = inputs.length > 0 && inputs.every(inp => inp.value.trim() === "");
            if (isEmptyRow) row.remove();
        });
    }
    const fragment = document.createDocumentFragment();
    const numCols = data2D[0].length;
    for (const rowData of data2D) {
        const tr = document.createElement("tr");
        for (let j = 0; j < numCols; j++) {
            const td = document.createElement("td");
            const input = document.createElement("input");
            input.type = "text";
            input.value = rowData[j] ?? '';
            td.appendChild(input);
            tr.appendChild(td);
        }
        fragment.appendChild(tr);
    }
    tbody.appendChild(fragment);
}

export function interpolateJet(t) {
    const jetColors = [
        [0.0, [0, 0, 128]], [0.35, [0, 255, 255]],
        [0.5, [0, 255, 0]], [0.75, [255, 255, 0]], [1.0, [255, 0, 0]]
    ];
    for (let i = 0; i < jetColors.length - 1; i++) {
        const [t1, c1] = jetColors[i];
        const [t2, c2] = jetColors[i + 1];
        if (t >= t1 && t <= t2) {
            const f = (t - t1) / (t2 - t1);
            const r = Math.round(c1[0] + (c2[0] - c1[0]) * f);
            const g = Math.round(c1[1] + (c2[1] - c1[1]) * f);
            const b = Math.round(c1[2] + (c2[2] - c1[2]) * f);
            return `rgb(${r},${g},${b})`;
        }
    }
    return `rgb(255,0,0)`;
}

export function formatDateTime(value) {
    const d = new Date(value);
    if (isNaN(d)) return value;
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ` +
        `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function numberFormatter(num, decimals) {
    if (num === null || num === undefined || isNaN(num)) return '';
    if (num === 0) return '0';
    const n = Number(num);
    if (Math.abs(n) < 1e-3 || Math.abs(n) >= 1e6) { return n.toExponential(decimals); }
    return n.toFixed(decimals);
}

export function colorbarTicks(min, max, numStops){
    if (Math.abs(max - min) < 1e-4) return [min];
    const ticks = [], step = (max - min) / (numStops - 1);
    for (let i = 0; i < numStops; i++) {
        ticks.push(min + i * step);
    }
    return ticks;
}

// Split lines into smaller segments and sort by distance
export function splitLines(pointContainer, polygonCentroids, subset_dis) {
    const interpolatedPoints = [];
    // Convert Lat, Long to x, y
    for (let i = 0; i < pointContainer.length - 1; i++) {
        const p1 = pointContainer[i], p2 = pointContainer[i + 1];
        const pt1 = L.Projection.SphericalMercator.project(L.latLng(p1.lat, p1.lng));
        const pt2 = L.Projection.SphericalMercator.project(L.latLng(p2.lat, p2.lng));
        const dx = pt2.x - pt1.x, dy = pt2.y - pt1.y;
        const segmentDist = Math.sqrt(dx * dx + dy * dy);
        const segments = Math.max(1, Math.floor(segmentDist / subset_dis));
        // Add the first point
        const originDist = L.latLng(p1.lat, p1.lng).distanceTo(pointContainer[0]);
        interpolatedPoints.push([originDist, p1.value, p1.lat, p1.lng]);
        // Add the intermediate points        
        for (let j = 1; j < segments; j++) {
            const ratio = j / segments;
            const interpX = pt1.x + ratio * dx, interpY = pt1.y + ratio * dy;
            const latlngInterp = L.Projection.SphericalMercator.unproject(L.point(interpX, interpY));
            // Interpolate
            const location = L.latLng(latlngInterp.lat, latlngInterp.lng);
            const interpValue = interpolateValue(location, polygonCentroids);
            // Fall back to nearest centroid if interpolation fails
            if (interpValue === null || interpValue === undefined) {
                interpValue = p1.value + ratio * (p2.value - p1.value);
            }
            // Compute distance            
            const distInterp = location.distanceTo(pointContainer[0]);
            interpolatedPoints.push([distInterp, interpValue, latlngInterp.lat, latlngInterp.lng]);
        }
        // Add the last point
        const lastDist = L.latLng(p2.lat, p2.lng).distanceTo(pointContainer[0]);
        interpolatedPoints.push([lastDist, p2.value, p2.lat, p2.lng]);
    }
    // Sort by distance
    interpolatedPoints.sort((a, b) => a[0] - b[0]);
    return interpolatedPoints;
}

export async function saveCSV(filename, headers, rows) {
    const csv = [
        headers.join(","), ...rows.map(r =>
            r.map(v => `${String(v).replace(/"/g, '""')}`).join(",")
        )].join("\n");
    const handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [{description: "CSV file", accept: {"text/csv": [".csv"]}}]
    });
    const writable = await handle.createWritable();
    await writable.write(csv); await writable.close();
}

export function updateLog(currentProject, info, seconds, key, onFinish){
    const new_key = `${currentProject}_${key}`;
    activeProject = new_key; lastOffset = 0;
    async function loop() {
        if (activeProject !== new_key) return;
        try {
            const res = await fetch(
                `/log_tail_download/${currentProject}?offset=${lastOffset}&log_file=log.txt`
            );
            const statusRes = await jsonLoader('check_download_status', {projectName: currentProject});
            if (res.ok) {
                const data = await res.json();
                if (Array.isArray(data.lines)) {
                    for (const line of data.lines) { info.value += line + "\n"; }
                }
                lastOffset = data.offset;
            }
            if (statusRes.status !== "running") {
                info.value += (statusRes.message || "") + "\n"; lastOffset = 0; 
                if (statusRes.status === 'finished' && onFinish) { await onFinish(); }
                return;
            }
        } catch (error) { alert(error); return; }
        setTimeout(loop, seconds * 1000);
    }
    loop();
}

export function addRowToTable(table, list, fillValue=false){
    const tbody = table.querySelector("tbody");
    const tr = document.createElement('tr');
    list.forEach(text => {
        const td = document.createElement('td');
        const input = document.createElement('input');
        input.type = 'text'; input.placeholder = text;
        if (fillValue) input.value = text;
        td.appendChild(input); tr.appendChild(td);
    });
    tbody.appendChild(tr);
}

export function nameChecker(name) { return !/^[A-Za-z0-9_-]+$/.test(name); }

export function copyPaste(table, nCols){
    const tbody = table.querySelector('tbody');
    table.addEventListener('paste', (e) => {
        e.preventDefault();
        const text = (e.clipboardData || window.Clipboard).getData('text'); // Get clipboard data
        const rows = text.split(/\r?\n/).filter(r => r.trim() !== ''); // Split into rows 
        if (!rows.length) return;
        // Get the first row
        const firstLine = rows[0];
        const columns = firstLine.split(/\t|,/);
        if (columns.length !== nCols) { 
            alert(`The current table has ${columns.length} columns.\nNumber of columns must be ${nCols}.`); 
            return; }
        tbody.innerHTML = '';
        const data_arr = rows.map(row => row.split(/\t|,/).slice(0, nCols)); // Split into columns
        fillTable(data_arr, table);
    });
}

export async function csvUploader(event, targetText, table,
    nCols, isIgnoreHeader=true, objName=null, latitude=null, longitude=null){
    return new Promise((resolve, reject) => {
        const file = event.target.files[0];
        if (!file) { resolve(); return; }
        targetText.value = file.name;
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const text = e.target.result;
                const lines = text.split('\n').map(line => line.trim()).filter(line => line !== '');
                const parts = lines[0].split(',').map(item => item.trim());
                if (parts.length !== nCols) { 
                    alert('Number of columns should be ' + nCols + '.'); 
                    target.value = ''; resolve(); return; 
                }
                let dataLines = lines;
                if (isIgnoreHeader) dataLines = dataLines.slice(1); // Skip header
                dataLines.forEach((line, idx) => {
                    const parts = line.split(',').map(item => item.trim());
                    let data_arr = [];
                    if (parts.length === 2) {
                        data_arr = [[parts[0], parseFloat(parts[1])]];
                    } else if (parts.length === 3) {
                        data_arr = [[parts[0], parseFloat(parts[1]), parseFloat(parts[2])]];
                    } else if (parts.length === 5) {
                        if (objName && latitude && longitude) {
                            objName.value = file.name.replace('.csv', ''); 
                            if (idx === 0) {
                                latitude.value = parts[0]; longitude.value = parts[1];
                            } else if (idx === 1) { return;
                            } else {
                                data_arr = [[parts[0], parseFloat(parts[1]), parseFloat(parts[2]), 
                                    parseFloat(parts[3]), parseFloat(parts[4])]];
                            }
                        } else {
                            data_arr = [[parts[0], parseFloat(parts[1]), parseFloat(parts[2]), 
                                parseFloat(parts[3]), parseFloat(parts[4])]];
                        }
                    } else {
                        data_arr = [[parts[0], ...parts.slice(1).map(item => parseFloat(item))]];
                    }
                    if (data_arr.length === 0) return;
                    fillTable(data_arr, table, false);
                });
                resolve();
            } catch (err) { reject(err); }
        };
        reader.onerror = reject; reader.readAsText(file);
    });
}

export async function fileUploader(targetFile, targetText, projectName, gridName, message, type){
    if (projectName === '') return;
    signalSender('showOverlay', message);
    const file = targetFile.files[0], formData = new FormData();
    formData.append('file', file); formData.append('projectName', projectName);
    formData.append('fileName', gridName); formData.append('type', type);
    if (targetText !== null) {targetText.value = file?.name || "";}
    const response = await fetch('/upload_data', { method: 'POST', body: formData });
    const data = await response.json();
    signalSender('hideOverlay'); alert(data.message);
    if (data.status === "error") { targetText.value = ''; targetFile.value = ''; return; }
}

export async function getProjectList(userName='', folderCheck='') {
    const contents = { filename: userName, key: 'getProjects', folder_check: folderCheck };
    const data = await jsonLoader('select_project', contents);
    if (data.status === "error") { alert(data.message); return; }
    return data.content;
}

export function pointUpdate(target, table, isExist=true, objList=[]){
    target.addEventListener('change', () => { 
        const objUpdate = document.getElementById('obs-update');
        objUpdate.style.display = 'none';
        if (isExist) {
            objList.forEach(obj => obj.value = ''); 
            objUpdate.style.display = 'block';
        } else {
            const tbody = table.querySelector("tbody");
            const newTbody = document.createElement('tbody');
            const tr = document.createElement('tr');
            objList.forEach(text => {
                const td = document.createElement('td');
                const input = document.createElement('input');
                input.type = 'text';
                input.placeholder = text;
                td.appendChild(input);
                tr.appendChild(td);
            });
            newTbody.appendChild(tr); tbody.replaceWith(newTbody);
        }
    });
}

export function removeRowFromTable(table, name){
    if (name.trim() === '') { alert('Please select observation point to remove.'); return; }
    // Remove row with matching name
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const rowToRemove = rows.find(row => {{
        const firstCell = row.querySelector("td");
        if (!firstCell) return false;
        const input = firstCell.querySelector("input");
        if (!input) return false;
        const cellText = input ? input.value.trim() : firstCell.textContent.trim();
        return cellText === name;
    }});
    if (rowToRemove) { rowToRemove.remove(); alert(`Observation point "${name}" removed.`);
    } else { alert(`Observation point "${name}" not found.`); }
}

export async function updateTable(table, comboBox, projectName, key='') {
    const data = await jsonLoader('init_source', {projectName: projectName, key: key});
    if (data.status === "ok") {
        comboBox.innerHTML = '';
        // Add hint to the velocity object
        const hint = document.createElement('option');
        hint.value = ''; hint.selected = true;
        hint.text = '- No Selection -'; 
        comboBox.add(hint);
        // Add options
        const data_arr = [];
        data.content.forEach((item, idx) => {
            const option = document.createElement('option');
            option.value = item; option.text = item;
            comboBox.add(option);
            data_arr.push([item, data.type[idx]]);
        });
        if (data_arr.length > 0) fillTable(data_arr, table);
    }
}

export async function initOptions(comboBox, key, projectName) {
    signalSender('showOverlay', 'Loading Options.\nPlease wait...');
    try {
        const response = await fetch('/initiate_options', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key, projectName: projectName})});
        const data = await response.json();
        if (data.status === "ok") {
            // Add none option in case of vector
            if (key === 'vector' || key === 'thermocline_waq'){
                comboBox.innerHTML = '';
                // Add hint to the velocity object
                const hint = document.createElement('option');
                hint.value = ''; hint.selected = true;
                hint.text = '- No Selection -'; 
                comboBox.add(hint);
            }
            // Add options
            data.content.forEach(item => {
                const option = document.createElement('option');
                option.value = item[0]; option.text = item[1];
                comboBox.add(option);
            });
            // Select the first option
            if (key !== 'vector' && key !== 'thermocline_waq') {comboBox.value = -1;}
        } else if (data.status === "error") {alert(data.message); return;}
    } catch (error) {alert(error);}
    signalSender('hideOverlay');
}

export function decodeArray(base64Str, n_decimals=3) {
    // Convert base64 to ArrayBuffer
    const binaryStr = atob(base64Str);
    const buffer = new ArrayBuffer(binaryStr.length);
    const view = new Uint8Array(buffer);
    for (let i = 0; i < binaryStr.length; i++) {
        view[i] = binaryStr.charCodeAt(i);
    }
    // Convert buffer to Float32Array
    const floatArray = new Float32Array(buffer);
    // Round values
    const values = Array.from(floatArray).map(v => parseFloat(v.toFixed(n_decimals)));
    return values;
}

export function updateMapByTime(setFunction, getFunction, layerMap, values, vmin, vmax, colorbarKey) {
    for (let i = 0; i < getFunction().mapLayer.length; i++) {
        const id = getFunction().mapLayer[i];
        const value = values[id];
        if (value === null || value === undefined) continue;
        const { r, g, b, a } = getColorFromValue(value, vmin, vmax, colorbarKey);
        const colorKey = `${r},${g},${b},${a}`;
        if (getFunction().lastFeatureColors[id] === colorKey) continue;
        getFunction().lastFeatureColors[id] = colorKey;
        layerMap.setFeatureStyle(id, { 
            fill: true, fillColor: `rgb(${r},${g},${b})`, 
            fillOpacity: a, weight: 0, opacity: 1 
        });
    }
    setFunction({ lastFeatureColors: getFunction().lastFeatureColors });
}







export function iframeConnector(objBtn, objtarget, requestId, content = null, lineType='') {
    if (objBtn.__handler) objBtn.removeEventListener('click', objBtn.__handler);
    objBtn.__handler = async () => {
        const freshData = typeof content === 'function' ? content() : content;
        const result = await new Promise((resolve) => {
            function listener(event) {
                if (event.data?.requestId === requestId) {
                    window.removeEventListener('message', listener);
                    resolve(event.data.result);
                }
            }
            window.addEventListener('message', listener);
            const contents = {
                id: 'hyd-waq', requestId: requestId, content: freshData, lineType
            }
            window.parent.postMessage(contents, origin);
        });
        if (requestId === 'pickLocation') { objtarget.value = result; 
        } else if (requestId === 'pickPoint' || requestId === 'pickSource') {
            const lat = Number(result.lat).toFixed(12);
            const lon = Number(result.lng).toFixed(12);
            objtarget[1].value = lat; objtarget[2].value = lon;
            if (objtarget[0].value.trim() === '') {
                let name = '';
                if (requestId === 'pickPoint') {
                    name = `Point_${Number(lat).toFixed(2)}_${Number(lon).toFixed(2)}`;
                } else if (requestId === 'pickSource') { name = 'Source_Sink'; }
                objtarget[0].value = name;
            }
        } else if (requestId === 'pickPath') {
            let name = objtarget[0].value.trim();
            if (name === '') {
                if (lineType === 'crossSection') { name = 'Cross-Section'; } 
                else if (lineType === 'boundary') { name = 'Boundary'; }
                objtarget[0].value = name;
            }
            const table = objtarget[1], arr = []; deleteTable(table);
            for (let i = 0; i < result.length; i++) {
                const lat = Number(result[i].lat).toFixed(12);
                const lon = Number(result[i].lng).toFixed(12);
                const newName = `${name}_${i + 1}`;
                arr.push([newName, lat, lon]);
            }
            fillTable(arr, table, true);
            if (lineType === 'boundary') { // Update boundary option
                const options = arr.map(row => `<option value="${row[0]}">${row[0]}</option>`).join(' ');
                const defaultOption = `<option value="" selected>--- No selected ---</option>`;
                objtarget[2].innerHTML = defaultOption + options;
            }
        } else if (requestId === 'waqPoint' || requestId === 'loadsPoint') {
            const lat = Number(result.lat).toFixed(12);
            const lon = Number(result.lng).toFixed(12);
            const table = objtarget[1];
            if (freshData.rows.length === 0) { deleteTable(table); } 
            let name = objtarget[0].value.trim();
            if (name === '') { 
                if (requestId === 'waqPoint') {
                    name = `Obs_${Number(lat).toFixed(2)}_${Number(lon).toFixed(2)}`;
                } else if (requestId === 'loadsPoint') {
                    name = `Loads_${Number(lat).toFixed(2)}_${Number(lon).toFixed(2)}`; 
                }
            }
            addRowToTable(table, [name, lat, lon], true);
            const contents = { type: requestId, content: getDataFromTable(table, true) }
            window.parent.postMessage(contents, origin);
        } else if (requestId === 'pickLatLon') {
            const lat = objtarget[0], lon = objtarget[1];
            lat.value = Number(result.lat).toFixed(1);
            lon.value = Number(result.lng).toFixed(1);





        }
        return result;
    };
    objBtn.addEventListener('click', objBtn.__handler);
}



