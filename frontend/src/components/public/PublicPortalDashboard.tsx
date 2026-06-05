/**
 * Public Portal Dashboard (RFC-007)
 * Main dashboard for authenticated public users to view their FOI requests
 */
import React, { useEffect, useState } from 'react';
import {
  Box,
  Typography,
  Button,
  Chip,
  CircularProgress,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper
} from '@mui/material';
import { useNavigate, Link } from 'react-router-dom';
import axios from 'axios';

interface FOIRequest {
  id: string;
  title: string;
  tracking_number: string;
  status: 'new' | 'in_progress' | 'review' | 'on_hold' | 'completed' | 'closed';
  created_at: string;
  updated_at: string;
  requester: {
    name: string;
    email: string;
  };
}

export const PublicPortalDashboard: React.FC = () => {
  const [requests, setRequests] = useState<FOIRequest[]>([]);
  const [selectedRequest, setSelectedRequest] = useState<FOIRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [orgConfig, setOrgConfig] = useState<{
    org_name: string;
    org_logo_url: string | null;
    primary_color: string;
  }>({
    org_name: 'Freedom of Information Office',
    org_logo_url: null,
    primary_color: '#0366d6'
  });
  const navigate = useNavigate();

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const token = localStorage.getItem('token');
      if (!token) {
        navigate('/public/login');
        return;
      }

      const headers = { Authorization: `Bearer ${token}` };

      // Fetch organization branding
      try {
        const configRes = await axios.get('/api/v1/admin/config/public');
        setOrgConfig({
          org_name: configRes.data.org_name || 'Freedom of Information Office',
          org_logo_url: configRes.data.org_logo_url,
          primary_color: configRes.data.primary_color || '#0366d6'
        });
      } catch (configErr) {
        console.error('Error fetching public config:', configErr);
      }

      const requestsRes = await axios.get('/api/v1/cases/public/my-requests', { headers });
      const requestsList = requestsRes.data.requests;
      setRequests(requestsList);
      
      // Auto-select first request for timeline
      if (requestsList.length > 0) {
        setSelectedRequest(requestsList[0]);
      }
    } catch (err: any) {
      if (err.response?.status === 401) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        localStorage.removeItem('user_type');
        navigate('/public/login');
      } else {
        setError('Failed to load your requests. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string): 'info' | 'warning' | 'success' | 'default' | 'primary' => {
    switch (status) {
      case 'new': return 'info';
      case 'in_progress': return 'primary';
      case 'review': return 'warning';
      case 'completed': return 'success';
      case 'on_hold': return 'default';
      case 'closed': return 'default';
      default: return 'default';
    }
  };

  const getStatusLabel = (status: string): string => {
    switch (status) {
      case 'new': return 'Submitted';
      case 'in_progress': return 'In Progress';
      case 'review': return 'Under Review';
      case 'completed': return 'Completed';
      case 'on_hold': return 'On Hold';
      case 'closed': return 'Closed';
      default: return status;
    }
  };

  const getTimelineSteps = (status: string) => {
    const steps = [
      { label: 'Submitted', status: 'new', completed: true },
      { label: 'Under Review', status: 'review', completed: false },
      { label: 'Processing', status: 'in_progress', completed: false },
      { label: 'Response Sent', status: 'completed', completed: false }
    ];

    let currentIndex = -1;
    if (status === 'new') currentIndex = 0;
    else if (status === 'review') currentIndex = 1;
    else if (status === 'in_progress') currentIndex = 2;
    else if (status === 'completed' || status === 'closed') currentIndex = 3;

    return steps.map((step, index) => ({
      ...step,
      completed: index <= currentIndex,
      active: index === currentIndex
    }));
  };

  const formatDate = (dateString: string | null | undefined) => {
    // Guard: new Date(null|undefined|'') returns Invalid Date or epoch
    // (Dec 31 1969 in PST). Render an em-dash for missing values so the
    // UI doesn't lie about when the request was submitted.
    if (!dateString) return '—';
    const d = new Date(dateString);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ bgcolor: 'var(--bg-tertiary)', minHeight: 'calc(100vh - 64px)' }}>
      <Box sx={{ maxWidth: 1200, mx: 'auto', p: 3 }}>
        {/* Org Branding Header */}
        {orgConfig.org_logo_url && (
          <Box sx={{ textAlign: 'center', mb: 3 }}>
            <img 
              src={orgConfig.org_logo_url} 
              alt={orgConfig.org_name} 
              style={{ maxHeight: '80px', maxWidth: '300px' }} 
            />
          </Box>
        )}
        <Typography 
          variant="h4" 
          sx={{ 
            mb: 3, 
            textAlign: 'center',
            color: orgConfig.primary_color 
          }}
        >
          {orgConfig.org_name}
        </Typography>

        {/* Submit New Request Button */}
        <Button
          variant="contained"
          fullWidth
          size="large"
          onClick={() => navigate('/public/request/new')}
          sx={{ 
            mb: 3, 
            py: 1.5, 
            fontSize: '1rem', 
            textTransform: 'uppercase',
            bgcolor: orgConfig.primary_color, 
            '&:hover': { bgcolor: orgConfig.primary_color, opacity: 0.9 } 
          }}
        >
          SUBMIT A NEW REQUEST
        </Button>

        {error && (
          <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        <Box sx={{ display: 'flex', gap: 3, flexDirection: { xs: 'column', md: 'row' } }}>
          {/* Left Column - My Requests Table */}
          <Box sx={{ flex: 1 }}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>
                My Requests
              </Typography>
              
              {requests.length === 0 ? (
                <Box sx={{ textAlign: 'center', py: 6 }}>
                  <Typography variant="body1" color="text.secondary" gutterBottom>
                    No FOI requests yet
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                    Submit your first Freedom of Information request to get started
                  </Typography>
                  <Button
                    variant="contained"
                    onClick={() => navigate('/public/request/new')}
                  >
                    Submit Your First Request
                  </Button>
                </Box>
              ) : (
                <TableContainer>
                  <Table>
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ fontWeight: 600 }}>Request ID</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Request</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Status</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>Date</TableCell>
                        <TableCell></TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {requests.map((request) => (
                        <TableRow 
                          key={request.id}
                          hover
                          onClick={() => setSelectedRequest(request)}
                          sx={{ cursor: 'pointer' }}
                        >
                          <TableCell>{request.tracking_number}</TableCell>
                          <TableCell>{request.title}</TableCell>
                          <TableCell>
                            <Chip
                              label={getStatusLabel(request.status)}
                              color={getStatusColor(request.status)}
                              size="small"
                            />
                          </TableCell>
                          <TableCell>{formatDate(request.created_at)}</TableCell>
                          <TableCell onClick={(e) => e.stopPropagation()}>
                            <Button
                              size="small"
                              onClick={() => navigate(`/public/request/${request.id}`)}
                            >
                              View Details
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Paper>
          </Box>

          {/* Right Column - Timeline and Help */}
          <Box sx={{ width: { xs: '100%', md: 400 } }}>
            {/* Request Status Timeline */}
            {selectedRequest && (
              <Paper sx={{ p: 3, mb: 3 }}>
                <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>
                  Request Status Timeline
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                  Request ID #{selectedRequest.tracking_number}: {selectedRequest.title}
                </Typography>
                
                {/* Timeline */}
                <Box sx={{ position: 'relative', pl: 4 }}>
                  {getTimelineSteps(selectedRequest.status).map((step, index) => (
                    <Box key={index} sx={{ position: 'relative', pb: index < 3 ? 4 : 0 }}>
                      {/* Timeline line */}
                      {index < 3 && (
                        <Box
                          sx={{
                            position: 'absolute',
                            left: -20,
                            top: 24,
                            width: 2,
                            height: 'calc(100% - 24px)',
                            bgcolor: step.completed ? 'primary.main' : 'var(--border-default)'
                          }}
                        />
                      )}
                      
                      {/* Timeline dot */}
                      <Box
                        sx={{
                          position: 'absolute',
                          left: -28,
                          top: 0,
                          width: 18,
                          height: 18,
                          borderRadius: '50%',
                          bgcolor: step.completed ? 'primary.main' : 'var(--border-default)',
                          border: '3px solid white',
                          boxShadow: 1
                        }}
                      />
                      
                      {/* Step label */}
                      <Typography
                        variant="body2"
                        sx={{
                          fontWeight: step.active ? 600 : 400,
                          color: step.completed ? 'text.primary' : 'text.secondary'
                        }}
                      >
                        {step.label}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              </Paper>
            )}

            {/* Help & Resources */}
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>
                Help & Resources
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <Box>
                  <Link to="#" style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: '4px', textDecoration: 'none' }}>
                    FAQs
                    <span style={{ fontSize: '0.875rem' }}>↗</span>
                  </Link>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                    Learn more to start about FAQs
                  </Typography>
                </Box>
                <Box>
                  <Link to="#" style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: '4px', textDecoration: 'none' }}>
                    How to file an FOI request
                    <span style={{ fontSize: '0.875rem' }}>↗</span>
                  </Link>
                </Box>
              </Box>
            </Paper>
          </Box>
        </Box>
      </Box>
    </Box>
  );
};
