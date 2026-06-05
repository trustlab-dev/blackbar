/**
 * Clock Management Component.
 *
 * Displays statutory clock status and allows pause/resume operations.
 * Shows clock history with pause reasons and duration.
 */
import React, { useState, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  Alert,
  CircularProgress,
  Tooltip,
  IconButton
} from '@mui/material';
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import HistoryIcon from '@mui/icons-material/History';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

import { clockApi, ClockStatus, ClockEvent } from '../../api/workflowApi';

const PauseIcon = PauseCircleOutlineIcon;
const PlayIcon = PlayCircleOutlineIcon;
const ClockIcon = AccessTimeIcon;
const WarningIcon = WarningAmberIcon;
const InfoIcon = InfoOutlinedIcon;

interface ClockManagementProps {
  caseId: string;
  dueDate?: string;
  onClockChange?: () => void;
}

const PAUSE_REASONS = [
  { value: 'fee_pending', label: 'Fee Payment Pending' },
  { value: 'scope_narrowing', label: 'Scope Narrowing Discussion' },
  { value: 'third_party_consultation', label: 'Third Party Consultation' },
  { value: 'privacy_commission_review', label: 'Privacy Commission Review' },
  { value: 'applicant_request', label: 'Applicant Requested Extension' },
  { value: 'manual', label: 'Other (specify in notes)' }
];

const ClockManagement: React.FC<ClockManagementProps> = ({ caseId, dueDate, onClockChange }) => {
  const [clockStatus, setClockStatus] = useState<ClockStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showPauseDialog, setShowPauseDialog] = useState(false);
  const [showHistoryDialog, setShowHistoryDialog] = useState(false);
  const [pauseReason, setPauseReason] = useState('');
  const [pauseNotes, setPauseNotes] = useState('');
  const [resumeNotes, setResumeNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchClockStatus();
  }, [caseId]);

  const fetchClockStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const status = await clockApi.getHistory(caseId);
      setClockStatus(status);
    } catch (err: any) {
      if (err.response?.status !== 404) {
        setError('Failed to load clock status');
      }
      setClockStatus({
        case_id: caseId,
        status: 'running',
        total_paused_days: 0,
        events: []
      });
    } finally {
      setLoading(false);
    }
  };

  const handlePauseClock = async () => {
    if (!pauseReason) return;
    
    try {
      setSubmitting(true);
      await clockApi.pause(caseId, pauseReason, pauseNotes || undefined);
      await fetchClockStatus();
      setShowPauseDialog(false);
      setPauseReason('');
      setPauseNotes('');
      onClockChange?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to pause clock');
    } finally {
      setSubmitting(false);
    }
  };

  const handleResumeClock = async () => {
    try {
      setSubmitting(true);
      await clockApi.resume(caseId, resumeNotes || undefined);
      await fetchClockStatus();
      setResumeNotes('');
      onClockChange?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to resume clock');
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

  const getReasonLabel = (reason: string) => {
    const found = PAUSE_REASONS.find(r => r.value === reason);
    return found ? found.label : reason;
  };

  if (loading) {
    return (
      <Box display="flex" alignItems="center" gap={1} p={1}>
        <CircularProgress size={16} />
        <Typography variant="body2" color="text.secondary">Loading clock status...</Typography>
      </Box>
    );
  }

  const isPaused = clockStatus?.status === 'paused';
  const adjustedDueDate = clockStatus?.adjusted_due_date || dueDate;

  return (
    <Card variant="outlined" sx={{ mb: 2 }}>
      <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={1}>
          <Box display="flex" alignItems="center" gap={1}>
            <ClockIcon color={isPaused ? 'warning' : 'primary'} />
            <Typography variant="subtitle2">
              Statutory Clock
            </Typography>
            <Chip
              size="small"
              label={isPaused ? 'PAUSED' : 'RUNNING'}
              color={isPaused ? 'warning' : 'success'}
              sx={{ fontWeight: 600 }}
            />
            {clockStatus && clockStatus.total_paused_days > 0 && (
              <Chip
                size="small"
                variant="outlined"
                label={`${clockStatus.total_paused_days} days paused`}
                icon={<WarningIcon />}
              />
            )}
          </Box>

          <Box display="flex" alignItems="center" gap={1}>
            {isPaused ? (
              <Button
                size="small"
                variant="contained"
                color="success"
                startIcon={<PlayIcon />}
                onClick={handleResumeClock}
                disabled={submitting}
              >
                Resume Clock
              </Button>
            ) : (
              <Button
                size="small"
                variant="outlined"
                color="warning"
                startIcon={<PauseIcon />}
                onClick={() => setShowPauseDialog(true)}
                disabled={submitting}
              >
                Pause Clock
              </Button>
            )}
            <Tooltip title="View clock history">
              <IconButton size="small" onClick={() => setShowHistoryDialog(true)}>
                <HistoryIcon />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>

        {isPaused && clockStatus?.current_pause_reason && (
          <Alert severity="warning" sx={{ mt: 1 }} icon={<PauseIcon />}>
            <Typography variant="body2">
              <strong>Paused since:</strong> {clockStatus.current_pause_start ? formatDate(clockStatus.current_pause_start) : 'Unknown'}
              <br />
              <strong>Reason:</strong> {getReasonLabel(clockStatus.current_pause_reason)}
            </Typography>
          </Alert>
        )}

        {adjustedDueDate && clockStatus && clockStatus.total_paused_days > 0 && (
          <Box mt={1} display="flex" alignItems="center" gap={1}>
            <InfoIcon fontSize="small" color="info" />
            <Typography variant="body2" color="text.secondary">
              Adjusted due date: <strong>{formatDate(adjustedDueDate)}</strong>
              {clockStatus.original_due_date && (
                <> (originally {formatDate(clockStatus.original_due_date)})</>
              )}
            </Typography>
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mt: 1 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
      </CardContent>

      {/* Pause Dialog */}
      <Dialog open={showPauseDialog} onClose={() => setShowPauseDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Pause Statutory Clock</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Pausing the clock will stop the countdown toward the due date. The due date will be automatically adjusted when the clock is resumed.
          </Typography>
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>Reason for Pause</InputLabel>
            <Select
              value={pauseReason}
              onChange={(e) => setPauseReason(e.target.value)}
              label="Reason for Pause"
            >
              {PAUSE_REASONS.map(reason => (
                <MenuItem key={reason.value} value={reason.value}>
                  {reason.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            fullWidth
            multiline
            rows={3}
            label="Notes (optional)"
            value={pauseNotes}
            onChange={(e) => setPauseNotes(e.target.value)}
            placeholder="Add any additional context..."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowPauseDialog(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="warning"
            onClick={handlePauseClock}
            disabled={!pauseReason || submitting}
          >
            {submitting ? <CircularProgress size={20} /> : 'Pause Clock'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* History Dialog */}
      <Dialog open={showHistoryDialog} onClose={() => setShowHistoryDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Clock History</DialogTitle>
        <DialogContent>
          {clockStatus?.events && clockStatus.events.length > 0 ? (
            <Box sx={{ mt: 1 }}>
              {clockStatus.events.map((event, index) => (
                <Box
                  key={event.id}
                  sx={{
                    display: 'flex',
                    gap: 2,
                    py: 1.5,
                    borderBottom: index < clockStatus.events.length - 1 ? '1px solid' : 'none',
                    borderColor: 'divider'
                  }}
                >
                  <Box>
                    {event.event_type === 'pause' ? (
                      <PauseIcon color="warning" />
                    ) : event.event_type === 'resume' ? (
                      <PlayIcon color="success" />
                    ) : (
                      <ClockIcon color="primary" />
                    )}
                  </Box>
                  <Box flex={1}>
                    <Typography variant="body2" fontWeight={600}>
                      {event.event_type === 'pause' ? 'Clock Paused' :
                       event.event_type === 'resume' ? 'Clock Resumed' :
                       event.event_type === 'start' ? 'Clock Started' :
                       event.event_type === 'extend' ? 'Extension Applied' :
                       event.event_type}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {formatDate(event.event_date)} by {event.created_by_name || 'Unknown'}
                    </Typography>
                    {event.reason && (
                      <Typography variant="body2" sx={{ mt: 0.5 }}>
                        Reason: {getReasonLabel(event.reason)}
                      </Typography>
                    )}
                    {event.notes && (
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                        {event.notes}
                      </Typography>
                    )}
                  </Box>
                </Box>
              ))}
            </Box>
          ) : (
            <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
              No clock events recorded yet.
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowHistoryDialog(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
};

export default ClockManagement;
