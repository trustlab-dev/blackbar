import React, { useState, useEffect } from 'react';
import { Autocomplete, TextField, CircularProgress, Chip, Box, Typography } from '@mui/material';
import api from '../api/client';

// API_BASE_URL not needed - api client already has baseURL configured

interface User {
  id: string;
  username: string;
  email: string;
  role: string;
}

interface UserPickerProps {
  value: string;
  onChange: (userId: string) => void;
  label?: string;
  helperText?: string;
  required?: boolean;
}

const UserPicker: React.FC<UserPickerProps> = ({
  value,
  onChange,
  label = 'Select User',
  helperText = 'Type to search by name or email',
  required = false
}) => {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  useEffect(() => {
    // Load initial users
    searchUsers('');
  }, []);

  const searchUsers = async (query: string) => {
    setLoading(true);
    try {
      const response = await api.get('/auth/users/search', {
        params: { q: query || undefined, limit: 50 }
      });
      setUsers(response.data.users || []);
    } catch (err) {
      console.error('Error searching users:', err);
      setUsers([]);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (event: any, newInputValue: string) => {
    setInputValue(newInputValue);
    if (newInputValue.length >= 2 || newInputValue.length === 0) {
      searchUsers(newInputValue);
    }
  };

  const handleChange = (event: any, newValue: User | null) => {
    setSelectedUser(newValue);
    onChange(newValue?.id || '');
  };

  return (
    <Autocomplete
      value={selectedUser}
      onChange={handleChange}
      inputValue={inputValue}
      onInputChange={handleInputChange}
      options={users}
      getOptionLabel={(option) => option.username || ''}
      loading={loading}
      renderOption={(props, option) => {
        const { key, ...otherProps } = props;
        return (
          <Box component="li" key={key} {...otherProps}>
            <Box sx={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {option.username}
                </Typography>
                <Chip
                  label={option.role}
                  size="small"
                  sx={{
                    bgcolor: '#f0f0f0',
                    color: '#666',
                    fontSize: '10px',
                    height: '18px'
                  }}
                />
              </Box>
              <Typography variant="caption" color="text.secondary">
                {option.email}
              </Typography>
            </Box>
          </Box>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          helperText={helperText}
          required={required}
          InputProps={{
            ...params.InputProps,
            endAdornment: (
              <>
                {loading ? <CircularProgress color="inherit" size={20} /> : null}
                {params.InputProps.endAdornment}
              </>
            ),
          }}
        />
      )}
      noOptionsText={inputValue.length < 2 ? "Type to search..." : "No users found"}
    />
  );
};

export default UserPicker;
