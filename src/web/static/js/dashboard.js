// Dashboard - Status polling and action handlers

let pollInterval = null;

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
    // Update engine status
    updateEngineIndicator(data.engine_status);

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
            statusText.innerHTML += `<div class="text-danger mt-1"><small>Error: ${data.startup_error}</small></div>`;
        }
    }

    // Update stats
    const statsJobs = document.getElementById('stat-jobs');
    if (statsJobs) statsJobs.textContent = data.jobs_count || 0;

    const statsQueue = document.getElementById('stat-queue');
    if (statsQueue) statsQueue.textContent = data.queue ? data.queue.size : 0;

    // Update account cards
    if (data.accounts) {
        for (const acct of data.accounts) {
            updateAccountCard(acct);
        }
    }
}

function updateAccountCard(acct) {
    const name = acct.name;

    // Status badge
    const badgeEl = document.querySelector(`.status-badge-${name}`);
    if (badgeEl) {
        const badges = {
            'running': '<span class="badge bg-primary">Running</span>',
            'error': '<span class="badge bg-danger">Error</span>',
            'paused': '<span class="badge bg-warning text-dark">Paused</span>',
            'idle': '<span class="badge bg-success">Idle</span>',
        };
        badgeEl.innerHTML = badges[acct.status] || badges['idle'];
    }

    // Last post
    const postEl = document.querySelector(`.last-post-${name}`);
    if (postEl) {
        postEl.textContent = acct.last_post ? formatDate(acct.last_post) : 'Never';
    }

    // Last retweet
    const rtEl = document.querySelector(`.last-rt-${name}`);
    if (rtEl) {
        rtEl.textContent = acct.last_retweet ? formatDate(acct.last_retweet) : 'Never';
    }

    // Retweet count
    const countEl = document.querySelector(`.rt-count-${name}`);
    if (countEl) {
        countEl.textContent = `${acct.retweets_today}/${acct.retweet_limit}`;
    }

    // Error message
    const errEl = document.querySelector(`.error-msg-${name}`);
    if (errEl) {
        if (acct.error_message) {
            errEl.textContent = acct.error_message;
            errEl.style.display = '';
        } else {
            errEl.style.display = 'none';
        }
    }
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

// Engine controls
async function startEngine() {
    try {
        const resp = await fetch('/api/actions/engine/start', { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'danger');
        if (data.success) {
            setTimeout(() => location.reload(), 2000);
        }
    } catch (e) {
        showToast('Failed to start engine', 'danger');
    }
}

async function stopEngine() {
    try {
        const resp = await fetch('/api/actions/engine/stop', { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'danger');
        if (data.success) {
            setTimeout(() => location.reload(), 2000);
        }
    } catch (e) {
        showToast('Failed to stop engine', 'danger');
    }
}

// Manual triggers
async function triggerPost(accountName) {
    try {
        const resp = await fetch(`/api/actions/account/${accountName}/post`, { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'warning');
    } catch (e) {
        showToast('Failed to trigger post', 'danger');
    }
}

async function triggerRetweet(accountName) {
    try {
        const resp = await fetch(`/api/actions/account/${accountName}/retweet`, { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'warning');
    } catch (e) {
        showToast('Failed to trigger retweet', 'danger');
    }
}

// Start polling
fetchStatus();
pollInterval = setInterval(fetchStatus, 5000);
