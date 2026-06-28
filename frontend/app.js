// frontend/app.js
// Handles all API calls and DOM rendering for NiftyLens dashboard

const API_BASE = '';

// ─── Utility functions ───────────────────────────────────────────

function formatChange(value) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}`;
}

function formatPrice(value) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    return `₹${value.toLocaleString('en-IN')}`;
}

function changeClass(value) {
    if (value > 0) return 'positive';
    if (value < 0) return 'negative';
    return 'neutral';
}

function heatmapColor(pct) {
    if (pct >= 2)   return { bg: '#166534', text: '#bbf7d0' };
    if (pct >= 1)   return { bg: '#15803d', text: '#dcfce7' };
    if (pct >= 0)   return { bg: '#1a3a2a', text: '#86efac' };
    if (pct >= -1)  return { bg: '#3a1a1a', text: '#fca5a5' };
    if (pct >= -2)  return { bg: '#7f1d1d', text: '#fecaca' };
    return              { bg: '#450a0a', text: '#fee2e2' };
}

function updateTimestamp() {
    const now = new Date();
    document.getElementById('last-updated').textContent =
        `Updated: ${now.toLocaleTimeString('en-IN')}`;
}

// ─── Module 1: Market Pulse render functions ─────────────────────

function renderSummaryCards(stocks) {
    const advancing = stocks.filter(s => s.change_pct > 0).length;
    const declining = stocks.filter(s => s.change_pct < 0).length;
    const unchanged = stocks.filter(s => s.change_pct === 0).length;

    document.getElementById('stat-total').textContent     = stocks.length;
    document.getElementById('stat-advancing').textContent = advancing;
    document.getElementById('stat-declining').textContent = declining;
    document.getElementById('stat-unchanged').textContent = unchanged;

    const statusEl = document.getElementById('market-status');
    if (advancing > declining) {
        statusEl.textContent = '🟢 Market Positive';
        statusEl.style.color = '#22c55e';
    } else if (declining > advancing) {
        statusEl.textContent = '🔴 Market Negative';
        statusEl.style.color = '#ef4444';
    } else {
        statusEl.textContent = '🟡 Market Mixed';
        statusEl.style.color = '#f59e0b';
    }
}

function renderStockItem(stock) {
    const cls = stock.change_pct >= 0 ? 'change-pos' : 'change-neg';
    return `
        <div class="stock-item">
            <div>
                <div class="stock-symbol">${stock.symbol}</div>
                <div class="stock-sector">${stock.sector}</div>
            </div>
            <div style="text-align:right">
                <div class="stock-price">₹${stock.price.toLocaleString('en-IN')}</div>
                <div class="stock-change ${cls}">
                    ${formatChange(stock.change_pct)}%
                </div>
            </div>
        </div>
    `;
}

function renderGainersLosers(data) {
    document.getElementById('gainers-list').innerHTML =
        data.gainers.map(renderStockItem).join('');
    document.getElementById('losers-list').innerHTML =
        data.losers.map(renderStockItem).join('');
}

function renderSectorHeatmap(sectors) {
    const grid = document.getElementById('sector-heatmap');
    grid.innerHTML = sectors.map(s => {
        const colors = heatmapColor(s.avg_change_pct);
        return `
            <div class="heatmap-cell"
                 style="background:${colors.bg}; color:${colors.text}">
                <div class="heatmap-sector">${s.sector}</div>
                <div class="heatmap-change">
                    ${formatChange(s.avg_change_pct)}%
                </div>
                <div class="heatmap-count">${s.stock_count} stocks</div>
            </div>
        `;
    }).join('');
}

function renderStockTable(stocks) {
    const tbody = document.getElementById('stock-tbody');
    tbody.innerHTML = stocks.map(s => `
        <tr>
            <td><strong>${s.symbol}</strong></td>
            <td><span class="badge">${s.sector}</span></td>
            <td class="num">₹${s.price.toLocaleString('en-IN')}</td>
            <td class="num ${changeClass(s.change)}">
                ${formatChange(s.change)}
            </td>
            <td class="num ${changeClass(s.change_pct)}">
                ${formatChange(s.change_pct)}%
            </td>
            <td class="num">₹${s.prev_close.toLocaleString('en-IN')}</td>
        </tr>
    `).join('');
}

function populateSectorFilter(stocks) {
    const sectors = [...new Set(stocks.map(s => s.sector))].sort();
    const select  = document.getElementById('sector-filter');
    sectors.forEach(sector => {
        const opt = document.createElement('option');
        opt.value = sector;
        opt.textContent = sector;
        select.appendChild(opt);
    });
}

let allStocks = [];

function applyFilters() {
    const query  = document.getElementById('search-input').value.toLowerCase();
    const sector = document.getElementById('sector-filter').value;

    const filtered = allStocks.filter(s => {
        const matchQuery  = !query ||
            s.symbol.toLowerCase().includes(query) ||
            s.sector.toLowerCase().includes(query);
        const matchSector = !sector || s.sector === sector;
        return matchQuery && matchSector;
    });

    renderStockTable(filtered);
}

document.getElementById('search-input')
    .addEventListener('input', applyFilters);
document.getElementById('sector-filter')
    .addEventListener('change', applyFilters);

// ─── Module 1: API calls ──────────────────────────────────────────

async function loadPrices() {
    try {
        const res  = await fetch(`${API_BASE}/api/prices`);
        const json = await res.json();
        if (json.status !== 'ok') throw new Error('Bad response');

        allStocks = json.data;
        renderSummaryCards(allStocks);
        renderStockTable(allStocks);
        populateSectorFilter(allStocks);
        renderMarketTerrain(allStocks);
        updateTimestamp();
    } catch (err) {
        console.error('loadPrices failed:', err);
        document.getElementById('stock-tbody').innerHTML =
            `<tr><td colspan="6" class="loading">
                Failed to load prices. Check console.
            </td></tr>`;
    }
}

async function loadGainersLosers() {
    try {
        const res  = await fetch(`${API_BASE}/api/gainers-losers`);
        const json = await res.json();
        if (json.status !== 'ok') throw new Error('Bad response');
        renderGainersLosers(json.data);
    } catch (err) {
        console.error('loadGainersLosers failed:', err);
    }
}

async function loadSectorPerformance() {
    try {
        const res  = await fetch(`${API_BASE}/api/sector-performance`);
        const json = await res.json();
        if (json.status !== 'ok') throw new Error('Bad response');
        renderSectorHeatmap(json.data);
    } catch (err) {
        console.error('loadSectorPerformance failed:', err);
    }
}

// ─── Bootstrap ─────────────────────────────────────────────────────

async function init() {
    await Promise.all([
        loadPrices(),
        loadGainersLosers(),
        loadSectorPerformance()
    ]);

    setInterval(() => {
        loadPrices();
        loadGainersLosers();
        loadSectorPerformance();
    }, 15 * 60 * 1000);
}

init();

// ─── Module 2: Technical Scanner ───────────────────────────────────

let scanData    = [];
let activeChart = null;
let activeTab   = 'rsi';

function rsiClass(rsi) {
    if (rsi >= 70) return 'rsi-high';
    if (rsi <= 30) return 'rsi-low';
    return 'rsi-mid';
}

function signalBadge(signal) {
    const map = {
        'Overbought':       'signal-overbought',
        'Oversold':         'signal-oversold',
        'Bullish Crossover':'signal-bullish',
        'Bearish Crossover':'signal-bearish',
        'Neutral':          'signal-neutral',
        'Middle':           'signal-neutral',
        'Near Upper Band':  'signal-overbought',
        'Near Lower Band':  'signal-oversold',
        'At Upper Band':    'signal-overbought',
        'At Lower Band':    'signal-oversold',
    };
    const cls = map[signal] || 'signal-neutral';
    return `<span class="signal-badge ${cls}">${signal}</span>`;
}

function renderScannerTable(data) {
    const filter = document.getElementById('scanner-filter').value;
    const filtered = filter
        ? data.filter(s =>
            s.rsi_signal === filter ||
            s.macd_signal === filter)
        : data;

    const tbody = document.getElementById('scanner-tbody');

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr>
            <td colspan="7" class="loading">No stocks match this filter.</td>
        </tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(s => `
        <tr class="scanner-row" data-symbol="${s.symbol}"
            style="cursor:pointer">
            <td><strong>${s.symbol}</strong></td>
            <td class="num">₹${s.current_price.toLocaleString('en-IN')}</td>
            <td class="num">
                <span class="rsi-value ${rsiClass(s.rsi)}">
                    ${s.rsi.toFixed(1)}
                </span>
            </td>
            <td>${signalBadge(s.rsi_signal)}</td>
            <td>${signalBadge(s.macd_signal)}</td>
            <td>${signalBadge(s.bb_signal)}</td>
            <td style="font-size:11px">${s.alerts.join('<br>')}</td>
        </tr>
    `).join('');

    document.querySelectorAll('.scanner-row').forEach(row => {
        row.addEventListener('click', () => {
            loadTechnicalChart(row.dataset.symbol);
        });
    });
}

async function loadTechnicalChart(symbol) {
    const panel = document.getElementById('chart-panel');
    const title = document.getElementById('chart-title');

    panel.style.display = 'block';
    title.textContent   = `Technical Chart — ${symbol}`;

    try {
        const res  = await fetch(`${API_BASE}/api/technical/${symbol}`);
        const json = await res.json();
        if (json.status !== 'ok') throw new Error('Bad response');

        const data = json.data;
        renderChart(data, activeTab);

        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.onclick = () => {
                document.querySelectorAll('.tab-btn')
                    .forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                activeTab = btn.dataset.tab;
                renderChart(data, activeTab);
            };
        });

        panel.scrollIntoView({ behavior: 'smooth' });

    } catch (err) {
        console.error('loadTechnicalChart failed:', err);
    }
}

function renderChart(data, tab) {
    const ctx = document.getElementById('technical-chart').getContext('2d');

    if (activeChart) {
        activeChart.destroy();
        activeChart = null;
    }

    const dates = data.dates.map(d => d.split(' ')[0]);

    if (tab === 'rsi') {
        activeChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: [{
                    label: 'RSI',
                    data: data.rsi.values,
                    borderColor: '#3b82f6',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: '#64748b', maxTicksLimit: 10 }, grid: { color: '#2a2d3e' } },
                    y: { min: 0, max: 100, ticks: { color: '#64748b' }, grid: { color: '#2a2d3e' } }
                }
            }
        });
    }

    if (tab === 'macd') {
        activeChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: [
                    { label: 'MACD',   data: data.macd.macd,   borderColor: '#3b82f6', borderWidth: 1.5, pointRadius: 0, fill: false },
                    { label: 'Signal', data: data.macd.signal, borderColor: '#f59e0b', borderWidth: 1.5, pointRadius: 0, fill: false }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { labels: { color: '#e2e8f0' } } },
                scales: {
                    x: { ticks: { color: '#64748b', maxTicksLimit: 10 }, grid: { color: '#2a2d3e' } },
                    y: { ticks: { color: '#64748b' }, grid: { color: '#2a2d3e' } }
                }
            }
        });
    }

    if (tab === 'bollinger') {
        activeChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: [
                    { label: 'Upper Band',    data: data.bollinger.upper,  borderColor: '#ef4444', borderWidth: 1,   pointRadius: 0, fill: false },
                    { label: 'Middle (MA20)', data: data.bollinger.middle, borderColor: '#f59e0b', borderWidth: 1.5, pointRadius: 0, fill: false },
                    { label: 'Lower Band',    data: data.bollinger.lower,  borderColor: '#22c55e', borderWidth: 1,   pointRadius: 0, fill: false }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { labels: { color: '#e2e8f0' } } },
                scales: {
                    x: { ticks: { color: '#64748b', maxTicksLimit: 10 }, grid: { color: '#2a2d3e' } },
                    y: { ticks: { color: '#64748b' }, grid: { color: '#2a2d3e' } }
                }
            }
        });
    }
}

async function runScanner() {
    const btn    = document.getElementById('scan-btn');
    const status = document.getElementById('scan-status');
    const tbody  = document.getElementById('scanner-tbody');

    btn.disabled    = true;
    btn.textContent = '⏳ Scanning...';
    status.textContent = 'Analyzing all 50 stocks — this takes 2-3 minutes on first run...';

    tbody.innerHTML = `<tr>
        <td colspan="7" class="loading">
            Running technical analysis on all 50 Nifty stocks...
        </td>
    </tr>`;

    try {
        const res  = await fetch(`${API_BASE}/api/technical/scan`);
        const json = await res.json();
        if (json.status !== 'ok') throw new Error('Scan failed');

        scanData = json.data;
        renderScannerTable(scanData);
        status.textContent = `✅ ${scanData.length} stocks analyzed`;

    } catch (err) {
        console.error('Scanner failed:', err);
        status.textContent = '❌ Scanner failed. Check console.';
        tbody.innerHTML = `<tr>
            <td colspan="7" class="loading">Scanner failed. Try again.</td>
        </tr>`;
    } finally {
        btn.disabled    = false;
        btn.textContent = '🔍 Run Scanner';
    }
}

document.getElementById('scan-btn')
    .addEventListener('click', runScanner);

document.getElementById('scanner-filter')
    .addEventListener('change', () => renderScannerTable(scanData));

// ─── Module 3: Earnings Radar ──────────────────────────────────────

function classBadgeClass(classification) {
    const map = {
        'Beat':    'classification-beat',
        'Miss':    'classification-miss',
        'Inline':  'classification-inline',
        'Unknown': 'classification-unknown'
    };
    return map[classification] || 'classification-unknown';
}

function renderEarningsItem(stock) {
    const surprise = stock.surprise_pct;
    const surpriseText = surprise === null ? 'N/A' : `${formatChange(surprise)}%`;
    const surpriseClass = surprise === null
        ? 'neutral'
        : (surprise >= 0 ? 'positive' : 'negative');

    return `
        <div class="stock-item">
            <div>
                <div class="stock-symbol">${stock.symbol}</div>
                <div class="stock-sector">${stock.latest_date}</div>
            </div>
            <div style="text-align:right">
                <div class="stock-price ${surpriseClass}">${surpriseText}</div>
            </div>
        </div>
    `;
}

function renderEarningsBestWorst(bestWorst) {
    document.getElementById('earnings-best-list').innerHTML =
        bestWorst.best.map(renderEarningsItem).join('') ||
        '<div class="loading">No ranked data available.</div>';

    document.getElementById('earnings-worst-list').innerHTML =
        bestWorst.worst.map(renderEarningsItem).join('') ||
        '<div class="loading">No ranked data available.</div>';
}

function renderEarningsTable(data) {
    const tbody = document.getElementById('earnings-tbody');

    if (data.length === 0) {
        tbody.innerHTML = `<tr>
            <td colspan="6" class="loading">No earnings data available.</td>
        </tr>`;
        return;
    }

    tbody.innerHTML = data.map(s => {
        const surprise = s.surprise_pct;
        const surpriseText = surprise === null ? 'N/A' : `${formatChange(surprise)}%`;
        const surpriseClass = surprise === null ? 'neutral' : changeClass(surprise);

        return `
            <tr>
                <td><strong>${s.symbol}</strong></td>
                <td>${s.latest_date}</td>
                <td class="num">₹${s.estimated_eps}</td>
                <td class="num">₹${s.actual_eps}</td>
                <td class="num ${surpriseClass}">${surpriseText}</td>
                <td>
                    <span class="classification-badge ${classBadgeClass(s.classification)}">
                        ${s.classification}
                    </span>
                </td>
            </tr>
        `;
    }).join('');
}

async function loadEarningsScan() {
    const btn    = document.getElementById('earnings-scan-btn');
    const status = document.getElementById('earnings-status');
    const tbody  = document.getElementById('earnings-tbody');

    btn.disabled    = true;
    btn.textContent = '⏳ Loading...';
    status.textContent = 'Fetching quarterly earnings for all 50 stocks...';

    tbody.innerHTML = `<tr>
        <td colspan="6" class="loading">Loading earnings data...</td>
    </tr>`;

    try {
        const res  = await fetch(`${API_BASE}/api/earnings/scan`);
        const json = await res.json();
        if (json.status !== 'ok') throw new Error('Scan failed');

        renderEarningsTable(json.data);
        renderEarningsBestWorst(json.best_worst);

        status.textContent =
            `✅ ${json.count}/50 stocks had usable earnings data`;

    } catch (err) {
        console.error('Earnings scan failed:', err);
        status.textContent = '❌ Failed to load earnings data.';
        tbody.innerHTML = `<tr>
            <td colspan="6" class="loading">Failed to load. Try again.</td>
        </tr>`;
    } finally {
        btn.disabled    = false;
        btn.textContent = '📊 Load Earnings Data';
    }
}

document.getElementById('earnings-scan-btn')
    .addEventListener('click', loadEarningsScan);

    // ─── Module 4: Sentiment Engine ────────────────────────────────────

function sentimentLabelClass(label) {
    if (label === 'Positive') return 'sentiment-positive';
    if (label === 'Negative') return 'sentiment-negative';
    return 'sentiment-neutral';
}

function renderSentimentTable(data) {
    const tbody = document.getElementById('sentiment-tbody');

    if (data.length === 0) {
        tbody.innerHTML = `<tr>
            <td colspan="5" class="loading">
                No stocks have matching news right now. Try again later.
            </td>
        </tr>`;
        return;
    }

    tbody.innerHTML = data.map(s => `
        <tr>
            <td><strong>${s.symbol}</strong></td>
            <td class="num">${s.headline_count}</td>
            <td class="num ${sentimentLabelClass(s.sentiment_label)}">
                ${s.avg_sentiment}
            </td>
            <td>
                <span class="signal-badge ${
                    s.sentiment_label === 'Positive' ? 'signal-bullish' :
                    s.sentiment_label === 'Negative' ? 'signal-bearish' :
                    'signal-neutral'
                }">${s.sentiment_label}</span>
            </td>
            <td style="font-size:12px">${s.all_headlines[0]?.headline || ''}</td>
        </tr>
    `).join('');
}

async function loadSentimentScan() {
    const btn    = document.getElementById('sentiment-scan-btn');
    const status = document.getElementById('sentiment-status');
    const tbody  = document.getElementById('sentiment-tbody');

    btn.disabled    = true;
    btn.textContent = '⏳ Loading...';
    status.textContent = 'Fetching and scoring news headlines...';

    tbody.innerHTML = `<tr>
        <td colspan="5" class="loading">Loading sentiment data...</td>
    </tr>`;

    try {
        const res  = await fetch(`${API_BASE}/api/sentiment/scan`);
        const json = await res.json();
        if (json.status !== 'ok') throw new Error('Scan failed');

        renderSentimentTable(json.data);
        status.textContent =
            `✅ ${json.count} stocks had matching news today`;

    } catch (err) {
        console.error('Sentiment scan failed:', err);
        status.textContent = '❌ Failed to load sentiment data.';
        tbody.innerHTML = `<tr>
            <td colspan="5" class="loading">Failed to load. Try again.</td>
        </tr>`;
    } finally {
        btn.disabled    = false;
        btn.textContent = '📰 Load News Sentiment';
    }
}

async function checkCorrelation() {
    const input  = document.getElementById('correlation-symbol-input');
    const result = document.getElementById('correlation-result');
    const symbol = input.value.trim().toUpperCase();

    if (!symbol) {
        result.innerHTML = '<p style="color:var(--text-muted)">Enter a symbol first.</p>';
        return;
    }

    result.innerHTML = '<div class="loading">Checking...</div>';

    try {
        const res  = await fetch(`${API_BASE}/api/sentiment/correlation/${symbol}`);
        const json = await res.json();

        if (json.status !== 'ok') throw new Error('Lookup failed');

        const data = json.data;

        if (data.status === 'insufficient_data') {
            result.innerHTML = `
                <div class="correlation-card">
                    <strong>${data.symbol}</strong>
                    <p style="margin-top:8px; color:var(--text-muted)">
                        Not enough data yet — ${data.days_available}/${data.days_required}
                        days collected. Run the sentiment scan daily to build up history.
                    </p>
                </div>
            `;
            return;
        }

        const corr = data.correlation;
        const corrClass = corr === null ? 'neutral' : (corr >= 0 ? 'positive' : 'negative');
        const corrText = corr === null ? 'N/A (no variation in data)' : corr;

        result.innerHTML = `
            <div class="correlation-card">
                <strong>${data.symbol}</strong>
                <div class="correlation-value ${corrClass}">${corrText}</div>
                <p style="margin-top:8px; color:var(--text-muted); font-size:12px">
                    Based on ${data.days_available} days of history.
                    Range: -1 (opposite movement) to +1 (moves together).
                </p>
            </div>
        `;

    } catch (err) {
        console.error('Correlation check failed:', err);
        result.innerHTML = '<p style="color:var(--red)">Failed to check correlation.</p>';
    }
}

document.getElementById('sentiment-scan-btn')
    .addEventListener('click', loadSentimentScan);

document.getElementById('correlation-btn')
    .addEventListener('click', checkCorrelation);

    // ─── Terminal Shell: Navigation + Starfield ────────────────────────

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.module-view').forEach(m => m.classList.remove('active'));

        btn.classList.add('active');
        document.getElementById(btn.dataset.module).classList.add('active');
    });
});

function initStarfield() {
    const canvas = document.getElementById('starfield-canvas');
    const ctx = canvas.getContext('2d');

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize);

    const stars = Array.from({ length: 120 }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 1.2 + 0.2,
        speed: Math.random() * 0.15 + 0.02
    }));

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#FFB000';
        stars.forEach(s => {
            ctx.globalAlpha = Math.random() * 0.3 + 0.2;
            ctx.beginPath();
            ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
            ctx.fill();
            s.y += s.speed;
            if (s.y > canvas.height) s.y = 0;
        });
        requestAnimationFrame(draw);
    }
    draw();
}

initStarfield();

// ─── Signature element: live market terrain ────────────────────────
// Wireframe mesh where each grid point's height = a real stock's
// change_pct today. Fixed isometric viewing angle (separate from the
// slow rotation animation) + canvas-size-aware scaling.

let terrainAngle = 0;
let terrainFrameId = null;

function renderMarketTerrain(stocks) {
    const canvas = document.getElementById('market-terrain');
    if (!canvas || stocks.length === 0) return;

    // Stop any previous loop before starting a new one — otherwise
    // every price refresh stacks another animation loop on top
    if (terrainFrameId !== null) {
        cancelAnimationFrame(terrainFrameId);
        terrainFrameId = null;
    }

    const ctx = canvas.getContext('2d');
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;

const isNarrow = canvas.clientWidth < 500;
    const cols = isNarrow ? 6 : 10;
    const rows = isNarrow ? 4 : 5;
    const grid = [];
    for (let r = 0; r < rows; r++) {
        const row = [];
        for (let c = 0; c < cols; c++) {
            const idx = r * cols + c;
            row.push(stocks[idx] ? stocks[idx].change_pct : 0);
        }
        grid.push(row);
    }

    const ISO_ANGLE = Math.PI / 6; // fixed 30° viewing angle — NEVER animated
    const cosIso = Math.cos(ISO_ANGLE);
    const sinIso = Math.sin(ISO_ANGLE);

    // Derive cell size FROM the actual canvas size, not a guessed constant
    const cellSize = Math.min(canvas.width / (cols * 1.8), canvas.height / (rows * 1.2));
    const centerCol = (cols - 1) / 2;
    const centerRow = (rows - 1) / 2;

    function project(x, y, z) {
        // Rotate around the grid's own center — this is the spin animation,
        // completely separate from the fixed isometric viewing angle above
        const dx = x - centerCol;
        const dy = y - centerRow;
        const rx = dx * Math.cos(terrainAngle) - dy * Math.sin(terrainAngle);
        const ry = dx * Math.sin(terrainAngle) + dy * Math.cos(terrainAngle);

        const isoX = (rx - ry) * cosIso * cellSize;
        const isoY = (rx + ry) * sinIso * cellSize - z * (cellSize * 0.35);

        return [canvas.width / 2 + isoX, canvas.height / 2 + isoY];
    }

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = '#FFB000';
        ctx.lineWidth = 0.8;

        for (let r = 0; r < rows; r++) {
            ctx.beginPath();
            for (let c = 0; c < cols; c++) {
                const [px, py] = project(c, r, grid[r][c]);
                ctx.globalAlpha = 0.55;
                if (c === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            }
            ctx.stroke();
        }
        for (let c = 0; c < cols; c++) {
            ctx.beginPath();
            for (let r = 0; r < rows; r++) {
                const [px, py] = project(c, r, grid[r][c]);
                if (r === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            }
            ctx.stroke();
        }

        terrainAngle += 0.003;
        terrainFrameId = requestAnimationFrame(draw);
    }
    draw();
}