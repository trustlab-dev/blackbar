/**
 * Public Login Page
 * Landing page for public users — magic-link login, plus an env-gated
 * one-click demo persona for local development and demos.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Typography, Paper, Button, Alert, Divider } from '@mui/material';
import { MagicLinkLogin } from '../components/auth/MagicLinkLogin';
import axios from 'axios';

export const PublicLoginPage: React.FC = () => {
  const navigate = useNavigate();
  const [orgConfig, setOrgConfig] = useState<{
    org_name: string;
    org_logo_url: string | null;
    primary_color: string;
    footer_text: string | null;
    demo_mode: boolean;
  }>({
    org_name: 'Freedom of Information Portal',
    org_logo_url: null,
    primary_color: '#0366d6',
    footer_text: null,
    demo_mode: false
  });
  const [demoLoginLoading, setDemoLoginLoading] = useState(false);
  const [demoLoginError, setDemoLoginError] = useState<string | null>(null);

  // Fetch organization branding + demo-mode flag
  useEffect(() => {
    const fetchBranding = async () => {
      try {
        const response = await axios.get('/api/v1/admin/config/public');
        setOrgConfig({
          org_name: response.data.org_name || 'Freedom of Information Portal',
          org_logo_url: response.data.org_logo_url,
          primary_color: response.data.primary_color || '#0366d6',
          footer_text: response.data.footer_text || null,
          demo_mode: Boolean(response.data.demo_mode)
        });
      } catch (error) {
        console.error('Error fetching public config:', error);
      }
    };
    fetchBranding();
  }, []);

  const handleDemoLogin = async () => {
    setDemoLoginLoading(true);
    setDemoLoginError(null);
    try {
      const response = await axios.post('/api/v1/auth/public/demo-login');
      const { access_token, user } = response.data;
      // Same localStorage shape as MagicLinkVerify so downstream pages
      // can't tell the difference between a demo and a real session.
      localStorage.setItem('token', access_token);
      localStorage.setItem('userId', user.id || user.user_id || '');
      localStorage.setItem('user_type', 'public');
      navigate('/public/dashboard');
    } catch (err: any) {
      setDemoLoginError(
        err.response?.status === 404
          ? 'Demo mode is disabled on this deployment.'
          : (err.response?.data?.detail || 'Demo login failed. Try again.')
      );
    } finally {
      setDemoLoginLoading(false);
    }
  };

  // Check if already authenticated
  useEffect(() => {
    const token = localStorage.getItem('token');
    const userType = localStorage.getItem('user_type');

    if (token && userType === 'public') {
      // Already logged in, redirect to dashboard
      navigate('/public/dashboard');
    }
  }, [navigate]);

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg-tertiary)',
        py: 8
      }}
    >
      <Box sx={{ maxWidth: 600, mx: 'auto', px: 2 }}>
        {/* Header */}
        <Box sx={{ textAlign: 'center', mb: 4 }}>
          {/* Org Logo */}
          {orgConfig.org_logo_url && (
            <Box sx={{ mb: 3 }}>
              <img
                src={orgConfig.org_logo_url}
                alt={orgConfig.org_name}
                style={{ maxHeight: '100px', maxWidth: '300px' }}
              />
            </Box>
          )}
          <Typography
            variant="h3"
            gutterBottom
            sx={{
              fontWeight: 600,
              color: orgConfig.primary_color
            }}
          >
            {orgConfig.org_name}
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Sign in to view and manage your FOI requests
          </Typography>
        </Box>

        {/* Login Component */}
        <MagicLinkLogin
          onSuccess={() => {
            console.log('Magic link sent successfully');
          }}
        />

        {/* Demo-mode one-click login. Only renders when BLACKBAR_DEMO_MODE
            is true in the backend env. Never in production. */}
        {orgConfig.demo_mode && (
          <Box sx={{ mt: 3 }}>
            <Divider sx={{ mb: 2 }}>
              <Typography variant="caption" color="text.secondary">
                or
              </Typography>
            </Divider>
            <Paper
              elevation={0}
              sx={{
                p: 2,
                border: '1px dashed #ffa726',
                backgroundColor: '#fff8e1',
                borderRadius: 1,
              }}
            >
              <Typography variant="caption" sx={{ display: 'block', fontWeight: 600, color: '#bf6900' }}>
                DEMO MODE
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 1.5 }}>
                Skip the magic-link email and log in as the demo requester
                (Jordan Park). Visible because <code>BLACKBAR_DEMO_MODE=true</code>
                on this backend; never enabled in production.
              </Typography>
              <Button
                variant="outlined"
                color="warning"
                fullWidth
                onClick={handleDemoLogin}
                disabled={demoLoginLoading}
                sx={{ textTransform: 'none' }}
              >
                {demoLoginLoading ? 'Signing in…' : 'Log in as Jordan Park (demo)'}
              </Button>
              {demoLoginError && (
                <Alert severity="error" sx={{ mt: 1.5 }} onClose={() => setDemoLoginError(null)}>
                  {demoLoginError}
                </Alert>
              )}
            </Paper>
          </Box>
        )}

        {/* Footer */}
        <Paper elevation={0} sx={{ mt: 4, p: 3, textAlign: 'center', backgroundColor: 'transparent' }}>
          <Typography variant="body2" color="text.secondary">
            New to our portal? Enter your email above to get started.
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            By signing in, you agree to our Terms of Service and Privacy Policy
          </Typography>
          {orgConfig.footer_text && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2, p: 2, backgroundColor: '#f0f0f0', borderRadius: 1 }}>
              {orgConfig.footer_text}
            </Typography>
          )}
        </Paper>
      </Box>
    </Box>
  );
};
