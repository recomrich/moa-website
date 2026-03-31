/**
 * Hyperliquid Trading Bot - Dashboard Application
 * Real-time WebSocket updates + REST API polling
 */

// --- State ---
let ws = null;
let equityChart = null;
let equitySeries = null;
let priceChart = null;
let priceSeries = null;
let reconnectAttempts = 0;
const MAX_RECONNECT = 10;
const POLL_INTERVAL = 5000;

// --- WebSocket ---

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(url);

    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        updateBotStatus('active', 'Connected');
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg.event, msg.data);
        } catch (e) {
            console.error('Failed to parse WS message:', e);
        }
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateBotStatus('error', 'Disconnected');
        scheduleReconnect();
    };

    ws.onerror = () => {
        ws.close();
    };
}

function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) return;
    reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
    setTimeout(connectWebSocket, delay);
}

function handleWSMessage(event, data) {
    switch (event) {
        case 'status':
            updateStatusDisplay(data);
            break;
        case 'positions':
            renderPositions(data);
            break;
        case 'trades':
            renderTrades(data);
            break;
        case 'strategies':
            renderStrategies(data);
            break;
        case 'equity':
            updateEquityChart(data);
            break;
        case 'prices':
            updatePrices(data);
            break;
    }
}

// --- REST API Polling ---

async function fetchAPI(endpoint) {
    try {
        const res = await fetch(endpoint);
        if (!res.ok) return null;
        return await res.json();
    } catch (e) {
        console.error(`API fetch error (${endpoint}):`, e);
        return null;
    }
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

// --- UI Updates ---

function updateBotStatus(state, text) {
    const badge = document.getElementById('bot-status');
    const statusText = document.getElementById('bot-status-text');
    badge.className = `status-badge ${state}`;
    statusText.textContent = text;
}

function updateStatusDisplay(data) {
    const portfolio = data.portfolio || {};

    setText('portfolio-value', `$${formatNum(portfolio.total_value || 0)}`);

    const dailyPnl = portfolio.daily_pnl || 0;
    const dailyPnlPct = portfolio.daily_pnl_pct || 0;
    setTextWithColor('daily-pnl', `$${formatNum(dailyPnl, true)}`, dailyPnl);
    setTextWithColor('daily-pnl-pct', `${formatNum(dailyPnlPct, true)}%`, dailyPnlPct);

    const running = data.running;
    if (running) {
        updateBotStatus('active', `${data.mode === 'paper' ? 'Paper' : 'Live'} Trading`);
    } else {
        updateBotStatus('paused', 'Paused');
    }
}

function renderPositions(positions) {
    const tbody = document.getElementById('positions-table');
    if (!positions || positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;opacity:0.5;">No open positions</td></tr>';
        setText('open-positions', '0');
        return;
    }

    setText('open-positions', positions.length.toString());
    tbody.innerHTML = positions.map(p => `
        <tr>
            <td><strong>${p.symbol}</strong></td>
            <td style="color: ${p.side === 'buy' ? 'var(--green)' : 'var(--red)'}">${p.side.toUpperCase()}</td>
            <td>${p.size}</td>
            <td>${formatPrice(p.entry_price)}</td>
            <td class="${p.unrealized_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">${formatNum(p.unrealized_pnl, true)}</td>
            <td class="${p.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}">${formatNum(p.pnl_pct, true)}%</td>
            <td>${p.leverage}x</td>
            <td>${formatPrice(p.stop_loss)} / ${formatPrice(p.take_profit)}</td>
            <td>${p.strategy || '-'}</td>
        </tr>
    `).join('');
}

function renderTrades(trades) {
    const tbody = document.getElementById('trades-table');
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;opacity:0.5;">No trades yet</td></tr>';
        return;
    }

    tbody.innerHTML = trades.slice(0, 20).map(t => `
        <tr>
            <td><strong>${t.symbol}</strong></td>
            <td style="color: ${t.side === 'buy' ? 'var(--green)' : 'var(--red)'}">${t.side.toUpperCase()}</td>
            <td>${formatPrice(t.entry_price)}</td>
            <td>${formatPrice(t.exit_price)}</td>
            <td class="${t.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">${formatNum(t.pnl, true)}</td>
            <td class="${(t.pnl_pct || 0) >= 0 ? 'pnl-positive' : 'pnl-negative'}">${formatNum(t.pnl_pct || 0, true)}%</td>
            <td>${t.strategy || '-'}</td>
            <td>${t.close_reason || t.reason || '-'}</td>
        </tr>
    `).join('');
}

function renderStrategies(strategies) {
    const grid = document.getElementById('strategies-grid');
    if (!strategies || strategies.length === 0) {
        grid.innerHTML = '<div style="opacity:0.5;">No strategies loaded</div>';
        return;
    }

    grid.innerHTML = strategies.map(s => `
        <div class="strategy-card">
            <div class="name">${s.name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</div>
            <div class="metric">
                <span>Timeframe</span>
                <span>${s.timeframe}</span>
            </div>
            <div class="metric">
                <span>Signals</span>
                <span>${s.signals_generated}</span>
            </div>
            <div class="metric">
                <span>Win Rate</span>
                <span style="color: ${s.win_rate >= 50 ? 'var(--green)' : 'var(--text-primary)'}">${s.win_rate}%</span>
            </div>
            <div class="metric">
                <span>W / L</span>
                <span>${s.wins} / ${s.losses}</span>
            </div>
            <button class="toggle-btn ${s.enabled ? 'active' : ''}" onclick="toggleStrategy('${s.name}')">
                ${s.enabled ? 'Enabled' : 'Disabled'}
            </button>
        </div>
    `).join('');
}

async function toggleStrategy(name) {
    await fetchAPI(`/api/strategy/${name}/toggle`, { method: 'POST' });
    const strategies = await fetchAPI('/api/strategies');
    if (strategies) renderStrategies(strategies);
}

// Override fetchAPI for POST
async function fetchAPI(endpoint, options = {}) {
    try {
        const res = await fetch(endpoint, options);
        if (!res.ok) return null;
        return await res.json();
    } catch (e) {
        console.error(`API error (${endpoint}):`, e);
        return null;
    }
}

// --- Charts ---

function initCharts() {
    // Equity chart
    const equityContainer = document.getElementById('equity-chart');
    if (equityContainer && window.LightweightCharts) {
        equityChart = LightweightCharts.createChart(equityContainer, {
            width: equityContainer.clientWidth,
            height: 280,
            layout: { background: { color: '#1a1e2e' }, textColor: '#c5c6c7' },
            grid: { vertLines: { color: '#2a2f42' }, horzLines: { color: '#2a2f42' } },
            timeScale: { timeVisible: true, borderColor: '#2a2f42' },
            rightPriceScale: { borderColor: '#2a2f42' },
        });
        equitySeries = equityChart.addAreaSeries({
            lineColor: '#66fcf1',
            topColor: 'rgba(102, 252, 241, 0.3)',
            bottomColor: 'rgba(102, 252, 241, 0.0)',
            lineWidth: 2,
        });
    }

    // Price chart
    const priceContainer = document.getElementById('price-chart');
    if (priceContainer && window.LightweightCharts) {
        priceChart = LightweightCharts.createChart(priceContainer, {
            width: priceContainer.clientWidth,
            height: 280,
            layout: { background: { color: '#1a1e2e' }, textColor: '#c5c6c7' },
            grid: { vertLines: { color: '#2a2f42' }, horzLines: { color: '#2a2f42' } },
            timeScale: { timeVisible: true, borderColor: '#2a2f42' },
            rightPriceScale: { borderColor: '#2a2f42' },
        });
        priceSeries = priceChart.addCandlestickSeries({
            upColor: '#00e676',
            downColor: '#ff5252',
            borderUpColor: '#00e676',
            borderDownColor: '#ff5252',
            wickUpColor: '#00e676',
            wickDownColor: '#ff5252',
        });
    }

    // Resize handler
    window.addEventListener('resize', () => {
        if (equityChart) {
            equityChart.applyOptions({ width: equityContainer.clientWidth });
        }
        if (priceChart) {
            priceChart.applyOptions({ width: priceContainer.clientWidth });
        }
    });
}

function updateEquityChart(data) {
    if (!equitySeries || !data || data.length === 0) return;

    const chartData = data.map(d => ({
        time: typeof d.timestamp === 'number'
            ? Math.floor(d.timestamp)
            : Math.floor(new Date(d.timestamp).getTime() / 1000),
        value: d.value,
    }));

    equitySeries.setData(chartData);
}

function updatePrices(pricesData) {
    // Price data updates handled via WS
}

// --- Helpers ---

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function setTextWithColor(id, text, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'stat-value ' + (value >= 0 ? 'positive' : 'negative');
}

function formatNum(n, signed = false) {
    if (n === null || n === undefined) return '0.00';
    const abs = Math.abs(n);
    const formatted = abs >= 1000
        ? abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : abs.toFixed(2);
    if (signed) return (n >= 0 ? '+' : '-') + formatted;
    return formatted;
}

function formatPrice(p) {
    if (p === null || p === undefined) return '-';
    return typeof p === 'number' ? p.toLocaleString('en-US', { maximumFractionDigits: 6 }) : p;
}

// --- Init ---

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    connectWebSocket();
    pollData();
    setInterval(pollData, POLL_INTERVAL);
});
