import React, { useState, useEffect, useCallback } from 'react';
import { Box, Typography, Card, CardContent, TextField, Button, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper, CircularProgress, Select, MenuItem, Chip, IconButton, Grid } from '@mui/material';
import { Bell, Trash2, AlertCircle } from 'lucide-react';
import { apiFetch } from '../utils/api';
import toast from 'react-hot-toast';

interface PriceAlert {
  id: number;
  ticker: string;
  target_price: number;
  condition: 'ABOVE' | 'BELOW';
  active: boolean;
  created_at: string;
}

export const AlertsDashboard: React.FC = () => {
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [loading, setLoading] = useState(true);

  // Form State
  const [ticker, setTicker] = useState('');
  const [targetPrice, setTargetPrice] = useState('');
  const [condition, setCondition] = useState<'ABOVE' | 'BELOW'>('ABOVE');
  const [submitting, setSubmitting] = useState(false);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const json = await apiFetch('/api/alerts');
      if (json.ok && json.alerts) {
        setAlerts(json.alerts);
      }
    } catch (err) {
      console.error('Failed to load alerts:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  const handleAddAlert = async () => {
    if (!ticker.trim()) {
      toast.error('Ticker symbol is required');
      return;
    }
    if (!targetPrice.trim() || isNaN(parseFloat(targetPrice))) {
      toast.error('Valid target price is required');
      return;
    }
    setSubmitting(true);
    try {
      const res = await apiFetch('/api/alerts/add', {
        method: 'POST',
        body: {
          ticker: ticker.trim().toUpperCase(),
          target_price: parseFloat(targetPrice),
          condition: condition,
        }
      });
      if (res.ok) {
        toast.success('Price alert set!');
        setTicker('');
        setTargetPrice('');
        fetchAlerts();
      } else {
        toast.error(res.error || 'Failed to set alert');
      }
    } catch (err) {
      toast.error('Network connection error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemoveAlert = async (id: number) => {
    if (!confirm('Are you sure you want to delete this price alert?')) return;
    try {
      const res = await apiFetch('/api/alerts/remove', {
        method: 'POST',
        body: { alert_id: id }
      });
      if (res.ok) {
        toast.success('Alert deleted');
        fetchAlerts();
      } else {
        toast.error(res.error || 'Failed to delete alert');
      }
    } catch (err) {
      toast.error('Network connection error');
    }
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1.5, color: 'text.primary' }}>
            <Bell color="#3b82f6" />
            Price Alerts
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Configure and manage real-time notifications for price breakouts and level triggers.
          </Typography>
        </Box>
      </Box>

      {/* New Alert Form */}
      <Card>
        <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Create Price Alert</Typography>
        </Box>
        <CardContent sx={{ p: 3 }}>
          <Grid container spacing={2.5} sx={{ alignItems: 'flex-end' }}>
            <Grid size={{ xs: 12, sm: 3 }}>
              <TextField 
                label="Ticker Symbol"
                placeholder="e.g. AAPL"
                size="small"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                fullWidth
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              <Select 
                value={condition} 
                onChange={(e) => setCondition(e.target.value as 'ABOVE' | 'BELOW')}
                size="small"
                fullWidth
              >
                <MenuItem value="ABOVE">Price Goes Above</MenuItem>
                <MenuItem value="BELOW">Price Goes Below</MenuItem>
              </Select>
            </Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              <TextField 
                label="Target Price ($)"
                placeholder="e.g. 200.50"
                size="small"
                type="number"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
                fullWidth
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              <Button 
                variant="contained" 
                color="primary" 
                fullWidth 
                onClick={handleAddAlert}
                disabled={submitting}
                sx={{ fontWeight: 'bold', height: 40 }}
              >
                {submitting ? 'Setting Alert...' : 'Add Alert'}
              </Button>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* Active Alerts List Grid */}
      <Card>
        <Box sx={{ px: 3, py: 2, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Active Alerts</Typography>
        </Box>
        <CardContent sx={{ p: 0 }}>
          {loading ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 8, gap: 2 }}>
              <CircularProgress size={24} />
              <Typography color="text.secondary" variant="body2">Loading alerts list...</Typography>
            </Box>
          ) : alerts.length === 0 ? (
            <Box sx={{ py: 8, textAlign: 'center', color: 'text.secondary' }}>
              <AlertCircle size={32} style={{ opacity: 0.3, marginBottom: 8 }} />
              <Typography variant="body2">No price alerts set. Create one above.</Typography>
            </Box>
          ) : (
            <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Ticker</TableCell>
                    <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold' }}>Condition</TableCell>
                    <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Target Price</TableCell>
                    <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'center' }}>Status</TableCell>
                    <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'right' }}>Created Date</TableCell>
                    <TableCell sx={{ color: 'text.secondary', fontWeight: 'bold', textAlign: 'center' }}>Action</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {alerts.map((row) => (
                    <TableRow key={row.id} hover sx={{ '&:last-child td': { border: 0 } }}>
                      <TableCell sx={{ py: 1.5, fontWeight: 'bold', color: 'primary.main' }}>{row.ticker}</TableCell>
                      <TableCell>Price goes <strong>{row.condition.toLowerCase()}</strong></TableCell>
                      <TableCell sx={{ textAlign: 'right', fontWeight: 'medium' }}>${row.target_price.toFixed(2)}</TableCell>
                      <TableCell sx={{ textAlign: 'center' }}>
                        <Chip 
                          label={row.active ? 'Active' : 'Triggered'} 
                          size="small" 
                          color={row.active ? 'success' : 'default'}
                          sx={{ fontWeight: 'bold', height: 20 }}
                        />
                      </TableCell>
                      <TableCell sx={{ textAlign: 'right', color: 'text.secondary' }}>{row.created_at}</TableCell>
                      <TableCell sx={{ textAlign: 'center' }}>
                        <IconButton color="error" size="small" onClick={() => handleRemoveAlert(row.id)}>
                          <Trash2 size={16} />
                        </IconButton>
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
  );
};
