import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Grid,
  Button,
  Alert,
  CircularProgress,
  Tabs,
  Tab
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import UploadIcon from '@mui/icons-material/Upload';
import api from '../../api/client';
import PackCard from './PackCard';
import PackDetailsModal from './PackDetailsModal';
import PackUploader from './PackUploader';
import './PackManagement.css';

interface Pack {
  pack_id: string;
  name: string;
  version: string;
  description: string;
  jurisdiction: {
    country: string;
    region: string;
    legislation_short: string;
  };
  author: string;
  category_count: number;
  status_count: number;
  has_templates: boolean;
  has_ai_prompts: boolean;
  is_active: boolean;
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`pack-tabpanel-${index}`}
      aria-labelledby={`pack-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

const PackManagement: React.FC = () => {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [selectedPack, setSelectedPack] = useState<Pack | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [uploaderOpen, setUploaderOpen] = useState(false);
  const [activating, setActivating] = useState<string | null>(null);
  const [tabValue, setTabValue] = useState(0);

  useEffect(() => {
    fetchPacks();
  }, []);

  const fetchPacks = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.get('/packs/');
      setPacks(response.data.packs || []);
    } catch (err: any) {
      console.error('Error fetching packs:', err);
      setError(err.response?.data?.detail || 'Failed to load packs');
    } finally {
      setLoading(false);
    }
  };

  const handleActivatePack = async (packId: string) => {
    try {
      setActivating(packId);
      setError(null);
      setSuccess(null);

      await api.post(`/packs/activate?pack_id=${packId}`);
      
      setSuccess(`Pack activated successfully! The system is now using ${packId}.`);
      
      // Refresh pack list to update active status
      await fetchPacks();
      
      // Clear success message after 5 seconds
      setTimeout(() => setSuccess(null), 5000);
    } catch (err: any) {
      console.error('Error activating pack:', err);
      setError(err.response?.data?.detail || 'Failed to activate pack');
    } finally {
      setActivating(null);
    }
  };

  const handleViewDetails = (pack: Pack) => {
    setSelectedPack(pack);
    setDetailsOpen(true);
  };

  const handleUploadSuccess = () => {
    setUploaderOpen(false);
    setSuccess('Pack uploaded successfully!');
    fetchPacks();
    setTimeout(() => setSuccess(null), 5000);
  };

  const handleReloadPacks = async () => {
    try {
      setLoading(true);
      await api.post('/packs/reload');
      await fetchPacks();
      setSuccess('Packs reloaded successfully!');
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      console.error('Error reloading packs:', err);
      setError(err.response?.data?.detail || 'Failed to reload packs');
    }
  };

  const handleTabChange = (event: React.SyntheticEvent, newValue: number) => {
    setTabValue(newValue);
  };

  // Filter packs by country
  const canadianPacks = packs.filter(p => p.jurisdiction.country === 'CA');
  const usPacks = packs.filter(p => p.jurisdiction.country === 'US');
  const otherPacks = packs.filter(p => !['CA', 'US'].includes(p.jurisdiction.country));

  const activePack = packs.find(p => p.is_active);

  if (loading && packs.length === 0) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box className="pack-management">
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" gutterBottom>
            Jurisdiction Packs
          </Typography>
          <Typography variant="body2" color="textSecondary">
            Manage jurisdiction-specific configurations for BlackBar
          </Typography>
        </Box>
        <Box display="flex" gap={2}>
          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={handleReloadPacks}
            disabled={loading}
          >
            Reload
          </Button>
          <Button
            variant="contained"
            startIcon={<UploadIcon />}
            onClick={() => setUploaderOpen(true)}
          >
            Upload Pack
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {success && (
        <Alert severity="success" onClose={() => setSuccess(null)} sx={{ mb: 2 }}>
          {success}
        </Alert>
      )}

      {activePack && (
        <Alert severity="info" sx={{ mb: 3 }}>
          <strong>Active Pack:</strong> {activePack.name} (v{activePack.version}) - {activePack.jurisdiction.region}, {activePack.jurisdiction.country}
        </Alert>
      )}

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={tabValue} onChange={handleTabChange}>
          <Tab label={`All Packs (${packs.length})`} />
          <Tab label={`Canada (${canadianPacks.length})`} />
          <Tab label={`United States (${usPacks.length})`} />
          {otherPacks.length > 0 && <Tab label={`Other (${otherPacks.length})`} />}
        </Tabs>
      </Box>

      <TabPanel value={tabValue} index={0}>
        <Grid container spacing={3}>
          {packs.map((pack) => (
            <Grid item xs={12} sm={6} md={4} key={pack.pack_id}>
              <PackCard
                pack={pack}
                onActivate={handleActivatePack}
                onViewDetails={handleViewDetails}
                activating={activating === pack.pack_id}
              />
            </Grid>
          ))}
        </Grid>
      </TabPanel>

      <TabPanel value={tabValue} index={1}>
        <Grid container spacing={3}>
          {canadianPacks.map((pack) => (
            <Grid item xs={12} sm={6} md={4} key={pack.pack_id}>
              <PackCard
                pack={pack}
                onActivate={handleActivatePack}
                onViewDetails={handleViewDetails}
                activating={activating === pack.pack_id}
              />
            </Grid>
          ))}
        </Grid>
        {canadianPacks.length === 0 && (
          <Typography color="textSecondary" align="center">
            No Canadian packs available
          </Typography>
        )}
      </TabPanel>

      <TabPanel value={tabValue} index={2}>
        <Grid container spacing={3}>
          {usPacks.map((pack) => (
            <Grid item xs={12} sm={6} md={4} key={pack.pack_id}>
              <PackCard
                pack={pack}
                onActivate={handleActivatePack}
                onViewDetails={handleViewDetails}
                activating={activating === pack.pack_id}
              />
            </Grid>
          ))}
        </Grid>
        {usPacks.length === 0 && (
          <Typography color="textSecondary" align="center">
            No US packs available
          </Typography>
        )}
      </TabPanel>

      {otherPacks.length > 0 && (
        <TabPanel value={tabValue} index={3}>
          <Grid container spacing={3}>
            {otherPacks.map((pack) => (
              <Grid item xs={12} sm={6} md={4} key={pack.pack_id}>
                <PackCard
                  pack={pack}
                  onActivate={handleActivatePack}
                  onViewDetails={handleViewDetails}
                  activating={activating === pack.pack_id}
                />
              </Grid>
            ))}
          </Grid>
        </TabPanel>
      )}

      {packs.length === 0 && !loading && (
        <Box textAlign="center" py={8}>
          <Typography variant="h6" color="textSecondary" gutterBottom>
            No packs available
          </Typography>
          <Typography variant="body2" color="textSecondary" mb={3}>
            Upload a jurisdiction pack to get started
          </Typography>
          <Button
            variant="contained"
            startIcon={<UploadIcon />}
            onClick={() => setUploaderOpen(true)}
          >
            Upload Your First Pack
          </Button>
        </Box>
      )}

      <PackDetailsModal
        pack={selectedPack}
        open={detailsOpen}
        onClose={() => setDetailsOpen(false)}
      />

      <PackUploader
        open={uploaderOpen}
        onClose={() => setUploaderOpen(false)}
        onSuccess={handleUploadSuccess}
      />
    </Box>
  );
};

export default PackManagement;
