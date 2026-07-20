import React, { useState, useEffect } from 'react';
import { Trophy, Search, TrendingUp, TrendingDown, Minus, Info } from 'lucide-react';
import { 
  Box, Typography, Card, CardContent, Grid, TextField, Button, 
  CircularProgress, Chip, LinearProgress, InputAdornment 
} from '@mui/material';
import { apiFetch } from '../utils/api';

interface ModelRow {
  ticker: string;
  interval: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  price: number;
  rsi: number;
  accuracy: number | null;
  n_checked: number;
}

export const LeaderboardDashboard: React.FC = () => {
  const [data, setData] = useState<ModelRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [filter, setFilter] = useState<'all' | '1d' | '1h' | '4h' | 'buy' | 'sell'>('all');

  useEffect(() => {
    const fetchLeaderboard = async () => {
      try {
        const response = await apiFetch('/api/leaderboard');
        if (response.ok && response.rows) {
          setData(response.rows);
        }
      } catch (err) {
        console.error('Failed to fetch model leaderboard:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchLeaderboard();
  }, []);

  const filteredData = data.filter((row) => {
    const matchesSearch = row.ticker.toLowerCase().includes(searchTerm.toLowerCase());
    
    let matchesFilter = true;
    if (filter === '1d' || filter === '1h' || filter === '4h') {
      matchesFilter = row.interval === filter;
    } else if (filter === 'buy') {
      matchesFilter = row.action === 'BUY';
    } else if (filter === 'sell') {
      matchesFilter = row.action === 'SELL';
    }
    
    return matchesSearch && matchesFilter;
  });

  const getActionColor = (action: string) => {
    if (action === 'BUY') return 'success';
    if (action === 'SELL') return 'error';
    return 'default';
  };

  const getActionIcon = (action: string) => {
    if (action === 'BUY') return <TrendingUp size={14} />;
    if (action === 'SELL') return <TrendingDown size={14} />;
    return <Minus size={14} />;
  };

  const getAccuracyColor = (accuracy: number | null) => {
    if (accuracy === null) return '#7a8499';
    if (accuracy >= 75) return '#10b981';
    if (accuracy >= 55) return '#8b5cf6';
    return '#ef4444';
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h2" sx={{ display: 'flex', alignItems: 'center', gap: 1.5, fontSize: '1.5rem', color: 'text.primary', fontWeight: 'bold' }}>
            <Trophy color="#8b5cf6" />
            Model Performance Leaderboard
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Proprietary machine learning models ranked by historical signal direction accuracy.
          </Typography>
        </Box>
      </Box>

      {/* Filter Bar */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 2, alignItems: 'center', justifyContent: 'space-between' }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
          <Button 
            variant={filter === 'all' ? 'contained' : 'outlined'} 
            onClick={() => setFilter('all')}
            size="small"
          >
            All
          </Button>
          <Button 
            variant={filter === '1d' ? 'contained' : 'outlined'} 
            onClick={() => setFilter('1d')}
            size="small"
          >
            Daily
          </Button>
          <Button 
            variant={filter === '1h' ? 'contained' : 'outlined'} 
            onClick={() => setFilter('1h')}
            size="small"
          >
            1H
          </Button>
          <Button 
            variant={filter === '4h' ? 'contained' : 'outlined'} 
            onClick={() => setFilter('4h')}
            size="small"
          >
            4H
          </Button>
          <Button 
            variant={filter === 'buy' ? 'contained' : 'outlined'} 
            color="success"
            onClick={() => setFilter('buy')}
            size="small"
            startIcon={<TrendingUp size={14} />}
          >
            Buy
          </Button>
          <Button 
            variant={filter === 'sell' ? 'contained' : 'outlined'} 
            color="error"
            onClick={() => setFilter('sell')}
            size="small"
            startIcon={<TrendingDown size={14} />}
          >
            Sell
          </Button>
        </Box>

        <TextField
          id="lb-search"
          placeholder="Filter ticker..."
          size="small"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <Search size={16} />
                </InputAdornment>
              ),
            }
          }}
          sx={{ width: { xs: '100%', md: 220 } }}
        />
      </Box>

      {/* Grid Content */}
      {loading ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyItems: 'center', py: 12, gap: 2 }}>
          <CircularProgress color="primary" />
          <Typography color="text.secondary">Loading performance metrics...</Typography>
        </Box>
      ) : filteredData.length === 0 ? (
        <Card sx={{ display: 'flex', justifyContent: 'center', py: 8, border: '1px dashed rgba(255,255,255,0.05)' }}>
          <Typography color="text.secondary">No matching signals found.</Typography>
        </Card>
      ) : (
        <Grid container spacing={2}>
          {filteredData.map((row, idx) => (
            <Grid size={{ xs: 12, sm: 6, md: 4 }} key={idx}>
              <Card sx={{ 
                bgcolor: 'background.paper', 
                border: '1px solid rgba(255,255,255,0.05)',
                transition: 'all 0.2s',
                '&:hover': {
                  borderColor: 'primary.main',
                  transform: 'translateY(-2px)',
                }
              }}>
                <CardContent sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {/* Top */}
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Typography variant="h6" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                      {row.ticker}
                    </Typography>
                    <Chip 
                      label={row.interval.toUpperCase()} 
                      size="small" 
                      color="primary"
                      variant="outlined" 
                      sx={{ fontWeight: 'bold' }}
                    />
                  </Box>

                  {/* Signal Info */}
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Chip 
                      label={row.action} 
                      color={getActionColor(row.action)}
                      icon={getActionIcon(row.action)}
                      size="small" 
                      sx={{ fontWeight: 'bold', px: 1 }}
                    />
                    <Box sx={{ textAlign: 'right' }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                        Confidence
                      </Typography>
                      <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                        {row.confidence}%
                      </Typography>
                    </Box>
                  </Box>

                  {/* Stats Grid */}
                  <Grid container spacing={1} sx={{ bgcolor: 'rgba(0,0,0,0.15)', p: 1.5, borderRadius: 2, border: '1px solid rgba(255,255,255,0.02)' }}>
                    <Grid size={6}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>RSI</Typography>
                      <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>{row.rsi.toFixed(1)}</Typography>
                    </Grid>
                    <Grid size={6}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Last Price</Typography>
                      <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary' }}>${row.price.toLocaleString()}</Typography>
                    </Grid>
                  </Grid>

                  {/* Accuracy progress bar */}
                  <Box>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">Accuracy</Typography>
                      <Typography variant="caption" sx={{ fontWeight: 'bold', color: getAccuracyColor(row.accuracy) }}>
                        {row.accuracy !== null ? `${row.accuracy}%` : 'Pending'}
                      </Typography>
                    </Box>
                    <LinearProgress 
                      variant="determinate" 
                      value={row.accuracy !== null ? row.accuracy : 0} 
                      sx={{ 
                        height: 4, 
                        borderRadius: 2, 
                        bgcolor: 'rgba(255,255,255,0.05)',
                        '& .MuiLinearProgress-bar': {
                          bgcolor: getAccuracyColor(row.accuracy),
                          borderRadius: 2
                        }
                      }}
                    />
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.8 }}>
                      <Info size={12} /> Checked {row.n_checked} predictions
                    </Typography>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );
};
