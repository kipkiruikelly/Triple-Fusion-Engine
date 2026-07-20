import React, { useState } from 'react';
import { Database, Play, Shield } from 'lucide-react';
import toast from 'react-hot-toast';
import { 
  Box, Typography, Card, CardContent, TextField, Select, MenuItem, 
  Button, Grid, CircularProgress, Chip, Table, TableBody, TableCell, 
  TableContainer, TableHead, TableRow, TablePagination, Paper 
} from '@mui/material';
import { apiFetch } from '../utils/api';

export const BacktestDashboard: React.FC = () => {
  const [ticker, setTicker] = useState('AAPL');
  const [interval, setInterval] = useState('1d');
  const [period, setPeriod] = useState('2y');
  const [capital, setCapital] = useState(10000);
  const [riskPct, setRiskPct] = useState(1.0);
  
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);

  const handleRun = async () => {
    setLoading(true);
    setData(null);
    try {
      const res = await apiFetch('/api/backtest', {
        method: 'POST',
        body: {
          ticker,
          interval,
          period,
          initial_capital: capital,
          risk_pct: riskPct
        }
      });
      if (res.ok) {
        setData(res);
        toast.success('Backtest completed successfully!');
      } else {
        toast.error(res.error || 'Failed to run backtest');
      }
    } catch (err) {
      toast.error('Network error. Failed to connect.');
    } finally {
      setLoading(false);
    }
  };

  const getResultColor = (result: string) => {
    if (result === 'win') return '#10b981';
    if (result === 'loss') return '#ef4444';
    return '#a0a5b1';
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h2" sx={{ display: 'flex', alignItems: 'center', gap: 1.5, fontSize: '1.5rem', color: 'text.primary', fontWeight: 'bold' }}>
            <Database color="#8b5cf6" />
            Strategy Backtester
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Simulate our proprietary ICT + ML signals on historical data to evaluate performance.
          </Typography>
        </Box>
      </Box>

      {/* Main Grid */}
      <Grid container spacing={3}>
        {/* Configuration Panel */}
        <Grid size={{ xs: 12, lg: 4 }}>
          <Card sx={{ 
            bgcolor: 'background.paper', 
            border: '1px solid rgba(255,255,255,0.05)',
            boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
            backdropFilter: 'blur(10px)'
          }}>
            <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'text.primary', display: 'flex', alignItems: 'center', gap: 1 }}>
                Configuration
              </Typography>

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
                <TextField
                  id="bt-ticker"
                  label="Ticker Symbol"
                  size="small"
                  variant="outlined"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value.toUpperCase())}
                  fullWidth
                />

                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'medium' }}>
                    Interval
                  </Typography>
                  <Select
                    id="bt-interval"
                    size="small"
                    value={interval}
                    onChange={(e) => setInterval(e.target.value)}
                    fullWidth
                  >
                    <MenuItem value="1d">Daily (1d)</MenuItem>
                    <MenuItem value="1h">Hourly (1h)</MenuItem>
                  </Select>
                </Box>

                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'medium' }}>
                    Historical Period
                  </Typography>
                  <Select
                    id="bt-period"
                    size="small"
                    value={period}
                    onChange={(e) => setPeriod(e.target.value)}
                    fullWidth
                  >
                    <MenuItem value="6mo">6 Months</MenuItem>
                    <MenuItem value="1y">1 Year</MenuItem>
                    <MenuItem value="2y">2 Years</MenuItem>
                  </Select>
                </Box>

                <TextField
                  id="bt-capital"
                  label="Initial Capital ($)"
                  type="number"
                  size="small"
                  variant="outlined"
                  value={capital}
                  onChange={(e) => setCapital(Number(e.target.value))}
                  fullWidth
                />

                <TextField
                  id="bt-risk"
                  label="Risk per Trade (%)"
                  type="number"
                  size="small"
                  variant="outlined"
                  value={riskPct}
                  onChange={(e) => setRiskPct(Number(e.target.value))}
                  slotProps={{ htmlInput: { step: 0.1, min: 0.1, max: 10 } }}
                  fullWidth
                />

                <Button 
                  id="bt-run-btn"
                  variant="contained" 
                  color="primary" 
                  onClick={handleRun}
                  disabled={loading}
                  startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <Play size={18} />}
                  sx={{ 
                    fontWeight: 'bold', 
                    py: 1.2, 
                    borderRadius: '8px',
                    transition: 'all 0.2s',
                    '&:hover': {
                      transform: 'translateY(-1px)',
                      boxShadow: '0 4px 12px rgba(139, 92, 246, 0.2)'
                    }
                  }}
                >
                  {loading ? 'Simulating...' : 'Run Simulation'}
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Results Panel */}
        <Grid size={{ xs: 12, lg: 8 }}>
          {loading && (
            <Card sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', py: 12, height: '100%' }}>
              <CircularProgress color="primary" sx={{ mb: 2 }} />
              <Typography color="text.secondary">Running historical backtest simulation...</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>Engaging Machine Learning Signal Confluence Engine</Typography>
            </Card>
          )}

          {!loading && !data && (
            <Card sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', py: 12, height: '100%', border: '1px dashed rgba(255,255,255,0.05)' }}>
              <Typography color="text.secondary" variant="body1">Configure parameters and run the simulation to see results.</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>Requires Plus or Pro subscription tier.</Typography>
            </Card>
          )}

          {!loading && data && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {/* Overview Stat Cards */}
              <Grid container spacing={2}>
                <Grid size={{ xs: 6, sm: 4 }}>
                  <Card>
                    <CardContent sx={{ p: 2.5 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Total Return</Typography>
                      <Typography variant="h5" sx={{ fontWeight: 'bold', color: data.metrics.total_return >= 0 ? 'success.main' : 'error.main', display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        {data.metrics.total_return >= 0 ? '+' : ''}{data.metrics.total_return}%
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>

                <Grid size={{ xs: 6, sm: 4 }}>
                  <Card>
                    <CardContent sx={{ p: 2.5 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Win Rate</Typography>
                      <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                        {data.metrics.win_rate}%
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>

                <Grid size={{ xs: 6, sm: 4 }}>
                  <Card>
                    <CardContent sx={{ p: 2.5 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Sharpe Ratio</Typography>
                      <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'primary.main' }}>
                        {data.metrics.sharpe !== null ? data.metrics.sharpe.toFixed(2) : 'N/A'}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>

                <Grid size={{ xs: 6, sm: 4 }}>
                  <Card>
                    <CardContent sx={{ p: 2.5 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Max Drawdown</Typography>
                      <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'error.main' }}>
                        -{data.metrics.max_drawdown.toFixed(2)}%
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>

                <Grid size={{ xs: 6, sm: 4 }}>
                  <Card>
                    <CardContent sx={{ p: 2.5 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Total Trades</Typography>
                      <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                        {data.metrics.total_trades}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>

                <Grid size={{ xs: 6, sm: 4 }}>
                  <Card>
                    <CardContent sx={{ p: 2.5 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Final Equity</Typography>
                      <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                        ${data.metrics.final_equity.toLocaleString()}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {/* Simulation Metadata Alert */}
              <Card sx={{ borderLeft: '4px solid #8b5cf6', bgcolor: 'rgba(139, 92, 246, 0.05)' }}>
                <CardContent sx={{ py: 1.5, px: 2 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Shield size={14} color="#8b5cf6" />
                    Simulated results (from {data.start} to {data.end}) assuming commissions, spreads, and slippage. Past performance does not guarantee future outcomes.
                  </Typography>
                </CardContent>
              </Card>

              {/* Trades Table */}
              <Card>
                <CardContent sx={{ p: 0 }}>
                  <Typography variant="h6" sx={{ p: 3, pb: 2, fontWeight: 'bold', color: 'text.primary' }}>
                    Recent Simulation Trades
                  </Typography>
                  <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none', border: 'none' }}>
                    <Table>
                      <TableHead sx={{ bgcolor: 'rgba(255,255,255,0.02)' }}>
                        <TableRow>
                          <TableCell sx={{ fontWeight: 'bold' }}>Type</TableCell>
                          <TableCell sx={{ fontWeight: 'bold' }}>Entry Date</TableCell>
                          <TableCell sx={{ fontWeight: 'bold' }}>Entry Price</TableCell>
                          <TableCell sx={{ fontWeight: 'bold' }}>Exit Date</TableCell>
                          <TableCell sx={{ fontWeight: 'bold' }}>Exit Price</TableCell>
                          <TableCell sx={{ fontWeight: 'bold' }}>Result</TableCell>
                          <TableCell sx={{ fontWeight: 'bold' }} align="right">PnL</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {data.trades.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage).map((t: any, idx: number) => (
                          <TableRow key={idx} hover>
                            <TableCell>
                              <Chip 
                                label={t.direction} 
                                size="small" 
                                color={t.direction === 'BUY' ? 'success' : 'error'}
                                variant="outlined"
                                sx={{ fontWeight: 'bold' }}
                              />
                            </TableCell>
                            <TableCell>{t.entry_time.split('T')[0]}</TableCell>
                            <TableCell>${t.entry_price.toFixed(2)}</TableCell>
                            <TableCell>{t.exit_time ? t.exit_time.split('T')[0] : '-'}</TableCell>
                            <TableCell>{t.exit_price ? `$${t.exit_price.toFixed(2)}` : '-'}</TableCell>
                            <TableCell>
                              <Typography variant="body2" sx={{ fontWeight: 'bold', color: getResultColor(t.result), textTransform: 'capitalize' }}>
                                {t.result}
                              </Typography>
                            </TableCell>
                            <TableCell align="right" sx={{ fontWeight: 'bold', color: t.pnl >= 0 ? 'success.main' : 'error.main' }}>
                              {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(2)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                  <TablePagination
                    rowsPerPageOptions={[10, 25, 50]}
                    component="div"
                    count={data.trades.length}
                    rowsPerPage={rowsPerPage}
                    page={page}
                    onPageChange={(_, newPage) => setPage(newPage)}
                    onRowsPerPageChange={(e) => {
                      setRowsPerPage(parseInt(e.target.value, 10));
                      setPage(0);
                    }}
                    sx={{ color: 'text.secondary', borderTop: '1px solid rgba(255,255,255,0.05)' }}
                  />
                </CardContent>
              </Card>
            </Box>
          )}
        </Grid>
      </Grid>
    </Box>
  );
};
