import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/client';
import './CaseDetailView.css';
import ReleasePackageActions from './ReleasePackageActions';
import CaseTeamPanel from './CaseTeamPanel';
import CaseApprovalPanel from './CaseApprovalPanel';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import DescriptionIcon from '@mui/icons-material/Description';
import EmailIcon from '@mui/icons-material/Email';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import BlockIcon from '@mui/icons-material/Block';
// Workflow components
import {
  ClockManagement,
  ContributorsPanel,
  RecordsConfirmation,
  TransferCase
} from './workflow';

interface Case {
  id: string;
  tracking_number: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  assignee: string | null;
  team: string | null;
  category?: string;
  requester: {
    name: string;
    email: string;
    phone?: string;
    organization?: string;
  } | null;
  due_date: string;
  created_at: string;
  updated_at: string;
  tags: string[];
  comments: Comment[];
  audit_log: AuditEntry[];
  document_ids: string[];
}

interface Comment {
  id: string;
  author_name: string;
  text: string;
  type: string;
  created_at: string;
}

interface AuditEntry {
  action: string;
  user_name: string;
  timestamp: string;
  details: any;
}

const CaseDetailView: React.FC = () => {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [loading, setLoading] = useState(true);
  const [commentType, setCommentType] = useState<'internal' | 'public'>('internal');
  const [submittingComment, setSubmittingComment] = useState(false);
  const [availableUsers, setAvailableUsers] = useState<Array<{id: string, name: string, email: string, role: string}>>([]);
  const [collectionLinks, setCollectionLinks] = useState<Array<any>>([]);
  const [showLinkDialog, setShowLinkDialog] = useState(false);
  const [showAllActivity, setShowAllActivity] = useState(false);
  const [showAllDocuments, setShowAllDocuments] = useState(false);
  const [currentUserRole, setCurrentUserRole] = useState<string>('viewer');
  const [documents, setDocuments] = useState<Array<any>>([]);
  const [newComment, setNewComment] = useState('');
  const [categories, setCategories] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [saveIndicators, setSaveIndicators] = useState<Record<string, boolean>>({});
  const [newTag, setNewTag] = useState('');
  const [templates, setTemplates] = useState<Array<any>>([]);
  const [selectedTemplate, setSelectedTemplate] = useState('');

  const showSaveIndicator = (field: string) => {
    setSaveIndicators(prev => ({ ...prev, [field]: true }));
    setTimeout(() => {
      setSaveIndicators(prev => ({ ...prev, [field]: false }));
    }, 2000);
  };

  useEffect(() => {
    if (caseId) {
      fetchCase();
      fetchCollectionLinks();
      fetchDocuments();
      fetchUsers();
      fetchCategories();
      fetchTemplates();
    }
  }, [caseId]);

  const fetchCategories = async () => {
    try {
      const response = await api.get('/admin/config/public');
      setCategories(response.data.request_categories || []);
    } catch (error) {
      console.error('Error fetching categories:', error);
    }
  };

  const getFileIcon = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase();
    const iconProps = { fontSize: 'small' as const, style: { color: 'var(--text-secondary)' } };
    
    switch (ext) {
      case 'pdf':
        return <PictureAsPdfIcon {...iconProps} style={{ color: '#d32f2f' }} />;
      case 'doc':
      case 'docx':
        return <DescriptionIcon {...iconProps} style={{ color: '#2196f3' }} />;
      case 'eml':
      case 'msg':
        return <EmailIcon {...iconProps} style={{ color: '#ff9800' }} />;
      default:
        return <InsertDriveFileIcon {...iconProps} />;
    }
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    const duplicates: string[] = [];
    
    try {
      for (let i = 0; i < files.length; i++) {
        const formData = new FormData();
        formData.append('file', files[i]);
        formData.append('case_id', caseId!);

        const response = await api.post('/documents/', formData, {
          headers: {
            'Content-Type': 'multipart/form-data'
          }
        });
        
        // Track duplicates
        if (response.data.is_duplicate && response.data.duplicate_of_filename) {
          duplicates.push(`${files[i].name} (matches ${response.data.duplicate_of_filename})`);
        }
      }

      // Refresh documents list
      await fetchDocuments();
      
      // Show duplicate notification if any
      if (duplicates.length > 0) {
        alert(`Duplicate documents detected:\n\n${duplicates.join('\n')}\n\nThese files were not uploaded as they already exist.`);
      }
    } catch (error) {
      console.error('Error uploading documents:', error);
      alert('Failed to upload documents. Please try again.');
    } finally {
      setUploading(false);
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };


  const fetchDocuments = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await api.get(`/cases/${caseId}/documents`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setDocuments(response.data.documents || []);
    } catch (error) {
      console.error('Error fetching documents:', error);
    }
  };

  const fetchUsers = async () => {
    try {
      const response = await api.get('/auth/users/assignable');
      setAvailableUsers(response.data);
    } catch (error) {
      console.error('Error fetching assignable users:', error);
    }
  };

  const fetchCollectionLinks = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await api.get(`/cases/${caseId}/collection-links`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setCollectionLinks(response.data.links || []);
    } catch (error) {
      console.error('Error fetching collection links:', error);
    }
  };

  const createCollectionLink = async () => {
    try {
      const token = localStorage.getItem('token');
      await api.post(
        `/cases/${caseId}/collection-links`,
        { case_id: caseId },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      fetchCollectionLinks();
      setShowLinkDialog(false);
    } catch (error) {
      console.error('Error creating collection link:', error);
    }
  };

  const copyLinkToClipboard = (url: string) => {
    const fullUrl = `${window.location.origin}${url}`;
    navigator.clipboard.writeText(fullUrl);
  };

  const deactivateLink = async (linkId: string) => {
    if (!window.confirm('Are you sure you want to deactivate this link?')) return;
    
    try {
      const token = localStorage.getItem('token');
      await api.delete(
        `/cases/${caseId}/collection-links/${linkId}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      fetchCollectionLinks();
    } catch (error) {
      console.error('Error deactivating link:', error);
    }
  };

  const fetchCase = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await api.get(`/cases/${caseId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setCaseData(response.data);
      
      // Get current user's role from case team
      const devUserId = localStorage.getItem('dev_current_user') || localStorage.getItem('userId') || '';
      const caseTeam = response.data.case_team || [];
      const currentMember = caseTeam.find((m: any) => m.user_id === devUserId && m.status === 'active');
      setCurrentUserRole(currentMember?.role || 'viewer');
    } catch (error) {
      console.error('Error fetching case:', error);
    } finally {
      setLoading(false);
    }
  };

  const updateStatus = async (newStatus: string) => {
    try {
      const token = localStorage.getItem('token');
      await api.put(
        `/cases/${caseId}/status`,
        JSON.stringify(newStatus),  // Send as JSON string
        { 
          headers: { 
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json'
          } 
        }
      );
      fetchCase();
      showSaveIndicator('status');
    } catch (error) {
      console.error('Error updating status:', error);
    }
  };

  const updatePriority = async (newPriority: string) => {
    try {
      const token = localStorage.getItem('token');
      await api.put(
        `/cases/${caseId}`,
        { priority: newPriority },
        {
          headers: { Authorization: `Bearer ${token}` }
        }
      );
      setCaseData((prevCaseData) => prevCaseData ? { ...prevCaseData, priority: newPriority } : null);
      showSaveIndicator('priority');
    } catch (error) {
      console.error('Error updating priority:', error);
    }
  };

  const updateCaseField = async (field: string, value: any) => {
    try {
      const token = localStorage.getItem('token');
      await api.put(
        `/cases/${caseId}`,
        { [field]: value },
        {
          headers: { Authorization: `Bearer ${token}` }
        }
      );
      setCaseData((prevCaseData) => prevCaseData ? { ...prevCaseData, [field]: value } : null);
      showSaveIndicator(field);
    } catch (error) {
      console.error(`Error updating ${field}:`, error);
    }
  };

  const assignCase = async (userId: string) => {
    try {
      const token = localStorage.getItem('token');
      await api.put(
        `/cases/${caseId}/assign`,
        { assignee: userId },
        {
          headers: { Authorization: `Bearer ${token}` }
        }
      );
      fetchCase();
      showSaveIndicator('assignee');
    } catch (error) {
      console.error('Error assigning case:', error);
    }
  };

  const deleteCase = async () => {
    if (!window.confirm('Are you sure you want to delete this case? This action cannot be undone.')) {
      return;
    }
    
    try {
      const token = localStorage.getItem('token');
      await api.delete(
        `/cases/${caseId}`,
        {
          headers: { Authorization: `Bearer ${token}` }
        }
      );
      alert('Case deleted successfully');
      navigate('/cases');
    } catch (error) {
      console.error('Error deleting case:', error);
      alert('Failed to delete case');
    }
  };

  const fetchTemplates = async () => {
    try {
      const response = await api.get('/templates/', {
        params: { active_only: true }
      });
      setTemplates(response.data);
    } catch (error) {
      console.error('Error fetching templates:', error);
    }
  };

  const applyTemplate = async (templateId: string) => {
    if (!templateId) return;
    
    try {
      const response = await api.post(`/templates/${templateId}/render`, null, {
        params: { case_id: caseId }
      });
      setNewComment(response.data.rendered_content);
      setSelectedTemplate(''); // Reset dropdown
    } catch (error) {
      console.error('Error applying template:', error);
    }
  };

  const addComment = async () => {
    if (!newComment.trim()) return;

    setSubmittingComment(true);
    try {
      const token = localStorage.getItem('token');
      await api.post(
        `/cases/${caseId}/comments`,
        { text: newComment, type: commentType },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setNewComment('');
      setSelectedTemplate('');
      fetchCase();
    } catch (error) {
      console.error('Error adding comment:', error);
    } finally {
      setSubmittingComment(false);
    }
  };

  const formatDate = (dateString: string | null | undefined) => {
    if (!dateString) return 'Not set';
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return 'Invalid Date';
    // Use regional date format
    return date.toLocaleDateString();
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      new: 'var(--color-primary)',
      in_progress: '#ffc107',
      review: '#fd7e14',
      on_hold: '#6c757d',
      completed: 'var(--color-success)',
      closed: '#343a40'
    };
    return colors[status] || '#6c757d';
  };

  const getPriorityColor = (priority: string) => {
    const colors: Record<string, string> = {
      high: 'var(--color-danger)',
      medium: '#ffc107',
      low: 'var(--color-success)'
    };
    return colors[priority] || '#6c757d';
  };

  if (loading) {
    return <div className="loading">Loading case...</div>;
  }

  if (!caseData) {
    return <div className="error">Case not found</div>;
  }

  const userRole = localStorage.getItem('userRole');

  return (
    <div className="case-detail-container">
      <div className="case-detail-header">
        <button onClick={() => navigate('/cases')} className="btn-back">
          ← Back to Queue
        </button>
        {userRole === 'admin' && (
          <button 
            onClick={deleteCase}
            style={{
              padding: '8px 16px',
              backgroundColor: 'var(--color-danger)',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '500',
              marginLeft: 'auto'
            }}
          >
            Delete Case
          </button>
        )}
      </div>

      {/* Approval Banner - Show when case needs approval */}
      {(caseData.status === 'review' || caseData.status === 'completed') && (
        <div className="approval-banner">
          <div className="banner-icon">⚠️</div>
          <div className="banner-content">
            <div className="banner-title">
              {caseData.status === 'review' ? 'Pending Review' : 'Pending Final Approval'}
            </div>
            <div className="banner-message">
              {caseData.status === 'review' 
                ? 'This case is awaiting review before release.'
                : 'This case is awaiting final approval. Only Approvers and Managers can approve cases for release.'}
            </div>
          </div>
        </div>
      )}

      <div className="case-detail-layout">
        {/* Left Column - Main Content */}
        <div className="case-main-content">
          <div className="case-title-section">
            <h1>{caseData.title}</h1>
            <div className="tracking-number">{caseData.tracking_number}</div>
          </div>

          {/* MVP3 Actions Toolbar - Moved to top */}
          <div className="mvp3-actions-toolbar" style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-default)',
            borderRadius: '8px',
            padding: '20px',
            marginBottom: '24px'
          }}>
            <div style={{
              color: 'var(--text-secondary)',
              fontSize: '12px',
              fontWeight: '600', 
              marginBottom: '12px',
              textTransform: 'uppercase',
              letterSpacing: '0.5px'
            }}>
              Quick Actions
            </div>
            <div style={{ 
              display: 'grid', 
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', 
              gap: '12px'
            }}>
              <ReleasePackageActions 
                caseId={caseId!} 
                caseNumber={caseData.tracking_number}
                documents={documents}
              />
            </div>
          </div>

          {/* Workflow Status Components */}
          <ClockManagement 
            caseId={caseId!} 
            dueDate={caseData.due_date}
            onClockChange={() => fetchCase()}
          />
          <RecordsConfirmation 
            caseId={caseId!}
            onConfirmationChange={() => fetchCase()}
          />

          {/* Documents Section with Button */}
          <div className="documents-section">
            <div className="documents-header-row">
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <h3>Documents</h3>
                <span className="document-count">{documents.length} document{documents.length !== 1 ? 's' : ''}</span>
              </div>
              <button
                onClick={() => navigate(`/cases/${caseId}/documents`)}
                className="btn-view-all-docs"
              >
                View All Documents →
              </button>
            </div>
            {documents.length > 0 ? (
              <div className="documents-preview">
                {documents.slice(0, 3).map((doc: any) => (
                  <div key={doc.id} className="document-preview-item">
                    <span className="doc-icon">{getFileIcon(doc.filename)}</span>
                    <span className="doc-name">{doc.filename}</span>
                    <span className="doc-size">
                      {doc.size ? `${(doc.size / 1024).toFixed(0)} KB` : ''}
                    </span>
                  </div>
                ))}
                {documents.length > 3 && (
                  <div className="more-docs">
                    +{documents.length - 3} more documents
                  </div>
                )}
              </div>
            ) : (
              <div style={{
                padding: '30px',
                textAlign: 'center',
                color: 'var(--text-secondary)',
                fontSize: '14px'
              }}>
                No documents uploaded yet
              </div>
            )}
          </div>

          <div className="case-description-section">
            <h3>Description</h3>
            <p>{caseData.description}</p>
          </div>

          {caseData.requester && (
            <div className="requester-section">
              <h3>Requester Information</h3>
              <div className="requester-details">
                <div className="detail-row">
                  <span className="label">Name:</span>
                  <span className="value">{caseData.requester.name}</span>
                </div>
                <div className="detail-row">
                  <span className="label">Email:</span>
                  <span className="value">{caseData.requester.email}</span>
                </div>
                {caseData.requester.phone && (
                  <div className="detail-row">
                    <span className="label">Phone:</span>
                    <span className="value">{caseData.requester.phone}</span>
                  </div>
                )}
                {caseData.requester.organization && (
                  <div className="detail-row">
                    <span className="label">Organization:</span>
                    <span className="value">{caseData.requester.organization}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Comments Section */}
          <div className="comments-section">
            <h3>Comments & Activity</h3>
            
            <div className="add-comment">
              <div className="comment-type-toggle">
                <button
                  className={commentType === 'internal' ? 'active' : ''}
                  onClick={() => setCommentType('internal')}
                >
                  Internal
                </button>
                <button
                  className={commentType === 'public' ? 'active' : ''}
                  onClick={() => setCommentType('public')}
                >
                  Public
                </button>
              </div>
              
              {commentType === 'public' && templates.length > 0 && (
                <div style={{ marginBottom: '10px' }}>
                  <label htmlFor="template-select" style={{ display: 'block', marginBottom: '5px', fontSize: '14px', color: 'var(--text-secondary)' }}>
                    Use a template (optional):
                  </label>
                  <select
                    id="template-select"
                    value={selectedTemplate}
                    onChange={(e) => {
                      setSelectedTemplate(e.target.value);
                      applyTemplate(e.target.value);
                    }}
                    style={{
                      width: '100%',
                      padding: '8px',
                      border: '1px solid var(--border-input)',
                      borderRadius: '4px',
                      fontSize: '14px'
                    }}
                  >
                    <option value="">-- Select a template --</option>
                    {templates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name} ({template.category})
                      </option>
                    ))}
                  </select>
                </div>
              )}
              
              <textarea
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                placeholder={`Add ${commentType} comment...`}
                rows={commentType === 'public' ? 8 : 4}
              />
              <button
                onClick={addComment}
                disabled={submittingComment || !newComment.trim()}
                className="btn-add-comment"
              >
                {submittingComment ? 'Adding...' : 'Add Comment'}
              </button>
            </div>

            <div className="comments-list">
              {caseData.comments.map((comment) => (
                <div key={comment.id} className={`comment-item ${comment.type}`}>
                  <div className="comment-header">
                    <span className="comment-author">{comment.author_name}</span>
                    <span className="comment-type-badge">{comment.type.toUpperCase()}</span>
                    {comment.created_at && (
                      <span className="comment-date">{formatDate(comment.created_at)}</span>
                    )}
                  </div>
                  <div className="comment-text">{comment.text}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Case Team */}
          <div style={{ marginBottom: '24px' }}>
            <CaseTeamPanel 
              caseId={caseId!} 
              canManageTeam={true}
            />
          </div>

          {/* Case Approval */}
          <div style={{ marginBottom: '24px' }}>
            <CaseApprovalPanel 
              caseId={caseId!} 
              userRole={currentUserRole}
            />
          </div>

          {/* Activity Log */}
          <div className="activity-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3>Activity Log</h3>
              {caseData.audit_log.length > 5 && (
                <button
                  onClick={() => setShowAllActivity(!showAllActivity)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                    fontSize: '14px',
                    fontWeight: '600'
                  }}
                >
                  {showAllActivity ? 'Show Less' : `Show All (${caseData.audit_log.length})`}
                </button>
              )}
            </div>
            <div className="activity-list">
              {[...caseData.audit_log]
                .reverse()
                .slice(0, showAllActivity ? undefined : 5)
                .map((entry, idx) => (
                  <div key={idx} className="activity-item">
                    <div className="activity-icon">•</div>
                    <div className="activity-content">
                      <div className="activity-text">
                        <strong>{entry.user_name}</strong> {entry.action.replace('_', ' ')}
                      </div>
                      <div className="activity-date">{formatDate(entry.timestamp)}</div>
                    </div>
                  </div>
                ))}
            </div>
          </div>

          {/* Collaboration Components */}
          <div style={{ marginTop: '24px' }}>
            <ContributorsPanel caseId={caseId!} />
          </div>

          <div style={{ marginTop: '24px' }}>
            <TransferCase 
              caseId={caseId!}
              caseTitle={caseData.title}
            />
          </div>
        </div>

        {/* Right Column - Metadata */}
        <div className="case-sidebar">
          <div className="sidebar-section">
            <label>
              Status
              {saveIndicators.status && (
                <span className="save-indicator">
                  <CheckCircleOutlineIcon fontSize="small" /> Saved
                </span>
              )}
            </label>
            <select
              value={caseData.status}
              onChange={(e) => updateStatus(e.target.value)}
              style={{ backgroundColor: getStatusColor(caseData.status) }}
              className="status-select"
            >
              <option value="new">New</option>
              <option value="in_progress">In Progress</option>
              <option value="review">Review</option>
              <option value="on_hold">On Hold</option>
              <option value="completed">Completed</option>
              <option value="closed">Closed</option>
            </select>
          </div>

          <div className="sidebar-section">
            <label>
              Priority
              {saveIndicators.priority && (
                <span className="save-indicator">
                  <CheckCircleOutlineIcon fontSize="small" /> Saved
                </span>
              )}
            </label>
            <select
              value={caseData.priority}
              onChange={(e) => updatePriority(e.target.value)}
              style={{ backgroundColor: getPriorityColor(caseData.priority) }}
              className="priority-select"
            >
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          <div className="sidebar-section">
            <label>
              Assignee
              {saveIndicators.assignee && (
                <span className="save-indicator">
                  <CheckCircleOutlineIcon fontSize="small" /> Saved
                </span>
              )}
            </label>
            <select
              value={caseData.assignee || ''}
              onChange={(e) => assignCase(e.target.value)}
              className="assignee-select"
            >
              <option value="">Unassigned</option>
              {availableUsers.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name || user.email} ({user.role})
                </option>
              ))}
            </select>
          </div>

          <div className="sidebar-section">
            <label>Category</label>
            {categories.length > 0 ? (
              <select
                value={caseData.category || ''}
                onChange={(e) => updateCaseField('category', e.target.value || null)}
                style={{
                  width: '100%',
                  padding: '8px',
                  border: '1px solid var(--border-input)',
                  borderRadius: '4px',
                  fontSize: '14px'
                }}
              >
                <option value="">No category</option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            ) : (
              <div className="value" style={{
                padding: '8px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-input)',
                borderRadius: '4px',
                fontSize: '14px',
                color: caseData.category ? 'var(--text-primary)' : 'var(--text-secondary)'
              }}>
                {caseData.category || 'No category'}
              </div>
            )}
          </div>

          <div className="sidebar-section">
            <label>Due Date</label>
            <input
              type="date"
              value={caseData.due_date ? new Date(caseData.due_date).toISOString().slice(0, 10) : ''}
              onChange={async (e) => {
                const newDate = e.target.value || null;
                await updateCaseField('due_date', newDate);
              }}
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid var(--border-input)',
                borderRadius: '4px',
                fontSize: '14px'
              }}
            />
          </div>

          <div className="sidebar-section">
            <label>Created</label>
            <div className="value">{formatDate(caseData.created_at)}</div>
          </div>

          <div className="sidebar-section">
            <label>Last Updated</label>
            <div className="value">{formatDate(caseData.updated_at)}</div>
          </div>

          <div className="sidebar-section">
            <label>Tags</label>
            <div className="tags-list">
              {caseData.tags.length > 0 ? (
                caseData.tags.map((tag, idx) => (
                  <span key={idx} className="tag">
                    {tag}
                    <button
                      onClick={async () => {
                        const newTags = caseData.tags.filter((_, i) => i !== idx);
                        await updateCaseField('tags', newTags);
                      }}
                      style={{
                        marginLeft: '6px',
                        background: 'none',
                        border: 'none',
                        color: 'inherit',
                        cursor: 'pointer',
                        fontSize: '12px',
                        opacity: 0.7
                      }}
                      title="Remove tag"
                    >
                      ×
                    </button>
                  </span>
                ))
              ) : (
                <span className="no-tags">No tags</span>
              )}
            </div>
            <div style={{ marginTop: '8px', display: 'flex', gap: '4px' }}>
              <input
                type="text"
                placeholder="Add tag..."
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                onKeyPress={async (e) => {
                  if (e.key === 'Enter' && newTag.trim()) {
                    const tagToAdd = newTag.trim();
                    if (!caseData.tags.includes(tagToAdd)) {
                      await updateCaseField('tags', [...caseData.tags, tagToAdd]);
                      setNewTag('');
                    }
                  }
                }}
                style={{
                  flex: 1,
                  padding: '6px 8px',
                  border: '1px solid var(--border-input)',
                  borderRadius: '4px',
                  fontSize: '13px'
                }}
              />
            </div>
          </div>

          <div className="sidebar-section">
            <label>Documents</label>
            <div className="value">{documents.length} document{documents.length !== 1 ? 's' : ''}</div>
          </div>

          <div className="sidebar-section">
            <label>Collection Links</label>
            <div className="value">{collectionLinks.length} active links</div>
            <button
              onClick={() => setShowLinkDialog(true)}
              className="btn-view-docs"
              style={{ marginTop: '10px' }}
            >
              + Create Link
            </button>
            {collectionLinks.length > 0 && (
              <div style={{ marginTop: '15px' }}>
                {collectionLinks.map((link: any) => (
                  <div key={link.id} className="collection-link-item">
                    <div className="link-info">
                      <span className="link-uploads">{link.upload_count} uploads</span>
                      {!link.is_active && <span className="link-inactive">Inactive</span>}
                    </div>
                    <div className="link-actions">
                      <button
                        onClick={() => copyLinkToClipboard(link.url)}
                        className="btn-link-action"
                        title="Copy link"
                      >
                        <ContentCopyIcon fontSize="small" />
                      </button>
                      {link.is_active && (
                        <button
                          onClick={() => deactivateLink(link.id)}
                          className="btn-link-action"
                          title="Deactivate"
                        >
                          <BlockIcon fontSize="small" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Create Link Dialog */}
      {showLinkDialog && (
        <div className="dialog-overlay" onClick={() => setShowLinkDialog(false)}>
          <div className="dialog-content" onClick={(e) => e.stopPropagation()}>
            <h3>Create Collection Link</h3>
            <p>Create a secure link for external users to upload documents to this case.</p>
            <div className="dialog-actions">
              <button onClick={() => setShowLinkDialog(false)} className="btn-cancel">
                Cancel
              </button>
              <button onClick={createCollectionLink} className="btn-create">
                Create Link
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CaseDetailView;
