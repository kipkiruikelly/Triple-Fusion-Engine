import React, { useState, useEffect } from 'react';
import { Star, RefreshCw, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { 
  Card, CardHeader, CardContent, Typography, Box, 
  IconButton, TextField, List, ListItem, ListItemText, ListItemSecondaryAction,
  Divider, CircularProgress 
} from '@mui/material';
import { apiFetch } from '../utils/api';

interface WatchlistItem {
  ticker: string;
  added_at: string;
  price: number | null;
}

export const WatchlistWidget: React.FC = () => {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchWatchlist = async () => {
    try {
      const json = await apiFetch('/api/watchlist');
      if (json.ok && json.watchlist) {
        setWatchlist(json.watchlist);
      }
    } catch (err) {
      console.error('Failed to fetch watchlist:', err);
    } finally {
      setLoading(false);
    }
  };

  const removeTicker = async (ticker: string) => {
    try {
      const data = await apiFetch('/api/watchlist/remove', {
        method: 'POST',
        body: { ticker }
      });
      if (data.ok) {
        toast.success(`${ticker} removed from watchlist`);
        fetchWatchlist();
      } else {
        toast.error(data.error || 'Failed to remove ticker');
      }
    } catch (err) {
      toast.error('Network error');
    }
  };

  const addTicker = async (ticker: string) => {
    try {
      const data = await apiFetch('/api/watchlist/add', {
        method: 'POST',
        body: { ticker }
      });
      if (data.ok) {
        toast.success(`${ticker} added to watchlist`);
        fetchWatchlist();
      } else {
        toast.error(data.error || 'Failed to add ticker');
      }
    } catch (err) {
      toast.error('Network error');
    }
  };

  useEffect(() => {
    fetchWatchlist();
    const interval = setInterval(fetchWatchlist, 10000); // refresh every 10s
    return () => clearInterval(interval);
  }, []);

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardHeader 
        title={
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Star size={18} color="#8b5cf6" />
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Watchlist</Typography>
          </Box>
        }
        action={
          <IconButton onClick={fetchWatchlist} size="small" sx={{ color: 'text.secondary', '&:hover': { color: 'text.primary' } }}>
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </IconButton>
        }
        sx={{ borderBottom: 1, borderColor: 'divider', pb: 2 }}
      />
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <TextField 
          fullWidth
          size="small"
          placeholder="Add ticker..."
          variant="outlined"
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              const val = (e.target as HTMLInputElement).value.toUpperCase();
              if (val) {
                addTicker(val);
                (e.target as HTMLInputElement).value = '';
              }
            }
          }}
          sx={{
            '& .MuiOutlinedInput-input': {
              textTransform: 'uppercase',
            }
          }}
        />
      </Box>
      <CardContent sx={{ flex: 1, overflowY: 'auto', p: 0, '&:last-child': { pb: 0 } }}>
        {loading && watchlist.length === 0 ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : watchlist.length === 0 ? (
          <Typography color="text.secondary" align="center" sx={{ p: 4, fontSize: '0.875rem' }}>
            Your watchlist is empty
          </Typography>
        ) : (
          <List disablePadding>
            {watchlist.map((item, idx) => (
              <React.Fragment key={item.ticker}>
                <ListItem 
                  sx={{ 
                    py: 1.5, 
                    px: 2,
                    '&:hover': { bgcolor: 'rgba(255, 255, 255, 0.02)' }
                  }}
                >
                  <ListItemText 
                    primary={<Typography sx={{ fontWeight: 600 }}>{item.ticker}</Typography>}
                    secondary={
                      <Typography variant="body2" color="text.secondary" component="span">
                        {item.price ? `$${item.price.toFixed(2)}` : 'Loading...'}
                      </Typography>
                    }
                  />
                  <ListItemSecondaryAction>
                    <IconButton edge="end" onClick={() => removeTicker(item.ticker)} size="small" sx={{ color: 'text.secondary', '&:hover': { color: 'error.main' } }}>
                      <X size={16} />
                    </IconButton>
                  </ListItemSecondaryAction>
                </ListItem>
                {idx < watchlist.length - 1 && <Divider component="li" />}
              </React.Fragment>
            ))}
          </List>
        )}
      </CardContent>
    </Card>
  );
};
