/**
 * Contributors Panel Component.
 *
 * Manages named record contributors for a case.
 * Allows inviting contributors, tracking their uploads, and sending reminders.
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
import Tooltip from '@mui/material/Tooltip';
import PersonAddIcon from '@mui/icons-material/PersonAdd';
import GroupAddIcon from '@mui/icons-material/GroupAdd';
import EmailIcon from '@mui/icons-material/Email';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteIcon from '@mui/icons-material/Delete';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import ErrorIcon from '@mui/icons-material/Error';
import GroupIcon from '@mui/icons-material/Group';
import VisibilityIcon from '@mui/icons-material/Visibility';
import UploadIcon from '@mui/icons-material/Upload';
import { contributorsApi, CaseContributor } from '../../api/workflowApi';

interface ContributorsPanelProps {
  caseId: string;
}

const ContributorsPanel: React.FC<ContributorsPanelProps> = ({ caseId }) => {
  const [contributors, setContributors] = useState<CaseContributor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showInviteDialog, setShowInviteDialog] = useState(false);
  const [showBulkDialog, setShowBulkDialog] = useState(false);
  const [inviteData, setInviteData] = useState({
    name: '',
    email: '',
    department: '',
    notes: ''
  });
  const [bulkText, setBulkText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [newUploadUrl, setNewUploadUrl] = useState<string | null>(null);
  const [bulkResults, setBulkResults] = useState<any[] | null>(null);

  useEffect(() => {
    fetchContributors();
  }, [caseId]);

  const fetchContributors = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await contributorsApi.list(caseId);
      setContributors(data);
    } catch (err: any) {
      if (err.response?.status !== 404) {
        setError('Failed to load contributors');
      }
      setContributors([]);
    } finally {
      setLoading(false);
    }
  };

  const handleInvite = async () => {
    if (!inviteData.name || !inviteData.email) return;

    try {
      setSubmitting(true);
      const result = await contributorsApi.invite(caseId, {
        name: inviteData.name,
        email: inviteData.email,
        department: inviteData.department || undefined,
        notes: inviteData.notes || undefined
      });
      setNewUploadUrl(window.location.origin + result.upload_url);
      setSuccess(`Invitation sent to ${inviteData.email}`);
      setInviteData({ name: '', email: '', department: '', notes: '' });
      await fetchContributors();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to invite contributor');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemind = async (contributorId: string, email: string) => {
    try {
      await contributorsApi.remind(caseId, contributorId);
      setSuccess(`Reminder sent to ${email}`);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to send reminder');
    }
  };

  const handleDelete = async (contributorId: string) => {
    if (!window.confirm('Are you sure you want to remove this contributor?')) return;

    try {
      await contributorsApi.delete(caseId, contributorId);
      await fetchContributors();
      setSuccess('Contributor removed');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to remove contributor');
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setSuccess('Link copied to clipboard');
  };

  const handleBulkInvite = async () => {
    // Parse bulk text: "Name, email, department" per line
    const lines = bulkText.split('\n').filter(line => line.trim());
    const contributors = lines.map(line => {
      const parts = line.split(',').map(p => p.trim());
      return {
        name: parts[0] || '',
        email: parts[1] || '',
        department: parts[2] || undefined
      };
    }).filter(c => c.name && c.email);

    if (contributors.length === 0) {
      setError('No valid contributors found. Format: Name, email, department (one per line)');
      return;
    }

    try {
      setSubmitting(true);
      const result = await contributorsApi.bulkInvite(caseId, contributors);
      setBulkResults(result.invitations.map((inv: any) => ({
        ...inv,
        upload_url: window.location.origin + inv.upload_url
      })));
      setSuccess(`${result.count} contributors invited`);
      setBulkText('');
      await fetchContributors();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to bulk invite contributors');
    } finally {
      setSubmitting(false);
    }
  };

  const getStatusChip = (contributor: CaseContributor) => {
    // Check if records confirmed
    if ((contributor as any).records_confirmed) {
      return <Chip size="small" icon={<CheckCircleIcon />} label="Complete" color="success" />;
    }
    
    const status = contributor.status;
    switch (status) {
      case 'completed':
        return <Chip size="small" icon={<CheckCircleIcon />} label="Complete" color="success" />;
      case 'active':
        // Has accessed but not confirmed
        if (contributor.documents_uploaded > 0) {
          return <Chip size="small" icon={<UploadIcon />} label="Uploading" color="warning" />;
        }
        return <Chip size="small" icon={<VisibilityIcon />} label="Accessed" color="primary" />;
      case 'invited':
        return <Chip size="small" icon={<EmailIcon />} label="Pending" color="default" />;
      case 'expired':
        return <Chip size="small" icon={<ErrorIcon />} label="Expired" color="error" />;
      default:
        return <Chip size="small" label={status} />;
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
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
        avatar={<GroupIcon />}
        title="Record Contributors"
        subheader={`${contributors.length} contributor${contributors.length !== 1 ? 's' : ''}`}
        action={
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              size="small"
              variant="outlined"
              startIcon={<GroupAddIcon />}
              onClick={() => setShowBulkDialog(true)}
            >
              Bulk
            </Button>
            <Button
              size="small"
              variant="contained"
              startIcon={<PersonAddIcon />}
              onClick={() => setShowInviteDialog(true)}
            >
              Invite
            </Button>
          </Box>
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

        {contributors.length === 0 ? (
          <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
            No contributors invited yet. Click "Invite" to add record providers.
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Department</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Documents</TableCell>
                <TableCell>Expires</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {contributors.map((contributor) => (
                <TableRow key={contributor.id}>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>
                      {contributor.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {contributor.email}
                    </Typography>
                  </TableCell>
                  <TableCell>{contributor.department || '-'}</TableCell>
                  <TableCell>{getStatusChip(contributor)}</TableCell>
                  <TableCell>{contributor.documents_uploaded}</TableCell>
                  <TableCell>{formatDate(contributor.token_expires_at)}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="Send reminder">
                      <IconButton
                        size="small"
                        onClick={() => handleRemind(contributor.id, contributor.email)}
                        disabled={contributor.status === 'completed' || contributor.status === 'expired'}
                      >
                        <EmailIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Remove">
                      <IconButton
                        size="small"
                        onClick={() => handleDelete(contributor.id)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {/* Invite Dialog */}
      <Dialog open={showInviteDialog} onClose={() => setShowInviteDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Invite Record Contributor</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Send an invitation to someone who needs to upload records for this case.
            They will receive a secure link to upload documents.
          </Typography>
          <TextField
            fullWidth
            label="Name"
            value={inviteData.name}
            onChange={(e) => setInviteData({ ...inviteData, name: e.target.value })}
            sx={{ mb: 2 }}
            required
          />
          <TextField
            fullWidth
            label="Email"
            type="email"
            value={inviteData.email}
            onChange={(e) => setInviteData({ ...inviteData, email: e.target.value })}
            sx={{ mb: 2 }}
            required
          />
          <TextField
            fullWidth
            label="Department (optional)"
            value={inviteData.department}
            onChange={(e) => setInviteData({ ...inviteData, department: e.target.value })}
            sx={{ mb: 2 }}
          />
          <TextField
            fullWidth
            label="Notes (optional)"
            multiline
            rows={2}
            value={inviteData.notes}
            onChange={(e) => setInviteData({ ...inviteData, notes: e.target.value })}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowInviteDialog(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleInvite}
            disabled={!inviteData.name || !inviteData.email || submitting}
          >
            {submitting ? <CircularProgress size={20} /> : 'Send Invitation'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Upload URL Dialog */}
      <Dialog open={!!newUploadUrl} onClose={() => setNewUploadUrl(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Invitation Sent</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            The contributor has been emailed an invitation. You can also share this link directly:
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
              {newUploadUrl}
            </Typography>
            <IconButton onClick={() => newUploadUrl && copyToClipboard(newUploadUrl)}>
              <ContentCopyIcon />
            </IconButton>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNewUploadUrl(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Bulk Invite Dialog */}
      <Dialog open={showBulkDialog} onClose={() => setShowBulkDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>Bulk Invite Contributors</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Enter one contributor per line in the format: <strong>Name, Email, Department</strong> (department is optional)
          </Typography>
          <TextField
            fullWidth
            multiline
            rows={8}
            placeholder="John Smith, john@example.com, HR
Jane Doe, jane@example.com, Finance
Bob Wilson, bob@example.com"
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            sx={{ fontFamily: 'monospace' }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            {bulkText.split('\n').filter(l => l.trim()).length} contributor(s) detected
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowBulkDialog(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleBulkInvite}
            disabled={!bulkText.trim() || submitting}
          >
            {submitting ? <CircularProgress size={20} /> : 'Send Invitations'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Bulk Results Dialog */}
      <Dialog open={!!bulkResults} onClose={() => setBulkResults(null)} maxWidth="md" fullWidth>
        <DialogTitle>Invitations Sent</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            {bulkResults?.length} contributor(s) have been invited. Share these links or they will receive emails:
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Email</TableCell>
                <TableCell>Link</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {bulkResults?.map((inv: any, idx: number) => (
                <TableRow key={idx}>
                  <TableCell>{inv.contributor.name}</TableCell>
                  <TableCell>{inv.contributor.email}</TableCell>
                  <TableCell>
                    <IconButton size="small" onClick={() => copyToClipboard(inv.upload_url)}>
                      <ContentCopyIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBulkResults(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
};

export default ContributorsPanel;
