// Generator page - category & title CRUD

async function deleteCategory(catId, catName) {
    if (!confirm(`Delete category "${catName}" and ALL its titles?`)) return;
    try {
        const resp = await fetch(`/generator/category/${catId}/delete`, { method: 'POST' });
        const data = await resp.json();
        showToast(data.message, data.success ? 'success' : 'danger');
        if (data.success) {
            setTimeout(() => location.reload(), 500);
        }
    } catch (e) {
        showToast('Failed to delete category', 'danger');
    }
}

async function deleteTitle(titleId, btn) {
    try {
        const resp = await fetch(`/generator/title/${titleId}/delete`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            // Remove the list item from DOM
            const item = btn.closest('.list-group-item');
            if (item) item.remove();
            showToast('Title deleted', 'success');
        } else {
            showToast(data.message, 'danger');
        }
    } catch (e) {
        showToast('Failed to delete title', 'danger');
    }
}


// ----- Global Target Accounts -----

async function addGlobalTarget() {
    const input = document.getElementById('new-gt-username');
    const username = input.value.trim();
    if (!username) return;

    try {
        const resp = await fetch('/generator/global-target/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username: username}),
        });
        const data = await resp.json();
        if (data.success) {
            const noMsg = document.getElementById('no-gt-msg');
            if (noMsg) noMsg.remove();

            const list = document.getElementById('global-targets-list');
            const html = `
                <div class="d-inline-flex align-items-center me-2 mb-2 gt-item" data-gt-id="${data.id}">
                    <span class="badge bg-dark border border-secondary d-flex align-items-center py-2 px-3" style="font-size: 0.9rem;">
                        ${data.username}
                        <button type="button" class="btn-close btn-close-white ms-2" style="font-size: 0.6rem;"
                                onclick="deleteGlobalTarget(${data.id}, this)"></button>
                    </span>
                </div>`;
            list.insertAdjacentHTML('beforeend', html);
            input.value = '';

            // Update counter
            const count = document.getElementById('gt-count');
            if (count) count.textContent = list.querySelectorAll('.gt-item').length;

            showToast(`${data.username} added to global pool`, 'success');
        } else {
            showToast(data.message || 'Failed to add target', 'danger');
        }
    } catch (e) {
        showToast('Failed to add global target', 'danger');
    }
}

async function deleteGlobalTarget(targetId, btn) {
    try {
        const resp = await fetch(`/generator/global-target/${targetId}/delete`, {
            method: 'POST',
        });
        const data = await resp.json();
        if (data.success) {
            const item = btn.closest('.gt-item');
            if (item) item.remove();

            const list = document.getElementById('global-targets-list');
            const count = document.getElementById('gt-count');
            if (count) count.textContent = list.querySelectorAll('.gt-item').length;

            showToast('Target removed', 'success');
        } else {
            showToast(data.message || 'Failed to remove target', 'danger');
        }
    } catch (e) {
        showToast('Failed to remove global target', 'danger');
    }
}
