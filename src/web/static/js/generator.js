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

function _ratingBadgeClass(rating) {
    return rating === 'nsfw' ? 'bg-danger' : 'bg-success';
}

async function addGlobalTarget() {
    const input = document.getElementById('new-gt-username');
    const ratingSelect = document.getElementById('new-gt-rating');
    const username = input.value.trim();
    const rating = ratingSelect ? ratingSelect.value : 'sfw';
    if (!username) return;

    try {
        const resp = await fetch('/generator/global-target/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username: username, content_rating: rating}),
        });
        const data = await resp.json();
        if (data.success) {
            const noMsg = document.getElementById('no-gt-msg');
            if (noMsg) noMsg.remove();

            const cr = data.content_rating || 'sfw';
            const list = document.getElementById('global-targets-list');
            const html = `
                <div class="d-inline-flex align-items-center me-2 mb-2 gt-item" data-gt-id="${data.id}">
                    <span class="badge bg-dark border border-secondary d-flex align-items-center py-2 px-3" style="font-size: 0.9rem;">
                        ${data.username}
                        <span class="badge ms-2 ${_ratingBadgeClass(cr)} gt-rating"
                              style="cursor:pointer; font-size: 0.7rem;"
                              onclick="toggleRating(${data.id}, '${cr}', this)"
                              title="Click to toggle SFW/NSFW">${cr.toUpperCase()}</span>
                        <button type="button" class="btn-close btn-close-white ms-2" style="font-size: 0.6rem;"
                                onclick="deleteGlobalTarget(${data.id}, this)"></button>
                    </span>
                </div>`;
            list.insertAdjacentHTML('beforeend', html);
            input.value = '';

            // Update counter
            const count = document.getElementById('gt-count');
            if (count) count.textContent = list.querySelectorAll('.gt-item').length;

            showToast(`${data.username} added to global pool (${cr.toUpperCase()})`, 'success');
        } else {
            showToast(data.message || 'Failed to add target', 'danger');
        }
    } catch (e) {
        showToast('Failed to add global target', 'danger');
    }
}

async function toggleRating(targetId, currentRating, el) {
    const newRating = currentRating === 'sfw' ? 'nsfw' : 'sfw';
    try {
        const resp = await fetch(`/generator/global-target/${targetId}/rating`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content_rating: newRating}),
        });
        const data = await resp.json();
        if (data.success) {
            el.textContent = newRating.toUpperCase();
            el.className = `badge ms-2 ${_ratingBadgeClass(newRating)} gt-rating`;
            el.setAttribute('onclick', `toggleRating(${targetId}, '${newRating}', this)`);
            showToast(`Target set to ${newRating.toUpperCase()}`, 'success');
        } else {
            showToast(data.message || 'Failed to update rating', 'danger');
        }
    } catch (e) {
        showToast('Failed to update rating', 'danger');
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
