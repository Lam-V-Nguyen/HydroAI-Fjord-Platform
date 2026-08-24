import { menuManager } from "./menuManager.js";
// import { projectMaker, projectModifier } from "./projectManager.js";
import { pdfOpener } from "./projectManager.js";
import { initGrid, addWidget, loadWidget, saveWidget, hasWidget } from "./widgetFunctions.js";
import { startLoading, stopLoading, htmlLoader, jsonLoader,
    // initRequestListener
} from "./commonFunctions.js";
// import { setState } from "./constant.js";
import { 
    setPendingRequest, initState, getState, clearPendingRequest, origin 
} from "./constant.js";
import { renderPreview } from "./mapManager.js";


const widgetMenu = document.getElementById("widgetMenu"); 
const menuContainer = document.getElementById('menu-container');

const githubCache = {}, pendingRequests = new Map();
let currentProject, waqModel, currentParams, isLoaded = false, 
    userName = null, prevSource = null;
// const exits = ['hyd-plot-source', 'hyd-plot-meteo', 'run-hyd', 'run-waq'];

// initRequestListener();

await login(); await projectChecker(); loadWidget();
widgetMenuManager(); updateComponent(); 
showGitHubLastUpdate('Lam-V-Nguyen', 'HydroAI-Fjord-Platform', 'dev');


async function login() {
    const data = await jsonLoader('auth_check', {}); 
    if (data.user === 'admin') { userName = ''; } else { userName = data.user; }
    initState(userName); currentProject = getState()?.currentProject || 'demo';
    // waqModel = getState()?.waqModel || 'coliform', 
    // currentParams = getState()?.currentParams || 
    // ['FlowFM_his.zarr', 'FlowFM_map.zarr', 'Coliform_his.zarr', 'Coliform_map.zarr'];
}

async function projectChecker() { 
    if (getState().currentProject === 'admin' || getState().currentProject === null) return; 
    // startLoading('Setting up Database.\nThis takes a while (especially the first time).\nPlease wait...'); 
    // await new Promise(requestAnimationFrame);
    // setState({ 
    //     currentProject: currentProject, currentParams: currentParams, waqModel: waqModel 
    // });
    // const data = await jsonLoader('setup_database', { 
    //     projectName: getState().currentProject, 
    //     params: getState().currentParams, waqModel: getState().waqModel
    // }); stopLoading();
    // if (data.status === "error") { alert(data.message); return; }
    showNotes(`${userName}/${getState().currentProject}`);
    // console.log('mainManager:', getState().currentProject, getState().waqModel, getState().currentParams);
} 

function widgetMenuManager() {
    widgetMenu.addEventListener("mouseenter", (e) => {
        e.target.dispatchEvent(new Event('click'));
    });
    widgetMenu.addEventListener("click", async () => { 
        if (!isLoaded) { 
            const res = await htmlLoader('getWidgetMenu'); 
            if (!res) { alert('Could not load menu.'); return; }
            menuManager(menuContainer, res); isLoaded = true;
            menuContainer.style.display = 'flex'; 
        } else { 
            isLoaded = false;
            menuContainer.style.display = 'none';
        }
    }); 
    // Menu click handler
    widgetMenu.addEventListener("mouseenter", (e) => { e.target.dispatchEvent(new Event('click')); });
    menuContainer.addEventListener("click", (e) => { 
        const item = e.target.closest(".submenu-item") || e.target.closest(".menu-link"); 
        if (!item) return;
        const id = item.id; if (!id) return;
        const url = item.dataset?.url;
        let w = 6, h = 7, title = item.textContent.replace(/▸|◂/g, '').trim();
        const closeMenu = () => { menuContainer.style.display = 'none'; };
        if (hasWidget(id)) { alert('Widget already exists.'); closeMenu(); return; }
//         if (id === 'new-project') { projectMaker(); closeMenu(); return; }
//         else if (id === 'open-project') { projectModifier(user, 'open'); closeMenu(); return; }
//         else if (id === 'delete-project') { projectModifier(user, 'delete'); closeMenu(); return; }
        
        


//         else if (id === 'flow-data-preparation') { 
//             w = 11; h = 8; title = 'Data Preparation for Flow Estimation';
        if (id === 'preparation-hyd') { w = 12; h = 7; title = 'Data Preparation for HYD Scenario'; }
        else if (id === 'grid-generation') { w = 12; h = 10; }
        else if (id === 'new-hyd' || id === 'new-waq') { w = 11; h = 9; }
        else if (id === 'run-hyd' || id === 'run-waq') { w = 9; h = 3; }
        else if (id === 'visualization') { w = 12; h = 9; }
//         else if (id === 'run-flow-model') { w = 16; h = 8; }
        else if (id === 'help-docs') { pdfOpener(url); closeMenu(); return; }
        else if (id === 'about') { w = 8; h = 5; }
        else if (id === 'data-download') { w = 7; h = 12; }
        addWidget(w, h, title, id, url); closeMenu();
    });
    document.addEventListener("click", (e) => { 
        // Close button handler 
        if (e.target.classList.contains("remove-btn")) { 
            const widget = e.target.closest(".grid-stack-item");
            if (widget) {
                const widgetId = widget.getAttribute("gs-id");
                saveWidget();  // Save grid layout before removing
                const mapEl = document.querySelector(`[gs-id=${widgetId}-map]`);
                if (mapEl !== null) {
                    const mapEL_btn = mapEl.querySelector('.remove-btn');
                    if (mapEL_btn !== null) mapEL_btn.click();
                }
                // Remove map if it exists
                const grid = initGrid();
                if (grid) {
                    const widgetNode = document.querySelector(`[gs-id="${widgetId}"]`);
                    if (widgetNode) {
                        grid.removeWidget(widgetNode, true);
                        setTimeout(() => { grid.update(); saveWidget(); }, 100);
                    }
                }
            } 
        } 
        // Edit title handler 
        if (e.target.classList.contains("widget-title")) { 
            const newTitle = prompt("Enter new title:", e.target.textContent); 
            if (newTitle) { 
                e.target.textContent = newTitle; saveWidget();
            } 
        }
    });
}

function updateComponent() {
    clearPendingRequest();
    // Listen for state change
    window.addEventListener('message', async (event) => {
        if (event.data.type === 'GET_USER') { // Get project destination
            const project = document.querySelector(".project-note");
            if (!project) return;
            const content = project.textContent.split(':').pop();
            event.source.postMessage({ type: 'USER', content: content }, origin);
        } else if (event.data.type === 'addMapWidget') { // Add map
            const id = event.data.content.id;
            if (!hasWidget(id)) addWidget(12, 5, event.data.content.title, id);
        } else if (event.data.id === 'hyd-waq') {
            const req = { 
                source: event.source, lineType: event.data.lineType,
                requestId: event.data.requestId, content: event.data.content
            };
            setPendingRequest(req); renderPreview(req);
        } else if (event.data.type === 'showOverlay') { 
            startLoading(event.data.content);
            await new Promise(requestAnimationFrame);
        } else if (event.data.type === 'hideOverlay') { 
            stopLoading(); await new Promise(requestAnimationFrame);
        } else if (event.data.type === 'updateObsPoint') { 
            const req = { 
                source: event.source, type: event.data.type, 
                content: event.data.content.content
            };
            setPendingRequest(req); renderPreview(req);
        } else if (event.data.type === 'clearCrossSection') { 
            renderPreview({ type: event.data.type });
        } else if (event.data.type === 'clearBoundary') { 
            renderPreview({ type: event.data.type });
//         } else if (event.data.type === 'clearGridMap') { 
//             renderPreview({ source: event.source, requestId: event.data.type });
//         } else if (event.data.type === 'colorbarOption') { 
//             renderPreview({ 
//                 source: event.source, content: event.data.content,
//                 requestId: event.data.type 
//             });
//         } else if (event.data.type === 'gridPlot') { 
//             renderPreview({ 
//                 source: event.source, requestId: event.data.type,
//                 content: event.data.content
//             });
//         } else if (event.data.type === 'flowOptions') { 
//             const { requestId } = event.data.content;
//             pendingRequests.set(requestId, { source: event.source });
//             const req = { 
//                 source: event.source, requestId: requestId,
//                 content: event.data.content, type: event.data.type
//             };
//             renderPreview(req); setPendingRequest(req);
        } else if (event.data.type === 'showNote') {
            showNotes(event.data.content);
        } else if (event.data.type === 'updateUIState') {
            const { requestId } = event.data.content;
            if (requestId && pendingRequests.has(requestId)) {
                const { source } = pendingRequests.get(requestId);
                prevSource = source;
                source.postMessage({ type: 'updateReturn', 
                    content: event.data.content, requestId: requestId
                }, origin);
                pendingRequests.delete(requestId);
            } else {
                prevSource.postMessage({ type: 'updateUIDelay', 
                    content: event.data.content,
                }, origin);
            }
        }
    });
}

async function showGitHubLastUpdate(username, repo, branch = 'main') {
    const url = `https://api.github.com/repos/${username}/${repo}/commits?sha=${branch}&per_page=1`;
    const key = `${username}/${repo}/${branch}`;
    if (githubCache[key]) {
        document.querySelector('.github-last-update').textContent = githubCache[key];
        return;
    }
    const displayDiv = document.querySelector('.github-last-update');
    if (!displayDiv) return;
    try {
        const header = {
            "Accept": "application/vnd.github+json", "User-Agent": repo
        }
        const response = await fetch(url, { headers: header });
        if (!response.ok) throw new Error('GitHub API error');
        const data = await response.json();
        if (data.length > 0) {
            const date = new Date(data[0].commit.committer.date);
            const formatted = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
            const text = `Branch: ${branch} | Last update: ${formatted}`;
            githubCache[key] = text; displayDiv.textContent = text;
        } else {
            displayDiv.textContent = 'Last update: unknown';
        }
    } catch (err) { alert(err); displayDiv.textContent = 'Last update: error'; }
}

export function showNotes(note) {
    const noteDiv = document.querySelector('.project-note');
    if (!noteDiv) return;
    noteDiv.textContent = `Project: ${note}`;
}