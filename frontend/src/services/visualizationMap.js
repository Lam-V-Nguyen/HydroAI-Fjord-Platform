import { CENTER, ZOOM, L, setMap } from "./constant.js";

let tileLayer = null, timeCounter = null;

const $ = (id) => document.getElementById(id);
const obj = { baseMap: $("basemap-btn") };

export async function initMap(id='leaflet-map') {
    const map = L.map(id, { center: CENTER, zoom: ZOOM, zoomControl: false, attributionControl: true });
    tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map); setMap(map);
    L.control.scale({imperial: false, metric: true, maxWidth: 200}).addTo(map);
    setTimeout(() => { map.invalidateSize(); }, 0);
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
            tileLayer.setUrl(url); 
            baseMapPopup.classList.remove('show'); 
        } 
    });
    return map;
}