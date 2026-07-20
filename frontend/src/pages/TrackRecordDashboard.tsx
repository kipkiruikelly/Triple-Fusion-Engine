import React, { useState, useEffect, useCallback } from 'react';
import { Box, Typography, Card, CardContent, Grid, Button, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper, CircularProgress } from '@mui/material';
import { ShieldCheck, Calendar, Activity } from 'lucide-react';
import { apiFetch } from '../utils/api';

interface ModelStat {
  ticker: string;
  interval: string;
  n: number;
  direction_accuracy: number | null;
  avg_pct_error: number | null;
  sufficient: boolean;
}

interface TrackRecordResponse {
  days: number;
  total_graded: number;
  overall_direction_accuracy: number | null;
  min_samples: number;
  per_model: ModelStat[];
}

export const TrackRecordDashboard: React.FC = () => {
  const [days, setDays] = useState<30 | 90>(90);
  const [data, setData] = useState<TrackRecordResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchTrackRecord = useCallback(async (filterDays: number) => {
    setLoading(true);
    try {
      const json = await apiFetch(`/api/track-record?days=${filterDays}`);
      if (json.ok) {
        setData(json);
      }
    } catch (err) {
      console.error('Failed to load track record:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrackRecord(days);
  }, [days, fetchTrackRecord]);

  const getAccuracyColor = (acc: number | null) => {
    if (acc === null) return 'text.secondary';
    if (acc >= 55) return 'success.main';
    if (acc < 45) return 'error.main';
    return 'text.primary';
  };

  const getSufficientCount = () => {
    if (!data) return 0;
    return data.per_model.filter((m) => m.sufficient).length;
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1.5, color: 'text.primary' }}>
            <ShieldCheck color="#3b82f6" />
            Track Record
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Every prediction made on BullLogic is automatically graded against actual market data. No cherry-picking.
          </Typography>
        </Box>

        {/* Days filters */}
        <Box sx={{ display: 'flex', gap: 1, bgcolor: 'rgba(255,255,255,0.02)', p: 0.5, borderRadius: 2, border: '1px solid rgba(255,255,255,0.05)' }}>
          <Button 
            size="small"
            variant={days === 30 ? 'contained' : 'text'}
            onClick={() => setDays(30)}
            sx={{ fontWeight: 'bold', px: 2 }}
          >
            Last 30 Days
          </Button>
          <Button 
            size="small"
            variant={days === 90 ? 'contained' : 'text'}
            onClick={() => setDays(90)}
            sx={{ fontWeight: 'bold', px: 2 }}
          >
            Last 90 Days
          </Button>
        </Box>
      </Box>

      {loading && !data ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 10, gap: 2 }}>
          <CircularProgress size={30} />
          <Typography color="text.secondary" variant="body2">Loading historical statistics...</Typography>
        </Box>
      ) : !data ? (
        <Box sx={{ py: 6, textAlign: 'center', color: 'text.secondary' }}>
          No graded records are available currently.
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {/* Hero Metrics cards */}
          <Grid container spacing={3}>
            <Grid size={{ xs: 12, sm: 4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <ShieldCheck size={14} color="#10b981" /> Overall Direction Accuracy
                  </Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', mt: 1, color: data.overall_direction_accuracy && data.overall_direction_accuracy >= 50 ? 'success.main' : 'text.primary' }}>
                    {data.overall_direction_accuracy !== null ? `${data.overall_direction_accuracy}%` : 'Insufficient Data'}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>

            <Grid size={{ xs: 12, sm: 4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Calendar size={14} color="#3b82f6" /> Predictions Graded
                  </Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', mt: 1 }}>
                    {data.total_graded.toLocaleString()}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>

            <Grid size={{ xs: 12, sm: 4 }}>
              <Card>
                <CardContent sx={{ p: 2.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 'bold', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Activity size={14} color="#8b5cf6" /> Models with Sufficient Data
                  </Typography>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', mt: 1 }}>
                    {getSufficientCount()} / {data.per_model.length}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          {/* Details Table */}
          <Card>
            <CardContent sx={{ p: 0 }}>
              <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Ticker</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Timeframe</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Graded Calls</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Direction Accuracy</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Avg Price Error</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.per_model.map((row) => (
                      <TableRow key={`${row.ticker}-${row.interval}`} hover sx={{ '&:last-child td': { border: 0 } }}>
                        <TableCell sx={{ py: 1.5, fontWeight: 'bold' }}>{row.ticker}</TableCell>
                        <TableCell sx={{ textTransform: 'uppercase' }}>{row.interval}</TableCell>
                        <TableCell sx={{ textAlign: 'right' }}>{row.n}</TableCell>
                        <TableCell sx={{ textAlign: 'right', fontWeight: 'bold', color: getAccuracyColor(row.direction_accuracy) }}>
                          {row.sufficient && row.direction_accuracy !== null 
                            ? `${row.direction_accuracy}%` 
                            : `insufficient data (${row.n}/${data.min_samples})`}
                        </TableCell>
                        <TableCell sx={{ textAlign: 'right', color: 'text.secondary' }}>
                          {row.sufficient && row.avg_pct_error !== null 
                            ? `${row.avg_pct_error}%` 
                            : '—'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </CardContent>
          </Card>

          {/* Methodology Note */}
          <Card sx={{ border: '1px solid rgba(59, 130, 246, 0.2)', bgcolor: 'rgba(59, 130, 246, 0.02)' }}>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: 'text.primary', mb: 1 }}>
                Methodology
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                When a prediction's timeframe elapses, the platform fetches the actual market close price and grades whether the predicted move direction was correct, alongside tracking target absolute deviation errors. No calls are filtered or skipped. Directional accuracy represents correct move predictions and does not guarantee investment returns.
              </Typography>
            </CardContent>
          </Card>
        </Box>
      )}
    </Box>
  );
};
