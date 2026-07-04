/**
 * charts.js — Triple-Fusion-Engine Chart Configurations
 *
 * Provides helper functions to create and update charts across all pages.
 * Supports both Chart.js and Canvas 2D fallback rendering.
 *
 * @author BullLogic
 */

const BullCharts = (() => {
  'use strict';

  const { formatCurrency, formatPercent } = BullLogic;

  // ── Theme Colors ──────────────────────────────────────────────────────────────
  const COLORS = {
    bg: '#0A0E17',
    card: '#131820',
    border: '#1E2538',
    text: '#8892B0',
    green: '#00D4AA',
    red: '#FF3366',
    blue: '#00A3FF',
    purple: '#7B61FF',
    orange: '#FF6B35',
    grid: '#1E2538',
  };

  // ── Default Options ───────────────────────────────────────────────────────────

  function baseOptions(title = '') {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 500 },
      plugins: {
        legend: {
          labels: { color: COLORS.text, font: { size: 11 }, usePointStyle: true, padding: 16 },
          position: 'top',
        },
        title: title ? { display: true, text: title, color: '#FFFFFF', font: { size: 14, weight: '600' } } : { display: false },
        tooltip: {
          backgroundColor: COLORS.card,
          titleColor: '#FFFFFF',
          bodyColor: COLORS.text,
          borderColor: COLORS.border,
          borderWidth: 1,
          cornerRadius: 8,
          padding: 12,
        },
      },
      scales: {
        x: {
          grid: { color: COLORS.grid, drawBorder: false },
          ticks: { color: COLORS.text, font: { size: 10 } },
        },
        y: {
          grid: { color: COLORS.grid, drawBorder: false },
          ticks: { color: COLORS.text, font: { size: 10 }, callback: (v) => formatCurrency(v) },
        },
      },
    };
  }

  // ── Equity Curve ──────────────────────────────────────────────────────────────

  function createEquityCurve(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data || !data.length) return null;

    // Fallback to Canvas 2D if Chart.js isn't loaded
    if (typeof Chart === 'undefined') {
      return _drawEquityCurveCanvas(canvas, data);
    }

    const ctx = canvas.getContext('2d');
    return new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.map((_, i) => i),
        datasets: [{
          label: 'Portfolio',
          data: data,
          borderColor: COLORS.green,
          backgroundColor: (context) => {
            const grad = context.chart.ctx.createLinearGradient(0, 0, 0, context.chart.height);
            grad.addColorStop(0, 'rgba(0,212,170,0.25)');
            grad.addColorStop(1, 'rgba(0,212,170,0.0)');
            return grad;
          },
          fill: true,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
        }],
      },
      options: { ...baseOptions('Equity Curve'), scales: { ...baseOptions().scales } },
    });
  }

  function _drawEquityCurveCanvas(canvas, data) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.parentElement.clientWidth;
    const h = canvas.height = 200;
    const min = Math.min(...data) * 0.995;
    const max = Math.max(...data) * 1.005;
    const range = max - min || 1;

    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = COLORS.grid;
    ctx.lineWidth = 0.5;
    for (let i = 0; i < 4; i++) {
      const y = (h / 4) * i;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    ctx.beginPath();
    ctx.strokeStyle = COLORS.green;
    ctx.lineWidth = 2;
    data.forEach((p, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((p - min) / range) * h;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, 'rgba(0,212,170,0.2)');
    grad.addColorStop(1, 'rgba(0,212,170,0.0)');
    ctx.fillStyle = grad;
    ctx.fill();
    return null;
  }

  // ── P&L Bar Chart ─────────────────────────────────────────────────────────────

  function createPnLChart(canvasId, labels, values) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return null;

    return new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'P&L',
          data: values,
          backgroundColor: values.map(v => v >= 0 ? COLORS.green : COLORS.red),
          borderRadius: 4,
          borderSkipped: false,
        }],
      },
      options: { ...baseOptions('Daily P&L'), scales: { x: { grid: { display: false }, ticks: { color: COLORS.text } }, y: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text, callback: (v) => formatCurrency(v) } } } },
    });
  }

  // ── Win Rate Donut ────────────────────────────────────────────────────────────

  function createWinRateDonut(canvasId, winRate) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return null;

    return new Chart(canvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: ['Wins', 'Losses'],
        datasets: [{
          data: [winRate, 100 - winRate],
          backgroundColor: [COLORS.green, COLORS.red + '44'],
          borderWidth: 0,
          cutout: '75%',
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
      },
    });
  }

  // ── Model Contribution Bars ───────────────────────────────────────────────────

  function createModelContribution(canvasId, models) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return null;

    const colors = ['#00D4AA', '#00A3FF', '#7B61FF', '#FF6B35', '#FF3366'];
    return new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: Object.keys(models),
        datasets: [{
          label: 'Contribution',
          data: Object.values(models).map(v => Math.abs(v)),
          backgroundColor: Object.keys(models).map((_, i) => colors[i % colors.length]),
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { display: false } },
          y: { grid: { display: false }, ticks: { color: COLORS.text, font: { size: 11 } } },
        },
      },
    });
  }

  return {
    COLORS,
    createEquityCurve,
    createPnLChart,
    createWinRateDonut,
    createModelContribution,
  };
})();
