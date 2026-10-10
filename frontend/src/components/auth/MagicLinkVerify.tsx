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
import { publicApi } from '../../api/client';
import { getApiErrorMessage } from '../../api/errors';
import { useCapabilityFromUrl } from '../../utils/capabilityUrl';

export const MagicLinkVerify: React.FC = () => {
  // Single-use token: take it out of the address bar straight away and keep
  // it only in memory. A refresh lands on /public/verify with no token.
  const token = useCapabilityFromUrl(useParams().token, { cleanPath: '/public/verify' });
  const navigate = useNavigate();
  const [status, setStatus] = useState<'verifying' | 'success' | 'error'>('verifying');
  const [error, setError] = useState('');

  useEffect(() => {
    const verifyToken = async () => {
      if (!token) {
        setStatus('error');
        setError(
          'This sign-in link has already been used or is incomplete. Sign-in links work once; request a new one to continue.',
        );
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
        const response = await publicApi.post('/auth/public/magic-link/verify', {
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
          setError(getApiErrorMessage(err, 'Failed to verify magic link. Please try again.'));
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
