import { CENTER, ZOOM } from "./constant.js";
import { getUser, signalSender, jsonLoader, deleteTable,
    fillTable, addRowToTable, nameChecker
} from "./commonFunctions.js";
import { gridPlotter, polygonPlotter, toggleMoveMode, orthoPlotter,
    getColorFromValue, updateColorbar, plotUnstructuredGrid
} from "./unstructuredGrid.js";
import { clearMap } from "./mapManager.js";

// initRequestListener();

const $ = (id) => document.getElementById(id);
const obj = {
    selectContainer: $("select-container"), municipalityName: $("municipality-name"), 
    municipalityList: $("municipality-list"), lakeSearcher: $("lake-search"), 
    sugesstionLake: $("lake-suggestions"), lakeLabel: $("lake-name-label"), 
    lakeSelector: $("lake-name"), lakeTable: $("lake-table"), 
    tableContent: $("table-of-contents"), menuContent: $("menu-container"),
    polygonCheckbox: $("polygon-checkbox"), depthCheckbox: $("depth-checkbox"),
    vertexesBtn: $("vertexes-btn"), refinementCheckbox: $("refinement-checkbox"),
    refinementContainer: $("refinement-container"), refinementValue: $("refinement-value"),
    moveCheckbox: $("move-checkbox"), deleteCheckbox: $("delete-checkbox"),
    scaleSelector: $("scale-factor"), scaleFactor: $("custom-scale-factor"),
    orthoCheckbox: $("orthogonality-checkbox"), createGrid: $("generate-grid"),
    gridOptimizationCheckbox: $("optimization-checkbox"), chartDiv: $("myChart-grid"),
    gridOptimizationContainer: $("grid-optimization-container"), saveGrid: $("save-grid"),
    iterationValue: $("iterations"), valueFrom: $("detail-level-from"),
    gridName: $("grid-name"), valueTo: $("detail-level-to"), optimizeBtn: $("optimize-grid"),
    progressbarGrid: $("progressbar-grid"), progressTextGrid: $("progress-text-grid"),
    baseMap: $("basemap-btn"), leafletMap: $("leaflet-map-lakes"),
    leafletContainer: $("map-container"), plotContainer: $("plot-container"), 
    colorBarContainer: $("custom-colorbar-grid"), colorBarColor: $("colorbar-gradient"),
    colorBarTitle: $("colorbar-title"), colorBarLabel: $("colorbar-label"),
    chartDiv: $("myChart-grid"), optimizeCloseBtn: $("optimization-close")
};

const row = ['Name', 'Municipality', 'Area', 'Perimeter', 
    'Max Depth', 'Min Depth', 'Average Depth'];
let currentProject = null, lakeMap = null, mapContainer = null, 
    currentTileLayer = null, timeOut = null, lakesData = {}, 
    dataLake = null, dataDepth = null, timeCounter = null,
    drawSelection = false, drawChecked = false, entireNorway = false,
    depthLayer = null, lakeLayer = null, gridLayer = null, orthoLayer = null,
    pointLayer = null, refineChecked = false, pointContainer = [], html = null,
    moveChecked = false, deleteChecked = false, levelValue = null, tempLine = null,
    activeProject = null, isRunning = false, logInterval = null;

const hoverTooltip = L.tooltip({
    permanent: false, direction: 'bottom',
    sticky: true, offset: [0, 10], className: 'custom-tooltip'
});

await getProject(); await initMap(); lakeOptions(); 
dataBaseOptions(); unGridManager();

async function getProject() { 
    const user = await getUser();
    currentProject = user.split('/').pop();
}

async function initMap() { 
    if (lakeMap) return;
    lakeMap = L.map(obj.leafletMap, { center: CENTER, zoom: ZOOM, zoomControl: false, attributionControl: true });
    currentTileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(lakeMap);
    L.control.scale({imperial: false, metric: true, maxWidth: 200}).addTo(lakeMap);
    setTimeout(() => { lakeMap.invalidateSize(); }, 0); mapContainer = lakeMap.getContainer();
    const baseMapPopup = document.querySelector('.basemap-popup');
    obj.baseMap.addEventListener('mouseenter', () => { 
        baseMapPopup.classList.add('show'); clearTimeout(timeCounter); 
        // Hide the popup after 4 seconds 
        timeCounter = setTimeout(() => {
            baseMapPopup.classList.remove('show');
        }, 4000);
    }); 
    // Change base map 
    baseMapPopup.addEventListener('click', (e) => { 
        if (e.target.classList.contains('basemap-option')) { 
            const url = e.target.dataset.url; 
            currentTileLayer.setUrl(url); 
            baseMapPopup.classList.remove('show'); 
        } 
    });
    lakeMap.on('mousemove', function (e) { 
        mapContainer.style.cursor = "grab";
        if (refineChecked) {
            if (pointContainer.length === 0) { html = "Select start point to refine"; }
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            lakeMap.openTooltip(hoverTooltip);
        }
        else if (deleteChecked) {
            if (pointContainer.length === 0) { html = "Select start point to delete"; }
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            lakeMap.openTooltip(hoverTooltip);
        }
        if (drawChecked) { 
            mapContainer.style.cursor = "crosshair";
            if (pointContainer.length === 0) { 
                html = `Draw a polygon with the left mouse button`; 
            }
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            lakeMap.openTooltip(hoverTooltip);
        }
        else if (moveChecked) { 
            mapContainer.style.cursor = "move";
            html = `Move a vertex using the left mouse button`;
            hoverTooltip.setLatLng(e.latlng).setContent(html);
            lakeMap.openTooltip(hoverTooltip);
        }
    });
    lakeMap.on('click', async function (e) {
        if (drawChecked) { 
            mapContainer.style.cursor = "crosshair";
            html = `Finish drawing with the right mouse button`;
            // Add marker
            L.circleMarker(e.latlng, {
                radius: 5, color: 'red', fillColor: 'pink', fillOpacity: 0.9
            }).addTo(lakeMap);
            pointContainer.push([e.latlng.lat, e.latlng.lng]);
            // Plot polygon
            if (tempLine) { tempLine.setLatLngs(pointContainer);
            } else {
                tempLine = L.polyline(pointContainer, { 
                    color: 'red', weight: 2
                }).addTo(lakeMap);
            }
            if (hoverTooltip) lakeMap.closeTooltip(hoverTooltip); return; 
        }
    });
    lakeMap.on('contextmenu', async function (e) { 
        e.originalEvent.preventDefault();
        if (drawChecked) { 
            if (pointContainer.length < 3) { 
                alert("Polygon must have at least 3 points."); return; 
            }
            tempLine = clearMap(tempLine, lakeMap); 
            lakeLayer = clearMap(lakeLayer, lakeMap);
            // Plot polygon
            await drawPolygon(pointContainer); drawChecked = false;
            pointContainer = []; mapContainer.style.cursor = "auto";
        }
    });
}

async function lakeOptions() {
    // Search lake
    const handleLakeSearchEvent = async (e) => { 
        const value = e.target.value.trim(); 
        if (e.type === 'input') clearTimeout(timeOut); 
        if (e.type === 'click') { 
            obj.lakeSelector.style.display = 'none'; 
            obj.lakeLabel.style.display = 'none'; 
        } 
        if (value === "") {
            obj.menuContent.style.display = "none"; 
            resetMap();
        }
        await addItems(currentProject, value); 
        obj.municipalityName.value = ''; 
        obj.municipalityList.style.display = "none"; 
    }; 
    ['click', 'input'].forEach(evt => { 
        obj.lakeSearcher.addEventListener(evt, handleLakeSearchEvent); 
    }); 
    obj.lakeSelector.addEventListener('change', async (e) => { 
        const lakeName = e.target.value.trim(); if (!lakeName) return;
        if (lakeName === '') { 
            obj.menuContent.style.display = "none";
        } else { obj.menuContent.style.display = "grid"; }
        resetMap(); signalSender('showOverlay', `Loading data for lake: ${lakeName}`);
        const response = await jsonLoader('load_lakes', { 
            projectName: currentProject, lakeName: lakeName 
        });
        signalSender('hideOverlay');
        if (response.status === "error") { alert(response.message); return; } 
        dataLake = response.content.lake; dataDepth = response.content.depth;
        const data = dataLake.features[0].properties;
        const contents = [[
            data.name, data.region, data.area, 
            data.perimeter, data.min, data.max, data.avg
        ]]; 
        obj.tableContent.style.display = "block"; 
        fillTable(contents, obj.lakeTable, true);
        obj.polygonCheckbox.checked = true;
        obj.depthCheckbox.checked = true;
        obj.orthoCheckbox.checked = false; 
        // Plot depth grid on map
        depthLayer = clearMap(depthLayer, lakeMap);
        depthLayer = gridPlotter(
            'Depth (m)', dataLake, dataDepth, lakeMap, obj.colorBarContainer
        );
        lakeLayer = clearMap(lakeLayer, lakeMap);
        lakeLayer = polygonPlotter(dataLake, lakeMap, entireNorway, true);
    });
}

async function dataBaseOptions() {
    // Update municipality name 
    obj.municipalityName.addEventListener('change', async (e) => { 
        const selectedLake = e.target.value.trim(); entireNorway = false; 
        if (!selectedLake || selectedLake === "") { 
            e.target.dispatchEvent(new Event('click')); return; 
        }
        if (selectedLake === "All Municipalities" ) { 
            signalSender('showOverlay', 'Loading Lakes for entire Norway.\nPlease wait...');
            entireNorway = true; obj.tableContent.style.display = "none"; 
            obj.menuContent.style.display = "none"; 
            obj.lakeSelector.style.display = "none"; 
            obj.colorBarContainer.style.display = "none";
            const response = await jsonLoader('load_lakes', { 
                projectName: currentProject, lakeName: 'all'
            });
            signalSender('hideOverlay'); resetMap();
            if (response.status === "error") { alert(response.message); return; } 
            dataLake = response.content.lake; dataDepth = response.content.depth;
            lakeLayer = polygonPlotter(dataLake, lakeMap, entireNorway, true);
            return;
        }
        obj.lakeSelector.innerHTML = lakesData[selectedLake]
            .map(name => `<option value="${name}">${name}</option>`).join(''); 
        obj.lakeSelector.value = lakesData[selectedLake][0]; 
        obj.lakeSelector.dispatchEvent(new Event('change')); 
    });
    obj.municipalityName.addEventListener('click', async (e) => { 
        obj.sugesstionLake.style.display = "none"; obj.lakeSearcher.value = "";
        if (e.target.value.trim() === "") { 
            obj.lakeLabel.style.display = "none"; 
            obj.lakeSelector.style.display = "none"; 
            obj.menuContent.style.display = "none"; 
            const tbody = obj.lakeTable.querySelector("tbody"); tbody.innerHTML = '';
            deleteTable(obj.lakeTable); addRowToTable(obj.lakeTable, row);
        } 
        if (Object.keys(lakesData).length === 0) { await loadLakes(currentProject); } 
        obj.municipalityList.innerHTML = ''; 
        // Add "All Municipalities" option 
        const allLi = document.createElement("li"); 
        allLi.textContent = "All Municipalities"; allLi.style.fontWeight = "bold"; 
        allLi.dataset.value = "All Municipalities"; allLi.style.fontSize = "18px"; 
        allLi.addEventListener('mousedown', () => { 
            obj.municipalityName.value = allLi.dataset.value; 
            obj.municipalityList.style.display = "none"; 
            obj.lakeLabel.style.display = "none"; 
            obj.lakeSelector.style.display = "none"; 
            obj.municipalityName.dispatchEvent(new Event('change')); 
        }); 
        obj.municipalityList.appendChild(allLi); 
        const allHr = document.createElement("hr"); 
        allHr.style.margin = "5px 10px 5px 10px"; 
        allHr.style.borderTop = "1px solid #0414f5"; 
        obj.municipalityList.appendChild(allHr); 
        Object.keys(lakesData).forEach(p => { 
            const li = document.createElement("li"); 
            li.textContent = p; 
            li.addEventListener('mousedown', () => { 
                obj.municipalityName.value = p; 
                obj.municipalityList.style.display = "none"; 
                obj.lakeLabel.style.display = "block"; 
                obj.lakeSelector.style.display = "block"; 
                obj.municipalityName.dispatchEvent(new Event('change')); 
            }); 
            obj.municipalityList.appendChild(li); 
        });
        obj.municipalityList.style.display = "block"; 
    });
    obj.municipalityName.addEventListener('input', (e) => { 
        const value = e.target.value.trim(); 
        if (value !== "") { 
            projectRender(e.target, obj.municipalityList, Object.keys(lakesData));
        } else { 
            obj.lakeSelector.value = ""; e.target.value = ""; 
            obj.lakeLabel.style.display = "none"; 
            obj.lakeSelector.style.display = "none"; 
            e.target.dispatchEvent(new Event('click')); 
        } 
    });
    obj.municipalityName.addEventListener('blur', (e) => { 
        setTimeout(() => { obj.municipalityList.style.display = "none"; }, 0); 
        if (e.target.value === "") { 
            obj.lakeLabel.style.display = "none"; obj.lakeSelector.style.display = "none"; 
        } 
    });
}

function unGridManager() {
    // Change data source 
    document.querySelectorAll('input[type="radio"]').forEach(opt => { 
        opt.addEventListener('change', () => { 
            if (opt.id === 'new-database') { 
                obj.selectContainer.style.display = 'flex'; 
                obj.municipalityName.value = ''; obj.lakeSearcher.value = ''; 
                obj.lakeSelector.style.display = 'none'; 
                obj.lakeSelector.value = ''; obj.lakeLabel.style.display = 'none';
                obj.menuContent.style.display = 'none'; 
                drawSelection = false; drawChecked = false; 
            } else if (opt.id === 'new-map') { 
                obj.selectContainer.style.display = 'none'; 
                drawSelection = true; drawChecked = true;
                obj.menuContent.style.display = 'grid';
                obj.colorBarContainer.style.display = 'none';
            }
            deleteTable(obj.lakeTable); addRowToTable(obj.lakeTable, row); resetMap();
        });
    });
    // Hide suggestions
    document.addEventListener('click', (e) => { 
        const input = obj.lakeSearcher, suggestion = obj.sugesstionLake; 
        if (!input.contains(e.target) && !suggestion.contains(e.target)) { 
            suggestion.style.display = "none"; 
        }
    });
    // Show/Hide objects
    obj.polygonCheckbox.addEventListener('change', (e) => {
        if (e.target.checked) { 
            if (!lakeLayer) {
                lakeLayer = polygonPlotter(
                    dataLake, lakeMap, entireNorway, true
                );
            }
        } else { 
            lakeLayer = clearMap(lakeLayer, lakeMap);
        }
    });
    obj.depthCheckbox.addEventListener('change', async (e) => {
        if (e.target.checked) { 
            if (drawSelection) { e.target.checked = false; return; } 
            if (!depthLayer) {
                signalSender('showOverlay', 'Plotting depth grid.\nPlease wait...');
                depthLayer = gridPlotter(
                    'Depth (m)', dataLake, dataDepth, lakeMap, obj.colorBarContainer
                );
                signalSender('hideOverlay');
            }
        } else { 
            depthLayer = clearMap(depthLayer, lakeMap);
            obj.colorBarContainer.style.display = 'none';
        }
    });
    obj.vertexesBtn.addEventListener('click', async () => {
        resetMap(); obj.colorBarContainer.style.display = 'none';
        signalSender('showOverlay', 'Generating Vertexes.\nPlease wait...');
        const response = await jsonLoader('vertex_generator', { projectName: currentProject }); 
        signalSender('hideOverlay');
        if (response.status === "error") { alert(response.message); return; }
        if (pointLayer) pointLayer = clearMap(pointLayer, lakeMap);
        pointLayer = addPointLayer(response.content, false);
        if (!obj.polygonCheckbox.checked) obj.polygonCheckbox.checked = true;
        obj.polygonCheckbox.dispatchEvent(new Event('change'));
        obj.orthoCheckbox.checked = false; obj.orthoCheckbox.dispatchEvent(new Event('change'));
        refineChecked = false; obj.refinementCheckbox.checked = false;
        obj.refinementCheckbox.dispatchEvent(new Event('change'));
        obj.depthCheckbox.checked = false; obj.depthCheckbox.dispatchEvent(new Event('change'));
    });
    obj.refinementCheckbox.addEventListener('change', async (e) => {
        if (e.target.checked) { 
            if (!pointLayer) { 
                alert("Select the button 'Get/Reset Vertexes' to create vertexes first.");
                e.target.checked = false; return;
            }
            refineChecked = true; obj.depthCheckbox.checked = false;
            obj.moveCheckbox.checked = false; moveChecked = false;
            obj.depthCheckbox.checked = false;
            obj.depthCheckbox.dispatchEvent(new Event('change'));
            deleteChecked = false; obj.deleteCheckbox.checked = false;
            obj.deleteCheckbox.dispatchEvent(new Event('change'));
            obj.refinementContainer.style.display = 'flex';
            pointContainer = []; gridLayer = clearMap(gridLayer, lakeMap);
            orthoLayer = clearMap(orthoLayer, lakeMap);
            obj.orthoCheckbox.checked = false; 
            obj.orthoCheckbox.dispatchEvent(new Event('change'));
        } else { 
            obj.refinementContainer.style.display = 'none'; refineChecked = false;
        }
    });
    obj.moveCheckbox.addEventListener('change', async (e) => { 
        const value = e.target.checked, pointCollection = [];
        if (value) {
            if (pointLayer === null) {
                alert("Select the button 'Get/Reset Vertexes' to create vertexes first.");
                e.target.checked = false; return;
            }
            toggleMoveMode(pointLayer, true);
            pointLayer.eachLayer(layer => {
                const latlng = layer.getLatLng();
                pointCollection.push([latlng.lat, latlng.lng]);
            });
            if (pointCollection.length === 0) { alert("No vertexes found."); return; }
            pointCollection.push(pointCollection[0]); 
            moveChecked = true; refineChecked = false; deleteChecked = false;
            obj.deleteCheckbox.checked = false; obj.refinementCheckbox.checked = false;
            signalSender('showOverlay', 'Regenerating vertexes.\nPlease wait...');
            const contents = { projectName: currentProject, pointCollection: pointCollection };
            const response = await jsonLoader('vertex_mover', contents); 
            signalSender('hideOverlay');
            if (response.status === "error") { alert(response.message); return; }
            if (!obj.polygonCheckbox.checked) { obj.polygonCheckbox.checked = true; }
            lakeLayer = clearMap(lakeLayer, lakeMap); 
            lakeLayer = polygonPlotter(response.content.polygon, lakeMap);
            pointLayer = clearMap(pointLayer, lakeMap); 
            pointLayer = addPointLayer(response.content.point, true);
        } else { moveChecked = false; toggleMoveMode(pointLayer, false); }
    });
    obj.deleteCheckbox.addEventListener('change', async (e) => {
        if (!e.target.checked) { deleteChecked = false; return; }
        if (pointLayer === null) { 
            alert("Select the button 'Get/Reset Vertexes' to create vertexes first.");
            e.target.checked = false; return;
        }
        obj.moveCheckbox.checked = false; moveChecked = false;
        pointContainer = []; gridLayer = clearMap(gridLayer, lakeMap); deleteChecked = true; 
        obj.orthoCheckbox.checked = false; obj.orthoCheckbox.dispatchEvent(new Event('change'));
        refineChecked = false; obj.refinementCheckbox.checked = false;
        obj.refinementCheckbox.dispatchEvent(new Event('change'));
    });
    obj.scaleSelector.addEventListener('change', (e) => {
        const value = e.target.value;
        if (value === "auto") { obj.scaleFactor.style.display = "none"; }
        else { obj.scaleFactor.style.display = "flex"; }
    });
    obj.scaleFactor.addEventListener('input', (e) => { 
        const value = e.target.value;
        if (value === "" || !Number.isFinite(Number(value)) || Number(value) <= 0) { 
            e.target.value = '1.0'; return; 
        }
    });
    // Create grid
    obj.createGrid.addEventListener('click', async () => {
        if (pointLayer === null) { alert("Please generate vertexes first."); return; }
        const levelSelector = obj.scaleSelector.value, pointCollection = [];
        if (levelSelector === "auto") { levelValue = ''; } 
        else { levelValue = Number(obj.scaleFactor.value); }
        pointLayer.eachLayer(layer => {
            const latlng = layer.getLatLng();
            pointCollection.push([latlng.lat, latlng.lng]);
        });
        if (pointCollection.length === 0) { alert("No vertexes found."); return; }
        pointCollection.push(pointCollection[0]);
        signalSender('showOverlay', 'Generating an Unstructured Grid.\nPlease wait...');
        const contents = { 
            projectName: currentProject, pointCollection: pointCollection, levelValue: levelValue 
        }
        const response = await jsonLoader('grid_creator', contents); 
        signalSender('hideOverlay');
        if (response.status === "error") { alert(response.message); return; }
        gridLayer = clearMap(gridLayer, lakeMap); orthoLayer = clearMap(orthoLayer, lakeMap);
        gridLayer = await plotUnstructuredGrid(response.content, lakeMap);
        moveChecked = false; obj.moveCheckbox.checked = false;
        refineChecked = false; obj.refinementCheckbox.checked = false;
        obj.refinementCheckbox.dispatchEvent(new Event('change'));
        obj.gridOptimizationCheckbox.checked = false;
        obj.gridOptimizationCheckbox.dispatchEvent(new Event('change'));
        obj.depthCheckbox.checked = false; obj.depthCheckbox.dispatchEvent(new Event('change'));
        obj.orthoCheckbox.checked = false; obj.orthoCheckbox.dispatchEvent(new Event('change'));
    });
    // Generate orthogonality
    obj.orthoCheckbox.addEventListener('change', async (e) => {
        if (e.target.checked) { 
            if (gridLayer === null) { 
                alert("Please generate grid first."); 
                obj.orthoCheckbox.checked = false; return; 
            }
            signalSender('showOverlay', 'Generating Orthogonality Grid.\nPlease wait...');
            const contents = { projectName: currentProject };
            const response = await jsonLoader('grid_ortho', contents);
            signalSender('hideOverlay');
            if (response.status === "error") { alert(response.message); return; }
            depthLayer = clearMap(depthLayer, lakeMap); orthoLayer = clearMap(orthoLayer, lakeMap); 
            obj.depthCheckbox.checked = false;
            const vmin = response.content.min, vmax = response.content.max, colorKey = 'ortho';
            orthoLayer = L.geoJSON(response.content.data, {
                pointToLayer: (feature, latlng) => {
                    const value = Number(feature.properties.orth);
                    const { r, g, b, a } = getColorFromValue(value, vmin, vmax, colorKey);
                    const col = `rgb(${r},${g},${b})`;
                    return L.circleMarker(latlng, {
                        color: col, fillColor: col, radius: 2, fillOpacity: a
                    });
                },
                onEachFeature: (feature, layer) => {
                    layer.bindTooltip(`Orthogonality: ${feature.properties.orth}`, {
                        sticky: true, permanent: false, direction: 'center', opacity: 1
                    });
                }
            }).addTo(lakeMap);
            updateColorbar(vmin, vmax, 'Orthogonality', colorKey, obj.colorBarColor, 
                obj.colorBarTitle, obj.colorBarLabel);
            obj.colorBarContainer.style.display = 'block';
        } else { 
            orthoLayer = clearMap(orthoLayer, lakeMap);
            if (!obj.depthCheckbox.checked) { obj.colorBarContainer.style.display = 'none'; } 
        }
    });
    obj.gridOptimizationCheckbox.addEventListener('change', async (e) => {
        if (e.target.checked) {
            if (gridLayer === null) { 
                alert("Please generate grid first."); 
                e.target.checked = false; return; 
            }
            obj.gridOptimizationContainer.style.display = 'flex';
        } else { obj.gridOptimizationContainer.style.display = 'none'; }
    });
    obj.optimizeBtn.addEventListener('click', async () => {
        obj.progressbarGrid.value = 0; obj.progressTextGrid.innerText = ''; 
        gridLayer = clearMap(gridLayer, lakeMap);
        if (isRunning) { alert("Grid optimization is already running."); return; }
        if (pointLayer === null) { alert("Please generate grid first."); return; }
        const iterations = Number(obj.iterationValue.value);
        if (isNaN(iterations)) { alert("Please enter a valid number of iterations."); return; }
        const levelFrom = Number(obj.valueFrom.value), levelTo = Number(obj.valueTo.value);
        if (isNaN(levelFrom) || isNaN(levelTo) || levelFrom < 0 || levelTo < 0 || levelFrom >= levelTo) {
            alert("Please enter a valid value range."); return; 
        }
        obj.leafletContainer.style.display = 'none'; obj.plotContainer.style.display = 'flex'; 
        obj.menuContent.style.display = 'none';
        obj.optimizeCloseBtn.innerText = 'Stop'; isRunning = true;
        const statusRes = await jsonLoader('check_grid_optimization', { projectName: currentProject });
        if (statusRes.status === "running") {
            updateLog(currentProject, obj.chartDiv, obj.progressbarGrid, obj.progressTextGrid, 1);
        }
        const pointCollection = [];
        pointLayer.eachLayer(layer => {
            const latlng = layer.getLatLng();
            pointCollection.push([latlng.lat, latlng.lng]);
        });
        if (pointCollection.length === 0) { alert("No vertexes found."); return; }
        pointCollection.push(pointCollection[0]);
        const contents = { projectName: currentProject, pointCollection: pointCollection,
            iterations: iterations, levelFrom: levelFrom, levelTo: levelTo
        };
        const start = await jsonLoader('start_grid_optimization', contents);
        if (start.status === "error") { isRunning = false; alert(start.message); return; }
        updateLog(currentProject, obj.chartDiv, obj.progressbarGrid, obj.progressTextGrid, 1);
    });
    obj.optimizeCloseBtn.addEventListener('click', async (e) => {
        const value = e.target.innerText;
        if (value === 'Stop') {
            const response = await jsonLoader('grid_stop', {projectName: currentProject});
            if (response.status === "error") { alert(response.message); }
            isRunning = false; e.target.innerText = 'Close and Plot Grid';
        } else if (value === 'Close and Plot Grid') {
            obj.leafletContainer.style.display = 'flex'; obj.plotContainer.style.display = 'none'; 
            obj.menuContent.style.display = 'grid';
        }
    });
    obj.saveGrid.addEventListener('click', async() => {
        if (gridLayer === null) { alert("Please generate unstructured grid first."); return; }
        let name = obj.gridName.value.trim();
        if (name === "") { alert("Please enter a name."); return; }
        if (nameChecker(name)) { alert('Grid name contains invalid characters.'); return; }
        if (!name.toLowerCase().endsWith('.nc')) { name = name + '.nc'; }
        signalSender('showOverlay', 'Checking grid existence.\nPlease wait...');
        const contents = { projectName: currentProject, gridName: name };
        const check = await jsonLoader('grid_checker', contents);
        signalSender('hideOverlay');
        if (check.status === "error") { 
            if (!confirm(`File "${name}" already exists. Do you want to overwrite it?`)) { return; }
        }
        signalSender('showOverlay', 'Saving grid.\nPlease wait...');
        const response = await jsonLoader('grid_saver', contents);
        signalSender('hideOverlay'); alert(response.message);
    });
}

async function addItems(currentProject, value) {
    signalSender('showOverlay', 'Loading all Lakes for entire Norway.\nPlease wait...');
    timeOut = setTimeout( async() => { 
        const response = await jsonLoader('search_lake', { 
            projectName: currentProject, name: value 
        });
        if (response.status === "error") { alert(response.message); return; }
        if (response.content.length === 0) { obj.sugesstionLake.style.display = 'none'; return; } 
        obj.sugesstionLake.innerHTML = ''; 
        response.content.forEach(lake => { 
            var div = document.createElement('div'); 
            div.textContent = lake; 
            div.addEventListener('click', () => { 
                obj.lakeSearcher.value = lake; 
                obj.municipalityList.value = ''; 
                obj.lakeSelector.innerHTML = `<option value="${lake}">${lake}</option>`; 
                obj.sugesstionLake.style.display = 'none'; 
                obj.lakeSelector.dispatchEvent(new Event('change')); 
            }); 
            obj.sugesstionLake.appendChild(div); 
        }); 
        obj.sugesstionLake.style.display = 'block'; 
    }, 200); 
    signalSender('hideOverlay');
}

async function loadLakes(currentProject){
    signalSender('showOverlay', "Initializing Database for entire Norway's Lakes.\nPlease wait...");
    const response = await jsonLoader('init_lakes', {projectName: currentProject});
    if (response.status === "error") { alert(response.message); return; }
    signalSender('hideOverlay'); lakesData = response.content;
    dataLake = lakesData.lake; dataDepth = lakesData.depth;
}

async function drawPolygon(pointList) {
    signalSender('showOverlay', 'Drawing Polygon on the map.\nPlease wait...');
    const content = { projectName: currentProject, points: pointList };
    const response = await jsonLoader('polygon_generator', content);
    signalSender('hideOverlay');
    if (response.status === "error") { alert(response.message); return; }
    const polygon = response.content.polygon, point = response.content.point;
    const data = polygon.features[0].properties;
    const contents = [[
        data.name, data.region, data.area, 
        data.perimeter, data.min, data.max, data.avg
    ]];
    fillTable(contents, obj.lakeTable, true); obj.depthCheckbox.checked = false;
    obj.polygonCheckbox.checked = true; dataLake = polygon; resetMap();
    lakeLayer = polygonPlotter(polygon, lakeMap); 
    pointLayer = addPointLayer(point, lakeMap, true);
}

export function addPointLayer(points, checkMove=false) {
    const pointType = checkMove ? 'point-marker-move' : 'point-marker-default';
    const tempLayer = L.geoJSON(points, {
        pointToLayer: (_, latlng) => {
            const marker = L.marker(latlng, {
                draggable: checkMove,
                icon: L.divIcon({
                    className: "", html: `<div class="${pointType}"></div>`,
                    iconSize: [10, 10], iconAnchor: [5, 5]
                }),
            });
            return marker;
        },
        onEachFeature: (feature, layer) => {
            layer.on('click', async () => { 
                mapContainer.style.cursor = "auto";
                if (refineChecked) {
                    if (!pointContainer.includes(feature.properties.id)) { 
                        pointContainer.push(feature.properties.id); 
                    }
                    if (pointContainer.length === 1) { html = "Select end point to refine."; }
                    if (pointContainer.length === 2) { 
                        await polygonRefinement(pointContainer); pointContainer = [];
                        obj.refinementCheckbox.dispatchEvent(new Event('change'));
                        if (hoverTooltip) lakeMap.closeTooltip(hoverTooltip); 
                        return;
                    }
                } else if (deleteChecked) {
                    if (!pointContainer.includes(feature.properties.id)) { 
                        pointContainer.push(feature.properties.id); 
                    }
                    if (pointContainer.length === 1) { html = "Select end point to delete."; }
                    if (pointContainer.length === 2) { 
                        await pointRemoval(pointContainer); pointContainer = []; 
                        obj.deleteCheckbox.dispatchEvent(new Event('change'));
                        if (hoverTooltip) lakeMap.closeTooltip(hoverTooltip); 
                        return;
                    }
                }
            });
            layer.on('dragend', async function (e) {
                const pos = e.target.getLatLng(), pointCollection = [];
                // Update point
                layer.feature.geometry.coordinates = [pos.lng, pos.lat];
                pointLayer.eachLayer(layer => {
                    const latlng = layer.getLatLng();
                    pointCollection.push([latlng.lat, latlng.lng]);
                });
                signalSender('showOverlay', 'Regenerating vertexes.\nPlease wait...');
                const contents = { projectName: currentProject, pointCollection: pointCollection };
                const response = await jsonLoader('vertex_mover', contents); 
                signalSender('hideOverlay');
                if (response.status === "error") { alert(response.message); return; }
                if (!obj.polygonCheckbox.checked) obj.polygonCheckbox.checked = true; resetMap();
                lakeLayer = polygonPlotter(response.content.polygon, lakeMap);
                pointLayer = addPointLayer(response.content.point, lakeMap, checkMove);
            });
            layer.bindTooltip(`Id: ${feature.properties.id}`, {
                sticky: true, permanent: false, direction: 'center', opacity: 1
            });
        }
    }).addTo(lakeMap);
    return tempLayer;
}

async function polygonRefinement(pointIds) {
    const refineValue = Number(obj.refinementValue.value); 
    gridLayer = clearMap(gridLayer, lakeMap);
    if (!Number.isFinite(refineValue) || refineValue <= 0) { 
        alert("Please enter a valid non-negative value."); return; 
    }
    if (pointLayer === null) { 
        alert("No polygon has been found. Select the button 'Get/Reset Vertexes' to draw the original polygon first."); return; 
    }
    const pointCollection = [];
    pointLayer.eachLayer(layer => {
        const latlng = layer.getLatLng();
        pointCollection.push([latlng.lat, latlng.lng]);
    });
    if (pointCollection.length < 2) { alert("No point has been found. Select the button 'Get/Reset Vertexes' to create vertexes first."); return; }
    signalSender('showOverlay', 'Refining Vertexes.\nPlease wait...');
    const contents = {
        projectName: currentProject, distance: refineValue, polygon: pointCollection,
        startPoint: pointIds[0], endPoint: pointIds[pointIds.length - 1]
    }
    const response = await jsonLoader('vertex_refiner', contents);
    signalSender('hideOverlay');
    if (response.status === "error") { alert(response.message);  return; }
    const polygon = response.content.polygon, point = response.content.point; dataLake = polygon;
    if (!obj.polygonCheckbox.checked) { obj.polygonCheckbox.checked = true; }
    resetMap();
    lakeLayer = polygonPlotter(polygon, lakeMap); pointLayer = addPointLayer(point, false);
    obj.orthoCheckbox.checked = false; obj.orthoCheckbox.dispatchEvent(new Event('change'));
}

async function pointRemoval(pointIds) {
    if (pointLayer === null) { 
        alert("No polygon has been found. Select the button 'Get/Reset Vertexes' to draw the original polygon first."); return; 
    }
    const pointCollection = []; deleteChecked = true;
    pointLayer.eachLayer(layer => {
        const latlng = layer.getLatLng();
        pointCollection.push([latlng.lat, latlng.lng]);
    });
    if (pointCollection.length < 2) { 
        alert("No point has been found. Select the button 'Get/Reset Vertexes' to draw the original polygon first."); return; 
    }
    signalSender('showOverlay', "Deleting Vertexes.\nPlease wait...");
    const contents = {
        projectName: currentProject, polygon: pointCollection,
        startPoint: pointIds[0], endPoint: pointIds[pointIds.length - 1]
    }
    const response = await jsonLoader('vertex_remover', contents); 
    signalSender('hideOverlay');
    if (response.status === "error") { alert(response.message); return; }
    const polygon = response.content.polygon, point = response.content.point;
    resetMap();
    lakeLayer = polygonPlotter(polygon, lakeMap, false, false); 
    pointLayer = addPointLayer(point, false);
    obj.orthoCheckbox.checked = false; 
    obj.orthoCheckbox.dispatchEvent(new Event('change'));
}

function resetMap(){
    lakeLayer = clearMap(lakeLayer, lakeMap); depthLayer = clearMap(depthLayer, lakeMap);
    gridLayer = clearMap(gridLayer, lakeMap); orthoLayer = clearMap(orthoLayer, lakeMap);
    pointLayer = clearMap(pointLayer, lakeMap); obj.colorBarContainer.style.display = 'none';
}

function updateLog(project, chartDiv, progress_bar, progress_text, seconds){
    activeProject = project; isRunning = true;
    logInterval = setInterval(async () => {
        if (activeProject !== project) { clearInterval(logInterval); logInterval = null; return; }
        try {
            const statusRes = await jsonLoader('check_grid_optimization', {projectName: project});
            progress_text.innerText = statusRes.message; progress_bar.value = statusRes.progress;
            if (statusRes.status === "finished" || statusRes.status === "stopped") {
                clearInterval(logInterval); logInterval = null; isRunning = false;
                if (statusRes.grid) { 
                    gridLayer = clearMap(gridLayer, lakeMap);
                    gridLayer = await plotUnstructuredGrid(statusRes.grid, lakeMap);
                    obj.orthoCheckbox.checked = true; obj.orthoCheckbox.dispatchEvent(new Event('change'));
                } else { alert('No grid has been found. Consider running the optimization again.'); }
                obj.optimizeCloseBtn.innerText = "Close and Plot Grid"; return;
            }
            if (statusRes.status === "failed") {
                clearInterval(logInterval); logInterval = null; isRunning = false;
                alert(statusRes.message); return;
            }
            // Plotting Orthogonality
            await orthoPlotter(statusRes.his, chartDiv, 'Step', 'Orthogonality', 'Orthogonality History');
        } catch (error) { 
            alert("Polling error: " + (error.message || error)); isRunning = false;
            clearInterval(logInterval); logInterval = null; 
        }
    }, seconds * 1000);
}
