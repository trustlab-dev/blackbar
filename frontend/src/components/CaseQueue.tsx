import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import './CaseQueue.css';
import { useUser } from '../contexts/UserContext';
import FiberNewIcon from '@mui/icons-material/FiberNew';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import RateReviewIcon from '@mui/icons-material/RateReview';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ArchiveIcon from '@mui/icons-material/Archive';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import AddIcon from '@mui/icons-material/Add';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import Alert from '@mui/material/Alert';

interface Case {
  id: string;
  tracking_number: string;
  title: string;
  status: string;
  priority: string;
  assignee: string | null;
  category?: string;
  requester: {
    name: string;
    email: string;
  } | null;
  due_date: string;
  sla_status?: string;
  created_at: string;
  tags: string[];
}

const CaseQueue: React.FC = () => {
  const navigate = useNavigate();
  const { currentRole } = useUser();
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit] = useState(50);

  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  // Sorting
  const [sortBy, setSortBy] = useState<string>('due_date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  // Admins see all cases by default, others see only their cases
  // Initialize from localStorage to avoid race condition
  const [viewMode, setViewMode] = useState<'all' | 'my'>(() => {
    const storedRole = localStorage.getItem('userRole');
    return storedRole === 'admin' ? 'all' : 'my';
  });

  // Create Case Modal State
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [newCase, setNewCase] = useState({
    title: '',
    description: '',
    category: '',
    priority: 'medium',
    requester_name: '',
    requester_email: '',
    requester_phone: '',
    requester_organization: ''
  });

  // Fetch categories for Create Case dropdown
  useEffect(() => {
    const fetchCategories = async () => {
      try {
        const response = await api.get('/admin/config/public');
        setCategories(response.data.request_categories || []);
      } catch (err) {
        console.log('Could not load categories');
      }
    };
    fetchCategories();
  }, []);

  useEffect(() => {
    fetchCases();
  }, [page, statusFilter, priorityFilter, searchQuery, viewMode, sortBy, sortOrder]);

  const fetchCases = async () => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('token');
      const endpoint = viewMode === 'my' ? '/cases/queue/my-cases' : '/cases/queue/all';

      const params: any = {
        skip: page * limit,
        limit: limit,
        sort_by: sortBy,
        sort_order: sortOrder
      };

      if (statusFilter) params.status = statusFilter;
      if (priorityFilter) params.priority = priorityFilter;
      if (searchQuery) params.search = searchQuery;

      const response = await api.get(endpoint, {
        params,
        headers: { Authorization: `Bearer ${token}` }
      });

      setCases(response.data.cases);
      setTotal(response.data.total);
    } catch (error: any) {
      console.error('Error fetching cases:', error);
      // Handle authentication errors explicitly
      if (error.response?.status === 401) {
        // Clear auth data and redirect to login
        localStorage.removeItem('token');
        localStorage.removeItem('userRole');
        localStorage.removeItem('username');
        window.location.href = '/login';
        return;
      }
      // For other errors, set error state and empty cases
      setError('Failed to load cases. Please try again.');
      setCases([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  const getStatusIcon = (status: string) => {
    const iconProps = { fontSize: 'small' as const, style: { marginRight: '6px' } };
    switch (status) {
      case 'new': return <FiberNewIcon {...iconProps} />;
      case 'in_progress': return <HourglassEmptyIcon {...iconProps} />;
      case 'review': return <RateReviewIcon {...iconProps} />;
      case 'on_hold': return <PauseCircleIcon {...iconProps} />;
      case 'completed': return <CheckCircleIcon {...iconProps} />;
      case 'closed': return <ArchiveIcon {...iconProps} />;
      default: return null;
    }
  };

  const getStatusStyle = (status: string) => {
    const styles: Record<string, { bg: string; border: string; color: string }> = {
      new: { bg: '#e3f2fd', border: '#90caf9', color: '#1565c0' },
      in_progress: { bg: '#fff3e0', border: '#ffb74d', color: '#e65100' },
      review: { bg: '#ffe0b2', border: '#ff9800', color: '#e65100' },
      on_hold: { bg: '#f5f5f5', border: '#bdbdbd', color: '#616161' },
      completed: { bg: '#e8f5e9', border: '#81c784', color: '#2e7d32' },
      closed: { bg: '#eeeeee', border: '#9e9e9e', color: '#424242' }
    };
    return styles[status] || styles.on_hold;
  };

  const getPriorityStyle = (priority: string) => {
    const styles: Record<string, { bg: string; border: string; color: string }> = {
      high: { bg: '#ffebee', border: '#ef5350', color: '#c62828' },
      medium: { bg: '#fff3e0', border: '#ffb74d', color: '#e65100' },
      low: { bg: '#e8f5e9', border: '#81c784', color: '#2e7d32' }
    };
    return styles[priority] || styles.medium;
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffTime = date.getTime() - now.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays < 0) {
      return `${Math.abs(diffDays)} days overdue`;
    } else if (diffDays === 0) {
      return 'Due today';
    } else if (diffDays <= 7) {
      return `${diffDays} days left`;
    } else {
      return date.toLocaleDateString();
    }
  };

  const getSLAClass = (slaStatus?: string) => {
    if (slaStatus === 'overdue') return 'sla-overdue';
    if (slaStatus === 'due_soon') return 'sla-due-soon';
    return 'sla-on-track';
  };

  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(column);
      setSortOrder('asc');
    }
  };

  const renderSortIcon = (column: string) => {
    if (sortBy !== column) return null;
    return sortOrder === 'asc' ? (
      <ArrowUpwardIcon fontSize="small" style={{ fontSize: '14px', marginLeft: '4px' }} />
    ) : (
      <ArrowDownwardIcon fontSize="small" style={{ fontSize: '14px', marginLeft: '4px' }} />
    );
  };

  const handleCreateCase = async () => {
    setCreateLoading(true);
    setCreateError(null);
    try {
      const payload = {
        title: newCase.title,
        description: newCase.description,
        category: newCase.category || undefined,
        priority: newCase.priority,
        requester: {
          name: newCase.requester_name,
          email: newCase.requester_email,
          phone: newCase.requester_phone || undefined,
          organization: newCase.requester_organization || undefined
        }
      };
      const response = await api.post('/cases/', payload);
      setCreateDialogOpen(false);
      setNewCase({
        title: '',
        description: '',
        category: '',
        priority: 'medium',
        requester_name: '',
        requester_email: '',
        requester_phone: '',
        requester_organization: ''
      });
      // Navigate to the new case
      navigate(`/cases/${response.data.id}`);
    } catch (err: any) {
      setCreateError(err.response?.data?.detail || 'Failed to create case');
    } finally {
      setCreateLoading(false);
    }
  };

  return (
    <div className="case-queue-container">
      <div className="queue-header">
        <h1>Case Queue</h1>
        <div className="view-toggle">
          <button
            className={`view-tab ${viewMode === 'my' ? 'active' : ''}`}
            onClick={() => setViewMode('my')}
          >
            <span className="tab-indicator" />
            My Cases
          </button>
          {currentRole === 'admin' && (
            <button
              className={`view-tab ${viewMode === 'all' ? 'active' : ''}`}
              onClick={() => setViewMode('all')}
            >
              <span className="tab-indicator" />
              All Cases
            </button>
          )}
        </div>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreateDialogOpen(true)}
          sx={{ ml: 2 }}
        >
          Create Case
        </Button>
      </div>

      <div className="queue-filters">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search by title, tracking number..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All Statuses</option>
          <option value="new">New</option>
          <option value="in_progress">In Progress</option>
          <option value="review">Review</option>
          <option value="on_hold">On Hold</option>
          <option value="completed">Completed</option>
          <option value="closed">Closed</option>
        </select>

        <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
          <option value="">All Priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        <button onClick={fetchCases} className="btn-refresh">
          ↻ Refresh
        </button>
      </div>

      {loading ? (
        <div className="loading">Loading cases...</div>
      ) : error ? (
        <div className="error-container">
          <div className="error-message">{error}</div>
          <button onClick={fetchCases} className="btn-retry">
            Try Again
          </button>
        </div>
      ) : (
        <>
          <div className="cases-table">
            <table>
              <thead>
                <tr>
                  <th className="sortable" onClick={() => handleSort('tracking_number')}>
                    Tracking # {renderSortIcon('tracking_number')}
                  </th>
                  <th className="sortable" onClick={() => handleSort('title')}>
                    Title {renderSortIcon('title')}
                  </th>
                  <th>Category</th>
                  <th>Assignee</th>
                  <th>Requester</th>
                  <th className="sortable" onClick={() => handleSort('status')}>
                    Status {renderSortIcon('status')}
                  </th>
                  <th className="sortable" onClick={() => handleSort('priority')}>
                    Priority {renderSortIcon('priority')}
                  </th>
                  <th className="sortable" onClick={() => handleSort('due_date')}>
                    Due Date {renderSortIcon('due_date')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {cases.map((caseItem) => (
                  <tr
                    key={caseItem.id}
                    onClick={() => navigate(`/cases/${caseItem.id}`)}
                    className="case-row"
                  >
                    <td>
                      <span className="tracking-number">{caseItem.tracking_number}</span>
                    </td>
                    <td>
                      <div className="case-title">{caseItem.title}</div>
                    </td>
                    <td>
                      {caseItem.category ? (
                        <span className="category-badge">{caseItem.category}</span>
                      ) : (
                        <span className="no-category">—</span>
                      )}
                    </td>
                    <td>
                      {caseItem.assignee ? (
                        <span className="assignee-name">{caseItem.assignee}</span>
                      ) : (
                        <span className="no-assignee">Unassigned</span>
                      )}
                    </td>
                    <td>
                      {caseItem.requester ? (
                        <div className="requester-info">
                          <div>{caseItem.requester.name}</div>
                          <div className="requester-email">{caseItem.requester.email}</div>
                        </div>
                      ) : (
                        <span className="no-requester">—</span>
                      )}
                    </td>
                    <td>
                      <div className="status-cell">
                        <div
                          className="status-indicator"
                          style={{ backgroundColor: getStatusStyle(caseItem.status).border }}
                        />
                        <span
                          className="status-badge"
                          style={{
                            backgroundColor: getStatusStyle(caseItem.status).bg,
                            borderColor: getStatusStyle(caseItem.status).border,
                            color: getStatusStyle(caseItem.status).color
                          }}
                        >
                          {getStatusIcon(caseItem.status)}
                          {caseItem.status.replace('_', ' ')}
                        </span>
                      </div>
                    </td>
                    <td>
                      <span
                        className="priority-badge"
                        style={{
                          backgroundColor: getPriorityStyle(caseItem.priority).bg,
                          borderColor: getPriorityStyle(caseItem.priority).border,
                          color: getPriorityStyle(caseItem.priority).color
                        }}
                      >
                        {caseItem.priority}
                      </span>
                    </td>
                    <td>
                      <span className={`due-date ${getSLAClass(caseItem.sla_status)}`}>
                        {formatDate(caseItem.due_date)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              Previous
            </button>
            <span>
              Page {page + 1} of {Math.ceil(total / limit)}
            </span>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={(page + 1) * limit >= total}
            >
              Next
            </button>
          </div>
        </>
      )}

      {/* Create Case Dialog */}
      <Dialog open={createDialogOpen} onClose={() => setCreateDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create New Case</DialogTitle>
        <DialogContent>
          {createError && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setCreateError(null)}>
              {createError}
            </Alert>
          )}
          <TextField
            autoFocus
            margin="dense"
            label="Request Title"
            fullWidth
            required
            value={newCase.title}
            onChange={(e) => setNewCase({ ...newCase, title: e.target.value })}
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Description"
            fullWidth
            multiline
            rows={3}
            required
            value={newCase.description}
            onChange={(e) => setNewCase({ ...newCase, description: e.target.value })}
            sx={{ mb: 2 }}
          />
          <TextField
            select
            margin="dense"
            label="Category"
            fullWidth
            value={newCase.category}
            onChange={(e) => setNewCase({ ...newCase, category: e.target.value })}
            sx={{ mb: 2 }}
          >
            <MenuItem value="">None</MenuItem>
            {categories.map((cat) => (
              <MenuItem key={cat} value={cat}>{cat}</MenuItem>
            ))}
          </TextField>
          <TextField
            select
            margin="dense"
            label="Priority"
            fullWidth
            value={newCase.priority}
            onChange={(e) => setNewCase({ ...newCase, priority: e.target.value })}
            sx={{ mb: 2 }}
          >
            <MenuItem value="low">Low</MenuItem>
            <MenuItem value="medium">Medium</MenuItem>
            <MenuItem value="high">High</MenuItem>
          </TextField>

          <DialogTitle sx={{ px: 0, pt: 2 }}>Requester Information</DialogTitle>
          <TextField
            margin="dense"
            label="Requester Name"
            fullWidth
            required
            value={newCase.requester_name}
            onChange={(e) => setNewCase({ ...newCase, requester_name: e.target.value })}
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Requester Email"
            type="email"
            fullWidth
            required
            value={newCase.requester_email}
            onChange={(e) => setNewCase({ ...newCase, requester_email: e.target.value })}
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Phone (Optional)"
            fullWidth
            value={newCase.requester_phone}
            onChange={(e) => setNewCase({ ...newCase, requester_phone: e.target.value })}
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Organization (Optional)"
            fullWidth
            value={newCase.requester_organization}
            onChange={(e) => setNewCase({ ...newCase, requester_organization: e.target.value })}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateCase}
            variant="contained"
            disabled={createLoading || !newCase.title || !newCase.description || !newCase.requester_name || !newCase.requester_email}
          >
            {createLoading ? 'Creating...' : 'Create Case'}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export default CaseQueue;
