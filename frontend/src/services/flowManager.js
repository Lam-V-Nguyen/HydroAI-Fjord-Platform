import { jsonLoader, signalSender } from "./commonFunctions.js";
import { highlightColor } from "./constant.js";

export async function catchmentDelineation(projectName, flowName, terrainName, lat, lon, snapDistance) {
    if (lat === null || lon === null) { alert('Please set the pourpoint coordinates and create a catchment first.'); return; }
    if (threshold === '') { alert('Please set the threshold first.'); return; }
    if (snapDistance === '') { alert('Please set the snap distance first.'); return; }
    try {
        signalSender('showOverlay', 'Generating catchment. Please wait ...');
        const contents = { projectName: projectName, filename: terrainName,
            lat: lat, lon: lon, snapDistance: snapDistance, flowName: flowName
        };
        const response = await jsonLoader('catchment', contents);
        signalSender('hideOverlay');
        if (response.status === "error") { alert(response.message); return null; }
        return response.content;
    } catch (error) { 
        alert(`Running catchment algorithm failed: ${error.message}`); return null;
    }
}

export async function geoJSONExporter(data, fileName) {
    try { 
        const json = JSON.stringify(data, null, 2);
        if ('showSaveFilePicker' in window) {
            // --- Chrome/Edge/Opera ---
            const fileHandle = await window.showSaveFilePicker({
                suggestedName: fileName,
                types: [{
                    description: 'GeoJSON',
                    accept: { 'application/json': ['.geojson'] }
                }]
            });
            const writable = await fileHandle.createWritable();
            await writable.write(json); await writable.close();
            await new Promise(res => setTimeout(res, 200));
        } else {
            // --- Fallback cho Firefox, Safari ---
            const blob = new Blob([json], { type: 'application/geo+json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = fileName;
            document.body.appendChild(a); 
            setTimeout(() => a.click(), 0);
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }
        alert(`Exporting succeeded.`);
    } catch (error) { alert(`Exporting failed: ${error.message}`); }
}

export async function mapPlotter(data, map, key) {
    const isRiver = key === 'river'; let type = null;
    const resetStyle = (layer) => {
        const id = layer.feature?.properties?.description;
        if (isRiver) {
            layer.setStyle({ 
                color: 'black', weight: 3, opacity: 1, fill: false
            });
            return;
        }
        layer.setStyle({  // Reset to default style
            color: 'black', weight: 1, opacity: 1,
            fillOpacity: 0.8, fillColor: highlightColor(id ?? 0) 
        });
    };
    const layer = L.geoJSON(data, { 
        style: feature => { 
            const id = feature.properties.id;
            if (isRiver) { 
                return { 
                    color: 'black', weight: 3, opacity: 1, fill: false
                };
            }
            return { 
                color: 'black', weight: 1, opacity: 1,
                fillOpacity: 0.8, fillColor: highlightColor(id ?? 0) 
            };
        },
        onEachFeature: (feature, featureLayer) => { 
            const id = feature.properties.description;
            featureLayer.on('click', (e) => { 
                L.DomEvent.stopPropagation(e);
                // Reset the color of all features
                layer.eachLayer(resetStyle);
                // Highlight the clicked feature
                featureLayer.setStyle({ color: 'yellow', weight: isRiver ? 7 : 5 });
                if (isRiver) { 
                    featureLayer.setStyle({ fillOpacity: 0.8 }); 
                }
                const result = tableAdjust(feature.properties, key);
                signalSender('updateUIState', { 
                    key: key, ids: [id], data: [result]
                });
            });
            featureLayer.bindTooltip(`${buildTooltip(feature.properties, key)}`, {sticky: true});
        }
    }).addTo(map);
    map.on('click', () => { layer.eachLayer(resetStyle); });
    return layer;
}

export function buildTooltip(props, key) {
    let html = `<div style="font-size: 15px;">
        <div style="font-weight: bold; text-align: center;">Type: ${props.description || 'Unknown'}</div>
        <hr style="margin: 5px 0 5px 0;">
    `;
    Object.entries(props).forEach(([k, v]) => {
        if (k === "description" || k === "geometry" || k === "id") return;
        html += `<strong>• ${k}:</strong> ${v}<br>`;
    });
    // if (key === 'eklima' || key === 'ntnu' || key === 'nve') {
    //     html += `
    //         <div style="font-weight: bold; text-align: center;">Name: ${props.name || 'Unknown'}</div>
    //         <hr style="margin: 5px 0 5px 0;">
    //         <strong>• ID:</strong> ${props.id ?? 'Unknown'}<br>
    //         <strong>• County:</strong> ${props.county ?? 'Unknown'}<br>
    //         <strong>• Municipality:</strong> ${props.municipality ?? 'Unknown'}<br>
    //         <strong>• Station Holders:</strong> ${props.stationHolders ?? 'Unknown'}<br>
    //         <hr style="margin: 5px 0 5px 0;">
    //         <strong>Click to get weather data</strong>
    //     `;
    // }
    html += `</div>`;
    return html;
}

function tableAdjust(props) {
    return Object.entries(props)
        .filter(([k]) => k !== "geometry")
        .map(([_, v]) => v ?? 'Unknown');
}