import { highlightColor } from "./constant.js";

export function setElementsEnabled(enabled, ...elements) {
    elements.forEach(e => {
        e.style.pointerEvents = enabled ? 'auto' : 'none';
        e.style.opacity = enabled ? '1' : '0.4';
    });
}

export function setElementsDisplayed(display, ...elements) {
    elements.forEach(e => {
        e.style.display = display ? 'flex' : 'none';
    });
}

export function isInvalidNumber(value) {
    if (value === null || value === undefined) return true;
    const str = value.toString().trim();
    if (str === '' || str.toLowerCase() === 'none') return true;
    return !Number.isFinite(Number(str));
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
    let selectedLayer = null, layer; const isRiver = key === 'River';
    layer = L.geoJSON(data, {
        style: feature => {
            const id = feature.properties.id;
            if (isRiver) {
                return { color: 'black', weight: 3, opacity: 0.6, fill: false };
            }
            return {
                color: 'black', weight: 1, opacity: 1, fillOpacity: 0.8,
                fillColor: highlightColor(id ?? 0)
            };
        },
        onEachFeature: (feature, featureLayer) => {
            const description = feature.properties.description ?? key;
            let content = '';
            if (key === 'Land Cover') {
                content = `<div style="font-size: 13px;">
                    <div style="font-weight: bold; text-align: center;">Type: ${description}</div>
                    <hr style="margin: 5px 0 5px 0;">
                    <div style="display: block; text-align: center;">Click to see details</div>
                `;
                const popupContent = buildTooltip(feature.properties, key);
                featureLayer.bindPopup(
                    `<div class="popup-content">${popupContent}</div>`,
                    { maxWidth: 400, maxHeight: 200 }
                );
            } else { content = buildTooltip(feature.properties, key); }
            if (isRiver) {
                content += `<hr style="margin: 5px 0 5px 0;">
                    <div style="display: block; text-align: center; font-size: 14px;">Click to edit river's properties</div>
                `;
            }
            // Show tooltip when hovering
            featureLayer.bindTooltip(content, { sticky: true, direction: 'bottom' });
            featureLayer.on('click', (e) => {
                L.DomEvent.stopPropagation(e);
                if (selectedLayer && selectedLayer !== featureLayer) { layer.resetStyle(selectedLayer); }
                featureLayer.setStyle({ color: 'yellow', weight: isRiver ? 5 : 3 });
                selectedLayer = featureLayer;
            });
        }
    }).addTo(map);
    return layer;
}

export function buildTooltip(props, key) {
    let html = `<div style="font-size: 15px;">
        <div style="font-weight: bold; text-align: center;">Type: ${props.description || key}</div>
        <hr style="margin: 5px 0 5px 0;">
    `, unit = '';
    if (key === 'River') { unit = ' (m)'; }
    Object.entries(props).forEach(([k, v]) => {
        if (k === "description" || k === "geometry" || k === "id") return;
        html += `<strong>• ${k}:</strong> ${v}${unit}<br>`;
    }); html += `</div>`;
    return html;
}