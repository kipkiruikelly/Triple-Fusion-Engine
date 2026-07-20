import React, { useEffect, useRef } from 'react';
import { Box, Card, Typography } from '@mui/material';
import { createChart, LineStyle } from 'lightweight-charts';

interface Candle {
  time: string | number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface Zone {
  low: number;
  high: number;
  type?: string;
}

interface PredictionChartData {
  candles: Candle[];
  sma200?: { time: string | number; value: number }[];
  ote_buy?: Zone;
  ote_sell?: Zone;
  fvg?: Zone[];
  ob?: Zone[];
  pred?: number;
  sl?: number;
  tp?: number;
  direction?: string;
}

interface PredictionChartProps {
  data: PredictionChartData;
  ticker: string;
}

export const PredictionChart: React.FC<PredictionChartProps> = ({ data, ticker }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const mainSeriesRef = useRef<any>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Clear previous chart
    chartContainerRef.current.innerHTML = '';
    if (overlayRef.current) {
      overlayRef.current.innerHTML = '';
    }

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 400,
      layout: {
        background: { color: '#16181d' },
        textColor: '#7a8499',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
      },
      crosshair: {
        mode: 0,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
        timeVisible: true,
      },
    }) as any;

    const mainSeries = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    mainSeries.setData(data.candles);

    chartRef.current = chart;
    mainSeriesRef.current = mainSeries;

    // Add SMA 200 line
    if (data.sma200 && data.sma200.length > 0) {
      const smaLine = chart.addLineSeries({
        color: '#f5a623',
        lineWidth: 1.5,
        priceLineVisible: false,
        lastValueVisible: false,
        title: '200 SMA',
      });
      smaLine.setData(data.sma200);
    }

    // Add Target Price, TP, and SL lines
    if (data.pred) {
      mainSeries.createPriceLine({
        price: data.pred,
        color: '#8b5cf6',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Target: $${data.pred.toFixed(2)}`,
      });
    }

    if (data.tp) {
      mainSeries.createPriceLine({
        price: data.tp,
        color: '#10b981',
        lineWidth: 1.5,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `Take Profit: $${data.tp.toFixed(2)}`,
      });
    }

    if (data.sl) {
      mainSeries.createPriceLine({
        price: data.sl,
        color: '#ef4444',
        lineWidth: 1.5,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `Stop Loss: $${data.sl.toFixed(2)}`,
      });
    }

    // Function to draw overlays (OTE, FVG, OB)
    const drawZones = () => {
      if (!overlayRef.current || !mainSeriesRef.current || !chartRef.current) return;
      overlayRef.current.innerHTML = '';

      const makeBox = (hiPrice: number, loPrice: number, bg: string, border: string, label: string) => {
        const yHi = mainSeriesRef.current?.priceToCoordinate(hiPrice);
        const yLo = mainSeriesRef.current?.priceToCoordinate(loPrice);
        if (yHi === null || yLo === null || yHi === undefined || yLo === undefined) return;
        const top = Math.min(yHi, yLo);
        const hgt = Math.max(Math.abs(yLo - yHi), 2);
        const psW = chartRef.current?.priceScale('right').width() || 0;

        const div = document.createElement('div');
        div.style.position = 'absolute';
        div.style.left = '0';
        div.style.top = `${top}px`;
        div.style.height = `${hgt}px`;
        div.style.right = `${psW}px`;
        div.style.background = bg;
        div.style.borderTop = `1px solid ${border}`;
        div.style.borderBottom = `1px solid ${border}`;
        div.style.pointerEvents = 'none';

        if (label) {
          const span = document.createElement('span');
          span.style.position = 'absolute';
          span.style.right = '6px';
          span.style.top = '1px';
          span.style.fontSize = '9px';
          span.style.color = border;
          span.style.fontWeight = '700';
          span.textContent = label;
          div.appendChild(span);
        }
        overlayRef.current?.appendChild(div);
      };

      // Draw OTE zones
      if (data.ote_buy) {
        makeBox(data.ote_buy.high, data.ote_buy.low, 'rgba(16, 185, 129, 0.05)', '#10b981', 'OTE Buy');
      }
      if (data.ote_sell) {
        makeBox(data.ote_sell.high, data.ote_sell.low, 'rgba(239, 68, 68, 0.05)', '#ef4444', 'OTE Sell');
      }

      // Draw FVG zones
      if (data.fvg) {
        data.fvg.forEach((z) => {
          const isBull = z.type === 'bull';
          makeBox(z.high, z.low, isBull ? 'rgba(59,130,246,0.06)' : 'rgba(234,179,8,0.06)', isBull ? '#3b82f6' : '#eab308', 'FVG');
        });
      }

      // Draw OB zones
      if (data.ob) {
        data.ob.forEach((z) => {
          const isBull = z.type === 'bull';
          makeBox(z.high, z.low, isBull ? 'rgba(139,92,246,0.06)' : 'rgba(249,115,22,0.06)', isBull ? '#8b5cf6' : '#f97316', 'OB');
        });
      }
    };

    chart.timeScale().fitContent();

    // Subscribe to events to redraw overlays when user zooms or scrolls
    chart.timeScale().subscribeVisibleLogicalRangeChange(drawZones);
    const timeoutId = setTimeout(drawZones, 100);

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.resize(chartContainerRef.current.clientWidth, 400);
        drawZones();
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      clearTimeout(timeoutId);
      chart.remove();
    };
  }, [data, ticker]);

  return (
    <Card sx={{ bgcolor: '#16181d', border: '1px solid rgba(255,255,255,0.05)' }}>
      <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
          ML Model Signal Visualization ({ticker})
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Lightweight Charts™ · Dynamic Prediction Overlays
        </Typography>
      </Box>
      <Box sx={{ position: 'relative', width: '100%', height: 400, bgcolor: '#16181d', overflow: 'hidden' }}>
        {/* Chart canvas target */}
        <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
        {/* DOM Box overlay layer */}
        <div ref={overlayRef} style={{ position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 10, overflow: 'hidden' }} />
      </Box>
    </Card>
  );
};
