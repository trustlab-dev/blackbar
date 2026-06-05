import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Paper,
  Grid,
  Card,
  CardContent,
  CircularProgress,
  Alert,
  Chip,
  List,
  ListItem,
  ListItemText,
  LinearProgress,
  Divider
} from '@mui/material';
// Using text icons instead of @mui/icons-material
import api from '../api/client';

// API_BASE_URL not needed - api client already has baseURL configured

interface DeadlineInfo {
  deadline: string;
  status: string;
  days_remaining: number;
  business_days_remaining: number;
  is_overdue: boolean;
  requires_attention: boolean;
}

interface CaseWithDeadline {
  id: string;
  case_number: string;
  title: string;
  status: string;
  deadline_info: DeadlineInfo;
}

interface DashboardSummary {
  total_cases: number;
  on_track: number;
  warning: number;
  urgent: number;
  overdue: number;
  requires_attention: number;
  compliance_rate: number;
  at_risk_rate: number;
}

const ReportingDashboard: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [attentionCases, setAttentionCases] = useState<CaseWithDeadline[]>([]);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await api.get(
        '/cases/deadline-dashboard',
        {
          headers: { Authorization: `Bearer ${token}` }
        }
      );

      setSummary(response.data.summary);
      setAttentionCases(response.data.attention_required || []);
    } catch (err: any) {
      console.error('Error fetching dashboard data:', err);
      setError(err.response?.data?.detail || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'on_track': return 'success';
      case 'warning': return 'warning';
      case 'urgent': return 'error';
      case 'overdue': return 'error';
      default: return 'default';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'on_track': return '✓';
      case 'warning': return '⚠';
      case 'urgent': return '⚠';
      case 'overdue': return '✕';
      default: return '⏱';
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'on_track': return 'On Track';
      case 'warning': return 'Warning';
      case 'urgent': return 'Urgent';
      case 'overdue': return 'OVERDUE';
      default: return status;
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        Reporting Dashboard
      </Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom sx={{ mb: 4 }}>
        Deadline tracking and SLA compliance monitoring
      </Typography>

      {/* Summary Cards */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <span style={{ marginRight: '8px' }}>✓</span>
                <Typography variant="h6">On Track</Typography>
              </Box>
              <Typography variant="h3" color="success.main">
                {summary?.on_track || 0}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Cases meeting deadlines
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <span style={{ marginRight: '8px' }}>⚠</span>
                <Typography variant="h6">Warning</Typography>
              </Box>
              <Typography variant="h3" color="warning.main">
                {summary?.warning || 0}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Within 7 days
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <span style={{ marginRight: '8px' }}>⚠</span>
                <Typography variant="h6">Urgent</Typography>
              </Box>
              <Typography variant="h3" color="error.main">
                {summary?.urgent || 0}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Within 3 days
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ bgcolor: 'error.dark', color: 'white' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <span style={{ marginRight: '8px' }}>✕</span>
                <Typography variant="h6">Overdue</Typography>
              </Box>
              <Typography variant="h3">
                {summary?.overdue || 0}
              </Typography>
              <Typography variant="caption">
                Past deadline
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Compliance Metrics */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Compliance Rate
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Box sx={{ flex: 1, mr: 2 }}>
                <LinearProgress
                  variant="determinate"
                  value={summary?.compliance_rate || 0}
                  sx={{ height: 10, borderRadius: 5 }}
                  color="success"
                />
              </Box>
              <Typography variant="h5" color="success.main">
                {summary?.compliance_rate?.toFixed(1) || 0}%
              </Typography>
            </Box>
            <Typography variant="caption" color="text.secondary">
              Cases on track or completed on time
            </Typography>
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              At-Risk Rate
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Box sx={{ flex: 1, mr: 2 }}>
                <LinearProgress
                  variant="determinate"
                  value={summary?.at_risk_rate || 0}
                  sx={{ height: 10, borderRadius: 5 }}
                  color="error"
                />
              </Box>
              <Typography variant="h5" color="error.main">
                {summary?.at_risk_rate?.toFixed(1) || 0}%
              </Typography>
            </Box>
            <Typography variant="caption" color="text.secondary">
              Cases requiring immediate attention
            </Typography>
          </Paper>
        </Grid>
      </Grid>

      {/* Cases Requiring Attention */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>
          Cases Requiring Attention
        </Typography>
        
        {attentionCases.length === 0 ? (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <Typography variant="body1" color="text.secondary">
              No cases requiring immediate attention
            </Typography>
          </Box>
        ) : (
          <List>
            {attentionCases.map((caseItem, index) => (
              <div key={caseItem.id}>
                {index > 0 && <Divider />}
                <ListItem
                  sx={{
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    py: 2,
                    bgcolor: caseItem.deadline_info.is_overdue ? 'error.light' : 'transparent'
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', width: '100%', mb: 1 }}>
                    <Box sx={{ flex: 1 }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                        {caseItem.case_number}: {caseItem.title}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Status: {caseItem.status}
                      </Typography>
                    </Box>
                    <Chip
                      label={`${getStatusIcon(caseItem.deadline_info.status)} ${getStatusLabel(caseItem.deadline_info.status)}`}
                      color={getStatusColor(caseItem.deadline_info.status) as any}
                      sx={{ ml: 2 }}
                    />
                  </Box>

                  <Box sx={{ display: 'flex', gap: 2, mt: 1 }}>
                    <Typography variant="body2">
                      <strong>Days Remaining:</strong> {caseItem.deadline_info.days_remaining}
                    </Typography>
                    <Typography variant="body2">
                      <strong>Business Days:</strong> {caseItem.deadline_info.business_days_remaining}
                    </Typography>
                    <Typography variant="body2">
                      <strong>Deadline:</strong> {new Date(caseItem.deadline_info.deadline).toLocaleDateString()}
                    </Typography>
                  </Box>
                </ListItem>
              </div>
            ))}
          </List>
        )}
      </Paper>
    </Box>
  );
};

export default ReportingDashboard;
