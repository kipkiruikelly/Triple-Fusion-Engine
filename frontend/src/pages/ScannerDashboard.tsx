import React, { useState, useEffect } from 'react';
import { 
  Box, Typography, Grid, Card, CardContent, CircularProgress, 
  Button, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Paper, Chip, LinearProgress
} from '@mui/material';
import { apiFetch } from '../utils/api';

interface VolumeRow {
  ticker: string;
  price: number;
  pct_change: number;
  volume: number;
  avg_volume: number;
  volume_ratio: number;
}

interface SqueezeRow {
  ticker: string;
  price: number;
  short_float_pct: number;
  days_to_cover: number;
  rsi: number | null;
  momentum_5d: number;
  squeeze_score: number;
}

interface SectorRow {
  sector: string;
  etf: string;
  price: number;
  d1: number;
  d5: number;
  volume: number;
}

export const ScannerDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'volume' | 'squeeze' | 'sector'>('volume');
  
  const [volumeRows, setVolumeRows] = useState<VolumeRow[]>([]);
  const [squeezeRows, setSqueezeRows] = useState<SqueezeRow[]>([]);
  const [sectorRows, setSectorRows] = useState<SectorRow[]>([]);

  const [loading, setLoading] = useState(true);
  const [sectorSortKey, setSectorSortKey] = useState<'d1' | 'd5'>('d1');

  const fetchVolume = async () => {
    setLoading(true);
    try {
      const data = await apiFetch('/api/scanner/volume');
      if (data.ok && data.rows) {
        setVolumeRows(data.rows);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchSqueeze = async () => {
    setLoading(true);
    try {
      const data = await apiFetch('/api/scanner/squeeze');
      if (data.ok && data.rows) {
        setSqueezeRows(data.rows);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchSector = async () => {
    setLoading(true);
    try {
      const data = await apiFetch('/api/scanner/sector');
      if (data.ok && data.sectors) {
        setSectorRows(data.sectors);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'volume') fetchVolume();
    else if (activeTab === 'squeeze') fetchSqueeze();
    else if (activeTab === 'sector') fetchSector();
  }, [activeTab]);

  const handleRefresh = () => {
    if (activeTab === 'volume') fetchVolume();
    else if (activeTab === 'squeeze') fetchSqueeze();
    else if (activeTab === 'sector') fetchSector();
  };

  const getIntensityColor = (val: number, maxVal: number) => {
    const intensity = Math.min(0.85, Math.abs(val) / (maxVal || 1));
    const bg = val >= 0 ? `rgba(16, 185, 129, ${intensity * 0.35})` : `rgba(239, 68, 68, ${intensity * 0.35})`;
    const border = val >= 0 ? `rgba(16, 185, 129, ${intensity * 0.5})` : `rgba(239, 68, 68, ${intensity * 0.5})`;
    const text = val >= 0 ? '#10b981' : '#ef4444';
    return { bg, border, text };
  };

  const sortedSectors = [...sectorRows].sort((a, b) => b[sectorSortKey] - a[sectorSortKey]);
  const maxSectorVal = Math.max(...sectorRows.map(s => Math.abs(s[sectorSortKey])), 1);

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, justifyItems: 'center', justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
            Advanced Scanner
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Volume anomalies, short squeeze metrics, and sector rotations calculated on demand.
          </Typography>
        </Box>
        <Button variant="outlined" color="inherit" onClick={handleRefresh} disabled={loading} sx={{ fontWeight: 'bold' }}>
          Refresh Scan
        </Button>
      </Box>

      {/* Tabs */}
      <Box sx={{ display: 'flex', gap: 1, borderBottom: '1px solid rgba(255,255,255,0.05)', pb: 0.5 }}>
        {(['volume', 'squeeze', 'sector'] as const).map(tab => (
          <Button 
            key={tab}
            onClick={() => setActiveTab(tab)}
            variant={activeTab === tab ? 'text' : 'text'}
            sx={{ 
              color: activeTab === tab ? 'primary.main' : 'text.secondary',
              fontWeight: 'bold',
              borderBottom: activeTab === tab ? '2px solid' : 'none',
              borderColor: 'primary.main',
              borderRadius: 0,
              px: 3,
              py: 1,
              textTransform: 'capitalize',
              '&:hover': {
                color: 'text.primary'
              }
            }}
          >
            {tab === 'volume' ? 'Volume Anomaly' : tab === 'squeeze' ? 'Short Squeeze' : 'Sector Rotation'}
          </Button>
        ))}
      </Box>

      {/* Panels */}
      <Card>
        <CardContent sx={{ p: 0 }}>
          {loading ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 10, gap: 2 }}>
              <CircularProgress size={28} />
              <Typography color="text.secondary" variant="body2">Scanning markets...</Typography>
            </Box>
          ) : (
            <>
              {/* Volume Scanner */}
              {activeTab === 'volume' && (
                <Box>
                  <Box sx={{ p: 3, borderBottom: '1px solid rgba(255,255,255,0.05)', bgcolor: 'rgba(59,130,246,0.02)' }}>
                    <Typography variant="body2" color="primary.main" sx={{ fontWeight: 'medium' }}>
                      💡 Volume ratio &gt; 2.0× indicates a significant volume spike. Use with price direction for confirmation.
                    </Typography>
                  </Box>
                  <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Ticker</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Price</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Day %</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Volume</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>30d Avg</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Ratio</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', width: 140 }}>Bar</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {volumeRows.map((row) => {
                          const isUp = row.pct_change >= 0;
                          const maxVolRatio = Math.max(...volumeRows.map(r => r.volume_ratio), 1);
                          return (
                            <TableRow key={row.ticker} sx={{ '&:last-child td': { border: 0 } }}>
                              <TableCell sx={{ py: 1.5 }}>
                                <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', display: 'inline' }}>
                                  {row.ticker}
                                </Typography>
                                {row.volume_ratio >= 3 && (
                                  <Chip label="SPIKE" color="error" size="small" sx={{ ml: 1, height: 16, fontSize: '0.6rem', fontWeight: 'bold' }} />
                                )}
                              </TableCell>
                              <TableCell>${row.price.toFixed(2)}</TableCell>
                              <TableCell sx={{ color: isUp ? 'success.main' : 'error.main', fontWeight: 'bold', textAlign: 'right' }}>
                                {isUp ? '+' : ''}{row.pct_change.toFixed(2)}%
                              </TableCell>
                              <TableCell sx={{ textAlign: 'right' }}>{(row.volume / 1000000).toFixed(2)}M</TableCell>
                              <TableCell sx={{ textAlign: 'right' }}>{(row.avg_volume / 1000000).toFixed(2)}M</TableCell>
                              <TableCell sx={{ textAlign: 'right', fontWeight: 'bold' }}>{row.volume_ratio.toFixed(2)}×</TableCell>
                              <TableCell sx={{ py: 1.5 }}>
                                <LinearProgress 
                                  variant="determinate" 
                                  value={Math.min(100, (row.volume_ratio / maxVolRatio) * 100)}
                                  sx={{ 
                                    height: 6, 
                                    borderRadius: 3, 
                                    bgcolor: 'rgba(255,255,255,0.05)',
                                    '& .MuiLinearProgress-bar': {
                                      bgcolor: row.volume_ratio >= 3 ? 'error.main' : row.volume_ratio >= 2 ? 'warning.main' : 'primary.main'
                                    }
                                  }}
                                />
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}

              {/* Squeeze Scanner */}
              {activeTab === 'squeeze' && (
                <Box>
                  <Box sx={{ p: 3, borderBottom: '1px solid rgba(255,255,255,0.05)', bgcolor: 'rgba(245,166,35,0.02)' }}>
                    <Typography variant="body2" color="primary.main" sx={{ fontWeight: 'medium' }}>
                      💡 High Short Float % + Positive 5D Momentum indicates short sellers covering risk triggers.
                    </Typography>
                  </Box>
                  <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Ticker</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Price</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Short Float</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Days to Cover</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>RSI</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>5D Momentum</TableCell>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Squeeze Score</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {squeezeRows.map((row) => {
                          const isUp = row.momentum_5d >= 0;
                          return (
                            <TableRow key={row.ticker} sx={{ '&:last-child td': { border: 0 } }}>
                              <TableCell sx={{ py: 1.5 }}>
                                <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', display: 'inline' }}>
                                  {row.ticker}
                                </Typography>
                                {row.short_float_pct >= 25 && (
                                  <Chip label="HIGH SHORT" color="error" size="small" sx={{ ml: 1, height: 16, fontSize: '0.6rem', fontWeight: 'bold' }} />
                                )}
                              </TableCell>
                              <TableCell>${row.price.toFixed(2)}</TableCell>
                              <TableCell sx={{ textAlign: 'right', fontWeight: 'bold' }}>{row.short_float_pct.toFixed(1)}%</TableCell>
                              <TableCell sx={{ textAlign: 'right' }}>{row.days_to_cover.toFixed(1)} days</TableCell>
                              <TableCell sx={{ 
                                textAlign: 'right', 
                                color: row.rsi !== null && row.rsi > 70 ? 'error.main' : row.rsi !== null && row.rsi < 30 ? 'success.main' : 'text.primary'
                              }}>
                                {row.rsi ?? '—'}
                              </TableCell>
                              <TableCell sx={{ color: isUp ? 'success.main' : 'error.main', fontWeight: 'bold', textAlign: 'right' }}>
                                {isUp ? '+' : ''}{row.momentum_5d.toFixed(2)}%
                              </TableCell>
                              <TableCell sx={{ textAlign: 'right', fontWeight: 'bold', color: 'primary.main' }}>{row.squeeze_score.toFixed(1)}</TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}

              {/* Sector rotation Heatmap */}
              {activeTab === 'sector' && (
                <Box sx={{ p: 3 }}>
                  <Box sx={{ display: 'flex', justifyItems: 'center', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                      Sector ETF Return Rates
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold' }}>Sort by:</Typography>
                      {(['d1', 'd5'] as const).map(key => (
                        <Button 
                          key={key}
                          size="small"
                          variant={sectorSortKey === key ? 'contained' : 'outlined'}
                          color={sectorSortKey === key ? 'primary' : 'inherit'}
                          onClick={() => setSectorSortKey(key)}
                          sx={{ minWidth: 44, textTransform: 'uppercase', fontWeight: 'bold', py: 0.2 }}
                        >
                          {key === 'd1' ? '1D' : '5D'}
                        </Button>
                      ))}
                    </Box>
                  </Box>
                  <Grid container spacing={2}>
                    {sortedSectors.map((row) => {
                      const v = row[sectorSortKey];
                      const color = getIntensityColor(v, maxSectorVal);
                      return (
                        <Grid key={row.sector} size={{ xs: 12, sm: 6, md: 4 }}>
                          <Box sx={{ 
                            p: 2.5,
                            textAlign: 'center',
                            borderRadius: 2.5,
                            bgcolor: color.bg,
                            border: '1px solid',
                            borderColor: color.border,
                            transition: 'transform 0.15s',
                            '&:hover': { transform: 'scale(1.02)' }
                          }}>
                            <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'text.primary', display: 'block', mb: 0.5 }}>
                              {row.sector}
                            </Typography>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                              {row.etf} · ${row.price.toFixed(2)}
                            </Typography>
                            <Typography variant="h5" sx={{ fontWeight: 'bold', color: color.text }}>
                              {v >= 0 ? '+' : ''}{v.toFixed(2)}%
                            </Typography>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                              {sectorSortKey === 'd1' ? `5D return: ${row.d5 >= 0 ? '+' : ''}${row.d5}%` : `1D return: ${row.d1 >= 0 ? '+' : ''}${row.d1}%`}
                            </Typography>
                          </Box>
                        </Grid>
                      );
                    })}
                  </Grid>
                </Box>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </Box>
  );
};
