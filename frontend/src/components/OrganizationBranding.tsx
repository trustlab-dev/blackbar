import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Paper,
  TextField,
  Button,
  Alert,
  CircularProgress,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import api from '../api/client';

interface BrandingData {
  org_name: string;
  primary_color: string;
}

const OrganizationBranding: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [formData, setFormData] = useState<BrandingData>({
    org_name: '',
    primary_color: '#0366d6',
  });

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    try {
      const response = await api.get('/admin/config/');
      const data = response.data;

      setFormData({
        org_name: data.org_name || '',
        primary_color: data.primary_color || '#0366d6',
      });
    } catch (error) {
      console.error('Error fetching config:', error);
      setError('Failed to load configuration');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);

    try {
      await api.put('/admin/config/', {
        org_name: formData.org_name,
        primary_color: formData.primary_color,
      });

      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (error: any) {
      console.error('Error saving branding:', error);
      setError(error.response?.data?.detail || 'Failed to save branding');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
        Instance Branding
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {success && (
        <Alert severity="success" sx={{ mb: 3 }}>
          Branding updated successfully!
        </Alert>
      )}

      <Paper sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* Organization Name */}
          <TextField
            label="Organization Name"
            value={formData.org_name}
            onChange={(e) => setFormData({ ...formData, org_name: e.target.value })}
            fullWidth
            helperText="Public-facing organization name shown on public pages"
          />

          {/* Primary Color */}
          <Box>
            <Typography variant="subtitle2" gutterBottom>
              Primary Color
            </Typography>
            <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
              <input
                type="color"
                value={formData.primary_color}
                onChange={(e) => setFormData({ ...formData, primary_color: e.target.value })}
                style={{ width: 60, height: 40, border: '1px solid #ccc', borderRadius: 4 }}
              />
              <TextField
                value={formData.primary_color}
                onChange={(e) => setFormData({ ...formData, primary_color: e.target.value })}
                size="small"
                sx={{ width: 120 }}
              />
              <Typography variant="body2" color="text.secondary">
                Brand color for public pages
              </Typography>
            </Box>
          </Box>

          {/* Save Button */}
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
            <Button
              variant="contained"
              startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? 'Saving...' : 'Save Changes'}
            </Button>
          </Box>
        </Box>
      </Paper>
    </Box>
  );
};

export default OrganizationBranding;
