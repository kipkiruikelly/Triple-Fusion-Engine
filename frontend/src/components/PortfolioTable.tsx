import { useEffect, useState } from 'react';
import axios from 'axios';
import toast from 'react-hot-toast';
import { 
  Card, CardContent, Typography, Box, CircularProgress, 
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Button 
} from '@mui/material';

export const PortfolioTable = () => {
  const [positions, setPositions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPositions = async () => {
    try {
      const res = await axios.get('/api/manual-paper/account');
      if (res.data && res.data.ok) {
        setPositions(res.data.positions || []);
      }
    } catch (err) {
      console.error('Error fetching positions:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, 5000); // refresh every 5s
    return () => clearInterval(interval);
  }, []);

  const handleClosePosition = async (symbol: string, qty: number) => {
    const action = qty > 0 ? 'sell' : 'buy';
    const closeQty = Math.abs(qty);
    
    try {
      const payload = {
        ticker: symbol,
        quantity: closeQty,
        side: action,
        order_type: 'market'
      };
      const res = await axios.post('/api/manual-paper/order', payload);
      if (res.data && res.data.ok) {
        toast.success(`Closed position for ${symbol}`);
        fetchPositions();
      } else {
        toast.error(res.data.error || 'Failed to close position');
      }
    } catch (err: any) {
      toast.error(err.response?.data?.msg || 'Error closing position');
    }
  };

  return (
    <Card sx={{ width: '100%' }}>
      <CardContent sx={{ p: 3 }}>
        <Typography variant="h3" color="text.secondary" gutterBottom>
          Open Positions
        </Typography>

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
            <CircularProgress />
          </Box>
        ) : positions.length === 0 ? (
          <Typography color="text.secondary" align="center" sx={{ py: 4 }}>
            No open positions. Use the order ticket to enter a trade.
          </Typography>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Symbol</TableCell>
                  <TableCell align="right">Shares</TableCell>
                  <TableCell align="right">Entry</TableCell>
                  <TableCell align="right">Current</TableCell>
                  <TableCell align="right">Unrealized P&L</TableCell>
                  <TableCell align="right">Action</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {positions.map((p, i) => {
                  const isProfit = p.unrealized_pnl >= 0;
                  return (
                    <TableRow key={i} hover sx={{ '&:last-child td, &:last-child th': { border: 0 } }}>
                      <TableCell component="th" scope="row" sx={{ fontWeight: 'bold', color: 'text.primary' }}>
                        {p.symbol}
                      </TableCell>
                      <TableCell align="right">{p.qty}</TableCell>
                      <TableCell align="right">${p.entry_price.toFixed(2)}</TableCell>
                      <TableCell align="right">${p.current_price.toFixed(2)}</TableCell>
                      <TableCell align="right" sx={{ color: isProfit ? 'secondary.main' : 'error.main', fontWeight: 600 }}>
                        {isProfit ? '+' : ''}${p.unrealized_pnl.toFixed(2)}
                      </TableCell>
                      <TableCell align="right">
                        <Button 
                          variant="outlined" 
                          color="error" 
                          size="small"
                          onClick={() => handleClosePosition(p.symbol, p.qty)}
                          sx={{ textTransform: 'none', borderRadius: 1 }}
                        >
                          Close
                        </Button>
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
  );
};
