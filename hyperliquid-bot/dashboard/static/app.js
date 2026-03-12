/**
 * HyperBot Dashboard — JavaScript client
 * Gestion du WebSocket, mise à jour de l'UI et graphiques Chart.js
 */

'use strict';

// ─── Configuration ───────────────────────────────────────────────────────────
const WS_URL = `ws://${location.host}/ws`;
const RECONNECT_DELAY_MS = 3000;
const EQUITY_CHART_MAX_POINTS = 200;

// ─── État global ─────────────────────────────────────────────────────────────
let ws = null;
let equityChart = null;
let reconnectTimer = null;
let equityData = { labels: [], values: [] };

// ─── Utilitaires ─────────────────────────────────────────────────────────────

/**
 * Formate un nombre en USD avec 2 décimales.
 * @param {number} value
 * @returns {string}
 */
function formatUSD(value) {
  if (value === null || value === undefined || isNaN(value)) return '—';
  const abs = Math.abs(value);
  const formatted = abs >= 1000
    ? abs.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : abs.toFixed(2);
  const sign = value >= 0 ? '+' : '−';
  return (value === 0 ? '' : sign) + '$' + formatted;
}

/**
 * Formate un pourcentage.
 * @param {number} value
 * @returns {string}
 */
function formatPct(value) {
  if (value === null || value === undefined || isNaN(value)) return '—';
  const sign = value >= 0 ? '+' : '';
  return sign + value.toFixed(2) + '%';
}

/**
 * Retourne une classe CSS selon le signe d'une valeur.
 * @param {number} value
 * @returns {string}
 */
function colorClass(value) {
  if (value > 0) return 'positive';
  if (value < 0) return 'negative';
  return 'neutral';
}

/**
 * Formate un timestamp ISO en heure locale.
 * @param {string} iso
 * @returns {string}
 */
function formatTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('fr-FR', {
      day: '2-digit', month: '2-digit',
      hour: '2-digit', minute: '2-digit'
    });
  } catch {
    return iso;
  }
}

// ─── Initialisation des graphiques ───────────────────────────────────────────

function initEquityChart() {
  const ctx = document.getElementById('equityChart').getContext('2d');
  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Équity ($)',
        data: [],
        borderColor: '#66fcf1',
        backgroundColor: 'rgba(102, 252, 241, 0.08)',
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: true,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          backgroundColor: '#1f2833',
          borderColor: 'rgba(69,162,158,0.4)',
          borderWidth: 1,
          callbacks: {
            label: ctx => `$${ctx.raw.toLocaleString('fr-FR', { minimumFractionDigits: 2 })}`,
          }
        },
      },
      scales: {
        x: {
          display: true,
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: {
            color: '#6c757d',
            maxTicksLimit: 8,
            maxRotation: 0,
          }
        },
        y: {
          display: true,
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: {
            color: '#6c757d',
            callback: val => '$' + val.toLocaleString('fr-FR')
          }
        }
      }
    }
  });
}

// ─── Mises à jour de l'UI ─────────────────────────────────────────────────────

function updatePortfolio(data) {
  if (!data) return;

  const equity = data.current_equity || 0;
  const dailyPnl = data.daily_pnl || 0;
  const dailyPct = data.daily_pnl_pct || 0;
  const totalPnl = data.total_pnl || 0;
  const totalPct = data.total_pnl_pct || 0;

  // Header
  document.getElementById('headerEquity').textContent = '$' + equity.toLocaleString('fr-FR', { minimumFractionDigits: 2 });
  const dailyPnlEl = document.getElementById('headerDailyPnl');
  dailyPnlEl.textContent = formatUSD(dailyPnl) + ' (' + formatPct(dailyPct) + ')';
  dailyPnlEl.className = `header__stat-value ${colorClass(dailyPnl)}`;

  // Mode badge
  const modeBadge = document.getElementById('modeBadge');
  if (data.paper_mode) {
    modeBadge.textContent = 'PAPER';
    modeBadge.className = 'mode-badge mode-badge--paper';
  } else {
    modeBadge.textContent = 'LIVE ⚠️';
    modeBadge.className = 'mode-badge mode-badge--live';
  }

  // Metrics
  document.getElementById('metricEquity').textContent = '$' + equity.toLocaleString('fr-FR', { minimumFractionDigits: 2 });

  const totalPnlEl = document.getElementById('metricTotalPnl');
  totalPnlEl.textContent = formatUSD(totalPnl) + ' (' + formatPct(totalPct) + ')';
  totalPnlEl.className = `metric__sub ${colorClass(totalPnl)}`;

  const dailyPnlMetric = document.getElementById('metricDailyPnl');
  dailyPnlMetric.textContent = '$' + Math.abs(dailyPnl).toFixed(2);
  dailyPnlMetric.className = `metric__value ${colorClass(dailyPnl)}`;

  const dailyPctMetric = document.getElementById('metricDailyPct');
  dailyPctMetric.textContent = formatPct(dailyPct);
  dailyPctMetric.className = `metric__sub ${colorClass(dailyPct)}`;

  const tradesCount = data.total_trades || 0;
  document.getElementById('metricTrades').textContent = `${tradesCount} trades`;
}

function updateEquityHistory(history) {
  if (!history || !history.length || !equityChart) return;

  const labels = history.map(p => {
    const d = new Date(p.timestamp);
    return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
  });
  const values = history.map(p => p.equity);

  equityChart.data.labels = labels;
  equityChart.data.datasets[0].data = values;
  equityChart.update('none');
}

function addEquityPoint(point) {
  if (!equityChart || !point) return;

  const d = new Date(point.timestamp);
  const label = d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');

  equityChart.data.labels.push(label);
  equityChart.data.datasets[0].data.push(point.equity);

  if (equityChart.data.labels.length > EQUITY_CHART_MAX_POINTS) {
    equityChart.data.labels.shift();
    equityChart.data.datasets[0].data.shift();
  }

  equityChart.update('none');
}

function updatePositions(positions) {
  const tbody = document.getElementById('positionsTable');
  const countEl = document.getElementById('positionsCount');
  document.getElementById('headerPositions').textContent = positions ? positions.length : 0;
  countEl.textContent = positions ? positions.length : 0;

  if (!positions || positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty-state">Aucune position ouverte</td></tr>';
    return;
  }

  tbody.innerHTML = positions.map(pos => {
    const pnlClass = colorClass(pos.unrealized_pnl);
    return `
      <tr>
        <td><strong>${escHtml(pos.symbol)}</strong></td>
        <td><span class="badge badge--${pos.side}">${pos.side.toUpperCase()}</span></td>
        <td>${pos.size}</td>
        <td>$${pos.entry_price.toLocaleString('fr-FR')}</td>
        <td>$${pos.current_price.toLocaleString('fr-FR')}</td>
        <td class="${pnlClass}">${formatUSD(pos.unrealized_pnl)}</td>
        <td class="${pnlClass}">${formatPct(pos.unrealized_pnl_pct)}</td>
        <td style="color:var(--red)">${pos.stop_loss ? '$' + pos.stop_loss.toLocaleString('fr-FR') : '—'}</td>
        <td style="color:var(--green)">${pos.take_profit ? '$' + pos.take_profit.toLocaleString('fr-FR') : '—'}</td>
        <td>${pos.leverage}x</td>
        <td style="color:var(--accent-teal)">${escHtml(pos.strategy || '—')}</td>
      </tr>`;
  }).join('');
}

function updateTrades(trades) {
  const tbody = document.getElementById('tradesTable');
  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty-state">Aucun trade fermé</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const pnlClass = colorClass(t.pnl);
    return `
      <tr>
        <td><strong>${escHtml(t.symbol)}</strong></td>
        <td><span class="badge badge--${t.side}">${t.side.toUpperCase()}</span></td>
        <td>$${t.entry_price.toLocaleString('fr-FR')}</td>
        <td>${t.exit_price ? '$' + t.exit_price.toLocaleString('fr-FR') : '—'}</td>
        <td>${t.size}</td>
        <td class="${pnlClass}">${formatUSD(t.pnl)}</td>
        <td class="${pnlClass}">${formatPct(t.pnl_pct)}</td>
        <td><span class="badge badge--${t.close_reason === 'tp' ? 'buy' : t.close_reason === 'sl' ? 'sell' : 'hold'}">${escHtml(t.close_reason || '—')}</span></td>
        <td style="color:var(--accent-teal)">${escHtml(t.strategy || '—')}</td>
        <td>${t.duration_min}m</td>
        <td style="color:var(--text-muted)">${formatTime(t.closed_at)}</td>
      </tr>`;
  }).join('');
}

function updateStrategies(strategies) {
  const grid = document.getElementById('strategiesGrid');
  if (!strategies || strategies.length === 0) {
    grid.innerHTML = '<div class="empty-state">Aucune stratégie chargée</div>';
    return;
  }

  grid.innerHTML = strategies.map(s => {
    const enabledClass = s.enabled ? '' : 'strategy-card--disabled';
    const lastSignalBadge = s.last_signal
      ? `<span class="badge badge--${s.last_signal}">${s.last_signal.toUpperCase()}</span>`
      : '<span class="badge badge--hold">—</span>';
    const winRateColor = s.win_rate >= 50 ? 'positive' : s.win_rate > 0 ? 'warning' : 'neutral';

    return `
      <div class="strategy-card ${enabledClass}">
        <div class="strategy-card__name">${escHtml(s.name)}</div>
        <div class="strategy-card__row">
          <span>Timeframe</span>
          <span>${escHtml(s.timeframe || '—')}</span>
        </div>
        <div class="strategy-card__row">
          <span>Trades</span>
          <span>${s.total_trades}</span>
        </div>
        <div class="strategy-card__row">
          <span>Win Rate</span>
          <span class="${winRateColor}">${s.win_rate.toFixed(1)}%</span>
        </div>
        <div class="strategy-card__row">
          <span>PnL Total</span>
          <span class="${colorClass(s.total_pnl)}">${formatUSD(s.total_pnl)}</span>
        </div>
        <div class="strategy-card__row">
          <span>Signaux</span>
          <span>${s.total_signals} (${s.buy_signals}↑ ${s.sell_signals}↓)</span>
        </div>
        <div class="strategy-card__row" style="margin-top:8px">
          <span>Dernier signal</span>
          ${lastSignalBadge}
        </div>
        <div class="progress-bar">
          <div class="progress-bar__fill" style="width:${Math.min(s.win_rate, 100)}%"></div>
        </div>
      </div>`;
  }).join('');
}

function updateRisk(risk) {
  if (!risk) return;

  const drawdown = risk.drawdown_pct || 0;
  const maxDrawdown = risk.max_drawdown_pct || 10;
  const drawdownClass = drawdown > maxDrawdown * 0.8 ? 'negative' : drawdown > maxDrawdown * 0.5 ? 'warning' : 'positive';

  document.getElementById('riskInitialCapital').textContent = '$' + (risk.current_capital || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 });
  document.getElementById('riskDrawdown').textContent = drawdown.toFixed(2) + '%';
  document.getElementById('riskDrawdown').className = `risk-row__value ${drawdownClass}`;
  document.getElementById('riskMaxDrawdown').textContent = maxDrawdown.toFixed(1) + '%';
  document.getElementById('riskPerTrade').textContent = (risk.max_risk_per_trade_pct || 1) + '%';

  const botStopped = risk.bot_stopped;
  const statusEl = document.getElementById('riskBotStatus');
  statusEl.textContent = botStopped ? '🛑 Arrêté (drawdown)' : '✅ Actif';
  statusEl.className = `risk-row__value ${botStopped ? 'negative' : 'positive'}`;

  const pct = Math.min((drawdown / maxDrawdown) * 100, 100);
  document.getElementById('drawdownBar').style.width = pct + '%';
  document.getElementById('drawdownBar').style.background =
    pct > 80 ? 'var(--red)' : pct > 50 ? 'var(--orange)' : 'linear-gradient(90deg, var(--accent-teal), var(--accent-cyan))';

  // Métriques
  document.getElementById('metricDrawdown').textContent = drawdown.toFixed(2) + '%';
  document.getElementById('metricDrawdown').className = `metric__value ${drawdownClass}`;
  document.getElementById('metricDrawdownMax').textContent = 'Max: ' + maxDrawdown.toFixed(1) + '%';

  const winRate = risk.win_rate || 0;
  document.getElementById('metricWinRate').textContent = winRate.toFixed(1) + '%';
  document.getElementById('metricWinRate').className = `metric__value ${winRate >= 50 ? 'positive' : 'negative'}`;
  document.getElementById('metricTrades').textContent = (risk.total_trades || 0) + ' trades';

  document.getElementById('riskPositions').textContent =
    `${risk.current_positions || 0} / ${risk.max_open_positions || 5}`;
}

function setConnectionStatus(connected) {
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  const banner = document.getElementById('connectionBanner');

  if (connected) {
    dot.className = 'status-dot active';
    text.textContent = 'Connecté';
    text.style.color = 'var(--green)';
    banner.classList.remove('visible');
  } else {
    dot.className = 'status-dot error';
    text.textContent = 'Déconnecté';
    text.style.color = 'var(--red)';
    banner.classList.add('visible');
  }
}

// ─── Sécurité XSS ────────────────────────────────────────────────────────────

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ─── WebSocket ────────────────────────────────────────────────────────────────

function connectWebSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  ws = new WebSocket(WS_URL);

  ws.addEventListener('open', () => {
    setConnectionStatus(true);
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  });

  ws.addEventListener('message', (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }

    const { type, data } = msg;

    switch (type) {
      case 'portfolio':        updatePortfolio(data); break;
      case 'equity_history':   updateEquityHistory(data); break;
      case 'equity_point':     addEquityPoint(data); break;
      case 'positions':        updatePositions(data); break;
      case 'trades':           updateTrades(data); break;
      case 'strategies':       updateStrategies(data); break;
      case 'risk':             updateRisk(data); break;
      case 'pong':             break; // heartbeat
      default:
        break;
    }
  });

  ws.addEventListener('close', () => {
    setConnectionStatus(false);
    scheduleReconnect();
  });

  ws.addEventListener('error', () => {
    setConnectionStatus(false);
    ws.close();
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectWebSocket();
  }, RECONNECT_DELAY_MS);
}

// Heartbeat pour maintenir la connexion
function startHeartbeat() {
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send('ping');
    }
  }, 20000);
}

// ─── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initEquityChart();
  connectWebSocket();
  startHeartbeat();
});
