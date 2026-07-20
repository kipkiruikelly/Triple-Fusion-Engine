import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Activity } from 'lucide-react';
import toast from 'react-hot-toast';
import { Box, Typography, Card, CardContent, TextField, Button, CircularProgress } from '@mui/material';

export const ResetPassword: React.FC = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const navigate = useNavigate();
  
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) {
      toast.error('Invalid or missing reset token');
      navigate('/login');
    }
  }, [token, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      toast.error('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }
    
    setLoading(true);
    try {
      const res = await fetch('/api/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, password, confirm }),
      });
      const data = await res.json();
      if (data.ok) {
        toast.success('Password reset successful. Please log in.');
        navigate('/login');
      } else {
        toast.error(data.error || 'Failed to reset password');
      }
    } catch (err) {
      toast.error('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  if (!token) return null;

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', p: 3 }}>
      <Box sx={{ mb: 4, display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <Activity size={36} color="#8b5cf6" />
        <Typography variant="h2" sx={{ color: 'text.primary', fontWeight: 800, letterSpacing: '0.02em' }}>
          BullLogic
        </Typography>
      </Box>
      
      <Card sx={{ w: '100%', maxWidth: 400, width: '100%' }}>
        <CardContent sx={{ p: { xs: 4, md: 5 } }}>
          <Typography variant="h4" align="center" gutterBottom sx={{ mb: 4 }}>
            Create New Password
          </Typography>
          
          <Box component="form" onSubmit={handleSubmit} sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <TextField 
              label="New Password"
              type="password"
              variant="outlined"
              fullWidth
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
            
            <TextField 
              label="Confirm Password"
              type="password"
              variant="outlined"
              fullWidth
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="••••••••"
            />
            
            <Button 
              type="submit" 
              variant="contained" 
              color="primary" 
              size="large"
              fullWidth
              disabled={loading}
              sx={{ mt: 2, py: 1.5 }}
            >
              {loading ? <CircularProgress size={24} color="inherit" /> : 'Reset Password'}
            </Button>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
};
