import React, { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Activity, CheckCircle, XCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { Box, Typography, Card, CardContent, CircularProgress, Button } from '@mui/material';

export const VerifyEmail: React.FC = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const navigate = useNavigate();
  const [status, setStatus] = useState<'verifying' | 'success' | 'error'>('verifying');
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    const verifyToken = async () => {
      if (!token) {
        setStatus('error');
        setErrorMsg('No verification token provided.');
        return;
      }

      try {
        const res = await fetch('/api/verify-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
        const data = await res.json();
        
        if (data.ok) {
          setStatus('success');
          toast.success('Email verified successfully!');
          setTimeout(() => navigate('/portfolio'), 2000);
        } else {
          setStatus('error');
          setErrorMsg(data.error || 'Verification failed');
        }
      } catch (err) {
        setStatus('error');
        setErrorMsg('Network error while verifying email.');
      }
    };

    verifyToken();
  }, [token, navigate]);

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', p: 3 }}>
      <Box sx={{ mb: 4, display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <Activity size={36} color="#8b5cf6" />
        <Typography variant="h2" sx={{ color: 'text.primary', fontWeight: 800, letterSpacing: '0.02em' }}>
          BullLogic
        </Typography>
      </Box>
      
      <Card sx={{ w: '100%', maxWidth: 400, width: '100%' }}>
        <CardContent sx={{ p: { xs: 4, md: 5 }, textAlign: 'center' }}>
          {status === 'verifying' && (
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
              <Typography variant="h4">Verifying Email...</Typography>
              <CircularProgress color="primary" />
            </Box>
          )}
          
          {status === 'success' && (
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <CheckCircle size={64} color="#22c55e" />
              <Typography variant="h4">Email Verified</Typography>
              <Typography color="text.secondary">Redirecting to dashboard...</Typography>
            </Box>
          )}
          
          {status === 'error' && (
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
              <XCircle size={64} color="#ef4444" />
              <Typography variant="h4">Verification Failed</Typography>
              <Typography color="error.main">{errorMsg}</Typography>
              <Button 
                variant="outlined" 
                color="inherit" 
                onClick={() => navigate('/login')}
                sx={{ mt: 2 }}
              >
                Back to Login
              </Button>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
};
