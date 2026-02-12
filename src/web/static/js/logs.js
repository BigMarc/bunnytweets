// Log viewer - file selection, tailing, and search

let currentOffset = 0;
let tailInterval = null;
let autoScroll = true;

const logContent = document.getElementById('log-content');
const fileSelect = document.getElementById('log-file-select');
const searchInput = document.getElementById('log-search');
const autoScrollToggle = document.getElementById('auto-scroll');

// File selection
if (fileSelect) {
    fileSelect.addEventListener('change', () => {
        loadLog(fileSelect.value);
    });
}

// Auto-scroll toggle
if (autoScrollToggle) {
    autoScrollToggle.addEventListener('change', () => {
        autoScroll = autoScrollToggle.checked;
        if (autoScroll) scrollToBottom();
    });
}

// Search/filter
if (searchInput) {
    let searchTimeout;
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => highlightSearch(searchInput.value), 300);
    });
}

async function loadLog(filename) {
    if (!filename) return;

    // Stop existing tail
    if (tailInterval) {
        clearInterval(tailInterval);
        tailInterval = null;
    }

    try {
        const resp = await fetch(`/logs/api/tail?file=${encodeURIComponent(filename)}&lines=200`);
        const data = await resp.json();

        if (data.error) {
            logContent.textContent = `Error: ${data.error}`;
            return;
        }

        logContent.textContent = data.content || '(empty log file)';
        currentOffset = data.offset || 0;

        if (autoScroll) scrollToBottom();

        // Re-apply search highlight
        if (searchInput && searchInput.value) {
            highlightSearch(searchInput.value);
        }

        // Start tailing
        tailInterval = setInterval(() => tailLog(filename), 2000);
    } catch (e) {
        logContent.textContent = `Failed to load log: ${e.message}`;
    }
}

async function tailLog(filename) {
    try {
        const resp = await fetch(
            `/logs/api/tail?file=${encodeURIComponent(filename)}&offset=${currentOffset}`
        );
        const data = await resp.json();

        if (data.error) return;

        if (data.content && data.offset > currentOffset) {
            // Append new content
            logContent.textContent += data.content;
            currentOffset = data.offset;

            if (autoScroll) scrollToBottom();

            // Re-apply search highlight if active
            if (searchInput && searchInput.value) {
                highlightSearch(searchInput.value);
            }
        }
    } catch (e) {
        // Silent fail on tail - will retry
    }
}

function scrollToBottom() {
    if (logContent) {
        logContent.scrollTop = logContent.scrollHeight;
    }
}

function highlightSearch(query) {
    if (!logContent) return;

    // Get raw text (remove any existing marks)
    const text = logContent.textContent;

    if (!query || query.length < 2) {
        logContent.textContent = text;
        return;
    }

    // Escape regex special chars
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escaped})`, 'gi');

    // Use innerHTML with escaped text + marks
    const safeText = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    logContent.innerHTML = safeText.replace(regex, '<mark>$1</mark>');
}

// Initial load if a file is selected
if (fileSelect && fileSelect.value) {
    // Content is already rendered server-side, just set up tailing
    currentOffset = 0;
    // Fetch current offset
    fetch(`/logs/api/tail?file=${encodeURIComponent(fileSelect.value)}&lines=0&offset=0`)
        .then(r => r.json())
        .then(data => {
            currentOffset = data.size || 0;
            tailInterval = setInterval(() => tailLog(fileSelect.value), 2000);
        })
        .catch(() => {});

    if (autoScroll) scrollToBottom();
}
