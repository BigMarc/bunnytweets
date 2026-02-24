// Dashboard - Status polling and action handlers

let pollInterval = null;
let _lastEngineStatus = null;  // Track status transitions

async function fetchStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        updateDashboard(data);
    } catch (e) {
        console.error('Status poll failed:', e);
    }
}

function updateDashboard(data) {
    // Update engine status indicator (navbar badge)
    updateEngineIndicator(data.engine_status);

    // Update engine status text and Start/Stop button
    updateEngineControls(data);

    // Update stats
    const statsJobs = document.getElementById('stat-jobs');
    if (statsJobs) statsJobs.textContent = data.jobs_count || 0;

    const statsQueue = document.getElementById('stat-queue');
    if (statsQueue) statsQueue.textContent = data.queue ? data.queue.size : 0;

    // Update account cards (badges, timestamps, error messages, AND buttons)
    if (data.accounts) {
        for (const acct of data.accounts) {
            updateAccountCard(acct, data.engine_running);
        }
    }

    _lastEngineStatus = data.engine_status;
}

// Dynamically swap the engine Start/Stop button and status text
// without requiring a page reload.
function updateEngineControls(data) {
    const statusText = document.getElementById('engine-status-text');
    if (statusText) {
        const colors = {
            'running': 'text-success',
            'starting': 'text-warning',
            'stopping': 'text-warning',
            'stopped': 'text-secondary',
        };
        const color = colors[data.engine_status] || 'text-secondary';
        const label = data.engine_status.charAt(0).toUpperCase() + data.engine_status.slice(1);
        statusText.innerHTML = `<span class="${color}">${label}</span>`;
        if (data.startup_error) {
            const errDiv = document.createElement('div');
            errDiv.className = 'text-danger mt-1';
            const errSmall = document.createElement('small');
            errSmall.textContent = 'Error: ' + data.startup_error;
            errDiv.appendChild(errSmall);
            statusText.appendChild(errDiv);
        }
    }

    // Swap the Start/Stop button based on current engine state
    const controls = document.getElementById('engine-controls');
    if (controls) {
        if (data.engine_status === 'running') {
            controls.innerHTML =
                '<button class="btn btn-danger" onclick="stopEngine()">' +
                '<i class="bi bi-stop-fill me-1"></i>Stop Engine</button>';
        } else if (data.engine_status === 'starting' || data.engine_status === 'stopping') {
            controls.innerHTML =
                '<button class="btn btn-secondary" disabled>' +
                '<i class="bi bi-hourglass-split me-1"></i>' +
                (data.engine_status === 'starting' ? 'Starting...' : 'Stopping...') +
                '</button>';
        } else {
            controls.innerHTML =
                '<button class="btn btn-success" onclick="startEngine()">' +
                '<i class="bi bi-play-fill me-1"></i>Start Engine</button>';
        }
    }
}

function updateAccountCard(acct, engineRunning) {
    const name = acct.name;

    // Status badge
    const badgeEl = document.querySelector(`.status-badge-${CSS.escape(name)}`);
    if (badgeEl) {
        const badges = {
            'running': '<span class="badge bg-primary">Running</span>',
            'browsing': '<span class="badge bg-info">Browsing</span>',
            'error': '<span class="badge bg-danger">Error</span>',
            'paused': '<span class="badge bg-warning text-dark">Paused</span>',
            'idle': '<span class="badge bg-success">Idle</span>',
        };
        badgeEl.innerHTML = badges[acct.status] || badges['idle'];
    }

    // Last post
    const postEl = document.querySelector(`.last-post-${CSS.escape(name)}`);
    if (postEl) {
        postEl.textContent = acct.last_post ? formatDate(acct.last_post) : 'Never';
    }

    // Last retweet
    const rtEl = document.querySelector(`.last-rt-${CSS.escape(name)}`);
    if (rtEl) {
        rtEl.textContent = acct.last_retweet ? formatDate(acct.last_retweet) : 'Never';
    }

    // Retweet count
    const countEl = document.querySelector(`.rt-count-${CSS.escape(name)}`);
    if (countEl) {
        countEl.textContent = `${acct.retweets_today}/${acct.retweet_limit}`;
    }

    // Error message
    const errEl = document.querySelector(`.error-msg-${CSS.escape(name)}`);
    if (errEl) {
        if (acct.error_message) {
            errEl.textContent = acct.error_message;
            errEl.style.display = '';
        } else {
            errEl.style.display = 'none';
        }
    }

    // Dynamically enable/disable action buttons based on engine state
    // AND per-account status (disable if error or paused).
    const accountDisabled = !engineRunning || acct.status === 'error' || acct.status === 'paused';
    const buttons = document.querySelectorAll(`button[data-account="${CSS.escape(name)}"]`);
    buttons.forEach(btn => {
        btn.disabled = accountDisabled;
    });
}

function formatDate(isoStr) {
    try {
        const d = new Date(isoStr);
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const hours = String(d.getHours()).padStart(2, '0');
        const mins = String(d.getMinutes()).padStart(2, '0');
        return `${month}/${day} ${hours}:${mins}`;
    } catch (e) {
        return isoStr;
    }
}

// Engine controls — no page reload; polling handles UI updates
async function startEngine() {
    try {
        const resp = await fetch('/api/actions/engine/start', { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'danger');
        // Immediately poll to reflect the new "starting" state
        if (data.success) fetchStatus();
    } catch (e) {
        showToast('Failed to start engine', 'danger');
    }
}

async function stopEngine() {
    try {
        const resp = await fetch('/api/actions/engine/stop', { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'danger');
        if (data.success) fetchStatus();
    } catch (e) {
        showToast('Failed to stop engine', 'danger');
    }
}

// Manual triggers
async function triggerPost(accountName) {
    try {
        const resp = await fetch(`/api/actions/account/${encodeURIComponent(accountName)}/post`, { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'warning');
    } catch (e) {
        showToast('Failed to trigger post', 'danger');
    }
}

async function triggerRetweet(accountName) {
    try {
        const resp = await fetch(`/api/actions/account/${encodeURIComponent(accountName)}/retweet`, { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'warning');
    } catch (e) {
        showToast('Failed to trigger retweet', 'danger');
    }
}

async function triggerSimulation(accountName) {
    try {
        const resp = await fetch(`/api/actions/account/${encodeURIComponent(accountName)}/simulate`, { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'warning');
    } catch (e) {
        showToast('Failed to trigger simulation', 'danger');
    }
}

// Start polling
fetchStatus();
pollInterval = setInterval(fetchStatus, 5000);
