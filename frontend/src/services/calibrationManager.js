import { setupTabs } from "./tabManager.js";
import { projectRender } from "./projectManager.js";
import { getProjectList, signalSender, jsonLoader, fillTable, getDataFromTable
} from "./commonFunctions.js";
import { calibrationParams, getCalibrationParam } from "./constant.js";


const $ = (id) => document.getElementById(id);
const obj = {
    projectList: $('project-list'), projectName: $('project-name'), projectBtn: $('project-btn'),
    simulationStartDate: $('sim-start-date'), simulationEndDate: $('sim-end-date'),
    iterationNumber: $('iteration-number'), calibrationLog: $('calibration-text'), 
    progressBar: $("progressbar"), progressText: $("progress-text"), 
    progressContainer: $("progressbar-container"), iterationBtn: $('iteration-btn'), 
    runSimulationBtn: $('run-simulation-btn'), observationBtn: $('observation-btn'), 
    observationFile: $('observation-file'), observationName: $('observation-name'),
    observationStartDate: $('observation-start-date'), observationEndDate: $('observation-end-date'),
    observationTable: $('observation-table'), extractStationBtn: $('extract-station-btn'), 
    stationSelector: $('station-select'), depthSelection: $('depth-selection'),
    criteriaTarget: $('criteria-select'), weightSelector: $('weight-select'),
    summaryBtn: $('summary-btn'), correlationBtn: $('correlation-btn'),
    sensitivityObject: $('sensitivity-analysis'), sensitivityContainer: $('sensitivity-container'), 
    surrogateSelector: $('surrogate-select'), surrogateBtn: $('surrogate-btn'),
    optimizationLogContainer: $('optimization-log'), optimizationChartContainer: $('optimization-chart'),
    optimizationLog: $('model-text'), optimizationDirection: $('direction-select'),
    optimizationIterations: $('iteration-value'), optimizationBtn: $('optimization-btn'),
    optimizationProgressBarContainer: $('progressbar-optimization-container'), 
    optimizationProgressBar: $('progressbar-optimization'), 
    optimizationProgressText: $('progress-optimization-text'),
    optimizationResults: $('optimization-results'), optimizationPlotBtn: $('plot-optimization-btn'),
    optimizationSaveBtn: $('save-optimization-btn'),

    


    
    
    
    
    
    
}

let currentProject = null, activeProject = null, isRunning = false, logInterval = null, lastOffsetHYD = 0;

setupTabs(document); await getProject();
await initParameterContainer(); calibrationManager();

async function getProject() { 
    const respond = await getProjectList('', 'input');
    await projectRender(obj.projectName, obj.projectList, respond);
}

async function initParameterContainer() {
    const container = document.querySelector('.parameter-container');
    container.innerHTML = `
        <div class="parameter-header">
            <div>Checked</div><div>Parameter</div>
            <div>Lower</div><div>Upper</div>
        </div>
    ${calibrationParams.map(param => `
        <div class="parameter-row" data-param="${param.value}">
            <div><input class="param-check" type="checkbox" ${param.checked ? 'checked' : ''}></div>
            <div>${param.name}</div>
            <div><input class="param-lower" type="text" value="${param.lower}" placeholder="Lower"></div>
            <div><input class="param-upper" type="text" value="${param.upper}" placeholder="Upper"></div>
        </div>
        `).join('')}
    `;
    container.addEventListener('change', e => {
        const row = e.target.closest('.parameter-row');
        if (!row) return;
        const value = row.dataset.param;
        const param = getCalibrationParam(value);
        if (!param) return;
        if (e.target.classList.contains('param-check')) {
            param.checked = e.target.checked;
        }
        if (e.target.classList.contains('param-lower')) {
            param.lower = parseFloat(e.target.value);
        }
        if (e.target.classList.contains('param-upper')) {
            param.upper = parseFloat(e.target.value);
        }
    });
}

function calibrationManager() {
    obj.projectBtn.addEventListener('click', async () => {
        currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        signalSender('Reading information from project "' + currentProject + '". Please wait...');
        const content = { projectName: currentProject };
        const data = await jsonLoader('calibration_project', content); signalSender('hideOverlay');
        if (data.status === 'error') { alert(data.message); return; }
        obj.simulationStartDate.value = data.content['start'];
        obj.simulationEndDate.value = data.content['end'];
    });
    obj.iterationBtn.addEventListener('click', async () => {
        const currentProject = obj.projectName.value.trim(), key = 'iteration';
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        const iterationNumber = parseInt(obj.iterationNumber.value);
        if (isNaN(iterationNumber) || iterationNumber <= 0) { alert('Please specify the number of resampling.'); return; }
        // Get checked parameters and their bounds
        const checkedParams = calibrationParams.filter(p => p.checked);
        if (checkedParams.length === 0) { alert('Please specify at least one parameter to be calibrated.'); return; }
        const params_in = checkedParams.map(p => [p.value, p.lower, p.upper]);
        if (isRunning) { alert("Iteration is currently running."); return; }
        // Reset UI
        activeProject = currentProject; isRunning = true;
        obj.progressText.innerText = 'Iteration is in progress. Please wait...'; 
        obj.progressContainer.style.display = 'flex'; obj.progressBar.value = 0; 
        obj.calibrationLog.value = ''; 
        const content = { 
            projectName: currentProject, key: key, 
            iterationNumber: iterationNumber, params: params_in
        };
        try {
            const start = await jsonLoader('start_calibration_iteration', content);
            if (start.status === "running") {
                obj.progressBar.value = start.progress || 0;
                obj.progressText.innerText = start.message || 'Iteration is already running.';
            }
            if (start.status === "failed") { 
                isRunning = false; obj.progressBar.value = 0;
                obj.progressText.innerText = start.message || 'Failed to start iteration.';
                alert(start.message || 'Failed to start iteration.'); return; 
            }
            updateLogResampling(currentProject, key, obj.progressBar, obj.progressText, 1);
        } catch (error) { 
            obj.progressText.innerText = 'Failed to start iteration.';
            alert(`Iteration is failed: ${error.message}`); isRunning = false;
        }
    });
    obj.runSimulationBtn.addEventListener('click', async () => {
        currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        const samplingName = obj.resamplingName.value.trim();
        if (samplingName === '') { alert('Please specify a name for the resampling.'); return; }
        const key = 'calibration', logFile = 'log.txt';
        if (isRunning) { alert("Detected an HYD simulation is running. Please wait until it finishes."); return; }
        obj.calibrationLog.value = ''; obj.progressBar.value = 0;
        obj.progressContainer.style.display = 'flex';
        const checkContent = { projectName: currentProject, key: key };
        const statusRes = await jsonLoader('check_sim_status_calibration', checkContent);
        if (statusRes.status === "running") {
            const res = await fetch(`/calibration_log_full/${currentProject}?log_file=${logFile}`);
            if (res.ok) {
                const data = await res.json();
                obj.calibrationLog.value = data.content || ''; lastOffsetHYD = data.offset;
            }; isRunning = true;
            updateLogSimulation(
                currentProject, key, obj.calibrationLog, obj.progressBar, obj.progressText, 5, logFile
            );
            obj.progressText.innerText = statusRes.message; obj.progressBar.value = statusRes.progress;
            alert("HYD simulation is already running."); return; 
        } else { isRunning = false; }
        const content = { projectName: currentProject, key: key, samplingName: samplingName };
        const start = await jsonLoader('start_sim_calibration', content);
        if (start.status === "error") { alert(start.message); return; }
        obj.progressText.innerText = 'Preparing data for the HYD simulation...';
        updateLogSimulation(currentProject, key, obj.calibrationLog, obj.progressBar, obj.progressText, 5, logFile);
    });
    obj.observationBtn.addEventListener('click', () => {
        const currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a HYD scenario first.'); return; }
        obj.observationFile.click();
    });
    obj.observationFile.addEventListener('change', async (e) => {
        const simStart = obj.simulationStartDate.value; const simEnd = obj.simulationEndDate.value;
        if (simStart === '' || simEnd === '') { alert('Please add the start/end of HYD scenario.'); return; }
        const file = e.target.files[0]; if (!file) return;
        const formData = new FormData(); formData.append('file', file); 
        formData.append('projectName', currentProject);
        formData.append('simStart', simStart); formData.append('simEnd', simEnd);
        try {
            signalSender('showOverlay', 'Reading observation data. Please wait...');
            const response = await fetch('/obs_calibration_upload', { method: 'POST', body: formData });
            const data = await response.json(); signalSender('hideOverlay');
            if (data.status === 'error') { alert(data.message); return; }
            fillTable(data.content.data, obj.observationTable);
            obj.observationName.value = file.name;
            obj.observationStartDate.value = data.content['start'];
            obj.observationEndDate.value = data.content['end']; 
        } catch (error) { alert(`Uploading observation data failed: ${error.message}`); }
        finally { e.target.value = ''; signalSender('hideOverlay'); }
    });
    obj.extractStationBtn.addEventListener('click', async () => {
        currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        signalSender('showOverlay', 'Getting station data fron project "' + currentProject + '".\nPlease wait...');
        const content = { projectName: currentProject };
        const data = await jsonLoader('get_stations_calibration', content);
        signalSender('hideOverlay');
        if (data.status === "error") { alert(data.message); return; }
        // Add content to the selector
        const defaultValue = `<option value="">-- Select a station --</option>`;
        const options = data.content.map(s => `<option value="${s}">${s}</option>`).join(''); 
        obj.stationSelector.innerHTML = defaultValue + options;
    });
    obj.summaryBtn.addEventListener('click', async () => {
        currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        const simStart = obj.simulationStartDate.value; const simEnd = obj.simulationEndDate.value;
        if (simStart === '' || simEnd === '') { alert('Please add the start/end of HYD scenario.'); return; }
        const obsStart = obj.observationStartDate.value; const obsEnd = obj.observationEndDate.value;
        if (obsStart === '' || obsEnd === '') { alert('Please add the start/end of observation.'); return; }
        const station = obj.stationSelector.value.trim();
        if (station === '') { alert('Please select a station first.'); return; }
        const depthSelection = obj.depthSelection.value.trim();
        if (depthSelection === '') { alert('Please specify the depth selection in the tab "Settings".'); return; }
        const targetValue = obj.criteriaTarget.value;
        const weightValue = obj.weightSelector.value;
        const observationData = getDataFromTable(obj.observationTable, true).rows;
        if (observationData.length === 0) { alert('Please upload observation data first.'); return; }
        signalSender('showOverlay', 'Summarizing information from different iterations for station "' + station + '".\nPlease wait...');
        const content = { 
            projectName: currentProject, simStart: simStart, simEnd: simEnd,
            obsStart: obsStart, obsEnd: obsEnd, station: station, depthSelection: depthSelection,
            obsData: observationData, targetValue: targetValue, weightValue: weightValue
        };
        const data = await jsonLoader('summarize_calibration', content);
        signalSender('hideOverlay'); alert(data.message); 
        if (data.status === "error") { return; }
    });
    obj.correlationBtn.addEventListener('click', async () => {    
        currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        const content = { projectName: currentProject};
        const respond = await jsonLoader('correlation_calibration', content);
        if (respond.status === "error") { 
            obj.sensitivityObject.style.display = 'none';
            alert(respond.message); return; 
        }
        obj.sensitivityObject.style.display = 'block';
        await sensitivityRender(obj.sensitivityContainer, respond.content, respond.key);
    });
    obj.surrogateBtn.addEventListener('click', async () => {
        currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        const model = obj.surrogateSelector.value.trim();
        const key = 'surrogate_model', logFile = 'log.txt';
        if (isRunning) { alert("Optimization is currently running."); return; }
        obj.optimizationLogContainer.style.display = 'flex';
        obj.optimizationChartContainer.style.display = 'none';
        obj.optimizationLog.value = ''; 
        const content = { 
            projectName: currentProject, model: model, key: key
        };
        try {
            const start = await jsonLoader('start_optimization_calibration', content);
            if (start.status === "error") { 
                alert(start.message); isRunning = false; return; 
            }
            updateLogOptimization(currentProject, key, obj.optimizationLog, null, null, 1, logFile);
        } catch (error) { 
            alert(`Starting optimization failed: ${error.message}`); isRunning = false;
        }
    });
    obj.optimizationBtn.addEventListener('click', async () => {
        currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        const iterationNumber = parseInt(obj.optimizationIterations.value);
        if (isNaN(iterationNumber) || iterationNumber <= 0) { alert('Please specify the number of iterations.'); return; }
        const direction = obj.optimizationDirection.value;
        if (isRunning) { alert("Optimization is currently running."); return; }
        // Reset UI
        activeProject = currentProject; isRunning = true;
        obj.optimizationProgressText.innerText = 'Iteration is in progress. Please wait...'; 
        obj.optimizationProgressBarContainer.style.display = 'flex'; 
        obj.optimizationProgressBar.value = 0; 
        obj.optimizationLogContainer.style.display = 'flex';
        obj.optimizationChartContainer.style.display = 'none';
        obj.optimizationLog.value = ''; obj.optimizationResults.style.display = 'none';
        const key = 'optuna', logFile = 'log.txt';
        const content = { 
            projectName: currentProject, iterations: iterationNumber, 
            direction: direction, key: key
        };
        try {
            const start = await jsonLoader('start_optimization_optuna', content);
            if (start.status === "error") { 
                alert(start.message); isRunning = false; return; 
            }
            updateLogOptimization(
                currentProject, key, obj.optimizationLog, obj.optimizationProgressBar, 
                obj.optimizationProgressText, 1, logFile
            );
        } catch (error) { 
            obj.optimizationProgressText.innerText = 'Failed to start optimization.';
            obj.optimizationResults.style.display = 'none';
            alert(`Optimization is failed: ${error.message}`); isRunning = false;
        }
    });
    obj.optimizationPlotBtn.addEventListener('click', async () => {
        currentProject = obj.projectName.value.trim();
        if (currentProject === '') { alert('Please select a scenario first.'); return; }
        obj.optimizationLogContainer.style.display = 'none';
        obj.optimizationChartContainer.style.display = 'flex';
        try {
            const response = await jsonLoader('plot_optuna', { projectName: currentProject });
            if (response.status === "error") { 
                obj.optimizationLogContainer.style.display = 'none';
                obj.optimizationChartContainer.style.display = 'none';
                alert(response.message); return; 
            }
            plotOptuna(obj.optimizationChartContainer, response.content);
        } catch (error) { 
            obj.optimizationLogContainer.style.display = 'none';
            obj.optimizationChartContainer.style.display = 'none';
            alert(`Optimization is failed: ${error.message}`);
        }

    });
    obj.optimizationSaveBtn.addEventListener('click', async () => {
        
    });




}

function formatOptunaValue(value) {
    if (Math.abs(value) < 0.001) { return value.toExponential(4); }
    return value.toFixed(3);
}

function plotOptuna(container, trials) {
    if (!container || !Array.isArray(trials) || trials.length === 0) {
        container.innerHTML = '<p>No Optuna trial data available.</p>';
        return;
    }

    // ------------------------------------------------------------
    // Prepare data
    // ------------------------------------------------------------
    const validTrials = trials.filter(
        trial =>
            trial.value !== null &&
            trial.value !== undefined &&
            Number.isFinite(Number(trial.value))
    );

    if (validTrials.length === 0) {
        container.innerHTML = '<p>No valid trial results available.</p>';
        return;
    }

    const values = validTrials.map(trial => Number(trial.value));
    const trialNumbers = validTrials.map(
        (trial, index) => trial.number ?? index
    );

    const bestValue = Math.min(...values);

    // Parameter columns: params_Vicouv, params_Dicouv, ...
    const paramColumns = Object.keys(validTrials[0])
        .filter(key => key.startsWith('params_'));

    const paramNames = paramColumns.map(
        key => key.replace(/^params_/, '')
    );


    // ------------------------------------------------------------
    // Create chart containers
    // ------------------------------------------------------------
    container.innerHTML = `
        <div class="optuna-chart-grid">
            <div class="optuna-chart" id="optuna-convergence"></div>
            <div class="optuna-chart" id="optuna-distribution"></div>
            <div class="optuna-chart" id="optuna-importance"></div>
            <div class="optuna-chart" id="optuna-sensitivity"></div>
        </div>
    `;


    // ------------------------------------------------------------
    // 1. Convergence
    // ------------------------------------------------------------
    let currentBest = Infinity;

    const cumulativeBest = values.map(value => {
        currentBest = Math.min(currentBest, value);
        return currentBest;
    });

    Plotly.newPlot(
        'optuna-convergence',
        [
            {
                x: trialNumbers,
                y: cumulativeBest,
                type: 'scatter',
                mode: 'lines',
                name: 'Best RMSE so far',
                line: {
                    width: 2
                }
            }
        ],
        {
            title: {
                text: "Optuna's Convergence Process"
            },
            xaxis: {
                title: 'Iterations (Trials)'
            },
            yaxis: {
                title: 'Smallest RMSE (°C)'
            },
            margin: {
                l: 70,
                r: 30,
                t: 60,
                b: 60
            },
            hovermode: 'x unified'
        },
        {
            responsive: true,
            displaylogo: false
        }
    );


    // ------------------------------------------------------------
    // 2. RMSE Distribution
    // ------------------------------------------------------------
    Plotly.newPlot(
        'optuna-distribution',
        [
            {
                x: values,
                type: 'histogram',
                name: 'RMSE',
                nbinsx: 25,
                opacity: 0.75
            },
            {
                x: [bestValue, bestValue],
                y: [0, Math.max(1, values.length)],
                type: 'scatter',
                mode: 'lines',
                name: `Best: ${bestValue.toFixed(4)} °C`,
                line: {
                    dash: 'dash',
                    width: 2
                }
            }
        ],
        {
            title: {
                text: 'RMSE Distribution Across Trials'
            },
            xaxis: {
                title: 'RMSE (°C)'
            },
            yaxis: {
                title: 'Number of Trials'
            },
            margin: {
                l: 70,
                r: 30,
                t: 60,
                b: 60
            },
            bargap: 0.05
        },
        {
            responsive: true,
            displaylogo: false
        }
    );


    // ------------------------------------------------------------
    // 3. Parameter Importance
    //
    // Here we calculate importance in the frontend using
    // absolute correlation between parameter and RMSE.
    //
    // This is not exactly the same evaluator as:
    // optuna.importance.MeanDecreaseImpurityImportanceEvaluator
    // ------------------------------------------------------------
    const importance = {};

    for (const param of paramNames) {
        const column = `params_${param}`;

        const data = validTrials
            .map(trial => ({
                x: Number(trial[column]),
                y: Number(trial.value)
            }))
            .filter(
                item =>
                    Number.isFinite(item.x) &&
                    Number.isFinite(item.y)
            );

        if (data.length < 2) {
            importance[param] = 0;
            continue;
        }

        const x = data.map(item => item.x);
        const y = data.map(item => item.y);

        const meanX =
            x.reduce((sum, value) => sum + value, 0) / x.length;

        const meanY =
            y.reduce((sum, value) => sum + value, 0) / y.length;

        let numerator = 0;
        let denominatorX = 0;
        let denominatorY = 0;

        for (let i = 0; i < x.length; i++) {
            const dx = x[i] - meanX;
            const dy = y[i] - meanY;

            numerator += dx * dy;
            denominatorX += dx * dx;
            denominatorY += dy * dy;
        }

        const denominator =
            Math.sqrt(denominatorX * denominatorY);

        const correlation =
            denominator === 0 ? 0 : numerator / denominator;

        importance[param] = Math.abs(correlation);
    }


    // Sort from smallest -> largest
    const sortedImportance = Object.entries(importance)
        .sort((a, b) => a[1] - b[1]);

    const importanceNames = sortedImportance.map(
        item => item[0]
    );

    const importanceValues = sortedImportance.map(
        item => item[1]
    );


    Plotly.newPlot(
        'optuna-importance',
        [
            {
                x: importanceValues,
                y: importanceNames,
                type: 'bar',
                orientation: 'h',
                text: importanceValues.map(
                    value => `${(value * 100).toFixed(1)}%`
                ),
                textposition: 'outside',
                hovertemplate:
                    '%{y}<br>Importance: %{x:.3f}<extra></extra>'
            }
        ],
        {
            title: {
                text: 'Importance of Parameters'
            },
            xaxis: {
                title: 'Relative Importance',
                range: [
                    0,
                    Math.max(...importanceValues, 0.1) * 1.15
                ]
            },
            yaxis: {
                title: ''
            },
            margin: {
                l: 100,
                r: 60,
                t: 60,
                b: 60
            }
        },
        {
            responsive: true,
            displaylogo: false
        }
    );


    // ------------------------------------------------------------
    // 4. Sensitivity Analysis
    // ------------------------------------------------------------
    const mostImportantParam =
        importanceNames.length > 0
            ? importanceNames[importanceNames.length - 1]
            : null;

    if (!mostImportantParam) {
        document.getElementById('optuna-sensitivity').innerHTML =
            '<p>No parameter data available.</p>';
        return;
    }

    const sensitivityColumn =
        `params_${mostImportantParam}`;

    const sensitivityData = validTrials
        .map(trial => ({
            x: Number(trial[sensitivityColumn]),
            y: Number(trial.value),
            trial: trial.number
        }))
        .filter(
            item =>
                Number.isFinite(item.x) &&
                Number.isFinite(item.y)
        );

    const bestTrial = validTrials.reduce(
        (best, trial) =>
            Number(trial.value) < Number(best.value)
                ? trial
                : best,
        validTrials[0]
    );

    const bestParamValue =
        Number(bestTrial[sensitivityColumn]);


    Plotly.newPlot(
        'optuna-sensitivity',
        [
            {
                x: sensitivityData.map(item => item.x),
                y: sensitivityData.map(item => item.y),
                type: 'scatter',
                mode: 'markers',
                name: 'Trials',
                marker: {
                    size: 7,
                    opacity: 0.65
                },
                text: sensitivityData.map(
                    item => `Trial ${item.trial}`
                ),
                hovertemplate:
                    `${mostImportantParam}: %{x}<br>` +
                    `RMSE: %{y:.4f} °C<br>` +
                    `%{text}<extra></extra>`
            },
            {
                x: [bestParamValue, bestParamValue],
                y: [
                    Math.min(...values),
                    Math.max(...values)
                ],
                type: 'scatter',
                mode: 'lines',
                name: `Best: ${formatOptunaValue(bestParamValue)}`,
                line: {
                    dash: 'dash',
                    width: 2
                }
            }
        ],
        {
            title: {
                text: `Sensitivity Analysis: ${mostImportantParam}`
            },
            xaxis: {
                title: mostImportantParam
            },
            yaxis: {
                title: 'RMSE (°C)'
            },
            margin: {
                l: 70,
                r: 30,
                t: 60,
                b: 60
            },
            hovermode: 'closest'
        },
        {
            responsive: true,
            displaylogo: false
        }
    );


}



function updateLogOptimization(project, key, logObject, progressBarObject, progressTextObject, seconds, logFile) {
    activeProject = project; isRunning = true;
    // Prevent multiple polling intervals
    if (logInterval !== null) { clearInterval(logInterval); logInterval = null; }
    const pollStatus = async () => {
        if (activeProject !== project) { clearInterval(logInterval); logInterval = null; return; }
        try {
            const content = { projectName: project, key: key };
            const statusRes = await jsonLoader('check_optimization_status_calibration', content);
            if (progressTextObject !== null) { progressTextObject.innerText = statusRes.message; }
            if (progressBarObject !== null) { progressBarObject.value = statusRes.progress; }
            if (statusRes.status !== "running") {
                logObject.value += statusRes.message; isRunning = false;
                if (statusRes.best_params !== '') {
                    obj.optimizationResults.style.display = 'block';
                    // Update optimal parameter container
                    const bestParams = statusRes.best_params;
                    const container = document.querySelector('.parameter-optimal');
                    container.innerHTML = `
                        <div class="parameter-header-optimal">
                            <div>Parameter</div><div>Value</div>
                        </div>
                        ${Object.entries(bestParams).map(([key, value]) => {
                            const param = calibrationParams.find(p => p.value === key);
                            return `
                                <div class="parameter-row-optimal" data-param="${param.value}">
                                    <div>${param.name}</div>
                                    <div><input type="text" value="${bestParams[param.value]}"></div>
                                </div>
                            `;
                        }).join('')}
                    `;
                }
                if (logInterval) { clearInterval(logInterval); logInterval = null; }
            }
            const res = await fetch(`/calibration_log_tail/${project}?offset=${lastOffsetHYD}&log_file=${logFile}`);
            if (!res.ok) return;
            const data = await res.json();
            for (const line of data.lines) { logObject.value += line + "\n"; }
            lastOffsetHYD = data.offset;
        } catch (error) { 
            obj.optimizationResults.style.display = 'none';
            alert("Error: " + (error.message || error)); isRunning = false;
            clearInterval(logInterval); logInterval = null; 
            if (progressTextObject !== null) { 
                progressTextObject.innerText = "Error: " + (error.message || error); 
            }
        }
    }
    logInterval = setInterval(pollStatus, seconds * 1000); pollStatus(); 
}

function updateLogResampling(project, key, progressBarObject, progressTextObject, seconds){
    activeProject = project; isRunning = true;
    // Prevent multiple polling intervals
    if (logInterval !== null) { clearInterval(logInterval); logInterval = null; }
    const pollStatus = async () => {
        if (activeProject !== project) { clearInterval(logInterval); logInterval = null; return; }
        try {
            const content = { projectName: project, key: key };
            const statusRes = await jsonLoader('check_calibration', content);
            // Update progress
            if (typeof statusRes.progress === 'number') {
                progressBarObject.value = Math.max(0, Math.min(100, statusRes.progress));
            }
            // Update message
            if (statusRes.message) { progressTextObject.innerText = statusRes.message; }
            if (statusRes.status === "finished" || statusRes.status === "stopped") {
                progressBarObject.value = statusRes.progress; isRunning = false;
                progressTextObject.innerText = statusRes.message || 'Resampling completed.';
                clearInterval(logInterval); logInterval = null;
            }
            if (statusRes.status === "failed") {
                progressTextObject.innerText = statusRes.message || 'Resampling failed.';
                isRunning = false; clearInterval(logInterval); logInterval = null;
            }
            obj.calibrationLog.value = statusRes.his;
        } catch (error) { 
            alert("Polling error: " + (error.message || error)); isRunning = false;
            clearInterval(logInterval); logInterval = null; progressTextObject.innerText = 'Polling error.';
        }
    }
    pollStatus(); logInterval = setInterval(pollStatus, seconds * 1000);
}

function updateLogSimulation(hydProject, key, logObject, progressBarObject, progressTextObject, seconds, logFile){
    activeProject = hydProject;
    logInterval = setInterval(async () => {
        if (activeProject !== hydProject) { clearInterval(logInterval); logInterval = null; }
        try {
            const content = { projectName: hydProject, key: key };
            const statusRes = await jsonLoader('check_sim_status_calibration', content);
            progressTextObject.innerText = statusRes.message; progressBarObject.value = statusRes.progress;
            if (statusRes.status !== "running") {
                logObject.value += statusRes.message;
                if (logInterval) { clearInterval(logInterval); logInterval = null; }
            }
            const res = await fetch(`/calibration_log_tail/${hydProject}?offset=${lastOffsetHYD}&log_file=${logFile}`);
            if (!res.ok) return;
            const data = await res.json();
            for (const line of data.lines) { logObject.value += line + "\n"; }
            lastOffsetHYD = data.offset;
        } catch (error) { clearInterval(logInterval); logInterval = null; }
    }, seconds * 1000);
}

async function sensitivityRender(container, data, key) {
    if (!data || data.length === 0) { return; }
    const parameters = Object.keys(data[0]).filter(k => k !== key);
    const variables = [...parameters, key];
    const sensitivityColumns = 2, rowHeight = 300;
    const sensitivityRows = Math.ceil(parameters.length / sensitivityColumns);
    const traces = [], z = [], text = [];
    variables.forEach(v1 => {
        const row = [], textRow = [];
        variables.forEach(v2 => {
            const pairs = data
                .map(row => [Number(row[v1]), Number(row[v2])])
                .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
            const x = pairs.map(p => p[0]), y = pairs.map(p => p[1]);
            const corr = pearsonCorrelation(x, y);
            row.push(corr);
            textRow.push(Number.isFinite(corr) ? corr.toFixed(3) : "");
        });
        z.push(row); text.push(textRow);
    });
    // Reverse Y direction so first variable is at the top
    const zReversed = z.slice().reverse();
    const textReversed = text.slice().reverse();
    const yReversed = variables.slice().reverse();
    traces.push({
        type: "heatmap", z: zReversed, text: textReversed, texttemplate: "%{text}",
        x: variables, y: yReversed, xaxis: "x", yaxis: "y",
        zmin: -1, zmax: 1, colorscale: "RdBu", textfont: { size: 13 }, colorbar: { title: "Pearson" },
        hovertemplate: "%{x} vs %{y}<br>" + "r = %{z:.3f}" +  "<extra></extra>"
    });
    // Sensitivity plots
    parameters.forEach((parameter, index) => {
        const validData = data
            .map(row => ({ x: Number(row[parameter]), y: Number(row[key]) }))
            .filter(row => Number.isFinite(row.x) && Number.isFinite(row.y));
        if (validData.length === 0) { return; }
        const x = validData.map(d => d.x), y = validData.map(d => d.y);
        const row = Math.floor(index / 2), col = index % 2;
        const subplotIndex = row * 2 + col + 2;
        const xAxisName = subplotIndex === 1 ? "x" : `x${subplotIndex}`;
        const yAxisName = subplotIndex === 1 ? "y" : `y${subplotIndex}`;
        traces.push({
            type: "scatter", x: x, y: y, mode: "markers", xaxis: xAxisName,
            yaxis: yAxisName, marker: { size: 8, opacity: 0.7 }, 
            name: parameter, showlegend: false,
            hovertemplate: `${parameter}: %{x}<br>` + `${key}: %{y:.4f}` + `<extra></extra>`
        });
        if (validData.length >= 2) {
            const meanX = x.reduce((a, b) => a + b, 0) / x.length;
            const meanY = y.reduce((a, b) => a + b, 0) / y.length;
            let numerator = 0, denominator = 0;
            for (let i = 0; i < x.length; i++) {
                numerator += (x[i] - meanX) * (y[i] - meanY);
                denominator += (x[i] - meanX) ** 2;
            }
            if (denominator !== 0) {
                const slope = numerator / denominator;
                const intercept = meanY - slope * meanX;
                const minX = Math.min(...x), maxX = Math.max(...x);
                traces.push({
                    type: "scatter", x: [minX, maxX],
                    y: [slope * minX + intercept, slope * maxX + intercept],
                    mode: "lines", xaxis: xAxisName, yaxis: yAxisName,
                    line: { dash: "dash", width: 2 },
                    hoverinfo: "skip", showlegend: false
                });
            }
        }
    });
    const layout = {
        height: Math.max(500, sensitivityRows * rowHeight),
        margin: { l: 20, r: 30, t: 80, b: 60 },
        title: {
            text: "Correlation Analysis",
            font: { size: 24, weight: "bold" }
        },
        xaxis: {
            domain: [0.00, 0.28], tickangle: 0, 
            automargin: true, showgrid: false, fixedrange: true
        },
        yaxis: {
            domain: [0.20, 0.80], tickangle: -90,
            automargin: true, showgrid: false, fixedrange: true
        }, annotations: []
    };
    parameters.forEach((parameter, index) => {
        const validData = data
            .map(row => ({ x: Number(row[parameter]), y: Number(row[key])}))
            .filter(row => Number.isFinite(row.x) && Number.isFinite(row.y));
        if (validData.length === 0) { return; }
        const x = validData.map(d => d.x), y = validData.map(d => d.y);
        const r = pearsonCorrelation(x, y);
        const row = Math.floor(index / 2), col = index % 2;
        const subplotIndex = row * 2 + col + 2;
        const xAxisName = subplotIndex === 1 ? "xaxis" : `xaxis${subplotIndex}`;
        const yAxisName = subplotIndex === 1 ? "yaxis" : `yaxis${subplotIndex}`;
        const xDomain = col === 0 ? [0.34, 0.64] : [0.70, 1.00], gap = 0.21;
        const plotHeight = (1 - gap * (sensitivityRows - 1)) / sensitivityRows;
        const yTop = 1 - row * (plotHeight + gap), yBottom = yTop - plotHeight;
        layout[xAxisName] = {
            domain: xDomain,
            anchor: subplotIndex === 2 ? "y2" : `y${subplotIndex}`,
            title: {text: `<b>${parameter}</b>`, font: { size: 13 }, standoff: 0 },
            tickangle: 0, automargin: true, showgrid: true,
            zeroline: true, showline: true, ticks: "outside"
        };
        layout[yAxisName] = {
            domain: [ yBottom, yTop ],
            anchor: subplotIndex === 2 ? "x2" : `x${subplotIndex}`,
            title: {text: `<b>${key}</b>`, font: { size: 13 }, standoff: 0 },
            tickangle: -90, tickpadding: 0, ticklen: 3, 
            automargin: true, showgrid: true
        };
        const annotationX = col === 0 ? 0.495 : 0.85;
        layout.annotations.push({
            x: annotationX, y: yTop - 0.015, xref: "paper", yref: "paper",
            xanchor: "center", yanchor: "bottom",
            text:
                `<b>${parameter} vs ${key}</b><br>` +
                `<span style="font-size:12px">` +
                `Pearson r = ${r.toFixed(3)}</span>`,
            showarrow: false, font: { size: 15 }
        });
    });
    Plotly.newPlot(
        container, traces, layout, { responsive: true, displaylogo: false }
    );
}

function pearsonCorrelation(x, y) {
    if (x.length !== y.length || x.length < 2) { return NaN; }
    const meanX = x.reduce((a, b) => a + b, 0) / x.length;
    const meanY = y.reduce((a, b) => a + b, 0) / y.length;
    let numerator = 0, denominatorX = 0, denominatorY = 0;
    for (let i = 0; i < x.length; i++) {
        const dx = x[i] - meanX, dy = y[i] - meanY;
        numerator += dx * dy;
        denominatorX += dx * dx;
        denominatorY += dy * dy;
    }
    const denominator = Math.sqrt(denominatorX * denominatorY);
    if (denominator === 0) { return NaN; }
    return numerator/Math.sqrt(denominatorX * denominatorY);
}







