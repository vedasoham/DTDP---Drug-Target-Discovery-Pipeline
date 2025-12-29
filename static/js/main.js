// Bacterial Drug Target Pipeline - JavaScript v7.3 (FIXED PROJECT MODAL)
// =============================================================================
// FIXES: Always show modal on startup, no default project, proper modal behavior
// =============================================================================

// Global variables
let socket = null;
let activeJobs = [];
let systemInfo = null;
let uploadedFiles = [];
let filterConfigs = {};
let currentProject = null;  // MUST start as null
let isDarkMode = false;
let myResultsChart = null;
let isAutoLoadingProject = false; // FIX: Flag to prevent race conditions on tab switch
let selectedLiteratureSequences = []; // For the new literature feature
let jobUpdateHandlers = {}; // For handling specific job updates, like in-modal progress

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    loadDarkModePreference();
    applyDarkMode();
    checkProject();  // This will ALWAYS show modal on startup
    initializeWebSocket();
    loadSystemInfo();
    setupEventListeners();
    setupFileUpload();
    handleHashNavigation();
    setupCardClickHandlers();
    // Don't load configs until project selected
    setupRunAllButton();
    
    // Periodically load jobs to update statuses
    setInterval(() => {
        if (currentProject) {
            loadJobs();
        }
    }, 5000);
});

// =============================================================================
// FIX: Add resetProjectDisplay function
// =============================================================================
function resetProjectDisplay() {
    // Reset global state variables
    activeJobs = [];
    uploadedFiles = []; // <-- Add this line to clear the file array
    
    // Clear the "Active Jobs" section
    updateActiveJobsDisplay();
    
    // Manually reset the pipeline flow diagram counts
    const flowInputCount = document.getElementById('flowInputCount');
    if (flowInputCount) flowInputCount.textContent = '-';
    const flowHumanCount = document.getElementById('flowHumanCount');
    if (flowHumanCount) flowHumanCount.textContent = '-';
    const flowDegCount = document.getElementById('flowDegCount');
    if (flowDegCount) flowDegCount.textContent = '-';
    const flowVfdbCount = document.getElementById('flowVfdbCount');
    if (flowVfdbCount) flowVfdbCount.textContent = '-';
    const flowEskapeCount = document.getElementById('flowEskapeCount');
    if (flowEskapeCount) flowEskapeCount.textContent = '-';
    // Reset filter card statuses
    updateFilterStatuses();
    const databases = ['human', 'deg', 'vfdb', 'eskape'];
    databases.forEach(db => {
        updateFilterStatus(db, 'not-started');
    });
    
    // Clear the "Uploaded Files" list
    const uploadedFilesDiv = document.getElementById('uploadedFiles');
    if (uploadedFilesDiv) {
        uploadedFilesDiv.innerHTML = '';
    }
    
    // Hide and reset the "Input Statistics" box
    const inputStats = document.getElementById('inputStats');
    if (inputStats) {
        inputStats.style.display = 'none';
        document.getElementById('statTotalFiles').textContent = '0';
        document.getElementById('statTotalSeqs').textContent = '0';
        document.getElementById('statTotalSize').textContent = '0 MB';
    }
    
    // Reset input tab text
    const inputTab = document.querySelector('.sub-tab-btn[data-section="input"]');
    if (inputTab) {
        inputTab.innerHTML = '📁 Input';
    }

    // --- NEW: Reset navigation tabs to disabled state ---
    const mutationTab = document.querySelector('.tab-link[data-tab="mutation"]');
    const structureTab = document.querySelector('.tab-link[data-tab="structure"]');
    if (mutationTab) mutationTab.classList.add('disabled');
    if (structureTab) structureTab.classList.add('disabled');
    console.log('Project display reset for:', currentProject);
}

// =============================================================================
// DARK MODE
// =============================================================================

function loadDarkModePreference() {
    const saved = localStorage.getItem('darkMode');
    isDarkMode = saved === 'true';
}

function toggleDarkMode() {
    isDarkMode = !isDarkMode;
    localStorage.setItem('darkMode', isDarkMode);
    applyDarkMode();
    showNotification(isDarkMode ? 'Dark mode enabled' : 'Light mode enabled', 'info');
}

function applyDarkMode() {
    if (isDarkMode) {
        document.body.classList.add('dark-mode');
    } else {
        document.body.classList.remove('dark-mode');
    }
}

// =============================================================================
// PROJECT MANAGEMENT - FIXED: Always show modal on startup
// =============================================================================

async function checkProject() {
    // If a project has NOT been selected in this browser session, show the modal.
    // We use sessionStorage to persist this across page loads in the same tab.
    if (sessionStorage.getItem('projectSelected') !== 'true') {
        showProjectModal(true);
        return;
    }

    // If a project has been selected, try to load its data from the server.
    try {
        const response = await fetch('/api/current_project');
        const data = await response.json();
        if (data.project) {
            currentProject = data.project;
            showCurrentProject(currentProject);
            loadProjectInfo(currentProject);
            loadProjectFiles(currentProject);
            loadSavedConfigs();
            await loadJobs();
        } else {
            // Server has no project, but client thinks it does. Show modal.
            showProjectModal(true);
        }
    } catch (error) {
        console.error('Error checking project:', error);
        showProjectModal(true);
    }
}

function showCurrentProject(project) {
    const currentProjectDiv = document.getElementById('currentProject');
    const projectName = document.getElementById('projectName');
    
    // Hide the "no project" message
    const noProjectDiv = document.getElementById('noProject');
    if (noProjectDiv) {
        noProjectDiv.style.display = 'none';
    }

    if (currentProjectDiv && projectName) {
        projectName.textContent = project.name || project;
        currentProjectDiv.style.display = 'flex';

        // Also hide the 'no project' message
        const noProjectDiv = document.getElementById('noProject');
        if (noProjectDiv) {
            noProjectDiv.style.display = 'none';
        }
    }
}

async function showProjectModal(force = false) {
    // FIX: Always allow modal to show when forced
    // Remove the check that was blocking it
    
    // Ensure the UI is in a "no project" state
    sessionStorage.removeItem('projectSelected'); // Invalidate session selection
    currentProject = null;
    const currentProjectDiv = document.getElementById('currentProject');
    if (currentProjectDiv) currentProjectDiv.style.display = 'none';
    const noProjectDiv = document.getElementById('noProject');
    if (noProjectDiv) noProjectDiv.style.display = 'block';


    const modal = document.getElementById('projectModal');
    modal.style.display = 'block';
    
    // Prevent closing by clicking outside - user MUST select a project
    modal.onclick = function(event) {
        if (event.target === modal) {
            // Don't close on outside click
            event.stopPropagation();
            showNotification('Please select or create a project to continue', 'warning');
        }
    };
    
    try {
        const response = await fetch('/api/projects');
        const data = await response.json();
        
        const projectsList = document.getElementById('projectsList');
        
        if (data.projects && data.projects.length > 0) {
            projectsList.innerHTML = data.projects.map(proj => `
                <div class="project-item ${currentProject && currentProject.name === proj.name ? 'selected' : ''}" 
                     onclick="selectProject('${proj.name}')">
                    <div class="project-item-header">
                        <h4>${proj.name}</h4>
                        ${currentProject && currentProject.name === proj.name ? '<span class="badge-current">Current</span>' : ''}
                    </div>
                    ${proj.description ? `<p>${proj.description}</p>` : ''}
                    <div class="project-meta">
                        <span>📅 ${new Date(proj.created_at).toLocaleDateString()}</span>
                    </div>
                </div>
            `).join('');
        } else {
            projectsList.innerHTML = '<p class="text-muted">No existing projects. Create one to get started!</p>';
        }
    } catch (error) {
        console.error('Error loading projects:', error);
        document.getElementById('projectsList').innerHTML = 
            '<p class="text-muted">Error loading projects</p>';
    }
    
    const form = document.getElementById('newProjectForm');
    form.onsubmit = async (e) => {
        e.preventDefault();
        await createNewProject();
    };
}

async function selectProject(projectName) {
    try {
        const response = await fetch('/api/set_project', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ project: projectName })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentProject = projectName;
            sessionStorage.setItem('projectSelected', 'true'); // Set the flag for this session
            showCurrentProject(projectName);
            document.getElementById('projectModal').style.display = 'none';
            
            resetProjectDisplay();
            
            await loadProjectInfo(projectName);
            await loadProjectFiles(projectName);
            loadSavedConfigs();
            
            showNotification('Project loaded: ' + projectName, 'success');
            await loadJobs();  // ADD AWAIT HERE
        } else {
            isAutoLoadingProject = false; // Ensure flag is reset on failure
            // ADD THIS ELSE CLAUSE
            showNotification(data.message || 'Failed to load project', 'error');
        }
    } catch (error) {
        console.error('Error selecting project:', error);
        showNotification('Error loading project', 'error');
    }
    isAutoLoadingProject = false; // Reset flag after operation
}

async function createNewProject() {
    const projectName = document.getElementById('projectNameInput').value.trim();
    const description = document.getElementById('projectDescription').value.trim();
    
    if (!projectName) {
        showNotification('Please enter a project name', 'warning');
        return;
    }
    
    try {
        const response = await fetch('/api/create_project', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: projectName,
                description: description
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentProject = projectName;
            sessionStorage.setItem('projectSelected', 'true'); // Set the flag for this session
            showCurrentProject(projectName);
            document.getElementById('projectModal').style.display = 'none';
            
            // Reset displays for new project
            resetProjectDisplay();
            
            showNotification('Project created: ' + projectName, 'success');
            await loadJobs();
            await loadProjectInfo(projectName); // <-- ADD THIS
            await loadProjectFiles(projectName); // <-- ADD THIS
        } else {
            showNotification('Error: ' + data.message, 'error');
        }
    } catch (error) {
        console.error('Error creating project:', error);
        showNotification('Error creating project', 'error');
    }
}

function openNewProject() {
    // Focus on the new project form
    showProjectModal(true);
    // Scroll to new project form
    setTimeout(() => {
        const newProjectInput = document.getElementById('projectNameInput');
        if (newProjectInput) {
            newProjectInput.focus();
        }
    }, 100);
}

function changeProject() {
    // Show modal to change project
    showProjectModal(true);
}

// =============================================================================
// FIX: Add loadProjectFiles and displayProjectFiles functions
// =============================================================================

async function loadProjectFiles(project) {
    if (!project) return;
    
    try {
        const response = await fetch(`/api/project_files/${project}`);
        const data = await response.json();
        
        if (data.success) {
            displayProjectFiles(data.files);
            
            // Update input file count in sub-tab (always update, even if 0)
            const inputTab = document.querySelector('.sub-tab-btn[data-section="input"]');
            if (inputTab) {
                if (data.count > 0) {
                    inputTab.innerHTML = `📁 Input Files (${data.count})`;
                } else {
                    inputTab.innerHTML = '📁 Input Files';
                }
            }
        }
    } catch (error) {
        console.error('Error loading project files:', error);
    }
}

function displayProjectFiles(files) {
    const uploadedFilesDiv = document.getElementById('uploadedFiles');
    if (!uploadedFilesDiv) return;
    
    if (files.length === 0) {
        return;
    }
    
    uploadedFilesDiv.innerHTML = files.map(file => `
        <div class="file-item">
            <div class="file-info">
                <span class="file-icon">📄</span>
                <div>
                    <strong>${file.name}</strong>
                    <br>
                    <small class="text-muted">
                        ${formatFileSize(file.size)} • 
                        ${file.sequences} sequences • 
                        ${file.modified}
                    </small>
                </div>
            </div>
            <span class="file-status" style="color: var(--success-color);">✓ Uploaded</span>
        </div>
    `).join('');
    
    // Update stats
    const totalSeqs = files.reduce((sum, f) => sum + f.sequences, 0);
    const totalSize = files.reduce((sum, f) => sum + f.size, 0);
    
    const statsBox = document.getElementById('inputStats');
    if (statsBox) {
        statsBox.style.display = 'block';
        document.getElementById('statTotalFiles').textContent = files.length;
        document.getElementById('statTotalSeqs').textContent = totalSeqs.toLocaleString();
        document.getElementById('statTotalSize').textContent = formatFileSize(totalSize);
        
        // Update flow input count
        const flowInputCount = document.getElementById('flowInputCount');
        if (flowInputCount) {
            flowInputCount.textContent = totalSeqs.toLocaleString();
        }
    }
}

// =============================================================================
// CONFIG PERSISTENCE - SAVE PER PROJECT
// =============================================================================

async function saveConfig(database, config) {
    if (!currentProject) return;

    try {
        const response = await fetch('/api/save_config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                database: database,
                config: config
            })
        });
        const result = await response.json();
        if (result.success) {
            filterConfigs[database] = config; // Update in-memory cache
            console.log(`Saved config for ${database} in ${currentProject} to server.`);
            return true;
        } else {
            throw new Error(result.message);
        }
    } catch (error) {
        console.error(`Error saving config for ${database}:`, error);
        showNotification(`Failed to save config for ${database}: ${error.message}`, 'error');
        return false;
    }
}

async function loadSavedConfigs() {
    if (!currentProject) return;

    try {
        const response = await fetch('/api/load_configs');
        const data = await response.json();

        if (data.success) {
            filterConfigs = data.configs || {};
            console.log('Loaded all configs from server:', filterConfigs);
            // After loading, update the UI to reflect the loaded configs
            updateFilterButtonsFromConfigs();
        } else {
            throw new Error(data.message);
        }
    } catch (error) {
        console.error('Error loading configs from server:', error);
        showNotification('Could not load saved configurations from the server.', 'error');
    }
}

function updateFilterButtonsFromConfigs() {
    const databases = ['human', 'deg', 'vfdb', 'eskape'];
    databases.forEach(db => {
        if (filterConfigs[db]) {
            const runBtn = document.getElementById(`runBtn${db.charAt(0).toUpperCase() + db.slice(1)}`);
            if (runBtn) {
                runBtn.disabled = false;
            }
        }
    });
}

function clearProjectConfigs() {
    if (!currentProject) return;
    
    const databases = ['human', 'deg', 'vfdb', 'eskape'];
    // This function is now a no-op on the frontend, as configs are server-side.
    // We can leave it to clear the in-memory cache if needed.
    filterConfigs = {};
    // We could add a backend call here to delete the config file if desired.
    // For now, we'll just clear the local state.
    updateFilterButtonsFromConfigs(); // Disable all run buttons
    showNotification('Configurations cleared for this project', 'info');
}

// =============================================================================
// PROJECT INFO LOADING
// =============================================================================

async function loadProjectInfo(projectName) {
    // Set the flag to indicate we are in an auto-load sequence
    isAutoLoadingProject = true;

    try {
        const response = await fetch(`/api/project_info/${projectName}`);
        const data = await response.json();
        
        if (data.success) {
            // Update the main input count in the flow diagram
            if (data.has_input && data.input_sequences > 0) {
                const flowInputCount = document.getElementById('flowInputCount');
                if (flowInputCount) {
                    flowInputCount.textContent = data.input_sequences.toLocaleString();
                }
            }

            // Update counts for each step in the flow diagram
            // This is now the primary way flow counts are updated.
            if (data.step_outputs) {
                for (const [db, count] of Object.entries(data.step_outputs)) {
                    const dbCapitalized = db.charAt(0).toUpperCase() + db.slice(1);
                    const countElement = document.getElementById(`flow${dbCapitalized}Count`);
                    if (countElement) {
                        countElement.textContent = count.toLocaleString();
                    }
                }
            }

            // The logic for the mutation tab has been moved to mutational_analysis.html
            // and its corresponding JS file. We just need to ensure the link is enabled if
            // a selection has been made.
            // This can be simplified or handled on the new page.
        }

    } catch (error) {
        console.error('Error loading project info:', error);
    } finally {
        // Always reset the flag after the function completes
        isAutoLoadingProject = false;
    }
}

// =============================================================================
// SETTINGS PANEL
// =============================================================================

function toggleSettingsPanel() {
    const panel = document.getElementById('settingsPanel');
    if (!panel) {
        createSettingsPanel();
    } else {
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
}

function createSettingsPanel() {
    const panel = document.createElement('div');
    panel.id = 'settingsPanel';
    panel.className = 'settings-panel';
    panel.innerHTML = `
        <div class="settings-content">
            <div class="settings-header">
                <h3>⚙️ Settings</h3>
                <button onclick="closeSettingsPanel()" class="close-settings">×</button>
            </div>
            
            <div class="settings-section">
                <h4>🖥️ System Information</h4>
                <div class="settings-grid">
                    <div class="setting-item">
                        <span class="setting-label">CPU Threads:</span>
                        <span class="setting-value" id="settingCpuCount">Loading...</span>
                    </div>
                    <div class="setting-item">
                        <span class="setting-label">GPU Available:</span>
                        <span class="setting-value" id="settingGpuInfo">Checking...</span>
                    </div>
                    <div class="setting-item">
                        <span class="setting-label">Memory:</span>
                        <span class="setting-value" id="settingMemory">-</span>
                    </div>
                </div>
            </div>
            
            <div class="settings-section">
                <h4>🎨 Appearance</h4>
                <div class="setting-item">
                    <label class="setting-toggle">
                        <span>Dark Mode</span>
                        <input type="checkbox" id="darkModeToggle" 
                               ${isDarkMode ? 'checked' : ''} 
                               onchange="toggleDarkMode()">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            
            <div class="settings-section">
                <h4>📚 Instructions</h4>
                <div class="instructions-text">
                    <p><strong>1. Upload Sequences:</strong> Add your FASTA files (.faa, .fasta, .fa)</p>
                    <p><strong>2. Configure Filters:</strong> Set thresholds for each database</p>
                    <p><strong>3. Run Pipeline:</strong> Execute filters sequentially</p>
                    <p><strong>4. View Results:</strong> Download filtered sequences</p>
                </div>
            </div>
            
            <div class="settings-section">
                <h4>🔧 Actions</h4>
                <button onclick="clearProjectConfigs()" class="btn btn-secondary">
                    Clear Saved Configurations
                </button>
            </div>
        </div>
    `;
    
    document.body.appendChild(panel);
    
    // Load system info
    if (systemInfo) {
        document.getElementById('settingCpuCount').textContent = systemInfo.cpu_count || '-';
    }
    
    // Check GPU (placeholder - would need backend support)
    document.getElementById('settingGpuInfo').textContent = 'Not Available';
}

function closeSettingsPanel() {
    const panel = document.getElementById('settingsPanel');
    if (panel) {
        panel.style.display = 'none';
    }
}

// =============================================================================
// RUN ALL & RESUME FUNCTIONALITY
// =============================================================================

function setupRunAllButton() {
    // Will be created in HTML, but setup logic here
    updateRunAllButton();
}

async function updateRunAllButton() {
    const runAllBtn = document.getElementById('runAllBtn');
    if (!runAllBtn) return;
    
    // Find the most recent "Full Pipeline" job for this project
    const fullRuns = activeJobs.filter(j => 
        j.type === 'Full Pipeline' && 
        j.project === currentProject
    );
    let mostRecentRun = null;
    if (fullRuns.length > 0) {
         fullRuns.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
         mostRecentRun = fullRuns[0];
    }

    if (mostRecentRun) {
        if (mostRecentRun.status === 'running' || mostRecentRun.status === 'queued') {
            runAllBtn.innerHTML = '🔄 Pipeline Running...';
            runAllBtn.disabled = true;
            runAllBtn.onclick = null;
        } else if (mostRecentRun.status === 'completed') {
            runAllBtn.innerHTML = '✅ All Steps Complete';
            runAllBtn.disabled = true; // Or set to re-run
            runAllBtn.onclick = null; // Or set to runAllSteps
        } else {
            // Job failed or was stopped
            runAllBtn.innerHTML = '▶️ Resume Pipeline'; // <-- UX IMPROVEMENT
            runAllBtn.disabled = false;
            runAllBtn.onclick = runAllSteps;
        }
    } else {
        // No "Full Pipeline" job has ever been run for this project
        runAllBtn.innerHTML = '▶️ Run All Steps';
        runAllBtn.disabled = false;
        runAllBtn.onclick = runAllSteps;
    }
}

// MODIFIED: This function now calls the server-side pipeline
async function runAllSteps() {
    const databases = ['human', 'deg', 'vfdb', 'eskape'];
    
    // 1. Check if all configs are set
    const missingConfigs = databases.filter(db => !filterConfigs[db]);
    if (missingConfigs.length > 0) {
        showNotification(
            `Please configure: ${missingConfigs.map(d => d.toUpperCase()).join(', ')}`,
            'warning'
        );
        return;
    }

    // 2. Package all configs into one object
    const allConfigs = {
        'human': filterConfigs['human'],
        'deg': filterConfigs['deg'],
        'vfdb': filterConfigs['vfdb'],
        'eskape': filterConfigs['eskape']
    };

    showNotification('Starting full pipeline...', 'info');

    // 3. Call the new server endpoint
    try {
        const response = await fetch('/api/start_full_pipeline', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ configs: allConfigs })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Full pipeline job created!', 'success');
            // 4. Redirect to the monitor page for the "master" job
            window.location.href = `/monitor/${result.job_id}`;
        } else {
            showNotification('Error starting pipeline: ' + result.message, 'error');
        }
    } catch (error) {
        console.error('Error starting full pipeline:', error);
        showNotification('A critical error occurred. Please check the console.', 'error');
}
}

function waitForJobCompletion(database) {
    return new Promise((resolve) => {
        const checkInterval = setInterval(() => {
            // MODIFICATION: Find all jobs for this type/project
            const dbJobs = activeJobs.filter(j => j.type === database && j.project === currentProject);

            // MODIFICATION: Sort to find the most recent
            dbJobs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
            const job = dbJobs.length > 0 ? dbJobs[0] : null;

            // Check the status of the *most recent* job
            if (job && (job.status === 'completed' || job.status === 'failed')) {
                clearInterval(checkInterval);
                resolve(job.status); // MODIFICATION: Resolve with the final status
            }
        }, 1000); // Check every second
    });
}

// =============================================================================
// CARD CLICK HANDLERS
// =============================================================================

function setupCardClickHandlers() {
    document.querySelectorAll('.filter-card').forEach(card => {
        card.addEventListener('click', function(e) {
            if (e.target.closest('button')) {
                return;
            }
            
            const database = this.dataset.database;
            const jobId = this.dataset.jobId;
            
            if (jobId) {
                window.location.href = `/monitor/${jobId}`;
            }
        });
        
        card.style.cursor = 'pointer';
    });
}

// =============================================================================
// HASH NAVIGATION
// =============================================================================

function handleHashNavigation() {
    const hash = window.location.hash;
    
    if (hash === '#filters') {
        switchSubSection('filters');
    } else if (hash === '#results') {
        switchSubSection('results');
        loadResults();
    } else if (hash === '#input') {
        switchSubSection('input');
    }
}

window.addEventListener('hashchange', handleHashNavigation);

// =============================================================================
// TAB MANAGEMENT
// =============================================================================

function setupEventListeners() {
    document.querySelectorAll('.tab-link').forEach(link => {
        link.addEventListener('click', function(e) {
            // If the link has a real URL (not just '#'), let the browser navigate.
            // This allows moving from mutational_analysis.html back to index.html.
            const href = this.getAttribute('href');
            if (href && href !== '#') {
                return; // Do not prevent default, allow navigation.
            }
            e.preventDefault(); // Otherwise, prevent default and switch tab via JS.
            if (!this.classList.contains('disabled')) { 
                switchMainTab(this.dataset.tab);
            }
        });
    });
    
    document.querySelectorAll('.sub-tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            switchSubSection(this.dataset.section);
        });
    });
    
    const showTableBtn = document.getElementById('showTableBtn');
    if (showTableBtn) {
        showTableBtn.addEventListener('click', () => switchResultsView('table'));
    }

    const showGraphBtn = document.getElementById('showGraphBtn');
    if (showGraphBtn) {
        showGraphBtn.addEventListener('click', () => switchResultsView('graph'));
    }

    // Set up close buttons for modals
    const configModalClose = document.querySelector('#configModal .close');
    if (configModalClose) {
        configModalClose.onclick = closeModal;
    }
    
    const fileReaderModalClose = document.querySelector('#fileReaderModal .close');
    if (fileReaderModalClose) { // This is correct
        fileReaderModalClose.onclick = closeFileReaderModal;
    }

    window.onclick = function(event) {
        const configModal = document.getElementById('configModal');
        const fileReaderModal = document.getElementById('fileReaderModal');
        const selectionModal = document.getElementById('selection-modal');
        
        // Close config modal when clicking outside
        if (event.target == configModal) {
            closeModal();
        }
        
        // Close file reader modal when clicking outside
        if (event.target == fileReaderModal) {
            closeFileReaderModal();
        }

        // Close selection modal when clicking outside
        if (event.target == selectionModal) {
            closeSelectionModal();
        }
    };

    // Event listener for the selection button in the results table
    const resultsTableBody = document.getElementById('resultsTableBody');
    if (resultsTableBody) {
        resultsTableBody.addEventListener('click', function(e) {
            const selectionBtn = e.target.closest('.selection-btn');
            if (selectionBtn) {
                openLiteratureModal(selectionBtn.dataset.database);
            }
        });
    }

    // Event listener for the "Select All" checkbox in the literature modal
    const literatureSelectAll = document.getElementById('literatureSelectAll');
    if (literatureSelectAll) {
        literatureSelectAll.addEventListener('change', function() {
            const checkboxes = document.querySelectorAll('#literatureSequenceList .literature-checkbox');
            checkboxes.forEach(checkbox => {
                checkbox.checked = this.checked;
            });
            updateLiteratureSelectionCount();
        });
    }

    // Event listener for individual checkboxes in the literature modal
    const literatureSequenceList = document.getElementById('literatureSequenceList');
    if (literatureSequenceList) {
        literatureSequenceList.addEventListener('change', function(e) {
            if (e.target.classList.contains('literature-checkbox')) {
                updateLiteratureSelectionCount();
            }
        });
    }

    // Add listener for Escape key to close modals
    window.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const literatureModal = document.getElementById('literatureModal');
            if (literatureModal && literatureModal.style.display === 'block') {
                closeLiteratureModal();
            }
            const downloadModal = document.getElementById('downloadOptionsModal');
            if (downloadModal && downloadModal.style.display === 'block') {
                closeDownloadOptionsModal();
            }
        }
    });

    // Event listeners for the new download options modal
    document.getElementById('downloadSelectedBtn')?.addEventListener('click', () => {
        handleDownloadRequest('selected');
    });
    document.getElementById('downloadAllBtn')?.addEventListener('click', () => {
        handleDownloadRequest('all');
    });
    document.getElementById('downloadAllVariants')?.addEventListener('change', function() {
        const fileSourceContainer = document.getElementById('downloadFileSourceContainer');
        if (this.checked) {
            fileSourceContainer.style.display = 'none';
        } else {
            fileSourceContainer.style.display = 'block';
        }
    });
    document.querySelector('#downloadOptionsModal .close')?.addEventListener('click', () => {
        closeDownloadOptionsModal();
    });
    
        // --- NEW: Generic modal close button handler ---
    // Find all elements with the class 'close' that are children of a 'modal'
    document.querySelectorAll('.modal .close').forEach(closeBtn => {
        closeBtn.addEventListener('click', () => {
            const modal = closeBtn.closest('.modal');
            if (modal) {
                // We find the specific close function if it exists (e.g., closeStructureViewerModal)
                // or just hide the modal as a fallback.
                const closeFnName = `close${modal.id.replace('Modal', '')}Modal`;
                if (typeof window[closeFnName] === 'function') {
                    windowcloseFnName;
                } else {
                    modal.style.display = 'none';
                }
            }
        });
    });

    // Event listener for the "Select All" checkbox in the validation table
    const validationSelectAll = document.getElementById('validationSelectAll');
    if (validationSelectAll) {
        // This seems to be for a different validation table, but we'll leave it.
        validationSelectAll.addEventListener('change', function() {
            const checkboxes = document.querySelectorAll('#validationTableBody .validation-checkbox');
            checkboxes.forEach(checkbox => {
                checkbox.checked = this.checked;
            });
        });
    }

    // --- NEW: Event listener for our new "Validate Files" button ---
    const validateFilesBtn = document.getElementById('validateFilesBtn');
    if (validateFilesBtn) {
        validateFilesBtn.addEventListener('click', validateInputFiles);
    }
}

function switchMainTab(tabName) {
    document.querySelectorAll('.tab-link').forEach(link => {
        link.classList.remove('active');
    });
    document.querySelector(`.tab-link[data-tab="${tabName}"]`).classList.add('active');
    
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(`${tabName}-content`)?.classList.add('active');
}

function switchSubSection(sectionName) {
    document.querySelectorAll('.sub-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelector(`.sub-tab-btn[data-section="${sectionName}"]`).classList.add('active');
    
    document.querySelectorAll('.sub-section').forEach(section => {
        // Guard against null if a section doesn't exist
        if (!section) {
            return;
        }
        section.classList.remove('active');
    });
    document.getElementById(`${sectionName}-section`).classList.add('active');
    
    if (sectionName === 'results') {
        loadResults();
    }
    
    window.location.hash = sectionName;
}

/**
 * Toggles between Table and Graph view on the Results tab.
 */
function switchResultsView(viewName) {
    // Get the containers
    const tableView = document.getElementById('tableView');
    const chartView = document.getElementById('chartView');
    
    // Get the buttons
    const tableBtn = document.getElementById('showTableBtn');
    const graphBtn = document.getElementById('showGraphBtn');

    if (viewName === 'graph') {
        // Show Graph
        tableView.style.display = 'none';
        chartView.style.display = 'block';
        
        // Update button styles
        tableBtn.classList.remove('active');
        graphBtn.classList.add('active');
    } else {
        // Show Table (default)
        tableView.style.display = 'block';
        chartView.style.display = 'none';
        
        // Update button styles
        tableBtn.classList.add('active');
        graphBtn.classList.remove('active');
    }
}

function proceedToFilters() {
    switchSubSection('filters');
    showNotification('Ready to configure and run filters!', 'info');
}

// =============================================================================
// NEW: FILE VALIDATION
// =============================================================================

async function validateInputFiles() {
    if (uploadedFiles.length === 0) {
        showNotification('Please add files to validate first', 'warning');
        return;
    }

    if (!currentProject) {
        showNotification('Please select a project first', 'warning');
        return;
    }

    const formData = new FormData();
    uploadedFiles.forEach(file => {
        formData.append('files', file);
    });

    const validateBtn = document.getElementById('validateFilesBtn');
    validateBtn.disabled = true;
    validateBtn.innerHTML = '<span class="spinner"></span> Validating...';

    try {
        const response = await fetch('/api/validate_input_files', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        if (data.success) {
            window.currentValidationSessionId = data.validation_session_id; // Store session ID
            displayValidationResults(data.results);
        } else {
            showNotification('Validation failed: ' + data.message, 'error');
        }
    } catch (error) {
        showNotification('An error occurred during validation.', 'error');
        console.error('Validation error:', error);
    } finally {
        validateBtn.disabled = false;
        validateBtn.innerHTML = 'Validate Files';
    }
}

function displayValidationResults(results) {
    const fixDescriptions = {
        'duplicate_ids': { label: 'Fix Duplicate IDs', description: 'Appends a unique suffix (e.g., _2) to repeated sequence identifiers.' },
        'illegal_chars_header': { label: 'Sanitize Headers', description: 'Replaces special characters (e.g., {}, [], /) with valid substitutes.' },
        'windows_endings': { label: 'Convert Line Endings', description: 'Converts Windows (CRLF) to Unix (LF) format for compatibility.' },
        'internal_stop_codon': { label: 'Remove Internal Stop Codons', description: 'Deletes entire sequences that contain a premature stop codon (*).' },
        'terminal_stop_codon': { label: 'Trim Terminal Stop Codons', description: 'Removes the trailing asterisk (*) from the end of sequences.' },
        'non_standard_aas': { label: 'Fix Non-Standard AAs', description: 'Replaces any character not in the 21 standard amino acids (including X) with "X".' },
        'lowercase_sequences': { label: 'Convert to Uppercase', description: 'Changes all amino acids in sequences to uppercase.' },
        'zero_length': { label: 'Remove Empty Sequences', description: 'Deletes headers that are not followed by any sequence data.' },
        'short_sequence': { label: 'Remove Short Sequences', description: 'Removes sequences with fewer than 20 amino acids.' },
        'multiline_wrapping': { label: 'Unwrap Sequences', description: 'Joins multi-line sequences into a single line per header.' },
        'empty_lines': { label: 'Remove Empty Lines', description: 'Removes blank lines found within the file.' },
        'no_header_for_sequence': { label: 'Sequence Before Header', description: 'Sequence data was found before the first ">" header line.' }
    };

    const modal = document.getElementById('validationResultModal');
    const container = document.getElementById('validationResultsContainer');
    container.innerHTML = ''; // Clear previous results

    results.forEach(fileResult => {
        const { filename, analysis } = fileResult;
        const fileId = filename.replace(/[^a-zA-Z0-9]/g, '_');

        // Combine errors and warnings for easier iteration
        const allIssueTypes = { ...analysis.errors, ...analysis.warnings };

        const hasIssues = Object.keys(allIssueTypes).length > 0;
        let issuesHtml = '';
        if (hasIssues) {
            // FIX: Use .map() to build the HTML string, instead of a for-loop with an incorrect `return`.
            // The `return` was causing the loop to exit after the first issue type,
            // and the result was not being assigned to `issuesHtml`.
            issuesHtml = Object.entries(allIssueTypes).map(([issueType, occurrences]) => {
                const fixInfo = fixDescriptions[issueType];
                if (!fixInfo) return ''; // Return empty string for this iteration if fix info is missing

                const isError = issueType in analysis.errors;
                const isFixable = occurrences.some(occ => occ.fixable);

                // Create a detailed list of ALL occurrences for the dropdown.
                // The container is scrollable, so we can show everything.
                const occurrencesHtml = occurrences.map(occ => `
                    <li class="issue-occurrence">
                        ${occ.line ? `<span class="line-number">L${occ.line}:</span>` : ''}
                        <code class="line-content">${escapeHtml(occ.content)}</code>
                    </li>
                `).join('');

                // Return the HTML for this specific issue type
                return `
                    <div class="validation-issue ${isError ? 'issue-error' : 'issue-warning'}" onclick="toggleIssueDetails(this)">
                        <div class="issue-checkbox">
                            ${isFixable ? `<input type="checkbox" class="fix-checkbox" data-file="${filename}" data-fix-type="${issueType}" checked onclick="event.stopPropagation()">` : ''}
                        </div>
                        <div class="issue-details">
                            <strong>${fixInfo.label} (${occurrences.length}) ${isError ? '(Error)' : '(Warning)'}</strong>
                            <small class="text-muted">${fixInfo.description}</small>
                        </div>
                        <div class="issue-toggle-icon">▾</div>
                    </div>
                    <div class="issue-occurrences-container">
                        <ul>${occurrencesHtml}</ul>
                    </div>
                `;
            }).join(''); // Join all the generated HTML strings together
        } else {
            issuesHtml = '<div class="validation-issue issue-success"><p>✅ No issues found in this file.</p></div>';
        }

        const fileCardHtml = `
            <div class="validation-file-card ${hasIssues ? '' : 'no-issues'}">
                <div class="validation-file-header" ${hasIssues ? 'onclick="toggleFileDetails(this)"' : ''}>
                    <h4>${filename}</h4>
                    <div class="file-header-right">
                        <span class="status-badge ${hasIssues ? (analysis.is_valid ? 'status-on-going' : 'status-on-going') : 'status-complete'}" 
                              style="background-color: ${hasIssues ? (analysis.is_valid ? 'var(--warning-color)' : 'var(--danger-color)') : 'var(--success-color)'};">
                            ${hasIssues ? (analysis.is_valid ? 'Warnings Found' : 'Errors Found') : 'No Issues Found'}
                        </span>
                        ${hasIssues ? '<div class="issue-toggle-icon">▾</div>' : ''}
                    </div>
                </div>
                <div class="validation-issues-list" style="display: none;">
                    ${issuesHtml}
                </div>
            </div>
        `;
        container.innerHTML += fileCardHtml;
    });

    modal.style.display = 'block';

    // Add event listener for the "Fix and Upload" button
    const fixBtn = document.getElementById('fixAndUploadBtn');
    fixBtn.onclick = () => handleFixAndUpload(window.currentValidationSessionId);
}

function toggleFileDetails(element) {
    const fileCard = element.closest('.validation-file-card');
    const issuesList = fileCard.querySelector('.validation-issues-list');
    if (issuesList) {
        const isOpening = issuesList.style.display === 'none';
        issuesList.style.display = isOpening ? 'block' : 'none';
        fileCard.classList.toggle('open', isOpening);
    }
}
function toggleIssueDetails(element) {
    const occurrencesContainer = element.nextElementSibling;
    if (occurrencesContainer && occurrencesContainer.classList.contains('issue-occurrences-container')) {
        occurrencesContainer.classList.toggle('open');
        element.classList.toggle('open');
    }
}

function closeValidationModal() {
    const modal = document.getElementById('validationResultModal');
    if (modal) {
        modal.style.display = 'none';
        document.getElementById('validationResultsContainer').innerHTML = '';
    }
}

async function handleFixAndUpload(validationSessionId) {
    const fixCheckboxes = document.querySelectorAll('.fix-checkbox:checked');
    const fixesToApply = {};

    fixCheckboxes.forEach(cb => {
        const file = cb.dataset.file;
        const fixType = cb.dataset.fixType;
        if (!fixesToApply[file]) {
            fixesToApply[file] = [];
        }
        fixesToApply[file].push(fixType);
    });

    // Also include files that had no issues
    const allFiles = [...new Set(Array.from(document.querySelectorAll('.validation-file-card h4')).map(h => h.textContent))];
    allFiles.forEach(file => {
        if (!fixesToApply[file]) {
            fixesToApply[file] = []; // No fixes, but still needs to be processed/moved
        }
    });

    const fixBtn = document.getElementById('fixAndUploadBtn');
    fixBtn.disabled = true;
    fixBtn.innerHTML = '<span class="spinner"></span> Fixing & Uploading...';

    try {
        const response = await fetch('/api/fix_and_upload_files', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                validation_session_id: validationSessionId,
                fixes: fixesToApply
            })
        });
        const result = await response.json();
        if (result.success) {
            showNotification(result.message, 'success');
            closeValidationModal();
            await loadProjectFiles(currentProject); // Refresh the file list
            proceedToFilters();
        } else {
            throw new Error(result.message);
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        fixBtn.disabled = false;
        fixBtn.innerHTML = 'Fix Selected & Upload';
    }
}

/**
 * Escapes HTML special characters to prevent them from being interpreted as HTML.
 * @param {string} str The string to escape.
 * @returns {string} The escaped string.
 */
function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

// =============================================================================
// FILE UPLOAD & SEQUENCE COUNTING
// =============================================================================

function setupFileUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    
    if (!uploadArea || !fileInput) return;
    
    uploadArea.addEventListener('click', () => {
        if (!currentProject) {
            showNotification('Please select a project first', 'warning');
            return;
        }
        fileInput.click();
    });
    
    fileInput.addEventListener('change', handleFiles);
    
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragging');
    });
    
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragging');
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragging');
        
        if (!currentProject) {
            showNotification('Please select a project first', 'warning');
            return;
        }
        
        const files = Array.from(e.dataTransfer.files).filter(file =>
            file.name.endsWith('.faa') || 
            file.name.endsWith('.fasta') ||
            file.name.endsWith('.fa')
        );
        
        if (files.length > 0) {
            const dt = new DataTransfer();
            files.forEach(file => dt.items.add(file));
            fileInput.files = dt.files;
            handleFiles({ target: fileInput });
        } else {
            showNotification('Please upload FASTA files (.faa, .fasta, .fa)', 'error');
        }
    });
}

function handleFiles(event) {
    const files = Array.from(event.target.files);
    const uploadedFilesDiv = document.getElementById('uploadedFiles');
    
    files.forEach(file => {
        if (uploadedFiles.find(f => f.name === file.name)) {
            showNotification(`File ${file.name} already added`, 'warning');
            return;
        }
        
        uploadedFiles.push(file);
        
        const fileItem = document.createElement('div');
        fileItem.className = 'file-item';
        fileItem.innerHTML = `
            <div class="file-info">
                <span class="file-icon">📄</span>
                <div>
                    <strong>${file.name}</strong>
                    <br>
                    <small class="text-muted">${formatFileSize(file.size)}</small>
                </div>
            </div>
            <button class="file-remove" onclick="removeFile('${file.name}')">Remove</button>
        `;
        
        uploadedFilesDiv.appendChild(fileItem);
        countSequencesInFile(file);
    });
    
    showNotification(`${files.length} file(s) added`, 'success');
}

function countSequencesInFile(file) {
    const reader = new FileReader();
    
    reader.onload = function(e) {
        const content = e.target.result;
        const sequenceCount = (content.match(/^>/gm) || []).length;
        
        const fileIndex = uploadedFiles.findIndex(f => f.name === file.name);
        if (fileIndex !== -1) {
            uploadedFiles[fileIndex].sequences = sequenceCount;
        }
        
        updateInputStats();
    };
    
    reader.readAsText(file);
}

function removeFile(filename) {
    uploadedFiles = uploadedFiles.filter(f => f.name !== filename);
    
    const uploadedFilesDiv = document.getElementById('uploadedFiles');
    const fileItems = uploadedFilesDiv.querySelectorAll('.file-item');
    
    fileItems.forEach(item => {
        if (item.textContent.includes(filename)) {
            item.remove();
        }
    });
    
    updateInputStats();
}

function updateInputStats() {
    const statsBox = document.getElementById('inputStats');
    
    if (uploadedFiles.length === 0) {
        statsBox.style.display = 'none';
        return;
    }
    
    statsBox.style.display = 'block';
    
    const totalSize = uploadedFiles.reduce((sum, file) => sum + file.size, 0);
    const totalSequences = uploadedFiles.reduce((sum, file) => sum + (file.sequences || 0), 0);
    
    document.getElementById('statTotalFiles').textContent = uploadedFiles.length;
    document.getElementById('statTotalSeqs').textContent = 
        totalSequences > 0 ? totalSequences.toLocaleString() : 'Calculating...';
    document.getElementById('statTotalSize').textContent = formatFileSize(totalSize);
    
    if (totalSequences > 0) {
        const flowInputCount = document.getElementById('flowInputCount');
        if (flowInputCount) {
            flowInputCount.textContent = totalSequences.toLocaleString();
        }
    }
}

// =============================================================================
// FILE UPLOAD TO SERVER
// =============================================================================

async function uploadAndProceed() {
    if (uploadedFiles.length === 0) {
        showNotification('Please add files first', 'warning');
        return;
    }
    
    if (!currentProject) {
        showNotification('Please select a project first', 'warning');
        return;
    }
    
    const formData = new FormData();
    uploadedFiles.forEach(file => {
        formData.append('files', file);
    });
    formData.append('project', currentProject);
    
    try {
        showNotification('Uploading files...', 'info');
        
        const response = await fetch('/api/upload_files', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(`Files uploaded successfully! ${result.total_sequences} sequences ready.`, 'success');
            
            const flowInputCount = document.getElementById('flowInputCount');
            if (flowInputCount) {
                flowInputCount.textContent = result.total_sequences.toLocaleString();
            }
            
            // Reload project files to show uploaded status
            await loadProjectFiles(currentProject);
            
            proceedToFilters();
        } else {
            showNotification('Error uploading files: ' + result.message, 'error');
        }
    } catch (error) {
        console.error('Error uploading files:', error);
        showNotification('Error uploading files', 'error');
    }
}

// [REST OF THE FILE CONTINUES WITH THE SAME FUNCTIONS AS BEFORE - FILTER CONFIGURATION, WEBSOCKET, JOBS, RESULTS, ETC.]
// I'm truncating here due to length, but all the rest of the functions remain the same
// Including: configureFilter, saveConfigAndEnableRun, runFilter, updateFilterStatus, 
// initializeWebSocket, loadSystemInfo, loadJobs, updateFilterStatuses, etc.

// =============================================================================
// FILTER CONFIGURATION & RUNNING - WITH CONFIG PERSISTENCE
// =============================================================================

let currentConfigDatabase = null;

function configureFilter(database) {
    if (!currentProject) {
        showNotification('Please select a project first', 'warning');
        return;
    }
    
    currentConfigDatabase = database;
    
    const modal = document.getElementById('configModal');
    const modalDatabase = document.getElementById('modalDatabase');
    const databaseInput = document.getElementById('database');
    
    const dbNames = {
        'human': 'Human Database',
        'deg': 'Database of Essential Genes (DEG)',
        'vfdb': 'Virulence Factor Database (VFDB)',
        'eskape': 'ESKAPE Protein Database'
    };
    
    modalDatabase.textContent = dbNames[database] || database.toUpperCase();
    databaseInput.value = database;
    
    // Load saved config for this project+database
    if (filterConfigs[database]) {
        document.getElementById('threads').value = filterConfigs[database].threads;
        document.getElementById('identity').value = filterConfigs[database].identity;
        document.getElementById('coverage').value = filterConfigs[database].coverage;
        document.getElementById('skipBlast').checked = filterConfigs[database].skip_blast;
        document.getElementById('cache').checked = filterConfigs[database].cache;
    } else {
        // Set defaults
        document.getElementById('threads').value = systemInfo?.cpu_count || 18;
        document.getElementById('identity').value = 35.0;
        document.getElementById('coverage').value = 90.0;
        document.getElementById('skipBlast').checked = false;
        document.getElementById('cache').checked = true;
    }
    
    modal.style.display = 'block';
}

async function saveConfigAndEnableRun() {
    const saveBtn = document.querySelector('#configModal .btn-primary');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner"></span> Saving...';

    const database = document.getElementById('database').value;
    
    const config = {
        threads: parseInt(document.getElementById('threads').value),
        identity: parseFloat(document.getElementById('identity').value),
        coverage: parseFloat(document.getElementById('coverage').value),
        skip_blast: document.getElementById('skipBlast').checked,
        cache: document.getElementById('cache').checked
    };
    
    // Save to localStorage for this project
    const success = await saveConfig(database, config);
    
    if (success) {
        const runBtn = document.getElementById(`runBtn${database.charAt(0).toUpperCase() + database.slice(1)}`);
        if (runBtn) {
            runBtn.disabled = false;
        }
        closeModal();
        showNotification(`Configuration saved for ${database.toUpperCase()} filter`, 'success');
    } else {
        // The error notification is already shown in saveConfig
    }

    saveBtn.disabled = false;
    saveBtn.innerHTML = 'Save Configuration';
}

async function runFilter(database, skipRedirect = false) {
    if (!currentProject) {
        showNotification('Please select a project first', 'warning');
        return;
    }
    
    if (!filterConfigs[database]) {
        showNotification('Please configure the filter first', 'warning');
        return;
    }
    
    const config = {
        database: database,
        project: currentProject,
        ...filterConfigs[database],
        skipRedirect: skipRedirect
    };
    
    try {
        updateFilterStatus(database, 'running');
        
        const response = await fetch('/api/start_pipeline', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(config)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Filter started successfully!', 'success');
            
            const card = document.querySelector(`.filter-card[data-database="${database}"]`);
            if (card) {
                card.dataset.jobId = result.job_id;
            }
            
            // Don't redirect if part of Run All
            if (!config.skipRedirect) {
                setTimeout(() => {
                    window.location.href = `/monitor/${result.job_id}`;
                }, 1000);
            }
        } else {
            showNotification('Error starting filter: ' + result.message, 'error');
            updateFilterStatus(database, 'not-started');
        }
    } catch (error) {
        console.error('Error starting filter:', error);
        showNotification('Error starting filter', 'error');
        updateFilterStatus(database, 'not-started');
    }
}

function updateFilterStatus(database, status) {
    const card = document.querySelector(`.filter-card[data-database="${database}"]`);
    if (!card) return;
    
    const statusBadge = card.querySelector('.status-badge');
    if (!statusBadge) return;
    
    // --- MODIFICATION: Map backend statuses to simplified frontend statuses ---
    let displayStatus, displayText, cardClass;
    
    if (status === 'running' || status === 'queued') {
        displayStatus = 'on-going';
        displayText = 'On Going';
        cardClass = 'status-card-running'; // A neutral state while running
    } else if (status === 'completed' || status === 'finished') {
        displayStatus = 'complete';
        displayText = 'Complete';
        cardClass = 'status-card-complete'; // Green card
    } else if (status === 'failed' || status === 'cancelled') {
        displayStatus = 'not-started'; // Badge will say "Not Started"
        displayText = 'Failed'; // But text shows failure
        cardClass = 'status-card-failed'; // Red card
    } else { // 'not-started'
        displayStatus = 'not-started';
        displayText = 'Not Started';
        cardClass = 'status-card-not-started'; // Grey card
    }

    // Remove old classes
    statusBadge.classList.remove('status-not-started', 'status-on-going', 'status-complete');
    // --- NEW: Remove old card status classes ---
    card.classList.remove(
        'status-card-not-started', 
        'status-card-running', 
        'status-card-complete', 
        'status-card-failed'
    );
    
    // Add new class and update text
    statusBadge.classList.add(`status-${displayStatus}`);
    statusBadge.textContent = displayText;
    // --- NEW: Add the new class to the card itself ---
    card.classList.add(cardClass);
}

async function updateFilterStatuses() {
    const databases = ['human', 'deg', 'vfdb', 'eskape'];

    // --- MODIFICATION START: Fetch file-based stats as a fallback ---
    let pipelineStats = null;
    try {
        const response = await fetch('/api/get_pipeline_stats');
        if (response.ok) {
            pipelineStats = await response.json();
        }
    } catch (error) {
        console.error("Could not fetch pipeline stats for filter card status:", error);
    }
    // --- MODIFICATION END ---

    // Find the most recent "Full Pipeline" job for this project.
    // This logic remains the same, as a running "Full Pipeline" job should be the source of truth.
    const fullRuns = activeJobs.filter(j => 
        j.type === 'Full Pipeline' && 
        j.project === currentProject
    );


    let fullRun = null;
    if (fullRuns.length > 0) {
         fullRuns.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
         fullRun = fullRuns[0];
    }

    if (fullRun) {
        // A "Full Pipeline" job exists, its status overrides individual cards
        const fullStatus = fullRun.status; // 'running', 'completed', 'failed'
        const stepsDone = (fullRun.results ? Object.keys(fullRun.results) : []);

        databases.forEach((db, index) => {
            let cardStatus = 'not-started'; // Default
            if (stepsDone.includes(db)) {
                cardStatus = 'completed';
            }

            if (fullStatus === 'running' && index === stepsDone.length) {
                cardStatus = 'running'; // This is the currently running step
            }

            if (fullStatus === 'failed' && index === stepsDone.length) {
                 cardStatus = 'failed'; // This is the step that failed
            }

            if (fullStatus === 'completed') {
                cardStatus = 'completed'; // All steps are done
            }

            updateFilterStatus(db, cardStatus);
            const card = document.querySelector(`.filter-card[data-database="${db}"]`);
            if (card) card.dataset.jobId = fullRun.id; // Link all cards to the master job
        });

    } else {
        // No "Full Pipeline" job found, use individual job logic.
        databases.forEach(db => {
            const dbJobs = activeJobs.filter(j => j.type === db && j.project === currentProject);
            
            if (dbJobs.length > 0) {
                // A job file exists, so it's the source of truth.
                dbJobs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
                const mostRecentJob = dbJobs[0];
                const card = document.querySelector(`.filter-card[data-database="${db}"]`);
                if (card) {
                    card.dataset.jobId = mostRecentJob.id;
                }
                updateFilterStatus(db, mostRecentJob.status);
            // --- MODIFICATION START: Add fallback to pipelineStats ---
            } else if (pipelineStats && pipelineStats.steps) {
                // No job file, but we have stats. Check if the step is marked as completed there.
                const stepStat = pipelineStats.steps.find(s => s.database === db && s.status === 'completed');
                if (stepStat) {
                    // The results API says it's done, so update the card.
                    updateFilterStatus(db, 'completed');
                } else {
                    // No job and no completed stat, so it's "Not Started".
                    updateFilterStatus(db, 'not-started');
                }
            // --- MODIFICATION END ---
            } else {
                // Default case if no jobs or stats are available.
                updateFilterStatus(db, 'not-started');
            }
        });
    }
}

// =============================================================================
// WEBSOCKET
// =============================================================================

function initializeWebSocket() {
    socket = io();
    
    socket.on('connect', function() {
        console.log('Connected to server');
    });
    
    socket.on('job_update', function(data) {
        updateJobStatus(data.job_id, data.data);
    });
    
    socket.on('job_log', function(data) {
        console.log('Log:', data.log.message);
    });
}

// =============================================================================
// JOBS MANAGEMENT - Filter jobs by current project
// =============================================================================

async function loadSystemInfo() {
    try {
        const response = await fetch('/api/system_info');
        systemInfo = await response.json();
        
        const cpuSpan = document.getElementById('availableCpus');
        if (cpuSpan && systemInfo.cpu_count) {
            cpuSpan.textContent = systemInfo.cpu_count;
        }
    } catch (error) {
        console.error('Error loading system info:', error);
    }
}

async function loadJobs() {
    if (!currentProject) {
        return;
    }
    
    try {
        const response = await fetch('/api/jobs');
        const data = await response.json();
        
        // Jobs are already filtered by project in backend
        activeJobs = data.jobs || [];
        updateActiveJobsDisplay();
        loadProjectInfo(currentProject); // Reload info to update flow counts
        updateFilterStatuses();
        updateRunAllButton();
    } catch (error) {
        console.error('Error loading jobs:', error);
    }
}

function updateActiveJobsDisplay() {
    const activeSection = document.getElementById('activeJobsSection');
    const activeJobsList = document.getElementById('activeJobsList');
    
    if (!activeSection || !activeJobsList) return;
    
    // Filter running jobs for current project
    const running = activeJobs.filter(j => 
        (j.status === 'running' || j.status === 'queued') && 
        j.project === currentProject
    );
    
    if (running.length === 0) {
        activeSection.style.display = 'none';
        return;
    }
    
    activeSection.style.display = 'block';
    
    activeJobsList.innerHTML = running.map(job => `
    <div class="job-card">
        <div class="job-header">
            <h4>${job.type}</h4>
            <span class="status-badge status-${job.status}">${job.status}</span>
        </div>
        <div class="progress-container">
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${job.progress}%"></div>
            </div>
            <p class="progress-text">${job.progress}%</p>
        </div>
        <!-- MODIFICATION: Make the step info a clickable link -->
        <a href="/monitor/${job.id}" class="job-step-link">
            <div class="job-step-info">
                <span>${job.current_step}</span>
            </div>
        </a>
        <!-- NEW: Add job metadata like start time -->
        <div class="job-meta">
            <span>Started: ${new Date(job.started_at).toLocaleString()}</span>
        </div>
    </div>
    `).join('');
}


function updateJobStatus(jobId, jobData) {
    // Only update if job belongs to current project
    if (jobData.project !== currentProject) {
        return;
    }
    
    const index = activeJobs.findIndex(j => j.id === jobId);
    if (index !== -1) {
        activeJobs[index] = jobData;
        updateActiveJobsDisplay();
        loadProjectInfo(currentProject); // Reload info to update flow counts
        updateFilterStatuses();
    }

    // Check for and execute a one-time handler for this job update
    if (jobUpdateHandlers[jobId]) {
        jobUpdateHandlers[jobId](jobData);
    }
}

// =============================================================================
// RESULTS LOADING
// =============================================================================

async function loadResults() {
    // Check if results section exists before trying to load
    const resultsSection = document.getElementById('results-section');
    if (!resultsSection) {
        console.warn('Results section not found, skipping loadResults');
        return;
    }
    
    try {
        const response = await fetch('/api/get_pipeline_stats');
        
        // Check if response is ok before parsing JSON
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const stats = await response.json();
        
        // Check if stats has an error property
        if (stats.error) {
            throw new Error(stats.error);
        }
        
        updateResultsSummary(stats);
        updateResultsTable(stats);
        createOrUpdateResultsChart(stats);
    } catch (error) {
        console.error('Error loading results:', error);
        // Only show notification if it's a real error, not just empty results
        if (error.message && !error.message.includes('status: 200')) {
            showNotification('Error loading results: ' + error.message, 'error');
        }
    }
}

/**
 * Creates or updates the reduction bar chart on the results page.
 */
function createOrUpdateResultsChart(stats) {
    const ctx = document.getElementById('resultsChartCanvas');
    if (!ctx) return; // Don't do anything if canvas isn't on the page

    // 1. Destroy the old chart if it exists
    if (myResultsChart) {
        myResultsChart.destroy();
    }

    // 2. Process the stats data to get chart labels, data, and tooltip info
    const labels = [];
    const reductionData = [];
    const customTooltipData = [];
    let prevCount = stats.initial_input || 0; // Start with the initial input

    if (stats.steps && stats.steps.length > 0) {
        stats.steps.forEach(step => {
            // X-Axis label (e.g., "HUMAN")
            labels.push(step.database.toUpperCase());
            
            let reduction = 0;
            // Calculate reduction *for this specific step*
            if (prevCount > 0 && step.output !== undefined) {
                reduction = (1 - (step.output / prevCount)) * 100;
            }
            
            // Y-Axis data point
            reductionData.push(reduction);
            
            // Custom data to show in the tooltip
            customTooltipData.push({
                input: prevCount,
                output: step.output
            });
            
            // The output of this step is the input for the next one
            prevCount = step.output;
        });
    }

    // 3. Create the new chart
    myResultsChart = new Chart(ctx, {
        type: 'line', // <-- MODIFICATION: Changed 'bar' to 'line'
        data: {
            labels: labels, // X-Axis
            datasets: [{
                label: 'Reduction %',
                data: reductionData, // Y-Axis

                // --- MODIFICATION: Added line graph styling ---
                fill: true,
                tension: 0.1,
                backgroundColor: 'rgba(59, 130, 246, 0.2)',
                borderColor: 'rgba(59, 130, 246, 1)',
                pointBackgroundColor: 'rgba(59, 130, 246, 1)', // Color of the dots
                pointRadius: 8, // Size of the dots
                // --- END MODIFICATION ---

                borderWidth: 3, // Width of the line
                // Pass our custom data to the dataset
                customData: customTooltipData
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    ticks: {
                        font: {
                            size: 20 // X-axis label font size
                        }
                    }
                },
                y: {
                    beginAtZero: true,
                    max: 100, // Y-Axis is a percentage
                    ticks: {
                        // Add a '%' sign to the Y-axis numbers
                        callback: function(value) {
                            return value.toFixed(0) + '%';
                        },
                        font: {
                            size: 20 // Y-axis label font size
                        }
                    }
                }
            },
            plugins: {
                title: {
                    display: true,
                    text: 'Sequence Reduction per Filter Step',
                    font: {
                        size: 24 // Title font size
                    }
                },
                tooltip: {
                    backgroundColor:'rgba(0, 0, 0, 0.85)',
                    padding:12,
                    titleFont: { size: 24 },
                    bodyFont: { size: 18 },
                
                    // 4. This configures the interactive hover tooltip
                    callbacks: {
                        // Title will be the filter name (e.g., "HUMAN")
                        title: function(tooltipItems) {
                            return tooltipItems[0].label;
                        },
                        // Body of the tooltip
                        label: function(context) {
                            // Get the Y-axis value
                            const reductionValue = context.parsed.y.toFixed(1) + '%';
                            
                            // Get our custom data (input/output counts)
                            const customData = context.dataset.customData[context.dataIndex];
                            const input = customData.input.toLocaleString();
                            const output = customData.output.toLocaleString();

                            // Return an array of strings, each on a new line
                            return [
                                `Reduction: ${reductionValue}`,
                                ``, // A blank line for spacing
                                `Input:  ${input} sequences`,
                                `Output: ${output} sequences`
                            ];
                        }
                    }
                }
            }
        }
    });
}

function updateResultsSummary(stats) {
    const finalTargetCount = document.getElementById('finalTargetCount');
    const reductionRate = document.getElementById('reductionRate');
    const totalRuntime = document.getElementById('totalRuntime');
    
    if (stats.steps && stats.steps.length > 0) {
        const lastStep = stats.steps[stats.steps.length - 1];
        if (lastStep.output !== undefined && finalTargetCount) {
            finalTargetCount.textContent = lastStep.output.toLocaleString();
        }
    }
    
    if (stats.initial_input > 0 && stats.steps.length > 0) {
        const lastStep = stats.steps[stats.steps.length - 1];
        if (lastStep.output !== undefined && reductionRate) {
            const reduction = ((1 - lastStep.output / stats.initial_input) * 100).toFixed(1);
            reductionRate.textContent = reduction + '%';
        }
    }
    
    if (stats.total_runtime && totalRuntime) {
        totalRuntime.textContent = stats.total_runtime;
    }
}

function updateResultsTable(stats) {
    const tbody = document.getElementById('resultsTableBody');
    
    // Check if element exists before trying to set innerHTML
    if (!tbody) {
        console.warn('resultsTableBody element not found');
        return;
    }
    
    const databases = [
        { name: 'human', label: 'Human Database' },
        { name: 'deg', label: 'Database of Essential Genes (DEG)' },
        { name: 'vfdb', label: 'Virulence Factor Database (VFDB)' },
        { name: 'eskape', label: 'ESKAPE Protein Database' }
    ];
    
    let html = '';
    let prevCount = stats.initial_input || 0;
    
    databases.forEach((db, index) => {
        const step = stats.steps && stats.steps.find ? stats.steps.find(s => s.database === db.name) : null;
        
        if (step) {
            const input = prevCount > 0 ? prevCount.toLocaleString() : '-';
            const output = step.output ? step.output.toLocaleString() : '0';
            const reduction = prevCount > 0 && step.output !== undefined ?
                `${((1 - step.output / prevCount) * 100).toFixed(1)}%` : '-';
            
            html += `
                <tr>
                    <td><strong>${db.label}</strong></td>
                    <td>${input}</td>
                    <td>${output}</td>
                    <td>${reduction}</td>
                    <td>
                        <button class="btn btn-small btn-primary selection-btn" style="margin-right: 5px;"
                           data-database="${db.name}">Selection</button>
                        <a href="/api/download/${db.name}_passing.faa" title="Download"
                           class="btn btn-small btn-secondary">📥</a>
                    </td>
                    <td><span class="status-badge status-finished">Finished</span></td>
                </tr>
            `;
            
            prevCount = step.output || 0;
        } else {
            html += `
                <tr class="not-started-row">
                    <td><strong>${db.label}</strong></td>
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
                    <td><span class="status-badge status-not-started">Not Started</span></td>
                </tr>
            `;
        }
    });
    
    tbody.innerHTML = html || '<tr><td colspan="6" class="text-center text-muted">No results yet.</td></tr>';
}

function updateDownloadButtons(stats) {
    const downloadButtons = document.getElementById('downloadButtons');
    
    // Check if element exists before trying to set innerHTML
    if (!downloadButtons) {
        console.warn('downloadButtons element not found');
        return;
    }
    
    let html = '';
    let hasResults = false;
    
    if (stats.steps && Array.isArray(stats.steps)) {
        stats.steps.forEach(step => {
            if (step && step.output > 0) {
                hasResults = true;
                const label = step.database ? step.database.toUpperCase() : 'UNKNOWN';
                html += `
                    <a href="/api/download/${step.database}_passing.faa" class="btn btn-primary">
                        📥 ${label} Results (${step.output.toLocaleString()} sequences)
                    </a>
                `;
            }
        });
    }
    
    downloadButtons.innerHTML = hasResults ? html : 
        '<p class="text-muted">Complete the pipeline to download results</p>';
}

/**
 * A generic function to open the file reader modal and display content from a URL.
 * @param {string} title - The title to display in the modal header.
 * @param {string} url - The API endpoint to fetch the content from.
 */
async function openFileReaderModal(title, url) {
    const modal = document.getElementById('fileReaderModal');
    const modalTitle = document.getElementById('modalFileTitle');
    const modalContent = document.getElementById('modalFileContent');

    // Show the modal and set loading state
    modalTitle.textContent = title;
    modalContent.textContent = `Loading content from ${url}...`;
    modal.style.display = 'block';

    try {
        const response = await fetch(url);
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || `Failed to load content (Status: ${response.status})`);
        }
        
        modalContent.textContent = data.content;
    } catch (error) {
        modalContent.textContent = `Error loading content:\n\n${error.message}`;
    }
}

/**
 * Opens the file reader modal and fetches the file content.
 */
async function openFileReader(filename, directoryType = 'output') {
    const modal = document.getElementById('fileReaderModal');
    const title = document.getElementById('modalFileTitle');
    const content = document.getElementById('modalFileContent');

    const apiUrl = `/api/view_file/${filename}?type=${directoryType}`;
    await openFileReaderModal(`Viewing: ${filename}`, apiUrl);
}

/**
 * Closes the file reader modal and clears its content.
 */
function closeFileReaderModal() {
    const modal = document.getElementById('fileReaderModal');
    const content = document.getElementById('modalFileContent');
    
    if (modal) {
        // Hide the modal and clear content
        modal.style.display = 'none';
        if (content) {
            content.textContent = '';
        }
    }
}

/**
 * Opens the literature selection modal.
 * Fetches, parses, and displays sequence IDs from the relevant _passing.faa file.
 */
async function openLiteratureModal(database) {
    const modal = document.getElementById('literatureModal');
    const title = document.getElementById('literatureModalTitle');
    const listContainer = document.getElementById('literatureSequenceList');
    updateLiteratureSelectionCount(0); // Reset count on open

    modal.dataset.database = database; // Store the database context for the download function
    // Show modal and set loading state
    title.textContent = `Select Sequences from ${database.toUpperCase()}`;
    listContainer.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Loading sequences...</td></tr>';
    modal.style.display = 'block';

    const filename = `${database}_passing.faa`;

    try {
        // Fetch both the FASTA file content and the project file list in parallel
        const [fastaResponse, filesResponse] = await Promise.all([
            fetch(`/api/view_file/${filename}`),
            fetch(`/api/project_files/${currentProject}`)
        ]);

        const data = await fastaResponse.json();
        const filesData = await filesResponse.json();

        // Update the variant count header with the number of input files
        const variantHeader = document.getElementById('literatureVariantHeader');
        const fileCount = filesData.success ? filesData.count : 0;
        variantHeader.textContent = `Number of variants in ${fileCount} files`;

        if (!fastaResponse.ok || !data.success) {
            throw new Error(data.error || `File not found or server error.`);
        }

        const fastaText = data.content;
        const proteinCounts = new Map();

        // Parse the FASTA text to get protein names and count variants
        const lines = fastaText.split('\n');
        lines.forEach(line => {
            if (line.startsWith('>')) {
                const firstSpaceIndex = line.indexOf(' ');
                if (firstSpaceIndex !== -1) {
                    // Protein name is everything after the first space
                    const proteinName = line.substring(firstSpaceIndex + 1).trim();
                    if (proteinName) { // Only count if a name exists
                        proteinCounts.set(proteinName, (proteinCounts.get(proteinName) || 0) + 1);
                    }
                }
            }
        });

        // Convert the Map to an array of objects and sort alphabetically by name
        const sortedData = Array.from(proteinCounts, ([name, count]) => ({ name, count }))
            .sort((a, b) => a.name.localeCompare(b.name));

        if (sortedData.length === 0) {
            listContainer.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No sequences found in this file.</td></tr>';
            return;
        }

        // Populate the list with checkboxes
        listContainer.innerHTML = sortedData.map(item => `
            <tr>
                <td><input type="checkbox" class="literature-checkbox" value="${item.name}"></td>
                <td>${item.name}</td>
                <td>${item.count}</td>
            </tr>
        `).join('');

        // Reset the 'Select All' checkbox to unchecked state
        const selectAllCheckbox = document.getElementById('literatureSelectAll');
        if (selectAllCheckbox) selectAllCheckbox.checked = false;

    } catch (error) {
        console.error('Error fetching sequences for literature review:', error);
        listContainer.innerHTML = `<tr><td colspan="3" class="text-center text-muted" style="color: var(--danger-color);">Error: ${error.message}</td></tr>`;
    }
}

/**
 * Updates the 'x sequences selected' text in the literature modal.
 */
function updateLiteratureSelectionCount(forceCount = null) {
    const countElement = document.getElementById('literatureSelectedCount');
    if (!countElement) return;

    const count = forceCount !== null 
        ? forceCount 
        : document.querySelectorAll('#literatureSequenceList .literature-checkbox:checked').length;

    countElement.textContent = `${count} sequence${count === 1 ? '' : 's'} selected`;
}

/**
 * Closes the literature selection modal.
 */
function closeLiteratureModal() {
    const modal = document.getElementById('literatureModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * Opens the modal to choose between downloading selected or all proteins.
 */
async function openDownloadOptionsModal() {
    const checkedBoxes = document.querySelectorAll('#literatureSequenceList .literature-checkbox:checked');
    const downloadSelectedBtn = document.getElementById('downloadSelectedBtn');

    // Disable the "Download Selected" button if nothing is checked
    if (checkedBoxes.length === 0) {
        downloadSelectedBtn.disabled = true;
        downloadSelectedBtn.title = 'Select at least one protein to download.';
    } else {
        downloadSelectedBtn.disabled = false;
        downloadSelectedBtn.title = '';
    }

    // Populate the file source dropdown
    const fileSourceSelect = document.getElementById('downloadFileSource');
    fileSourceSelect.innerHTML = '<option value="">Loading files...</option>';

    try {
        const response = await fetch(`/api/project_files/${currentProject}`);
        const data = await response.json();
        if (data.success && data.files.length > 0) {
            fileSourceSelect.innerHTML = data.files.map(file => 
                `<option value="${file.name}">${file.name}</option>`
            ).join('');
        } else {
            fileSourceSelect.innerHTML = '<option value="">No input files found</option>';
        }
    } catch (error) {
        fileSourceSelect.innerHTML = '<option value="">Error loading files</option>';
    }

    // Reset the variant selection controls to default
    document.getElementById('downloadAllVariants').checked = true;
    document.getElementById('downloadFileSourceContainer').style.display = 'none';

    // Show the modal
    document.getElementById('downloadOptionsModal').style.display = 'block';
}

/**
 * Handles the actual download request based on user's choice ('selected' or 'all').
 */
async function handleDownloadRequest(type) {
    const modal = document.getElementById('literatureModal');
    const database = modal.dataset.database;
    const format = document.querySelector('input[name="downloadFormat"]:checked').value;
    const allVariants = document.getElementById('downloadAllVariants').checked;
    let sourceFile = null;

    if (!allVariants) {
        sourceFile = document.getElementById('downloadFileSource').value;
    }

    const namesOnly = (format === 'names');
    let proteinNames = [];

    if (type === 'selected') {
        const checkedBoxes = document.querySelectorAll('#literatureSequenceList .literature-checkbox:checked');
        proteinNames = Array.from(checkedBoxes).map(cb => cb.value);
    } else { // 'all'
        const allCheckboxes = document.querySelectorAll('#literatureSequenceList .literature-checkbox');
        proteinNames = Array.from(allCheckboxes).map(cb => cb.value);
    }

    showNotification('Preparing your download...', 'info');

    try {
        const response = await fetch('/api/download_selected_sequences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                database: database,
                protein_names: proteinNames,
                names_only: namesOnly,
                source_file: sourceFile
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || 'Server error during download preparation.');
        }

        // Trigger the file download
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        const fileExtension = namesOnly ? 'txt' : 'faa';
        a.download = `${database}_${type}_proteins.${fileExtension}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();

    } catch (error) {
        showNotification(`Download failed: ${error.message}`, 'error');
        console.error('Error downloading selected sequences:', error);
    }

    closeDownloadOptionsModal();
}

/**
 * Closes the download options modal.
 */
function closeDownloadOptionsModal() {
    document.getElementById('downloadOptionsModal').style.display = 'none';
}

/**
 * Gathers checked sequences, enables and switches to the Mutational Analysis tab.
 */
async function proceedToMutationAnalysis() {
    const checkedBoxes = document.querySelectorAll('.literature-checkbox:checked');
    
    selectedLiteratureSequences = Array.from(checkedBoxes).map(cb => {
        const row = cb.closest('tr');
        const name = cb.value;
        const count = row.querySelector('td:nth-child(3)').textContent;
        return { name, count: parseInt(count, 10) };
    });

    if (selectedLiteratureSequences.length === 0) {
        showNotification('Please select at least one sequence to proceed.', 'warning');
        return;
    }

    closeLiteratureModal();
    showNotification(`Starting preparation for ${selectedLiteratureSequences.length} proteins...`, 'info');

    // --- MODIFICATION: First, save the selection to the project metadata ---
    try {
        const saveResponse = await fetch('/api/save_mutation_selection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proteins: selectedLiteratureSequences })
        });
        const saveResult = await saveResponse.json();
        if (!saveResult.success) {
            throw new Error(saveResult.message || 'Failed to save protein selection.');
        }
    } catch (error) {
        showNotification(`Error saving selection: ${error.message}`, 'error');
        return; // Stop if we can't save the selection
    }

    try {
        // Call the new backend endpoint to start the master job
        const response = await fetch('/api/prepare_mutational_analysis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proteins: selectedLiteratureSequences })
        });

        const result = await response.json();
        if (!result.success) {
            throw new Error(result.message || 'Failed to start preparation job.');
        }

        // --- MODIFICATION: Redirect to the mutational analysis page instead of the monitor page ---
        window.location.href = '/mutational_analysis';

    } catch (error) {
        showNotification(`Error starting mutational analysis preparation: ${error.message}`, 'error');
        console.error('Error starting mutational analysis preparation:', error.message);
    }
}

async function viewProteinVariants(proteinName) {
    const modal = document.getElementById('fileReaderModal');
    const title = document.getElementById('modalFileTitle');
    const content = document.getElementById('modalFileContent');

    title.textContent = `Variants for: ${proteinName}`;
    content.textContent = `Loading variants for ${proteinName}...`;
    modal.style.display = 'block';

    try {
        const response = await fetch('/api/download_selected_sequences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                database: 'eskape', // Always fetch from the final ESKAPE results
                protein_names: [proteinName], // Request only this specific protein
                names_only: false, // We want the full sequences
                source_file: null // We want from the eskape_passing.faa, not original input
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || 'Server error during variant retrieval.');
        }

        const fastaContent = await response.text(); // Get raw text content
        content.textContent = fastaContent.trim() === "" ? `No variants found for ${proteinName} in the ESKAPE passing file.` : fastaContent;

    } catch (error) {
        console.error('Error fetching protein variants:', error);
        content.textContent = `Error loading variants:\n\n${error.message}`;
    }
}

/**
 * Fetches all variants for a specific protein and saves them to a local FASTA file.
 * @param {string} proteinName - The name of the protein to save variants for.
 */
async function saveProteinVariants(proteinName) {
    showNotification(`Preparing variants for "${proteinName}"...`, 'info');

    try {
        // Use the existing download_selected_sequences API to get the FASTA content
        const response = await fetch('/api/download_selected_sequences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                database: 'eskape', // Always fetch from the final ESKAPE results
                protein_names: [proteinName], // Request only this specific protein
                names_only: false, // We want the full sequences
                source_file: null // We want from the eskape_passing.faa, not original input
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || 'Server error during variant retrieval.');
        }

        const fastaContent = await response.text();
        if (fastaContent.trim() === "") {
            showNotification(`No variants found for ${proteinName} to save.`, 'warning');
            return;
        }

        // Create a Blob and trigger a download
        const blob = new Blob([fastaContent], { type: 'application/fasta' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        // Sanitize filename and download
        const safeFilename = proteinName.replace(/[^a-z0-9_.-]/gi, '_').substring(0, 50);
        a.download = `${safeFilename}_variants.faa`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
    } catch (error) {
        showNotification(`Error saving variants: ${error.message}`, 'error');
        console.error('Error saving protein variants:', error);
    }
}

/**
 * Opens a modal to view a specific alignment file.
 * @param {string} proteinName - The name of the protein.
 * @param {string} filename - The filename of the alignment file (.aln).
 */
async function viewAlignmentFile(proteinName, filename) {
    const modal = document.getElementById('fileReaderModal'); // This is the modal on mutational_analysis.html
    const title = document.getElementById('modalFileTitle');
    const content = document.getElementById('modalFileContent');
    const downloadBtn = document.getElementById('downloadAlignmentBtn'); // This button is on the modal

    title.textContent = `Alignment for: ${proteinName}`;
    content.textContent = `Loading alignment file: ${filename}...`;
    modal.style.display = 'block';

    try {
        const params = new URLSearchParams({
            protein_name: proteinName,
            filename: filename
        });

        if (downloadBtn) {
            const downloadUrl = `/api/download_alignment_file?${params.toString()}`;
            downloadBtn.href = downloadUrl;
        }

        const response = await fetch(`/api/view_alignment_file?${params.toString()}`);
        const data = await response.json();

        if (!response.ok || !data.success) {
            const error = new Error(data.error || 'Server error while fetching alignment file.');
            if (data.can_rerun) error.can_rerun = true;
            throw error;
        }

        // Pass the new ss_string to the rendering function
        renderPositionCharts(
            proteinName, data.alignment_data, data.max_id_len, 
            data.positional_data, data.occupancy_data, 
            data.positional_counts_text,
            data.ss_string // NEW: Pass the structure string
        );

    } catch (error) {
        console.error('Error fetching alignment file:', error);
        
        // Clear content and show formatted error
        content.innerHTML = '';
        
        const errorContainer = document.createElement('div');
        errorContainer.style.textAlign = 'left';
        errorContainer.style.padding = '20px';
        
        const errorMsg = document.createElement('div');
        errorMsg.style.color = 'var(--danger-color)';
        errorMsg.style.marginBottom = '15px';
        errorMsg.style.wordWrap = 'break-word';
        errorMsg.innerHTML = `<strong>Error loading alignment file:</strong><br>${error.message.replace(/\n/g, '<br>')}`;
        errorContainer.appendChild(errorMsg);
        
        // Add Re-run button if allowed
        if (error.can_rerun) {
            const rerunBtn = document.createElement('button');
            rerunBtn.className = 'rerun-btn'; // Uses the style added to style.css
            rerunBtn.innerHTML = '🔄 Re-run Alignment (Fix & Retry)';
            
            rerunBtn.onclick = async function() {
                this.disabled = true;
                this.innerHTML = '<span class="spinner"></span> Starting...';
                
                try {
                    const res = await fetch('/api/run_alignment', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ protein_name: proteinName })
                    });
                    const data = await res.json();
                    
                    if (data.success) {
                        alert('Alignment job started! Check the Monitor tab for progress.');
                        closeFileReaderModal();
                    } else {
                        alert('Failed to start job: ' + data.message);
                        this.disabled = false;
                        this.innerHTML = '🔄 Re-run Alignment (Fix & Retry)';
                    }
                } catch (e) {
                    alert('Error: ' + e.message);
                    this.disabled = false;
                    this.innerHTML = '🔄 Re-run Alignment (Fix & Retry)';
                }
            };
            
            errorContainer.appendChild(rerunBtn);
        }
        
        content.appendChild(errorContainer);
    }
}

/**
 * Finds the best reference sequence from an alignment based on length and gap count.
 * @param {Array<Object>} alignmentData - Array of sequence objects {id, sequence}.
 * @returns {string|null} The ID of the reference sequence, or null if none found.
 */
function findReferenceSequence(alignmentData) {
    if (!alignmentData || alignmentData.length === 0) {
        return null;
    }

    let bestCandidate = null;
    let maxUngappedLength = -1;
    let minGapCount = Infinity;

    // Filter out the consensus line if it exists
    const sequences = alignmentData.filter(seq => !seq.is_consensus);

    for (const seqObj of sequences) {
        if (!seqObj.id) continue; // Skip entries without an ID

        const sequence = seqObj.sequence;
        const ungappedLength = (sequence.match(/[^ -]/g) || []).length;
        const gapCount = (sequence.match(/-/g) || []).length;

        // Criterion 1: Prioritize longest ungapped length
        if (ungappedLength > maxUngappedLength) {
            maxUngappedLength = ungappedLength;
            minGapCount = gapCount;
            bestCandidate = seqObj;
        } 
        // Criterion 2: Tie-breaker using fewest gaps
        else if (ungappedLength === maxUngappedLength) {
            if (gapCount < minGapCount) {
                minGapCount = gapCount;
                bestCandidate = seqObj;
            }
            // Criterion 3 (Implicit): If still a tie, the first one encountered is kept.
        }
    }

    return bestCandidate ? bestCandidate.id : null;
}

/**
 * Renders the position-wise bar charts in the alignment viewer.
 * @param {Array} alignmentData - Array of sequence objects {id, sequence}.
 * @param {number} maxIdLen - The length of the longest sequence ID for padding.
 * @param {Array} positionalData - The structured data from the backend.
 * @param {string} positionalCountsText - The text-based report.
 */
function renderPositionCharts(proteinName, alignmentData, maxIdLen, positionalData, occupancyData, positionalCountsText, ssString) {
    const modalContent = document.getElementById('modalFileContent');
    // Clear previous content
    modalContent.innerHTML = '';

    if (!alignmentData || alignmentData.length === 0) {
        modalContent.textContent = "No alignment data to display.";
        return;
    }

    // Create the main viewer container
    const viewerWrapper = document.createElement('div');
    viewerWrapper.className = 'msa-viewer-container';
    modalContent.appendChild(viewerWrapper);

    // --- NEW: Color mapping for amino acids (frontend-side) ---
    const aaColorMapping = {
        'R': { bg: '#E60606', text: '#FFFFFF' }, 'K': { bg: '#C64200', text: '#FFFFFF' },
        'Q': { bg: '#FF6600', text: '#000000' }, 'N': { bg: '#FF9900', text: '#000000' },
        'E': { bg: '#FFCC00', text: '#000000' }, 'D': { bg: '#FFCC99', text: '#000000' },
        'H': { bg: '#FFFF99', text: '#000000' }, 'P': { bg: '#FFFF00', text: '#000000' },
        'Y': { bg: '#CCFFCC', text: '#000000' }, 'W': { bg: '#CC99FF', text: '#000000' },
        'S': { bg: '#CCFF99', text: '#000000' }, 'T': { bg: '#00FF99', text: '#000000' },
        'G': { bg: '#00FF00', text: '#000000' }, 'A': { bg: '#CCFFFF', text: '#000000' },
        'M': { bg: '#99CCFF', text: '#000000' }, 'C': { bg: '#00FFFF', text: '#000000' },
        'F': { bg: '#00CCFF', text: '#000000' }, 'L': { bg: '#3366FF', text: '#FFFFFF' },
        'V': { bg: '#0000FF', text: '#FFFFFF' }, 'I': { bg: '#000080', text: '#FFFFFF' },
        '-': { bg: '#FFFFFF', text: '#CCCCCC' }, // Gap
        'X': { bg: '#E0E0E0', text: '#000000' }, // Unknown
        '*': { bg: 'transparent', text: 'var(--text-primary)' }, // Consensus symbols
        ':': { bg: 'transparent', text: 'var(--text-primary)' },
        '.': { bg: 'transparent', text: 'var(--text-primary)' }
    };

    // --- NEW: Find the reference sequence ID first ---
    const referenceId = findReferenceSequence(alignmentData);
    const referenceSequence = alignmentData.find(s => s.id === referenceId)?.sequence || '';

    // --- MODIFICATION: Build the HTML/CSS secondary structure row ---
    let structureHtml = '';
    if (ssString) {
        structureHtml += `<div class="msa-id msa-title">Structure</div>`;
        structureHtml += `<div class="msa-sequence msa-structure-row">`;
        let ssIndex = 0;
        for (const refChar of referenceSequence) {
            if (refChar !== '-') {
                const structChar = ssString[ssIndex] || 'C'; // Default to Coil if out of bounds
                let dataText = 'Coil';
                if (structChar === 'H') {
                    dataText = 'Alpha';
                } else if (structChar === 'E') {
                    dataText = 'Beta';
                }
                structureHtml += `<span class="ss-char ss-${structChar}" data-text="${dataText}"></span>`;
                ssIndex++;
            } else {
                // Add a non-interactive gap character
                structureHtml += `<span class="ss-char ss-gap"></span>`;
            }
        }
        structureHtml += `</div>`;
    }

    // --- NEW: Build the colored alignment HTML ---
    let alignmentHtml = '<div class="msa-grid">';
    alignmentData.forEach(seqObj => {
        // --- MODIFICATION: Add a 'reference' class if the ID matches ---
        const isReference = seqObj.id === referenceId;
        let idClass = isReference ? 'msa-id reference' : 'msa-id';
        let paddedId = seqObj.id.padEnd(maxIdLen, ' ');

        // --- NEW: Add a special class for the title rows ---
        if (seqObj.id === 'Alignment Score') {
            idClass += ' msa-title';
        }

        alignmentHtml += `<div class="${idClass}">${paddedId.trim()}</div>`;
        alignmentHtml += `<div class="msa-sequence">`;
        for (const char of seqObj.sequence) {
            const colors = aaColorMapping[char.toUpperCase()] || aaColorMapping['X'];
            alignmentHtml += `<span style="background-color:${colors.bg}; color:${colors.text};">${char}</span>`;
        }
        alignmentHtml += `</div>`;
    });
    alignmentHtml = '<div class="msa-grid">' + structureHtml + alignmentHtml.substring('<div class="msa-grid">'.length);

    /**
     * Helper function to generate the HTML for a chart (Conservation or Occupancy).
     * @param {Array} chartData - The data for the chart (e.g., positionalData or occupancyData).
     * @param {string} yAxisTitle - The title for the Y-axis (e.g., "Conservation").
     * @param {Function} colorFunction - A function that takes a percentage and returns a color.
     * @param {Function} titleFunction - A function that takes a data point and returns a title string for the bar.
     * @param {Function} barHeightExtractor - A function that takes a data point and returns the percentage for the bar's height.
     * @param {boolean} showXAxisLabels - Whether to render the x-axis position labels.
     * @returns {string} The complete HTML for the chart grid.
     */
    function createChartHtml(chartData, yAxisTitle, colorFunction, titleFunction, barHeightExtractor, showXAxisLabels = true) {
        if (!chartData || chartData.length === 0) {
            return '';
        }

        let barsHtml = '<div class="position-charts-container">';
        let labelsHtml = '<div class="position-labels-container">';

        chartData.forEach((pos, index) => {
            const barHeight = barHeightExtractor(pos, index);
            const color = colorFunction(barHeight);
            const title = titleFunction(pos);

            barsHtml += `<div class="position-chart">`;
            barsHtml += `<div class="position-bars">`;
            barsHtml += `
                <div class="bar-segment" style="height: ${barHeight}%; background-color: ${color};" title="${title}">
                </div>
            `;
            barsHtml += `</div></div>`;

            // Conditionally render labels
            if (showXAxisLabels && (pos.position % 10 === 0 || (pos.position === 1 && chartData.length > 1))) {
                labelsHtml += `<div class="position-label" style="grid-column: ${pos.position};">${pos.position}</div>`;
            }
        });

        barsHtml += '</div>';
        labelsHtml += '</div>';

        const chartContainer = document.createElement('div');
        chartContainer.className = 'charts-wrapper';
        const yAxisTitleHtml = `<div class="y-axis-title">${yAxisTitle}</div>`;

        const spacerContent = '&nbsp;'.repeat(maxIdLen);
        const spacer = `<div class="msa-id">${spacerContent}</div>`;
        const chartGrid = `<div class="msa-grid">${spacer}<div class="msa-sequence-chart-content">${yAxisTitleHtml}${barsHtml}${labelsHtml}</div></div>`;

        chartContainer.innerHTML = chartGrid;
        return chartContainer;
    }

    /**
     * Calculates a color on a gradient from dark green to bright green.
     * @param {number} percentage - A value from 0 to 100.
     * @returns {string} A hex color string.
     */
    function getConservationColor(percentage) {
        const startColor = { r: 37, g: 61, b: 44 };   // #253D2C (0%)
        const endColor = { r: 0, g: 255, b: 127 }; // #00FF7F (100%)

        const ratio = percentage / 100;

        const r = Math.round(startColor.r + (endColor.r - startColor.r) * ratio);
        const g = Math.round(startColor.g + (endColor.g - startColor.g) * ratio);
        const b = Math.round(startColor.b + (endColor.b - startColor.b) * ratio);

        // Helper to convert a number to a 2-digit hex string
        const toHex = (c) => ('0' + c.toString(16)).slice(-2);

        return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
    }

    // Render the alignment grid (which now includes the structure row)
    const alignmentContainer = document.createElement('div');
    alignmentContainer.innerHTML = alignmentHtml; // This now contains the structure row
    viewerWrapper.appendChild(alignmentContainer); // This is now appended after the image

    // --- NEW: Render Occupancy Chart ---
    const occupancyChart = createChartHtml(
        occupancyData,
        'Occupancy',
        (percentage) => `hsl(200, 80%, ${90 - (percentage * 0.4)}%)`, // Blue gradient
        (pos) => `Occupancy: ${pos.percentage.toFixed(1)}%`,
        (pos) => pos.percentage || 0, // Extractor for bar height
        false // Do not show x-axis labels for this chart
    );
    if (occupancyChart) {
        viewerWrapper.appendChild(occupancyChart);
    }

    // --- NEW: Render Conservation Chart ---
    const conservationChart = createChartHtml(
        positionalData,
        'Conservation',
        (barHeight) => getConservationColor(barHeight), // Color is based on the dominant percentage
        (pos) => {
            // This logic is now duplicated, but it's correct. It calculates the title.
            let dominantAA = '';
            let maxPercentage = 0;
            for (const [aa, percentage] of Object.entries(pos.percentages)) {
                if (aa !== '-' && percentage > maxPercentage) {
                    maxPercentage = percentage;
                    dominantAA = aa;
                }
            }
            return dominantAA ? `${dominantAA}: ${maxPercentage.toFixed(1)}%` : 'N/A';
        },
        (pos) => { // --- FIX: Add the correct bar height extractor for conservation ---
            let dominantAA = '';
            let maxPercentage = 0;
            for (const [aa, percentage] of Object.entries(pos.percentages)) {
                if (aa !== '-' && percentage > maxPercentage) {
                    maxPercentage = percentage;
                    dominantAA = aa;
                }
            }
            return maxPercentage; // The height of the bar is the percentage of the dominant AA.
        }
    );
    if (conservationChart) {
        viewerWrapper.appendChild(conservationChart);
    }

    // --- NEW: Add a toggle for the detailed text report ---
    const reportWrapper = document.createElement('div');
    reportWrapper.style.marginTop = '20px';

    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'btn btn-secondary';
    toggleBtn.textContent = 'Show Position-wise Counts';

    const textReportContainer = document.createElement('div');
    textReportContainer.style.display = 'none'; // Initially hidden
    textReportContainer.style.marginTop = '15px';

    const textReportPre = document.createElement('pre');
    textReportPre.textContent = positionalCountsText;
    textReportContainer.appendChild(textReportPre);

    toggleBtn.onclick = () => {
        const isHidden = textReportContainer.style.display === 'none';
        textReportContainer.style.display = isHidden ? 'block' : 'none';
        toggleBtn.textContent = isHidden ? 'Hide Position-wise Counts' : 'Show Position-wise Counts';
    };

    reportWrapper.appendChild(toggleBtn);
    reportWrapper.appendChild(textReportContainer);
    viewerWrapper.appendChild(reportWrapper);

    // --- MODIFICATION: Add the note to the modal's footer (form-actions) ---
    const modalFooter = document.querySelector('#fileReaderModal .form-actions');
    const referenceNote = document.createElement('div');
    referenceNote.className = 'msa-reference-note';
    referenceNote.innerHTML = `
        <p><strong>Note:</strong> <span class="note-highlight">The highlighted sequence</span> is the selected reference.</p>
        <div class="legend-container">
            <strong>Structure Legend:</strong>
            <span class="legend-item"><span class="ss-char ss-H"></span> Alpha-Helix (H)</span>
            <span class="legend-item"><span class="ss-char ss-E"></span> Beta-Strand (E)</span>
            <span class="legend-item"><span class="ss-char ss-C"></span> Coil (C)</span>
        </div>
    `;
    // Prepend it so it appears on the left side of the footer
    modalFooter.prepend(referenceNote);

}

function closeFileReaderModal() {    
    const modal = document.getElementById('fileReaderModal');
    if (modal) {
        document.getElementById('modalFileContent').innerHTML = 'Loading...';
        const existingNote = modal.querySelector('.msa-reference-note');
        if (existingNote) {
            existingNote.remove();
        }
        modal.style.display = 'none';
    }
}

/**
 * Resets the Mutational Analysis tab to its initial state (an empty table).
 */
function resetMutationAnalysisView() {
}

/**
 * Saves the final protein selection and displays it on the analysis page.
 * @param {Array<Object>} proteins - Array of protein objects with name, count, and securedName.
 */
async function saveAndShowFinalSelection(proteins) {
}
// =============================================================================
// SELECTION MODAL (for final ESKAPE results)
// =============================================================================

// Placeholder functions for the new buttons.
// You can add the download and proceed logic here.
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('download-selected-btn')?.addEventListener('click', () => {
        showNotification('Download functionality for selected proteins is not yet implemented.', 'warning');
    });
    document.getElementById('proceed-selected-btn')?.addEventListener('click', () => {
        showNotification('Proceed functionality for selected proteins is not yet implemented.', 'warning');
    });
});

// =============================================================================
// UTILITIES
// =============================================================================

function formatTime(seconds) {
    if (seconds < 60) {
        return Math.round(seconds) + 's';
    } else if (seconds < 3600) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.round(seconds % 60);
        return `${mins}m ${secs}s`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        return `${hours}h ${mins}m`;
    }
}

function closeModal() {
    const modal = document.getElementById('configModal');
    modal.style.display = 'none';
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => notification.classList.add('show'), 10);
    
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 5000);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Inject notification styles
const notificationStyles = `
.notification {
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 15px 25px;
    border-radius: 6px;
    color: white;
    font-weight: 500;
    opacity: 0;
    transform: translateY(-20px);
    transition: all 0.3s;
    z-index: 10000;
    max-width: 400px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.2);
}
.notification.show {
    opacity: 1;
    transform: translateY(0);
}
.notification-success { background: #10b981; }
.notification-error { background: #ef4444; }
.notification-info { background: #3b82f6; }
.notification-warning { background: #f59e0b; }
`;

const styleSheet = document.createElement('style');
styleSheet.textContent = notificationStyles;
document.head.appendChild(styleSheet);
