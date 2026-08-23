import { CENTER, ZOOM, L, getPendingRequest, clearPendingRequest, origin } from "./constant.js";
import { signalSender } from "./commonFunctions.js";
import { updateColorbar } from "./unstructuredGrid.js";
import { mapPlotter, buildTooltip } from "./flowManager.js";

const layerConfig = {
    terrainLayer: {
        getLayer: () => terrainLayer, setLayer: (l) => terrainLayer = l,
        title: 'Raw Terrain (m)', colorKey: 'terrain', min: 0, max: 0,
        alert: 'Please upload terrain data first.'
    },
    streamLayer: {
        getLayer: () => streamLayer, setLayer: (l) => streamLayer = l,
        title: 'Streams', colorKey: 'terrain', min: 0, max: 1, 
        alert: 'Please upload terrain data first.'
    },
    soilLayer: {
        getLayer: () => streamLayer, setLayer: (l) => streamLayer = l,
        title: 'Soil', colorKey: 'terrain', min: 0, max: 0, 
        alert: 'Please upload soil data first.'
    },
    catchmentLayer_Vector: {
        layer: null, data: null,
        getLayer() { return this.layer; }, setLayer(l) { this.layer = l; },
        getData() { return this.data; }, setData(d) { this.data = d; },
    },
    landLayer_Vector: {
        layer: null, data: null,
        getLayer() { return this.layer; }, setLayer(l) { this.layer = l; },
        getData() { return this.data; }, setData(d) { this.data = d; },
    },
    riverLayer_Vector: {
        layer: null, data: null,
        getLayer() { return this.layer; }, setLayer(l) { this.layer = l; },
        getData() { return this.data; }, setData(d) { this.data = d; },
    },
    lakeLayer_Vector: {
        layer: null, data: null,
        getLayer() { return this.layer; }, setLayer(l) { this.layer = l; },
        getData() { return this.data; }, setData(d) { this.data = d; },
    }
}

const mapping = {
    river: {
        key: 'river', fields: ['rivwth','rivdph']
    }
};





export let currentMap;
let currentTileLayer = null, timeCounter = null, html='', markersObs = [], 
    markerCrossSection = [], currentPoints = [], markerBoundary = [], 
    pathCrossSection = null, pathBoundary = null, currentPointsCross = [], 
    currentPointsBoundary = [], waqObs = [], waqLoads = [], mapContainer = null,
    markerLayer = null, terrainLayer = null, streamLayer = null,
    isPourpointActive = false, lastLayer = null, layer = null;
const configCrossSectionPoint = { color: 'blue', fillColor: 'yellow', radius: 4, fill: true, fillOpacity: 1 }, 
    configBoundaryPoint = { color: 'red', fillColor: 'green', radius: 4, fill: true, fillOpacity: 1 }, 
    configCrossSectionPath = { color: 'blue', weight: 2, dashArray: '5,5' }, 
    configBoundaryPath = {color: 'red', weight: 2};

const hoverTooltip = L.tooltip({
    permanent: false, direction: 'bottom', sticky: true, 
    offset: [0, 10], className: 'custom-tooltip'
});

function iconAdd(iconUrl, markers, map, pointList) {
    if (!pointList || pointList.length === 0) return;
    const customIcon = iconUrl ? L.icon({
        iconUrl: iconUrl, iconSize: [20, 20], popupAnchor: [1, -34],
    }) : null;
    // Add new markers
    pointList.forEach(row => {
        const [name, lat, lon] = row;
        if (!name || isNaN(lat) || isNaN(lon)) return;
        const markerOptions = customIcon ? { icon: customIcon } : {};
        const marker = L.marker(
            [parseFloat(lat), parseFloat(lon)], markerOptions
        ).addTo(map);
        marker.bindPopup(name); markers.push(marker);
    })
}

function lineAdd(pointContainer, map, lineType) {
    const latlngs = pointContainer
        .map(p => {
            const lat = parseFloat(p[1]), lon = parseFloat(p[2]);
            if (isNaN(lat) || isNaN(lon)) return null;
            return [lat, lon];
        })
        .filter(Boolean);
    if (latlngs.length < 2) return;
    if (lineType === 'crossSection') { 
        pathCrossSection = L.polyline(latlngs, configCrossSectionPath).addTo(map);
        currentMap.fitBounds(pathCrossSection.getBounds());
    } else if (lineType === 'boundary') { 
        pathBoundary = L.polyline(latlngs, configBoundaryPath).addTo(map); 
        currentMap.fitBounds(pathBoundary.getBounds());
    }
}

export async function renderPreview(request=null) {
    currentPoints.length = 0; if (!request) return;
    const type = request.type; console.log(request);
    if (type === 'pickPoint' || type === 'updateObsPoint') {
        const iconUrl = `/src_frontend/images/station.png?v=${Date.now()}`;
        iconAdd(iconUrl, markersObs, currentMap, request.content.rows);
        if (type === 'updateObsPoint') alert('Observation points are updated.\nSee the map for details.');
    } else if (type === 'pickPath') {
        const pointList = request.content.rows, lineType = request.content.lineType;
        if (!pointList || pointList.length === 0) return;
        lineAdd(pointList, currentMap, lineType);
    // } else if (type === 'updateObsPoint') {
    //     const pointList = request.content.rows, lineType = request.lineType;
    //     if (!pointList || pointList.length === 0) return;
    //     lineAdd(pointList, currentMap, lineType);
    } else if (type === 'clearCrossSection') {
        if (pathCrossSection) {
            pathCrossSection.remove(); pathCrossSection = null;
        }
        if (markerCrossSection.length > 0) {
            markerCrossSection.forEach(marker => marker.remove()); 
            markerCrossSection.length = 0;
        }
        currentPointsCross.length = 0; currentPoints.length = 0;
    } else if (type === 'clearBoundary') {
        if (pathBoundary) {
            pathBoundary.remove(); pathBoundary = null;
        }
        if (markerBoundary.length > 0) {
            markerBoundary.forEach(marker => marker.remove()); 
            markerBoundary.length = 0;
        }
        currentPointsBoundary.length = 0; currentPoints.length = 0;    
    } else if (type === 'waqPoint' || type === 'loadsPoint' 
        || type === 'waqUpdate' || type === 'loadsUpdate') {
        
        let iconUrl = null;
        if (type === 'waqPoint' || type === 'waqUpdate') {
            iconUrl =`/src_frontend/images/waq_obs.png?v=${Date.now()}`
        } else {
            iconUrl =`/src_frontend/images/waq_loads.png?v=${Date.now()}`
        }
        if (type === 'waqUpdate') {
            waqObs.forEach(marker => marker.remove()); waqObs.length = 0;
            iconAdd(iconUrl, waqObs, currentMap, request.content.rows);
        } else if (type === 'loadsUpdate') {
            waqLoads.forEach(marker => marker.remove()); waqLoads.length = 0; 
            iconAdd(iconUrl, waqLoads, currentMap, request.content.rows);
        }
    } else if (type === 'flowOptions') {
        const key = request.content.key;
        const content = { requestId: request.content.requestId }
        if (key === 'hideLayer') {
            const config = layerConfig[request.content.layerKey];
            const existing = config.getLayer();
            if (existing) currentMap.removeLayer(existing);
        } else if (key === 'hideColorbar') {
            const colorBar = document.querySelector('.custom-colorbar');
            if (colorBar) colorBar.style.display = 'none';
        } else if (key === 'drawLayer') {
            const layerKey = request.content.layerKey;
            content.checked = null; content.ok = true; content.message = null;
            const config = layerConfig[layerKey];
            const colorBar = document.querySelector('.custom-colorbar');
            if (!colorBar) { 
                content.message = 'Colorbar not found'; 
                signalSender('updateUIState', content); return; 
            }
            if (!config) {
                content.message = 'Layer not found';
                signalSender('updateUIState', content); return;
            }
            if (layerKey.includes('_Vector')) config.setData(request.content.data);
            // Hide all layers
            if (request.content.reset) resetMap(currentMap);
            const existing = config.getLayer();
            if (existing && !request.content.data) {
                existing.addTo(currentMap);
                if (layerKey.includes('_Vector')) { colorBar.style.display = 'none';
                } else { 
                    colorbarReset(colorBar, config.min, config.max, config.title, config.colorKey);
                    colorBar.style.display = 'flex'; 
                }
            } else {
                if (layerKey.includes('_Vector')) {
                    lastLayer = L.geoJSON(
                        config.getData(), { style: { color: 'red', weight: 2, opacity: 1 }}
                    );
                    colorBar.style.display = 'none';
                } else {
                    lastLayer = L.tileLayer(request.content.data, {tileSize: 256, opacity: 1 })
                    colorbarReset(
                        colorBar, request.content.min, request.content.max, config.title, config.colorKey
                    );
                    colorBar.style.display = 'flex';
                }
                config.setLayer(lastLayer); config.min = request.content.min; 
                config.max = request.content.max; lastLayer.addTo(currentMap);
            }
            signalSender('updateUIState', content); return;
        } else if (key === 'reCheck') {
            if (request.content.ok) {
                if (lastLayer) lastLayer = clearMap(lastLayer, currentMap);
                if (layer) layer.addTo(currentMap); lastLayer = layer; 
            } else { if (lastLayer) lastLayer.addTo(currentMap) }
        } else if (key === 'clearAll') {
            // Hide all layers
            resetMap(currentMap);
            currentMap.closeTooltip(hoverTooltip); mapContainer.style.cursor = '';
            if (markerLayer) markerLayer = clearMap(markerLayer, currentMap);
            const colorBar = document.querySelector('.custom-colorbar');
            if (colorBar) colorBar.style.display = 'none';
        } else if (key === 'pourpoint') {  
            markerLayer = clearMap(markerLayer, currentMap);
            if (request.content.checked) {
                isPourpointActive = true; mapContainer.style.cursor = 'crosshair';
            } else {
                isPourpointActive = false; lat = null; lon = null;
                mapContainer.style.cursor = ''; 
            }
            clearPendingRequest(); return;
        } else if (key === 'pourpointCancel') {
            isPourpointActive = false; mapContainer.style.cursor = ''; 
            currentMap.closeTooltip(hoverTooltip); clearPendingRequest();
        } else if (key === 'getLayer') {
            const config = layerConfig[request.content.layerKey];
            const data = config.getData();
            content.data = data;
            signalSender('updateUIState', content); return;
        } else if (key === 'mapPlotter') {
            const layerKey = request.content.layerKey;
            const type = request.content.type;
            const config = layerConfig[layerKey];
            if (!config) {
                content.message = 'Layer not found';
                signalSender('updateUIState', content); return;
            }
            if (request.content.reset) resetMap(currentMap);
            config.setData(request.content.data);
            lastLayer = await mapPlotter(
                config.getData(), currentMap, type
            );
            config.setLayer(lastLayer);
        } else if (key === 'layerChecker') {
            const layerKey = request.content.layerKey;
            const config = layerConfig[layerKey];
            const existing = config.getLayer();
            content.exist = existing !== null ? true : false;
        } else if (key === 'invalidCheck') {
            const layerKey = request.content.layerKey;
            const config = layerConfig[layerKey];
            if (!config) {
                content.message = 'Layer not found';
                signalSender('updateUIState', content); return;
            }
            const existing = config.getLayer();
            signalSender('showOverlay', 'Checking for invalid polygons.\nPlease wait...');
            const invalidContent = [], invalidIDs = [];
            setTimeout(() => { 
                existing.eachLayer((layer) => { 
                    const props = layer.feature?.properties; 
                    let check = !river || river === '' || river === 'None';
                    const river = (props.width ?? '').toString().trim();
                    // Highlight invalid polygons
                    if (check) {
                        layer.setStyle({ color: 'yellow', weight: 3 });
                        const id = props.description; let values = null;
                        values = [id, 'None', 'None']
                        invalidContent.push(values); invalidIDs.push(id);
                    }
                }); signalSender('hideOverlay');
                content.key = request.content.type;
                content.ids = invalidIDs; content.data = invalidContent;
                if (invalidIDs.length === 0) { alert(`All ${request.content.type} polygons are valid.`); 
                } else { alert(`Number of invalid polygons: ${invalidIDs.length}.`); }
                signalSender('showOverlay', 'Sending invalid polygons and updating table.\nPlease wait...');
                signalSender('updateUIState', content); return;
            }, 500);
        } else if (key === 'assignType') {
            const config = layerConfig[request.content.layerKey];
            const id = request.content.id, type = request.content.type;
            const objType = mapping[type];
            if (!config) {
                content.message = 'Layer not found';
                signalSender('updateUIState', content); return;
            }
            signalSender('showOverlay', `Assigning river attribute to the selected polygon.\nPlease wait...`);
            let data = JSON.parse(JSON.stringify(config.getData()));
            data.features = data.features.map(f => {
                if (Number(f.properties.description) === Number(id)) {
                    const values = request.content.data.slice(1).map(v => Number(v));
                    if (objType) {
                        objType.fields.forEach((field, i) => {
                            f.properties[field] = values[i];
                        });
                    }
                    values.unshift(id); content.ids = [id]; content.data = [values];
                    alert(`River "${id}" was registered successfully.`);
                }
                return f;
            }); config.setData(data);
            const oldLayer = config.getLayer();
            if (oldLayer) currentMap.removeLayer(oldLayer);
            lastLayer = await mapPlotter(data, currentMap, type);
            config.setLayer(lastLayer);
            const existing = config.getLayer();
            existing.eachLayer((layer) => { 
                if (Number(layer.feature.properties.description) === Number(id)) {
                    layer.setStyle({ color: 'green', weight: 3, fillOpacity: 0.8, fillColor: 'green' });
                }
                if (layer.getTooltip()) {
                    layer.getTooltip().setContent(buildTooltip(layer.feature.properties, type));
                }
            }); 
            config.setLayer(existing); existing.addTo(currentMap);
            signalSender('hideOverlay'); signalSender('updateUIState', content); return;
        } else if (key === 'deleteItem') {
            const layerKey = request.content.layerKey;
            const id = request.content.id, type = request.content.type;
            const config = layerConfig[layerKey]; let checked = false;
            if (!config) {
                content.message = 'Layer not found';
                signalSender('updateUIState', content); return;
            }
            const existing = config.getLayer();
            existing.eachLayer((layer) => { 
                if (Number(layer.feature.properties.description) === Number(id)) {
                    layer.remove(); existing.removeLayer(layer); checked = true;
                }
                if (layer.getTooltip()) {
                    layer.getTooltip().setContent(buildTooltip(layer.feature.properties, type));
                }
            });
            if (checked) { alert(`Segment "${id}" was deleted from the river layer.`); }
            config.setLayer(existing);
            signalSender('updateUIState', content); return;
        } else if (key === 'weather') {
        //     let iCon = '';
        //     const layerKey = request.content.layerKey, id = request.content.id;
        //     if (id === 'rosim') iCon = `/src_frontend/images/rain.png?v=${Date.now()}`;
        //     const config = layerConfig[layerKey];
        //     if (!config) {
        //         content.message = 'Layer not found';
        //         signalSender('updateUIState', content); return;
        //     }

        
        
        }



        signalSender('updateUIState', content);
    }
}

function colorbarReset(colorBar, vmin, vmax, title, colorKey) {
    const colorbarTitle = colorBar.querySelector(".colorbar-title");
    const colorbarColor = colorBar.querySelector(".colorbar-gradient");
    const colorbarLabel = colorBar.querySelector(".colorbar-labels");
    updateColorbar(vmin, vmax, title, colorKey, colorbarColor, colorbarTitle, colorbarLabel);
    colorBar.style.display = 'flex';
}

export function initMap(mapId='map') { 
    currentMap = L.map(`leaflet-${mapId}`, {
        center:CENTER, zoom: ZOOM, zoomControl: false, attributionControl: true, preferCanvas: true
    }); 
    currentTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(currentMap); 
    // Add scale bar 
    L.control.scale({imperial: false, metric: true, maxWidth: 200}).addTo(currentMap); 
    setTimeout(() => currentMap.invalidateSize(), 100); 
    // Prepare base map
    const container = document.querySelector(`#leaflet-${mapId}`);
    const baseMapBtn = container.querySelector('.leaflet-basemap-btn'); 
    const baseMapPopup = container.querySelector('.basemap-popup'); 
    baseMapBtn.addEventListener('mouseenter', () => { 
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
    mapContainer = currentMap.getContainer();
    currentMap.on('mousemove', async (e) => { 
        const req = getPendingRequest();
        if (!req)  return;
        if (req.requestId === 'waqUpdate' || req.requestId === 'loadsUpdate') return;
        mapContainer.style.cursor = 'crosshair';
        if (req.requestId === 'pickLocation') { html = 'Pick average latitude';
        } else if (req.requestId === 'pickLatLon') { html = 'Pick average location';
        } else if (req.requestId === 'pickPoint') { html = 'Select an HYD point';
        } else if (req.requestId === 'pickPath') {
            html = `
            - Click the left mouse button to select points.<br>
            - Right-click to finish the selection.<br>
            - Number of points must be at least 2.<br>
            `;
        } else if (req.requestId === 'pickSource') { html = 'Select a HYD source';
        } else if (req.requestId === 'waqPoint') { html = 'Select a WAQ observation point';
        } else if (req.requestId === 'loadsPoint') { html = 'Select a WAQ load point';
        } else if (req.requestId === 'drawChecked') { html = 'Draw a polygon using the left mouse button';
        } else if (req.type === 'flowOptions') { 
            if (req.content.key === 'pourpoint' && isPourpointActive) html = "Click to set the pourpoint.";
            if (req.content.key === 'pourpointCancel' || isPourpointActive === false) {
                mapContainer.style.cursor = ''; 
                currentMap.closeTooltip(hoverTooltip); 
                clearPendingRequest();
            }
            

        } else if (req.type === 'updateObsPoint') { 
            mapContainer.style.cursor = 'grab'; return;
        }
        hoverTooltip.setLatLng(e.latlng).setContent(html);
        currentMap.openTooltip(hoverTooltip);


    });
    currentMap.on('click', (e) => { 
        let result = null;
        const req = getPendingRequest(); if (!req) return;
        if (req.requestId === 'pickLocation') { 
            result = Number(e.latlng.lat).toFixed(2);
        } else if (req.requestId === 'pickLatLon') { result = e.latlng;
        } else if (req.requestId === 'pickPoint' || req.requestId === 'pickSource'
            || req.requestId === 'waqPoint' || req.requestId === 'loadsPoint') { result = e.latlng;
        } else if (req.requestId === 'pickPath') {
            const isCross = req.lineType === 'crossSection';
            const points = isCross ? currentPointsCross : currentPointsBoundary;
            const markerList = isCross ? markerCrossSection : markerBoundary;
            const configPoint = isCross ? configCrossSectionPoint : configBoundaryPoint;
            const configPath = isCross ? configCrossSectionPath : configBoundaryPath;
            let line = isCross ? pathCrossSection : pathBoundary;
            // Add point
            currentPoints.push({ lat: e.latlng.lat, lng: e.latlng.lng });
            points.push({ lat: e.latlng.lat, lng: e.latlng.lng });
            // Add marker
            const marker = L.circleMarker(e.latlng, configPoint).addTo(currentMap);
            markerList.push(marker);
            if (points.length < 2) return;
            const latlngs = points.map(p => [p.lat, p.lng]); 
            // Draw/update line
            if (line) { line.setLatLngs(latlngs); line.setStyle(configPath);
            } else {
                line = L.polyline(latlngs, configPath).addTo(currentMap);
                if (isCross) { pathCrossSection = line; } else { pathBoundary = line; }
            }
        } else if (req.content.key === 'pourpoint' && isPourpointActive) {
            result = e.latlng;
            markerLayer = clearMap(markerLayer, currentMap);
            markerLayer = L.circleMarker(e.latlng, {
                radius: 4, fillColor: 'blue', color: 'red', weight: 2, opacity: 1, fillOpacity: 1
            }).addTo(currentMap);
            signalSender('updateUIState', { 
                requestId: req.requestId, result: result 
            });
            clearPendingRequest(); isPourpointActive = false;
            
            
            
            
            
            
            
            
            // if (req.content.key === 'refineChecked' && req.content.checked) {
            //     // if (!currentPoints.includes(feature.properties.id)) { pointContainer.push(feature.properties.id); }
            //     // if (currentPoints.length === 1) { html = "Select end point to refine."; }
            //     // if (currentPoints.length === 2) { 
            //     //     await polygonRefinement(currentPoints); currentPoints = []; 
            //     //     refinementCheckbox().dispatchEvent(new Event('change'));
            //     //     if (hoverTooltip) lakeMap.closeTooltip(hoverTooltip); return; 
            //     // }
            // }
            // console.log(req);
    

        }



        if (req.requestId !== 'pickPath') {
            req.source.postMessage({ requestId: req.requestId, result: result }, origin);
            clearPendingRequest();
            mapContainer.style.cursor = 'grab'; currentMap.closeTooltip(hoverTooltip);
        }
    });
    currentMap.on('contextmenu', async (e) => { 
        e.originalEvent.preventDefault();
        const req = getPendingRequest(); if (!req) return;
        // Right-click
        if (req.requestId === 'pickPath') {
            if (currentPoints.length < 2) {
                alert("Not enough points selected.\nPlease select at least 02 points."); return;
            }
            req.source.postMessage({ requestId: req.requestId, result: currentPoints }, origin);
        // } else if (req.requestId === 'drawChecked') {
        //     if (currentPoints.length < 3) {
        //         alert("Polygon must have at least 3 points."); return;
        //     }
        //     tempLine = clearMap(tempLine, currentMap);
        //     polygonLayer = clearMap(polygonLayer, currentMap);
        //     // Plot polygon
        //     await pointsToPolygon(
        //         req.content.currentProject, currentPoints, polygonLayer, 
        //         pointLayer, currentMap, req.content.action
        //     ); 
        //     // drawChecked = false;




        }
        clearPendingRequest(); currentPoints.length = 0;
        mapContainer.style.cursor = 'grab'; currentMap.closeTooltip(hoverTooltip); 
    });
}

export function clearMap(layer, map) {
    if (layer) { map.removeLayer(layer); }
    return null;
}

function resetMap(map){
    // Hide all layers
    Object.keys(layerConfig).forEach(key => {
        let subLayer = layerConfig[key].getLayer();
        if (subLayer) map.removeLayer(subLayer);
    });
}