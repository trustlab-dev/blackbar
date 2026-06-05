/**
 * Magic Link Login Component (RFC-007)
 * Passwordless email authentication for public users
 */
import React, { useState } from 'react';
import {
  Box,
  TextField,
  Button,
  Typography,
  Paper,
  CircularProgress,
  Alert
} from '@mui/material';
import EmailIcon from '@mui/icons-material/Email';
import SendIcon from '@mui/icons-material/Send';
import axios from 'axios';

interface MagicLinkLoginProps {
  onSuccess?: () => void;
}

export const MagicLinkLogin: React.FC<MagicLinkLoginProps> = ({
  onSuccess
}) => {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [expiresIn, setExpiresIn] = useState(900);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await axios.post('/api/v1/auth/public/magic-link/request', {
        email,
        name: name || undefined
      });

      // Save email to localStorage for verification step
      localStorage.setItem('magic_link_email', email);

      setExpiresIn(response.data.expires_in);
      setSent(true);
      
      if (onSuccess) {
        onSuccess();
      }
    } catch (err: any) {
      if (err.response?.status === 429) {
        setError('Too many requests. Please wait an hour before trying again.');
      } else {
        setError(err.response?.data?.detail || 'Failed to send magic link. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  if (sent) {
    return (
      <Paper elevation={3} sx={{ p: 4, maxWidth: 500, mx: 'auto', textAlign: 'center' }}>
        <EmailIcon sx={{ fontSize: 64, color: 'primary.main', mb: 2 }} />
        
        <Typography variant="h5" gutterBottom>
          Check your email
        </Typography>
        
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
          We sent a sign-in link to <strong>{email}</strong>
        </Typography>
        
        <Alert severity="info" sx={{ mb: 2 }}>
          The link will expire in {Math.floor(expiresIn / 60)} minutes
        </Alert>
        
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Click the link in your email to continue. You can close this window.
        </Typography>
        
        <Button
          variant="outlined"
          onClick={() => {
            setSent(false);
            setEmail('');
            setName('');
          }}
        >
          Use a different email
        </Button>
      </Paper>
    );
  }

  return (
    <Paper elevation={3} sx={{ p: 4, maxWidth: 500, mx: 'auto' }}>
      <Box sx={{ textAlign: 'center', mb: 3 }}>
        <Typography variant="h5" gutterBottom>
          Continue with your email
        </Typography>
        <Typography variant="body2" color="text.secondary">
          We'll send you a magic link to sign in
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <form onSubmit={handleSubmit}>
        <TextField
          fullWidth
          type="email"
          label="Email address"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
          autoFocus
          sx={{ mb: 2 }}
          InputProps={{
            startAdornment: <EmailIcon sx={{ mr: 1, color: 'action.active' }} />
          }}
        />

        <TextField
          fullWidth
          type="text"
          label="Your name (optional)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={loading}
          sx={{ mb: 3 }}
          helperText="We'll use this to personalize your experience"
        />

        <Button
          type="submit"
          fullWidth
          variant="contained"
          size="large"
          disabled={loading || !email}
          startIcon={loading ? <CircularProgress size={20} /> : <SendIcon />}
        >
          {loading ? 'Sending...' : 'Send magic link'}
        </Button>
      </form>

      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2, textAlign: 'center' }}>
        By continuing, you agree to our Terms of Service and Privacy Policy
      </Typography>
    </Paper>
  );
};
