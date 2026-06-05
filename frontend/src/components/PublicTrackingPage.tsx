import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api/client';
import './PublicTrackingPage.css';

// API_BASE_URL not needed - api client already has baseURL configured

interface Comment {
  id: string;
  author_name: string;
  text: string;
  type: string;
  created_at: string;
}

interface TrackingData {
  tracking_number: string;
  title: string;
  status: string;
  received_date: string;
  due_date: string;
  sla_status: string;
  comments: Comment[];
  last_updated: string;
}

const PublicTrackingPage: React.FC = () => {
  const { trackingNumber } = useParams();
  const [data, setData] = useState<TrackingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [footerText, setFooterText] = useState<string | null>(null);

  useEffect(() => {
    if (trackingNumber) {
      fetchTrackingData(trackingNumber);
    }
    fetchPublicConfig();
  }, [trackingNumber]);

  const fetchPublicConfig = async () => {
    try {
      const response = await api.get('/admin/config/public');
      setFooterText(response.data.footer_text || null);
    } catch (err) {
      console.error('Error fetching public config:', err);
    }
  };

  const fetchTrackingData = async (number: string) => {
    try {
      const response = await api.get(`/cases/public/track/${number}`);
      setData(response.data);
      setError('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Tracking number not found');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      new: '#0366d6',
      in_progress: '#ffc107',
      review: '#fd7e14',
      on_hold: '#6c757d',
      completed: '#28a745',
      closed: '#343a40'
    };
    return colors[status] || '#6c757d';
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      new: 'New',
      in_progress: 'In Progress',
      review: 'Under Review',
      on_hold: 'On Hold',
      completed: 'Completed',
      closed: 'Closed'
    };
    return labels[status] || status;
  };

  const getSLABadge = (slaStatus: string) => {
    if (slaStatus === 'overdue') {
      return <span className="sla-badge overdue">Overdue</span>;
    } else if (slaStatus === 'due_soon') {
      return <span className="sla-badge due-soon">Due Soon</span>;
    } else {
      return <span className="sla-badge on-track">On Track</span>;
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
  };

  if (loading) {
    return (
      <div className="tracking-container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="tracking-container">
        <div className="error-box">
          <div className="error-icon">✗</div>
          <h2>Request Not Found</h2>
          <p>{error}</p>
          <a href="/request" className="btn-back">Submit a New Request</a>
        </div>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <div className="tracking-container">
      <div className="tracking-header">
        <h1>Track Your FOI Request</h1>
        <div className="tracking-number-display">
          {data.tracking_number}
        </div>
      </div>

      <div className="tracking-content">
        <div className="status-card">
          <div className="status-header">
            <h2>Request Status</h2>
            {getSLABadge(data.sla_status)}
          </div>

          <div className="status-badge" style={{ backgroundColor: getStatusColor(data.status) }}>
            {getStatusLabel(data.status)}
          </div>

          <div className="request-title">
            <h3>{data.title}</h3>
          </div>

          <div className="dates-grid">
            <div className="date-item">
              <span className="date-label">Received</span>
              <span className="date-value">{formatDate(data.received_date)}</span>
            </div>
            <div className="date-item">
              <span className="date-label">Due Date</span>
              <span className="date-value">{formatDate(data.due_date)}</span>
            </div>
            <div className="date-item">
              <span className="date-label">Last Updated</span>
              <span className="date-value">{formatDate(data.last_updated)}</span>
            </div>
          </div>
        </div>

        {data.comments && data.comments.length > 0 && (
          <div className="comments-card">
            <h2>Updates</h2>
            <div className="comments-list">
              {data.comments.map((comment) => (
                <div key={comment.id} className="comment-item">
                  <div className="comment-header">
                    <span className="comment-author">{comment.author_name}</span>
                    <span className="comment-date">{formatDate(comment.created_at)}</span>
                  </div>
                  <div className="comment-text">{comment.text}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="info-card">
          <h3>What to Expect</h3>
          <ul>
            <li>We will review your request and may contact you for clarification</li>
            <li>You will be notified of any updates via email</li>
            <li>The standard response time is 30 days from the date received</li>
            <li>You can check this page anytime for status updates</li>
          </ul>
        </div>

        <div className="actions">
          <a href="/request" className="btn-new-request">
            Submit Another Request
          </a>
        </div>

        {footerText && (
          <div className="portal-footer" style={{ marginTop: '24px', padding: '16px', backgroundColor: '#f8f9fa', borderRadius: '8px', fontSize: '14px', color: '#666', textAlign: 'center' }}>
            {footerText}
          </div>
        )}
      </div>
    </div>
  );
};

export default PublicTrackingPage;
