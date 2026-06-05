/**
 * Contributor Portal.
 *
 * Public page for contributors to upload documents for a case.
 * Accessed via token-based URL (no login required).
 */
import React, { useState, useEffect, useCallback } from 'react';
import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Alert from '@mui/material/Alert';
import CircularProgress from '@mui/material/CircularProgress';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Chip from '@mui/material/Chip';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import DescriptionIcon from '@mui/icons-material/Description';
import WarningIcon from '@mui/icons-material/Warning';
import { useParams, useLocation } from 'react-router-dom';
import { publicApi } from '../../api/client';

// Phase 4 Batch 4.4 (audit F2): use the shared `publicApi` from
// `src/api/client.ts` instead of a local axios.create + duplicated
// getBaseURL() helper.

interface ContributorInfo {
  contributor_id: string;
  contributor_name: string;
  case_tracking_number: string;
  case_title: string;
  org_name: string;
  documents_uploaded: number;
  uploaded_documents: Array<{
    id: string;
    filename: string;
    uploaded_at: string;
  }>;
  is_expired: boolean;
  expires_at: string;
  records_confirmed: boolean;
}

const ContributorPortal: React.FC = () => {
  const { contributorId } = useParams();
  const location = useLocation();
  const searchParams = new URLSearchParams(location.search);
  const token = searchParams.get('token');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<ContributorInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchContributorInfo = useCallback(async () => {
    if (!contributorId || !token) {
      setError('Invalid or missing access token');
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      const response = await publicApi.get(`/contribute/${contributorId}`, {
        params: { token }
      });
      setInfo(response.data);
      setError(null);
    } catch (err: any) {
      if (err.response?.status === 401 || err.response?.status === 403) {
        setError('This link has expired or is invalid. Please contact the FOI coordinator for a new link.');
      } else if (err.response?.status === 404) {
        setError('Contributor not found. Please check your link or contact the FOI coordinator.');
      } else {
        setError('Failed to load contributor information. Please try again later.');
      }
    } finally {
      setLoading(false);
    }
  }, [contributorId, token]);

  useEffect(() => {
    fetchContributorInfo();
  }, [fetchContributorInfo]);

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files || files.length === 0 || !contributorId || !token) return;

    setUploading(true);
    setError(null);
    setSuccess(null);

    try {
      for (let i = 0; i < files.length; i++) {
        const formData = new FormData();
        formData.append('file', files[i]);
        formData.append('token', token);

        await publicApi.post(`/contribute/${contributorId}/upload`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
      }

      setSuccess(`Successfully uploaded ${files.length} file(s)`);
      await fetchContributorInfo(); // Refresh the list
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to upload file(s)');
    } finally {
      setUploading(false);
      // Reset the file input
      event.target.value = '';
    }
  };

  const handleConfirmComplete = async () => {
    if (!contributorId || !token) return;

    setConfirming(true);
    setError(null);

    try {
      await publicApi.post(`/contribute/${contributorId}/confirm-complete`, null, {
        params: { token }
      });
      setSuccess('Thank you! Your records submission has been confirmed.');
      await fetchContributorInfo();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to confirm submission');
    } finally {
      setConfirming(false);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (loading) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: '#f5f5f5' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error && !info) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: '#f5f5f5' }}>
        <Container maxWidth="sm">
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <WarningIcon sx={{ fontSize: 64, color: 'error.main', mb: 2 }} />
            <Typography variant="h5" gutterBottom>Access Error</Typography>
            <Typography color="text.secondary">{error}</Typography>
          </Paper>
        </Container>
      </Box>
    );
  }

  if (!info) return null;

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: '#f5f5f5', py: 4 }}>
      <Container maxWidth="md">
        {/* Header */}
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h4" gutterBottom>
            Records Upload Portal
          </Typography>
          <Typography variant="body1" color="text.secondary" gutterBottom>
            Hello <strong>{info.contributor_name}</strong>, you have been asked to provide records for:
          </Typography>
          <Box sx={{ mt: 2, p: 2, bgcolor: '#e3f2fd', borderRadius: 1 }}>
            <Typography variant="subtitle1" fontWeight={600}>
              {info.case_title}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Reference: {info.case_tracking_number} • {info.org_name}
            </Typography>
          </Box>
          
          {info.is_expired && (
            <Alert severity="error" sx={{ mt: 2 }}>
              This link has expired. Please contact the FOI coordinator for a new link.
            </Alert>
          )}
          
          {info.records_confirmed && (
            <Alert severity="success" sx={{ mt: 2 }} icon={<CheckCircleIcon />}>
              You have confirmed that all records have been submitted.
            </Alert>
          )}
        </Paper>

        {/* Alerts */}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
        {success && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>
            {success}
          </Alert>
        )}

        {/* Upload Section */}
        {!info.is_expired && !info.records_confirmed && (
          <Paper sx={{ p: 3, mb: 3 }}>
            <Typography variant="h6" gutterBottom>
              Upload Documents
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Upload any documents that may be relevant to this FOI request. You can upload multiple files at once.
            </Typography>
            
            <Box sx={{ textAlign: 'center', py: 3, border: '2px dashed #ccc', borderRadius: 2, bgcolor: '#fafafa' }}>
              <input
                accept="*/*"
                style={{ display: 'none' }}
                id="file-upload"
                multiple
                type="file"
                onChange={handleFileUpload}
                disabled={uploading}
              />
              <label htmlFor="file-upload">
                <Button
                  variant="contained"
                  component="span"
                  startIcon={uploading ? <CircularProgress size={20} color="inherit" /> : <CloudUploadIcon />}
                  disabled={uploading}
                  size="large"
                >
                  {uploading ? 'Uploading...' : 'Select Files to Upload'}
                </Button>
              </label>
              <Typography variant="caption" display="block" sx={{ mt: 1, color: 'text.secondary' }}>
                Supported formats: PDF, Word, Excel, images, and more
              </Typography>
            </Box>
          </Paper>
        )}

        {/* Uploaded Documents */}
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" gutterBottom>
            Uploaded Documents ({info.documents_uploaded})
          </Typography>
          
          {info.uploaded_documents.length === 0 ? (
            <Typography color="text.secondary" sx={{ textAlign: 'center', py: 3 }}>
              No documents uploaded yet.
            </Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>File Name</TableCell>
                  <TableCell>Uploaded</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {info.uploaded_documents.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <DescriptionIcon fontSize="small" color="action" />
                        {doc.filename}
                      </Box>
                    </TableCell>
                    <TableCell>{formatDate(doc.uploaded_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Paper>

        {/* Confirm Complete */}
        {!info.is_expired && !info.records_confirmed && info.documents_uploaded > 0 && (
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Confirm Submission
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Once you have uploaded all relevant documents, click the button below to confirm your submission is complete.
            </Typography>
            <Button
              variant="contained"
              color="success"
              startIcon={confirming ? <CircularProgress size={20} color="inherit" /> : <CheckCircleIcon />}
              onClick={handleConfirmComplete}
              disabled={confirming}
              size="large"
            >
              {confirming ? 'Confirming...' : 'Confirm All Records Submitted'}
            </Button>
          </Paper>
        )}

        {/* Footer */}
        <Box sx={{ mt: 4, textAlign: 'center' }}>
          <Typography variant="caption" color="text.secondary">
            Link expires: {formatDate(info.expires_at)}
          </Typography>
        </Box>
      </Container>
    </Box>
  );
};

export default ContributorPortal;
