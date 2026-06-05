/**
 * Transfer Case Component.
 *
 * Allows transferring a request to another public body.
 * Generates a secure link for the recipient to access request details.
 */
import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import SendIcon from '@mui/icons-material/Send';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import DownloadIcon from '@mui/icons-material/Download';
import { transferApi, CaseTransfer } from '../../api/workflowApi';
import api from '../../api/client';

interface Document {
  id: string;
  original_filename: string;
  status: string;
}

interface TransferCaseProps {
  caseId: string;
  caseTitle?: string;
}

const TransferCase: React.FC<TransferCaseProps> = ({ caseId, caseTitle }) => {
  const [transfers, setTransfers] = useState<CaseTransfer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showTransferDialog, setShowTransferDialog] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [newTransferUrl, setNewTransferUrl] = useState<string | null>(null);
  const [formData, setFormData] = useState({
    recipient_organization: '',
    recipient_email: '',
    recipient_name: '',
    transfer_reason: '',
    notes: '',
    include_documents: false
  });
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);

  useEffect(() => {
    fetchTransfers();
    fetchDocuments();
  }, [caseId]);

  const fetchDocuments = async () => {
    try {
      setLoadingDocs(true);
      const response = await api.get(`/cases/${caseId}/documents`);
      setDocuments(response.data || []);
    } catch (err) {
      console.error('Failed to load documents:', err);
      setDocuments([]);
    } finally {
      setLoadingDocs(false);
    }
  };

  const fetchTransfers = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await transferApi.list(caseId);
      setTransfers(data);
    } catch (err: any) {
      if (err.response?.status !== 404) {
        setError('Failed to load transfers');
      }
      setTransfers([]);
    } finally {
      setLoading(false);
    }
  };

  const handleTransfer = async () => {
    if (!formData.recipient_organization || !formData.recipient_email || !formData.transfer_reason) return;

    try {
      setSubmitting(true);
      const result = await transferApi.create(caseId, {
        recipient_organization: formData.recipient_organization,
        recipient_email: formData.recipient_email,
        recipient_name: formData.recipient_name || undefined,
        transfer_reason: formData.transfer_reason,
        notes: formData.notes || undefined,
        include_documents: formData.include_documents,
        included_document_ids: formData.include_documents ? selectedDocIds : undefined
      });
      setNewTransferUrl(window.location.origin + result.transfer_url);
      setSuccess(`Request transferred to ${formData.recipient_organization}`);
      setShowTransferDialog(false);
      setFormData({
        recipient_organization: '',
        recipient_email: '',
        recipient_name: '',
        transfer_reason: '',
        notes: '',
        include_documents: false
      });
      setSelectedDocIds([]);
      await fetchTransfers();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to transfer request');
    } finally {
      setSubmitting(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setSuccess('Link copied to clipboard');
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  };

  const getStatusChip = (status: string) => {
    switch (status) {
      case 'downloaded':
        return <Chip size="small" icon={<DownloadIcon />} label="Downloaded" color="success" />;
      case 'accessed':
        return <Chip size="small" icon={<CheckCircleIcon />} label="Accessed" color="primary" />;
      case 'pending':
        return <Chip size="small" icon={<HourglassEmptyIcon />} label="Pending" color="warning" />;
      case 'expired':
        return <Chip size="small" label="Expired" color="error" />;
      default:
        return <Chip size="small" label={status} />;
    }
  };

  if (loading) {
    return (
      <Card variant="outlined">
        <CardContent sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={24} />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card variant="outlined">
      <CardHeader
        avatar={<SwapHorizIcon />}
        title="Request Transfer"
        subheader="Transfer this request to another public body"
        action={
          <Button
            size="small"
            variant="contained"
            startIcon={<SendIcon />}
            onClick={() => setShowTransferDialog(true)}
          >
            Transfer
          </Button>
        }
        sx={{ pb: 0 }}
      />
      <CardContent>
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

        {transfers.length === 0 ? (
          <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
            No transfers yet. Click "Transfer" to send this request to another organization.
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Recipient</TableCell>
                <TableCell>Reason</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Date</TableCell>
                <TableCell>Expires</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {transfers.map((transfer) => (
                <TableRow key={transfer.id}>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>
                      {transfer.recipient_organization}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {transfer.recipient_email}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {transfer.transfer_reason}
                    </Typography>
                  </TableCell>
                  <TableCell>{getStatusChip(transfer.status)}</TableCell>
                  <TableCell>{formatDate(transfer.transferred_at)}</TableCell>
                  <TableCell>{formatDate(transfer.token_expires_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {/* Transfer Dialog */}
      <Dialog open={showTransferDialog} onClose={() => setShowTransferDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Transfer Request to Another Public Body</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Transfer this FOI request to another organization. They will receive a secure link
            to access the request details and optionally the uploaded documents.
          </Typography>
          <TextField
            fullWidth
            label="Recipient Organization"
            value={formData.recipient_organization}
            onChange={(e) => setFormData({ ...formData, recipient_organization: e.target.value })}
            sx={{ mb: 2 }}
            required
            placeholder="e.g., City of Vancouver"
          />
          <TextField
            fullWidth
            label="Recipient Email"
            type="email"
            value={formData.recipient_email}
            onChange={(e) => setFormData({ ...formData, recipient_email: e.target.value })}
            sx={{ mb: 2 }}
            required
            placeholder="foi@example.gov"
          />
          <TextField
            fullWidth
            label="Recipient Name (optional)"
            value={formData.recipient_name}
            onChange={(e) => setFormData({ ...formData, recipient_name: e.target.value })}
            sx={{ mb: 2 }}
          />
          <TextField
            fullWidth
            label="Reason for Transfer"
            multiline
            rows={3}
            value={formData.transfer_reason}
            onChange={(e) => setFormData({ ...formData, transfer_reason: e.target.value })}
            sx={{ mb: 2 }}
            required
            placeholder="Explain why this request is being transferred..."
          />
          <TextField
            fullWidth
            label="Internal Notes (optional)"
            multiline
            rows={2}
            value={formData.notes}
            onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
            sx={{ mb: 2 }}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={formData.include_documents}
                onChange={(e) => {
                  setFormData({ ...formData, include_documents: e.target.checked });
                  if (e.target.checked && selectedDocIds.length === 0) {
                    // Select all by default
                    setSelectedDocIds(documents.map(d => d.id));
                  }
                }}
              />
            }
            label="Include documents in transfer"
          />
          
          {formData.include_documents && documents.length > 0 && (
            <Box sx={{ mt: 2, pl: 4, maxHeight: 200, overflow: 'auto', border: '1px solid #e0e0e0', borderRadius: 1, p: 1 }}>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                Select documents to include ({selectedDocIds.length} of {documents.length} selected)
              </Typography>
              <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                <Button size="small" onClick={() => setSelectedDocIds(documents.map(d => d.id))}>
                  Select All
                </Button>
                <Button size="small" onClick={() => setSelectedDocIds([])}>
                  Clear
                </Button>
              </Box>
              {documents.map((doc) => (
                <FormControlLabel
                  key={doc.id}
                  control={
                    <Checkbox
                      size="small"
                      checked={selectedDocIds.includes(doc.id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedDocIds([...selectedDocIds, doc.id]);
                        } else {
                          setSelectedDocIds(selectedDocIds.filter(id => id !== doc.id));
                        }
                      }}
                    />
                  }
                  label={
                    <Typography variant="body2" sx={{ fontSize: '0.85rem' }}>
                      {doc.original_filename}
                    </Typography>
                  }
                  sx={{ display: 'block', ml: 0 }}
                />
              ))}
            </Box>
          )}
          
          {formData.include_documents && documents.length === 0 && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block', pl: 4 }}>
              No documents uploaded to this case yet.
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowTransferDialog(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleTransfer}
            disabled={!formData.recipient_organization || !formData.recipient_email || !formData.transfer_reason || submitting}
          >
            {submitting ? <CircularProgress size={20} /> : 'Transfer Request'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Transfer URL Dialog */}
      <Dialog open={!!newTransferUrl} onClose={() => setNewTransferUrl(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Transfer Initiated</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            The recipient has been emailed a secure link to access this request.
            You can also share this link directly:
          </Typography>
          <Box
            sx={{
              p: 2,
              bgcolor: 'grey.100',
              borderRadius: 1,
              display: 'flex',
              alignItems: 'center',
              gap: 1
            }}
          >
            <Typography
              variant="body2"
              sx={{ flex: 1, wordBreak: 'break-all', fontFamily: 'monospace' }}
            >
              {newTransferUrl}
            </Typography>
            <IconButton onClick={() => newTransferUrl && copyToClipboard(newTransferUrl)}>
              <ContentCopyIcon />
            </IconButton>
          </Box>
          <Alert severity="info" sx={{ mt: 2 }}>
            This link expires in 30 days. The case workflow stage has been updated to "Transferred".
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNewTransferUrl(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
};

export default TransferCase;
