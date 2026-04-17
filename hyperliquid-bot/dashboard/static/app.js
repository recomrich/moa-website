/**
 * Hyperliquid Trading Bot - CoinTrader Style Dashboard
 */

let ws = null;
let equityChart = null;
let equitySeries = null;
let priceChart = null;
let priceSeries = null;
let reconnectAttempts = 0;
const MAX_RECONNECT = 10;
const POLL_INTERVAL = 5000;

const SYMBOL_COLORS = {
    BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff', XRP: '#546e7a',
    IO: '#4a90d9', LINK: '#2a5ada', DOGE: '#c2a633', SUI: '#4da2ff',
    AVAX: '#e84142',
};

// --- WebSocket ---

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        reconnectAttempts = 0;
        updateBotStatus('active', 'Connected');
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg.event, msg.data);
        } catch (e) {}
    };

    ws.onclose = () => {
        updateBotStatus('error', 'Disconnected');
        scheduleReconnect();
    };

    ws.onerror = () => { ws.close(); };
}

function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) return;
    reconnectAttempts++;
    setTimeout(connectWebSocket, Math.min(1000 * Math.pow(2, reconnectAttempts), 30000));
}

function handleWSMessage(event, data) {
    switch (event) {
        case 'status': updateStatusDisplay(data); break;
        case 'positions': renderPositions(data); break;
        case 'trades': renderTrades(data); break;
        case 'strategies': renderStrategies(data); break;
        case 'equity': updateEquityChart(data); break;
    }
}

// --- REST API ---

async function fetchAPI(endpoint, options = {}) {
    try {
        const res = await fetch(endpoint, options);
        if (!res.ok) return null;
        return await res.json();
    } catch (e) { return null; }
}

async function pollData() {
    const [status, positions, trades, strategies, equity] = await Promise.all([
        fetchAPI('/api/status'),
        fetchAPI('/api/positions'),
        fetchAPI('/api/trades'),
        fetchAPI('/api/strategies'),
        fetchAPI('/api/equity'),
    ]);

    if (status) updateStatusDisplay(status);
    if (positions) renderPositions(positions);
    if (trades) renderTrades(trades);
    if (strategies) renderStrategies(strategies);
    if (equity) updateEquityChart(equity);
}

// --- Status ---

function updateBotStatus(state, text) {
    const badge = document.getElementById('bot-status');
    const st = document.getElementById('bot-status-text');
    if (badge) badge.className = `status-badge ${state}`;
    if (st) st.textContent = text;
}

function updateStatusDisplay(data) {
    const p = data.portfolio || {};
    const risk = data.risk || {};

    setText('portfolio-value', `$${formatNum(p.total_value || 0)}`);
    setText('mode-label', data.mode === 'paper' ? 'paper mode' : 'live trading');

    const dailyPnl = p.daily_pnl || 0;
    const dailyPnlPct = p.daily_pnl_pct || 0;
    setValColor('daily-pnl', `$${formatNum(dailyPnl, true)}`, dailyPnl);
    setValColor('daily-pnl-pct', `${formatNum(dailyPnlPct, true)}%`, dailyPnlPct);

    const totalPnl = p.total_pnl || 0;
    setValColor('total-pnl', `$${formatNum(totalPnl, true)}`, totalPnl);

    if (data.running) {
        updateBotStatus('active', `${data.mode === 'paper' ? 'Paper' : 'Live'} Trading`);
    } else {
        updateBotStatus('paused', 'Paused');
    }
}

// --- Positions (Assets table) ---

function renderPositions(positions) {
    const tbody = document.getElementById('positions-table');
    if (!positions || positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No open positions</td></tr>';
        setText('positions-count', '0 open');
        drawPieChart([]);
        return;
    }

    setText('positions-count', `${positions.length} open`);
    drawPieChart(positions);

    tbody.innerHTML = positions.map(p => {
        const sym = (p.symbol || '').toUpperCase();
        const iconClass = sym.toLowerCase();
        const isLong = p.side === 'buy';
        const pnlVal = p.unrealized_pnl || 0;
        const pnlPct = p.pnl_pct || 0;
        const pnlClass = pnlVal >= 0 ? 'pnl-positive' : 'pnl-negative';
        const entryVal = (p.entry_price || 0) * (p.size || 0);

        return `<tr>
            <td>
                <div class="symbol-cell">
                    <div class="symbol-icon ${SYMBOL_COLORS[sym] ? iconClass : 'default'}">${sym.slice(0,2)}</div>
                    <span class="symbol-name">${sym}</span>
                </div>
            </td>
            <td><span class="strategy-tag">${formatStrategy(p.strategy)}</span></td>
            <td>$${formatNum(entryVal)}</td>
            <td class="${pnlClass}">${formatNum(pnlPct, true)}%</td>
            <td><span class="${isLong ? 'side-long' : 'side-short'}">${isLong ? 'Long' : 'Short'}</span></td>
            <td><span class="leverage-badge">${p.leverage}x</span></td>
            <td class="${pnlClass}">${formatNum(pnlPct, true)}%</td>
            <td style="font-family:var(--mono);font-size:0.78rem">${p.size} ${sym}</td>
        </tr>`;
    }).join('');
}

// --- Trades ---

function renderTrades(trades) {
    const tbody = document.getElementById('trades-table');
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No trades yet</td></tr>';
        setText('trades-count', '0');
        updateTradeStats(0, 0);
        return;
    }

    setText('trades-count', trades.length.toString());

    const wins = trades.filter(t => (t.pnl || 0) > 0).length;
    const losses = trades.filter(t => (t.pnl || 0) < 0).length;
    updateTradeStats(wins, losses);

    tbody.innerHTML = trades.slice(0, 30).map(t => {
        const sym = (t.symbol || '').toUpperCase();
        const iconClass = sym.toLowerCase();
        const isLong = t.side === 'buy';
        const pnl = t.pnl || 0;
        const pnlPct = t.pnl_pct || 0;
        const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        const reason = t.close_reason || t.reason || '-';

        return `<tr>
            <td>
                <div class="symbol-cell">
                    <div class="symbol-icon ${SYMBOL_COLORS[sym] ? iconClass : 'default'}">${sym.slice(0,2)}</div>
                    <span class="symbol-name">${sym}</span>
                </div>
            </td>
            <td><span class="${isLong ? 'side-long' : 'side-short'}">${isLong ? 'Long' : 'Short'}</span></td>
            <td style="font-family:var(--mono)">${formatPrice(t.entry_price)}</td>
            <td style="font-family:var(--mono)">${formatPrice(t.exit_price)}</td>
            <td class="${pnlClass}">$${formatNum(pnl, true)}</td>
            <td class="${pnlClass}">${formatNum(pnlPct, true)}%</td>
            <td><span class="strategy-tag">${formatStrategy(t.strategy)}</span></td>
            <td><span class="reason-tag ${getReasonClass(reason)}">${reason}</span></td>
        </tr>`;
    }).join('');
}

function updateTradeStats(wins, losses) {
    const total = wins + losses;
    setText('wins-badge', wins.toString());
    setText('losses-badge', losses.toString());

    const winsBar = document.getElementById('wins-bar');
    const lossesBar = document.getElementById('losses-bar');
    if (winsBar) winsBar.style.width = total > 0 ? `${(wins / total) * 100}%` : '0%';
    if (lossesBar) lossesBar.style.width = total > 0 ? `${(losses / total) * 100}%` : '0%';
}

// --- Strategies ---

function renderStrategies(strategies) {
    const grid = document.getElementById('strategies-grid');
    if (!strategies || strategies.length === 0) {
        grid.innerHTML = '<div class="empty-state">No strategies loaded</div>';
        setText('strategies-count', '0');
        return;
    }

    setText('strategies-count', strategies.length.toString());

    grid.innerHTML = strategies.map(s => {
        const wr = s.win_rate || 0;
        const barClass = wr >= 55 ? 'good' : wr >= 45 ? 'mid' : 'bad';

        return `<div class="strategy-card">
            <div class="name">${formatStrategy(s.name)}</div>
            <div class="metric"><span>Timeframe</span><span>${s.timeframe}</span></div>
            <div class="metric"><span>Signals</span><span>${s.signals_generated || 0}</span></div>
            <div class="metric"><span>Win Rate</span><span style="color:${wr >= 50 ? 'var(--green)' : 'var(--text)'}">${wr}%</span></div>
            <div class="metric"><span>W / L</span><span>${s.wins || 0} / ${s.losses || 0}</span></div>
            <div class="winrate-bar"><div class="fill ${barClass}" style="width:${wr}%"></div></div>
            <button class="toggle-btn ${s.enabled ? 'active' : ''}" onclick="toggleStrategy('${s.name}')">
                ${s.enabled ? 'Enabled' : 'Disabled'}
            </button>
        </div>`;
    }).join('');
}

async function toggleStrategy(name) {
    await fetchAPI(`/api/strategy/${name}/toggle`, { method: 'POST' });
    const strategies = await fetchAPI('/api/strategies');
    if (strategies) renderStrategies(strategies);
}

// --- Pie Chart (Canvas) ---

function drawPieChart(positions) {
    const canvas = document.getElementById('pie-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2, r = 90, inner = 60;

    ctx.clearRect(0, 0, w, h);

    if (!positions || positions.length === 0) {
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.arc(cx, cy, inner, 0, Math.PI * 2, true);
        ctx.fillStyle = 'rgba(255,255,255,0.06)';
        ctx.fill();
        setText('pie-main', 'No data');
        setText('pie-sub', '');
        document.getElementById('pie-legend').innerHTML = '';
        return;
    }

    const symbolTotals = {};
    positions.forEach(p => {
        const sym = (p.symbol || 'OTHER').toUpperCase();
        const val = Math.abs((p.entry_price || 0) * (p.size || 0));
        symbolTotals[sym] = (symbolTotals[sym] || 0) + val;
    });

    const entries = Object.entries(symbolTotals).sort((a, b) => b[1] - a[1]);
    const total = entries.reduce((s, e) => s + e[1], 0);

    if (total === 0) {
        drawPieChart([]);
        return;
    }

    const defaultColors = ['#a855f7', '#6366f1', '#3b82f6', '#14b8a6', '#f59e0b', '#ef4444', '#ec4899'];
    let startAngle = -Math.PI / 2;

    entries.forEach(([sym, val], i) => {
        const slice = (val / total) * Math.PI * 2;
        const color = SYMBOL_COLORS[sym] || defaultColors[i % defaultColors.length];

        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, r, startAngle, startAngle + slice);
        ctx.closePath();
        ctx.fillStyle = color;
        ctx.fill();

        startAngle += slice;
    });

    ctx.beginPath();
    ctx.arc(cx, cy, inner, 0, Math.PI * 2);
    ctx.fillStyle = getComputedStyle(document.body).backgroundColor || '#2d1b69';
    ctx.fill();

    // Approximate the gradient background for center
    ctx.beginPath();
    ctx.arc(cx, cy, inner, 0, Math.PI * 2);
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, inner);
    grad.addColorStop(0, 'rgba(45, 27, 105, 1)');
    grad.addColorStop(1, 'rgba(35, 20, 80, 1)');
    ctx.fillStyle = grad;
    ctx.fill();

    const topSym = entries[0][0];
    const topPct = Math.round((entries[0][1] / total) * 100);
    setText('pie-main', topSym);
    setText('pie-sub', `${topPct}%`);

    const legend = document.getElementById('pie-legend');
    legend.innerHTML = entries.map(([sym, val], i) => {
        const color = SYMBOL_COLORS[sym] || defaultColors[i % defaultColors.length];
        return `<div class="pie-legend-item">
            <div class="pie-legend-dot" style="background:${color}"></div>
            ${sym}
        </div>`;
    }).join('');
}

// --- Charts ---

function initCharts() {
    const eqC = document.getElementById('equity-chart');
    if (eqC && window.LightweightCharts) {
        equityChart = LightweightCharts.createChart(eqC, {
            width: eqC.clientWidth, height: 270,
            layout: { background: { color: 'transparent' }, textColor: 'rgba(255,255,255,0.45)', fontFamily: "'Poppins', sans-serif" },
            grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
            timeScale: { timeVisible: true, borderColor: 'rgba(255,255,255,0.06)' },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
            crosshair: { vertLine: { color: 'rgba(240,201,38,0.3)', width: 1, style: 2 }, horzLine: { color: 'rgba(240,201,38,0.3)', width: 1, style: 2 } },
        });
        equitySeries = equityChart.addAreaSeries({
            lineColor: '#f0c926', topColor: 'rgba(240, 201, 38, 0.25)', bottomColor: 'rgba(240, 201, 38, 0.0)', lineWidth: 2,
        });
    }

    const prC = document.getElementById('price-chart');
    if (prC && window.LightweightCharts) {
        priceChart = LightweightCharts.createChart(prC, {
            width: prC.clientWidth, height: 270,
            layout: { background: { color: 'transparent' }, textColor: 'rgba(255,255,255,0.45)', fontFamily: "'Poppins', sans-serif" },
            grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
            timeScale: { timeVisible: true, borderColor: 'rgba(255,255,255,0.06)' },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
            crosshair: { vertLine: { color: 'rgba(240,201,38,0.3)', width: 1, style: 2 }, horzLine: { color: 'rgba(240,201,38,0.3)', width: 1, style: 2 } },
        });
        priceSeries = priceChart.addCandlestickSeries({
            upColor: '#2ecc71', downColor: '#e74c3c', borderUpColor: '#2ecc71', borderDownColor: '#e74c3c', wickUpColor: '#2ecc71', wickDownColor: '#e74c3c',
        });
    }

    window.addEventListener('resize', () => {
        if (equityChart && eqC) equityChart.applyOptions({ width: eqC.clientWidth });
        if (priceChart && prC) priceChart.applyOptions({ width: prC.clientWidth });
    });
}

function updateEquityChart(data) {
    if (!equitySeries || !data || data.length === 0) return;
    equitySeries.setData(data.map(d => ({
        time: typeof d.timestamp === 'number' ? Math.floor(d.timestamp) : Math.floor(new Date(d.timestamp).getTime() / 1000),
        value: d.value,
    })));
}

// --- Helpers ---

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function setValColor(id, text, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'card-value ' + (value >= 0 ? 'positive' : 'negative');
}

function formatNum(n, signed = false) {
    if (n === null || n === undefined) return '0.00';
    const abs = Math.abs(n);
    const f = abs >= 1000 ? abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : abs.toFixed(2);
    if (signed) return (n >= 0 ? '+' : '-') + f;
    return f;
}

function formatPrice(p) {
    if (p === null || p === undefined) return '-';
    return typeof p === 'number' ? p.toLocaleString('en-US', { maximumFractionDigits: 6 }) : p;
}

function formatStrategy(name) {
    if (!name || name === '-') return '-';
    return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function getReasonClass(reason) {
    if (!reason) return 'other';
    const r = reason.toLowerCase();
    if (r.includes('tp') || r.includes('take') || r.includes('profit')) return 'tp';
    if (r.includes('sl') || r.includes('stop') || r.includes('loss')) return 'sl';
    return 'other';
}

// --- Init ---

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    connectWebSocket();
    pollData();
    setInterval(pollData, POLL_INTERVAL);
    drawPieChart([]);
});
