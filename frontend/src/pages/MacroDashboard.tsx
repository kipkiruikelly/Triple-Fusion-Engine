import React, { useState, useEffect } from 'react';
import { 
  Box, Typography, Grid, Card, CardContent, CircularProgress, 
  Button, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Paper, TextField, Chip
} from '@mui/material';
import { apiFetch } from '../utils/api';

interface YieldCurveData {
  maturities: string[];
  current: (number | null)[];
  month_ago: (number | null)[];
  year_ago: (number | null)[];
  date_current: string;
  date_month_ago: string;
  date_year_ago: string;
}

interface FredIndicators {
  fed_funds?: number;
  unemployment?: number;
  inflation?: number;
  gdp_growth?: number;
}

interface MarketItem {
  symbol: string;
  price: number;
  change: number;
  pct_change: number;
}

interface HeatmapItem {
  symbol: string;
  price: number;
  chg_1d: number;
  chg_1w: number;
  chg_1m: number;
  chg_ytd: number;
}

interface InsiderTransaction {
  name: string;
  share: number;
  change: number;
  transactionDate: string;
  transactionCode: string;
}

interface RecommendationTrend {
  buy: number;
  hold: number;
  sell: number;
  strongBuy: number;
  strongSell: number;
  period: string;
}

export const MacroDashboard: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [yieldCurve, setYieldCurve] = useState<YieldCurveData | null>(null);
  const [indicators, setIndicators] = useState<FredIndicators>({});
  const [markets, setMarkets] = useState<Record<string, MarketItem>>({});
  
  const [heatmap, setHeatmap] = useState<Record<string, HeatmapItem>>({});
  const [loadingHeatmap, setLoadingHeatmap] = useState(true);
  const [activeTimeframe, setActiveTimeframe] = useState<'1d' | '1w' | '1m' | 'ytd'>('1d');

  // Search Ticker Insights
  const [searchTicker, setSearchTicker] = useState('');
  const [activeTicker, setActiveTicker] = useState('AAPL');
  const [recommendations, setRecommendations] = useState<RecommendationTrend[]>([]);
  const [insiders, setInsiders] = useState<InsiderTransaction[]>([]);
  const [loadingInsights, setLoadingInsights] = useState(false);

  const fetchMacroData = async () => {
    setLoading(true);
    try {
      const data = await apiFetch('/api/macro/data');
      if (data.ok) {
        setYieldCurve(data.yield_curve);
        setIndicators(data.indicators || {});
        setMarkets(data.markets || {});
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchHeatmap = async () => {
    setLoadingHeatmap(true);
    try {
      const data = await apiFetch('/api/macro/heatmap');
      if (data.ok && data.heatmap) {
        setHeatmap(data.heatmap);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingHeatmap(false);
    }
  };

  const fetchTickerInsights = async (symbol: string) => {
    setLoadingInsights(true);
    try {
      const data = await apiFetch(`/api/macro/ticker-insights/${symbol}`);
      if (data.ok) {
        setRecommendations(data.recommendations || []);
        setInsiders(data.insiders || []);
        setActiveTicker(symbol);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingInsights(false);
    }
  };

  useEffect(() => {
    fetchMacroData();
    fetchHeatmap();
    fetchTickerInsights('AAPL');
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchTicker.trim()) {
      fetchTickerInsights(searchTicker.trim().toUpperCase());
    }
  };

  const getHeatmapColor = (val: number) => {
    if (val > 2.0) return { bg: 'rgba(16, 185, 129, 0.15)', border: 'rgba(16, 185, 129, 0.4)', text: '#10b981' };
    if (val > 0.0) return { bg: 'rgba(16, 185, 129, 0.07)', border: 'rgba(16, 185, 129, 0.2)', text: '#10b981' };
    if (val < -2.0) return { bg: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.4)', text: '#ef4444' };
    if (val < 0.0) return { bg: 'rgba(239, 68, 68, 0.07)', border: 'rgba(239, 68, 68, 0.2)', text: '#ef4444' };
    return { bg: 'rgba(255,255,255,0.02)', border: 'rgba(255,255,255,0.05)', text: '#a0a5b1' };
  };

  const sideTickers = {
    Stocks: ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD', 'NFLX', 'JPM'],
    ETFs: ['SPY', 'QQQ', 'DIA', 'IWM', 'TLT', 'GLD', 'USO', 'UNG'],
    Cryptos: ['BTC-USD', 'ETH-USD', 'SOL-USD']
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
            Market Intelligence
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Macroeconomic indicators, global yield curves, index comparisons and institutional insights.
          </Typography>
        </Box>
        <Chip label="FRED + YAHOO API" color="primary" variant="outlined" sx={{ fontWeight: 'bold' }} />
      </Box>

      {/* Main Grid */}
      <Grid container spacing={4}>
        {/* Left sidebar / quick search dropdown */}
        <Grid size={{ xs: 12, md: 3 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {/* Quick Search */}
            <Card>
              <CardContent sx={{ p: 2.5 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 2 }}>
                  Search Asset Insights
                </Typography>
                <form onSubmit={handleSearch} style={{ display: 'flex', gap: '8px' }}>
                  <TextField 
                    size="small" 
                    placeholder="e.g. AAPL, BTC-USD" 
                    value={searchTicker}
                    onChange={(e) => setSearchTicker(e.target.value)}
                    fullWidth
                    slotProps={{
                      input: {
                        style: { fontSize: '0.85rem' }
                      }
                    }}
                  />
                  <Button type="submit" variant="contained" color="primary" sx={{ fontWeight: 'bold', minWidth: 70 }}>
                    Search
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Quick links list */}
            <Card>
              <CardContent sx={{ p: 2.5 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 2 }}>
                  Tracked Assets
                </Typography>
                {Object.entries(sideTickers).map(([category, items]) => (
                  <Box key={category} sx={{ mb: 2.5 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontWeight: 'bold', mb: 1, textTransform: 'uppercase' }}>
                      {category}
                    </Typography>
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                      {items.map(sym => (
                        <Chip 
                          key={sym} 
                          label={sym} 
                          onClick={() => fetchTickerInsights(sym)}
                          size="small"
                          color={activeTicker === sym ? 'primary' : 'default'}
                          sx={{ cursor: 'pointer', fontSize: '0.75rem', fontWeight: 600 }}
                        />
                      ))}
                    </Box>
                  </Box>
                ))}
              </CardContent>
            </Card>
          </Box>
        </Grid>

        {/* Central / Right Macro details */}
        <Grid size={{ xs: 12, md: 9 }} sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {/* US Key FRED stats */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                US Key Macro Indicators (FRED)
              </Typography>
            </Box>
            <CardContent sx={{ p: 3 }}>
              {loading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>
              ) : (
                <Grid container spacing={3}>
                  <Grid size={{ xs: 6, sm: 3 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}>Fed Funds Rate</Typography>
                    <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>
                      {indicators.fed_funds ? `${indicators.fed_funds.toFixed(2)}%` : '—'}
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 6, sm: 3 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}>YoY Inflation CPI</Typography>
                    <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>
                      {indicators.inflation ? `${indicators.inflation.toFixed(2)}%` : '—'}
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 6, sm: 3 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}>Unemployment Rate</Typography>
                    <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>
                      {indicators.unemployment ? `${indicators.unemployment.toFixed(2)}%` : '—'}
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 6, sm: 3 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}>Real GDP Growth</Typography>
                    <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>
                      {indicators.gdp_growth ? `${indicators.gdp_growth.toFixed(2)}%` : '—'}
                    </Typography>
                  </Grid>
                </Grid>
              )}
            </CardContent>
          </Card>

          {/* Markets Summary Table */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                Key Assets & Yields (YFinance)
              </Typography>
            </Box>
            <CardContent sx={{ p: 0 }}>
              {loading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}><CircularProgress size={24} /></Box>
              ) : (
                <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Market Instrument</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>Price</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)', textAlign: 'right' }}>Change</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)', textAlign: 'right' }}>% Change</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {Object.entries(markets).map(([name, item]) => {
                        const isUp = item.change >= 0;
                        return (
                          <TableRow key={name} sx={{ '&:last-child td': { border: 0 } }}>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                              <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>{name}</Typography>
                              <Typography variant="caption" color="text.secondary">{item.symbol}</Typography>
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', fontWeight: 'medium' }}>
                              {item.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', color: isUp ? 'success.main' : 'error.main', fontWeight: 'bold', textAlign: 'right' }}>
                              {isUp ? '+' : ''}{item.change.toFixed(2)}
                            </TableCell>
                            <TableCell sx={{ py: 1.5, borderBottom: '1px solid rgba(255,255,255,0.03)', color: isUp ? 'success.main' : 'error.main', fontWeight: 'bold', textAlign: 'right' }}>
                              {isUp ? '+' : ''}{item.pct_change.toFixed(2)}%
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </CardContent>
          </Card>

          {/* Global Yield Curve Summary rates */}
          {yieldCurve && yieldCurve.maturities && (
            <Card>
              <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                  US Treasury Yield Curve Rates
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Daily rates extracted from US Fiscal Service API
                </Typography>
              </Box>
              <CardContent sx={{ p: 3, overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Maturity</TableCell>
                      {yieldCurve.maturities.map(m => (
                        <TableCell key={m} sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'center' }}>{m}</TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 'bold', color: 'text.primary' }}>Current ({yieldCurve.date_current})</TableCell>
                      {yieldCurve.current.map((v, i) => (
                        <TableCell key={i} sx={{ textAlign: 'center', fontWeight: 'bold', color: 'primary.main' }}>{v !== null ? `${v}%` : '—'}</TableCell>
                      ))}
                    </TableRow>
                    <TableRow>
                      <TableCell sx={{ color: 'text.secondary' }}>Month Ago ({yieldCurve.date_month_ago})</TableCell>
                      {yieldCurve.month_ago.map((v, i) => (
                        <TableCell key={i} sx={{ textAlign: 'center', color: 'text.secondary' }}>{v !== null ? `${v}%` : '—'}</TableCell>
                      ))}
                    </TableRow>
                    <TableRow>
                      <TableCell sx={{ color: 'text.secondary' }}>Year Ago ({yieldCurve.date_year_ago})</TableCell>
                      {yieldCurve.year_ago.map((v, i) => (
                        <TableCell key={i} sx={{ textAlign: 'center', color: 'text.secondary' }}>{v !== null ? `${v}%` : '—'}</TableCell>
                      ))}
                    </TableRow>
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Global Indices Heatmap */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                Global Indices Heatmap
              </Typography>
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                {(['1d', '1w', '1m', 'ytd'] as const).map(tf => (
                  <Button 
                    key={tf}
                    size="small"
                    variant={activeTimeframe === tf ? 'contained' : 'outlined'}
                    color={activeTimeframe === tf ? 'primary' : 'inherit'}
                    onClick={() => setActiveTimeframe(tf)}
                    sx={{ textTransform: 'uppercase', minWidth: 44, fontWeight: 'bold', py: 0.2 }}
                  >
                    {tf}
                  </Button>
                ))}
              </Box>
            </Box>
            <CardContent sx={{ p: 3 }}>
              {loadingHeatmap ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>
              ) : (
                <Grid container spacing={1.5}>
                  {Object.entries(heatmap).map(([name, item]) => {
                    let val = 0.0;
                    if (activeTimeframe === '1d') val = item.chg_1d;
                    else if (activeTimeframe === '1w') val = item.chg_1w;
                    else if (activeTimeframe === '1m') val = item.chg_1m;
                    else if (activeTimeframe === 'ytd') val = item.chg_ytd;

                    const color = getHeatmapColor(val);
                    return (
                      <Grid key={name} size={{ xs: 6, sm: 4, md: 3 }}>
                        <Box sx={{ 
                          p: 2,
                          textAlign: 'center',
                          borderRadius: 2,
                          bgcolor: color.bg,
                          border: '1px solid',
                          borderColor: color.border,
                          transition: 'transform 0.15s',
                          '&:hover': { transform: 'scale(1.02)' }
                        }}>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontWeight: 'bold', textTransform: 'uppercase', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {name}
                          </Typography>
                          <Typography variant="body1" sx={{ fontWeight: 'bold', mt: 0.5, color: color.text }}>
                            {val >= 0 ? '+' : ''}{val.toFixed(2)}%
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                            {item.price.toLocaleString()}
                          </Typography>
                        </Box>
                      </Grid>
                    );
                  })}
                </Grid>
              )}
            </CardContent>
          </Card>

          {/* Ticker Consensus Insights Search View */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                Institutional Consensus & Insider Trades: <span style={{ color: '#8b5cf6' }}>{activeTicker}</span>
              </Typography>
            </Box>
            <CardContent sx={{ p: 3 }}>
              {loadingInsights ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}><CircularProgress size={24} /></Box>
              ) : (
                <Grid container spacing={4}>
                  {/* Recommendations */}
                  <Grid size={{ xs: 12, md: 5 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 2 }}>
                      Analyst Recommendations
                    </Typography>
                    {recommendations.length === 0 ? (
                      <Typography variant="body2" color="text.secondary">No recommendation trends found for {activeTicker}.</Typography>
                    ) : (
                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {recommendations.map((r, idx) => (
                          <Box key={idx} sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>
                              Period: {r.period}
                            </Typography>
                            <Grid container spacing={1} sx={{ textAlign: 'center' }}>
                              <Grid size={2.4}>
                                <Typography variant="caption" color="success.main" sx={{ fontWeight: 'bold' }}>St Buy</Typography>
                                <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>{r.strongBuy}</Typography>
                              </Grid>
                              <Grid size={2.4}>
                                <Typography variant="caption" color="success.main" sx={{ fontWeight: 'medium' }}>Buy</Typography>
                                <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>{r.buy}</Typography>
                              </Grid>
                              <Grid size={2.4}>
                                <Typography variant="caption" color="text.secondary">Hold</Typography>
                                <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>{r.hold}</Typography>
                              </Grid>
                              <Grid size={2.4}>
                                <Typography variant="caption" color="error.main" sx={{ fontWeight: 'medium' }}>Sell</Typography>
                                <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>{r.sell}</Typography>
                              </Grid>
                              <Grid size={2.4}>
                                <Typography variant="caption" color="error.main" sx={{ fontWeight: 'bold' }}>St Sell</Typography>
                                <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>{r.strongSell}</Typography>
                              </Grid>
                            </Grid>
                          </Box>
                        ))}
                      </Box>
                    )}
                  </Grid>

                  {/* Insiders */}
                  <Grid size={{ xs: 12, md: 7 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 2 }}>
                      Insider Transactions
                    </Typography>
                    {insiders.length === 0 ? (
                      <Typography variant="body2" color="text.secondary">No recent insider transactions found for {activeTicker}.</Typography>
                    ) : (
                      <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none', maxHeight: 340, overflowY: 'auto' }}>
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Name</TableCell>
                              <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Shares</TableCell>
                              <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Change</TableCell>
                              <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Date</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {insiders.map((item, idx) => (
                              <TableRow key={idx}>
                                <TableCell sx={{ py: 1 }}>
                                  <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{item.name}</Typography>
                                  <Typography variant="caption" color="text.secondary">Code: {item.transactionCode}</Typography>
                                </TableCell>
                                <TableCell sx={{ py: 1, textAlign: 'right' }}>{item.share.toLocaleString()}</TableCell>
                                <TableCell sx={{ py: 1, textAlign: 'right', color: item.change >= 0 ? 'success.main' : 'error.main', fontWeight: 'bold' }}>
                                  {item.change >= 0 ? '+' : ''}{item.change.toLocaleString()}
                                </TableCell>
                                <TableCell sx={{ py: 1, textAlign: 'right', color: 'text.secondary', fontSize: '0.75rem' }}>{item.transactionDate}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    )}
                  </Grid>
                </Grid>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};
