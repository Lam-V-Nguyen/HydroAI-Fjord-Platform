import { signalSender, fileUploader, jsonLoader, getUser } from "./commonFunctions.js";
// import { getState } from "./constant.js";
import { generalOptionsManager } from "./generalOptions.js";
import { plotChart } from "./chartManager.js";
import { spatialMapManager } from "./spatialMapManager.js";
import { projectModifier } from "./projectManager.js";

let cachedMenus = {}, html = null, timeOut = null, checked = false, userName = null,
    currentProject, waqModel, currentParams;


function addGISMenu(menu) {
    const li = document.createElement("li"), a = document.createElement("a");
    a.className = "menu"; a.textContent = "GIS Layer"; a.id = "GISMenu";
    a.setAttribute("data-info", "4|gisLayer.html");
    li.appendChild(a); menu.appendChild(li);
}

async function initProject() {
    userName = await getUser();
    let user = userName.split('/').shift(); projectModifier(user); 
}

export function locationFinder(input, suggestion, map) {
    input.addEventListener('input', (e) => {
        clearTimeout(timeOut);
        const value = e.target.value.trim();
        if (value === '' || value.length < 2) { 
            suggestion.style.display = 'none'; return; 
        }
        timeOut = setTimeout(() => {
            fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(value)}&addressdetails=1&limit=100`)
            .then(response => response.json()).then(data => {
                if (data.length === 0) { suggestion.style.display = 'none'; return;}
                suggestion.innerHTML = '';
                data.forEach(location => {
                    var div = document.createElement('div');
                    div.textContent = location.display_name;
                    div.addEventListener('click', () => {
                        var lat = location.lat, lng = location.lon;
                        map.setView([lat, lng], 12);
                        input.value = location.display_name;
                        suggestion.style.display = 'none';
                    });
                    suggestion.appendChild(div);
                });
                suggestion.style.display = 'block';
            })
        }, 200);
    });
}

export async function projectChecker(name, params, waqModel, message, gisChanged=false) {
    cachedMenus = {}; // Clear cache of menus for new project
    signalSender('showOverlay', message); 
    const content = { projectName: name, params: params, waqModel: waqModel, gisChanged: gisChanged };
    const data = await jsonLoader('setup_database', content);
    if (data.status === "error") { 
        alert(data.message); signalSender('hideOverlay');
        // location.reload(); 
        checked = false; return; 
    }
    checked = true;
    const menuLeft = document.getElementById('menu-left');
    const hasGISMenu = menuLeft.querySelector("#GISMenu") !== null;
    if (data.content.gis_layers.length > 0) {
        if (!hasGISMenu) addGISMenu(menuLeft);
    } else { if (hasGISMenu) { hasGISMenu.parentElement.remove(); } }
    signalSender('hideOverlay');
}

export async function initializeMenu(waqName){
    // const project = getState().currentProject, params = getState().currentParams, waqModel = getState().waqModel;
    // Work with pupup menu
    document.querySelectorAll('.nav ul li a:not([style*="display: none"])').forEach(link => {
        link.onclick = async(event) => {
            event.stopPropagation(); event.preventDefault();
            const rect = link.getBoundingClientRect();
            const pm = document.getElementById('popup-menu');
            if (pm.classList.contains('show')) pm.classList.remove('show');
            const info = link.dataset.info;
            if (info === 'home') { window.location.href = "https://ntnusmartwater.github.io/"; return; }
            else if (info === 'gis-upload') { 
                const gisUploadFile = document.getElementById('gis-file');
                if (!gisUploadFile) return;
                // GIS Uploader
                gisUploadFile.click();
                gisUploadFile.addEventListener('change', async (e) => { 
                    const file = e.target.files[0]; if (!file) return;
                    await fileUploader(gisUploadFile, null, project, 
                        file.name, 'Uploading and Processing GIS data.\nPlease wait...', 'gis');
                    const message = `Reloading project '${project}'.\nPlease wait...`;
                    gisUploadFile.value = ''; projectChecker(project, params, waqModel, message, true);
                }); return;
            }
            else if (info == 'project-open') { initProject(); return; }
            if (!checked) { alert('No scenario was loaded. Please select a project to open.'); return; }
            const [id, htmlFile] = info.split('|');
            signalSender('showOverlay', 'Getting Information.\nPlease wait...');
            await showPopupMenu(waqName, id, htmlFile);
            signalSender('hideOverlay');
            pm.style.top = `${rect.bottom + 10 + window.scrollY}px`;
            pm.style.left = `${rect.left + window.scrollX}px`;
            pm.classList.add('show');
        };
    })
}

export async function showPopupMenu(waqName, id, htmlFile) {
    try {
        const popupContent = document.getElementById('popup-content');
        if (!popupContent) return; 
        // const project = getState().currentProject;
        if (cachedMenus[htmlFile]) { 
            popupContent.innerHTML = cachedMenus[htmlFile];
        } else {
            const response = await fetch(`/load_popupMenu?data=${htmlFile}|${waqName}&project_name=${project}`);
            if (!response.ok) { alert(response.message); return; }
            html = await response.text(); cachedMenus[htmlFile] = html;
            popupContent.innerHTML = html;
        }
        if (id === '1') generalOptionsManager(project); // Events on General Options submenu
        if (id === '2') timeSeriesManager(project); // Events on Time series Measurement submenu
        if (id === '3') spatialMapManager(project); // Events on Map submenu
        if (id === '4') {
            const checkBox = popupContent.querySelectorAll('input[type="checkbox"]');
            if (checkBox === null || checkBox.length === 0 ) return;
            for (let i = 0; i < checkBox.length; i++) { 
                checkBox[i].checked = getState().gisLayers[checkBox[i].id]; 
            }
        }
        
    } catch (error) { alert(error + ': ' + htmlFile); }
}

function timeSeriesManager(projectName) {
    // Set function for plot using Plotly
    const plotContainer = document.getElementById('time-series-container');
    const substanceContainer = document.getElementById('substance-container');
    const substancesContent = substanceContainer.querySelector('#substance-content');
    document.querySelectorAll('.function').forEach(plot => {
        plot.addEventListener('click', () => {
            const [key, titleY, chartTitle] = plot.dataset.info.split('|');
            plotChart(projectName, plotContainer, '', key, chartTitle, 'Time', titleY);
        });
    });
    // Process water quality selector
    document.querySelectorAll('.waq_his').forEach(item => {
        item.addEventListener('click', async() => {
            // substanceWindowMap().style.display = 'none';
            const content = { 
                query: item.dataset.info, key: 'substance_check', projectName: projectName 
            };
            const data = await jsonLoader('process_data', content);
            if (data.status === "error") {
                alert(data.message); substanceContainer.style.display = 'none'; return;
            }
            const substanceTitle = substanceContainer.querySelector('#substance-title');
            substanceTitle.textContent = 'Substance - Time Series';
            substancesContent.innerHTML = ''; substanceContainer.style.display = 'flex';
            // Add content
            substancesContent.innerHTML = data.content.map((substance, i) => 
                `<label for="his-${substance}"><input type="radio" name="waq-substance-his" id="his-${substance}"
                    value="${data.message[i]}" ${i === 0 ? 'checked':''}>${data.message[i]}</label>`).join('');
            // hideMap();
            const chartTitle = `Substance: ${data.message[0]}`;
            plotChart(projectName, plotContainer, data.content[0], 'substance', chartTitle, 'Time', data.message[0]);
        });
    });
    // Listen to substance selection
    substancesContent.addEventListener('change', (e) => {
        if (e.target && e.target.name === "waq-substance-his") {
            const id = e.target.id, value = e.target.value;
            // hideMap(); 
            plotChart(projectName, plotContainer, id.replace('his-', ''), 'substance', `Substance: ${value}`, 'Time', value);
        }
    });
}
