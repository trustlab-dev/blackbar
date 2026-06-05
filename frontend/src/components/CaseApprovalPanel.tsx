import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Alert,
  Chip,
  Paper
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import api from '../api/client';

// API_BASE_URL not needed - api client already has baseURL configured

interface CaseApprovalPanelProps {
  caseId: string;
  userRole: string;  // Case team role
}

interface ApprovalStatus {
  approval_status: string | null;
  approved_by: string | null;
  approved_at: string | null;
  approval_notes: string | null;
}

const CaseApprovalPanel: React.FC<CaseApprovalPanelProps> = ({ caseId, userRole }) => {
  const [approvalStatus, setApprovalStatus] = useState<ApprovalStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Dialog state
  const [openApproveDialog, setOpenApproveDialog] = useState(false);
  const [openRejectDialog, setOpenRejectDialog] = useState(false);
  const [notes, setNotes] = useState('');
  const [reason, setReason] = useState('');

  const canApprove = ['approver', 'manager', 'analyst'].includes(userRole);

  useEffect(() => {
    fetchApprovalStatus();
  }, [caseId]);

  const fetchApprovalStatus = async () => {
    try {
      const response = await api.get(`/cases/${caseId}/approval-status`);
      setApprovalStatus(response.data);
    } catch (err: any) {
      // If 403, user doesn't have access - silently fail
      if (err.response?.status === 403) {
        return;
      }
      console.error('Error fetching approval status:', err);
    }
  };

  const handleApprove = async () => {
    try {
      setLoading(true);
      setError(null);
      
      await api.post(`/cases/${caseId}/approve`, {
        notes: notes || undefined
      });
      
      setSuccess('Case approved for release!');
      setOpenApproveDialog(false);
      setNotes('');
      await fetchApprovalStatus();
    } catch (err: any) {
      console.error('Error approving case:', err);
      setError(err.response?.data?.detail || 'Failed to approve case');
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    if (!reason) {
      setError('Reason is required');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      
      await api.post(`/cases/${caseId}/reject-approval`, {
        reason
      });
      
      setSuccess('Case approval rejected');
      setOpenRejectDialog(false);
      setReason('');
      await fetchApprovalStatus();
    } catch (err: any) {
      console.error('Error rejecting approval:', err);
      setError(err.response?.data?.detail || 'Failed to reject approval');
    } finally {
      setLoading(false);
    }
  };

  const getStatusBadge = () => {
    if (!approvalStatus?.approval_status) {
      return (
        <Chip
          label="Pending Approval"
          sx={{ bgcolor: '#fff3cd', color: '#856404', fontWeight: 600 }}
        />
      );
    }

    if (approvalStatus.approval_status === 'approved') {
      return (
        <Chip
          icon={<CheckCircleIcon />}
          label="Approved for Release"
          sx={{ bgcolor: '#d4edda', color: '#155724', fontWeight: 600 }}
        />
      );
    }

    if (approvalStatus.approval_status === 'rejected') {
      return (
        <Chip
          icon={<CancelIcon />}
          label="Approval Rejected"
          sx={{ bgcolor: '#f8d7da', color: '#721c24', fontWeight: 600 }}
        />
      );
    }

    return null;
  };

  return (
    <Paper sx={{ p: 2, border: '1px solid #e0e0e0', borderRadius: '4px', bgcolor: 'white' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" sx={{ fontWeight: 600, color: '#333' }}>
          Case Approval
        </Typography>
        {getStatusBadge()}
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}

      {approvalStatus?.approval_notes && (
        <Box sx={{ mb: 2, p: 2, bgcolor: '#f8f9fa', borderRadius: '4px' }}>
          <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
            Notes:
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {approvalStatus.approval_notes}
          </Typography>
          {approvalStatus.approved_at && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              {new Date(approvalStatus.approved_at).toLocaleString()}
            </Typography>
          )}
        </Box>
      )}

      {canApprove && !approvalStatus?.approval_status && (
        <Box sx={{ display: 'flex', gap: 2 }}>
          <Button
            variant="contained"
            startIcon={<CheckCircleIcon />}
            onClick={() => setOpenApproveDialog(true)}
            sx={{
              bgcolor: '#28a745',
              '&:hover': { bgcolor: '#218838' }
            }}
          >
            Approve Case
          </Button>
          <Button
            variant="outlined"
            startIcon={<CancelIcon />}
            onClick={() => setOpenRejectDialog(true)}
            sx={{
              borderColor: '#dc3545',
              color: '#dc3545',
              '&:hover': {
                borderColor: '#c82333',
                bgcolor: '#f8d7da'
              }
            }}
          >
            Reject
          </Button>
        </Box>
      )}

      {!canApprove && (
        <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
          Only Approvers and Managers can approve cases for release.
        </Typography>
      )}

      {/* Approve Dialog */}
      <Dialog open={openApproveDialog} onClose={() => setOpenApproveDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Approve Case for Release</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2 }}>
            <Alert severity="success" sx={{ mb: 2 }}>
              This will mark the case as approved and ready for release package generation.
            </Alert>
            <TextField
              fullWidth
              label="Notes (Optional)"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              multiline
              rows={3}
              helperText="Add any notes about the approval"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenApproveDialog(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleApprove}
            variant="contained"
            disabled={loading}
            sx={{
              bgcolor: '#28a745',
              '&:hover': { bgcolor: '#218838' }
            }}
          >
            {loading ? 'Approving...' : 'Approve Case'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Reject Dialog */}
      <Dialog open={openRejectDialog} onClose={() => setOpenRejectDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Reject Case Approval</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2 }}>
            <Alert severity="warning" sx={{ mb: 2 }}>
              This will mark the case as needing additional work before approval.
            </Alert>
            <TextField
              fullWidth
              label="Reason for Rejection"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              multiline
              rows={3}
              required
              helperText="Explain what needs to be addressed"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenRejectDialog(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleReject}
            variant="contained"
            disabled={loading || !reason}
            sx={{
              bgcolor: '#dc3545',
              '&:hover': { bgcolor: '#c82333' }
            }}
          >
            {loading ? 'Rejecting...' : 'Reject Approval'}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
};

export default CaseApprovalPanel;
