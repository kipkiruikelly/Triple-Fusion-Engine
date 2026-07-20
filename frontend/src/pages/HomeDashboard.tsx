import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Award, Flame, AlertCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { 
  Box, Typography, Card, CardContent, Grid, Button, Chip, 
  CircularProgress, LinearProgress, Divider, Avatar 
} from '@mui/material';
import { apiFetch } from '../utils/api';

interface PredictionRow {
  id: number;
  ticker: string;
  interval: string;
  current_price: number;
  direction: 'UP' | 'DOWN' | 'HOLD';
  confidence: number;
  predicted_at: string | null;
}

interface WatchlistItem {
  id: number;
  ticker: string;
}

export const HomeDashboard: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [loadingStats, setLoadingStats] = useState(true);
  const [predictions, setPredictions] = useState<PredictionRow[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  
  // Paper Trading stats
  const [paperOptedIn, setPaperOptedIn] = useState(false);
  const [paperStats, setPaperStats] = useState<any>({ open: 0, closed: 0, pnl: 0, balance: null });
  const [currency, setCurrency] = useState('KES');

  useEffect(() => {
    const fetchHomeData = async () => {
      setLoadingStats(true);
      try {
        // Fetch prediction history (recent 5)
        const predRes = await apiFetch('/api/predict/history?limit=5');
        if (predRes.ok && predRes.history) {
          setPredictions(predRes.history);
        }

        // Fetch Watchlist
        const wlRes = await apiFetch('/api/watchlist');
        if (wlRes.ok && wlRes.watchlist) {
          setWatchlist(wlRes.watchlist);
        }

        // Fetch Paper Portfolio summary
        const paperRes = await apiFetch('/api/paper/my-portfolio');
        if (paperRes.ok) {
          setPaperOptedIn(paperRes.opted_in);
          setCurrency(paperRes.currency || 'KES');
          if (paperRes.strategies && paperRes.strategies.length > 0) {
            let totalEquity = 0;
            let totalOpen = 0;
            let totalClosed = 0;
            let totalPnl = 0;
            
            paperRes.strategies.forEach((s: any) => {
              totalEquity += s.equity;
              totalOpen += s.open_positions || 0;
              totalClosed += s.metrics?.trades || 0;
              totalPnl += (s.equity - s.starting_balance);
            });

            setPaperStats({
              balance: totalEquity,
              open: totalOpen,
              closed: totalClosed,
              pnl: totalPnl
            });
          }
        }
      } catch (err) {
        console.error('Error fetching home dashboard data:', err);
      } finally {
        setLoadingStats(false);
      }
    };

    if (user) {
      fetchHomeData();
    }
  }, [user]);

  if (!user) return null;

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Welcome Banner */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary', display: 'flex', alignItems: 'center', gap: 1.5 }}>
            Welcome back, {user.username}
            <Chip 
              label={user.is_pro ? 'PRO' : user.is_plus ? 'PLUS' : 'FREE'} 
              color="primary" 
              size="small" 
              sx={{ fontWeight: 'bold', height: 20 }}
            />
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {user.is_plus || user.is_pro 
              ? 'Unlimited predictions active on your plan.' 
              : `${user.predictions_remaining ?? 5} of 5 free predictions remaining today.`}
          </Typography>
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2.5, bgcolor: 'background.paper', p: 1.5, borderRadius: 2, border: '1px solid rgba(255,255,255,0.05)' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Award size={18} color="#8b5cf6" />
            <Typography variant="body2" sx={{ fontWeight: 'bold' }}>Level {user.level}</Typography>
          </Box>
          <Divider orientation="vertical" flexItem sx={{ borderColor: 'rgba(255,255,255,0.1)' }} />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Flame size={18} color="#ef4444" />
            <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{user.current_streak || 0} Day Streak</Typography>
          </Box>
        </Box>
      </Box>

      {/* Gamification progress bar */}
      <Card sx={{ bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.03)' }}>
        <CardContent sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 2 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'medium' }}>XP Progress</Typography>
          <LinearProgress 
            variant="determinate" 
            value={user.xp_into_level || 0} 
            sx={{ flex: 1, height: 6, borderRadius: 3, bgcolor: 'rgba(255,255,255,0.05)' }}
          />
          <Typography variant="caption" sx={{ fontWeight: 'bold', color: 'primary.main' }}>
            {user.xp} XP ({user.xp_into_level}/100)
          </Typography>
        </CardContent>
      </Card>

      {/* Stats Cards Row */}
      <Grid container spacing={3}>
        {/* Predictions Made */}
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <Card>
            <CardContent sx={{ p: 2.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, textTransform: 'uppercase', fontWeight: 'bold', letterSpacing: 0.5 }}>
                Predictions Made
              </Typography>
              <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                {user.total_predictions ?? 0}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                {user.predictions_today ?? 0} today · all time
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Watching Count */}
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <Card>
            <CardContent sx={{ p: 2.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, textTransform: 'uppercase', fontWeight: 'bold', letterSpacing: 0.5 }}>
                Watching
              </Typography>
              <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                {watchlist.length}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                Instruments tracked
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Paper balance */}
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <Card>
            <CardContent sx={{ p: 2.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, textTransform: 'uppercase', fontWeight: 'bold', letterSpacing: 0.5 }}>
                Paper Balance
              </Typography>
              {paperStats.balance !== null ? (
                <>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                    {paperStats.balance.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                    Virtual {currency} · {paperStats.open} open, {paperStats.closed} closed
                  </Typography>
                </>
              ) : (
                <>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.secondary' }}>
                    —
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                    No paper activity yet
                  </Typography>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Plan card */}
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <Card>
            <CardContent sx={{ p: 2.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, textTransform: 'uppercase', fontWeight: 'bold', letterSpacing: 0.5 }}>
                Plan Status
              </Typography>
              <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'primary.main', textTransform: 'capitalize' }}>
                {user.plan || 'Free'}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                {user.is_plus || user.is_pro ? 'Unlimited predictions' : `${user.predictions_remaining ?? 5} remaining today`}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Jump In Quick Access Grid */}
      <Box>
        <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 2, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.5 }}>
          Jump In
        </Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 6, sm: 4, md: 3 }}>
            <Card component={Link} to="/predict" sx={{ display: 'block', textDecoration: 'none', transition: 'all 0.15s', cursor: 'pointer', '&:hover': { borderColor: 'primary.main', transform: 'translateY(-2px)' } }}>
              <CardContent sx={{ p: 2.5, textAlign: 'center' }}>
                <Typography variant="h4" sx={{ mb: 1 }}>🔮</Typography>
                <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>Predict</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, height: 32, overflow: 'hidden' }}>Run ML predictions and analysis</Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 6, sm: 4, md: 3 }}>
            <Card component={Link} to="/watchlist" sx={{ display: 'block', textDecoration: 'none', transition: 'all 0.15s', cursor: 'pointer', '&:hover': { borderColor: 'primary.main', transform: 'translateY(-2px)' } }}>
              <CardContent sx={{ p: 2.5, textAlign: 'center' }}>
                <Typography variant="h4" sx={{ mb: 1 }}>📋</Typography>
                <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>Watchlist</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, height: 32, overflow: 'hidden' }}>Track signals and details</Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 6, sm: 4, md: 3 }}>
            <Card component={Link} to="/paper" sx={{ display: 'block', textDecoration: 'none', transition: 'all 0.15s', cursor: 'pointer', '&:hover': { borderColor: 'primary.main', transform: 'translateY(-2px)' } }}>
              <CardContent sx={{ p: 2.5, textAlign: 'center' }}>
                <Typography variant="h4" sx={{ mb: 1 }}>🧪</Typography>
                <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>Paper Trading</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, height: 32, overflow: 'hidden' }}>Simulate positions with virtual money</Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 6, sm: 4, md: 3 }}>
            <Card component={Link} to="/mt5" sx={{ display: 'block', textDecoration: 'none', transition: 'all 0.15s', cursor: 'pointer', '&:hover': { borderColor: 'primary.main', transform: 'translateY(-2px)' } }}>
              <CardContent sx={{ p: 2.5, textAlign: 'center' }}>
                <Typography variant="h4" sx={{ mb: 1 }}>🤖</Typography>
                <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>MT5 Trading</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, height: 32, overflow: 'hidden' }}>Algorithmic execution bridge</Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 6, sm: 4, md: 3 }}>
            <Card component={Link} to="/traders" sx={{ display: 'block', textDecoration: 'none', transition: 'all 0.15s', cursor: 'pointer', '&:hover': { borderColor: 'primary.main', transform: 'translateY(-2px)' } }}>
              <CardContent sx={{ p: 2.5, textAlign: 'center' }}>
                <Typography variant="h4" sx={{ mb: 1 }}>🏆</Typography>
                <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>Leaderboard</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, height: 32, overflow: 'hidden' }}>Sharpe ratio user rankings</Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 6, sm: 4, md: 3 }}>
            <Card component={Link} to="/track-record" sx={{ display: 'block', textDecoration: 'none', transition: 'all 0.15s', cursor: 'pointer', '&:hover': { borderColor: 'primary.main', transform: 'translateY(-2px)' } }}>
              <CardContent sx={{ p: 2.5, textAlign: 'center' }}>
                <Typography variant="h4" sx={{ mb: 1 }}>✅</Typography>
                <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>Track Record</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, height: 32, overflow: 'hidden' }}>Live prediction accuracies stats</Typography>
              </CardContent>
            </Card>
          </Grid>

          {!user.is_plus && (
            <Grid size={{ xs: 6, sm: 4, md: 3 }}>
              <Card component={Link} to="/pricing" sx={{ display: 'block', textDecoration: 'none', borderColor: 'rgba(139, 92, 246, 0.3)', transition: 'all 0.15s', cursor: 'pointer', '&:hover': { borderColor: 'primary.main', transform: 'translateY(-2px)' } }}>
                <CardContent sx={{ p: 2.5, textAlign: 'center' }}>
                  <Typography variant="h4" sx={{ mb: 1 }}>⭐</Typography>
                  <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'primary.main' }}>Upgrade</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, height: 32, overflow: 'hidden' }}>Unlock unlimited runs and plans</Typography>
                </CardContent>
              </Card>
            </Grid>
          )}

          {user.role_level >= 3 && (
            <Grid size={{ xs: 6, sm: 4, md: 3 }}>
              <Card component={Link} to="/admin" sx={{ display: 'block', textDecoration: 'none', borderColor: 'rgba(239, 68, 68, 0.3)', transition: 'all 0.15s', cursor: 'pointer', '&:hover': { borderColor: 'error.main', transform: 'translateY(-2px)' } }}>
                <CardContent sx={{ p: 2.5, textAlign: 'center' }}>
                  <Typography variant="h4" sx={{ mb: 1 }}>🛠️</Typography>
                  <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'error.main' }}>Admin Console</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, height: 32, overflow: 'hidden' }}>Manage system, users & payments</Typography>
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      </Box>

      {/* Main Two-Column Detail Layout */}
      <Grid container spacing={3}>
        {/* Left Column: Recent Predictions */}
        <Grid size={{ xs: 12, lg: 7 }}>
          <Card sx={{ height: '100%' }}>
            <CardContent sx={{ p: 0 }}>
              <Box sx={{ px: 3, py: 2.5, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold' }}>
                  Recent Predictions
                </Typography>
                {predictions.length > 0 && (
                  <Button component={Link} to="/history" size="small" sx={{ fontWeight: 'bold' }}>
                    View All &rarr;
                  </Button>
                )}
              </Box>

              {loadingStats ? (
                <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'center', py: 8 }}>
                  <CircularProgress size={24} />
                </Box>
              ) : predictions.length === 0 ? (
                <Box sx={{ p: 4, textAlign: 'center' }}>
                  <Typography variant="h4" sx={{ mb: 1.5 }}>👋</Typography>
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold', color: 'text.primary', mb: 1 }}>
                    New here? Get set up in three steps
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                    No predictions run yet. Get started with these simple guides:
                  </Typography>

                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, maxWidth: 400, mx: 'auto', textAlign: 'left' }}>
                    <Card component={Link} to="/risk-basics" sx={{ textDecoration: 'none', transition: 'border-color 0.15s', '&:hover': { borderColor: 'primary.main' } }}>
                      <CardContent sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 2 }}>
                        <Avatar sx={{ bgcolor: 'primary.main', width: 26, height: 26, fontSize: '0.85rem', fontWeight: 'bold' }}>1</Avatar>
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>Read Risk Basics</Typography>
                          <Typography variant="caption" color="text.secondary">Two-minute introduction to platform risk controls</Typography>
                        </Box>
                      </CardContent>
                    </Card>

                    <Card component={Link} to="/predict" sx={{ textDecoration: 'none', transition: 'border-color 0.15s', '&:hover': { borderColor: 'primary.main' } }}>
                      <CardContent sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 2 }}>
                        <Avatar sx={{ bgcolor: 'primary.main', width: 26, height: 26, fontSize: '0.85rem', fontWeight: 'bold' }}>2</Avatar>
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>Run First Prediction</Typography>
                          <Typography variant="caption" color="text.secondary">Try AAPL, MSFT, or BTC on the daily timeframe</Typography>
                        </Box>
                      </CardContent>
                    </Card>

                    <Card component={Link} to="/watchlist" sx={{ textDecoration: 'none', transition: 'border-color 0.15s', '&:hover': { borderColor: 'primary.main' } }}>
                      <CardContent sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 2 }}>
                        <Avatar sx={{ bgcolor: 'primary.main', width: 26, height: 26, fontSize: '0.85rem', fontWeight: 'bold' }}>3</Avatar>
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>Build Your Watchlist</Typography>
                          <Typography variant="caption" color="text.secondary">Track the assets you care about most</Typography>
                        </Box>
                      </CardContent>
                    </Card>
                  </Box>
                </Box>
              ) : (
                <Box>
                  {predictions.map((p, idx) => (
                    <Box key={p.id} sx={{ 
                      display: 'grid', 
                      gridTemplateColumns: '1.2fr 1fr 1fr 1.4fr', 
                      alignItems: 'center', 
                      px: 3, 
                      py: 2, 
                      borderBottom: idx === predictions.length - 1 ? 'none' : '1px solid rgba(255,255,255,0.03)' 
                    }}>
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', display: 'inline' }}>
                          {p.ticker}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ ml: 1, fontWeight: 'medium' }}>
                          {p.interval}
                        </Typography>
                      </Box>

                      <Box>
                        <Chip 
                          label={p.direction} 
                          color={p.direction === 'UP' ? 'success' : p.direction === 'DOWN' ? 'error' : 'default'}
                          size="small" 
                          sx={{ fontWeight: 'bold', fontSize: '0.75rem', height: 20 }}
                        />
                      </Box>

                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                          {p.confidence.toFixed(1)}%
                        </Typography>
                      </Box>

                      <Box sx={{ textAlign: 'right' }}>
                        <Typography variant="caption" color="text.secondary">
                          {p.predicted_at ? new Date(p.predicted_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                        </Typography>
                      </Box>
                    </Box>
                  ))}
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Right Column: Watchlist snapshot & Paper trading stats & Upgrade Card */}
        <Grid size={{ xs: 12, lg: 5 }} sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* Watchlist snapshot panel */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                Watchlist Snapshot
              </Typography>
              <Button component={Link} to="/watchlist" size="small" sx={{ fontWeight: 'bold' }}>
                Manage &rarr;
              </Button>
            </Box>
            <CardContent sx={{ p: 3 }}>
              {loadingStats ? (
                <CircularProgress size={18} />
              ) : watchlist.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  Your watchlist is empty.{' '}
                  <Link to="/watchlist" style={{ color: '#8b5cf6', fontWeight: 'bold', textDecoration: 'none' }}>
                    Add tickers &rarr;
                  </Link>
                </Typography>
              ) : (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                  {watchlist.map((item) => (
                    <Chip
                      key={item.id}
                      label={item.ticker}
                      onClick={() => navigate(`/predict`)}
                      variant="outlined"
                      sx={{ 
                        fontWeight: 'bold',
                        cursor: 'pointer',
                        borderColor: 'rgba(255,255,255,0.08)',
                        '&:hover': {
                          borderColor: 'primary.main',
                          color: 'primary.main'
                        }
                      }}
                    />
                  ))}
                </Box>
              )}
            </CardContent>
          </Card>

          {/* Paper Trading Summary Panel */}
          <Card>
            <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyItems: 'center', justifyContent: 'space-between' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                Simulated Paper Portfolio
              </Typography>
              <Button component={Link} to="/paper" size="small" sx={{ fontWeight: 'bold' }}>
                Open &rarr;
              </Button>
            </Box>
            <CardContent sx={{ p: 3 }}>
              {loadingStats ? (
                <CircularProgress size={18} />
              ) : !paperOptedIn ? (
                <Typography variant="body2" color="text.secondary">
                  You haven't opted in to paper trading yet. Practice with virtual balance, zero risk.{' '}
                  <Link to="/paper" style={{ color: '#8b5cf6', fontWeight: 'bold', textDecoration: 'none' }}>
                    Learn more &rarr;
                  </Link>
                </Typography>
              ) : (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <Grid container spacing={1}>
                    <Grid size={4}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Open Positions</Typography>
                      <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>{paperStats.open}</Typography>
                    </Grid>
                    <Grid size={4}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Closed Trades</Typography>
                      <Typography variant="body1" sx={{ fontWeight: 'bold', color: 'text.primary' }}>{paperStats.closed}</Typography>
                    </Grid>
                    <Grid size={4}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Simulated P&L</Typography>
                      <Typography variant="body1" sx={{ fontWeight: 'bold', color: paperStats.pnl >= 0 ? 'success.main' : 'error.main' }}>
                        {paperStats.pnl >= 0 ? '+' : ''}{paperStats.pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })} {currency}
                      </Typography>
                    </Grid>
                  </Grid>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 1 }}>
                    <AlertCircle size={12} /> Virtual balance, not real financial trades.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>

          {/* Upgrade prompt card for free tier */}
          {!user.is_plus && (
            <Card sx={{ border: '1px solid rgba(139, 92, 246, 0.2)', background: 'linear-gradient(135deg, rgba(139, 92, 246, 0.03) 0%, rgba(0,0,0,0) 100%)' }}>
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'center', textAlign: 'center' }}>
                <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                  ⭐ Go further with Plus or Pro plans
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                  Free plan tier allows {user.predictions_remaining ?? 5} of 5 daily predictions. Paid plans add unlimited runs, intraday signals, backtester and automated bot executions.
                </Typography>
                <Button 
                  component={Link} 
                  to="/pricing" 
                  variant="contained" 
                  color="primary"
                  sx={{ 
                    fontWeight: 'bold',
                    px: 4,
                    mt: 1,
                    transition: 'all 0.2s',
                    '&:hover': {
                      transform: 'translateY(-1px)',
                      boxShadow: '0 4px 15px rgba(139, 92, 246, 0.2)'
                    }
                  }}
                >
                  Upgrade Account
                </Button>
              </CardContent>
            </Card>
          )}
        </Grid>
      </Grid>
    </Box>
  );
};
