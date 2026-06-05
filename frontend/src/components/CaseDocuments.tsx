import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/client';
import DownloadIcon from '@mui/icons-material/Download';
import ShareIcon from '@mui/icons-material/Share';
import DeleteIcon from '@mui/icons-material/Delete';
import CloseIcon from '@mui/icons-material/Close';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import WarningIcon from '@mui/icons-material/Warning';
import ErrorIcon from '@mui/icons-material/Error';
import DescriptionIcon from '@mui/icons-material/Description';
import FolderIcon from '@mui/icons-material/Folder';
import ComputerIcon from '@mui/icons-material/Computer';
import AddIcon from '@mui/icons-material/Add';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import EmailIcon from '@mui/icons-material/Email';
import ArticleIcon from '@mui/icons-material/Article';
import TableChartIcon from '@mui/icons-material/TableChart';
import SlideshowIcon from '@mui/icons-material/Slideshow';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import './CaseDocuments.css';

// API_BASE_URL not needed - api client already has baseURL configured

interface Document {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  upload_date?: string;
  uploaded_at?: string; // Legacy field
  uploaded_by: string;
  uploaded_by_name?: string;
  submitter_name?: string;
  submitter_email?: string;
  collection_link_id?: string;
  status?: string;
  processing_status?: string;
  is_duplicate?: boolean;
  duplicate_of?: string;
  thread_status?: 'active' | 'superseded' | 'pending';
  superseded_by?: string;
  superseded_by_filename?: string;
  mime_type?: string;
  original_mime_type?: string;
  message_id?: string;
  has_attachments?: boolean;
  total_attachments?: number;
}

interface Attachment {
  id: string;
  filename: string;
  mime_type: string;
  size: number;
  upload_date: string;
}

const DOCUMENT_STATUSES = [
  { value: 'new', label: 'New', color: '#6c757d' },
  { value: 'under_review', label: 'Under Review', color: '#0dcaf0' },
  { value: 'redaction_required', label: 'Redaction Required', color: '#ffc107' },
  { value: 'redaction_in_progress', label: 'Redaction In Progress', color: '#fd7e14' },
  { value: 'ready_for_approval', label: 'Ready for Approval', color: '#20c997' },
  { value: 'approved', label: 'Approved', color: 'var(--color-success)' },
  { value: 'released', label: 'Released', color: '#0d6efd' },
  { value: 'withheld', label: 'Withheld', color: 'var(--color-danger)' }
];

const getStatusInfo = (status: string) => {
  return DOCUMENT_STATUSES.find(s => s.value === status) || DOCUMENT_STATUSES[0];
};

const CaseDocuments: React.FC = () => {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [caseTitle, setCaseTitle] = useState('');
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<'name' | 'date' | 'size'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [bulkStatus, setBulkStatus] = useState<string>('');
  const [shareDialogOpen, setShareDialogOpen] = useState(false);
  const [selectedDocForShare, setSelectedDocForShare] = useState<Document | null>(null);
  const [guestUsers, setGuestUsers] = useState<any[]>([]);
  const [selectedGuestId, setSelectedGuestId] = useState('');
  const [shareNotes, setShareNotes] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadResultsModalOpen, setUploadResultsModalOpen] = useState(false);
  const [duplicateFiles, setDuplicateFiles] = useState<Array<{filename: string, duplicateOf: string}>>([]);
  const [threadConsolidations, setThreadConsolidations] = useState<string[]>([]);
  const [failedUploads, setFailedUploads] = useState<Array<{filename: string, error: string}>>([]);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [documentToDelete, setDocumentToDelete] = useState<{id: string, filename: string} | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState<{[key: string]: {status: string, progress: number}}>({});
  const [showUploadProgress, setShowUploadProgress] = useState(false);
  const [attachmentsByDoc, setAttachmentsByDoc] = useState<Record<string, Attachment[]>>({});
  const [notificationModal, setNotificationModal] = useState<{open: boolean, message: string, type: 'success' | 'error'}>({
    open: false,
    message: '',
    type: 'success'
  });
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (caseId) {
      fetchDocuments();
      fetchGuestUsers();
    }
  }, [caseId]);

  // Poll for processing status updates
  useEffect(() => {
    // Check if any documents are still processing
    const hasProcessingDocs = documents.some(doc => 
      doc.processing_status && 
      ['ai_queued', 'ai_processing', 'ocr_processing'].includes(doc.processing_status)
    );

    if (!hasProcessingDocs) return;

    // Poll every 2 seconds
    const interval = setInterval(() => {
      fetchDocuments();
    }, 2000);

    return () => clearInterval(interval);
  }, [documents]);

  const fetchGuestUsers = async () => {
    try {
      const response = await api.get('/auth/users/guests');
      setGuestUsers(response.data);
    } catch (err) {
      console.error('Error fetching guest users:', err);
    }
  };

  const fetchAttachmentsForDocuments = async (docs: Document[]) => {
    const docsWithAttachments = docs.filter(d => d.has_attachments);
    const attachmentPromises = docsWithAttachments.map(async (doc) => {
      try {
        const response = await api.get(`/documents/${doc.id}/attachments`);
        return { docId: doc.id, attachments: response.data || [] };
      } catch (err) {
        console.error('Error fetching attachments for document', doc.id, err);
        return { docId: doc.id, attachments: [] };
      }
    });

    const results = await Promise.all(attachmentPromises);
    const attachmentsMap: Record<string, Attachment[]> = {};
    results.forEach(({ docId, attachments }) => {
      attachmentsMap[docId] = attachments;
    });
    setAttachmentsByDoc(attachmentsMap);
  };

  const fetchCase = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await api.get(`/cases/${caseId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setCaseTitle(response.data.title);
    } catch (error) {
      console.error('Error fetching case:', error);
    }
  };

  const fetchDocuments = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await api.get(`/cases/${caseId}/documents`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const docs = response.data.documents || [];
      setDocuments(docs);
      // Auto-fetch attachments for all documents that have them
      await fetchAttachmentsForDocuments(docs);
    } catch (error) {
      console.error('Error fetching documents:', error);
    } finally {
      setLoading(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  };

  const formatDate = (dateString: string) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return 'N/A';
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getFileTypeIcon = (doc: Document) => {
    // Check original MIME type first (for converted files)
    const mimeType = doc.original_mime_type || doc.mime_type || '';
    const filename = doc.filename.toLowerCase();
    
    // Email files
    if (mimeType.includes('rfc822') || mimeType.includes('outlook') || filename.endsWith('.eml') || filename.includes('.eml.')) {
      return <EmailIcon fontSize="small" style={{ color: 'var(--color-primary)' }} />;
    }
    
    // Word documents
    if (mimeType.includes('word') || filename.endsWith('.doc') || filename.endsWith('.docx') || filename.includes('.docx.')) {
      return <ArticleIcon fontSize="small" style={{ color: '#2b579a' }} />;
    }
    
    // Excel spreadsheets
    if (mimeType.includes('spreadsheet') || mimeType.includes('excel') || filename.endsWith('.xls') || filename.endsWith('.xlsx') || filename.includes('.xlsx.')) {
      return <TableChartIcon fontSize="small" style={{ color: '#217346' }} />;
    }
    
    // PowerPoint presentations
    if (mimeType.includes('presentation') || mimeType.includes('powerpoint') || filename.endsWith('.ppt') || filename.endsWith('.pptx') || filename.includes('.pptx.')) {
      return <SlideshowIcon fontSize="small" style={{ color: '#d24726' }} />;
    }
    
    // PDF files
    if (mimeType.includes('pdf') || filename.endsWith('.pdf')) {
      return <PictureAsPdfIcon fontSize="small" style={{ color: '#d32f2f' }} />;
    }
    
    // Default
    return <DescriptionIcon fontSize="small" style={{ color: '#6c757d' }} />;
  };

  const updateDocumentStatus = async (docId: string, newStatus: string) => {
    try {
      const token = localStorage.getItem('token');
      await api.put(
        `/documents/${docId}/status`,
        { status: newStatus },
        {
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json'
          }
        }
      );
      // Update local state
      setDocuments(docs => docs.map(doc =>
        doc.id === docId ? { ...doc, status: newStatus } : doc
      ));
    } catch (error) {
      console.error('Error updating document status:', error);
      alert('Failed to update document status');
    }
  };

  const bulkUpdateStatus = async () => {
    if (!bulkStatus || selectedDocs.size === 0) return;

    try {
      const token = localStorage.getItem('token');
      await api.put(
        '/documents/bulk/status',
        {
          document_ids: Array.from(selectedDocs),
          status: bulkStatus
        },
        {
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json'
          }
        }
      );
      // Update local state
      setDocuments(docs => docs.map(doc =>
        selectedDocs.has(doc.id) ? { ...doc, status: bulkStatus } : doc
      ));
      setSelectedDocs(new Set());
      setBulkStatus('');
      alert(`Updated ${selectedDocs.size} documents`);
    } catch (error) {
      console.error('Error bulk updating status:', error);
      alert('Failed to bulk update statuses');
    }
  };

  const getSortedDocuments = () => {
    let filtered = documents.filter(doc =>
      doc.filename.toLowerCase().includes(searchQuery.toLowerCase()) ||
      doc.submitter_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      doc.submitter_email?.toLowerCase().includes(searchQuery.toLowerCase())
    );

    // Apply status filter
    if (statusFilter !== 'all') {
      filtered = filtered.filter(doc => (doc.status || 'new') === statusFilter);
    }

    filtered.sort((a, b) => {
      let comparison = 0;
      
      switch (sortBy) {
        case 'name':
          comparison = a.filename.localeCompare(b.filename);
          break;
        case 'date':
          comparison = new Date(a.upload_date || a.uploaded_at || 0).getTime() - new Date(b.upload_date || b.uploaded_at || 0).getTime();
          break;
        case 'size':
          comparison = a.size - b.size;
          break;
      }

      return sortOrder === 'asc' ? comparison : -comparison;
    });

    return filtered;
  };

  const toggleSelectAll = () => {
    if (selectedDocs.size === documents.length) {
      setSelectedDocs(new Set());
    } else {
      setSelectedDocs(new Set(documents.map(d => d.id)));
    }
  };

  const toggleSelect = (docId: string) => {
    const newSelected = new Set(selectedDocs);
    if (newSelected.has(docId)) {
      newSelected.delete(docId);
    } else {
      newSelected.add(docId);
    }
    setSelectedDocs(newSelected);
  };

  const downloadDocument = async (docId: string, filename: string) => {
    try {
      const response = await api.get(`/documents/${docId}/download`, {
        responseType: 'blob'
      });
      
      // Extract filename from Content-Disposition header if available
      const contentDisposition = response.headers['content-disposition'];
      let downloadFilename = filename;
      if (contentDisposition) {
        // Match filename with or without quotes, non-greedy
        const filenameMatch = contentDisposition.match(/filename="([^"]+)"|filename=([^;\s]+)/);
        if (filenameMatch) {
          downloadFilename = filenameMatch[1] || filenameMatch[2];
        }
      }
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = downloadFilename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Error downloading document:', error);
      alert('Failed to download document');
    }
  };

  const downloadSelected = () => {
    selectedDocs.forEach(docId => {
      const doc = documents.find(d => d.id === docId);
      if (doc) {
        downloadDocument(docId, doc.filename);
      }
    });
  };

  const confirmDeleteDocument = (docId: string, filename: string) => {
    setDocumentToDelete({ id: docId, filename });
    setDeleteModalOpen(true);
  };

  const deleteDocument = async () => {
    if (!documentToDelete) return;
    
    try {
      const { id: docId, filename } = documentToDelete;
      const token = localStorage.getItem('token');
      await api.delete(`/documents/${docId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Refetch documents from server to ensure attachments are also removed
      await fetchDocuments();
      
      // Clear selection if deleted doc was selected
      setSelectedDocs(prev => {
        const newSet = new Set(prev);
        newSet.delete(docId);
        return newSet;
      });
      
      setNotificationModal({
        open: true,
        message: 'Document deleted successfully',
        type: 'success'
      });
    } catch (error) {
      console.error('Error deleting document:', error);
      setNotificationModal({
        open: true,
        message: 'Failed to delete document',
        type: 'error'
      });
    } finally {
      setDeleteModalOpen(false);
      setDocumentToDelete(null);
    }
  };

  const deleteSelected = async () => {
    if (selectedDocs.size === 0) return;
    
    // Use the existing delete modal for confirmation
    setDocumentToDelete({ 
      id: 'bulk', 
      filename: `${selectedDocs.size} documents` 
    });
    setDeleteModalOpen(true);
  };

  const confirmBulkDelete = async () => {
    try {
      const token = localStorage.getItem('token');
      let successCount = 0;
      
      for (const docId of Array.from(selectedDocs)) {
        try {
          await api.delete(`/documents/${docId}`, {
            headers: { Authorization: `Bearer ${token}` }
          });
          successCount++;
        } catch (error) {
          console.error(`Error deleting document ${docId}:`, error);
        }
      }
      
      // Refetch documents from server to ensure attachments are also removed
      await fetchDocuments();
      setSelectedDocs(new Set());
      
      setNotificationModal({
        open: true,
        message: `Deleted ${successCount} of ${selectedDocs.size} documents`,
        type: successCount === selectedDocs.size ? 'success' : 'error'
      });
    } catch (error) {
      console.error('Error deleting documents:', error);
      setNotificationModal({
        open: true,
        message: 'Failed to delete documents',
        type: 'error'
      });
    } finally {
      setDeleteModalOpen(false);
      setDocumentToDelete(null);
    }
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    
    const fileArray = Array.from(files);
    // Append new files to existing selection instead of replacing
    setSelectedFiles(prev => [...prev, ...fileArray]);
  };

  const removeSelectedFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const startUpload = async () => {
    if (selectedFiles.length === 0) return;

    setUploading(true);
    setShowUploadProgress(true);
    setUploadModalOpen(false);
    
    const duplicates: Array<{filename: string, duplicateOf: string}> = [];
    const threadConsolidations: string[] = [];
    const failures: Array<{filename: string, error: string}> = [];
    
    // Initialize progress for all files
    const initialProgress: {[key: string]: {status: string, progress: number}} = {};
    selectedFiles.forEach(file => {
      initialProgress[file.name] = { status: 'Uploading...', progress: 0 };
    });
    setUploadProgress(initialProgress);
    
    try {
      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        
        // Update to uploading
        setUploadProgress(prev => ({
          ...prev,
          [file.name]: { status: 'Uploading...', progress: 50 }
        }));

        const formData = new FormData();
        formData.append('file', file);
        formData.append('case_id', caseId!);

        try {
          // Let axios set the multipart Content-Type itself: it derives the
          // required `boundary` from the FormData body. Setting the header
          // manually omits the boundary, which breaks request parsing.
          const response = await api.post('/documents/', formData);
          
          // Update to processing
          setUploadProgress(prev => ({
            ...prev,
            [file.name]: { status: 'Processing...', progress: 75 }
          }));
          
          // Track duplicates
          if (response.data.is_duplicate && response.data.duplicate_of_filename) {
            duplicates.push({
              filename: file.name,
              duplicateOf: response.data.duplicate_of_filename
            });
            setUploadProgress(prev => ({
              ...prev,
              [file.name]: { status: 'Duplicate', progress: 100 }
            }));
          } else {
            // Mark as complete
            setUploadProgress(prev => ({
              ...prev,
              [file.name]: { status: 'Complete', progress: 100 }
            }));
          }
          
          // Track thread consolidations
          if (response.data.thread_consolidation) {
            const consolidation = response.data.thread_consolidation;
            if (consolidation.action === 'mark_new_as_superseded') {
              threadConsolidations.push(`📧 ${file.name} - ${consolidation.message}`);
            } else if (consolidation.action === 'mark_older_as_superseded' && consolidation.superseded_count > 0) {
              threadConsolidations.push(`📧 ${file.name} - Latest in thread (${consolidation.superseded_count} older emails marked as superseded)`);
            }
          }
        } catch (error: any) {
          console.error(`Error uploading ${file.name}:`, error);
          
          // Extract error message
          let errorMsg = 'Failed';
          let errorDetail = 'Unknown error';
          if (error.response?.data?.detail) {
            errorDetail = error.response.data.detail;
            errorMsg = `Failed: ${errorDetail}`;
          } else if (error.message) {
            errorDetail = error.message;
            errorMsg = `Failed: ${errorDetail}`;
          }
          
          // Track failure for results modal
          failures.push({
            filename: file.name,
            error: errorDetail
          });
          
          setUploadProgress(prev => ({
            ...prev,
            [file.name]: { status: errorMsg, progress: 0 }
          }));
        }
      }

      // Refresh documents list
      await fetchDocuments();
      
      // Show upload results modal if duplicates, thread consolidations, or failures found
      if (duplicates.length > 0 || threadConsolidations.length > 0 || failures.length > 0) {
        setDuplicateFiles(duplicates);
        setThreadConsolidations(threadConsolidations);
        setFailedUploads(failures);
        setUploadResultsModalOpen(true);
      }
    } catch (error) {
      console.error('Error uploading documents:', error);
    } finally {
      setUploading(false);
      setSelectedFiles([]);
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      
      // Keep progress modal open for a moment so user can see completion
      setTimeout(() => {
        setShowUploadProgress(false);
        setUploadProgress({});
      }, 3000);
    }
  };

  const sortedDocs = getSortedDocuments();

  if (loading) {
    return <div className="documents-page-loading">Loading documents...</div>;
  }

  return (
    <div className="case-documents-page">
      <div className="documents-header">
        <div className="header-top">
          <button onClick={() => navigate(`/cases/${caseId}`)} className="btn-back">
            ← Back to Case
          </button>
          <h1>Documents</h1>
          <div className="header-actions">
            <input
              type="file"
              ref={fileInputRef}
              multiple
              accept=".pdf,.doc,.docx,.eml,.msg,.jpg,.jpeg,.png,.gif,.bmp,.tiff,.tif,.webp"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            <button
              onClick={() => setUploadModalOpen(true)}
              className="btn-upload"
              disabled={uploading}
            >
              <UploadFileIcon fontSize="small" />
              <span>{uploading ? 'Uploading...' : 'Upload Documents'}</span>
            </button>
          </div>
        </div>
        <div className="case-info-bar">
          <span className="case-title">{caseTitle}</span>
          <span className="doc-count">{documents.length} documents</span>
        </div>
      </div>

      <div className="documents-controls">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search documents..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="sort-controls">
          <label>Sort by:</label>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)}>
            <option value="date">Date</option>
            <option value="name">Name</option>
            <option value="size">Size</option>
          </select>
          <button
            onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
            className="btn-sort-order"
          >
            {sortOrder === 'asc' ? '↑' : '↓'}
          </button>
        </div>

        <div className="status-filter">
          <label>Status:</label>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">All Statuses</option>
            {DOCUMENT_STATUSES.map(status => (
              <option key={status.value} value={status.value}>{status.label}</option>
            ))}
          </select>
        </div>

        {selectedDocs.size > 0 && (
          <div className="bulk-actions">
            <span className="selected-count">{selectedDocs.size} selected</span>
            <select
              value={bulkStatus}
              onChange={(e) => setBulkStatus(e.target.value)}
              className="bulk-status-select"
            >
              <option value="">Change Status...</option>
              {DOCUMENT_STATUSES.map(status => (
                <option key={status.value} value={status.value}>{status.label}</option>
              ))}
            </select>
            <button
              onClick={bulkUpdateStatus}
              disabled={!bulkStatus}
              className="btn-bulk-action"
            >
              Update Status
            </button>
            <button onClick={downloadSelected} className="btn-bulk-action">
              Download
            </button>
            <button onClick={deleteSelected} className="btn-bulk-action btn-delete">
              Delete
            </button>
          </div>
        )}
      </div>

      <div className="documents-table-container">
        <table className="documents-table">
          <thead>
            <tr>
              <th className="col-checkbox">
                <input
                  type="checkbox"
                  checked={selectedDocs.size === documents.length && documents.length > 0}
                  onChange={toggleSelectAll}
                />
              </th>
              <th className="col-filename">Filename</th>
              <th className="col-status">Workflow Status</th>
              <th className="col-processing">Processing</th>
              <th className="col-submitter">Uploaded By</th>
              <th className="col-date">Date</th>
              <th className="col-size">Size</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sortedDocs.length === 0 ? (
              <tr>
                <td colSpan={8} className="no-documents">
                  {searchQuery ? 'No documents match your search' : 'No documents uploaded yet'}
                </td>
              </tr>
            ) : (
              sortedDocs.map((doc) => {
                const attachmentRows =
                  attachmentsByDoc[doc.id]
                    ? attachmentsByDoc[doc.id].map((att) => (
                        <tr 
                          key={`${doc.id}-${att.id}`} 
                          className="attachment-row"
                          onClick={() => navigate(`/documents/${att.id}`)}
                          style={{ cursor: 'pointer' }}
                        >
                          <td className="col-checkbox attachment-checkbox" />
                          <td className="col-filename attachment-filename-col">
                            <div className="attachment-filename-wrapper">
                              <span className="attachment-indicator">↳</span>
                              <div>
                                <div className="attachment-name">{att.filename}</div>
                                <div className="attachment-meta">{formatFileSize(att.size)}</div>
                              </div>
                            </div>
                          </td>
                          <td className="col-status attachment-status">
                            <span className="attachment-pill">Attachment</span>
                          </td>
                          <td className="col-processing attachment-processing">—</td>
                          <td className="col-submitter attachment-submitter">Email attachment</td>
                          <td className="col-date attachment-date">{formatDate(att.upload_date)}</td>
                          <td className="col-size attachment-size">{formatFileSize(att.size)}</td>
                          <td className="col-actions attachment-actions">
                            <button
                              onClick={() => downloadDocument(att.id, att.filename)}
                              className="btn-icon"
                              title="Download attachment"
                            >
                              <DownloadIcon fontSize="small" />
                            </button>
                          </td>
                        </tr>
                      ))
                    : [];

                return [
                  <tr key={doc.id} data-doc-id={doc.id} className={`${doc.is_duplicate ? 'duplicate-row' : ''} ${doc.thread_status === 'superseded' ? 'superseded-row' : ''}`}>
                    <td className="col-checkbox">
                      <input
                        type="checkbox"
                        checked={selectedDocs.has(doc.id)}
                        onChange={() => toggleSelect(doc.id)}
                      />
                    </td>
                    <td className="col-filename">
                      <div className="filename-cell-wrapper">
                        <div
                          className="filename-cell clickable"
                          onClick={() => navigate(`/documents/${doc.id}`)}
                          title={doc.is_duplicate ? "Duplicate document - Click to view" : doc.thread_status === 'superseded' ? "Superseded by newer email - Click to view" : "Click to view and redact"}
                        >
                          <span className="file-icon">{getFileTypeIcon(doc)}</span>
                          <span className="filename">{doc.filename}</span>
                        </div>
                        {doc.thread_status === 'active' && (doc.mime_type === 'message/rfc822' || doc.mime_type === 'application/vnd.ms-outlook') && (
                          <div className="thread-info" style={{ fontSize: '12px', color: '#94a3b8', fontStyle: 'italic', marginTop: '2px', paddingLeft: '24px' }}>
                            Latest email from thread {doc.message_id ? doc.message_id.substring(0, 20) + '...' : doc.id.substring(0, 8)}
                          </div>
                        )}
                        {doc.thread_status === 'superseded' && doc.superseded_by_filename && (
                          <div className="superseded-info" style={{ fontSize: '12px', color: '#64748b', marginTop: '4px' }}>
                            <span className="superseded-text">Superseded by: </span>
                            <span 
                              className="superseded-link"
                              onClick={(e) => {
                                e.stopPropagation();
                                const newerDoc = documents.find(d => d.id === doc.superseded_by);
                                if (newerDoc) {
                                  // Scroll to newer document
                                  const element = document.querySelector(`tr[data-doc-id="${doc.superseded_by}"]`);
                                  if (element) {
                                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                    element.classList.add('highlight-flash');
                                    setTimeout(() => element.classList.remove('highlight-flash'), 2000);
                                  }
                                }
                              }}
                              title="Click to jump to newer email"
                              style={{ color: '#3b82f6', cursor: 'pointer', textDecoration: 'underline' }}
                            >
                              {doc.superseded_by_filename}
                            </span>
                          </div>
                        )}
                        {doc.is_duplicate && doc.duplicate_of && (
                          <div className="duplicate-info">
                            <span className="duplicate-text">Duplicate of: </span>
                            <span 
                              className="duplicate-link"
                              onClick={(e) => {
                                e.stopPropagation();
                                const originalDoc = documents.find(d => d.id === doc.duplicate_of);
                                if (originalDoc) {
                                  // Scroll to original document
                                  const element = document.querySelector(`tr[data-doc-id="${doc.duplicate_of}"]`);
                                  if (element) {
                                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                    element.classList.add('highlight-flash');
                                    setTimeout(() => element.classList.remove('highlight-flash'), 2000);
                                  }
                                }
                              }}
                              title="Click to jump to original document"
                            >
                              {documents.find(d => d.id === doc.duplicate_of)?.filename || 'Original document'}
                            </span>
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="col-status">
                      <select
                        value={doc.status || 'new'}
                        onChange={(e) => updateDocumentStatus(doc.id, e.target.value)}
                        className="status-dropdown"
                        style={{
                          backgroundColor: getStatusInfo(doc.status || 'new').color,
                          color: 'white'
                        }}
                      >
                        {DOCUMENT_STATUSES.map(status => (
                          <option key={status.value} value={status.value}>
                            {status.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="col-processing">
                      <span className="processing-status">
                        {doc.processing_status || 'Complete'}
                      </span>
                    </td>
                    <td className="col-submitter">
                      {doc.submitter_name ? (
                        <div className="submitter-info">
                          <div className="submitter-name">{doc.submitter_name}</div>
                          <div className="submitter-email">{doc.submitter_email}</div>
                        </div>
                      ) : doc.uploaded_by_name ? (
                        <div className="submitter-info">
                          <div className="submitter-name">{doc.uploaded_by_name}</div>
                        </div>
                      ) : (
                        <span className="system-upload">System</span>
                      )}
                    </td>
                    <td className="col-date">{formatDate(doc.upload_date || doc.uploaded_at || '')}</td>
                    <td className="col-size">{formatFileSize(doc.size)}</td>
                    <td className="col-actions">
                      <button
                        onClick={() => downloadDocument(doc.id, doc.filename)}
                        className="btn-icon"
                        title="Download"
                      >
                        <DownloadIcon fontSize="small" />
                      </button>
                      <button
                        onClick={() => {
                          setSelectedDocForShare(doc);
                          setShareDialogOpen(true);
                        }}
                        className="btn-icon"
                        title="Share with guest"
                      >
                        <ShareIcon fontSize="small" />
                      </button>
                      <button
                        onClick={() => confirmDeleteDocument(doc.id, doc.filename)}
                        className="btn-icon btn-icon-delete"
                        title="Delete"
                      >
                        <DeleteIcon fontSize="small" />
                      </button>
                    </td>
                  </tr>
                  ,
                  ...attachmentRows
                ];
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Share Dialog */}
      {shareDialogOpen && selectedDocForShare && (
        <div className="modal-overlay" onClick={() => setShareDialogOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>Share Document</h2>
            <p><strong>{selectedDocForShare.filename}</strong></p>
            
            <div className="form-group">
              <label>Select Guest User:</label>
              <select 
                value={selectedGuestId} 
                onChange={(e) => setSelectedGuestId(e.target.value)}
                className="form-control"
              >
                <option value="">-- Select a guest --</option>
                {guestUsers.map(user => (
                  <option key={user.id} value={user.id}>
                    {user.username} ({user.email})
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Notes (optional):</label>
              <textarea
                value={shareNotes}
                onChange={(e) => setShareNotes(e.target.value)}
                className="form-control"
                rows={3}
                placeholder="Add a note for the guest user..."
              />
            </div>

            <div className="modal-actions">
              <button 
                onClick={async () => {
                  if (!selectedGuestId) {
                    alert('Please select a guest user');
                    return;
                  }
                  try {
                    await api.post(`/documents/${selectedDocForShare.id}/share`, {
                      user_id: selectedGuestId,
                      notes: shareNotes
                    });
                    alert('Document shared successfully!');
                    setShareDialogOpen(false);
                    setSelectedGuestId('');
                    setShareNotes('');
                  } catch (err: any) {
                    alert(err.response?.data?.detail || 'Failed to share document');
                  }
                }}
                className="btn-primary"
              >
                Share
              </button>
              <button 
                onClick={() => {
                  setShareDialogOpen(false);
                  setSelectedGuestId('');
                  setShareNotes('');
                }}
                className="btn-secondary"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Upload Results Modal - Duplicates & Thread Consolidation */}
      {uploadResultsModalOpen && (
        <div className="modal-overlay" onClick={() => setUploadResultsModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>📋 Upload Results</h2>
            
            {/* Thread Consolidation Results */}
            {threadConsolidations.length > 0 && (
              <div className="upload-results-section">
                <h3>📧 Email Thread Consolidation</h3>
                <p className="section-description">
                  Older emails in threads have been automatically marked as superseded to avoid redundant redaction work.
                </p>
                <div className="thread-consolidation-list">
                  {threadConsolidations.map((consolidation, index) => (
                    <div key={index} className="consolidation-item">
                      {consolidation}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Duplicate Files Results */}
            {duplicateFiles.length > 0 && (
              <div className="upload-results-section">
                <h3>⚠️ Duplicate Documents</h3>
                <p className="section-description">
                  The following documents already exist and were not uploaded:
                </p>
                <div className="duplicate-list">
                  {duplicateFiles.map((dup, index) => (
                    <div key={index} className="duplicate-item">
                      <div className="duplicate-filename">
                        <strong>{dup.filename}</strong>
                      </div>
                      <div className="duplicate-of">
                        Matches: <em>{dup.duplicateOf}</em>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Failed Uploads */}
            {failedUploads.length > 0 && (
              <div className="upload-results-section">
                <h3>❌ Failed Uploads</h3>
                <p className="section-description">
                  The following documents failed to upload:
                </p>
                <div className="failed-list">
                  {failedUploads.map((failure, index) => (
                    <div key={index} className="failed-item">
                      <div className="failed-filename">
                        <strong>{failure.filename}</strong>
                      </div>
                      <div className="failed-error">
                        {failure.error}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="modal-actions">
              <button 
                onClick={() => {
                  setUploadResultsModalOpen(false);
                  setThreadConsolidations([]);
                  setDuplicateFiles([]);
                  setFailedUploads([]);
                }}
                className="btn-primary"
              >
                Got it
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modern Upload Modal */}
      {uploadModalOpen && (
        <div className="modal-overlay" onClick={() => {
          if (selectedFiles.length === 0) {
            setUploadModalOpen(false);
          }
        }}>
          <div className="upload-modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close-btn" onClick={() => {
              setUploadModalOpen(false);
              setSelectedFiles([]);
            }}>×</button>
            
            {selectedFiles.length === 0 ? (
              <>
                <h2>Add Documents</h2>
                
                <div 
                  className={`upload-dropzone ${isDragging ? 'dragging' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setIsDragging(false);
                    const files = e.dataTransfer.files;
                    if (files && files.length > 0) {
                      const fileArray = Array.from(files) as File[];
                      setSelectedFiles(fileArray);
                    }
                  }}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <div className="upload-icon"><FolderIcon style={{ fontSize: 64, color: 'var(--color-primary)' }} /></div>
                  <p className="upload-text">
                    Drop files here, <span className="browse-link">browse files</span> or import from:
                  </p>
                  <div className="upload-sources">
                    <div className="upload-source" onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}>
                      <div className="source-icon"><ComputerIcon style={{ fontSize: 32, color: 'var(--color-primary)' }} /></div>
                      <div className="source-label">My Device</div>
                    </div>
                  </div>
                  <p className="upload-hint">
                    Supported: PDF, DOCX, XLSX, PPTX, EML, MSG · Max: 50 MB
                  </p>
                </div>
              </>
            ) : (
              <>
                <h2>{selectedFiles.length} File{selectedFiles.length > 1 ? 's' : ''} Selected</h2>
                
                <div className="selected-files-list">
                  {selectedFiles.map((file, index) => (
                    <div key={index} className="selected-file-item">
                      <div className="file-preview">
                        <div className="file-icon-large"><DescriptionIcon style={{ fontSize: 32, color: 'var(--color-primary)' }} /></div>
                        <div className="file-details">
                          <div className="file-name">{file.name}</div>
                          <div className="file-size">{(file.size / 1024).toFixed(2)} KB</div>
                        </div>
                      </div>
                      <button 
                        className="remove-file-btn"
                        onClick={() => removeSelectedFile(index)}
                        title="Remove file"
                      >
                        <CloseIcon fontSize="small" />
                      </button>
                    </div>
                  ))}
                  
                  <div className="add-more-files" onClick={() => fileInputRef.current?.click()}>
                    <div className="add-more-icon"><AddIcon style={{ fontSize: 24, color: 'var(--color-primary)' }} /></div>
                    <div className="add-more-text">Add More</div>
                  </div>
                </div>

                <div className="upload-modal-actions">
                  <button 
                    onClick={() => {
                      setUploadModalOpen(false);
                      setSelectedFiles([]);
                    }}
                    className="btn-secondary"
                  >
                    Cancel
                  </button>
                  <button 
                    onClick={startUpload}
                    className="btn-primary"
                  >
                    Upload {selectedFiles.length} File{selectedFiles.length > 1 ? 's' : ''}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Upload Progress Toast - Bottom Right */}
      {showUploadProgress && (
        <div className="upload-progress-toast">
          <div className="upload-progress-header">
            <h3>
              {Object.values(uploadProgress).every(p => p.status === 'Complete' || p.status === 'Duplicate' || p.status.startsWith('Failed')) 
                ? 'Upload Complete' 
                : 'Uploading Documents'}
            </h3>
            <button 
              className="toast-close-btn"
              onClick={() => {
                setShowUploadProgress(false);
                setUploadProgress({});
              }}
              title="Close"
            >
              <CloseIcon fontSize="small" />
            </button>
          </div>
          
          <div className="progress-files-list">
            {Object.entries(uploadProgress).map(([filename, progress]) => (
              <div key={filename} className="progress-file-item">
                <div className="progress-file-header">
                  <div className="progress-file-icon">
                    {progress.status === 'Complete' ? <CheckCircleIcon fontSize="small" style={{ color: '#22c55e' }} /> : 
                     progress.status === 'Duplicate' ? <WarningIcon fontSize="small" style={{ color: '#fb8500' }} /> :
                     progress.status.startsWith('Failed') ? <ErrorIcon fontSize="small" style={{ color: '#d73a49' }} /> : 
                     <DescriptionIcon fontSize="small" style={{ color: 'var(--color-primary)' }} />}
                  </div>
                  <div className="progress-file-info">
                    <div className="progress-file-name">{filename}</div>
                    <div className={`progress-file-status status-${progress.status.toLowerCase().replace(/\.\.\./g, '').split(':')[0]}`}>
                      {progress.status}
                    </div>
                  </div>
                </div>
                {progress.status !== 'Complete' && progress.status !== 'Duplicate' && !progress.status.startsWith('Failed') && (
                  <div className="progress-bar-container">
                    <div 
                      className="progress-bar-fill" 
                      style={{ width: `${progress.progress}%` }}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteModalOpen && documentToDelete && (
        <div className="modal-overlay" onClick={() => setDeleteModalOpen(false)}>
          <div className="modal-content delete-modal" onClick={(e) => e.stopPropagation()}>
            <h2>🗑️ Delete {documentToDelete.id === 'bulk' ? 'Documents' : 'Document'}</h2>
            <p>Are you sure you want to delete {documentToDelete.id === 'bulk' ? 'these documents' : 'this document'}?</p>
            <div className="delete-doc-info">
              <strong>{documentToDelete.filename}</strong>
            </div>
            <p className="warning-text">⚠️ This action cannot be undone.</p>

            <div className="modal-actions">
              <button 
                onClick={() => {
                  setDeleteModalOpen(false);
                  setDocumentToDelete(null);
                }}
                className="btn-secondary"
              >
                Cancel
              </button>
              <button 
                onClick={documentToDelete.id === 'bulk' ? confirmBulkDelete : deleteDocument}
                className="btn-danger"
              >
                Delete {documentToDelete.id === 'bulk' ? 'Documents' : 'Document'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Notification Modal */}
      {notificationModal.open && (
        <div className="modal-overlay" onClick={() => setNotificationModal({ ...notificationModal, open: false })}>
          <div className="modal-content notification-modal" onClick={(e) => e.stopPropagation()}>
            <div className={`notification-icon ${notificationModal.type}`}>
              {notificationModal.type === 'success' ? '✓' : '✕'}
            </div>
            <p className="notification-message">{notificationModal.message}</p>
            <div className="modal-actions">
              <button 
                onClick={() => setNotificationModal({ ...notificationModal, open: false })}
                className={notificationModal.type === 'success' ? 'btn-primary' : 'btn-secondary'}
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CaseDocuments;
