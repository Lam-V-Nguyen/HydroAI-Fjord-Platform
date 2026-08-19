import { valueFormatter, L } from "./constant.js";

function getAdaptiveCellSize(polygon, targetCells = 50) {
    const bbox = turf.bbox(polygon); // [minX, minY, maxX, maxY]
    // Approx width & height (meters)
    const width = turf.distance(
        [bbox[0], bbox[1]], [bbox[2], bbox[1]], { units: 'meters' }
    );
    const height = turf.distance(
        [bbox[0], bbox[1]], [bbox[0], bbox[3]], { units: 'meters' }
    );
    const bboxArea = width * height;
    const cellArea = bboxArea / targetCells;
    return Math.sqrt(cellArea);
}

export function toggleMoveMode(targetLayer, enable) {
    targetLayer.eachLayer(layer => {
        if (layer.dragging) {
            enable ? layer.dragging.enable() : layer.dragging.disable();
        }
    });
}

export function getColorFromValue(value, vmin, vmax, colorbarKey) {
    if (typeof value !== 'number' || isNaN(value) || value === null) {
        return { r: 0, g: 0, b: 0, a: 0 };
    }
    if (vmin === vmax) return { r: 0, g: 0, b: 100, a: 1 };
    // Minimum difference
    const minDiff = 1e-2, epsilon = 1e-6;
    if (vmax - vmin < minDiff) vmax = vmin + minDiff;
    let t0, t, colors;
    // avoid zero division error for vmin or vmax = 0
    if (vmin + epsilon <=0 || vmax + epsilon <=0 || colorbarKey === "terrain") { 
        t0 = (value - vmin) / (vmax - vmin);
    } else {
        t0 = (Math.log(value + epsilon) - Math.log(vmin + epsilon)) / 
        (Math.log(vmax + epsilon) - Math.log(vmin + epsilon));
    }
    t = 1 - Math.max(0, Math.min(1, t0));
    if (colorbarKey === "depth") { // used for depth
        colors = [
            { r: 160, g: 216, b: 239 },  // very light blue
            { r: 80,  g: 180, b: 220 },  // light blue
            { r: 0,   g: 119, b: 190 },  // medium blue
            { r: 0,   g: 70,  b: 130 },  // dark blue
            { r: 0,   g: 25,  b: 51  }   // very dark blue
        ];
    } else if (colorbarKey === "vector") { // used for vector
        colors = [
            { r: 220, g: 50,  b: 50  },  // red
            { r: 255, g: 140, b: 0   },  // orange
            { r: 255, g: 215, b: 0   },  // yellow
            { r: 255, g: 0,   b: 255 },  // magenta
            { r: 255, g: 255, b: 255 }   // white
        ];
    } else if (colorbarKey === "terrain") { // used for terrain
        t = 1 - t;
        colors = [
            { r: 0,   g: 70,  b: 0   },   // dark green
            { r: 120, g: 180, b: 0   },   // green
            { r: 210, g: 185, b: 139 },   // tan
            { r: 139, g: 90,  b: 43  },   // brown
            { r: 255, g: 255, b: 255 }    // white
        ];
    } else { // used for temperature, salinity, contaminant, ...
        colors = [
            { r: 255, g: 0,   b: 0   },    // red
            { r: 255, g: 165, b: 0   },   // orange
            { r: 255, g: 255, b: 0   },   // yellow
            { r: 100, g: 150, b: 255 },   // light blue 
            { r: 0,   g: 0,   b: 255 }    // blue
        ];
    }
    const binCount = colors.length - 1;
    const scaledT = t * binCount;
    const lower = Math.floor(scaledT);
    const upper = Math.min(colors.length - 1, lower + 1);
    const frac = scaledT - lower;
    const c1 = colors[lower], c2 = colors[upper];
    const r = Math.round(c1.r + (c2.r - c1.r) * frac);
    const g = Math.round(c1.g + (c2.g - c1.g) * frac);
    const b = Math.round(c1.b + (c2.b - c1.b) * frac);
    return { r, g, b, a: 1 };
}

export function updateColorbar(min, max, title, colorbarKey, bar_color, bar_title, bar_label) {
    bar_title.innerHTML = title.replace(/\n/g, '<br>');
    // Generate 5 color stops
    const colorStops = [], numStops = 5;
    // Minimum difference
    const minDiff = 1e-2, epsilon = 1e-6;
    if (max - min < minDiff) max = min + minDiff;
    // Update 5 labels
    const labels = bar_label.children;
    for (let i = 0; i < numStops; i++) {
        const percent = i / 4; // 0,0.25,0.5,0.75,1
        let value;
        if (min + epsilon > 0 && max + epsilon > 0) {
            const logMin = Math.log(min + epsilon);
            const logMax = Math.log(max + epsilon);
            value = Math.exp(logMin + percent * (logMax - logMin));
        } else { value = min + percent * (max - min);}
        labels[numStops - i - 1].textContent = valueFormatter(value, minDiff);
    }
    // Generate color for colorbar
    for (let i = 0; i < numStops; i++) {
        const t = i / (numStops - 1);
        let value;
        if (min + epsilon > 0 && max + epsilon > 0) {
            const logMin = Math.log(min + epsilon);
            const logMax = Math.log(max + epsilon);
            value = Math.exp(logMin + t * (logMax - logMin));
        } else { value = min + t * (max - min); }
        const color = getColorFromValue(value, min, max, colorbarKey);
        colorStops.push(`rgb(${color.r}, ${color.g}, ${color.b}) ${(t * 100).toFixed(1)}%`);
    }
    // Update gradient
    bar_color.style.background = `linear-gradient(to top, ${colorStops.join(", ")})`;
}

export function gridPlotter(legend, polygon, points, map, colorBarObj, colorbarKey='depth') {
    if (points === null || points.features === null 
        || points.features.length === 0) { return null; }
    // Make grid points colored by depth
    const colorbar_title = colorBarObj.querySelector('.colorbar-title');
    const colorbar_label = colorBarObj.querySelector('.colorbar-labels');
    const colorbar_color = colorBarObj.querySelector('.colorbar-gradient');
    const lakePolygon = polygon.features[0];
    const cellSize = getAdaptiveCellSize(lakePolygon, 800);
    colorBarObj.style.display = 'block';
    const grid = turf.squareGrid(turf.bbox(lakePolygon), cellSize, {units: 'meters'});
    grid.features.forEach(cell => {
        const center = turf.center(cell);
        if (!turf.booleanPointInPolygon(center , lakePolygon)) return;
        let num = 0, den = 0;
        points.features.forEach(p => {
            const d = turf.distance(center , p, {units: 'meters'});
            const w = 1 / Math.max(d, 1);
            num += w * p.properties.depth; den += w;
        });
        if (den > 0) { cell.properties.value = num / den; }
    });
    const vmin = lakePolygon.properties.min, vmax = lakePolygon.properties.max;
    const tempGrid = L.geoJSON(grid, {
        filter: f => f.properties.value !== undefined,
        style: f => {
            const value = f.properties.value;
            const { r, g, b, a } = getColorFromValue(value, vmin, vmax, colorbarKey);
            return { fill: true, fillColor: `rgb(${r},${g},${b})`, 
                fillOpacity: a, weight: 0, opacity: 1, stroke: false };
        }
    }).addTo(map);
    map.fitBounds(tempGrid.getBounds());
    updateColorbar(vmin, vmax, legend, colorbarKey, colorbar_color, colorbar_title, colorbar_label);
    return tempGrid;
}

export function polygonPlotter(polygon, map, entireNorway=false, zoom = false) {
    // Draw polygon
    const tempLayer = L.geoJSON(polygon, {
        style: { color: 'blue', weight: 2, fillColor: 'cyan', fillOpacity: 0 },
        // Add tooltips or popups if needed
        onEachFeature: (feature, layer) => {
            if (feature.properties && entireNorway) {
                let tooltip = `
                    <div style="font-weight: bold; text-align: center;">${feature.properties.name}</div>
                    <hr style="margin: 5px 0 5px 0;">
                    <strong>• Municipality:</strong> ${feature.properties.region}<br>
                    <strong>• Area:</strong> ${feature.properties.area} (m²)<br>
                    <strong>• Perimeter:</strong> ${feature.properties.perimeter} (m)
                `;
                layer.bindTooltip(tooltip, {sticky: true});
            }
        }
    }).addTo(map);
    // Fit map to lake bounds
    const bounds = tempLayer.getBounds();
    if (bounds.isValid() && zoom) { 
        setTimeout(() => { map.invalidateSize(); map.fitBounds(bounds); }, 0);
    }
    return tempLayer;
}

export async function plotUnstructuredGrid(obj, map) {
    const tempLayer = L.geoJSON(obj, {
        style: feature => {
            switch (feature.geometry.type) {
                case 'LineString': 
                case 'MultiLineString': return { color: 'black', weight: 0.5 };
                case 'Polygon':
                case 'MultiPolygon':
                    return { color: 'black', fillColor: 'darkcyan', fillOpacity: 0.5, weight: 0.5 };
                default: return {};
            }
        }
    }).addTo(map);
    return tempLayer;
}

export async function orthoPlotter(data, plotDiv, titleX, titleY, chartTitle) {
    if (!plotDiv) { alert("plotDiv is null"); return; }
    if (!data || data.length === 0) return;
    // Delete existing plot
    Plotly.purge(plotDiv); plotDiv.innerHTML = "";
    const x = data.map(d => d.iteration), minVals = data.map(d => d.min);
    const meanVals = data.map(d => d.mean), maxVals = data.map(d => d.max);
    const traces = [{x: x, y: minVals, mode: 'lines', type: 'scatter', name: 'Min', line: { width: 2 }},
        { x: x, y: meanVals, mode: 'lines', type: 'scatter', name: 'Mean', line: { width: 2 } },
        { x: x, y: maxVals, mode: 'lines', type: 'scatter', name: 'Max', line: { width: 2 } }
    ];
    const layout = {
        title: { text: chartTitle, font: { size: 20, color: 'black', weight: 'bold' } },
        paper_bgcolor: 'rgb(245, 240, 240)', plot_bgcolor: 'rgb(247, 243, 243)', showlegend: true,
        xaxis: {  title: titleX, type: 'linear', showline: true, mirror: true, ticks: 'outside', font: { color: 'black', size: 18 } },
        yaxis: { title: titleY, showline: true, mirror: true, ticks: 'outside', font: { color: 'black', size: 18 } },
        margin: { l: 70, r: 30, t: 50, b: 50 }, 
    };
    Plotly.react(plotDiv, traces, layout, { responsive: true });
}