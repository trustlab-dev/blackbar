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
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  Chip,
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  Tooltip
} from '@mui/material';
import PersonAddIcon from '@mui/icons-material/PersonAdd';
import DeleteIcon from '@mui/icons-material/Delete';
import api from '../api/client';
import UserPicker from './UserPicker';

// API_BASE_URL not needed - using api client directly

interface CaseTeamMember {
  user_id: string;
  role: string;
  department?: string;
  permissions: string[];
  added_at: string;
  added_by: string;
  status: string;
  notes?: string;
  review_status?: string;
  approval_status?: string;
  user_name?: string;
  user_email?: string;
}

interface CaseTeamPanelProps {
  caseId: string;
  canManageTeam: boolean;
}

const ROLE_LABELS: { [key: string]: string } = {
  analyst: 'Analyst',
  legal: 'Legal',
  sme: 'Subject Matter Expert',
  reviewer: 'Reviewer',
  approver: 'Approver',
  third_party: 'Third-Party',
  manager: 'Manager'
};

const ROLE_COLORS: { [key: string]: string } = {
  analyst: '#333',
  legal: '#666',
  sme: '#666',
  reviewer: '#666',
  approver: '#666',
  third_party: '#999',
  manager: '#000'
};

const ROLE_DESCRIPTIONS: { [key: string]: string } = {
  analyst: 'Primary case handler - reviews documents, applies redactions, and prepares responses',
  legal: 'Provides legal advice on redaction decisions and FOI compliance',
  sme: 'Subject matter expert - provides specialized knowledge for specific content areas',
  reviewer: 'Reviews completed redactions before final approval',
  approver: 'Final authority - approves cases for release to requester',
  third_party: 'External consultant or party providing input on the case',
  manager: 'Oversees case workflow and team coordination'
};

const CaseTeamPanel: React.FC<CaseTeamPanelProps> = ({ caseId, canManageTeam }) => {
  const [teamMembers, setTeamMembers] = useState<CaseTeamMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openAddDialog, setOpenAddDialog] = useState(false);
  
  // Add member form state
  const [newMemberUserId, setNewMemberUserId] = useState('');
  const [newMemberRole, setNewMemberRole] = useState('legal');
  const [newMemberDepartment, setNewMemberDepartment] = useState('');
  const [newMemberNotes, setNewMemberNotes] = useState('');

  useEffect(() => {
    fetchTeamMembers();
  }, [caseId]);

  const fetchTeamMembers = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/cases/${caseId}/team`);
      setTeamMembers(response.data.team_members || []);
      setError(null);
    } catch (err: any) {
      console.error('Error fetching team members:', err);
      setError(err.response?.data?.detail || 'Failed to fetch team members');
    } finally {
      setLoading(false);
    }
  };

  const handleAddMember = async () => {
    if (!newMemberUserId) {
      setError('User ID is required');
      return;
    }

    try {
      setLoading(true);
      await api.post(`/cases/${caseId}/team/members`, {
        user_id: newMemberUserId,
        role: newMemberRole,
        department: newMemberDepartment || undefined,
        notes: newMemberNotes || undefined
      });
      
      setOpenAddDialog(false);
      setNewMemberUserId('');
      setNewMemberRole('legal');
      setNewMemberDepartment('');
      setNewMemberNotes('');
      
      await fetchTeamMembers();
    } catch (err: any) {
      console.error('Error adding team member:', err);
      setError(err.response?.data?.detail || 'Failed to add team member');
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!window.confirm('Are you sure you want to remove this team member?')) {
      return;
    }

    try {
      setLoading(true);
      await api.delete(`/cases/${caseId}/team/members/${userId}`);
      await fetchTeamMembers();
    } catch (err: any) {
      console.error('Error removing team member:', err);
      setError(err.response?.data?.detail || 'Failed to remove team member');
    } finally {
      setLoading(false);
    }
  };

  const getRoleChip = (role: string) => {
    return (
      <Tooltip title={ROLE_DESCRIPTIONS[role] || 'Team member role'} arrow>
        <Chip
          label={ROLE_LABELS[role] || role}
          size="small"
          sx={{
            bgcolor: ROLE_COLORS[role] || '#666',
            color: 'white',
            fontWeight: 600,
            fontSize: '11px',
            cursor: 'help'
          }}
        />
      </Tooltip>
    );
  };

  const getStatusBadge = (member: CaseTeamMember) => {
    if (member.approval_status === 'pending') {
      return <Chip label="Approval Pending" size="small" sx={{ bgcolor: 'var(--color-warning-bg)', color: 'var(--color-warning-text)' }} />;
    }
    if (member.approval_status === 'approved') {
      return <Chip label="Approved" size="small" sx={{ bgcolor: 'var(--color-success-bg)', color: 'var(--color-success-text)' }} />;
    }
    if (member.review_status === 'pending') {
      return <Chip label="Review Pending" size="small" sx={{ bgcolor: 'var(--color-warning-bg)', color: 'var(--color-warning-text)' }} />;
    }
    if (member.review_status === 'approved') {
      return <Chip label="Review Complete" size="small" sx={{ bgcolor: 'var(--color-success-bg)', color: 'var(--color-success-text)' }} />;
    }
    return null;
  };

  return (
    <Box sx={{ border: '1px solid var(--border-default)', borderRadius: '4px', bgcolor: 'white' }}>
      <Box sx={{
        p: 2,
        borderBottom: '1px solid var(--border-default)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        bgcolor: 'var(--bg-secondary)'
      }}>
        <Typography variant="h6" sx={{ fontWeight: 600, color: 'var(--text-primary)' }}>
          Case Team ({teamMembers.length})
        </Typography>
        {canManageTeam && (
          <Button
            size="small"
            startIcon={<PersonAddIcon />}
            onClick={() => setOpenAddDialog(true)}
            sx={{
              borderColor: '#d0d0d0',
              color: 'var(--text-primary)',
              '&:hover': {
                borderColor: 'var(--text-muted)',
                bgcolor: 'var(--bg-tertiary)'
              }
            }}
          >
            Add Member
          </Button>
        )}
      </Box>

      {error && (
        <Alert severity="error" sx={{ m: 2 }}>
          {error}
        </Alert>
      )}

      <List sx={{ p: 0 }}>
        {teamMembers.length === 0 ? (
          <ListItem>
            <ListItemText
              primary="No team members"
              secondary="Add team members to collaborate on this case"
            />
          </ListItem>
        ) : (
          teamMembers.map((member, index) => (
            <ListItem
              key={member.user_id}
              sx={{
                borderBottom: index < teamMembers.length - 1 ? '1px solid #f0f0f0' : 'none',
                '&:hover': {
                  bgcolor: '#fafafa'
                }
              }}
            >
              <Box sx={{ flex: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Typography variant="body1" sx={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                    {member.user_name || member.user_id}
                  </Typography>
                  {getRoleChip(member.role)}
                  {getStatusBadge(member)}
                </Box>
                <Box>
                  {member.department && (
                    <Typography variant="body2" color="text.secondary" sx={{ fontSize: '13px' }}>
                      {member.department}
                    </Typography>
                  )}
                  {member.notes && (
                    <Typography variant="body2" color="text.secondary" sx={{ fontSize: '13px', fontStyle: 'italic' }}>
                      {member.notes}
                    </Typography>
                  )}
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '11px' }}>
                    Added {new Date(member.added_at).toLocaleDateString()}
                  </Typography>
                </Box>
              </Box>
              {canManageTeam && member.role !== 'analyst' && (
                <ListItemSecondaryAction>
                  <IconButton
                    edge="end"
                    size="small"
                    onClick={() => handleRemoveMember(member.user_id)}
                    sx={{ color: 'var(--text-secondary)' }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </ListItemSecondaryAction>
              )}
            </ListItem>
          ))
        )}
      </List>

      {/* Add Member Dialog */}
      <Dialog open={openAddDialog} onClose={() => setOpenAddDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Team Member</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <UserPicker
              value={newMemberUserId}
              onChange={(userId) => setNewMemberUserId(userId)}
              label="Select User"
              helperText="Search by name or email"
              required
            />
            
            <FormControl fullWidth>
              <InputLabel>Role</InputLabel>
              <Select
                value={newMemberRole}
                label="Role"
                onChange={(e) => setNewMemberRole(e.target.value)}
              >
                <MenuItem value="legal">Legal</MenuItem>
                <MenuItem value="sme">Subject Matter Expert</MenuItem>
                <MenuItem value="reviewer">Reviewer</MenuItem>
                <MenuItem value="approver">Approver</MenuItem>
                <MenuItem value="third_party">Third-Party</MenuItem>
                <MenuItem value="manager">Manager</MenuItem>
              </Select>
            </FormControl>
            
            <TextField
              fullWidth
              label="Department (Optional)"
              value={newMemberDepartment}
              onChange={(e) => setNewMemberDepartment(e.target.value)}
            />
            
            <TextField
              fullWidth
              label="Notes (Optional)"
              value={newMemberNotes}
              onChange={(e) => setNewMemberNotes(e.target.value)}
              multiline
              rows={2}
              helperText="Why is this person being added to the team?"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenAddDialog(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleAddMember}
            variant="contained"
            disabled={loading || !newMemberUserId}
          >
            Add Member
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default CaseTeamPanel;
