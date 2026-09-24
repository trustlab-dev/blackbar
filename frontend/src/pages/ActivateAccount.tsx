import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  TextField,
  Button,
  Alert,
  CircularProgress,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { publicApi } from '../api/client';
import { getApiErrorMessage } from '../api/errors';
import { passwordPolicyError, PASSWORD_REQUIREMENTS_TEXT } from '../utils/passwordPolicy';
import { clearCapability, useCapabilityFromUrl } from '../utils/capabilityUrl';

const ACTIVATION_STASH = 'activation';
const INVALID_LINK = 'Invalid activation link. Please check your email and try again.';

function parseActivation(raw: string | null): { email: string; token: string } | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as { email?: unknown; token?: unknown };
    if (typeof value.email === 'string' && typeof value.token === 'string') {
      return { email: value.email, token: value.token };
    }
  } catch {
    // Corrupt stash: treat as no link.
  }
  return null;
}

// Phase 4 Batch 4.4 (audit F2): use the shared `publicApi` from
// `src/api/client.ts` instead of a local axios + duplicated
// getBaseUrl() helper. `publicApi` already targets `/api/v1` (Vite
// proxy handles the dev / prod split), so call sites pass paths
// rooted at the API namespace (e.g. `/auth/activate-owner`).

const ActivateAccount: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const searchParams = new URLSearchParams(location.search);
  const emailParam = searchParams.get('email');
  const tokenParam = searchParams.get('token');

  // The activation link carries the email and a token in its query string.
  // Take both out of the address bar once read, and keep them in
  // sessionStorage so a refresh before submitting still works.
  const activation = parseActivation(
    useCapabilityFromUrl(
      emailParam && tokenParam ? JSON.stringify({ email: emailParam, token: tokenParam }) : null,
      { cleanPath: '/activate', storageKey: ACTIVATION_STASH },
    ),
  );
  const email = activation?.email ?? emailParam ?? '';
  const token = activation?.token ?? '';

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(activation ? null : INVALID_LINK);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validate passwords match
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    // Validate password strength
    const passwordError = passwordPolicyError(password);
    if (passwordError) {
      setError(passwordError);
      return;
    }

    setLoading(true);

    try {
      await publicApi.post('/auth/activate-owner', {
        email,
        token,
        password,
      });

      clearCapability(ACTIVATION_STASH);
      setSuccess(true);

      // Redirect to login after 3 seconds
      setTimeout(() => {
        navigate('/login');
      }, 3000);
    } catch (err: any) {
      setError(getApiErrorMessage(err, 'Failed to activate account. The link may have expired.'));
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <Box sx={{ maxWidth: 'sm', mx: 'auto' }}>
        <Box sx={{ mt: 8, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <Paper sx={{ p: 4, width: '100%', textAlign: 'center' }}>
            <CheckCircleIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
            <Typography variant="h4" gutterBottom>
              Account Activated!
            </Typography>
            <Typography variant="body1" color="text.secondary" paragraph>
              Your account has been successfully activated. You can now log in with your email and password.
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Redirecting to login page...
            </Typography>
          </Paper>
        </Box>
      </Box>
    );
  }

  return (
    <Box sx={{ maxWidth: 'sm', mx: 'auto' }}>
      <Box sx={{ mt: 8, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <Paper sx={{ p: 4, width: '100%' }}>
          <Typography variant="h4" component="h1" gutterBottom align="center">
            Activate Your Account
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph align="center">
            Set your password to complete account activation
          </Typography>

          {error && (
            <Alert severity="error" sx={{ mb: 3 }}>
              {error}
            </Alert>
          )}

          <Box component="form" onSubmit={handleSubmit} sx={{ mt: 3 }}>
            <TextField
              label="Email"
              type="email"
              value={email}
              fullWidth
              required
              disabled
              sx={{ mb: 2 }}
            />

            <TextField
              label="New Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              fullWidth
              required
              helperText={PASSWORD_REQUIREMENTS_TEXT}
              sx={{ mb: 2 }}
              autoFocus
            />

            <TextField
              label="Confirm Password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              fullWidth
              required
              sx={{ mb: 3 }}
            />

            <Button
              type="submit"
              variant="contained"
              fullWidth
              size="large"
              disabled={loading || !email || !token || !password || !confirmPassword}
            >
              {loading ? <CircularProgress size={24} /> : 'Activate Account'}
            </Button>

            <Box sx={{ mt: 2, textAlign: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                Already have an account?{' '}
                <Button
                  onClick={() => navigate('/login')}
                  sx={{ textTransform: 'none', p: 0, minWidth: 0 }}
                >
                  Log in
                </Button>
              </Typography>
            </Box>
          </Box>
        </Paper>
      </Box>
    </Box>
  );
};

export default ActivateAccount;
