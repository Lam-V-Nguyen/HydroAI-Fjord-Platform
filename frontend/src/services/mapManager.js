// export let currentMap;

// export function initMap(mapId='map') { 
//     currentMap = L.map(`leaflet-${mapId}`, {
//         center:CENTER, zoom: ZOOM, zoomControl: false, attributionControl: true, preferCanvas: true
//     }); 
//     currentTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(currentMap); 
//     // Add scale bar 
//     L.control.scale({imperial: false, metric: true, maxWidth: 200}).addTo(currentMap); 
//     setTimeout(() => currentMap.invalidateSize(), 100); 
//     // Prepare base map
//     const container = document.querySelector(`#leaflet-${mapId}`);
//     const baseMapBtn = container.querySelector('.leaflet-basemap-btn'); 
//     const baseMapPopup = container.querySelector('.basemap-popup'); 
//     baseMapBtn.addEventListener('mouseenter', () => { 
//         baseMapPopup.classList.add('show'); clearTimeout(timeCounter); 
//         // Hide the popup after 4 seconds 
//         timeCounter = setTimeout(() => {
//             baseMapPopup.classList.remove('show');
//         }, 4000);
//     }); 
//     // Change base map 
//     baseMapPopup.addEventListener('click', (e) => { 
//         if (e.target.classList.contains('basemap-option')) { 
//             const url = e.target.dataset.url; 
//             currentTileLayer.setUrl(url); 
//             baseMapPopup.classList.remove('show'); 
//         } 
//     });
//     mapContainer = currentMap.getContainer();
//     currentMap.on('mousemove', async (e) => { 
//         const req = getPendingRequest();
//         if (!req)  return;
//         if (req.requestId === 'waqUpdate' || req.requestId === 'loadsUpdate') return;
//         mapContainer.style.cursor = 'crosshair';
//         if (req.requestId === 'pickLocation') { html = 'Pick average latitude';
//         } else if (req.requestId === 'pickLatLon') { html = 'Pick average location';
//         } else if (req.requestId === 'pickPoint') { html = 'Select an HYD point';
//         } else if (req.requestId === 'pickPath') {
//             html = `
//             - Click the left mouse button to select points.<br>
//             - Right-click to finish the selection.<br>
//             - Number of points must be at least 2.<br>
//             `;
//         } else if (req.requestId === 'pickSource') { html = 'Select a HYD source';
//         } else if (req.requestId === 'waqPoint') { html = 'Select a WAQ observation point';
//         } else if (req.requestId === 'loadsPoint') { html = 'Select a WAQ load point';
//         } else if (req.requestId === 'drawChecked') { html = 'Draw a polygon using the left mouse button';
//         } else if (req.type === 'flowOptions') { 
//             if (req.content.key === 'pourpoint' && isPourpointActive) html = "Click to set the pourpoint.";
//             if (req.content.key === 'pourpointCancel' || isPourpointActive === false) {
//                 mapContainer.style.cursor = ''; 
//                 currentMap.closeTooltip(hoverTooltip); 
//                 clearPendingRequest();
//             }
            

//         } else if (req.requestId === 'updateObsPoint') { 
//             mapContainer.style.cursor = 'grab'; return;
//         }
//         hoverTooltip.setLatLng(e.latlng).setContent(html);
//         currentMap.openTooltip(hoverTooltip);


//     });
//     currentMap.on('click', (e) => { 
//         let result = null;
//         const req = getPendingRequest(); if (!req) return;
//         if (req.requestId === 'pickLocation') { 
//             result = Number(e.latlng.lat).toFixed(2);
//         } else if (req.requestId === 'pickLatLon') { result = e.latlng;
//         } else if (req.requestId === 'pickPoint' || req.requestId === 'pickSource'
//             || req.requestId === 'waqPoint' || req.requestId === 'loadsPoint') { result = e.latlng;
//         } else if (req.requestId === 'pickPath') {
//             const isCross = req.lineType === 'crossSection';
//             const points = isCross ? currentPointsCross : currentPointsBoundary;
//             const markerList = isCross ? markerCrossSection : markerBoundary;
//             const configPoint = isCross ? configCrossSectionPoint : configBoundaryPoint;
//             const configPath = isCross ? configCrossSectionPath : configBoundaryPath;
//             let line = isCross ? pathCrossSection : pathBoundary;
//             // Add point
//             currentPoints.push({ lat: e.latlng.lat, lng: e.latlng.lng });
//             points.push({ lat: e.latlng.lat, lng: e.latlng.lng });
//             // Add marker
//             const marker = L.circleMarker(e.latlng, configPoint).addTo(currentMap);
//             markerList.push(marker);
//             if (points.length < 2) return;
//             const latlngs = points.map(p => [p.lat, p.lng]); 
//             // Draw/update line
//             if (line) { line.setLatLngs(latlngs); line.setStyle(configPath);
//             } else {
//                 line = L.polyline(latlngs, configPath).addTo(currentMap);
//                 if (isCross) { pathCrossSection = line; } else { pathBoundary = line; }
//             }
//         } else if (req.content.key === 'pourpoint' && isPourpointActive) {
//             result = e.latlng;
//             markerLayer = clearMap(markerLayer, currentMap);
//             markerLayer = L.circleMarker(e.latlng, {
//                 radius: 4, fillColor: 'blue', color: 'red', weight: 2, opacity: 1, fillOpacity: 1
//             }).addTo(currentMap);
//             signalSender('updateUIState', { 
//                 requestId: req.requestId, result: result 
//             });
//             clearPendingRequest(); isPourpointActive = false;
            
            
            
            
            
            
            
            
//             // if (req.content.key === 'refineChecked' && req.content.checked) {
//             //     // if (!currentPoints.includes(feature.properties.id)) { pointContainer.push(feature.properties.id); }
//             //     // if (currentPoints.length === 1) { html = "Select end point to refine."; }
//             //     // if (currentPoints.length === 2) { 
//             //     //     await polygonRefinement(currentPoints); currentPoints = []; 
//             //     //     refinementCheckbox().dispatchEvent(new Event('change'));
//             //     //     if (hoverTooltip) lakeMap.closeTooltip(hoverTooltip); return; 
//             //     // }
//             // }
//             // console.log(req);
    

//         }



//         if (req.requestId !== 'pickPath') {
//             req.source.postMessage({ requestId: req.requestId, result: result }, origin);
//             clearPendingRequest();
//             mapContainer.style.cursor = 'grab'; currentMap.closeTooltip(hoverTooltip);
//         }
//     });
//     currentMap.on('contextmenu', async (e) => { 
//         e.originalEvent.preventDefault();
//         const req = getPendingRequest(); if (!req) return;
//         // Right-click
//         if (req.requestId === 'pickPath') {
//             if (currentPoints.length < 2) {
//                 alert("Not enough points selected.\nPlease select at least 02 points."); return;
//             }
//             req.source.postMessage({ requestId: req.requestId, result: currentPoints }, origin);
//         // } else if (req.requestId === 'drawChecked') {
//         //     if (currentPoints.length < 3) {
//         //         alert("Polygon must have at least 3 points."); return;
//         //     }
//         //     tempLine = clearMap(tempLine, currentMap);
//         //     polygonLayer = clearMap(polygonLayer, currentMap);
//         //     // Plot polygon
//         //     await pointsToPolygon(
//         //         req.content.currentProject, currentPoints, polygonLayer, 
//         //         pointLayer, currentMap, req.content.action
//         //     ); 
//         //     // drawChecked = false;




//         }
//         clearPendingRequest(); currentPoints.length = 0;
//         mapContainer.style.cursor = 'grab'; currentMap.closeTooltip(hoverTooltip); 
//     });
// }