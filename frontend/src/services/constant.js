export const origin = '*';
export const CENTER = [62.476969, 6.471598];
export const ZOOM = 13, L = window.L, n_decimals = 2;



let state = {}, currentProjectId = null, pendingRequest = null, mapInstance = null;
const getKey = (projectId) => `app_state_${projectId}`;
const defaultState = {
    currentProject: 'demo', waqModel: 'coliform',
    currentParams: [
        'FlowFM_his.zarr', 'FlowFM_map.zarr', 
        'Coliform_his.zarr', 'Coliform_map.zarr'
    ]
}

export const initState = (projectId) => {
    currentProjectId = projectId;
    state = loadState(projectId);
};

const loadState = (projectId) => {
    const saved = localStorage.getItem(getKey(projectId));
    return saved ? JSON.parse(saved) : structuredClone(defaultState);
};

export const getState = () => state;

