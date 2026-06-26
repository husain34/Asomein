// Clock
setInterval(() => {
    document.getElementById('clock').innerText = new Date().toLocaleTimeString('en-US', {hour12: false});
}, 1000);

// --- Animation Utils ---
function animateCount(el, from, to, duration, suffix='') {
    const start = performance.now();
    function frame(now) {
        const p = Math.min((now - start) / duration, 1);
        const ease = p < 0.5 ? 2*p*p : -1+(4-2*p)*p;
        el.textContent = Math.round(from + (to - from) * ease) + suffix;
        if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
}

// --- Chart Config ---
function createSparkline(canvasId, color, seedValue, yMin, yMax) {
    const data = Array.from({ length: 30 }, () =>
        seedValue + Math.floor((Math.random() - 0.5) * 10)
    );
    return new Chart(document.getElementById(canvasId), {
        type: 'line',
        data: {
            labels: data.map((_, i) => i),
            datasets: [{
                data,
                borderColor: color,
                borderWidth: 1.5,
                pointRadius: 0,
                fill: true,
                backgroundColor: color + '18',
                tension: 0.45,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
                x: { display: false },
                y: { display: false, min: yMin, max: yMax },
            },
        },
    });
}

const throughputChart = createSparkline('chart-throughput', '#1d4ed8', 22, 0, 50);
const latencyChart    = createSparkline('chart-latency',    '#7c3aed', 300, 0, 600);
const successChart    = createSparkline('chart-success',    '#22c55e', 95,  0, 100);

function pushPoint(chart, value) {
    chart.data.labels.push(chart.data.labels.length);
    chart.data.labels.shift();
    chart.data.datasets[0].data.push(value);
    chart.data.datasets[0].data.shift();
    chart.update('none'); 
}

// --- Global State ---
let lastLogTimestamp = null;
let lastSuccessVal = 0;
let lastTasksVal = 0;
let lastTpmVal = 0;
let nextTaskEpoch = 0;

// Countdown logic
const cdEl = document.getElementById('countdown-val');
setInterval(() => {
    if (!nextTaskEpoch) return;
    const now = Math.floor(Date.now() / 1000);
    const diff = nextTaskEpoch - now;
    
    if (diff <= 0) {
        cdEl.textContent = "00:00";
        if (diff === 0) {
            cdEl.style.color = '#7c3aed';
            cdEl.style.opacity = '0.4';
            setTimeout(() => { cdEl.style.opacity = '1'; }, 500);
        }
        return;
    }
    const m = Math.floor(diff / 60).toString().padStart(2, '0');
    const s = (diff % 60).toString().padStart(2, '0');
    cdEl.textContent = `${m}:${s}`;
    cdEl.style.color = '#7c3aed';
}, 1000);

// Format Time helper
function formatTime(sec) {
    const h = Math.floor(sec / 3600).toString().padStart(2, '0');
    const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
    const s = (sec % 60).toString().padStart(2, '0');
    return `${h}:${m}:${s}`;
}

// --- Fetch & Update ---
function pollStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            const orbEl = document.getElementById('status-orb');
            const statusEl = document.getElementById('status-text');
            
            const stateMap = {
                running: { label: 'AUTONOMOUS', color: '#22c55e' },
                idle:    { label: 'IDLE',       color: '#d97706' },
                error:   { label: 'ERROR',      color: '#ef4444' },
                paused:  { label: 'PAUSED',     color: '#6b7280' },
            };
            const s = stateMap[data.agent_state] || stateMap.idle;
            orbEl.style.background = s.color;
            statusEl.textContent = s.label;
            statusEl.style.color = s.color;

            // Header stats
            document.getElementById('val-uptime').textContent = formatTime(data.uptime_seconds);
            document.getElementById('val-latency').textContent = data.latency_ms + 'ms';
            
            if (data.tasks_completed !== lastTasksVal) {
                animateCount(document.getElementById('val-tasks'), lastTasksVal, data.tasks_completed, 800);
                lastTasksVal = data.tasks_completed;
            }
            if (data.tokens_per_min !== lastTpmVal) {
                animateCount(document.getElementById('val-tpm'), lastTpmVal, data.tokens_per_min, 800);
                lastTpmVal = data.tokens_per_min;
            }

            // Left Col - Metrics
            if (data.success_rate !== lastSuccessVal) {
                animateCount(document.getElementById('val-success'), lastSuccessVal, data.success_rate, 800, '%');
                lastSuccessVal = data.success_rate;
            }
            
            document.getElementById('bar-cpu').style.width = data.cpu_pct + '%';
            document.getElementById('pct-cpu').textContent = Math.round(data.cpu_pct) + '%';
            document.getElementById('bar-mem').style.width = data.memory_pct + '%';
            document.getElementById('pct-mem').textContent = Math.round(data.memory_pct) + '%';
            document.getElementById('bar-tok').style.width = data.token_ctx_pct + '%';
            document.getElementById('pct-tok').textContent = Math.round(data.token_ctx_pct) + '%';

            // Left Col - Schedule
            nextTaskEpoch = data.next_task_epoch;
            document.getElementById('next-task-name').textContent = data.next_task_name;
            
            const tlContainer = document.getElementById('schedule-timeline');
            tlContainer.innerHTML = '';
            data.schedule.forEach(item => {
                const row = document.createElement('div');
                row.className = 'tl-item';
                const dotClass = item.status === 'done' ? 's-done' : (item.status === 'next' ? 's-next' : '');
                row.innerHTML = `<div class="tl-dot ${dotClass}"></div><div class="tl-time">${item.time}</div><div class="tl-name">${item.name}</div>`;
                tlContainer.appendChild(row);
            });

            // Left Col - Rules
            const rulesList = document.getElementById('rules-list');
            rulesList.innerHTML = '';
            data.active_rules.forEach(rule => {
                const badgeClass = rule.active ? 'badge-on' : 'badge-off';
                const badgeText = rule.active ? 'ON' : 'OFF';
                rulesList.innerHTML += `<div class="rule-row"><span class="rule-name">${rule.name}</span><span class="rule-badge ${badgeClass}">${badgeText}</span></div>`;
            });

            // Right Col - Personality & Config
            const traitsList = document.getElementById('traits-list');
            traitsList.innerHTML = '';
            for (const [trait, val] of Object.entries(data.personality)) {
                traitsList.innerHTML += `<div class="trait-row"><span class="trait-lbl">${trait}</span><div class="trait-track"><div class="trait-fill" style="width: ${Math.min(val * 100, 100)}%"></div></div><span class="trait-val">${val.toFixed(1)}</span></div>`;
            }
            document.getElementById('conf-model').textContent = data.model;
            document.getElementById('conf-mode').textContent = data.mode;
            document.getElementById('conf-budget').textContent = `FREE`;

            // Right Col - Memory
            const maxContext = 128000;
            const currentContext = data.working_memory * 50; // Approx 50 tokens per node to fit UI
            const ctxPct = Math.min((currentContext / maxContext) * 100, 100);
            document.getElementById('bar-ctx').style.width = ctxPct + '%';
            document.getElementById('bar-tok').style.width = ctxPct + '%';
            document.getElementById('pct-tok').textContent = Math.round(ctxPct) + '%';
            document.getElementById('val-ctx').textContent = `${currentContext.toLocaleString()} / ${maxContext.toLocaleString()} tokens`;
            document.getElementById('val-workmem').textContent = data.working_memory;
            document.getElementById('val-lastgoal').textContent = data.last_goal_done;
            document.getElementById('val-dbnodes').textContent = data.db_nodes;
            document.getElementById('val-embeddings').textContent = data.embeddings;
            document.getElementById('val-pruned').textContent = data.pruned_tokens;

            // Center Col - Logs
            const feed = document.getElementById('neural-feed');
            data.recent_logs.forEach(log => {
                if (lastLogTimestamp && log.ts <= lastLogTimestamp) return;
                
                const row = document.createElement('div');
                row.className = 'log-entry';
                
                let lvlClass = 'lvl-info';
                if (log.level === 'WARN') { lvlClass = 'lvl-warn'; row.classList.add('bg-warn'); }
                if (log.level === 'ERR') { lvlClass = 'lvl-err'; row.classList.add('bg-err'); }
                if (log.level === 'ACT') lvlClass = 'lvl-act';
                if (log.level === 'OK') lvlClass = 'lvl-ok';

                row.innerHTML = `<span class="log-time">${log.ts.split('T')[1]?.substring(0,8) || log.ts}</span>
                                 <span class="log-lvl ${lvlClass}">${log.level}</span>
                                 <span class="log-agent">${log.agent}</span>
                                 <span class="log-msg">${log.msg}</span>`;
                feed.appendChild(row);
                lastLogTimestamp = log.ts;
                
                // Truncate to 100
                if (feed.children.length > 100) {
                    feed.removeChild(feed.firstChild);
                }
            });
            feed.scrollTop = feed.scrollHeight;

            // Center Col - Errors
            const errList = document.getElementById('errors-list');
            errList.innerHTML = '';
            if (data.errors.length === 0) {
                errList.innerHTML = '<div style="color:var(--text-muted); padding:20px; text-align:center; font-style:italic;">[ SYSTEM NOMINAL — ZERO ERRORS DETECTED ]</div>';
            } else {
                data.errors.forEach(err => {
                    const warnCls = err.level === 'WARN' ? 'warn' : '';
                    errList.innerHTML += `<div class="err-item ${warnCls}">
                        <div class="err-msg">${err.msg}</div>
                        <div class="err-sub">recently · ${err.agent}</div>
                    </div>`;
                });
            }

            // Update Charts
            pushPoint(throughputChart, data.tokens_per_min / 100);
            pushPoint(latencyChart, data.latency_ms);
            pushPoint(successChart, data.success_rate);

            // API Connections Panel
            if (data.api_health) {
                updateApiHealth('nvidia', data.api_health.nvidia);
                updateApiHealth('bluesky', data.api_health.bluesky);
            }

        })
        .catch(() => {
            const orbEl = document.getElementById('status-orb');
            const statusEl = document.getElementById('status-text');
            statusEl.textContent = 'OFFLINE';
            statusEl.style.color = '#ef4444';
            orbEl.style.background = '#ef4444';
        });
}

// --- API Health Panel Updater ---
const STATUS_LABELS = {
    online:      'ONLINE',
    offline:     'OFFLINE',
    checking:    'CHECKING…',
    invalid_key: 'INVALID KEY',
    no_key:      'NO KEY SET',
    error:       'ERROR',
};

function updateApiHealth(service, info) {
    if (!info) return;
    const status = info.status || 'checking';
    const dot    = document.getElementById(`dot-${service}`);
    const txt    = document.getElementById(`status-${service}`);
    const lat    = document.getElementById(`latency-${service}`);
    const lastEl = document.getElementById('api-last-checked');

    // Update dot class
    dot.className = `api-dot ${status}`;

    // Update status text + class for color
    txt.textContent = STATUS_LABELS[status] || status.toUpperCase();
    txt.className   = `api-status-text ${status}`;

    // Latency
    if (info.latency_ms != null) {
        lat.textContent = `${info.latency_ms}ms`;
    } else {
        lat.textContent = '';
    }

    // Last checked timestamp (shared line at the bottom)
    if (info.last_checked) {
        const d = new Date(info.last_checked);
        lastEl.textContent = `last checked: ${d.toLocaleTimeString('en-US', {hour12: false})}`;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    pollStatus();
    setInterval(pollStatus, 2000);
});
