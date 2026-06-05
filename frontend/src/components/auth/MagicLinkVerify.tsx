/**
 * Magic Link Verification Component (RFC-007)
 * Handles the OAuth callback and token verification
 */
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Box,
  CircularProgress,
  Typography,
  Alert,
  Button,
  Paper
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import axios from 'axios';

export const MagicLinkVerify: React.FC = () => {
  const { token } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<'verifying' | 'success' | 'error'>('verifying');
  const [error, setError] = useState('');

  useEffect(() => {
    const verifyToken = async () => {
      if (!token) {
        setStatus('error');
        setError('Invalid magic link. Missing token.');
        return;
      }

      // Get email from localStorage (saved during magic link request)
      const savedEmail = localStorage.getItem('magic_link_email');
      
      if (!savedEmail) {
        setStatus('error');
        setError('Session expired. Please request a new magic link.');
        return;
      }

      try {
        const response = await axios.post('/api/v1/auth/public/magic-link/verify', {
          token,
          email: savedEmail
        });

        const { access_token, user } = response.data;

        // Store authentication data (minimal — avoid PII in localStorage)
        localStorage.setItem('token', access_token);
        localStorage.setItem('userId', user.id || user.user_id || '');
        localStorage.setItem('user_type', 'public');
        
        // Clear the saved email after successful verification
        localStorage.removeItem('magic_link_email');

        setStatus('success');

        // Redirect to dashboard after brief delay
        setTimeout(() => {
          navigate('/public/dashboard');
        }, 1500);

      } catch (err: any) {
        setStatus('error');
        
        if (err.response?.data?.error === 'invalid_token') {
          setError('This magic link is invalid or has expired. Please request a new one.');
        } else {
          setError(err.response?.data?.detail || 'Failed to verify magic link. Please try again.');
        }
      }
    };

    verifyToken();
  }, [token, navigate]);

  if (status === 'verifying') {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '400px',
          gap: 2
        }}
      >
        <CircularProgress size={64} />
        <Typography variant="h6" color="text.secondary">
          Verifying your magic link...
        </Typography>
      </Box>
    );
  }

  if (status === 'success') {
    return (
      <Paper elevation={3} sx={{ p: 4, maxWidth: 500, mx: 'auto', textAlign: 'center' }}>
        <CheckCircleIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
        <Typography variant="h5" gutterBottom>
          Success!
        </Typography>
        <Typography variant="body1" color="text.secondary">
          You're being redirected to your dashboard...
        </Typography>
      </Paper>
    );
  }

  return (
    <Paper elevation={3} sx={{ p: 4, maxWidth: 500, mx: 'auto', textAlign: 'center' }}>
      <ErrorIcon sx={{ fontSize: 64, color: 'error.main', mb: 2 }} />
      <Typography variant="h5" gutterBottom>
        Verification Failed
      </Typography>
      <Alert severity="error" sx={{ mb: 3, textAlign: 'left' }}>
        {error}
      </Alert>
      <Button
        variant="contained"
        onClick={() => navigate('/public/login')}
      >
        Request a new magic link
      </Button>
    </Paper>
  );
};
