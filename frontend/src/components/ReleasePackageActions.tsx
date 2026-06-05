import React, { useState, useEffect, useCallback } from 'react';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import CircularProgress from '@mui/material/CircularProgress';
import Checkbox from '@mui/material/Checkbox';
import FormControlLabel from '@mui/material/FormControlLabel';
import Paper from '@mui/material/Paper';
import TextField from '@mui/material/TextField';
import Divider from '@mui/material/Divider';
import Chip from '@mui/material/Chip';
import Snackbar from '@mui/material/Snackbar';
import LinearProgress from '@mui/material/LinearProgress';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import BuildIcon from '@mui/icons-material/Build';
import RefreshIcon from '@mui/icons-material/Refresh';
import DownloadIcon from '@mui/icons-material/Download';
import PublishIcon from '@mui/icons-material/Publish';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CloseIcon from '@mui/icons-material/Close';
import DescriptionIcon from '@mui/icons-material/Description';
import api from '../api/client';

// Types matching backend models
interface IncludedDocument {
  document_id: string;
  filename: string;
  original_filename?: string;
  redaction_count: number;
  exemptions: string[];
}

interface ReleasePackageResponse {
  id: string;
  case_id: string;
  status: 'generating' | 'draft' | 'released' | 'expired' | 'revoked';
  filename: string;
  size_bytes: number;
  document_count: number;
  total_redactions: number;
  included_documents: IncludedDocument[];
  generation_progress: number;
  generation_message?: string;
  download_url?: string;
  public_url?: string;
  expires_at?: string;
  download_count: number;
  max_downloads?: number;
  created_at: string;
  created_by_name: string;
  released_at?: string;
  released_by_name?: string;
}

interface CurrentPackageState {
  current_draft: ReleasePackageResponse | null;
  current_release: ReleasePackageResponse | null;
}

interface Document {
  id: string;
  filename: string;
  status: string;
  redactions?: any[];
}

interface ReleasePackageActionsProps {
  caseId: string;
  caseNumber: string;
  documents: Document[];
  disabled?: boolean;
  onPackageReleased?: () => void;
}

const ReleasePackageActions: React.FC<ReleasePackageActionsProps> = ({
  caseId,
  caseNumber,
  documents,
  disabled = false,
  onPackageReleased,
}) => {
  // State
  const [packageState, setPackageState] = useState<CurrentPackageState>({
    current_draft: null,
    current_release: null,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Dialog states
  const [generateDialogOpen, setGenerateDialogOpen] = useState(false);
  const [releaseDialogOpen, setReleaseDialogOpen] = useState(false);
  
  // Generate dialog options
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [includeCoverLetter, setIncludeCoverLetter] = useState(true);
  
  // Release dialog options
  const [expiresInDays, setExpiresInDays] = useState(30);
  const [maxDownloads, setMaxDownloads] = useState(10);
  const [notifyRequester, setNotifyRequester] = useState(true);
  const [customMessage, setCustomMessage] = useState('');
  
  // Toast state
  const [toastOpen, setToastOpen] = useState(false);
  const [toastMessage, setToastMessage] = useState('');
  const [toastSeverity, setToastSeverity] = useState<'success' | 'error' | 'info'>('success');

  // Filter to approved/released documents
  const approvedDocuments = documents.filter(
    (doc) => doc.status === 'approved' || doc.status === 'released'
  );

  // Fetch current package state
  const fetchPackageState = useCallback(async () => {
    try {
      const response = await api.get(`/cases/${caseId}/release-packages`);
      setPackageState(response.data);
    } catch (err) {
      console.error('Error fetching package state:', err);
    }
  }, [caseId]);

  // Initial fetch
  useEffect(() => {
    fetchPackageState();
  }, [fetchPackageState]);

  // Poll for generation progress
  useEffect(() => {
    if (packageState.current_draft?.status === 'generating') {
      const interval = setInterval(async () => {
        await fetchPackageState();
      }, 2000);
      
      return () => clearInterval(interval);
    }
  }, [packageState.current_draft?.status, fetchPackageState]);

  // Show toast when generation completes
  useEffect(() => {
    if (packageState.current_draft?.status === 'draft') {
      // Check if we just transitioned from generating
      showToast('Release package ready for review', 'success');
    }
  }, [packageState.current_draft?.status]);

  const showToast = (message: string, severity: 'success' | 'error' | 'info') => {
    setToastMessage(message);
    setToastSeverity(severity);
    setToastOpen(true);
  };

  // Initialize selected docs when dialog opens
  const handleOpenGenerateDialog = () => {
    setSelectedDocIds(approvedDocuments.map((d) => d.id));
    setIncludeCoverLetter(true);
    setError(null);
    setGenerateDialogOpen(true);
  };

  const handleOpenReleaseDialog = () => {
    setExpiresInDays(30);
    setMaxDownloads(10);
    setNotifyRequester(true);
    setCustomMessage('');
    setError(null);
    setReleaseDialogOpen(true);
  };

  // Step 1: Generate package
  const handleGenerate = async () => {
    setLoading(true);
    setError(null);

    try {
      await api.post(`/cases/${caseId}/release-package/generate`, {
        document_ids: selectedDocIds.length === approvedDocuments.length ? null : selectedDocIds,
        include_cover_letter: includeCoverLetter,
      });

      setGenerateDialogOpen(false);
      showToast('Package generation started...', 'info');
      
      // Start polling
      await fetchPackageState();
    } catch (err: any) {
      console.error('Error starting generation:', err);
      setError(err.response?.data?.detail || 'Failed to start package generation');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Download draft
  const handleDownloadDraft = async () => {
    if (!packageState.current_draft) return;

    try {
      const response = await api.get(
        `/cases/${caseId}/release-package/${packageState.current_draft.id}/download`,
        { responseType: 'blob' }
      );

      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${caseNumber}-Release-DRAFT.zip`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      console.error('Error downloading draft:', err);
      showToast(err.response?.data?.detail || 'Failed to download package', 'error');
    }
  };

  // Step 3: Release package
  const handleRelease = async () => {
    if (!packageState.current_draft) return;

    setLoading(true);
    setError(null);

    try {
      await api.post(
        `/cases/${caseId}/release-package/${packageState.current_draft.id}/release`,
        {
          expires_in_days: expiresInDays,
          max_downloads: maxDownloads,
          notify_requester: notifyRequester,
          custom_message: customMessage || null,
        }
      );

      setReleaseDialogOpen(false);
      showToast(
        notifyRequester
          ? 'Package released and requester notified'
          : 'Package released to public portal',
        'success'
      );
      
      await fetchPackageState();
      onPackageReleased?.();
    } catch (err: any) {
      console.error('Error releasing package:', err);
      setError(err.response?.data?.detail || 'Failed to release package');
    } finally {
      setLoading(false);
    }
  };

  const toggleDocSelection = (docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    );
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  // Determine current state
  const isGenerating = packageState.current_draft?.status === 'generating';
  const hasDraft = packageState.current_draft?.status === 'draft';
  const hasRelease = packageState.current_release !== null;
  const hasNoPackage = !packageState.current_draft && !packageState.current_release;

  return (
    <>
      {/* Action Buttons */}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {/* Generate / Regenerate Button */}
        {hasNoPackage && (
          <Button
            variant="outlined"
            startIcon={<BuildIcon />}
            onClick={handleOpenGenerateDialog}
            disabled={disabled || approvedDocuments.length === 0}
            fullWidth
            sx={{
              borderColor: '#d0d0d0',
              color: '#333',
              bgcolor: 'white',
              fontWeight: 500,
              '&:hover': { borderColor: '#999', bgcolor: '#f5f5f5' },
            }}
          >
            GENERATE PACKAGE
          </Button>
        )}

        {isGenerating && (
          <Box sx={{ width: '100%' }}>
            <Button
              variant="outlined"
              disabled
              startIcon={<CircularProgress size={16} />}
              fullWidth
              sx={{ mb: 1 }}
            >
              GENERATING...
            </Button>
            <LinearProgress
              variant="determinate"
              value={packageState.current_draft?.generation_progress || 0}
            />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
              {packageState.current_draft?.generation_message || 'Processing...'}
            </Typography>
          </Box>
        )}

        {(hasDraft || hasRelease) && !isGenerating && (
          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={handleOpenGenerateDialog}
            disabled={disabled || approvedDocuments.length === 0}
            fullWidth
            sx={{
              borderColor: '#d0d0d0',
              color: '#333',
              bgcolor: 'white',
              fontWeight: 500,
              '&:hover': { borderColor: '#999', bgcolor: '#f5f5f5' },
            }}
          >
            REGENERATE PACKAGE
          </Button>
        )}

        {/* Download Button (draft or released) */}
        {(hasDraft || hasRelease) && !isGenerating && (
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={handleDownloadDraft}
            disabled={disabled}
            fullWidth
            sx={{
              borderColor: '#d0d0d0',
              color: '#333',
              bgcolor: 'white',
              fontWeight: 500,
              '&:hover': { borderColor: '#999', bgcolor: '#f5f5f5' },
            }}
          >
            DOWNLOAD PACKAGE
          </Button>
        )}

        {/* Release Button (draft only) */}
        {hasDraft && (
          <Button
            variant="contained"
            color="success"
            startIcon={<PublishIcon />}
            onClick={handleOpenReleaseDialog}
            disabled={disabled}
            fullWidth
          >
            RELEASE PACKAGE
          </Button>
        )}

        {/* Released Status */}
        {hasRelease && (
          <Chip
            icon={<CheckCircleIcon />}
            label={`Released ${formatDate(packageState.current_release!.released_at!)}`}
            color="success"
            variant="outlined"
            sx={{ justifyContent: 'flex-start' }}
          />
        )}

        {/* Release Stats */}
        {hasRelease && (
          <Typography variant="caption" color="text.secondary">
            Downloads: {packageState.current_release!.download_count}
            {packageState.current_release!.max_downloads && 
              ` / ${packageState.current_release!.max_downloads}`}
            {packageState.current_release!.expires_at && 
              ` • Expires: ${formatDate(packageState.current_release!.expires_at)}`}
          </Typography>
        )}
      </Box>

      {/* Generate Dialog */}
      <Dialog open={generateDialogOpen} onClose={() => setGenerateDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {hasDraft || hasRelease ? 'Regenerate Release Package' : 'Generate Release Package'}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2 }}>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              Select documents to include in the release package:
            </Typography>

            <Paper variant="outlined" sx={{ maxHeight: 200, overflow: 'auto', mt: 1, mb: 2 }}>
              <List dense>
                {approvedDocuments.map((doc) => (
                  <ListItem
                    key={doc.id}
                    button
                    onClick={() => toggleDocSelection(doc.id)}
                  >
                    <ListItemIcon>
                      <Checkbox
                        edge="start"
                        checked={selectedDocIds.includes(doc.id)}
                        tabIndex={-1}
                        disableRipple
                      />
                    </ListItemIcon>
                    <ListItemIcon>
                      <DescriptionIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText
                      primary={doc.filename}
                      secondary={`${doc.redactions?.length || 0} redactions`}
                    />
                  </ListItem>
                ))}
              </List>
            </Paper>

            {approvedDocuments.length === 0 && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                No approved or released documents available.
              </Alert>
            )}

            <Divider sx={{ my: 2 }} />

            <FormControlLabel
              control={
                <Checkbox
                  checked={includeCoverLetter}
                  onChange={(e) => setIncludeCoverLetter(e.target.checked)}
                />
              }
              label="Include cover letter"
            />

            <Alert severity="info" sx={{ mt: 2 }}>
              Package will be generated in the background. You'll receive a notification when it's ready for review.
            </Alert>

            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {error}
              </Alert>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGenerateDialogOpen(false)} disabled={loading}>
            Cancel
          </Button>
          <Button
            onClick={handleGenerate}
            variant="contained"
            disabled={loading || selectedDocIds.length === 0}
            startIcon={loading ? <CircularProgress size={20} /> : <BuildIcon />}
          >
            {loading ? 'Starting...' : 'Start Generation'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Release Dialog */}
      <Dialog open={releaseDialogOpen} onClose={() => setReleaseDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Release Package to Requester</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2 }}>
            {/* Package Summary */}
            {packageState.current_draft && (
              <Paper sx={{ p: 2, mb: 2, bgcolor: 'grey.50' }}>
                <Typography variant="subtitle2" gutterBottom>
                  Package Summary
                </Typography>
                <Typography variant="body2">
                  {packageState.current_draft.document_count} documents •{' '}
                  {formatBytes(packageState.current_draft.size_bytes)}
                </Typography>
                <Typography variant="body2">
                  {packageState.current_draft.total_redactions} total redactions applied
                </Typography>
              </Paper>
            )}

            {/* Expiration Settings */}
            <TextField
              label="Link expires in (days)"
              type="number"
              value={expiresInDays}
              onChange={(e) => setExpiresInDays(parseInt(e.target.value) || 30)}
              fullWidth
              sx={{ mb: 2 }}
              inputProps={{ min: 7, max: 90 }}
              helperText={`Expires: ${formatDate(
                new Date(Date.now() + expiresInDays * 24 * 60 * 60 * 1000).toISOString()
              )}`}
            />

            <TextField
              label="Maximum downloads"
              type="number"
              value={maxDownloads}
              onChange={(e) => setMaxDownloads(parseInt(e.target.value) || 10)}
              fullWidth
              sx={{ mb: 2 }}
              inputProps={{ min: 1, max: 100 }}
            />

            <Divider sx={{ my: 2 }} />

            {/* Notification Settings */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={notifyRequester}
                  onChange={(e) => setNotifyRequester(e.target.checked)}
                />
              }
              label="Send email notification to requester"
            />

            {notifyRequester && (
              <TextField
                label="Custom message (optional)"
                multiline
                rows={3}
                value={customMessage}
                onChange={(e) => setCustomMessage(e.target.value)}
                fullWidth
                sx={{ mt: 1 }}
                placeholder="Add a personal message to include in the notification email..."
              />
            )}

            <Alert severity="warning" sx={{ mt: 2 }}>
              Once released, the requester will be able to download this package. You can still
              regenerate a new version if needed.
            </Alert>

            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {error}
              </Alert>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setReleaseDialogOpen(false)} disabled={loading}>
            Cancel
          </Button>
          <Button
            onClick={handleRelease}
            variant="contained"
            color="success"
            disabled={loading}
            startIcon={loading ? <CircularProgress size={20} /> : <PublishIcon />}
          >
            {loading ? 'Releasing...' : 'Release to Requester'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Toast Notification */}
      <Snackbar
        open={toastOpen}
        autoHideDuration={6000}
        onClose={() => setToastOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          onClose={() => setToastOpen(false)}
          severity={toastSeverity}
          sx={{ width: '100%' }}
          action={
            toastSeverity === 'success' && hasDraft ? (
              <Button color="inherit" size="small" onClick={handleDownloadDraft}>
                Download
              </Button>
            ) : undefined
          }
        >
          {toastMessage}
        </Alert>
      </Snackbar>
    </>
  );
};

export default ReleasePackageActions;
