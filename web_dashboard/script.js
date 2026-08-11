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
                backgroundColor: color + '14', // 0.08 opacity (hex 14)
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

const throughputChart = createSparkline('chart-throughput', '#00e5ff', 22, -2, 50); // cyan
const latencyChart    = createSparkline('chart-latency',    '#ffab40', 300, -10, 600); // amber
const successChart    = createSparkline('chart-success',    '#00e676', 95,  -5, 100); // green

function pushPoint(chart, value) {
    chart.data.labels.push('');
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
            cdEl.style.color = '#00e5ff';
            cdEl.style.opacity = '0.4';
            setTimeout(() => { cdEl.style.opacity = '1'; }, 500);
        }
        return;
    }
    const m = Math.floor(diff / 60).toString().padStart(2, '0');
    const s = (diff % 60).toString().padStart(2, '0');
    cdEl.textContent = `${m}:${s}`;
    cdEl.style.color = '#00e5ff';
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
                running: { label: 'AUTONOMOUS', color: '#00e676' },
                idle:    { label: 'IDLE',       color: '#ffab40' },
                error:   { label: 'ERROR',      color: '#ff5252' },
                paused:  { label: 'PAUSED',     color: '#00e5ff' }, // cyan
            };
            const s = stateMap[data.agent_state] || stateMap.idle;
            orbEl.style.backgroundColor = s.color;
            orbEl.style.boxShadow = `0 0 10px ${s.color}`;
            statusEl.textContent = s.label;
            statusEl.style.color = s.color;

            // Header stats
            document.getElementById('val-uptime').textContent = formatTime(data.uptime_seconds);
            document.getElementById('val-latency').textContent = data.latency_ms;
            
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
                animateCount(document.getElementById('val-success'), lastSuccessVal, data.success_rate, 800);
                lastSuccessVal = data.success_rate;
            }
            const ring = document.getElementById('ring-success'); 
            if(ring) ring.style.strokeDashoffset = 339.3 * (1 - data.success_rate/100);
            
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
                let dotClass = '';
                let iconChar = '○';
                if (item.status === 'done') { dotClass = 's-done'; iconChar = '✓'; }
                else if (item.status === 'next') { dotClass = 's-next'; iconChar = '●'; }
                else { dotClass = 's-wait'; }
                row.innerHTML = `<span class="tl-icon ${dotClass}">${iconChar}</span><span class="tl-time mono">${item.time}</span><span class="tl-name">${item.name}</span>`;
                tlContainer.appendChild(row);
            });

            // Left Col - Rules
            const rulesList = document.getElementById('rules-list');
            rulesList.innerHTML = '';
            data.active_rules.forEach(rule => {
                const badgeClass = rule.active ? 'on' : 'off';
                const badgeText = rule.active ? 'ON' : 'OFF';
                rulesList.innerHTML += `<div class="rule-row"><span class="rule-icon">${rule.active ? '✓' : '○'}</span><span class="rule-name">${rule.name}</span><span class="rule-badge ${badgeClass}">${badgeText}</span></div>`;
            });

            // Right Col - Personality & Config
            const traitsList = document.getElementById('traits-list');
            traitsList.innerHTML = '';
            for (const [trait, val] of Object.entries(data.personality)) {
                traitsList.innerHTML += `<div class="trait-row"><span class="trait-lbl">${trait}</span><div class="trait-track"><div class="trait-fill" style="width: ${Math.min(val * 100, 100)}%"></div></div><span class="trait-val mono">${val.toFixed(2)}</span></div>`;
            }
            document.getElementById('conf-model').textContent = data.model;
            document.getElementById('conf-mode').textContent = data.mode;
            document.getElementById('conf-budget').textContent = `FREE`;

            // Right Col - Memory
            const maxContext = 128000;
            const currentContext = data.working_memory * 35;
            const ctxPct = Math.min((currentContext / maxContext) * 100, 100);
            document.getElementById('bar-ctx').style.width = ctxPct + '%';
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
                row.className = 'log-row';
                
                let lvlClass = 'info';
                if (log.level === 'WARN') { lvlClass = 'warn'; }
                if (log.level === 'ERR' || log.level === 'ERROR') { lvlClass = 'error'; }

                row.innerHTML = `<span class="log-time">${log.ts.split('T')[1]?.substring(0,8) || log.ts}</span><span class="log-lvl ${lvlClass}">${log.level}</span><span class="log-agent">${log.agent}</span><span class="log-msg">${log.msg}</span>`;
                feed.appendChild(row);
                lastLogTimestamp = log.ts;
                
                if (feed.children.length > 100) {
                    feed.removeChild(feed.firstChild);
                }
            });
            feed.scrollTop = feed.scrollHeight;

            // Center Col - Errors
            const errList = document.getElementById('errors-list');
            errList.innerHTML = '';
            if (data.errors.length === 0) {
                errList.innerHTML = '<div style="color:var(--muted); padding:20px; text-align:center; font-style:italic; font-size:11px;">[ SYSTEM NOMINAL — ZERO ERRORS DETECTED ]</div>';
            } else {
                data.errors.forEach(err => {
                    const warnCls = err.level === 'WARN' ? 'warn-level' : '';
                    errList.innerHTML += `<div class="err-item ${warnCls}"><span class="err-icon">${err.level === 'WARN' ? '▲' : '✕'}</span><div class="err-body"><div class="err-msg">${err.msg}</div><div class="err-sub">${err.agent}</div></div></div>`;
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
            statusEl.style.color = '#ff5252';
            orbEl.style.backgroundColor = '#ff5252';
            orbEl.style.boxShadow = '0 0 10px #ff5252';
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

const STATUS_ICONS = {
    online:      '✓',
    offline:     '✕',
    checking:    '⟳',
    invalid_key: '▲',
    no_key:      '◎',
    error:       '✕',
};

function updateApiHealth(service, info) {
    if (!info) return;
    const status = info.status || 'checking';
    const dot    = document.getElementById(`dot-${service}`);
    const txt    = document.getElementById(`status-${service}`);
    const lat    = document.getElementById(`latency-${service}`);
    const lastEl = document.getElementById('api-last-checked');

    dot.textContent = STATUS_ICONS[status] || '◎';
    dot.className = `api-status-icon status-${status}`;

    txt.textContent = STATUS_LABELS[status] || status.toUpperCase();
    txt.className   = `api-status-text status-${status}`;

    if (info.latency_ms != null) {
        lat.textContent = `${info.latency_ms}ms`;
    } else {
        lat.textContent = '--ms';
    }

    if (info.last_checked) {
        const d = new Date(info.last_checked);
        lastEl.textContent = d.toLocaleTimeString('en-US', {hour12: false});
    }
}

document.addEventListener("DOMContentLoaded", () => {
    pollStatus();
    setInterval(updateSchedule, 1000);
});

// Initialize Background Grid
function initInteractiveBg() {
    const bg = document.getElementById('interactive-bg');
    if (!bg) return;
    
    let debounceTimer;
    let cols = 0;
    let rows = 0;
    let tiles = [];
    let lastHovered = null;

    const fillGrid = () => {
        bg.innerHTML = '';
        tiles = [];
        cols = Math.ceil(window.innerWidth / 48);
        rows = Math.ceil(window.innerHeight / 48);
        const total = cols * rows;
        if(total > 2500) return; 
        
        bg.style.gridTemplateColumns = `repeat(${cols}, 48px)`;
        bg.style.gridAutoRows = '48px';
        
        const frag = document.createDocumentFragment();
        for (let i = 0; i < total; i++) {
            const tile = document.createElement('div');
            tile.className = 'interactive-bg-tile';
            tiles.push(tile);
            frag.appendChild(tile);
        }
        bg.appendChild(frag);
        lastHovered = null;
    };
    
    fillGrid();
    window.addEventListener('resize', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(fillGrid, 200);
    });

    document.addEventListener('mousemove', (e) => {
        if (tiles.length === 0) return;
        const col = Math.floor(e.clientX / 48);
        const row = Math.floor(e.clientY / 48);
        const tileIndex = row * cols + col;
        
        if (lastHovered !== tileIndex && tileIndex >= 0 && tileIndex < tiles.length) {
            if (lastHovered !== null && tiles[lastHovered]) {
                tiles[lastHovered].classList.remove('hovered');
            }
            if (tiles[tileIndex]) {
                tiles[tileIndex].classList.add('hovered');
                lastHovered = tileIndex;
            }
        }
    });

    document.addEventListener('mouseleave', () => {
        if (lastHovered !== null && tiles[lastHovered]) {
            tiles[lastHovered].classList.remove('hovered');
            lastHovered = null;
        }
    });
}
initInteractiveBg();

// CUTE PET CLICK HANDLER
const petWrapper = document.querySelector('.wrapper');
if (petWrapper) {
    petWrapper.addEventListener('click', function() {
        if (this.classList.contains('playing-story')) return;
        this.classList.add('playing-story');
        setTimeout(() => {
            this.classList.remove('playing-story');
        }, 3000);
    });
}
