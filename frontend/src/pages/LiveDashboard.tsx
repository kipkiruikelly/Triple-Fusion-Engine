import React, { useState, useEffect, useCallback } from 'react';
import { Box, Typography, Card, CardContent, TextField, Button, Grid, MenuItem, Select, Switch, FormControlLabel, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper, Chip, Divider } from '@mui/material';
import { Zap, Play, Square, Settings, Key, AlertTriangle, ShieldCheck, HelpCircle, Activity } from 'lucide-react';
import { apiFetch } from '../utils/api';
import toast from 'react-hot-toast';

interface AccountInfo {
  name: string;
  login: string;
  server: string;
  balance: number;
  equity: number;
  free_margin: number;
  leverage: number;
  currency: string;
}

interface LogEntry {
  time: string;
  level: string;
  msg: string;
}

interface SignalData {
  action: 'BUY' | 'SELL' | 'HOLD';
  score: number;
  rsi: number | null;
  macd: number | null;
  atr: number | null;
  price: number | null;
  reason: string | null;
}

interface MlData {
  action: 'BUY' | 'SELL' | 'HOLD';
  confidence: number | null;
  lr_pred: number | null;
  rf_pred: number | null;
  current_price: number | null;
}

export const LiveDashboard: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [trading, setTrading] = useState(false);
  const [mode, setMode] = useState<'paper' | 'metaapi' | 'bridge'>('paper');
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [signal, setSignal] = useState<SignalData | null>(null);
  const [ml, setMl] = useState<MlData | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);

  // Connection Fields
  const [mapiToken, setMapiToken] = useState('');
  const [mapiAccountId, setMapiAccountId] = useState('');
  const [accNum, setAccNum] = useState('');
  const [accPass, setAccPass] = useState('');
  const [accServer, setAccServer] = useState('');
  const [bridgeHost, setBridgeHost] = useState('localhost');
  const [bridgePort, setBridgePort] = useState('18812');

  // Algo Settings Fields
  const [algoSymbol, setAlgoSymbol] = useState('AAPL');
  const [algoTimeframe, setAlgoTimeframe] = useState('M5');
  const [algoRisk, setAlgoRisk] = useState('1.0');
  const [algoInterval, setAlgoInterval] = useState('300');
  const [useMl, setUseMl] = useState(true);
  const [startingAlgo, setStartingAlgo] = useState(false);
  const [stoppingAlgo, setStoppingAlgo] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await apiFetch('/mt5/status');
      if (data) {
        setConnected(!!data.connected);
        setTrading(!!data.trading);
        if (data.status_msg) {
          // parse or update state from status message
        }
        if (data.account && Object.keys(data.account).length) {
          setAccount(data.account);
        }
        if (data.last_signal && data.last_signal.action) {
          setSignal(data.last_signal);
        }
        if (data.last_ml && data.last_ml.action) {
          setMl(data.last_ml);
        }
        if (data.log) {
          setLogs(data.log);
        }
      }
    } catch (err) {
      console.error('Failed to fetch status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // Adjust default symbols based on trading mode
  const handleModeChange = (newMode: 'paper' | 'metaapi' | 'bridge') => {
    setMode(newMode);
    if (newMode === 'paper') {
      setAlgoSymbol('AAPL');
    } else {
      setAlgoSymbol('EURUSD');
    }
  };

  const handleConnect = async () => {
    let payload: any = {};
    if (mode === 'metaapi') {
      if (!mapiToken || !mapiAccountId) {
        toast.error('Token and Account ID required for MetaApi');
        return;
      }
      payload = {
        metaapi_token: mapiToken,
        metaapi_account_id: mapiAccountId,
        account: 0, password: '', server: '', host: 'localhost', port: 18812,
      };
    } else if (mode === 'paper') {
      payload = { account: 0, password: '', server: '', host: 'localhost', port: 18812 };
    } else {
      if (!accNum || !accPass || !accServer) {
        toast.error('Account login credentials required');
        return;
      }
      payload = {
        account: parseInt(accNum),
        password: accPass,
        server: accServer,
        host: bridgeHost || 'localhost',
        port: parseInt(bridgePort || '18812'),
      };
    }

    setLoading(true);
    try {
      const res = await apiFetch('/mt5/connect', {
        method: 'POST',
        body: payload
      });
      if (res.ok) {
        toast.success(`Connected in ${mode} mode!`);
        fetchStatus();
      } else {
        toast.error(res.error || 'Connection failed');
      }
    } catch (err) {
      toast.error('Failed to connect to MT5 bridge');
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      const res = await apiFetch('/mt5/disconnect', { method: 'POST' });
      if (res.ok) {
        toast.success('Disconnected');
        setConnected(false);
        setAccount(null);
        fetchStatus();
      }
    } catch (err) {
      toast.error('Disconnect failed');
    }
  };

  const handleStartAlgo = async () => {
    setStartingAlgo(true);
    try {
      const res = await apiFetch('/mt5/start', {
        method: 'POST',
        body: {
          symbol: algoSymbol.toUpperCase(),
          timeframe: algoTimeframe,
          risk_pct: parseFloat(algoRisk),
          interval: parseInt(algoInterval),
          use_ml: useMl,
        }
      });
      if (res.ok) {
        toast.success('Algorithmic engine started successfully');
        setTrading(true);
      } else {
        toast.error(res.error || 'Could not start engine');
      }
    } catch (err) {
      toast.error('Failed to start algo');
    } finally {
      setStartingAlgo(false);
    }
  };

  const handleStopAlgo = async () => {
    setStoppingAlgo(true);
    try {
      const res = await apiFetch('/mt5/stop', { method: 'POST' });
      if (res.ok) {
        toast.success('Algorithmic engine stopped');
        setTrading(false);
      }
    } catch (err) {
      toast.error('Failed to stop algo');
    } finally {
      setStoppingAlgo(false);
    }
  };

  const handleCloseAll = async () => {
    if (!confirm(`Close ALL open positions for ${algoSymbol.toUpperCase()}?`)) return;
    try {
      const res = await apiFetch('/mt5/close_all', {
        method: 'POST',
        body: { symbol: algoSymbol.toUpperCase() }
      });
      if (res.ok) {
        toast.success(`Closed ${res.closed} position(s)`);
      }
    } catch (err) {
      toast.error('Close positions failed');
    }
  };

  const getLevelColor = (level: string) => {
    const l = level.toUpperCase();
    if (l.includes('ERROR')) return 'error.main';
    if (l.includes('WARN')) return 'warning.main';
    if (l.includes('SIGNAL')) return 'secondary.main';
    if (l.includes('TRADE') || l.includes('PAPER-TRADE')) return 'primary.main';
    if (l.includes('CLOSE') || l.includes('PAPER-CLOSE')) return 'success.main';
    return 'text.secondary';
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header Banner */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1.5, color: 'text.primary' }}>
            <Zap color="#3b82f6" />
            MetaTrader 5 Algorithmic Hub
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Automate trade execution using technical indicators confluences and machine learning models.
          </Typography>
        </Box>
        <Chip 
          label={connected ? (trading ? "Algo Running" : "Connected") : "Disconnected"}
          color={connected ? (trading ? "success" : "primary") : "default"}
          icon={<Activity size={16} />}
          sx={{ fontWeight: 'bold' }}
        />
      </Box>

      {/* Warnings & Notices */}
      <Card sx={{ bgcolor: 'rgba(234,179,8,0.02)', border: '1px solid rgba(234,179,8,0.1)' }}>
        <CardContent sx={{ display: 'flex', gap: 2, p: 2, '&:last-child': { pb: 2 } }}>
          <AlertTriangle color="#fbbf24" style={{ flexShrink: 0 }} />
          <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
            <strong>Operator Advisory:</strong> Algorithmic trading involves substantial risk of loss. Simulated balance is used by default. Real trading requires a Pro package subscription, explicit configuration of Metatrader 5 servers, and direct local bridge deployment.
          </Typography>
        </CardContent>
      </Card>

      <Grid container spacing={3}>
        {/* Left Side: Configuration Controls */}
        <Grid size={{ xs: 12, lg: 4 }} sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* Connection Settings */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Key size={16} color="#3b82f6" />
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Bridge Connection</Typography>
            </Box>
            <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* Mode Selector */}
              <Box sx={{ display: 'flex', gap: 0.5, border: '1px solid rgba(255,255,255,0.05)', p: 0.5, borderRadius: 2, bgcolor: 'rgba(0,0,0,0.15)' }}>
                {(['paper', 'metaapi', 'bridge'] as const).map((m) => (
                  <Button
                    key={m}
                    size="small"
                    fullWidth
                    variant={mode === m ? 'contained' : 'text'}
                    onClick={() => handleModeChange(m)}
                    sx={{ fontWeight: 'bold', textTransform: 'capitalize' }}
                  >
                    {m === 'bridge' ? 'Direct MT5' : m}
                  </Button>
                ))}
              </Box>

              {/* Mode specific fields */}
              {mode === 'paper' && (
                <Box sx={{ p: 1.5, border: '1px solid rgba(251,191,36,0.15)', borderRadius: 2, bgcolor: 'rgba(251,191,36,0.02)' }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5, fontWeight: 'bold' }}>
                    Paper trading mode enabled.
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>
                    Provides a $10,000 virtual balance and fetches real-time quote feeds via yfinance without needing local software.
                  </Typography>
                </Box>
              )}

              {mode === 'metaapi' && (
                <>
                  <TextField 
                    label="MetaApi Token" 
                    type="password"
                    size="small"
                    value={mapiToken}
                    onChange={(e) => setMapiToken(e.target.value)}
                    placeholder="MetaApi dashboard token"
                    fullWidth
                  />
                  <TextField 
                    label="MetaApi Account ID" 
                    size="small"
                    value={mapiAccountId}
                    onChange={(e) => setMapiAccountId(e.target.value)}
                    placeholder="MetaApi account ID hash"
                    fullWidth
                  />
                </>
              )}

              {mode === 'bridge' && (
                <>
                  <TextField 
                    label="Account Login" 
                    size="small"
                    type="number"
                    value={accNum}
                    onChange={(e) => setAccNum(e.target.value)}
                    placeholder="MT5 account number"
                    fullWidth
                  />
                  <TextField 
                    label="Account Password" 
                    type="password"
                    size="small"
                    value={accPass}
                    onChange={(e) => setAccPass(e.target.value)}
                    placeholder="Broker password"
                    fullWidth
                  />
                  <TextField 
                    label="Broker Server" 
                    size="small"
                    value={accServer}
                    onChange={(e) => setAccServer(e.target.value)}
                    placeholder="e.g. ICMarkets-Demo"
                    fullWidth
                  />
                  <Box sx={{ display: 'flex', gap: 1.5 }}>
                    <TextField 
                      label="Host" 
                      size="small"
                      value={bridgeHost}
                      onChange={(e) => setBridgeHost(e.target.value)}
                      fullWidth
                    />
                    <TextField 
                      label="Port" 
                      size="small"
                      value={bridgePort}
                      onChange={(e) => setBridgePort(e.target.value)}
                      fullWidth
                    />
                  </Box>
                </>
              )}

              {!connected ? (
                <Button 
                  variant="contained" 
                  color="primary" 
                  fullWidth 
                  onClick={handleConnect}
                  disabled={loading}
                  sx={{ fontWeight: 'bold' }}
                >
                  {loading ? 'Connecting...' : 'Connect Bridge'}
                </Button>
              ) : (
                <Button 
                  variant="outlined" 
                  color="error" 
                  fullWidth 
                  onClick={handleDisconnect}
                  sx={{ fontWeight: 'bold' }}
                >
                  Disconnect Bridge
                </Button>
              )}
            </CardContent>
          </Card>

          {/* Account Details */}
          {connected && account && (
            <Card>
              <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: 1 }}>
                <ShieldCheck size={16} color="#10b981" />
                <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Broker Account</Typography>
              </Box>
              <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">Name</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{account.name}</Typography>
                </Box>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">Login ID</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{account.login}</Typography>
                </Box>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">Server</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{account.server}</Typography>
                </Box>
                <Divider />
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">Balance</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'success.main' }}>
                    {account.currency} {account.balance.toLocaleString()}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">Equity</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'success.main' }}>
                    {account.currency} {account.equity.toLocaleString()}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">Leverage</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 'bold' }}>1:{account.leverage}</Typography>
                </Box>
              </CardContent>
            </Card>
          )}

          {/* Algorithm Config Panel */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Settings size={16} color="#8b5cf6" />
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Algorithm Settings</Typography>
            </Box>
            <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
              <TextField 
                label="Target Symbol"
                size="small"
                value={algoSymbol}
                onChange={(e) => setAlgoSymbol(e.target.value)}
                placeholder="EURUSD or AAPL"
                fullWidth
              />

              <Box sx={{ display: 'flex', gap: 1.5 }}>
                <Select 
                  value={algoTimeframe}
                  onChange={(e) => setAlgoTimeframe(e.target.value)}
                  size="small"
                  fullWidth
                >
                  <MenuItem value="M1">M1 (1 Min)</MenuItem>
                  <MenuItem value="M5">M5 (5 Min)</MenuItem>
                  <MenuItem value="M15">M15 (15 Min)</MenuItem>
                  <MenuItem value="H1">H1 (1 Hour)</MenuItem>
                </Select>
                <TextField 
                  label="Risk per Trade (%)"
                  size="small"
                  type="number"
                  value={algoRisk}
                  onChange={(e) => setAlgoRisk(e.target.value)}
                  fullWidth
                />
              </Box>

              <TextField 
                label="Interval Check (sec)"
                size="small"
                type="number"
                value={algoInterval}
                onChange={(e) => setAlgoInterval(e.target.value)}
                fullWidth
              />

              <FormControlLabel 
                control={
                  <Switch 
                    checked={useMl} 
                    onChange={(e) => setUseMl(e.target.checked)} 
                    color="primary"
                  />
                }
                label="ML Ensemble Filtering"
              />

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mt: 1 }}>
                <Button
                  variant="contained"
                  color="success"
                  disabled={!connected || trading || startingAlgo}
                  onClick={handleStartAlgo}
                  startIcon={<Play size={16} />}
                  sx={{ fontWeight: 'bold' }}
                >
                  {startingAlgo ? 'Starting...' : 'Start Algorithm'}
                </Button>
                <Button
                  variant="contained"
                  color="error"
                  disabled={!connected || !trading || stoppingAlgo}
                  onClick={handleStopAlgo}
                  startIcon={<Square size={16} />}
                  sx={{ fontWeight: 'bold' }}
                >
                  {stoppingAlgo ? 'Stopping...' : 'Stop Algorithm'}
                </Button>
                <Button
                  variant="outlined"
                  color="warning"
                  onClick={handleCloseAll}
                  disabled={!connected}
                  sx={{ fontWeight: 'bold' }}
                >
                  Close All Positions
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Right Side: Signal overview & logging console */}
        <Grid size={{ xs: 12, lg: 8 }} sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* Live Signal Panel */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyItems: 'center', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Live Signals</Typography>
              {useMl && ml && (
                <Chip label="ML Ensemble Mode" size="small" color="primary" sx={{ height: 18, fontSize: '0.65rem', fontWeight: 'bold' }} />
              )}
            </Box>
            <CardContent sx={{ p: 3 }}>
              <Grid container spacing={2}>
                <Grid size={{ xs: 6, sm: 3 }}>
                  <Box sx={{ border: '1px solid rgba(255,255,255,0.05)', borderRadius: 2, p: 2, textAlign: 'center', bgcolor: 'rgba(0,0,0,0.1)' }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', display: 'block', mb: 0.5 }}>Confluence Signal</Typography>
                    <Chip 
                      label={signal?.action || 'HOLD'} 
                      color={signal?.action === 'BUY' ? 'success' : signal?.action === 'SELL' ? 'error' : 'default'}
                      size="small"
                      sx={{ fontWeight: 'bold' }}
                    />
                  </Box>
                </Grid>
                <Grid size={{ xs: 6, sm: 3 }}>
                  <Box sx={{ border: '1px solid rgba(255,255,255,0.05)', borderRadius: 2, p: 2, textAlign: 'center', bgcolor: 'rgba(0,0,0,0.1)' }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', display: 'block', mb: 0.5 }}>RSI (14)</Typography>
                    <Typography variant="h6" sx={{ fontWeight: 'bold' }}>{signal?.rsi?.toFixed(1) || '-'}</Typography>
                  </Box>
                </Grid>
                <Grid size={{ xs: 6, sm: 3 }}>
                  <Box sx={{ border: '1px solid rgba(255,255,255,0.05)', borderRadius: 2, p: 2, textAlign: 'center', bgcolor: 'rgba(0,0,0,0.1)' }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', display: 'block', mb: 0.5 }}>MACD Histogram</Typography>
                    <Typography variant="h6" sx={{ fontWeight: 'bold' }}>{signal?.macd?.toFixed(4) || '-'}</Typography>
                  </Box>
                </Grid>
                <Grid size={{ xs: 6, sm: 3 }}>
                  <Box sx={{ border: '1px solid rgba(255,255,255,0.05)', borderRadius: 2, p: 2, textAlign: 'center', bgcolor: 'rgba(0,0,0,0.1)' }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', display: 'block', mb: 0.5 }}>ATR (14)</Typography>
                    <Typography variant="h6" sx={{ fontWeight: 'bold' }}>{signal?.atr?.toFixed(4) || '-'}</Typography>
                  </Box>
                </Grid>
              </Grid>

              {/* Machine learning details */}
              {useMl && ml && (
                <Box sx={{ mt: 3, pt: 3, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', display: 'block', mb: 2, letterSpacing: 0.5, textTransform: 'uppercase' }}>
                    ML Forecast Predictions
                  </Typography>
                  <Grid container spacing={2}>
                    <Grid size={{ xs: 12, sm: 4 }}>
                      <Box sx={{ border: '1px solid rgba(255,255,255,0.05)', borderRadius: 2, p: 2, bgcolor: 'rgba(0,0,0,0.15)' }}>
                        <Typography variant="caption" color="text.secondary">ML Signal / Confidence</Typography>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                          <Chip 
                            label={ml.action} 
                            color={ml.action === 'BUY' ? 'success' : ml.action === 'SELL' ? 'error' : 'default'}
                            size="small"
                            sx={{ fontWeight: 'bold' }}
                          />
                          {ml.confidence !== null && (
                            <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{ml.confidence.toFixed(0)}%</Typography>
                          )}
                        </Box>
                      </Box>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 4 }}>
                      <Box sx={{ border: '1px solid rgba(255,255,255,0.05)', borderRadius: 2, p: 2, bgcolor: 'rgba(0,0,0,0.15)' }}>
                        <Typography variant="caption" color="text.secondary">Logistic Reg Forecast</Typography>
                        <Typography variant="body1" sx={{ fontWeight: 'bold', mt: 0.5 }}>
                          {ml.lr_pred ? `$${ml.lr_pred.toFixed(2)}` : '-'}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 4 }}>
                      <Box sx={{ border: '1px solid rgba(255,255,255,0.05)', borderRadius: 2, p: 2, bgcolor: 'rgba(0,0,0,0.15)' }}>
                        <Typography variant="caption" color="text.secondary">Random Forest Target</Typography>
                        <Typography variant="body1" sx={{ fontWeight: 'bold', mt: 0.5 }}>
                          {ml.rf_pred ? `$${ml.rf_pred.toFixed(2)}` : '-'}
                        </Typography>
                      </Box>
                    </Grid>
                  </Grid>
                  {signal?.reason && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2, lineHeight: 1.4 }}>
                      Reasoning: {signal.reason}
                    </Typography>
                  )}
                </Box>
              )}
            </CardContent>
          </Card>

          {/* Real-time Log Console */}
          <Card sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Real-time Console Log</Typography>
            </Box>
            <CardContent sx={{ p: 0, flex: 1, display: 'flex', flexDirection: 'column' }}>
              <Box sx={{ maxHeight: 360, overflowY: 'auto', flex: 1 }}>
                <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', width: 90, bgcolor: 'background.paper' }}>Time</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', width: 110, bgcolor: 'background.paper' }}>Level</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', bgcolor: 'background.paper' }}>Message</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {logs.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={3} sx={{ py: 6, textClassName: 'empty', textAlign: 'center', color: 'text.secondary' }}>
                            <HelpCircle size={24} style={{ opacity: 0.3, marginBottom: 4 }} />
                            <Typography variant="caption" sx={{ display: 'block' }}>Connect bridge to print messages.</Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        logs.map((e, idx) => (
                          <TableRow key={idx}>
                            <TableCell sx={{ py: 1, color: 'text.secondary', fontFamily: 'monospace', fontSize: '0.75rem' }}>{e.time}</TableCell>
                            <TableCell sx={{ py: 1, fontWeight: 'bold', color: getLevelColor(e.level), fontSize: '0.75rem' }}>
                              {e.level}
                            </TableCell>
                            <TableCell sx={{ py: 1, fontFamily: 'monospace', fontSize: '0.75rem' }}>{e.msg}</TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};
