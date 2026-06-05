import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import './SharedDocuments.css';

interface SharedDocument {
  id: string;
  filename: string;
  case_id: string;
  mime_type: string;
  size: number;
  upload_date: string;
  shared_by: string;
  shared_at: string;
  notes: string;
}

const SharedDocuments: React.FC = () => {
  const [documents, setDocuments] = useState<SharedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchSharedDocuments();
  }, []);

  const fetchSharedDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.get('/documents/shared-with-me');
      setDocuments(response.data.documents);
    } catch (err: any) {
      console.error('Error fetching shared documents:', err);
      // Handle authentication errors explicitly
      if (err.response?.status === 401) {
        // Clear auth data and redirect to login
        localStorage.removeItem('token');
        localStorage.removeItem('userRole');
        localStorage.removeItem('username');
        window.location.href = '/login';
        return;
      }
      setError(err.response?.data?.detail || 'Failed to load shared documents');
    } finally {
      setLoading(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString();
  };

  if (loading) {
    return <div className="shared-documents-container"><p>Loading shared documents...</p></div>;
  }

  if (error) {
    return <div className="shared-documents-container"><p className="error">{error}</p></div>;
  }

  return (
    <div className="shared-documents-container">
      <div className="shared-documents-header">
        <h1>Documents Shared With Me</h1>
        <p className="subtitle">View documents that have been shared with you</p>
      </div>

      {documents.length === 0 ? (
        <div className="empty-state">
          <p>No documents have been shared with you yet.</p>
        </div>
      ) : (
        <div className="documents-grid">
          {documents.map((doc) => (
            <div 
              key={doc.id} 
              className="document-card"
              onClick={() => navigate(`/documents/${doc.id}`)}
            >
              <div className="document-icon">
                📄
              </div>
              <div className="document-info">
                <h3>{doc.filename}</h3>
                <div className="document-meta">
                  <span className="meta-item">
                    <strong>Size:</strong> {formatFileSize(doc.size)}
                  </span>
                  <span className="meta-item">
                    <strong>Shared by:</strong> {doc.shared_by}
                  </span>
                  <span className="meta-item">
                    <strong>Shared on:</strong> {formatDate(doc.shared_at)}
                  </span>
                  {doc.notes && (
                    <span className="meta-item notes">
                      <strong>Note:</strong> {doc.notes}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default SharedDocuments;
