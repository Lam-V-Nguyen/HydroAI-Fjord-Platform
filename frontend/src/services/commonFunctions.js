
const pendingRequests = new Map();

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





