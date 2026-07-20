import React, { useState } from 'react';
import { 
  Box, Typography, Grid, Card, CardContent, Button, TextField, 
  LinearProgress, Alert, AlertTitle
} from '@mui/material';
import { apiFetch } from '../utils/api';
import toast from 'react-hot-toast';

interface RiskResult {
  shares: number;
  position_val: number;
  risk_amount: number;
  risk_per_sh: number;
  rr_ratio: number;
  potential_pnl: number;
  kelly_shares: number;
  kelly_pct: number;
}

export const RiskDashboard: React.FC = () => {
  const [ticker, setTicker] = useState('');
  const [account, setAccount] = useState('10000');
  const [riskPct, setRiskPct] = useState('1.0');
  const [entry, setEntry] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [target, setTarget] = useState('');
  
  const [result, setResult] = useState<RiskResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleCalculate = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const accountNum = parseFloat(account);
    const riskPctNum = parseFloat(riskPct);
    const entryNum = parseFloat(entry);
    const stopNum = parseFloat(stopLoss);
    const targetNum = parseFloat(target);

    if (isNaN(accountNum) || isNaN(riskPctNum) || isNaN(entryNum) || isNaN(stopNum) || isNaN(targetNum)) {
      toast.error('Please enter valid numerical values for calculation');
      return;
    }

    if (entryNum <= 0 || stopNum <= 0 || targetNum <= 0) {
      toast.error('Prices must be greater than zero');
      return;
    }

    if (entryNum === stopNum) {
      toast.error('Entry price and stop loss cannot be equal');
      return;
    }

    setLoading(true);
    try {
      const data = await apiFetch('/api/risk/calculate', {
        method: 'POST',
        body: {
          account: accountNum,
          risk_pct: riskPctNum,
          entry: entryNum,
          stop_loss: stopNum,
          target: targetNum,
          ticker: ticker.toUpperCase().trim()
        }
      });

      if (data.ok) {
        setResult(data);
        toast.success('Calculation completed!');
      } else {
        toast.error(data.error || 'Failed to calculate');
      }
    } catch (err) {
      toast.error('An error occurred during calculation');
    } finally {
      setLoading(false);
    }
  };

  const getRrColor = (ratio: number) => {
    if (ratio >= 3) return '#10b981'; // Green
    if (ratio >= 1.5) return '#8b5cf6'; // Orange/Yellow
    return '#ef4444'; // Red
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box>
        <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
          Risk & Position Size Calculator
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Calculate exact position size, risk-reward ratios, and optimal Kelly Criterion sizing before every trade.
        </Typography>
      </Box>

      {/* Grid Layout */}
      <Grid container spacing={3}>
        {/* Left Column: Form Parameters */}
        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <Box sx={{ px: 3, py: 2.5, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                Trade Sizing Parameters
              </Typography>
            </Box>
            <CardContent sx={{ p: 3 }}>
              <form onSubmit={handleCalculate} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <Grid container spacing={2}>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField 
                      label="Ticker symbol"
                      placeholder="e.g. AAPL"
                      value={ticker}
                      onChange={(e) => setTicker(e.target.value)}
                      fullWidth
                    />
                  </Grid>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField 
                      label="Account Size ($)"
                      type="number"
                      value={account}
                      onChange={(e) => setAccount(e.target.value)}
                      fullWidth
                      required
                    />
                  </Grid>
                  <Grid size={12}>
                    <TextField 
                      label="Risk Per Trade (%)"
                      type="number"
                      value={riskPct}
                      onChange={(e) => setRiskPct(e.target.value)}
                      slotProps={{ htmlInput: { step: "0.1", min: "0.1", max: "10" } }}
                      fullWidth
                      required
                    />
                  </Grid>
                  <Grid size={4}>
                    <TextField 
                      label="Entry Price ($)"
                      type="number"
                      value={entry}
                      onChange={(e) => setEntry(e.target.value)}
                      slotProps={{ htmlInput: { step: "0.01" } }}
                      fullWidth
                      required
                    />
                  </Grid>
                  <Grid size={4}>
                    <TextField 
                      label="Stop Loss ($)"
                      type="number"
                      value={stopLoss}
                      onChange={(e) => setStopLoss(e.target.value)}
                      slotProps={{ htmlInput: { step: "0.01" } }}
                      fullWidth
                      required
                    />
                  </Grid>
                  <Grid size={4}>
                    <TextField 
                      label="Target Price ($)"
                      type="number"
                      value={target}
                      onChange={(e) => setTarget(e.target.value)}
                      slotProps={{ htmlInput: { step: "0.01" } }}
                      fullWidth
                      required
                    />
                  </Grid>
                </Grid>

                <Button 
                  type="submit" 
                  variant="contained" 
                  color="primary"
                  disabled={loading}
                  sx={{ mt: 1, py: 1.2, fontWeight: 'bold' }}
                >
                  {loading ? 'Calculating...' : 'Calculate Sizing'}
                </Button>
              </form>
            </CardContent>
          </Card>
        </Grid>

        {/* Right Column: Results */}
        <Grid size={{ xs: 12, md: 6 }}>
          <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ px: 3, py: 2.5, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                Position Sizing Results
              </Typography>
            </Box>
            <CardContent sx={{ p: 3, flex: 1, display: 'flex', flexDirection: 'column', justifyItems: 'center', justifyContent: 'center' }}>
              {!result ? (
                <Box sx={{ py: 6, textAlign: 'center', color: 'text.secondary' }}>
                  Enter trade parameters and click Calculate Sizing.
                </Box>
              ) : (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <Grid container spacing={2}>
                    <Grid size={6}>
                      <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <Typography variant="caption" color="text.secondary">Position Size</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'primary.main', mt: 0.5 }}>
                          {result.shares.toLocaleString(undefined, { maximumFractionDigits: 1 })} shares
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={6}>
                      <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <Typography variant="caption" color="text.secondary">Notional Value</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>
                          ${result.position_val.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={6}>
                      <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <Typography variant="caption" color="text.secondary">Max Risk Amount</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'error.main', mt: 0.5 }}>
                          -${result.risk_amount.toLocaleString()}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={6}>
                      <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <Typography variant="caption" color="text.secondary">Potential Profit</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'success.main', mt: 0.5 }}>
                          +${result.potential_pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={6}>
                      <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <Typography variant="caption" color="text.secondary">Risk Per Share</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>
                          ${result.risk_per_sh.toFixed(2)}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={6}>
                      <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <Typography variant="caption" color="text.secondary">Kelly Optimal Size</Typography>
                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'text.primary', mt: 0.5 }}>
                          {result.kelly_shares.toLocaleString(undefined, { maximumFractionDigits: 1 })} sh ({result.kelly_pct}%)
                        </Typography>
                      </Box>
                    </Grid>
                  </Grid>

                  {/* R:R Visual indicator */}
                  <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                      <Typography variant="caption" color="text.secondary">Risk / Reward Ratio</Typography>
                      <Typography variant="body2" sx={{ fontWeight: 'bold', color: getRrColor(result.rr_ratio) }}>
                        {result.rr_ratio.toFixed(2)} : 1
                      </Typography>
                    </Box>
                    <LinearProgress 
                      variant="determinate" 
                      value={Math.min(100, (result.rr_ratio / 5) * 100)} 
                      sx={{ 
                        height: 8, 
                        borderRadius: 4, 
                        bgcolor: 'rgba(255,255,255,0.05)',
                        '& .MuiLinearProgress-bar': {
                          bgcolor: getRrColor(result.rr_ratio)
                        }
                      }}
                    />
                    <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', mt: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">Poor (&lt;1)</Typography>
                      <Typography variant="caption" color="text.secondary">Good (2+)</Typography>
                      <Typography variant="caption" color="text.secondary">Excellent (3+)</Typography>
                    </Box>
                  </Box>

                  {/* Narrative explainer */}
                  <Alert severity={result.rr_ratio >= 3 ? 'success' : result.rr_ratio >= 1.5 ? 'info' : 'warning'} sx={{ border: '1px solid rgba(255,255,255,0.05)' }}>
                    <AlertTitle sx={{ fontWeight: 'bold' }}>Trade Setup Analysis</AlertTitle>
                    Buying <strong>{result.shares.toLocaleString(undefined, { maximumFractionDigits: 1 })} shares</strong> of {ticker || 'Asset'} at <strong>${entry}</strong>, with a stop loss at <strong>${stopLoss}</strong> (risking ${result.risk_amount}) and profit target at <strong>${target}</strong> (potential return of ${result.potential_pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}).
                    <br />
                    {result.rr_ratio < 1.5 
                      ? '⚠️ Risk/Reward is below 1.5. Consider widening your target or tightening the stop loss to protect capital.' 
                      : result.rr_ratio >= 3 
                      ? '✅ Excellent Risk/Reward ratio. Setup meets institutional standards.' 
                      : '✓ Acceptable Risk/Reward ratio. Setup is viable.'}
                  </Alert>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};
