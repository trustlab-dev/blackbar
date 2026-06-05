import React, { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { publicApi as api } from '../api/client';
import './PublicUploadPortal.css';

// API_BASE_URL not needed - api client already has baseURL configured

interface CollectionInfo {
  case_title: string;
  case_tracking_number: string;
  upload_count: number;
  max_uploads?: number;
  expires_at?: string;
}

interface PublicConfig {
  footer_text: string | null;
}

interface UploadedFile {
  file: File;
  id: string;
  status: 'pending' | 'uploading' | 'success' | 'error';
  progress: number;
  error?: string;
}

const PublicUploadPortal: React.FC = () => {
  const { token } = useParams();
  const [collectionInfo, setCollectionInfo] = useState<CollectionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Form state
  const [submitterName, setSubmitterName] = useState('');
  const [submitterEmail, setSubmitterEmail] = useState('');
  const [notes, setNotes] = useState('');

  // Upload state
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadComplete, setUploadComplete] = useState(false);
  const [publicConfig, setPublicConfig] = useState<PublicConfig>({ footer_text: null });

  useEffect(() => {
    if (token) {
      fetchCollectionInfo();
    }
    fetchPublicConfig();
  }, [token]);

  const fetchPublicConfig = async () => {
    try {
      const response = await api.get('/admin/config/public');
      setPublicConfig({ footer_text: response.data.footer_text || null });
    } catch (err) {
      console.error('Error fetching public config:', err);
    }
  };

  const fetchCollectionInfo = async () => {
    try {
      const response = await api.get(`/cases/collect/${token}`);
      setCollectionInfo(response.data);
      setError('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Collection link not found or expired');
    } finally {
      setLoading(false);
    }
  };

  const handleDragOver = useCallback((e: any) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: any) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: any) => {
    e.preventDefault();
    setIsDragging(false);

    const droppedFiles = Array.from(e.dataTransfer.files) as File[];
    addFiles(droppedFiles);
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selectedFiles = Array.from(e.target.files);
      addFiles(selectedFiles);
    }
  };

  const addFiles = (newFiles: File[]) => {
    const uploadFiles: UploadedFile[] = newFiles.map(file => ({
      file,
      id: Math.random().toString(36).substr(2, 9),
      status: 'pending',
      progress: 0
    }));
    setFiles(prev => [...prev, ...uploadFiles]);
  };

  const removeFile = (id: string) => {
    setFiles(prev => prev.filter(f => f.id !== id));
  };

  const uploadFile = async (uploadFile: UploadedFile) => {
    // Update status to uploading
    setFiles(prev => prev.map(f =>
      f.id === uploadFile.id ? { ...f, status: 'uploading' as const, progress: 0 } : f
    ));

    const formData = new FormData();
    formData.append('file', uploadFile.file);
    formData.append('submitter_name', submitterName);
    formData.append('submitter_email', submitterEmail);
    if (notes) formData.append('notes', notes);

    try {
      await api.post(
        `/cases/collect/${token}/upload`,
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' }
        }
      );

      // Mark as success
      setFiles(prev => prev.map(f =>
        f.id === uploadFile.id ? { ...f, status: 'success' as const, progress: 100 } : f
      ));
    } catch (err: any) {
      setFiles(prev => prev.map(f =>
        f.id === uploadFile.id ? {
          ...f,
          status: 'error' as const,
          error: err.response?.data?.detail || 'Upload failed'
        } : f
      ));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!submitterName || !submitterEmail) {
      setError('Please provide your name and email');
      return;
    }

    if (files.length === 0) {
      setError('Please select at least one file to upload');
      return;
    }

    setError('');

    // Upload all files
    for (const file of files) {
      if (file.status === 'pending') {
        await uploadFile(file);
      }
    }

    setUploadComplete(true);
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  };

  if (loading) {
    return (
      <div className="upload-portal-container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (error && !collectionInfo) {
    return (
      <div className="upload-portal-container">
        <div className="error-box">
          <div className="error-icon">✗</div>
          <h2>Link Not Available</h2>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (uploadComplete) {
    const successCount = files.filter(f => f.status === 'success').length;
    return (
      <div className="upload-portal-container">
        <div className="success-box">
          <div className="success-icon">✓</div>
          <h2>Upload Complete!</h2>
          <p>Successfully uploaded {successCount} of {files.length} files</p>
          <div className="uploaded-files-list">
            {files.map(file => (
              <div key={file.id} className={`file-status ${file.status}`}>
                <span>{file.file.name}</span>
                <span className="status-icon">
                  {file.status === 'success' ? '✓' : '✗'}
                </span>
              </div>
            ))}
          </div>
          <button onClick={() => window.location.reload()} className="btn-upload-more">
            Upload More Files
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="upload-portal-container">
      <div className="upload-portal-header">
        <h1>Document Upload</h1>
        <div className="case-info">
          <p><strong>Case:</strong> {collectionInfo?.case_title}</p>
          <p><strong>Tracking #:</strong> {collectionInfo?.case_tracking_number}</p>
          {collectionInfo?.max_uploads && (
            <p><strong>Uploads:</strong> {collectionInfo.upload_count} / {collectionInfo.max_uploads}</p>
          )}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="upload-form">
        <div className="form-section">
          <h3>Your Information</h3>
          <div className="form-group">
            <label>Name *</label>
            <input
              type="text"
              value={submitterName}
              onChange={(e) => setSubmitterName(e.target.value)}
              required
              placeholder="John Doe"
            />
          </div>
          <div className="form-group">
            <label>Email *</label>
            <input
              type="email"
              value={submitterEmail}
              onChange={(e) => setSubmitterEmail(e.target.value)}
              required
              placeholder="john@example.com"
            />
          </div>
          <div className="form-group">
            <label>Notes (Optional)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Any additional information about these documents..."
              rows={3}
            />
          </div>
        </div>

        <div className="form-section">
          <h3>Upload Documents</h3>

          <div
            className={`drop-zone ${isDragging ? 'dragging' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => document.getElementById('file-input')?.click()}
          >
            <div className="drop-zone-content">
              <div className="upload-icon">📁</div>
              <p className="drop-text">Drag and drop files here</p>
              <p className="or-text">or</p>
              <button type="button" className="btn-browse">
                Browse Files
              </button>
            </div>
            <input
              id="file-input"
              type="file"
              multiple
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
          </div>

          {files.length > 0 && (
            <div className="files-list">
              <h4>Files to Upload ({files.length})</h4>
              {files.map(file => (
                <div key={file.id} className={`file-item ${file.status}`}>
                  <div className="file-info">
                    <span className="file-name">{file.file.name}</span>
                    <span className="file-size">{formatFileSize(file.file.size)}</span>
                  </div>
                  <div className="file-actions">
                    {file.status === 'uploading' && (
                      <div className="progress-bar">
                        <div className="progress-fill" style={{ width: `${file.progress}%` }} />
                      </div>
                    )}
                    {file.status === 'success' && <span className="status-icon success">✓</span>}
                    {file.status === 'error' && <span className="status-icon error">✗</span>}
                    {file.status === 'pending' && (
                      <button type="button" onClick={() => removeFile(file.id)} className="btn-remove">
                        ✕
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {error && <div className="error-message">{error}</div>}

        <div className="form-actions">
          <button
            type="submit"
            disabled={files.length === 0 || !submitterName || !submitterEmail}
            className="btn-submit"
          >
            Upload {files.length} {files.length === 1 ? 'File' : 'Files'}
          </button>
        </div>

        {publicConfig.footer_text && (
          <div className="portal-footer" style={{ marginTop: '24px', padding: '16px', backgroundColor: '#f8f9fa', borderRadius: '8px', fontSize: '14px', color: '#666', textAlign: 'center' }}>
            {publicConfig.footer_text}
          </div>
        )}
      </form>
    </div>
  );
};

export default PublicUploadPortal;
