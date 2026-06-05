/**
 * Request Details Page (RFC-007)
 * Detailed view of a single FOI request for public users
 */
import React, { useEffect, useState } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Chip,
  List,
  ListItem,
  ListItemText,
  CircularProgress,
  Alert,
  Divider,
  Button,
  Grid,
  Paper
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DescriptionIcon from '@mui/icons-material/Description';
import TimelineIcon from '@mui/icons-material/Timeline';
import DownloadIcon from '@mui/icons-material/Download';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';

interface ReleasePackage {
  id: string;
  filename: string;
  size_bytes: number;
  document_count: number;
  download_count: number;
  max_downloads?: number;
  expires_at?: string;
  access_token: string;
  released_at: string;
}

interface RequestDetails {
  id: string;
  tracking_number: string;
  title: string;
  description: string;
  status: string;
  category: string;
  created_at: string;
  updated_at: string;
  due_date: string | null;
  requester: {
    name: string;
    email: string;
    phone?: string;
    organization?: string;
  };
  timeline: Array<{
    event: string;
    timestamp: string;
    details?: string;
  }>;
  documents: Array<{
    id: string;
    filename: string;
    file_type: string;
    file_size: number;
    uploaded_at: string;
    status: string;
  }>;
  document_count: number;
  release_packages?: ReleasePackage[];
  release_status?: string;
}

export const RequestDetailsPage: React.FC = () => {
  const { requestId } = useParams() as { requestId: string };
  const [request, setRequest] = useState<RequestDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    fetchRequestDetails();
  }, [requestId]);

  const fetchRequestDetails = async () => {
    try {
      const token = localStorage.getItem('token');
      if (!token) {
        navigate('/public/login');
        return;
      }

      const response = await axios.get(`/api/v1/cases/public/${requestId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      setRequest(response.data);
    } catch (err: any) {
      if (err.response?.status === 401) {
        localStorage.removeItem('token');
        navigate('/public/login');
      } else if (err.response?.status === 404) {
        setError('Request not found or you do not have access to it.');
      } else {
        setError('Failed to load request details. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string): 'info' | 'warning' | 'success' | 'default' => {
    switch (status) {
      case 'open': return 'info';
      case 'in_progress': return 'warning';
      case 'completed': return 'success';
      case 'closed': return 'default';
      default: return 'default';
    }
  };

  const formatDate = (dateString: string | null | undefined) => {
    if (!dateString) return '—';
    const d = new Date(dateString);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const getEventLabel = (eventName: string): string => {
    const eventLabels: { [key: string]: string } = {
      'case_created': 'Request Submitted',
      'case_assigned': 'Assigned to Analyst',
      'status_changed': 'Status Updated',
      'document_uploaded': 'Document Added',
      'comment_added': 'Comment Added',
      'case_closed': 'Request Closed',
      'case_completed': 'Request Completed',
      'extension_requested': 'Extension Requested',
      'extension_granted': 'Extension Granted'
    };
    return eventLabels[eventName] || eventName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  const formatEventDetails = (details: any): string | null => {
    if (!details) return null;
    if (typeof details === 'string') return details;
    
    // Format common detail patterns
    if (details.source === 'public_portal') return null; // Don't show internal source info
    if (details.status) return `Status: ${details.status}`;
    if (details.assigned_to) return `Assigned to: ${details.assigned_to}`;
    if (details.reason) return details.reason;
    
    // For other objects, show key-value pairs
    return Object.entries(details)
      .filter(([key]) => !['source'].includes(key)) // Filter out internal fields
      .map(([key, value]) => `${key}: ${value}`)
      .join(', ') || null;
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error || !request) {
    return (
      <Box sx={{ maxWidth: 800, mx: 'auto', p: 3 }}>
        <Alert severity="error" sx={{ mb: 2 }}>
          {error || 'Request not found'}
        </Alert>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/public/dashboard')}
        >
          Back to Dashboard
        </Button>
      </Box>
    );
  }

  return (
    <Box sx={{ maxWidth: 1200, mx: 'auto', p: 3 }}>
      {/* Header */}
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate('/public/dashboard')}
        sx={{ mb: 2 }}
      >
        Back to Dashboard
      </Button>

      <Box sx={{ mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
          <Typography variant="h4">{request.title}</Typography>
          <Chip
            label={request.status.replace('_', ' ')}
            color={getStatusColor(request.status)}
          />
        </Box>
        <Typography variant="body2" color="text.secondary">
          Tracking Number: {request.tracking_number}
        </Typography>
      </Box>

      <Grid container spacing={3}>
        {/* Main Content */}
        <Grid item xs={12} md={8}>
          {/* Request Details */}
          <Card sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Request Details
              </Typography>
              <Divider sx={{ mb: 2 }} />
              
              <Typography variant="body1" paragraph>
                {request.description}
              </Typography>

              <Grid container spacing={2}>
                <Grid item xs={6}>
                  <Typography variant="caption" color="text.secondary">
                    Category
                  </Typography>
                  <Typography variant="body2">
                    {request.category || 'Not specified'}
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="caption" color="text.secondary">
                    Submitted
                  </Typography>
                  <Typography variant="body2">
                    {formatDate(request.created_at)}
                  </Typography>
                </Grid>
                {request.due_date && (
                  <Grid item xs={6}>
                    <Typography variant="caption" color="text.secondary">
                      Due Date
                    </Typography>
                    <Typography variant="body2">
                      {formatDate(request.due_date)}
                    </Typography>
                  </Grid>
                )}
              </Grid>
            </CardContent>
          </Card>

          {/* Downloads Section - Only show if there are released packages */}
          {request.release_packages && request.release_packages.length > 0 && (
            <Card sx={{ mb: 3 }}>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                  <DownloadIcon color="success" />
                  <Typography variant="h6">
                    Available Downloads
                  </Typography>
                </Box>
                <Divider sx={{ mb: 2 }} />

                {request.release_packages.map((pkg) => (
                  <Paper key={pkg.id} sx={{ p: 2, mb: 2, bgcolor: 'success.50' }} variant="outlined">
                    <Typography variant="subtitle1" sx={{ fontWeight: 500 }}>
                      {pkg.filename}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      {pkg.document_count} documents • {formatFileSize(pkg.size_bytes)}
                    </Typography>
                    {pkg.expires_at && (
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                        Available until {formatDate(pkg.expires_at)}
                      </Typography>
                    )}
                    {pkg.max_downloads && (
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
                        Downloads: {pkg.download_count} / {pkg.max_downloads}
                      </Typography>
                    )}
                    <Button
                      variant="contained"
                      color="success"
                      startIcon={<DownloadIcon />}
                      onClick={() => window.open(`/api/v1/cases/public/release/${pkg.access_token}`, '_blank')}
                      fullWidth
                    >
                      Download Release Package
                    </Button>
                  </Paper>
                ))}
              </CardContent>
            </Card>
          )}

        </Grid>

        {/* Sidebar */}
        <Grid item xs={12} md={4}>
          {/* Timeline */}
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <TimelineIcon />
                <Typography variant="h6">
                  Timeline
                </Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />

              {request.timeline.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  No timeline events yet
                </Typography>
              ) : (
                <List>
                  {request.timeline.map((event, index) => (
                    <div key={index}>
                      {index > 0 && <Divider sx={{ my: 1 }} />}
                      <ListItem sx={{ px: 0 }}>
                        <ListItemText
                          primary={
                            <Typography variant="body2" sx={{ fontWeight: 500 }}>
                              {getEventLabel(event.event)}
                            </Typography>
                          }
                          secondary={
                            <>
                              <Typography variant="caption" color="text.secondary" display="block">
                                {formatDate(event.timestamp)}
                              </Typography>
                              {(() => {
                                const formattedDetails = formatEventDetails(event.details);
                                return formattedDetails && (
                                  <Typography variant="caption" color="text.secondary">
                                    {formattedDetails}
                                  </Typography>
                                );
                              })()}
                            </>
                          }
                        />
                      </ListItem>
                    </div>
                  ))}
                </List>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};
