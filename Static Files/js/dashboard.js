/**
 * dashboard.js — Triple-Fusion-Engine Dashboard Controller
 *
 * Handles dashboard data fetching, rendering, and user interaction.
 * Depends on BullLogic (app.js) for API client and utilities.
 *
 * @author BullLogic
 */

(function () {
  'use strict';

  const { apiGet, apiPost, formatCurrency, formatPercent, formatNumber,
          formatTime, notify, $, $$, startAutoRefresh, connectWebSocket } = BullLogic;

  // ── State ────────────────────────────────────────────────────────────────────
  const state = {
    portfolio: null,
    predictions: [],
    positions: [],
    marketMovers: [],
    activities: [],
  };

  // ── Init ──────────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', () => {
    initDashboard();
  });

  async function initDashboard() {
    try {
      await Promise.all([
        fetchPortfolio(),
        fetchPredictions(),
        fetchPositions(),
        fetchMarketMovers(),
        fetchActivities(),
        fetchEquityCurve(),
      ]);
    } catch (e) {
      console.warn('[Dashboard] Partial data load:', e.message);
      notify('Some dashboard data could not be loaded', 'warning');
    }

    // Auto-refresh every 30s
    startAutoRefresh(async () => {
      await Promise.all([fetchPortfolio(), fetchPositions(), fetchActivities()]);
    }, 30000);

    // WebSocket for real-time updates
    connectWebSocket();
  }

  // ── Data Fetching ─────────────────────────────────────────────────────────────

  async function fetchPortfolio() {
    try {
      const data = await apiGet('/portfolio');
      state.portfolio = data;
      renderPortfolioCards(data);
    } catch (e) { /* silent, use defaults */ }
  }

  async function fetchPredictions() {
    try {
      const data = await apiGet('/predictions/recent', { limit: 5 });
      state.predictions = data.predictions || [];
      renderPredictionsTable(state.predictions);
    } catch (e) { /* silent */ }
  }

  async function fetchPositions() {
    try {
      const data = await apiGet('/trading/positions');
      state.positions = data.positions || [];
      renderOpenPositionsCount(state.positions.length);
    } catch (e) { /* silent */ }
  }

  async function fetchMarketMovers() {
    try {
      const data = await apiGet('/market/movers', { limit: 5 });
      state.marketMovers = data.movers || [];
      renderMarketMovers(state.marketMovers);
    } catch (e) { /* silent */ }
  }

  async function fetchActivities() {
    try {
      const data = await apiGet('/activity/recent', { limit: 10 });
      state.activities = data.activities || [];
      renderActivityFeed(state.activities);
    } catch (e) { /* silent */ }
  }

  async function fetchEquityCurve() {
    try {
      const data = await apiGet('/portfolio/equity-curve');
      renderEquityChart(data);
    } catch (e) { /* chart stays empty */ }
  }

  // ── Rendering ─────────────────────────────────────────────────────────────────

  function renderPortfolioCards(p) {
    if (!p) return;
    // Portfolio value
    const valEl = $('#portfolio-value');
    if (valEl) valEl.textContent = formatCurrency(p.equity || p.balance);
    const chgEl = $('#portfolio-change');
    if (chgEl) {
      const chg = p.change_pct || 0;
      chgEl.textContent = (chg >= 0 ? '+' : '') + formatPercent(chg);
      chgEl.className = chg >= 0 ? 'text-success' : 'text-danger';
    }
    // Today's P&L
    const pnlEl = $('#today-pnl');
    if (pnlEl) {
      const pnl = p.daily_pnl || 0;
      pnlEl.textContent = (pnl >= 0 ? '+' : '') + formatCurrency(pnl);
      pnlEl.className = pnl >= 0 ? 'text-success' : 'text-danger';
    }
    // Win rate
    const wrEl = $('#win-rate');
    if (wrEl) wrEl.textContent = formatPercent(p.win_rate || 0, 1);
  }

  function renderPredictionsTable(predictions) {
    const tbody = $('#predictions-tbody');
    if (!tbody || !predictions.length) return;

    tbody.innerHTML = predictions.map(p => `
      <tr>
        <td><strong>${BullLogic.escapeHtml(p.ticker)}</strong></td>
        <td><span class="badge badge-${p.direction === 'Up' ? 'success' : 'danger'}">${p.direction === 'Up' ? 'BUY' : 'SELL'}</span></td>
        <td>
          <div class="progress" style="height:6px">
            <div class="progress-fill" style="width:${p.confidence || 50}%;background:${p.direction === 'Up' ? 'var(--success)' : 'var(--danger)'}"></div>
          </div>
          <small>${formatPercent(p.confidence || 50, 0)}</small>
        </td>
        <td><button class="btn btn-sm btn-ghost" onclick="location.href='/result?ticker=${p.ticker}'">View</button></td>
      </tr>
    `).join('');
  }

  function renderOpenPositionsCount(count) {
    const el = $('#open-positions-count');
    if (el) el.textContent = count || 0;
  }

  function renderMarketMovers(movers) {
    const list = $('#market-movers-list');
    if (!list || !movers.length) return;

    list.innerHTML = movers.map(m => `
      <div class="mover-item flex-between">
        <div>
          <span class="mover-ticker">${BullLogic.escapeHtml(m.ticker)}</span>
          <span class="mover-name text-muted">${BullLogic.escapeHtml(m.name || '')}</span>
        </div>
        <span class="${m.change_pct >= 0 ? 'text-success' : 'text-danger'}">
          ${m.change_pct >= 0 ? '\u25B2' : '\u25BC'} ${formatPercent(Math.abs(m.change_pct))}
        </span>
      </div>
    `).join('');
  }

  function renderActivityFeed(activities) {
    const feed = $('#activity-feed');
    if (!feed || !activities.length) return;

    feed.innerHTML = activities.map(a => `
      <div class="activity-item">
        <span class="activity-icon">${_activityIcon(a.type)}</span>
        <div class="activity-content">
          <p>${BullLogic.escapeHtml(a.message)}</p>
          <small class="text-muted">${formatTime(a.timestamp)}</small>
        </div>
      </div>
    `).join('');
  }

  function renderEquityChart(data) {
    const canvas = $('#equity-chart');
    if (!canvas || !data || !data.equity) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const points = data.equity;
    const w = canvas.width = canvas.parentElement.clientWidth;
    const h = canvas.height = 200;

    const min = Math.min(...points) * 0.995;
    const max = Math.max(...points) * 1.005;
    const range = max - min || 1;

    ctx.clearRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = '#1E2538';
    ctx.lineWidth = 0.5;
    for (let i = 0; i < 4; i++) {
      const y = (h / 4) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Line
    ctx.beginPath();
    ctx.strokeStyle = '#00D4AA';
    ctx.lineWidth = 2;
    points.forEach((p, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = h - ((p - min) / range) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Fill
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, 'rgba(0,212,170,0.2)');
    grad.addColorStop(1, 'rgba(0,212,170,0.0)');
    ctx.fillStyle = grad;
    ctx.fill();
  }

  function _activityIcon(type) {
    const icons = { trade: '\u{1F4C8}', prediction: '\u{1F52E}', achievement: '\u{1F3C6}', alert: '\u{1F514}', system: '\u{2699}' };
    return icons[type] || '\u{25CF}';
  }

  // ── Quick Action Handlers ─────────────────────────────────────────────────────

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const ticker = btn.dataset.ticker || '';

    switch (action) {
      case 'predict':
        location.href = '/result?ticker=' + ticker;
        break;
      case 'trade':
        location.href = '/trading?ticker=' + ticker;
        break;
      case 'refresh':
        initDashboard();
        notify('Dashboard refreshed', 'success');
        break;
    }
  });

})();
