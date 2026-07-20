import { useState } from 'react';
import axios from 'axios';
import toast from 'react-hot-toast';
import { 
  Box, Card, CardContent, Typography, TextField, 
  Button, ToggleButtonGroup, ToggleButton, Divider,
  FormControl, Select, MenuItem, InputLabel, CircularProgress
} from '@mui/material';

export const OrderTicket = () => {
  const [symbol, setSymbol] = useState('');
  const [qty, setQty] = useState('');
  const [action, setAction] = useState('buy');
  const [orderType, setOrderType] = useState('market');
  const [limitPrice, setLimitPrice] = useState('');
  const [stopPrice, setStopPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol || !qty) {
      toast.error('Symbol and Quantity are required');
      return;
    }

    setSubmitting(true);
    try {
      const payload: any = {
        ticker: symbol.toUpperCase(),
        quantity: parseFloat(qty),
        side: action,
        order_type: orderType
      };
      if (orderType === 'limit') payload.target_price = parseFloat(limitPrice);
      if (orderType === 'stop') payload.target_price = parseFloat(stopPrice);

      const res = await axios.post('/api/manual-paper/order', payload);
      if (res.data && res.data.ok) {
        toast.success('Order placed successfully');
        setQty('');
        setLimitPrice('');
        setStopPrice('');
      } else {
        toast.error(res.data.error || 'Failed to place order');
      }
    } catch (err: any) {
      toast.error(err.response?.data?.error || 'Error placing order');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', p: 3 }}>
        <Typography variant="h3" color="text.secondary" gutterBottom>
          Order Ticket
        </Typography>
        <Divider sx={{ mb: 3 }} />
        
        <Box component="form" onSubmit={handleSubmit} sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 3 }}>
          <ToggleButtonGroup
            value={action}
            exclusive
            onChange={(_, newVal) => newVal && setAction(newVal)}
            fullWidth
            sx={{
              '& .MuiToggleButton-root': {
                py: 1.5,
                fontWeight: 600,
                border: '1px solid rgba(255, 255, 255, 0.1)',
                '&.Mui-selected': {
                  bgcolor: action === 'buy' ? 'secondary.main' : 'error.main',
                  color: '#fff',
                  '&:hover': {
                    bgcolor: action === 'buy' ? 'secondary.dark' : 'error.dark',
                  }
                }
              }
            }}
          >
            <ToggleButton value="buy">BUY</ToggleButton>
            <ToggleButton value="sell">SELL</ToggleButton>
          </ToggleButtonGroup>

          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Symbol"
              variant="outlined"
              size="small"
              fullWidth
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="AAPL"
              required
            />
            <TextField
              label="Quantity"
              variant="outlined"
              size="small"
              type="number"
              slotProps={{ htmlInput: { step: 'any' } }}
              fullWidth
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              placeholder="0"
              required
            />
          </Box>

          <FormControl size="small" fullWidth>
            <InputLabel>Order Type</InputLabel>
            <Select
              value={orderType}
              label="Order Type"
              onChange={(e) => setOrderType(e.target.value)}
            >
              <MenuItem value="market">Market Order</MenuItem>
              <MenuItem value="limit">Limit Order</MenuItem>
              <MenuItem value="stop">Stop Order</MenuItem>
            </Select>
          </FormControl>

          {orderType === 'limit' && (
            <TextField
              label="Limit Price"
              variant="outlined"
              size="small"
              type="number"
              slotProps={{ htmlInput: { step: 'any' } }}
              fullWidth
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              placeholder="0.00"
              required
            />
          )}

          {orderType === 'stop' && (
            <TextField
              label="Stop Price"
              variant="outlined"
              size="small"
              type="number"
              slotProps={{ htmlInput: { step: 'any' } }}
              fullWidth
              value={stopPrice}
              onChange={(e) => setStopPrice(e.target.value)}
              placeholder="0.00"
              required
            />
          )}

          <Box sx={{ mt: 'auto', pt: 2 }}>
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={submitting}
              sx={{
                py: 1.5,
                bgcolor: action === 'buy' ? 'secondary.main' : 'error.main',
                color: '#fff',
                fontWeight: 700,
                fontSize: '1rem',
                background: 'none',
                '&:hover': {
                  bgcolor: action === 'buy' ? 'secondary.dark' : 'error.dark',
                },
                '&.Mui-disabled': {
                  bgcolor: 'rgba(255, 255, 255, 0.12)',
                  color: 'rgba(255, 255, 255, 0.3)',
                }
              }}
            >
              {submitting ? <CircularProgress size={24} color="inherit" /> : `Place ${action.toUpperCase()} Order`}
            </Button>
          </Box>
        </Box>
      </CardContent>
    </Card>
  );
};
