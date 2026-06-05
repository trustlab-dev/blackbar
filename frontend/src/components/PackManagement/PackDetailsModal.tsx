import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
  Tabs,
  Tab,
  Chip,
  List,
  ListItem,
  ListItemText,
  CircularProgress,
  Divider
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import api from '../../api/client';

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
}

interface PackDetails {
  pack_id: string;
  name: string;
  version: string;
  jurisdiction: any;
  terminology: any;
  timelines: any;
  categories: any[];
  statuses: any[];
  priorities: any[];
  templates: string[];
  features: any;
  branding: any;
}

interface PackDetailsModalProps {
  pack: Pack | null;
  open: boolean;
  onClose: () => void;
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
      {...other}
    >
      {value === index && <Box sx={{ py: 2 }}>{children}</Box>}
    </div>
  );
}

const PackDetailsModal: React.FC<PackDetailsModalProps> = ({ pack, open, onClose }) => {
  const [details, setDetails] = useState<PackDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [tabValue, setTabValue] = useState(0);

  useEffect(() => {
    if (open && pack) {
      fetchDetails();
    }
  }, [open, pack]);

  const fetchDetails = async () => {
    if (!pack) return;

    try {
      setLoading(true);
      const response = await api.get(`/packs/${pack.pack_id}/preview`);
      setDetails(response.data);
    } catch (err) {
      console.error('Error fetching pack details:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleTabChange = (event: React.SyntheticEvent, newValue: number) => {
    setTabValue(newValue);
  };

  if (!pack) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="h5">{pack.name}</Typography>
          <Button onClick={onClose} size="small">
            <CloseIcon />
          </Button>
        </Box>
        <Typography variant="body2" color="textSecondary">
          {pack.jurisdiction.region}, {pack.jurisdiction.country} • v{pack.version}
        </Typography>
      </DialogTitle>

      <DialogContent dividers>
        {loading ? (
          <Box display="flex" justifyContent="center" py={4}>
            <CircularProgress />
          </Box>
        ) : details ? (
          <>
            <Tabs value={tabValue} onChange={handleTabChange} sx={{ borderBottom: 1, borderColor: 'divider' }}>
              <Tab label="Overview" />
              <Tab label={`Categories (${details.categories?.length || 0})`} />
              <Tab label={`Statuses (${details.statuses?.length || 0})`} />
              <Tab label="Timelines" />
              <Tab label="Features" />
            </Tabs>

            <TabPanel value={tabValue} index={0}>
              <Typography variant="h6" gutterBottom>Jurisdiction</Typography>
              <Box mb={2}>
                <Typography variant="body2"><strong>Country:</strong> {details.jurisdiction?.country_name}</Typography>
                <Typography variant="body2"><strong>Region:</strong> {details.jurisdiction?.region_name}</Typography>
                <Typography variant="body2"><strong>Legislation:</strong> {details.jurisdiction?.legislation}</Typography>
                {details.jurisdiction?.legislation_url && (
                  <Typography variant="body2">
                    <strong>Reference:</strong>{' '}
                    <a href={details.jurisdiction.legislation_url} target="_blank" rel="noopener noreferrer">
                      View Legislation
                    </a>
                  </Typography>
                )}
              </Box>

              <Divider sx={{ my: 2 }} />

              <Typography variant="h6" gutterBottom>Terminology</Typography>
              <Box mb={2}>
                <Typography variant="body2"><strong>Request Type:</strong> {details.terminology?.request_type}</Typography>
                <Typography variant="body2"><strong>Requester:</strong> {details.terminology?.requester}</Typography>
                <Typography variant="body2"><strong>Tracking Prefix:</strong> {details.terminology?.tracking_number_prefix}</Typography>
              </Box>

              <Divider sx={{ my: 2 }} />

              <Typography variant="h6" gutterBottom>Capabilities</Typography>
              <Box display="flex" flexWrap="wrap" gap={1}>
                <Chip label={`${details.categories?.length || 0} Redaction Categories`} color="primary" />
                <Chip label={`${details.statuses?.length || 0} Statuses`} color="primary" />
                <Chip label={`${details.priorities?.length || 0} Priorities`} color="primary" />
                <Chip label={`${details.templates?.length || 0} Templates`} color="secondary" />
              </Box>
            </TabPanel>

            <TabPanel value={tabValue} index={1}>
              <List>
                {details.categories?.map((cat: any, index: number) => (
                  <ListItem key={index} divider>
                    <Box width="100%">
                      <Box display="flex" alignItems="center" gap={1} mb={1}>
                        <Chip 
                          label={cat.code} 
                          size="small" 
                          sx={{ bgcolor: cat.color, color: '#fff' }}
                        />
                        <Typography variant="subtitle1">{cat.name}</Typography>
                      </Box>
                      <Typography variant="body2" color="textSecondary">
                        {cat.description}
                      </Typography>
                      {cat.guidance && (
                        <Typography variant="caption" display="block" mt={0.5}>
                          <strong>Guidance:</strong> {cat.guidance}
                        </Typography>
                      )}
                    </Box>
                  </ListItem>
                ))}
              </List>
            </TabPanel>

            <TabPanel value={tabValue} index={2}>
              <List>
                {details.statuses?.map((status: any, index: number) => (
                  <ListItem key={index} divider>
                    <Box width="100%">
                      <Box display="flex" alignItems="center" gap={1} mb={1}>
                        <Chip 
                          label={status.label} 
                          size="small" 
                          sx={{ bgcolor: status.color, color: '#fff' }}
                        />
                      </Box>
                      {status.description && (
                        <Typography variant="body2" color="textSecondary">
                          {status.description}
                        </Typography>
                      )}
                    </Box>
                  </ListItem>
                ))}
              </List>
            </TabPanel>

            <TabPanel value={tabValue} index={3}>
              <Typography variant="body2" paragraph>
                <strong>Default Response Time:</strong> {details.timelines?.default_response_days} days
              </Typography>
              <Typography variant="body2" paragraph>
                <strong>Maximum Extension:</strong> {details.timelines?.extension_max_days} days
              </Typography>
              <Typography variant="body2" paragraph>
                <strong>Business Days:</strong> {details.timelines?.business_days ? 'Yes' : 'No'}
              </Typography>
              {details.timelines?.extension_reasons && (
                <>
                  <Typography variant="body2" gutterBottom><strong>Extension Reasons:</strong></Typography>
                  <List dense>
                    {details.timelines.extension_reasons.map((reason: string, index: number) => (
                      <ListItem key={index}>
                        <ListItemText primary={reason} />
                      </ListItem>
                    ))}
                  </List>
                </>
              )}
            </TabPanel>

            <TabPanel value={tabValue} index={4}>
              <Typography variant="h6" gutterBottom>Available Features</Typography>
              <Box display="flex" flexWrap="wrap" gap={1} mb={3}>
                {details.features && Object.entries(details.features).map(([key, value]) => (
                  <Chip 
                    key={key}
                    label={key.replace(/_/g, ' ').toUpperCase()}
                    color={value ? 'success' : 'default'}
                    variant={value ? 'filled' : 'outlined'}
                  />
                ))}
              </Box>

              <Typography variant="h6" gutterBottom>Templates</Typography>
              <List dense>
                {details.templates?.map((template: string, index: number) => (
                  <ListItem key={index}>
                    <ListItemText primary={template.replace(/_/g, ' ').toUpperCase()} />
                  </ListItem>
                ))}
              </List>
            </TabPanel>
          </>
        ) : (
          <Typography>No details available</Typography>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
};

export default PackDetailsModal;
