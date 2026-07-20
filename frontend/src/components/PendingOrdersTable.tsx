import { useEffect, useState } from 'react';
import axios from 'axios';
import toast from 'react-hot-toast';
import { 
  Card, CardContent, Typography, Box, CircularProgress, 
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Button 
} from '@mui/material';

export const PendingOrdersTable = () => {
  const [orders, setOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchOrders = async () => {
    try {
      const res = await axios.get('/api/manual-paper/account');
      if (res.data && res.data.ok) {
        setOrders(res.data.orders?.filter((o: any) => o.status === 'pending') || []);
      }
    } catch (err) {
      console.error('Error fetching orders:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders();
    const interval = setInterval(fetchOrders, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleCancelOrder = async (orderId: number) => {
    try {
      const res = await axios.post(`/api/manual-paper/cancel`, { order_id: orderId });
      if (res.data && res.data.ok) {
        toast.success('Order cancelled');
        fetchOrders();
      } else {
        toast.error(res.data.error || 'Failed to cancel order');
      }
    } catch (err: any) {
      toast.error(err.response?.data?.error || 'Error cancelling order');
    }
  };

  if (!loading && orders.length === 0) {
    return null; // Don't show if no pending orders
  }

  return (
    <Card sx={{ mt: 3, width: '100%' }}>
      <CardContent sx={{ p: 3 }}>
        <Typography variant="h3" color="text.secondary" gutterBottom>
          Pending Orders
        </Typography>

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
            <CircularProgress />
          </Box>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Symbol</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Action</TableCell>
                  <TableCell align="right">Qty</TableCell>
                  <TableCell align="right">Target Price</TableCell>
                  <TableCell align="right">Cancel</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {orders.map((o, i) => (
                  <TableRow key={i} hover sx={{ '&:last-child td, &:last-child th': { border: 0 } }}>
                    <TableCell component="th" scope="row" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                      {o.ticker}
                    </TableCell>
                    <TableCell sx={{ textTransform: 'uppercase', fontSize: '0.75rem', color: 'text.secondary' }}>
                      {o.order_type}
                    </TableCell>
                    <TableCell sx={{ 
                      textTransform: 'uppercase', 
                      fontSize: '0.75rem', 
                      fontWeight: 'bold',
                      color: o.side === 'buy' ? 'secondary.main' : 'error.main'
                    }}>
                      {o.side}
                    </TableCell>
                    <TableCell align="right">{o.quantity}</TableCell>
                    <TableCell align="right">${o.target_price?.toFixed(2)}</TableCell>
                    <TableCell align="right">
                      <Button 
                        variant="outlined" 
                        color="error" 
                        size="small"
                        onClick={() => handleCancelOrder(o.id)}
                        sx={{ textTransform: 'none', borderRadius: 1 }}
                      >
                        Cancel
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </CardContent>
    </Card>
  );
};
