import { setupTabs } from "./tabManager.js";
import { getUser, signalSender, getProjectList, jsonLoader, updateLog, nameChecker
} from "./commonFunctions.js";
import { initMap } from "./visualizationMap.js";
import { projectRender } from "./projectManager.js";
import { CENTER, ZOOM, getLastTimeZone } from "./constant.js";


const hoverTooltip = L.tooltip({
    permanent: false, direction: 'bottom',
    sticky: true, offset: [0, 10], className: 'custom-tooltip'
});

const $ = (id) => document.getElementById(id);
const obj = {
    projectList: $('project-list'), projectName: $('project-name'), projectOpener: $('open-btn'),
    // modelInterval: $('model-step'), modelStart: $('model-start'), modelEnd: $('model-end'),
    // modelCheckBtn: $('model-check-btn'), modelLogText: $('model-log'), 
    // modelLat: $('model-lat'), modelLon: $('model-lon'), modelRunBtn: $('model-run-btn')
}


let currentProject;

setupTabs(document); await getProject();
const mapObj = await initMap('leaflet-map-flow-estimation'); 
mapOptions(mapObj); 



async function getProject() { 
    const userName = await getUser(); currentProject = userName.split('/').pop();
    const respond = await getProjectList(`${currentProject}/flows`, '');
    await projectRender(obj.projectName, obj.projectList, respond);
}


function mapOptions(map) {
    const mapElement = map.getContainer();
    const mapContainer = mapElement.parentElement;
    if (map._resizeObserver) {map._resizeObserver.disconnect();}
    map._resizeObserver = new ResizeObserver(() => {
        if (mapContainer.clientWidth > 0 && mapContainer.clientHeight > 0) {
            map.invalidateSize({ pan: false });
        }
    });
    map._resizeObserver.observe(mapContainer); 
    requestAnimationFrame(() => {
        map.invalidateSize({ pan: false }); map.setView(CENTER, ZOOM, { animate: false });
    });
    // map.on('mousemove', function (e) {
    //     if (layerChecker) {
    //         mapElement.style.cursor = 'crosshair';
    //         hoverTooltip.setLatLng(e.latlng).setContent('Select point.');
    //         map.openTooltip(hoverTooltip);
    //     } else {
    //         map.closeTooltip(hoverTooltip); mapElement.style.cursor = '';
    //     }
    // });
    // map.on('click', async function (e) {
    //     if (layerChecker) {
    //         const lat = Number(e.latlng.lat).toFixed(8), lon = Number(e.latlng.lng).toFixed(8);
    //         obj.modelLat.value = lat; obj.modelLon.value = lon;
    //         if (pointLayer) { mapObj.removeLayer(pointLayer); }
    //         pointLayer = L.circleMarker(e.latlng, {
    //             radius: 4, fillColor: 'blue', color: 'red', weight: 2, opacity: 1, fillOpacity: 1
    //         }).addTo(mapObj);
    //         layerChecker = false; mapElement.style.cursor = ''; obj.upstreamCheckbox.checked = false;
    //     }
    // });
}

