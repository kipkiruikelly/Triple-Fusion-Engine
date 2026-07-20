import React, { useState, useEffect } from 'react';
import { Trophy, AlertCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { 
  Box, Typography, Card, CardContent, Grid, Button, Chip, 
  CircularProgress, Divider 
} from '@mui/material';
import { apiFetch } from '../utils/api';

interface StrategyMetrics {
  strategy: string;
  equity: number;
  currency: string;
  metrics: {
    sufficient: boolean;
    total_return_pct: number;
    trades: number;
    min_trades: number;
    sharpe: number | null;
    win_rate_pct: number | null;
  };
}

interface LeaderboardUser {
  username: string;
  strategy: string;
  sharpe: number | null;
  return_pct: number;
  win_rate: number | null;
  trades: number;
  equity: number;
  rank: number;
}

export const TradersDashboard: React.FC = () => {
  const [optedIn, setOptedIn] = useState(false);
  const [loadingPortfolio, setLoadingPortfolio] = useState(true);
  const [loadingLeaderboard, setLoadingLeaderboard] = useState(true);
  const [strategies, setStrategies] = useState<StrategyMetrics[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardUser[]>([]);
  const [currency, setCurrency] = useState('USD');
  const [togglingOptIn, setTogglingOptIn] = useState(false);

  const fetchMyPortfolio = async () => {
    setLoadingPortfolio(true);
    try {
      const res = await apiFetch('/api/paper/my-portfolio');
      if (res.ok) {
        setOptedIn(res.opted_in);
        setStrategies(res.strategies || []);
        setCurrency(res.currency || 'USD');
      }
    } catch (err) {
      console.error('Failed to load paper portfolio settings:', err);
    } finally {
      setLoadingPortfolio(false);
    }
  };

  const fetchLeaderboard = async () => {
    setLoadingLeaderboard(true);
    try {
      const res = await apiFetch('/api/leaderboard/users');
      if (res.ok && res.leaderboard) {
        setLeaderboard(res.leaderboard);
      }
    } catch (err) {
      console.error('Failed to load trader leaderboard:', err);
    } finally {
      setLoadingLeaderboard(false);
    }
  };

  useEffect(() => {
    fetchMyPortfolio();
    fetchLeaderboard();
  }, []);

  const handleToggleOpt = async () => {
    setTogglingOptIn(true);
    const url = optedIn ? '/api/paper/opt-out' : '/api/paper/opt-in';
    try {
      const res = await apiFetch(url, { method: 'POST' });
      if (res.ok) {
        toast.success(optedIn ? 'Deactivated paper trading.' : 'Activated paper trading!');
        fetchMyPortfolio();
        fetchLeaderboard();
      } else {
        toast.error(res.error || 'Failed to update preferences');
      }
    } catch (err) {
      toast.error('Network error occurred.');
    } finally {
      setTogglingOptIn(false);
    }
  };

  const rankEmoji = ['🥇', '🥈', '🥉'];

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box>
        <Typography variant="h2" sx={{ display: 'flex', alignItems: 'center', gap: 1.5, fontSize: '1.5rem', color: 'text.primary', fontWeight: 'bold' }}>
          <Trophy color="#8b5cf6" />
          Trader Leaderboard
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Ranked by Sharpe ratio (return relative to volatility) from real paper-trading portfolios.
          Risk is standardized: every trade is sized off a fixed % of equity by our automated risk engine.
        </Typography>
      </Box>

      {/* My Portfolio Section */}
      <Card sx={{ 
        bgcolor: 'background.paper',
        border: '1px solid rgba(255,255,255,0.05)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.2)'
      }}>
        <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                My Paper Portfolio
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                Participate in the global trading leaderboard with your own virtual balance.
              </Typography>
            </Box>
            
            <Button
              id="opt-toggle-btn"
              variant={optedIn ? "outlined" : "contained"}
              color={optedIn ? "inherit" : "primary"}
              onClick={handleToggleOpt}
              disabled={loadingPortfolio || togglingOptIn}
              startIcon={togglingOptIn ? <CircularProgress size={16} color="inherit" /> : null}
              sx={{ fontWeight: 'bold' }}
            >
              {optedIn ? 'Stop Paper Trading' : 'Start My Paper Portfolio'}
            </Button>
          </Box>

          <Divider sx={{ borderColor: 'rgba(255,255,255,0.05)' }} />

          {loadingPortfolio ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress size={24} />
            </Box>
          ) : !optedIn ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, p: 2, bgcolor: 'rgba(255,255,255,0.02)', borderRadius: 2, border: '1px solid rgba(255,255,255,0.05)' }}>
              <AlertCircle size={18} color="#a0a5b1" />
              <Typography variant="body2" color="text.secondary">
                You haven't started a paper portfolio yet. Opt in above to trade both strategies with your own virtual {currency} balance.
              </Typography>
            </Box>
          ) : (
            <Grid container spacing={3}>
              {strategies.map((s, idx) => (
                <Grid size={{ xs: 12, md: 6 }} key={idx}>
                  <Card sx={{ bgcolor: 'rgba(0,0,0,0.15)', border: '1px solid rgba(255,255,255,0.03)' }}>
                    <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <Typography variant="subtitle2" sx={{ textTransform: 'uppercase', color: 'primary.main', fontWeight: 'bold', letterSpacing: 0.5 }}>
                        {s.strategy.replace('_', ' ')}
                      </Typography>
                      
                      <Grid container spacing={2}>
                        <Grid size={4}>
                          <Typography variant="caption" color="text.secondary">Equity</Typography>
                          <Typography variant="body1" sx={{ fontWeight: 'bold' }}>
                            ${s.equity.toLocaleString()}
                          </Typography>
                        </Grid>
                        
                        <Grid size={4}>
                          <Typography variant="caption" color="text.secondary">Return</Typography>
                          <Typography variant="body1" sx={{ fontWeight: 'bold', color: s.metrics.total_return_pct >= 0 ? 'success.main' : 'error.main' }}>
                            {s.metrics.sufficient ? `${s.metrics.total_return_pct >= 0 ? '+' : ''}${s.metrics.total_return_pct}%` : '-'}
                          </Typography>
                        </Grid>
                        
                        <Grid size={4}>
                          <Typography variant="caption" color="text.secondary">Trades</Typography>
                          <Typography variant="body1" sx={{ fontWeight: 'bold' }}>
                            {s.metrics.trades}
                          </Typography>
                        </Grid>
                      </Grid>

                      {!s.metrics.sufficient && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, bgcolor: 'rgba(255,255,255,0.02)', p: 1, borderRadius: 1 }}>
                          Requires {s.metrics.min_trades} closed trades to show ratio metrics ({s.metrics.trades} so far).
                        </Typography>
                      )}
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          )}
        </CardContent>
      </Card>

      {/* Leaderboard Top 10 */}
      <Box>
        <Typography variant="h6" sx={{ fontWeight: 'bold', mb: 2, color: 'text.primary' }}>
          Top 10 Rankings
        </Typography>
        
        {loadingLeaderboard ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
            <CircularProgress color="primary" />
          </Box>
        ) : leaderboard.length === 0 ? (
          <Card sx={{ display: 'flex', justifyContent: 'center', py: 8, border: '1px dashed rgba(255,255,255,0.05)' }}>
            <Typography color="text.secondary">No traders have enough closed trades yet. Be the first!</Typography>
          </Card>
        ) : (
          <Grid container spacing={2}>
            {leaderboard.map((user, idx) => (
              <Grid size={{ xs: 12, sm: 6, md: 4 }} key={idx}>
                <Card sx={{ 
                  bgcolor: 'background.paper',
                  border: '1px solid rgba(255,255,255,0.05)',
                  transition: 'transform 0.15s',
                  '&:hover': { transform: 'translateY(-2px)' }
                }}>
                  <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Typography variant="body1" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                        <span style={{ fontSize: '1.2rem' }}>
                          {idx < 3 ? rankEmoji[idx] : `#${idx + 1}`}
                        </span>
                        {user.username}
                      </Typography>
                      <Chip
                        label={user.strategy === 'ml_ensemble' ? 'ML Ensemble' : 'Alpha Rules'}
                        size="small"
                        color={user.strategy === 'ml_ensemble' ? 'primary' : 'secondary'}
                        variant="outlined"
                        sx={{ fontWeight: 'bold', fontSize: '0.7rem' }}
                      />
                    </Box>
                    
                    <Grid container spacing={1} sx={{ bgcolor: 'rgba(0,0,0,0.15)', p: 1.5, borderRadius: 2 }}>
                      <Grid size={6}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Sharpe Ratio</Typography>
                        <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                          {user.sharpe !== null ? user.sharpe.toFixed(2) : '-'}
                        </Typography>
                      </Grid>
                      <Grid size={6}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Return</Typography>
                        <Typography variant="body2" sx={{ fontWeight: 'bold', color: user.return_pct >= 0 ? 'success.main' : 'error.main' }}>
                          {user.return_pct >= 0 ? '+' : ''}{user.return_pct}%
                        </Typography>
                      </Grid>
                      <Grid size={6} sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Win Rate</Typography>
                        <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                          {user.win_rate !== null ? `${user.win_rate}%` : '-'}
                        </Typography>
                      </Grid>
                      <Grid size={6} sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Trades</Typography>
                        <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                          {user.trades}
                        </Typography>
                      </Grid>
                    </Grid>
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>
        )}
      </Box>
    </Box>
  );
};
