/**
 * Public Verify Page (RFC-007)
 * Handles magic link verification callback
 */
import React from 'react';
import { Box } from '@mui/material';
import { MagicLinkVerify } from '../components/auth/MagicLinkVerify';

export const PublicVerifyPage: React.FC = () => {
  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#f5f5f5'
      }}
    >
      <Box sx={{ maxWidth: 600, mx: 'auto', px: 2 }}>
        <MagicLinkVerify />
      </Box>
    </Box>
  );
};
