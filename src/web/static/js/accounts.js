// Accounts page - toggle, delete, dynamic form rows

// Toggle account enabled/disabled
async function toggleAccount(el) {
    const name = el.dataset.name;
    try {
        const resp = await fetch(`/accounts/${encodeURIComponent(name)}/toggle`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showToast(data.message, 'success');
        } else {
            showToast(data.message, 'danger');
            el.checked = !el.checked;
        }
    } catch (e) {
        showToast('Failed to toggle account', 'danger');
    }
}

// Delete account with confirmation
function deleteAccount(name) {
    const modal = document.getElementById('deleteModal');
    const nameEl = document.getElementById('delete-name');
    const form = document.getElementById('delete-form');

    if (nameEl) nameEl.textContent = name;
    if (form) form.action = `/accounts/${encodeURIComponent(name)}/delete`;

    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

// Dynamic form rows for targets
let targetCount = document.querySelectorAll('.target-row').length;

function addTarget() {
    const container = document.getElementById('targets-container');
    if (!container) return;

    const idx = targetCount++;
    const html = `
        <div class="row g-2 mb-2 target-row">
            <div class="col-6">
                <input type="text" class="form-control form-control-sm"
                       name="target_${idx}_username" placeholder="@username">
            </div>
            <div class="col-3">
                <input type="number" class="form-control form-control-sm"
                       name="target_${idx}_priority" value="${idx + 1}" placeholder="Priority">
            </div>
            <div class="col-3">
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeRow(this)">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </div>`;
    container.insertAdjacentHTML('beforeend', html);
    reindexRows('targets-container', 'target-row', 'target_');
}

// Dynamic form rows for time windows
let windowCount = document.querySelectorAll('.window-row').length;

function addWindow() {
    const container = document.getElementById('windows-container');
    if (!container) return;

    const idx = windowCount++;
    const html = `
        <div class="row g-2 mb-2 window-row">
            <div class="col-4">
                <input type="text" class="form-control form-control-sm"
                       name="window_${idx}_start" placeholder="HH:MM">
            </div>
            <div class="col-1 text-center pt-1">to</div>
            <div class="col-4">
                <input type="text" class="form-control form-control-sm"
                       name="window_${idx}_end" placeholder="HH:MM">
            </div>
            <div class="col-3">
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeRow(this)">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </div>`;
    container.insertAdjacentHTML('beforeend', html);
    reindexRows('windows-container', 'window-row', 'window_');
}

// Dynamic form rows for simulation time windows
let simWindowCount = document.querySelectorAll('.sim-window-row').length;

function addSimWindow() {
    const container = document.getElementById('sim-windows-container');
    if (!container) return;

    const idx = simWindowCount++;
    const html = `
        <div class="row g-2 mb-2 sim-window-row">
            <div class="col-4">
                <input type="text" class="form-control form-control-sm"
                       name="sim_window_${idx}_start" placeholder="HH:MM">
            </div>
            <div class="col-1 text-center pt-1">to</div>
            <div class="col-4">
                <input type="text" class="form-control form-control-sm"
                       name="sim_window_${idx}_end" placeholder="HH:MM">
            </div>
            <div class="col-3">
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeRow(this)">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </div>`;
    container.insertAdjacentHTML('beforeend', html);
    reindexRows('sim-windows-container', 'sim-window-row', 'sim_window_');
}

// Dynamic form rows for reply time windows
let replyWindowCount = document.querySelectorAll('.reply-window-row').length;

function addReplyWindow() {
    const container = document.getElementById('reply-windows-container');
    if (!container) return;

    const idx = replyWindowCount++;
    const html = `
        <div class="row g-2 mb-2 reply-window-row">
            <div class="col-4">
                <input type="text" class="form-control form-control-sm"
                       name="reply_window_${idx}_start" placeholder="HH:MM">
            </div>
            <div class="col-1 text-center pt-1">to</div>
            <div class="col-4">
                <input type="text" class="form-control form-control-sm"
                       name="reply_window_${idx}_end" placeholder="HH:MM">
            </div>
            <div class="col-3">
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeRow(this)">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </div>`;
    container.insertAdjacentHTML('beforeend', html);
    reindexRows('reply-windows-container', 'reply-window-row', 'reply_window_');
}

function removeRow(btn) {
    const row = btn.closest('.target-row, .window-row, .sim-window-row, .reply-window-row');
    if (row) {
        const container = row.parentElement;
        row.remove();
        // Reindex remaining rows
        if (container.id === 'targets-container') {
            reindexRows('targets-container', 'target-row', 'target_');
        } else if (container.id === 'sim-windows-container') {
            reindexRows('sim-windows-container', 'sim-window-row', 'sim_window_');
        } else if (container.id === 'reply-windows-container') {
            reindexRows('reply-windows-container', 'reply-window-row', 'reply_window_');
        } else {
            reindexRows('windows-container', 'window-row', 'window_');
        }
    }
}

function reindexRows(containerId, rowClass, prefix) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const rows = container.querySelectorAll(`.${rowClass}`);
    rows.forEach((row, i) => {
        const inputs = row.querySelectorAll('input');
        inputs.forEach(input => {
            const oldName = input.name;
            // Replace the index in the name
            const parts = oldName.split('_');
            if (parts.length >= 3) {
                parts[1] = String(i);
                input.name = parts.join('_');
            }
        });
    });

    if (prefix === 'target_') targetCount = rows.length;
    if (prefix === 'window_') windowCount = rows.length;
    if (prefix === 'sim_window_') simWindowCount = rows.length;
    if (prefix === 'reply_window_') replyWindowCount = rows.length;
}
