import React, { useState, useEffect } from 'react';
import { Cpu, Check, Plus, AlertCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { Box, Typography, Card, CardContent, Button, Grid, CircularProgress, Chip } from '@mui/material';
import { apiFetch } from '../utils/api';

interface Bot {
  id: number;
  name: string;
  description: string;
  asset_class: string;
  is_subscribed: boolean;
}

export const BotsDashboard: React.FC = () => {
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchBots = async () => {
    try {
      const json = await apiFetch('/api/bots');
      if (json.ok) {
        const botsList = json.bots || (json.data && json.data.bots) || [];
        const mapped = botsList.map((b: any) => ({
          ...b,
          is_subscribed: b.is_subscribed !== undefined ? b.is_subscribed : b.subscribed
        }));
        setBots(mapped);
      }
    } catch (err) {
      console.error('Failed to fetch bots:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBots();
  }, []);

  const toggleSubscription = async (botId: number, botName: string) => {
    try {
      const form = new FormData();
      form.append('bot_id', botId.toString());
      const data = await apiFetch('/api/bots/subscribe', {
        method: 'POST',
        body: form
      });
      
      if (data.ok) {
        const isSubscribed = data.subscribed !== undefined ? data.subscribed : (data.data && data.data.is_subscribed);
        setBots(prev => prev.map(b => 
          b.id === botId ? { ...b, is_subscribed: isSubscribed } : b
        ));
        if (isSubscribed) {
          toast.success(`Subscribed to ${botName}`);
        } else {
          toast.success(`Unsubscribed from ${botName}`);
        }
      } else {
        toast.error(data.error || 'Failed to toggle subscription');
      }
    } catch (err) {
      toast.error('Network error');
    }
  };

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, justifyContent: 'space-between', gap: 2 }}>
        <Box>
          <Typography variant="h2" sx={{ display: 'flex', alignItems: 'center', gap: 1.5, fontSize: '1.5rem', color: 'text.primary' }}>
            <Cpu color="#3b82f6" />
            AI Robots
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Subscribe to automated trading strategies powered by our proprietary machine learning models.
          </Typography>
        </Box>
      </Box>

      {/* Grid */}
      <Grid container spacing={3}>
        {loading ? (
          <Grid size={12}>
            <Box sx={{ py: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <CircularProgress />
              <Typography color="text.secondary">Loading AI models...</Typography>
            </Box>
          </Grid>
        ) : bots.length === 0 ? (
          <Grid size={12}>
            <Box sx={{ py: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <AlertCircle size={48} color="rgba(255,255,255,0.3)" />
              <Typography color="text.secondary">No active robots found.</Typography>
            </Box>
          </Grid>
        ) : (
          bots.map((bot) => (
            <Grid size={{ xs: 12, md: 6, lg: 4 }} key={bot.id}>
              <Card 
                sx={{ 
                  height: '100%', 
                  display: 'flex', 
                  flexDirection: 'column', 
                  transition: 'transform 0.2s, box-shadow 0.2s',
                  '&:hover': {
                    transform: 'translateY(-4px)',
                    boxShadow: '0 12px 40px rgba(0,0,0,0.5)'
                  }
                }}
              >
                <CardContent sx={{ p: 3, flex: 1, display: 'flex', flexDirection: 'column' }}>
                  <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 2 }}>
                    <Typography variant="h6" sx={{ fontWeight: 'bold' }}>
                      {bot.name}
                    </Typography>
                    <Chip 
                      label={bot.asset_class} 
                      color="success" 
                      size="small" 
                      sx={{ fontWeight: 'bold', borderRadius: 1 }}
                    />
                  </Box>
                  
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 3, flex: 1, lineHeight: 1.6 }}>
                    {bot.description}
                  </Typography>
                  
                  <Button
                    fullWidth
                    variant={bot.is_subscribed ? "outlined" : "contained"}
                    color={bot.is_subscribed ? "secondary" : "primary"}
                    onClick={() => toggleSubscription(bot.id, bot.name)}
                    startIcon={bot.is_subscribed ? <Check size={16} /> : <Plus size={16} />}
                  >
                    {bot.is_subscribed ? 'Subscribed' : 'Subscribe'}
                  </Button>
                </CardContent>
              </Card>
            </Grid>
          ))
        )}
      </Grid>
    </Box>
  );
};
