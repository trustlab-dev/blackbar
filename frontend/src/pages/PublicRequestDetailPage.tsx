/**
 * Public Request Detail Page (RFC-007)
 * Detailed view of a single FOI request
 */
import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Typography, Button } from '@mui/material';
import LogoutIcon from '@mui/icons-material/Logout';
import { RequestDetailsPage } from '../components/public/RequestDetailsPage';

export const PublicRequestDetailPage: React.FC = () => {
  const navigate = useNavigate();

  // Check authentication
  useEffect(() => {
    const token = localStorage.getItem('token');
    const userType = localStorage.getItem('user_type');
    
    if (!token || userType !== 'public') {
      navigate('/public/login');
    }
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    localStorage.removeItem('user_type');
    localStorage.removeItem('magic_link_email'); // Clear saved email
    navigate('/public/login');
  };

  const user = JSON.parse(localStorage.getItem('user') || '{}');

  return (
    <Box sx={{ minHeight: '100vh', backgroundColor: 'var(--bg-tertiary)' }}>
      {/* Top Navigation */}
      <Box sx={{ backgroundColor: 'var(--color-primary)', color: 'white', px: 3, py: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', maxWidth: 1200, mx: 'auto' }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            FOI Portal
          </Typography>
          {user.email && (
            <Typography variant="body2" sx={{ mr: 2 }}>
              {user.email}
            </Typography>
          )}
          <Button
            sx={{ color: 'white' }}
            startIcon={<LogoutIcon />}
            onClick={handleLogout}
          >
            Sign Out
          </Button>
        </Box>
      </Box>

      {/* Request Details Content */}
      <Box sx={{ maxWidth: 1200, mx: 'auto', py: 4, px: 2 }}>
        <RequestDetailsPage />
      </Box>
    </Box>
  );
};
