// Analytics dashboard — fetch data and render Chart.js charts

const CHART_COLORS = {
    success: 'rgba(40, 167, 69, 0.8)',
    failed: 'rgba(220, 53, 69, 0.8)',
    line_success: 'rgba(40, 167, 69, 1)',
    line_failed: 'rgba(220, 53, 69, 1)',
    bars: [
        'rgba(13, 110, 253, 0.7)',
        'rgba(255, 193, 7, 0.7)',
        'rgba(13, 202, 240, 0.7)',
        'rgba(108, 117, 125, 0.7)',
    ],
};

async function loadAnalytics() {
    try {
        const resp = await fetch('/api/analytics');
        const data = await resp.json();
        renderSuccessChart(data.success_failure);
        renderActivityChart(data.daily_activity);
        renderAccountTable(data.per_account);
        renderRotationChart(data.rotation);
    } catch (e) {
        console.error('Failed to load analytics', e);
    }
}

function renderSuccessChart(sf) {
    const success = sf.success || 0;
    const failed = sf.failed || 0;
    const total = success + failed;
    const ctx = document.getElementById('successChart').getContext('2d');
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Success', 'Failed'],
            datasets: [{
                data: [success, failed],
                backgroundColor: [CHART_COLORS.success, CHART_COLORS.failed],
                borderWidth: 0,
            }],
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: 'bottom', labels: { color: '#ccc' } },
                title: {
                    display: true,
                    text: total > 0 ? `${Math.round(success / total * 100)}% success` : 'No data',
                    color: '#ccc',
                },
            },
        },
    });
}

function renderActivityChart(daily) {
    // Group by day
    const dayMap = {};
    daily.forEach(r => {
        if (!dayMap[r.day]) dayMap[r.day] = { success: 0, failed: 0 };
        dayMap[r.day][r.status] = (dayMap[r.day][r.status] || 0) + r.count;
    });
    const days = Object.keys(dayMap).sort();
    const successData = days.map(d => dayMap[d].success || 0);
    const failedData = days.map(d => dayMap[d].failed || 0);
    const labels = days.map(d => d.slice(5)); // MM-DD

    const ctx = document.getElementById('activityChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Success',
                    data: successData,
                    borderColor: CHART_COLORS.line_success,
                    backgroundColor: 'rgba(40, 167, 69, 0.1)',
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: 'Failed',
                    data: failedData,
                    borderColor: CHART_COLORS.line_failed,
                    backgroundColor: 'rgba(220, 53, 69, 0.1)',
                    fill: true,
                    tension: 0.3,
                },
            ],
        },
        options: {
            responsive: true,
            scales: {
                x: { ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { beginAtZero: true, ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,0.05)' } },
            },
            plugins: {
                legend: { labels: { color: '#ccc' } },
            },
        },
    });
}

function renderAccountTable(perAccount) {
    const body = document.getElementById('accountStatsBody');
    if (!perAccount.length) {
        body.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No data yet</td></tr>';
        return;
    }

    // Aggregate by account
    const acctMap = {};
    perAccount.forEach(r => {
        if (!acctMap[r.account]) {
            acctMap[r.account] = { post: 0, retweet: 0, reply: 0, simulation: 0, failed: 0 };
        }
        if (r.status === 'failed') {
            acctMap[r.account].failed += r.count;
        } else {
            const key = r.task_type === 'post' ? 'post'
                : r.task_type === 'retweet' ? 'retweet'
                : r.task_type === 'reply' ? 'reply'
                : r.task_type === 'simulation' ? 'simulation'
                : 'post';
            acctMap[r.account][key] += r.count;
        }
    });

    let html = '';
    Object.entries(acctMap).forEach(([name, s]) => {
        html += `<tr>
            <td>${name}</td>
            <td>${s.post}</td>
            <td>${s.retweet}</td>
            <td>${s.reply}</td>
            <td>${s.simulation}</td>
            <td class="text-danger">${s.failed}</td>
        </tr>`;
    });
    body.innerHTML = html;
}

function renderRotationChart(rotation) {
    const ctx = document.getElementById('rotationChart').getContext('2d');
    if (!rotation.length) {
        new Chart(ctx, {
            type: 'bar',
            data: { labels: ['No data'], datasets: [{ data: [0] }] },
            options: { responsive: true },
        });
        return;
    }

    // Group by account
    const acctMap = {};
    rotation.forEach(r => {
        if (!acctMap[r.account]) acctMap[r.account] = {};
        acctMap[r.account][r.use_count] = r.files;
    });

    const accounts = Object.keys(acctMap);
    const maxUse = Math.max(...rotation.map(r => r.use_count), 0);
    const labels = [];
    for (let i = 0; i <= Math.min(maxUse, 10); i++) labels.push(`${i}x used`);

    const datasets = accounts.map((acct, i) => ({
        label: acct,
        data: labels.map((_, idx) => acctMap[acct][idx] || 0),
        backgroundColor: CHART_COLORS.bars[i % CHART_COLORS.bars.length],
    }));

    new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets },
        options: {
            responsive: true,
            scales: {
                x: { ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { beginAtZero: true, ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,0.05)' } },
            },
            plugins: {
                legend: { labels: { color: '#ccc' } },
            },
        },
    });
}

// Load on page ready
loadAnalytics();
