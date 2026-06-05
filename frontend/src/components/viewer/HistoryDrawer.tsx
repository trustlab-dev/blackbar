// frontend/src/components/viewer/HistoryDrawer.tsx
import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Divider from '@mui/material/Divider';
import Avatar from '@mui/material/Avatar';
import Close from '@mui/icons-material/Close';
import Add from '@mui/icons-material/Add';
import Edit from '@mui/icons-material/Edit';
import Delete from '@mui/icons-material/Delete';
import Search from '@mui/icons-material/Search';
import AutoAwesome from '@mui/icons-material/AutoAwesome';
import api from '../../api/client';

interface AuditLogEntry {
  action: string;
  user_id: string;
  username: string;
  timestamp: string;
  details?: any;
}

interface Props {
  open: boolean;
  onClose: () => void;
  documentId: string;
}

const HistoryDrawer: React.FC<Props> = ({ open, onClose, documentId }) => {
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    if (open && documentId) {
      fetchAuditLogs();
    }
  }, [open, documentId]);

  const fetchAuditLogs = async () => {
    setLoading(true);
    setErrorMessage('');
    try {
      const response = await api.get(`/documents/${documentId}/audit-logs`);
      console.log('Audit logs full response:', response.data);
      console.log('Response keys:', Object.keys(response.data));
      
      // Try different possible keys
      const logs = response.data.audit_logs || response.data.logs || response.data || [];
      console.log('Parsed logs:', logs);
      console.log('Logs count:', Array.isArray(logs) ? logs.length : 'not an array');
      
      setAuditLogs(Array.isArray(logs) ? logs : []);
    } catch (error: any) {
      console.error('Error fetching audit logs:', error);
      setErrorMessage(error.response?.data?.detail || 'Failed to load history');
    } finally {
      setLoading(false);
    }
  };

  const getActionIcon = (action: string) => {
    if (action.includes('created') || action.includes('add')) return <Add fontSize="small" />;
    if (action.includes('edited') || action.includes('update')) return <Edit fontSize="small" />;
    if (action.includes('deleted') || action.includes('remove')) return <Delete fontSize="small" />;
    if (action.includes('search')) return <Search fontSize="small" />;
    if (action.includes('ai') || action.includes('suggest')) return <AutoAwesome fontSize="small" />;
    return <Edit fontSize="small" />;
  };

  const getActionColor = (action: string): string => {
    if (action.includes('created') || action.includes('add')) return '#22c55e';
    if (action.includes('deleted') || action.includes('remove')) return '#ef4444';
    if (action.includes('ai') || action.includes('suggest')) return '#3b82f6';
    return '#6b7280';
  };

  const formatActionText = (action: string): string => {
    return action
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (l) => l.toUpperCase());
  };

  const formatTimestamp = (timestamp: string): string => {
    try {
      // Backend sends UTC timestamps without 'Z' suffix, so add it
      const isoTimestamp = timestamp.endsWith('Z') ? timestamp : timestamp + 'Z';
      const date = new Date(isoTimestamp);
      const now = new Date();
      
      const diffMs = now.getTime() - date.getTime();
      const diffSecs = Math.floor(diffMs / 1000);
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);

      if (diffSecs < 30) return 'Just now';
      if (diffMins < 1) return `${diffSecs}s ago`;
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}d ago`;
      
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch (e) {
      console.error('Error parsing timestamp:', timestamp, e);
      return timestamp;
    }
  };

  const formatDetails = (log: AuditLogEntry): string | null => {
    if (!log.details) return null;
    
    // Extract useful info from details
    const details = log.details;
    
    // For redaction actions, show page and text
    if (log.action.includes('redaction')) {
      const parts: string[] = [];
      if (details.page) parts.push(`Page ${details.page}`);
      if (details.text) parts.push(`"${details.text.substring(0, 30)}${details.text.length > 30 ? '...' : ''}"`);
      if (details.category) parts.push(details.category);
      if (parts.length > 0) return parts.join(' • ');
    }
    
    // For other actions, show relevant details
    if (typeof details === 'string') {
      return details.substring(0, 80);
    }
    
    // Try to extract meaningful info from object
    const detailStr = JSON.stringify(details);
    if (detailStr.length > 10) {
      return detailStr.substring(0, 80) + (detailStr.length > 80 ? '...' : '');
    }
    
    return null;
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      variant="persistent"
      sx={{
        '& .MuiDrawer-paper': {
          width: 400,
          right: '60px',
          height: '100%',
          boxShadow: 3,
          position: 'absolute',
          zIndex: 1200
        }
      }}
      ModalProps={{
        keepMounted: true,
        BackdropProps: {
          invisible: true
        }
      }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Header */}
        <Box sx={{ p: 2, borderBottom: '1px solid #e0e0e0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography variant="h6">Document History</Typography>
          <IconButton size="small" onClick={onClose}>
            <Close />
          </IconButton>
        </Box>

        {/* Error Message */}
        {errorMessage && (
          <Alert severity="error" onClose={() => setErrorMessage('')} sx={{ m: 2 }}>
            {errorMessage}
          </Alert>
        )}

        {/* Content */}
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : auditLogs.length === 0 ? (
            <Alert severity="info" sx={{ m: 2 }}>No activity history available</Alert>
          ) : (
            <List sx={{ p: 0 }}>
              {auditLogs.map((log, index) => (
                <Box key={index}>
                  <ListItem alignItems="flex-start" sx={{ py: 2, px: 2 }}>
                    <ListItemIcon sx={{ minWidth: 48 }}>
                      <Avatar 
                        sx={{ 
                          width: 36, 
                          height: 36,
                          bgcolor: getActionColor(log.action),
                          color: 'white'
                        }}
                      >
                        {getActionIcon(log.action)}
                      </Avatar>
                    </ListItemIcon>
                    <ListItemText
                      primary={
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {formatActionText(log.action)}
                        </Typography>
                      }
                      secondary={
                        <>
                          <Typography variant="caption" color="text.secondary" component="span" sx={{ display: 'block' }}>
                            by {log.username || 'Unknown'} • {formatTimestamp(log.timestamp)}
                          </Typography>
                          {formatDetails(log) && (
                            <Typography variant="caption" color="text.secondary" component="span" sx={{ display: 'block', mt: 0.5 }}>
                              {formatDetails(log)}
                            </Typography>
                          )}
                        </>
                      }
                    />
                  </ListItem>
                  {index < auditLogs.length - 1 && <Divider variant="inset" component="li" />}
                </Box>
              ))}
            </List>
          )}
        </Box>
      </Box>
    </Drawer>
  );
};

export default HistoryDrawer;
