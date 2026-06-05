import React, { useState, useEffect } from 'react';
import { Box, Typography, Paper, Card, CardContent, List, ListItem, ListItemText, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import UserManagement from './UserManagement';
import ReportingDashboard from './ReportingDashboard';
import SystemConfiguration from './SystemConfiguration';
import OrganizationBranding from './OrganizationBranding';
import TemplatesManager from './TemplatesManager';
import LLMConfiguration from './LLMConfiguration';
import PackManagement from './PackManagement/PackManagement';
import api from '../api/client';

const AdminConsole: React.FC = () => {
  const [activeTab, setActiveTab] = useState(0);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);

  const menuItems = [
    { label: 'Dashboard' },
    { label: 'User Management' },
    { label: 'System Configuration' },
    { label: 'Branding' },
    { label: 'Templates' },
    { label: 'LLM Configuration' },
    { label: 'Packs' },
    { label: 'Audit Logs' }
  ];

  useEffect(() => {
    if (activeTab === 7) {
      fetchAuditLogs();
    }
  }, [activeTab]);

  const fetchAuditLogs = async () => {
    setLoadingLogs(true);
    try {
      const token = localStorage.getItem('token');
      const response = await api.get('/cases/', {
        params: { limit: 50 },
        headers: { Authorization: `Bearer ${token}` }
      });

      const logs: any[] = [];
      response.data.cases.forEach((caseItem: any) => {
        if (caseItem.audit_log && Array.isArray(caseItem.audit_log)) {
          caseItem.audit_log.forEach((log: any) => {
            logs.push({
              ...log,
              case_number: caseItem.tracking_number,
              case_title: caseItem.title
            });
          });
        }
      });

      logs.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
      setAuditLogs(logs.slice(0, 100));
    } catch (error) {
      console.error('Error fetching audit logs:', error);
    } finally {
      setLoadingLogs(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', minHeight: 'calc(100vh - 100px)', p: 3 }}>
      {/* Left Sidebar Navigation */}
      <Paper
        sx={{
          width: 280,
          mr: 3,
          borderRadius: '8px',
          border: '1px solid var(--border-default)'
        }}
      >
        <Box sx={{ p: 3, borderBottom: '1px solid var(--border-default)' }}>
          <Typography variant="h5" sx={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            Admin Console
          </Typography>
        </Box>
        <List sx={{ p: 2 }}>
          {menuItems.map((item, index) => (
            <ListItem
              key={index}
              onClick={() => setActiveTab(index)}
              sx={{
                mb: 1,
                borderRadius: '6px',
                backgroundColor: activeTab === index ? 'var(--bg-tertiary)' : 'transparent',
                '&:hover': {
                  backgroundColor: 'var(--bg-tertiary)'
                },
                transition: 'all 0.2s',
                cursor: 'pointer'
              }}
            >
              <ListItemText
                primary={item.label}
                sx={{
                  '& .MuiTypography-root': {
                    fontWeight: activeTab === index ? 600 : 400,
                    color: 'var(--text-primary)',
                    fontSize: '15px'
                  }
                }}
              />
            </ListItem>
          ))}
        </List>
      </Paper>

      {/* Main Content Area */}
      <Box sx={{ flex: 1 }}>
        {/* Dashboard */}
        {activeTab === 0 && (
          <Box>
            <ReportingDashboard />
          </Box>
        )}

        {/* User Management */}
        {activeTab === 1 && (
          <Box>
            <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
              User Management
            </Typography>
            <UserManagement />
          </Box>
        )}

        {/* System Configuration */}
        {activeTab === 2 && (
          <Box>
            <SystemConfiguration />
          </Box>
        )}

        {/* Branding */}
        {activeTab === 3 && (
          <Box>
            <OrganizationBranding />
          </Box>
        )}

        {/* Templates */}
        {activeTab === 4 && (
          <Box>
            <TemplatesManager />
          </Box>
        )}

        {/* LLM Configuration */}
        {activeTab === 5 && (
          <Box>
            <LLMConfiguration />
          </Box>
        )}

        {/* Packs */}
        {activeTab === 6 && (
          <Box>
            <PackManagement />
          </Box>
        )}

        {/* Audit Logs */}
        {activeTab === 7 && (
          <Box>
            <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
              Audit Logs
            </Typography>
            {loadingLogs ? (
              <Card>
                <CardContent>
                  <Typography>Loading audit logs...</Typography>
                </CardContent>
              </Card>
            ) : auditLogs.length === 0 ? (
              <Card>
                <CardContent>
                  <Typography>No audit logs found</Typography>
                </CardContent>
              </Card>
            ) : (
              <TableContainer component={Paper}>
                <Table>
                  <TableHead>
                    <TableRow sx={{ bgcolor: 'var(--bg-secondary)' }}>
                      <TableCell sx={{ fontWeight: 600 }}>Timestamp</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>User</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Action</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Case</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Details</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {auditLogs.map((log, index) => (
                      <TableRow key={index} sx={{ '&:hover': { bgcolor: 'var(--bg-tertiary)' } }}>
                        <TableCell sx={{ fontSize: '14px' }}>
                          {new Date(log.timestamp).toLocaleString()}
                        </TableCell>
                        <TableCell sx={{ fontSize: '14px' }}>{log.user_name || 'System'}</TableCell>
                        <TableCell sx={{ fontSize: '14px' }}>
                          {log.action.replace(/_/g, ' ')}
                        </TableCell>
                        <TableCell sx={{ fontSize: '14px' }}>
                          {log.case_number || '-'}
                        </TableCell>
                        <TableCell sx={{ fontSize: '14px', maxWidth: 300 }}>
                          {log.details ? JSON.stringify(log.details).substring(0, 100) : '-'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Box>
        )}
      </Box>
    </Box>
  );
};

export default AdminConsole;
