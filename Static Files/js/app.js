/**
 * app.js — Triple-Fusion-Engine Application Core
 * 
 * Shared utilities, theme management, API client, and navigation.
 * Loaded on every page. Depends on no other JS modules.
 * 
 * @author BullLogic
 * @version 3.0.0
 */

const BullLogic = (() => {
  'use strict';

  // ── Configuration ────────────────────────────────────────────────────────────
  const CONFIG = {
    apiBase: '/api',
    wsUrl: (location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + location.host + '/ws',
    refreshInterval: 30000, // ms
    themeKey: 'bullLogicTheme',
    defaultTheme: 'dark',
  };

  // ── State ─────────────────────────────────────────────────────────────────────
  let _user = null;
  let _theme = localStorage.getItem(CONFIG.themeKey) || CONFIG.defaultTheme;
  let _ws = null;
  let _refreshTimer = null;

  // ── API Client ────────────────────────────────────────────────────────────────

  async function apiGet(endpoint, params = {}) {
    const url = new URL(CONFIG.apiBase + endpoint, location.origin);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    try {
      const res = await fetch(url, { headers: _authHeaders() });
      if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
      return await res.json();
    } catch (err) {
      console.error(`[BullLogic] GET ${endpoint} failed:`, err);
      throw err;
    }
  }

  async function apiPost(endpoint, data = {}) {
    try {
      const res = await fetch(CONFIG.apiBase + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ..._authHeaders() },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
      return await res.json();
    } catch (err) {
      console.error(`[BullLogic] POST ${endpoint} failed:`, err);
      throw err;
    }
  }

  function _authHeaders() {
    const token = localStorage.getItem('bullLogicToken');
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }

  // ── Theme ─────────────────────────────────────────────────────────────────────

  function setTheme(theme) {
    _theme = theme;
    // The account-backed theme system (_theme.html / blTheme) owns the
    // data-theme attribute when present; delegate instead of overwriting.
    if (window.blTheme) { window.blTheme.set(theme); return; }
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(CONFIG.themeKey, theme);
  }

  function getTheme() { return _theme; }

  function toggleTheme() {
    setTheme(_theme === 'dark' ? 'light' : 'dark');
  }

  // ── WebSocket ─────────────────────────────────────────────────────────────────

  function connectWebSocket() {
    if (_ws && _ws.readyState === WebSocket.OPEN) return _ws;
    
    try {
      _ws = new WebSocket(CONFIG.wsUrl);
      _ws.onopen = () => {
        console.log('[BullLogic] WebSocket connected');
        _ws.send(JSON.stringify({ type: 'subscribe', channels: ['trades', 'predictions', 'alerts'] }));
      };
      _ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          document.dispatchEvent(new CustomEvent('bullLogic:' + msg.type, { detail: msg }));
        } catch (e) { /* ignore malformed */ }
      };
      _ws.onclose = () => {
        console.log('[BullLogic] WebSocket disconnected, retrying in 5s...');
        setTimeout(connectWebSocket, 5000);
      };
    } catch (e) {
      console.warn('[BullLogic] WebSocket unavailable:', e.message);
    }
    return _ws;
  }

  // ── Notifications ─────────────────────────────────────────────────────────────

  function notify(message, type = 'info', duration = 5000) {
    const container = document.getElementById('toast-container') || _createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <span class="toast-icon">${_iconForType(type)}</span>
      <span class="toast-msg">${escapeHtml(message)}</span>
      <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    if (duration > 0) setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, duration);
  }

  function _createToastContainer() {
    const el = document.createElement('div');
    el.id = 'toast-container';
    el.className = 'toast-container';
    document.body.appendChild(el);
    return el;
  }

  function _iconForType(type) {
    const icons = { success: '\u2713', error: '\u2717', warning: '\u26A0', info: '\u2139' };
    return icons[type] || icons.info;
  }

  // ── Number Formatting ─────────────────────────────────────────────────────────

  function formatCurrency(val, decimals = 2) {
    if (val == null || isNaN(val)) return '$0.00';
    return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }

  function formatPercent(val, decimals = 2) {
    if (val == null || isNaN(val)) return '0.00%';
    return Number(val).toFixed(decimals) + '%';
  }

  function formatNumber(val, decimals = 0) {
    if (val == null || isNaN(val)) return '0';
    return Number(val).toLocaleString('en-US', { maximumFractionDigits: decimals });
  }

  function formatTime(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  }

  function formatDate(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  // ── DOM Helpers ───────────────────────────────────────────────────────────────

  function $(selector, parent = document) { return parent.querySelector(selector); }
  function $$(selector, parent = document) { return [...parent.querySelectorAll(selector)]; }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function showLoader(el) { if (el) el.classList.add('loading'); }
  function hideLoader(el) { if (el) el.classList.remove('loading'); }

  // ── Auto-Refresh ──────────────────────────────────────────────────────────────

  function startAutoRefresh(callback, interval = CONFIG.refreshInterval) {
    stopAutoRefresh();
    _refreshTimer = setInterval(callback, interval);
  }

  function stopAutoRefresh() {
    if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
  }

  // ── Init ──────────────────────────────────────────────────────────────────────

  function init() {
    // Only apply the standalone theme when the account theme system
    // (_theme.html) is not on the page — it resolves light/dark itself.
    if (!window.blTheme) setTheme(_theme);
    document.addEventListener('DOMContentLoaded', () => {
      document.body.classList.add('bull-logic-app');
    });
  }

  // ── Public API ────────────────────────────────────────────────────────────────

  return {
    CONFIG,
    init,
    apiGet,
    apiPost,
    setTheme,
    getTheme,
    toggleTheme,
    connectWebSocket,
    notify,
    formatCurrency,
    formatPercent,
    formatNumber,
    formatTime,
    formatDate,
    $,
    $$,
    showLoader,
    hideLoader,
    startAutoRefresh,
    stopAutoRefresh,
    escapeHtml,
  };
})();

// Auto-initialize
BullLogic.init();
