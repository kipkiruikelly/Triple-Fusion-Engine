import React from 'react';
import { Database, Filter, Bell, Crosshair } from 'lucide-react';
import { Box, Typography, Card, CardContent, Grid, Chip } from '@mui/material';

export const ToolsDashboard: React.FC = () => {
  const tools = [
    {
      title: 'Backtester',
      description: 'Simulate trading strategies on historical data to evaluate performance.',
      icon: <Database size={32} color="#3b82f6" />,
      color: '#3b82f6'
    },
    {
      title: 'ML Pipeline',
      description: 'View and manage automated model retraining and data pipelines.',
      icon: <Filter size={32} color="#8b5cf6" />,
      color: '#8b5cf6'
    },
    {
      title: 'Alerts Configuration',
      description: 'Set up Telegram and Discord webhooks for real-time trade alerts.',
      icon: <Bell size={32} color="#10b981" />,
      color: '#10b981'
    },
    {
      title: 'Risk Manager',
      description: 'Calculate optimal position sizes and manage portfolio risk.',
      icon: <Crosshair size={32} color="#ef4444" />,
      color: '#ef4444'
    }
  ];

  return (
    <Box sx={{ flex: 1, overflowY: 'auto', p: { xs: 2, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h2" sx={{ fontSize: '1.5rem', color: 'text.primary', fontWeight: 'bold' }}>
          Strategy Tools
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Advanced tooling for algorithmic trading.
        </Typography>
      </Box>

      <Grid container spacing={3}>
        {tools.map((tool, idx) => (
          <Grid size={{ xs: 12, md: 6 }} key={idx}>
            <Card 
              sx={{ 
                height: '100%',
                cursor: 'pointer',
                transition: 'all 0.2s ease-in-out',
                border: '1px solid',
                borderColor: 'divider',
                '&:hover': {
                  borderColor: tool.color,
                  transform: 'translateY(-4px)',
                  boxShadow: `0 8px 24px ${tool.color}33` // Add subtle colored glow
                }
              }}
            >
              <CardContent sx={{ p: 4, display: 'flex', flexDirection: 'column', height: '100%' }}>
                <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 3 }}>
                  <Box sx={{ 
                    p: 1.5, 
                    borderRadius: 2, 
                    bgcolor: `${tool.color}15`, // 15% opacity background
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}>
                    {tool.icon}
                  </Box>
                  <Chip label="Module" size="small" variant="outlined" />
                </Box>
                
                <Typography variant="h5" gutterBottom sx={{ fontWeight: 'bold',  
                  transition: 'color 0.2s',
                  '.MuiCard-root:hover &': {
                    color: tool.color
                  }
                }}>
                  {tool.title}
                </Typography>
                
                <Typography variant="body2" color="text.secondary" sx={{ flex: 1, lineHeight: 1.6 }}>
                  {tool.description}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
};
