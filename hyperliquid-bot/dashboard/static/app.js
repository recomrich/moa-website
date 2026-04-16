/**
 * Hyperliquid Trading Bot - Premium Dashboard
 */

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
        reconnectAttempts = 0;
        updateBotStatus('active', 'Connected');
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg.event, msg.data);
        } catch (e) {
            console.error('WS parse error:', e);
        }
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
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
    setTimeout(connectWebSocket, delay);
}

function handleWSMessage(event, data) {
    switch (event) {
        case 'status': updateStatusDisplay(data); break;
        case 'positions': renderPositions(data); break;
        case 'trades': renderTrades(data); break;
        case 'strategies': renderStrategies(data); break;
        case 'equity': updateEquityChart(data); break;
        case 'prices': updatePrices(data); break;
    }
}

// --- REST API ---

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
    if (badge) badge.className = `status-badge ${state}`;
    if (statusText) statusText.textContent = text;
}

function updateStatusDisplay(data) {
    const portfolio = data.portfolio || {};
    const risk = data.risk || {};

    setText('portfolio-value', `$${formatNum(portfolio.total_value || 0)}`);

    const dailyPnl = portfolio.daily_pnl || 0;
    const dailyPnlPct = portfolio.daily_pnl_pct || 0;
    setTextWithColor('daily-pnl', `$${formatNum(dailyPnl, true)}`, dailyPnl);
    setTextWithColor('daily-pnl-pct', `${formatNum(dailyPnlPct, true)}%`, dailyPnlPct);

    // Stat cards
    const totalPnl = portfolio.total_pnl || 0;
    setTextWithColor('total-pnl', `$${formatNum(totalPnl, true)}`, totalPnl);

    const drawdown = risk.current_drawdown || 0;
    const maxDrawdown = risk.max_drawdown || 0;
    setText('drawdown', `${Math.abs(drawdown).toFixed(1)}%`);
    setText('drawdown-sub', `max: ${Math.abs(maxDrawdown).toFixed(1)}%`);

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
        tbody.innerHTML = '<tr><td colspan="10" class="empty-state">No open positions</td></tr>';
        setText('open-positions', '0');
        setText('positions-count', '0');
        setText('positions-sub', '0 long / 0 short');
        return;
    }

    const count = positions.length;
    const longs = positions.filter(p => p.side === 'buy').length;
    const shorts = count - longs;

    setText('open-positions', count.toString());
    setText('positions-count', count.toString());
    setText('positions-sub', `${longs} long / ${shorts} short`);

    tbody.innerHTML = positions.map(p => {
        const sideClass = p.side === 'buy' ? 'side-buy' : 'side-sell';
        const sideText = p.side === 'buy' ? 'LONG' : 'SHORT';
        const pnlClass = p.unrealized_pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        const pctClass = p.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative';

        return `<tr>
            <td><span class="symbol-name">${p.symbol}</span></td>
            <td><span class="${sideClass}">${sideText}</span></td>
            <td>${p.size}</td>
            <td>${formatPrice(p.entry_price)}</td>
            <td>${formatPrice(p.current_price)}</td>
            <td class="${pnlClass}">$${formatNum(p.unrealized_pnl, true)}</td>
            <td class="${pctClass}">${formatNum(p.pnl_pct, true)}%</td>
            <td><span class="leverage-badge">${p.leverage}x</span></td>
            <td>${formatPrice(p.stop_loss)} / ${formatPrice(p.take_profit)}</td>
            <td><span class="strategy-tag">${formatStrategy(p.strategy)}</span></td>
        </tr>`;
    }).join('');
}

function renderTrades(trades) {
    const tbody = document.getElementById('trades-table');
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No trades yet</td></tr>';
        setText('trades-count', '0');
        return;
    }

    const displayed = trades.slice(0, 30);
    setText('trades-count', trades.length.toString());

    // Update win rate card
    const wins = trades.filter(t => (t.pnl || 0) > 0).length;
    const losses = trades.filter(t => (t.pnl || 0) < 0).length;
    const total = wins + losses;
    const winRate = total > 0 ? Math.round((wins / total) * 100) : 0;
    setText('win-rate', `${winRate}%`);
    setText('win-rate-sub', `${wins}W / ${losses}L`);
    setText('total-trades', total.toString());

    // Color the win rate
    const wrEl = document.getElementById('win-rate');
    if (wrEl) {
        wrEl.className = 'card-value' + (winRate >= 50 ? ' positive' : winRate > 0 ? ' negative' : '');
    }

    tbody.innerHTML = displayed.map(t => {
        const sideClass = t.side === 'buy' ? 'side-buy' : 'side-sell';
        const sideText = t.side === 'buy' ? 'LONG' : 'SHORT';
        const pnl = t.pnl || 0;
        const pnlPct = t.pnl_pct || 0;
        const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        const reason = t.close_reason || t.reason || '-';
        const reasonClass = getReasonClass(reason);

        return `<tr>
            <td><span class="symbol-name">${t.symbol}</span></td>
            <td><span class="${sideClass}">${sideText}</span></td>
            <td>${formatPrice(t.entry_price)}</td>
            <td>${formatPrice(t.exit_price)}</td>
            <td class="${pnlClass}">$${formatNum(pnl, true)}</td>
            <td class="${pnlClass}">${formatNum(pnlPct, true)}%</td>
            <td><span class="strategy-tag">${formatStrategy(t.strategy)}</span></td>
            <td><span class="reason-tag ${reasonClass}">${reason}</span></td>
        </tr>`;
    }).join('');
}

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
        const wrBarClass = wr >= 55 ? 'good' : wr >= 45 ? 'mid' : 'bad';
        const name = formatStrategy(s.name);

        return `<div class="strategy-card">
            <div class="name">${name}</div>
            <div class="metric">
                <span>Timeframe</span>
                <span>${s.timeframe}</span>
            </div>
            <div class="metric">
                <span>Signals</span>
                <span>${s.signals_generated || 0}</span>
            </div>
            <div class="metric">
                <span>Win Rate</span>
                <span style="color: ${wr >= 50 ? 'var(--green)' : 'var(--text-primary)'}">${wr}%</span>
            </div>
            <div class="metric">
                <span>W / L</span>
                <span>${s.wins || 0} / ${s.losses || 0}</span>
            </div>
            <div class="winrate-bar">
                <div class="fill ${wrBarClass}" style="width: ${wr}%"></div>
            </div>
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

// --- Charts ---

function initCharts() {
    const equityContainer = document.getElementById('equity-chart');
    if (equityContainer && window.LightweightCharts) {
        equityChart = LightweightCharts.createChart(equityContainer, {
            width: equityContainer.clientWidth,
            height: 290,
            layout: {
                background: { color: '#141620' },
                textColor: '#8b8fa3',
                fontFamily: "'Inter', sans-serif",
            },
            grid: {
                vertLines: { color: 'rgba(255,255,255,0.04)' },
                horzLines: { color: 'rgba(255,255,255,0.04)' },
            },
            timeScale: { timeVisible: true, borderColor: 'rgba(255,255,255,0.06)' },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
            crosshair: {
                vertLine: { color: 'rgba(99,102,241,0.3)', width: 1, style: 2 },
                horzLine: { color: 'rgba(99,102,241,0.3)', width: 1, style: 2 },
            },
        });
        equitySeries = equityChart.addAreaSeries({
            lineColor: '#6366f1',
            topColor: 'rgba(99, 102, 241, 0.28)',
            bottomColor: 'rgba(99, 102, 241, 0.0)',
            lineWidth: 2,
        });
    }

    const priceContainer = document.getElementById('price-chart');
    if (priceContainer && window.LightweightCharts) {
        priceChart = LightweightCharts.createChart(priceContainer, {
            width: priceContainer.clientWidth,
            height: 290,
            layout: {
                background: { color: '#141620' },
                textColor: '#8b8fa3',
                fontFamily: "'Inter', sans-serif",
            },
            grid: {
                vertLines: { color: 'rgba(255,255,255,0.04)' },
                horzLines: { color: 'rgba(255,255,255,0.04)' },
            },
            timeScale: { timeVisible: true, borderColor: 'rgba(255,255,255,0.06)' },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
            crosshair: {
                vertLine: { color: 'rgba(99,102,241,0.3)', width: 1, style: 2 },
                horzLine: { color: 'rgba(99,102,241,0.3)', width: 1, style: 2 },
            },
        });
        priceSeries = priceChart.addCandlestickSeries({
            upColor: '#22c55e',
            downColor: '#ef4444',
            borderUpColor: '#22c55e',
            borderDownColor: '#ef4444',
            wickUpColor: '#22c55e',
            wickDownColor: '#ef4444',
        });
    }

    window.addEventListener('resize', () => {
        if (equityChart && equityContainer) {
            equityChart.applyOptions({ width: equityContainer.clientWidth });
        }
        if (priceChart && priceContainer) {
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
    // Handled via WS
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

function formatStrategy(name) {
    if (!name || name === '-') return '-';
    return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function getReasonClass(reason) {
    if (!reason) return 'other';
    const r = reason.toLowerCase();
    if (r.includes('tp') || r.includes('take') || r.includes('profit') || r.includes('target')) return 'tp';
    if (r.includes('sl') || r.includes('stop') || r.includes('loss')) return 'sl';
    return 'other';
}

// --- Init ---

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    connectWebSocket();
    pollData();
    setInterval(pollData, POLL_INTERVAL);
});
