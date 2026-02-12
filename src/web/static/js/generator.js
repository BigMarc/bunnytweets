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
