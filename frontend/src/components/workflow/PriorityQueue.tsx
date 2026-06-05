/**
 * Priority Queue Component.
 *
 * Displays cases ordered by priority score.
 * Allows filtering by analyst, workflow stage, and clock status.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import LinearProgress from '@mui/material/LinearProgress';
import Tooltip from '@mui/material/Tooltip';
import QueueIcon from '@mui/icons-material/Queue';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline';
import RefreshIcon from '@mui/icons-material/Refresh';
import { queueApi, CasePriorityScore } from '../../api/workflowApi';

interface PriorityQueueProps {
  currentUserId?: string;
  users?: Array<{ id: string; name: string }>;
}

const WORKFLOW_STAGES = [
  { value: '', label: 'All Stages' },
  { value: 'intake', label: 'Intake' },
  { value: 'collection', label: 'Collection' },
  { value: 'review', label: 'Review' },
  { value: 'redaction', label: 'Redaction' },
  { value: 'approval', label: 'Approval' },
  { value: 'release', label: 'Release' },
  { value: 'pending_fee_payment', label: 'Pending Fee' },
  { value: 'privacy_commission_review', label: 'Privacy Commission' }
];

const PriorityQueue: React.FC<PriorityQueueProps> = ({ currentUserId, users = [] }) => {
  const navigate = useNavigate();
  const [cases, setCases] = useState<CasePriorityScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    analyst_id: '',
    workflow_stage: '',
    clock_status: '',
    include_closed: false
  });

  useEffect(() => {
    fetchQueue();
  }, [filters]);

  const fetchQueue = async () => {
    try {
      setLoading(true);
      setError(null);
      const params: any = { limit: 50 };
      if (filters.analyst_id) params.analyst_id = filters.analyst_id;
      if (filters.workflow_stage) params.workflow_stage = filters.workflow_stage;
      if (filters.clock_status) params.clock_status = filters.clock_status;
      if (filters.include_closed) params.include_closed = true;
      
      const data = await queueApi.getPrioritized(params);
      setCases(data);
    } catch (err: any) {
      setError('Failed to load priority queue');
      setCases([]);
    } finally {
      setLoading(false);
    }
  };

  const getPriorityColor = (score: number): 'error' | 'warning' | 'info' | 'success' => {
    if (score >= 80) return 'error';
    if (score >= 60) return 'warning';
    if (score >= 40) return 'info';
    return 'success';
  };

  const getDaysUntilDueDisplay = (days: number | undefined) => {
    if (days === undefined) return '-';
    if (days < 0) return <Chip size="small" label={`${Math.abs(days)}d OVERDUE`} color="error" />;
    if (days === 0) return <Chip size="small" label="DUE TODAY" color="warning" />;
    if (days <= 5) return <Chip size="small" label={`${days}d left`} color="warning" />;
    return `${days}d`;
  };

  const formatDate = (dateStr: string | undefined) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric'
    });
  };

  return (
    <Card>
      <CardHeader
        avatar={<QueueIcon />}
        title="Priority Queue"
        subheader="Cases ordered by priority score"
        action={
          <Button
            size="small"
            startIcon={<RefreshIcon />}
            onClick={fetchQueue}
            disabled={loading}
          >
            Refresh
          </Button>
        }
      />
      <CardContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Filters */}
        <Box display="flex" gap={2} mb={3} flexWrap="wrap">
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Analyst</InputLabel>
            <Select
              value={filters.analyst_id}
              onChange={(e) => setFilters({ ...filters, analyst_id: e.target.value })}
              label="Analyst"
            >
              <MenuItem value="">All Analysts</MenuItem>
              {currentUserId && <MenuItem value={currentUserId}>My Cases</MenuItem>}
              {users.map(user => (
                <MenuItem key={user.id} value={user.id}>{user.name}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Stage</InputLabel>
            <Select
              value={filters.workflow_stage}
              onChange={(e) => setFilters({ ...filters, workflow_stage: e.target.value })}
              label="Stage"
            >
              {WORKFLOW_STAGES.map(stage => (
                <MenuItem key={stage.value} value={stage.value}>{stage.label}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Clock</InputLabel>
            <Select
              value={filters.clock_status}
              onChange={(e) => setFilters({ ...filters, clock_status: e.target.value })}
              label="Clock"
            >
              <MenuItem value="">All</MenuItem>
              <MenuItem value="running">Running</MenuItem>
              <MenuItem value="paused">Paused</MenuItem>
            </Select>
          </FormControl>
        </Box>

        {loading ? (
          <Box display="flex" justifyContent="center" py={4}>
            <CircularProgress />
          </Box>
        ) : cases.length === 0 ? (
          <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
            No cases match the current filters.
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Priority</TableCell>
                <TableCell>Case</TableCell>
                <TableCell>Stage</TableCell>
                <TableCell>Due</TableCell>
                <TableCell>Age</TableCell>
                <TableCell>Docs</TableCell>
                <TableCell>Clock</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {cases.map((caseItem, index) => (
                <TableRow
                  key={caseItem.case_id}
                  hover
                  sx={{ cursor: 'pointer' }}
                  onClick={() => navigate(`/cases/${caseItem.case_id}`)}
                >
                  <TableCell>
                    <Box display="flex" alignItems="center" gap={1}>
                      <Typography variant="body2" fontWeight={600} sx={{ minWidth: 24 }}>
                        #{index + 1}
                      </Typography>
                      <Tooltip title={`Priority Score: ${caseItem.priority_score}`}>
                        <Box sx={{ width: 60 }}>
                          <LinearProgress
                            variant="determinate"
                            value={Math.min(caseItem.priority_score, 100)}
                            color={getPriorityColor(caseItem.priority_score)}
                            sx={{ height: 8, borderRadius: 1 }}
                          />
                        </Box>
                      </Tooltip>
                      {caseItem.priority_override && (
                        <Chip size="small" label="Override" variant="outlined" />
                      )}
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>
                      {caseItem.tracking_number}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ 
                      display: 'block',
                      maxWidth: 200,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap'
                    }}>
                      {caseItem.title}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={caseItem.workflow_stage || caseItem.status}
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell>
                    {getDaysUntilDueDisplay(caseItem.days_until_due)}
                  </TableCell>
                  <TableCell>{caseItem.case_age_days}d</TableCell>
                  <TableCell>{caseItem.document_count}</TableCell>
                  <TableCell>
                    {caseItem.clock_status === 'paused' ? (
                      <Tooltip title="Clock paused">
                        <PauseCircleOutlineIcon color="warning" fontSize="small" />
                      </Tooltip>
                    ) : (
                      <Typography variant="caption" color="success.main">●</Typography>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
};

export default PriorityQueue;
