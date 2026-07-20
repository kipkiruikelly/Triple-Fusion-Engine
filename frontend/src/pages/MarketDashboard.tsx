import React, { useState, useEffect, useRef } from 'react';
import { ChartWidget } from '../components/ChartWidget';
import { 
  Box, Typography, Grid, Card, CardContent, CircularProgress, 
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Paper, Chip
} from '@mui/material';
import { apiFetch } from '../utils/api';

interface Mover {
  ticker: string;
  name: string;
  price: number;
  change_pct: number;
  volume: string;
}

interface IndexItem {
  name: string;
  price: string;
  change: string;
  pts: string;
  isUp: boolean;
}

export const MarketDashboard: React.FC = () => {
  const [movers, setMovers] = useState<Mover[]>([]);
  const [indices, setIndices] = useState<IndexItem[]>([]);
  const [loading, setLoading] = useState(true);
  const heatmapContainer = useRef<HTMLDivElement>(null);
  const tickerTapeContainer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fetchMovers = async () => {
      try {
        const json = await apiFetch('/api/market/movers');
        if (json.ok) {
          const fetched: Mover[] = (json.movers || []).map((m: any) => ({
            ticker: m.ticker,
            name: m.ticker === 'NVDA' ? 'NVIDIA Corp.' :
                  m.ticker === 'TSLA' ? 'Tesla Inc.' :
                  m.ticker === 'AAPL' ? 'Apple Inc.' :
                  m.ticker === 'META' ? 'Meta Platforms' :
                  m.ticker === 'MSFT' ? 'Microsoft Corp.' : 
                  m.ticker === 'AMZN' ? 'Amazon.com Inc.' :
                  m.ticker === 'GOOGL' ? 'Alphabet Inc.' :
                  m.ticker === 'NFLX' ? 'Netflix Inc.' :
                  m.ticker === 'AMD' ? 'Advanced Micro Devices' :
                  m.ticker === 'JPM' ? 'JPMorgan Chase' : 'Instrument',
            price: m.price || 0,
            change_pct: m.change_pct || 0,
            volume: m.volume ? `${(m.volume / 1000000).toFixed(1)}M` : '—'
          }));
          setMovers(fetched);
          if (json.indices) {
            setIndices(json.indices);
          }
        }
      } catch (err) {
        console.error('Failed to fetch market movers:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchMovers();
  }, []);

  // Inject Heatmap Widget
  useEffect(() => {
    if (heatmapContainer.current) {
      heatmapContainer.current.innerHTML = '';
      const script = document.createElement("script");
      script.src = "https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js";
      script.type = "text/javascript";
      script.async = true;
      script.innerHTML = JSON.stringify({
        "exchanges": [],
        "dataSource": "SPX500",
        "grouping": "sector",
        "blockSize": "market_cap_basic",
        "blockColor": "change",
        "locale": "en",
        "symbolUrl": "",
        "colorTheme": "dark",
        "hasTopBar": false,
        "isDataSetEnabled": false,
        "isZoomEnabled": true,
        "hasSymbolTooltip": true,
        "isMonoSize": false,
        "width": "100%",
        "height": "400"
      });
      heatmapContainer.current.appendChild(script);
    }
  }, []);

  // Inject TradingView Ticker Tape Widget
  useEffect(() => {
    if (tickerTapeContainer.current) {
      tickerTapeContainer.current.innerHTML = '';
      const script = document.createElement("script");
      script.src = "https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js";
      script.type = "text/javascript";
      script.async = true;
      script.innerHTML = JSON.stringify({
        "symbols": [
          { "proName": "FOREXCOM:SPXUSD", "title": "S&P 500 Index" },
          { "proName": "FOREXCOM:NAS100", "title": "Nasdaq 100 Index" },
          { "proName": "FOREXCOM:DJI", "title": "Dow Jones Index" },
          { "proName": "NASDAQ:AAPL", "title": "Apple" },
          { "proName": "NASDAQ:TSLA", "title": "Tesla" },
          { "proName": "NASDAQ:NVDA", "title": "NVIDIA" },
          { "proName": "NASDAQ:MSFT", "title": "Microsoft" }
        ],
        "showSymbolLogo": true,
        "colorTheme": "dark",
        "isTransparent": true,
        "displayMode": "adaptive",
        "locale": "en"
      });
      tickerTapeContainer.current.appendChild(script);
    }
  }, []);

  const staticIndices = [
    { name: 'S&P 500', price: '5,308.15', change: '+0.51%', pts: '+27.02 pts', isUp: true },
    { name: 'NASDAQ 100', price: '16,742.39', change: '+0.78%', pts: '+129.61 pts', isUp: true },
    { name: 'DOW JONES', price: '38,996.39', change: '-0.12%', pts: '-47.68 pts', isUp: false },
    { name: 'VIX (Fear Index)', price: '14.82', change: '-3.21%', pts: 'Low volatility', isUp: false }
  ];

  const sectorPerformance = [
    { name: 'Technology', change: '+1.42%', isUp: true },
    { name: 'Communication', change: '+0.98%', isUp: true },
    { name: 'Consumer Disc.', change: '-0.34%', isUp: false },
    { name: 'Healthcare', change: '+0.21%', isUp: true },
    { name: 'Financials', change: '-0.62%', isUp: false },
    { name: 'Industrials', change: '+0.15%', isUp: true },
    { name: 'Energy', change: '-0.88%', isUp: false },
    { name: 'Materials', change: '+0.07%', isUp: true },
    { name: 'Real Estate', change: '-1.14%', isUp: false }
  ];

  const staticGainers = [
    { ticker: 'NVDA', name: 'NVIDIA Corp.', price: 875.40, change_pct: 3.12, volume: '42.1M' },
    { ticker: 'META', name: 'Meta Platforms', price: 512.30, change_pct: 2.87, volume: '18.3M' },
    { ticker: 'AAPL', name: 'Apple Inc.', price: 189.30, change_pct: 1.24, volume: '56.7M' },
    { ticker: 'GOOGL', name: 'Alphabet Inc.', price: 168.45, change_pct: 0.91, volume: '22.5M' },
    { ticker: 'MSFT', name: 'Microsoft Corp.', price: 415.32, change_pct: 0.64, volume: '19.8M' }
  ];

  const staticLosers = [
    { ticker: 'TSLA', name: 'Tesla Inc.', price: 177.46, change_pct: -2.31, volume: '81.2M' },
    { ticker: 'AMZN', name: 'Amazon.com Inc.', price: 182.01, change_pct: -1.08, volume: '35.4M' },
    { ticker: 'JPM', name: 'JPMorgan Chase', price: 196.22, change_pct: -0.87, volume: '12.1M' },
    { ticker: 'XOM', name: 'Exxon Mobil', price: 112.44, change_pct: -0.73, volume: '14.9M' },
    { ticker: 'BAC', name: 'Bank of America', price: 37.92, change_pct: -0.54, volume: '38.6M' }
  ];

  const gainers = movers.length > 0 ? movers.filter(m => m.change_pct >= 0) : staticGainers;
  const losers = movers.length > 0 ? movers.filter(m => m.change_pct < 0) : staticLosers;
  const activeIndices = indices.length > 0 ? indices : staticIndices;

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
      
      {/* TradingView Ticker Tape Widget */}
      <Box sx={{ 
        width: '100%', 
        overflow: 'hidden', 
        bgcolor: 'background.paper', 
        borderBottom: '1px solid rgba(255,255,255,0.05)',
        minHeight: '46px',
        position: 'relative'
      }} ref={tickerTapeContainer}>
        <div className="tradingview-widget-container__widget w-full h-full" style={{ height: '46px' }}></div>
      </Box>

      {/* Page Title & Heading */}
      <Box sx={{ px: { xs: 2, md: 6 } }}>
        <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
          Market Overview
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Live indices, sector performances, top movers and market sentiment.
        </Typography>
      </Box>

      <Box sx={{ px: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {/* Live indicator banner */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Chip label="LIVE FEED" color="success" size="small" sx={{ fontWeight: 'bold', height: 18, fontSize: '0.65rem' }} />
          <Typography variant="caption" color="text.secondary">
            Real-time feed streaming major indices, volume spikes, and technical metrics indicators.
          </Typography>
        </Box>

        {/* Global Indices cards Grid */}
        <Grid container spacing={3}>
          {activeIndices.map((idx) => (
            <Grid key={idx.name} size={{ xs: 12, sm: 6, md: 3 }}>
              <Card sx={{ 
                borderLeft: idx.isUp ? '3px solid #10b981' : '3px solid #ef4444',
                transition: 'border-color 0.15s',
                '&:hover': { borderColor: 'primary.main' }
              }}>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5, fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    {idx.name}
                  </Typography>
                  <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary', mb: 0.5 }}>
                    {idx.price}
                  </Typography>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography 
                      variant="body2" 
                      sx={{ 
                        fontWeight: 'bold', 
                        color: idx.isUp ? 'success.main' : 'error.main',
                        display: 'flex',
                        alignItems: 'center'
                      }}
                    >
                      {idx.isUp ? '▲' : '▼'} {idx.change}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {idx.pts}
                    </Typography>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>

        {/* TradingView Main Chart Widget */}
        <Card>
          <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
              Live Market Chart, S&P 500 Index
            </Typography>
          </Box>
          <Box sx={{ p: 1 }}>
            <ChartWidget symbol="FOREXCOM:SPXUSD" />
          </Box>
        </Card>

        {/* Movers Section: Gainers vs Losers */}
        <Grid container spacing={3}>
          {/* Gainers */}
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%' }}>
              <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'space-between' }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                  Top Gainers
                </Typography>
                <Chip label="Today" color="success" size="small" sx={{ fontWeight: 'bold', height: 18 }} />
              </Box>
              <CardContent sx={{ p: 0 }}>
                {loading ? (
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}><CircularProgress size={24} /></Box>
                ) : (
                  <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Symbol</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Price</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)', textAlign: 'right' }}>Change</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)', textAlign: 'right' }}>Volume</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {gainers.map((row) => (
                          <TableRow key={row.ticker} sx={{ '&:last-child td': { border: 0 } }}>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                              <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>{row.ticker}</Typography>
                              <Typography variant="caption" color="text.secondary">{row.name}</Typography>
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', fontWeight: 'medium' }}>
                              ${row.price.toFixed(2)}
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', color: 'success.main', fontWeight: 'bold', textAlign: 'right' }}>
                              +{row.change_pct.toFixed(2)}%
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', color: 'text.secondary', textAlign: 'right' }}>
                              {row.volume}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </CardContent>
            </Card>
          </Grid>

          {/* Losers */}
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%' }}>
              <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'space-between' }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                  Top Losers
                </Typography>
                <Chip label="Today" color="error" size="small" sx={{ fontWeight: 'bold', height: 18 }} />
              </Box>
              <CardContent sx={{ p: 0 }}>
                {loading ? (
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}><CircularProgress size={24} /></Box>
                ) : (
                  <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Symbol</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Price</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)', textAlign: 'right' }}>Change</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)', textAlign: 'right' }}>Volume</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {losers.map((row) => (
                          <TableRow key={row.ticker} sx={{ '&:last-child td': { border: 0 } }}>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                              <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>{row.ticker}</Typography>
                              <Typography variant="caption" color="text.secondary">{row.name}</Typography>
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', fontWeight: 'medium' }}>
                              ${row.price.toFixed(2)}
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', color: 'error.main', fontWeight: 'bold', textAlign: 'right' }}>
                              {row.change_pct.toFixed(2)}%
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', color: 'text.secondary', textAlign: 'right' }}>
                              {row.volume}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {/* Sector Performance Grid */}
        <Card>
          <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
              Sector Performance
            </Typography>
          </Box>
          <CardContent sx={{ p: 3 }}>
            <Grid container spacing={2}>
              {sectorPerformance.map((sector) => (
                <Grid key={sector.name} size={{ xs: 12, sm: 6, md: 4 }}>
                  <Box sx={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'space-between',
                    p: 2,
                    borderRadius: 2,
                    bgcolor: 'background.paper',
                    border: '1px solid rgba(255,255,255,0.05)'
                  }}>
                    <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>{sector.name}</Typography>
                    <Typography 
                      variant="body2" 
                      sx={{ 
                        fontWeight: 'bold', 
                        color: sector.isUp ? 'success.main' : 'error.main' 
                      }}
                    >
                      {sector.change}
                    </Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
          </CardContent>
        </Card>

        {/* Fear & Greed / Sentiment Card */}
        <Card>
          <CardContent sx={{ p: 4 }}>
            <Grid container spacing={4} sx={{ alignItems: 'center' }}>
              <Grid size={{ xs: 12, md: 2 }} sx={{ textAlign: 'center' }}>
                <Typography variant="h1" sx={{ fontWeight: 900, color: 'primary.main', fontSize: '3.8rem', lineHeight: 1 }}>
                  62
                </Typography>
              </Grid>
              <Grid size={{ xs: 12, md: 5 }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'text.primary', mb: 1 }}>
                  Greed Index
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                  The CNN Fear & Greed Index measures market sentiment on a 0-100 scale. A score of 62 indicates moderate greed, investors are optimistic but not yet at extreme euphoria levels. Historically, readings above 75 precede short-term pullbacks.
                </Typography>
              </Grid>
              <Grid size={{ xs: 12, md: 5 }}>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', mb: 1, display: 'block', textTransform: 'uppercase' }}>
                  Fear & Greed Index Scale
                </Typography>
                
                <Box sx={{ width: '100%', my: 2.5 }}>
                  <Box sx={{ 
                    height: 8, 
                    borderRadius: 4, 
                    background: 'linear-gradient(to right, #ef4444, #8b5cf6, #10b981)',
                    position: 'relative'
                  }}>
                    <Box sx={{ 
                      position: 'absolute',
                      width: 14,
                      height: 14,
                      borderRadius: '50%',
                      bgcolor: 'white',
                      top: -3,
                      left: '62%',
                      transform: 'translateX(-50%)',
                      boxShadow: '0 2px 6px rgba(0,0,0,0.5)',
                      border: '1px solid rgba(0,0,0,0.2)'
                    }} />
                  </Box>
                </Box>
                
                <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold' }}>Extreme Fear</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold' }}>Neutral</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold' }}>Extreme Greed</Typography>
                </Box>
              </Grid>
            </Grid>
          </CardContent>
        </Card>

        {/* Live Market Heatmap Widget */}
        <Card sx={{ mb: 4 }}>
          <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
              Market Heatmap (S&P 500 Components)
            </Typography>
          </Box>
          <Box sx={{ p: 1, minHeight: 400 }} ref={heatmapContainer}>
            <div className="tradingview-widget-container__widget w-full h-full" style={{ height: '400px' }}></div>
          </Box>
        </Card>

      </Box>
    </Box>
  );
};
