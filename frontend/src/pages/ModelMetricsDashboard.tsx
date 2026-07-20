import React, { useState, useEffect } from 'react';
import { 
  Box, Typography, Grid, Card, CardContent, CircularProgress, 
  Button, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Paper, Chip
} from '@mui/material';
import { apiFetch } from '../utils/api';
import toast from 'react-hot-toast';

interface ModelResult {
  ticker: string;
  tf: string;
  rows: number;
  feats: number;
  lr_acc: number;
  lr_auc: number;
  rf_acc: number;
  rf_auc: number;
  xgb_cv_acc: number;
  xgb_test_acc: number;
  xgb_auc: number;
}

interface AccuracyRecord {
  ticker: string;
  date: string;
  predicted: number;
  actual: number | null;
  dir_ok: boolean;
  pct_err: number | null;
}

interface TrackRecordData {
  count: number;
  direction_accuracy: number | null;
  avg_pct_error: number | null;
  recent: AccuracyRecord[];
}

export const ModelMetricsDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'quality' | 'track'>('quality');
  
  // Model Quality state
  const [modelsList, setModelsList] = useState<ModelResult[]>([]);
  const [trainedAt, setTrainedAt] = useState<string>('');
  const [activeTf, setActiveTf] = useState<string>('all');
  const [loadingQuality, setLoadingQuality] = useState(true);

  // Track Record state
  const [trackRecord, setTrackRecord] = useState<TrackRecordData | null>(null);
  const [loadingTrack, setLoadingTrack] = useState(true);

  const fetchModelQuality = async () => {
    setLoadingQuality(true);
    try {
      const data = await apiFetch('/api/model-metrics');
      if (data.ok) {
        setModelsList(data.results || []);
        if (data.trained_at) {
          setTrainedAt(new Date(data.trained_at).toLocaleString());
        }
      } else {
        toast.error(data.error || 'Failed to load model metrics');
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingQuality(false);
    }
  };

  const fetchTrackRecord = async () => {
    setLoadingTrack(true);
    try {
      const data = await apiFetch('/api/accuracy');
      if (data.ok) {
        setTrackRecord(data);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingTrack(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'quality') fetchModelQuality();
    else if (activeTab === 'track') fetchTrackRecord();
  }, [activeTab]);

  const getAucClass = (v: number | null) => {
    if (v === null) return { text: 'text.secondary', bg: 'transparent', label: 'N/A' };
    if (v >= 0.65) return { text: '#10b981', bg: 'rgba(16, 185, 129, 0.1)', label: 'Strong' };
    if (v >= 0.55) return { text: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.1)', label: 'Usable' };
    return { text: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)', label: 'Weak' };
  };

  // Filter and sort quality results
  const filteredModels = activeTf === 'all' 
    ? modelsList 
    : modelsList.filter(m => m.tf === activeTf);

  const sortedModels = [...filteredModels].sort((a, b) => {
    const tfOrder = ['1m', '5m', '15m', '30m', '1h', '4h', '1d'];
    return a.ticker.localeCompare(b.ticker) || tfOrder.indexOf(a.tf) - tfOrder.indexOf(b.tf);
  });

  // Calculate quality summaries
  const xgbAucs = modelsList.map(m => m.xgb_auc).filter(v => v !== null) as number[];
  const avgAuc = xgbAucs.length ? xgbAucs.reduce((s, v) => s + v, 0) / xgbAucs.length : 0;
  const bestAuc = xgbAucs.length ? Math.max(...xgbAucs) : 0;
  const strongModelsCount = xgbAucs.filter(v => v >= 0.65).length;
  const weakModelsCount = xgbAucs.filter(v => v < 0.55).length;

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box>
        <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
          Model Metrics & Track Record
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          View quantitative model AUC backtest quality statistics and actual prediction accuracy records.
        </Typography>
      </Box>

      {/* Tabs */}
      <Box sx={{ display: 'flex', gap: 1, borderBottom: '1px solid rgba(255,255,255,0.05)', pb: 0.5 }}>
        <Button 
          onClick={() => setActiveTab('quality')}
          sx={{ 
            color: activeTab === 'quality' ? 'primary.main' : 'text.secondary',
            fontWeight: 'bold',
            borderBottom: activeTab === 'quality' ? '2px solid' : 'none',
            borderColor: 'primary.main',
            borderRadius: 0,
            px: 3,
            py: 1,
            textTransform: 'capitalize'
          }}
        >
          ML Model Quality
        </Button>
        <Button 
          onClick={() => setActiveTab('track')}
          sx={{ 
            color: activeTab === 'track' ? 'primary.main' : 'text.secondary',
            fontWeight: 'bold',
            borderBottom: activeTab === 'track' ? '2px solid' : 'none',
            borderColor: 'primary.main',
            borderRadius: 0,
            px: 3,
            py: 1,
            textTransform: 'capitalize'
          }}
        >
          Prediction Track Record
        </Button>
      </Box>

      {activeTab === 'quality' ? (
        // Model Quality Tab
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {/* Summary Cards */}
          <Grid container spacing={3}>
            <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>Models Trained</Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold' }}>{modelsList.length}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                    Last: {trainedAt || '—'}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>Avg XGB AUC</Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', color: avgAuc >= 0.65 ? 'success.main' : avgAuc >= 0.55 ? 'warning.main' : 'error.main' }}>
                    {avgAuc.toFixed(3)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>Cross-validation mean</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>Best AUC Score</Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'success.main' }}>{bestAuc.toFixed(3)}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>Top performing model</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>Strong (AUC ≥ 0.65)</Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'success.main' }}>{strongModelsCount}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>High predictive accuracy</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>Weak (AUC &lt; 0.55)</Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', color: weakModelsCount > 0 ? 'error.main' : 'success.main' }}>{weakModelsCount}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>Near-random predictions</Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          {/* Timeframe Filter Buttons */}
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, justifyItems: 'center', justifyContent: 'space-between', alignItems: 'center' }}>
            <Box sx={{ display: 'flex', gap: 1 }}>
              {['all', '1m', '5m', '15m', '30m', '1h', '4h', '1d'].map(tf => (
                <Button 
                  key={tf}
                  onClick={() => setActiveTf(tf)}
                  size="small"
                  variant={activeTf === tf ? 'contained' : 'outlined'}
                  color={activeTf === tf ? 'primary' : 'inherit'}
                  sx={{ textTransform: 'uppercase', fontWeight: 'bold', px: 2, borderRadius: 4 }}
                >
                  {tf}
                </Button>
              ))}
            </Box>
            
            {/* Legend indicators */}
            <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#10b981' }} />
                <Typography variant="caption" color="text.secondary">AUC ≥ 0.65 (Strong)</Typography>
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#8b5cf6' }} />
                <Typography variant="caption" color="text.secondary">0.55 - 0.65 (Usable)</Typography>
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#ef4444' }} />
                <Typography variant="caption" color="text.secondary">&lt; 0.55 (Weak)</Typography>
              </Box>
            </Box>
          </Box>

          {/* Main Table */}
          <Card>
            <CardContent sx={{ p: 0 }}>
              {loadingQuality ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}><CircularProgress size={24} /></Box>
              ) : (
                <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Ticker</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>TF</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Rows</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Features</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>LR Acc</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>LR AUC</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>RF Acc</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>RF AUC</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>XGB CV</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>XGB Test</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>XGB AUC</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {sortedModels.map((row, idx) => {
                        const lr = getAucClass(row.lr_auc);
                        const rf = getAucClass(row.rf_auc);
                        const xgb = getAucClass(row.xgb_auc);
                        return (
                          <TableRow key={idx} sx={{ '&:last-child td': { border: 0 } }}>
                            <TableCell sx={{ py: 1.5, fontWeight: 'bold', color: 'text.primary' }}>{row.ticker}</TableCell>
                            <TableCell><Chip label={row.tf} size="small" color="primary" variant="outlined" sx={{ height: 18, fontSize: '0.65rem', fontWeight: 'bold' }} /></TableCell>
                            <TableCell sx={{ textAlign: 'right', color: 'text.secondary' }}>{row.rows >= 1000 ? `${(row.rows / 1000).toFixed(0)}k` : row.rows}</TableCell>
                            <TableCell sx={{ textAlign: 'right', color: 'text.secondary' }}>{row.feats}</TableCell>
                            <TableCell sx={{ textAlign: 'right' }}>{row.lr_acc.toFixed(3)}</TableCell>
                            <TableCell sx={{ textAlign: 'right' }}>
                              <Box sx={{ display: 'inline-block', px: 1, py: 0.25, borderRadius: 1, bgcolor: lr.bg, color: lr.text, fontWeight: 'bold', fontSize: '0.85rem' }}>
                                {row.lr_auc.toFixed(3)}
                              </Box>
                            </TableCell>
                            <TableCell sx={{ textAlign: 'right' }}>{row.rf_acc.toFixed(3)}</TableCell>
                            <TableCell sx={{ textAlign: 'right' }}>
                              <Box sx={{ display: 'inline-block', px: 1, py: 0.25, borderRadius: 1, bgcolor: rf.bg, color: rf.text, fontWeight: 'bold', fontSize: '0.85rem' }}>
                                {row.rf_auc.toFixed(3)}
                              </Box>
                            </TableCell>
                            <TableCell sx={{ textAlign: 'right' }}>{row.xgb_cv_acc.toFixed(3)}</TableCell>
                            <TableCell sx={{ textAlign: 'right' }}>{row.xgb_test_acc.toFixed(3)}</TableCell>
                            <TableCell sx={{ textAlign: 'right' }}>
                              <Box sx={{ display: 'inline-block', px: 1, py: 0.25, borderRadius: 1, bgcolor: xgb.bg, color: xgb.text, fontWeight: 'bold', fontSize: '0.85rem' }}>
                                {row.xgb_auc.toFixed(3)}
                              </Box>
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
        </Box>
      ) : (
        // Prediction Track Record Tab
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {/* Summary stats */}
          <Grid container spacing={3}>
            <Grid size={{ xs: 12, sm: 4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>Predictions Verified</Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold' }}>{trackRecord?.count ?? 0}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>Outcome checked against close price</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>Direction Accuracy</Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', color: 'success.main' }}>
                    {trackRecord && trackRecord.direction_accuracy !== null ? `${trackRecord.direction_accuracy}%` : '—'}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>Percentage of correct predictions</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontWeight: 'bold' }}>Average % Error</Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold' }}>
                    {trackRecord && trackRecord.avg_pct_error !== null ? `${trackRecord.avg_pct_error}%` : '—'}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>Mean absolute percentage error</Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          {/* Table of verified predictions */}
          <Card>
            <Box sx={{ px: 3, py: 2.5, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                Recent Verified Prediction Outcomes
              </Typography>
            </Box>
            <CardContent sx={{ p: 0 }}>
              {loadingTrack ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}><CircularProgress size={24} /></Box>
              ) : !trackRecord || trackRecord.recent.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ p: 4, textAlign: 'center' }}>No verified prediction records found.</Typography>
              ) : (
                <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Ticker</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Date</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Predicted Close</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Actual Close</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Direction Check</TableCell>
                        <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>% Error</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {trackRecord.recent.map((row, idx) => (
                        <TableRow key={idx} sx={{ '&:last-child td': { border: 0 } }}>
                          <TableCell sx={{ py: 1.5, fontWeight: 'bold', color: 'text.primary' }}>{row.ticker}</TableCell>
                          <TableCell sx={{ color: 'text.secondary' }}>{row.date}</TableCell>
                          <TableCell sx={{ textAlign: 'right' }}>${row.predicted.toFixed(2)}</TableCell>
                          <TableCell sx={{ textAlign: 'right', fontWeight: 'semibold' }}>{row.actual !== null ? `$${row.actual.toFixed(2)}` : '—'}</TableCell>
                          <TableCell sx={{ textAlign: 'right', py: 1.5 }}>
                            <Chip 
                              label={row.dir_ok ? 'CORRECT' : 'INCORRECT'}
                              color={row.dir_ok ? 'success' : 'error'}
                              size="small"
                              sx={{ fontWeight: 'bold', fontSize: '0.65rem', height: 18 }}
                            />
                          </TableCell>
                          <TableCell sx={{ textAlign: 'right', fontWeight: 'medium' }}>
                            {row.pct_err !== null ? `${row.pct_err.toFixed(2)}%` : '—'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </CardContent>
          </Card>
        </Box>
      )}
    </Box>
  );
};
