import React, { useState, useEffect } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Switch,
  Typography,
  IconButton,
  Tooltip
} from '@mui/material';
import {
  Add,
  Edit,
  Delete,
  Refresh,
  Lock
} from '@mui/icons-material';
import { getUsers, createUser, updateUser, deleteUser } from '../services/userService';
import { getApiErrorMessage } from '../api/errors';
import { useOptionalAuth } from '../contexts/AuthContext';
import { passwordPolicyError, PASSWORD_REQUIREMENTS_TEXT } from '../utils/passwordPolicy';

/**
 * The caller's system roles: AuthContext when mounted inside the provider,
 * otherwise what login persisted to localStorage.
 */
function useCallerRoles(): string[] {
  const auth = useOptionalAuth();
  if (auth?.roles?.length) return auth.roles.map((r) => r.toLowerCase());
  try {
    const stored = JSON.parse(localStorage.getItem('userRoles') || '[]');
    if (Array.isArray(stored) && stored.length) return stored.map((r) => String(r).toLowerCase());
  } catch {
    // fall through
  }
  const single = localStorage.getItem('userRole');
  return single ? [single.toLowerCase()] : [];
}

/**
 * Roles this caller may grant. Mirrors the backend rule in
 * backend/src/auth/routes.py `_ensure_may_assign` (and auth/roles.py
 * SYSTEM_ROLES): only an owner may hand out `owner`; anything else in the
 * role list is grantable by an owner or admin. `/auth/roles` omits `owner`,
 * so it is added back for owners.
 */
export function grantableRoles(available: string[], callerIsOwner: boolean): string[] {
  const roles = available.filter((r) => r !== 'owner');
  return callerIsOwner ? ['owner', ...roles] : roles;
}

const OWNER_ONLY_MESSAGE = 'Only an owner can modify an owner account';

// Define User interface
interface User {
  id: string;
  email: string;
  /** @deprecated kept for backwards compatibility with older user records */
  username?: string;
  full_name?: string;
  role: string;
  created_at: string;
  disabled?: boolean;
}

// New user input (magic-link flow — no password)
interface UserCreate {
  email: string;
  full_name: string;
  role: string;
}

// Define UserUpdate interface for updating existing users
interface UserUpdate {
  email?: string;
  username?: string;
  full_name?: string;
  password?: string;
  role?: string;
  disabled?: boolean;
}

const UserManagement: React.FC = () => {
  // State variables
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // Errors from the add/edit and password dialogs render inside the dialog;
  // the page-level alert sits behind the modal backdrop.
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [openDialog, setOpenDialog] = useState<boolean>(false);
  const [openPasswordDialog, setOpenPasswordDialog] = useState<boolean>(false);
  const [dialogMode, setDialogMode] = useState<'add' | 'edit'>('add');
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  // Form states
  const [newUser, setNewUser] = useState<UserCreate>({
    email: '',
    full_name: '',
    role: 'analyst'
  });
  const [invitationSent, setInvitationSent] = useState<string | null>(null);
  const [passwordData, setPasswordData] = useState<{
    password: string;
    confirmPassword: string;
  }>({
    password: '',
    confirmPassword: ''
  });

  // Available org roles
  const [userRoles, setUserRoles] = useState<string[]>(['owner', 'admin', 'analyst', 'user', 'guest']);
  const callerIsOwner = useCallerRoles().includes('owner');
  const assignableRoles = grantableRoles(userRoles, callerIsOwner);
  // An admin cannot change an owner account at all (403 from the backend).
  const isLockedOwner = (user: User) => user.role === 'owner' && !callerIsOwner;

  // Load users and roles on component mount
  useEffect(() => {
    fetchUsers();
    fetchRoles();
  }, []);

  // Fetch available roles from the API
  const fetchRoles = async () => {
    try {
      const { apiClient } = await import('../api/client');
      const response = await apiClient.get('/auth/roles');
      const data = response.data;
      if (data.roles) {
        setUserRoles(data.roles.map((r: any) => r.id));
      }
    } catch (err) {
      console.error('Error fetching roles:', err);
      // Keep default roles if fetch fails
    }
  };

  // Fetch users from the API
  const fetchUsers = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getUsers();
      setUsers(data);
    } catch (err: any) {
      setError(getApiErrorMessage(err, 'An error occurred while fetching users'));
    } finally {
      setIsLoading(false);
    }
  };

  // Handle form input changes
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setNewUser(prev => ({ ...prev, [name]: value }));
  };

  // Handle role selection changes
  const handleRoleChange = (e: any) => {
    setNewUser(prev => ({ ...prev, role: e.target.value }));
  };

  // Handle password changes in the password dialog
  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setPasswordData(prev => ({ ...prev, [name]: value }));
  };

  // Open dialog to add a new user
  const handleOpenAddDialog = () => {
    setDialogMode('add');
    setNewUser({
      email: '',
      full_name: '',
      role: 'analyst'
    });
    setInvitationSent(null);
    setDialogError(null);
    setOpenDialog(true);
  };

  // Open dialog to edit an existing user
  const handleOpenEditDialog = (user: User) => {
    setDialogMode('edit');
    setSelectedUser(user);
    setNewUser({
      email: user.email,
      full_name: user.full_name || '',
      role: user.role
    });
    setInvitationSent(null);
    setDialogError(null);
    setOpenDialog(true);
  };

  // Open dialog to change a user's password
  const handleOpenPasswordDialog = (user: User) => {
    setSelectedUser(user);
    setPasswordData({
      password: '',
      confirmPassword: ''
    });
    setDialogError(null);
    setOpenPasswordDialog(true);
  };

  // Close all dialogs
  const handleCloseDialogs = () => {
    setOpenDialog(false);
    setOpenPasswordDialog(false);
    setSelectedUser(null);
    setDialogError(null);
  };

  // Toggle a user's disabled status
  const handleToggleDisable = async (user: User) => {
    try {
      await updateUser(user.id, { disabled: !user.disabled });
      // Update the local state
      setUsers(users.map(u => u.id === user.id ? { ...u, disabled: !u.disabled } : u));
    } catch (err: any) {
      setError(getApiErrorMessage(err, `Failed to ${user.disabled ? 'enable' : 'disable'} user`));
    }
  };

  // Submit form to add or edit a user
  const handleSubmit = async () => {
    try {
      if (dialogMode === 'add') {
        // Validate required fields (no password needed - magic link flow)
        if (!newUser.email || !newUser.role) {
          setDialogError('Email and role are required');
          return;
        }

        // Create new user (will send invitation email)
        const result = await createUser(newUser as UserCreate);
        if (result.invitation_sent) {
          setInvitationSent(newUser.email);
          setTimeout(() => {
            handleCloseDialogs();
            fetchUsers();
          }, 2000);
        } else {
          await fetchUsers();
          handleCloseDialogs();
        }
      } else if (dialogMode === 'edit' && selectedUser) {
        // Update existing user
        await updateUser(selectedUser.id, newUser as UserUpdate);
        // Update the local state
        setUsers(users.map(u => u.id === selectedUser.id ? { ...u, ...newUser } : u));
        handleCloseDialogs();
      }
    } catch (err: any) {
      // 403 "Only an owner can assign the owner role", 422 invalid role, ...
      setDialogError(getApiErrorMessage(err, 'Failed to save user'));
    }
  };

  // Submit password change
  const handleSubmitPassword = async () => {
    if (!selectedUser) return;

    // Validate passwords match
    if (passwordData.password !== passwordData.confirmPassword) {
      setDialogError('Passwords do not match');
      return;
    }
    const policyError = passwordPolicyError(passwordData.password);
    if (policyError) {
      setDialogError(policyError);
      return;
    }

    try {
      await updateUser(selectedUser.id, { password: passwordData.password });
      handleCloseDialogs();
    } catch (err: any) {
      // The backend's 422 policy message or 403 owner-account refusal.
      setDialogError(getApiErrorMessage(err, 'Failed to update password'));
    }
  };

  return (
    <Box sx={{ width: '100%' }}>
      {error && (
        <Typography color="error" sx={{ my: 2 }}>
          {error}
        </Typography>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">User Management</Typography>
        <Box>
          <Button
            variant="outlined"
            startIcon={<Refresh />}
            onClick={fetchUsers}
            sx={{ mr: 1 }}
          >
            Refresh
          </Button>
          <Button
            variant="contained"
            startIcon={<Add />}
            onClick={handleOpenAddDialog}
          >
            Add User
          </Button>
        </Box>
      </Box>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Email</TableCell>
              <TableCell>Role</TableCell>
              <TableCell>Created</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} align="center">Loading users...</TableCell>
              </TableRow>
            ) : users.length > 0 ? (
              users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>{user.full_name || user.email.split('@')[0]}</TableCell>
                  <TableCell>{user.email}</TableCell>
                  <TableCell>{user.role}</TableCell>
                  <TableCell>{new Date(user.created_at).toLocaleDateString()}</TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center' }}>
                      <Switch
                        checked={!user.disabled}
                        onChange={() => handleToggleDisable(user)}
                        disabled={isLockedOwner(user)}
                        inputProps={{ 'aria-label': 'toggle user status' }}
                      />
                      <Typography variant="body2">
                        {user.disabled ? 'Disabled' : 'Active'}
                      </Typography>
                    </Box>
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title={isLockedOwner(user) ? OWNER_ONLY_MESSAGE : 'Change Password'}>
                      <span>
                        <IconButton
                          aria-label="Change Password"
                          onClick={() => handleOpenPasswordDialog(user)}
                          disabled={isLockedOwner(user)}
                        >
                          <Lock />
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title={isLockedOwner(user) ? OWNER_ONLY_MESSAGE : 'Edit User'}>
                      <span>
                        <IconButton
                          aria-label="Edit User"
                          onClick={() => handleOpenEditDialog(user)}
                          disabled={isLockedOwner(user)}
                        >
                          <Edit />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={7} align="center">No users found</TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Add/Edit User Dialog */}
      <Dialog open={openDialog} onClose={handleCloseDialogs} maxWidth="sm" fullWidth>
        <DialogTitle>
          {dialogMode === 'add' ? 'Invite New User' : 'Edit User'}
        </DialogTitle>
        <DialogContent>
          {invitationSent ? (
            <Box sx={{ textAlign: 'center', py: 3 }}>
              <Typography variant="h6" color="success.main" gutterBottom>
                ✓ Invitation Sent!
              </Typography>
              <Typography color="text.secondary">
                An activation email has been sent to {invitationSent}
              </Typography>
            </Box>
          ) : (
            <>
              {dialogError && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {dialogError}
                </Alert>
              )}
              <TextField
                margin="dense"
                name="email"
                label="Email Address"
                type="email"
                fullWidth
                value={newUser.email}
                onChange={handleInputChange}
                helperText={dialogMode === 'add' ? 'User will receive an invitation email to set their password' : 'Changing email requires user to re-verify'}
              />
              <TextField
                margin="dense"
                name="full_name"
                label="Full Name"
                type="text"
                fullWidth
                value={newUser.full_name || ''}
                onChange={handleInputChange}
              />
              <FormControl fullWidth margin="dense">
                <InputLabel id="user-role-label">Role</InputLabel>
                <Select
                  labelId="user-role-label"
                  value={newUser.role}
                  onChange={handleRoleChange}
                  label="Role"
                >
                  {assignableRoles.map((role) => (
                    <MenuItem key={role} value={role}>
                      {role.charAt(0).toUpperCase() + role.slice(1)}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialogs}>{invitationSent ? 'Close' : 'Cancel'}</Button>
          {!invitationSent && (
            <Button onClick={handleSubmit} variant="contained">
              {dialogMode === 'add' ? 'Send Invitation' : 'Save Changes'}
            </Button>
          )}
        </DialogActions>
      </Dialog>

      {/* Change Password Dialog */}
      <Dialog open={openPasswordDialog} onClose={handleCloseDialogs} maxWidth="sm" fullWidth>
        <DialogTitle>Change Password</DialogTitle>
        <DialogContent>
          {dialogError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {dialogError}
            </Alert>
          )}
          <TextField
            margin="dense"
            name="password"
            label="New Password"
            type="password"
            fullWidth
            value={passwordData.password}
            onChange={handlePasswordChange}
            helperText={PASSWORD_REQUIREMENTS_TEXT}
          />
          <TextField
            margin="dense"
            name="confirmPassword"
            label="Confirm New Password"
            type="password"
            fullWidth
            value={passwordData.confirmPassword}
            onChange={handlePasswordChange}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialogs}>Cancel</Button>
          <Button onClick={handleSubmitPassword} variant="contained">
            Update Password
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default UserManagement;
