/**
 * Records Confirmation Component.
 *
 * Allows staff to confirm that all responsive records have been uploaded.
 * This signals to analysts that the case is ready for review.
 */
import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import UndoIcon from '@mui/icons-material/Undo';
import FolderIcon from '@mui/icons-material/Folder';
import { recordsConfirmationApi, RecordsConfirmation as RecordsConfirmationType } from '../../api/workflowApi';

interface RecordsConfirmationProps {
  caseId: string;
  onConfirmationChange?: () => void;
}

const RecordsConfirmation: React.FC<RecordsConfirmationProps> = ({ caseId, onConfirmationChange }) => {
  const [confirmation, setConfirmation] = useState<RecordsConfirmationType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchConfirmation();
  }, [caseId]);

  const fetchConfirmation = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await recordsConfirmationApi.get(caseId);
      setConfirmation(data);
    } catch (err: any) {
      if (err.response?.status !== 404) {
        setError('Failed to load confirmation status');
      }
      setConfirmation({ confirmed: false });
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    try {
      setSubmitting(true);
      await recordsConfirmationApi.confirm(caseId, notes || undefined);
      setShowConfirmDialog(false);
      setNotes('');
      await fetchConfirmation();
      onConfirmationChange?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to confirm records');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async () => {
    if (!window.confirm('Are you sure you want to revoke the records confirmation?')) return;

    try {
      setSubmitting(true);
      await recordsConfirmationApi.revoke(caseId);
      await fetchConfirmation();
      onConfirmationChange?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to revoke confirmation');
    } finally {
      setSubmitting(false);
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
      <Card variant="outlined" sx={{ mb: 2 }}>
        <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1.5, '&:last-child': { pb: 1.5 } }}>
          <CircularProgress size={16} />
          <Typography variant="body2" color="text.secondary">Loading...</Typography>
        </CardContent>
      </Card>
    );
  }

  const isConfirmed = confirmation?.confirmed;

  return (
    <Card variant="outlined" sx={{ mb: 2 }}>
      <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
        {error && (
          <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={1}>
          <Box display="flex" alignItems="center" gap={1}>
            <FolderIcon color={isConfirmed ? 'success' : 'action'} />
            <Typography variant="subtitle2">
              Records Collection
            </Typography>
            <Chip
              size="small"
              icon={isConfirmed ? <CheckCircleIcon /> : <HourglassEmptyIcon />}
              label={isConfirmed ? 'ALL RECORDS UPLOADED' : 'COLLECTION IN PROGRESS'}
              color={isConfirmed ? 'success' : 'default'}
              sx={{ fontWeight: 600 }}
            />
          </Box>

          <Box>
            {isConfirmed ? (
              <Button
                size="small"
                variant="outlined"
                startIcon={<UndoIcon />}
                onClick={handleRevoke}
                disabled={submitting}
              >
                Revoke
              </Button>
            ) : (
              <Button
                size="small"
                variant="contained"
                color="success"
                startIcon={<CheckCircleIcon />}
                onClick={() => setShowConfirmDialog(true)}
                disabled={submitting}
              >
                Confirm All Uploaded
              </Button>
            )}
          </Box>
        </Box>

        {isConfirmed && confirmation?.confirmed_at && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            Confirmed by {confirmation.confirmed_by_name || 'Unknown'} on {formatDate(confirmation.confirmed_at)}
            {confirmation.notes && <> — {confirmation.notes}</>}
          </Typography>
        )}
      </CardContent>

      {/* Confirm Dialog */}
      <Dialog open={showConfirmDialog} onClose={() => setShowConfirmDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Confirm All Records Uploaded</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            By confirming, you are indicating that all responsive records have been collected and uploaded.
            This will notify assigned analysts that the case is ready for review.
          </Typography>
          <TextField
            fullWidth
            label="Notes (optional)"
            multiline
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Any additional context about the records collection..."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowConfirmDialog(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="success"
            onClick={handleConfirm}
            disabled={submitting}
          >
            {submitting ? <CircularProgress size={20} /> : 'Confirm'}
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
};

export default RecordsConfirmation;
