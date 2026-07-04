/**
 * trading.js — Triple-Fusion-Engine Trading Interface
 *
 * Handles trade execution modal, position management, and order history.
 * Depends on BullLogic (app.js).
 *
 * @author BullLogic
 */

(function () {
  'use strict';

  const { apiGet, apiPost, formatCurrency, formatPercent, notify, $, $$, connectWebSocket } = BullLogic;

  const state = {
    positions: [],
    orders: [],
    activeSymbol: '',
    currentPrice: 0,
    atr: 0,
  };

  // ── Init ──────────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', () => {
    fetchPositions();
    fetchOrderHistory();

    // Wire up trade button clicks
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action="open-trade-modal"]');
      if (btn) {
        state.activeSymbol = btn.dataset.ticker || '';
        state.currentPrice = parseFloat(btn.dataset.price) || 0;
        state.atr = parseFloat(btn.dataset.atr) || 1.0;
        openTradeModal(state.activeSymbol, state.currentPrice);
      }
    });

    // Wire up close position buttons
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action="close-position"]');
      if (btn) {
        const ticket = btn.dataset.ticket;
        if (confirm('Close position #' + ticket + '?')) {
          closePosition(ticket);
        }
      }
    });
  });

  // ── Trade Modal ───────────────────────────────────────────────────────────────

  function openTradeModal(ticker, price) {
    const modal = document.getElementById('trade-modal');
    if (!modal) return;

    const riskSlider = $('#trade-risk-slider');
    const riskPct = riskSlider ? parseFloat(riskSlider.value) : 1.0;

    const slDist = state.atr * 1.5;
    const tpDist = state.atr * 2.5;

    const buySl = price - slDist;
    const buyTp = price + tpDist;
    const sellSl = price + slDist;
    const sellTp = price - tpDist;

    modal.innerHTML = `
      <div class="modal-overlay" onclick="this.closest('.modal').classList.remove('open')"></div>
      <div class="modal-content">
        <div class="modal-header">
          <h3>Place Trade — ${BullLogic.escapeHtml(ticker)}</h3>
          <p class="text-muted">Current Price: <strong>${formatCurrency(price, 5)}</strong></p>
          <button class="modal-close" onclick="this.closest('.modal').classList.remove('open')">&times;</button>
        </div>
        <div class="modal-body">
          <div class="trade-type-selector flex gap-2">
            <button class="btn btn-success flex-1 trade-btn" data-side="BUY" onclick="document.querySelectorAll('.trade-btn').forEach(b=>b.classList.remove('active'));this.classList.add('active')">
              \u25B2 BUY / LONG
            </button>
            <button class="btn btn-danger flex-1 trade-btn" data-side="SELL" onclick="document.querySelectorAll('.trade-btn').forEach(b=>b.classList.remove('active'));this.classList.add('active')">
              \u25BC SELL / SHORT
            </button>
          </div>
          <div class="form-group mt-3">
            <label class="form-label">Risk % per Trade</label>
            <input type="range" id="trade-risk-slider" class="form-range" min="0.25" max="5" step="0.25" value="1.0"
                   oninput="document.getElementById('risk-display').textContent=this.value+'%'">
            <span id="risk-display" class="text-info">1.0%</span>
          </div>
          <div class="trade-preview mt-3">
            <div class="flex-between"><span>Entry Price:</span><strong>${formatCurrency(price, 5)}</strong></div>
            <div class="flex-between"><span>Stop Loss:</span><span class="text-danger">${formatCurrency(buySl, 5)}</span></div>
            <div class="flex-between"><span>Take Profit:</span><span class="text-success">${formatCurrency(buyTp, 5)}</span></div>
            <div class="flex-between"><span>ATR(14):</span><span class="text-muted">${state.atr.toFixed(5)}</span></div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" onclick="this.closest('.modal').classList.remove('open')">Cancel</button>
          <button class="btn btn-success" onclick="confirmTrade()">Confirm BUY</button>
        </div>
      </div>
    `;

    modal.classList.add('open');
  }

  async function confirmTrade() {
    const sideBtn = document.querySelector('.trade-btn.active');
    const side = sideBtn ? sideBtn.dataset.side : 'BUY';
    const riskSlider = $('#trade-risk-slider');
    const riskPct = riskSlider ? parseFloat(riskSlider.value) : 1.0;

    try {
      notify('Placing ' + side + ' order for ' + state.activeSymbol + '...', 'info');
      const result = await apiPost('/trading/place', {
        symbol: state.activeSymbol,
        action: side,
        risk_pct: riskPct,
      });
      if (result.ok) {
        notify(side + ' order placed successfully!', 'success');
        const modal = document.getElementById('trade-modal');
        if (modal) modal.classList.remove('open');
        fetchPositions();
      } else {
        notify('Order failed: ' + (result.error || 'Unknown error'), 'error');
      }
    } catch (e) {
      notify('Order error: ' + e.message, 'error');
    }
  }

  // ── Position Management ───────────────────────────────────────────────────────

  async function fetchPositions() {
    try {
      const data = await apiGet('/trading/positions');
      state.positions = data.positions || [];
      renderPositionsTable(state.positions);
    } catch (e) { /* silent */ }
  }

  function renderPositionsTable(positions) {
    const tbody = $('#positions-tbody');
    if (!tbody) return;

    if (!positions.length) {
      tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted">No open positions</td></tr>';
      return;
    }

    tbody.innerHTML = positions.map(p => {
      const pnl = (p.unrealized_pnl || 0);
      const pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
      return `
        <tr>
          <td><strong>${BullLogic.escapeHtml(p.symbol)}</strong></td>
          <td><span class="badge badge-${p.action === 'BUY' ? 'success' : 'danger'}">${p.action === 'BUY' ? 'LONG' : 'SHORT'}</span></td>
          <td>${formatCurrency(p.entry_price, 5)}</td>
          <td>${formatCurrency(p.current_price, 5)}</td>
          <td>${p.volume || 0.01}</td>
          <td class="${pnlClass}">${pnl >= 0 ? '+' : ''}${formatCurrency(pnl)}</td>
          <td class="${pnlClass}">${formatPercent(p.unrealized_pnl_pct || 0)}</td>
          <td><span class="text-muted">${formatCurrency(p.sl, 5)}</span> / <span class="text-success">${formatCurrency(p.tp, 5)}</span></td>
          <td><small class="text-muted">${p.time_in_position || ''}</small></td>
          <td><button class="btn btn-sm btn-danger" data-action="close-position" data-ticket="${p.ticket}">Close</button></td>
        </tr>
      `;
    }).join('');
  }

  async function closePosition(ticket) {
    try {
      await apiPost('/trading/close', { ticket });
      notify('Position #' + ticket + ' closed', 'success');
      fetchPositions();
      fetchOrderHistory();
    } catch (e) {
      notify('Close failed: ' + e.message, 'error');
    }
  }

  // ── Order History ─────────────────────────────────────────────────────────────

  async function fetchOrderHistory() {
    try {
      const data = await apiGet('/trading/orders', { limit: 20 });
      state.orders = data.orders || [];
      renderOrderHistory(state.orders);
    } catch (e) { /* silent */ }
  }

  function renderOrderHistory(orders) {
    const tbody = $('#orders-tbody');
    if (!tbody) return;

    if (!orders.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No order history</td></tr>';
      return;
    }

    tbody.innerHTML = orders.map(o => `
      <tr>
        <td><small>${BullLogic.formatTime(o.timestamp)}</small></td>
        <td><strong>${BullLogic.escapeHtml(o.symbol)}</strong></td>
        <td><span class="badge badge-${o.action === 'BUY' ? 'success' : 'danger'}">${o.action}</span></td>
        <td>${formatCurrency(o.price, 5)}</td>
        <td>${o.volume || 0.01}</td>
        <td><span class="badge badge-${o.status === 'FILLED' ? 'success' : 'warning'}">${o.status || 'PENDING'}</span></td>
        <td>${o.slippage_bps != null ? o.slippage_bps + ' bps' : '-'}</td>
        <td>${o.fill_rate_pct != null ? formatPercent(o.fill_rate_pct, 0) : '-'}</td>
      </tr>
    `).join('');
  }

  // ── Real-time Updates ─────────────────────────────────────────────────────────

  // The modal HTML references confirmTrade() via inline onclick, so it
  // must be reachable on window (this module is an IIFE).
  window.confirmTrade = confirmTrade;

  document.addEventListener('bullLogic:trade', (e) => {
    fetchPositions();
    notify('Trade update: ' + (e.detail.message || ''), 'info', 3000);
  });

  connectWebSocket();

})();
