import { useState, useEffect } from 'react';
import axios from 'axios';
import { Box, Typography, Grid, Card, CardContent, CircularProgress, Chip } from '@mui/material';
import { ArrowUpward, ArrowDownward, AccessTime, ShowChart, Star, CheckCircle, CardMembership } from '@mui/icons-material';
import { OrderTicket } from '../components/OrderTicket';
import { PortfolioTable } from '../components/PortfolioTable';
import { PendingOrdersTable } from '../components/PendingOrdersTable';
import { ChartWidget } from '../components/ChartWidget';
import { WatchlistWidget } from '../components/WatchlistWidget';
import { useAuth } from '../context/AuthContext';

interface AccountData {
  balance: number;
  equity: number;
  starting_balance: number;
}

export const TradingDashboard = () => {
  const { user } = useAuth();
  const [account, setAccount] = useState<AccountData | null>(null);
  const [watchlistCount, setWatchlistCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch manual paper trading account data from Flask API
    const fetchAccount = async () => {
      try {
        const res = await axios.get('/api/manual-paper/account');
        if (res.data && res.data.ok && res.data.account) {
          setAccount(res.data.account);
        }
      } catch (err) {
        console.error("Failed to fetch account data", err);
      } finally {
        setLoading(false);
      }
    };

    const fetchWatchlist = async () => {
      try {
        const res = await axios.get('/api/watchlist');
        if (res.data && res.data.ok && res.data.data && res.data.data.watchlist) {
          setWatchlistCount(res.data.data.watchlist.length);
        }
      } catch (err) {
        console.error("Failed to fetch watchlist count", err);
      }
    };
    
    fetchAccount();
    fetchWatchlist();
    const interval = setInterval(() => {
      fetchAccount();
      fetchWatchlist();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Box>
          <Typography variant="h2" sx={{ fontSize: '1.5rem', color: 'text.primary' }}>
            Trading Dashboard
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Real-time overview of your portfolio and market activity.
          </Typography>
        </Box>
        <Box>
          <Chip
            icon={<Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'secondary.main', animation: 'pulse 2s infinite' }} />}
            label="Market Open"
            sx={{
              bgcolor: 'background.paper',
              color: 'secondary.main',
              border: 1,
              borderColor: 'divider',
              px: 1,
              '@keyframes pulse': {
                '0%': { opacity: 1 },
                '50%': { opacity: 0.4 },
                '100%': { opacity: 1 },
              }
            }}
          />
        </Box>
      </Box>

      {/* Stats Row */}
      <Grid container spacing={3}>
        {/* Card 1: Total Equity */}
        <Grid size={{ xs: 12, sm: 6, md: 4, lg: 2.4 }}>
          <Card>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                <Typography variant="h3" color="text.secondary">
                  Total Equity
                </Typography>
                <Box sx={{ p: 1, bgcolor: 'rgba(139, 92, 246, 0.1)', borderRadius: 2, color: 'primary.main', display: 'flex' }}>
                  <ShowChart fontSize="small" />
                </Box>
              </Box>
              {loading ? (
                <CircularProgress size={24} />
              ) : (
                <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1.5 }}>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary' }}>
                    ${account?.equity.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) || '0.00'}
                  </Typography>
                  {account && account.equity >= account.starting_balance ? (
                    <Typography variant="body2" sx={{ color: 'secondary.main', display: 'flex', alignItems: 'center', fontWeight: 600 }}>
                      <ArrowUpward fontSize="inherit" sx={{ mr: 0.5 }} /> +{(((account.equity / account.starting_balance) - 1) * 100).toFixed(2)}%
                    </Typography>
                  ) : account ? (
                    <Typography variant="body2" sx={{ color: 'error.main', display: 'flex', alignItems: 'center', fontWeight: 600 }}>
                      <ArrowDownward fontSize="inherit" sx={{ mr: 0.5 }} /> {(((account.equity / account.starting_balance) - 1) * 100).toFixed(2)}%
                    </Typography>
                  ) : null}
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Card 2: Available Cash */}
        <Grid size={{ xs: 12, sm: 6, md: 4, lg: 2.4 }}>
          <Card>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                <Typography variant="h3" color="text.secondary">
                  Available Cash
                </Typography>
                <Box sx={{ p: 1, bgcolor: 'rgba(160, 165, 177, 0.1)', borderRadius: 2, color: 'text.secondary', display: 'flex' }}>
                  <AccessTime fontSize="small" />
                </Box>
              </Box>
              {loading ? (
                <CircularProgress size={24} />
              ) : (
                <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary' }}>
                  ${account?.balance.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) || '0.00'}
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Card 3: Predictions Made */}
        <Grid size={{ xs: 12, sm: 6, md: 4, lg: 2.4 }}>
          <Card>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                <Typography variant="h3" color="text.secondary">
                  Predictions Made
                </Typography>
                <Box sx={{ p: 1, bgcolor: 'rgba(74, 144, 226, 0.1)', borderRadius: 2, color: '#4a90e2', display: 'flex' }}>
                  <CheckCircle fontSize="small" />
                </Box>
              </Box>
              <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary' }}>
                {user?.total_predictions ?? 0}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, fontSize: '0.75rem' }}>
                {user?.predictions_today ?? 0} today &middot; all time
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Card 4: Watching */}
        <Grid size={{ xs: 12, sm: 6, md: 4, lg: 2.4 }}>
          <Card>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                <Typography variant="h3" color="text.secondary">
                  Watching
                </Typography>
                <Box sx={{ p: 1, bgcolor: 'rgba(255, 107, 53, 0.1)', borderRadius: 2, color: '#ff6b35', display: 'flex' }}>
                  <Star fontSize="small" />
                </Box>
              </Box>
              <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary' }}>
                {watchlistCount}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, fontSize: '0.75rem' }}>
                Instruments on watchlist
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Card 5: Account Plan */}
        <Grid size={{ xs: 12, sm: 6, md: 4, lg: 2.4 }}>
          <Card>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                <Typography variant="h3" color="text.secondary">
                  Account Plan
                </Typography>
                <Box sx={{ p: 1, bgcolor: 'rgba(80, 227, 194, 0.1)', borderRadius: 2, color: '#50e3c2', display: 'flex' }}>
                  <CardMembership fontSize="small" />
                </Box>
              </Box>
              <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary', textTransform: 'capitalize' }}>
                {user?.plan || 'Free'}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, fontSize: '0.75rem' }}>
                {user?.is_plus || user?.is_pro ? 'Unlimited predictions' : `${user?.predictions_remaining ?? 5} remaining today`}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Main Content Area */}
      <Grid container spacing={3}>
        <Grid size={{ xs: 12, xl: 8 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <ChartWidget />
            <PortfolioTable />
          </Box>
        </Grid>
        
        <Grid size={{ xs: 12, xl: 4 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3, height: '100%' }}>
            <OrderTicket />
            <Box sx={{ flex: 1, minHeight: 300 }}>
              <WatchlistWidget />
            </Box>
          </Box>
        </Grid>
      </Grid>
      
      <PendingOrdersTable />
    </Box>
  );
};
