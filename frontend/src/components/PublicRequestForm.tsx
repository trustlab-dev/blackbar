import React, { useState, useEffect } from 'react';
import api from '../api/client';
import './PublicRequestForm.css';

// API_BASE_URL not needed - api client already has baseURL configured

interface FormData {
  title: string;
  description: string;
  category?: string;
  requester: {
    name: string;
    email: string;
    phone: string;
    organization: string;
  };
}

const PublicRequestForm: React.FC = () => {
  const [formData, setFormData] = useState<FormData>({
    title: '',
    description: '',
    category: '',
    requester: {
      name: '',
      email: '',
      phone: '',
      organization: ''
    }
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [trackingNumber, setTrackingNumber] = useState('');
  const [error, setError] = useState('');
  const [categories, setCategories] = useState<string[]>([]);
  const [orgConfig, setOrgConfig] = useState<{
    org_name: string;
    org_logo_url: string | null;
    contact_email: string;
    footer_text: string | null;
  }>({
    org_name: 'Freedom of Information Office',
    org_logo_url: null,
    contact_email: 'foi@example.com',
    footer_text: null
  });

  // Pre-fill email from authenticated user
  useEffect(() => {
    const user = localStorage.getItem('user');
    if (user) {
      try {
        const userData = JSON.parse(user);
        if (userData.email) {
          setFormData(prev => ({
            ...prev,
            requester: {
              ...prev.requester,
              email: userData.email,
              name: userData.name || prev.requester.name
            }
          }));
        }
      } catch (err) {
        console.error('Error parsing user data:', err);
      }
    }
  }, []);

  // Fetch categories and org config
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const response = await api.get('/admin/config/public');
        setCategories(response.data.request_categories || []);
        setOrgConfig({
          org_name: response.data.org_name || 'Freedom of Information Office',
          org_logo_url: response.data.org_logo_url,
          contact_email: response.data.contact_email || 'foi@example.com',
          footer_text: response.data.footer_text
        });
      } catch (err) {
        console.error('Error fetching config:', err);
      }
    };
    fetchConfig();
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    
    if (name.startsWith('requester.')) {
      const field = name.split('.')[1];
      setFormData(prev => ({
        ...prev,
        requester: {
          ...prev.requester,
          [field]: value
        }
      }));
    } else {
      setFormData(prev => ({
        ...prev,
        [name]: value
      }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError('');

    try {
      const response = await api.post('/cases/public/submit', formData);
      
      setTrackingNumber(response.data.tracking_number);
      setSubmitted(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to submit request. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div className="public-request-container">
        <div className="success-message">
          <div className="success-icon">✓</div>
          <h2>Request Submitted Successfully!</h2>
          <div className="tracking-info">
            <p>Your tracking number is:</p>
            <div className="tracking-number">{trackingNumber}</div>
            <p className="tracking-instructions">
              Save this number to track your request status.
            </p>
          </div>
          <div className="next-steps">
            <h3>What happens next?</h3>
            <ul>
              <li>You will receive a confirmation email shortly</li>
              <li>Your request will be reviewed within 30 days</li>
              <li>You can track your request status using the tracking number above</li>
            </ul>
          </div>
          <div className="action-buttons">
            <a 
              href={localStorage.getItem('user') ? '/public/dashboard' : `/track/${trackingNumber}`} 
              className="btn-track"
            >
              {localStorage.getItem('user') ? 'View My Requests' : 'Track Your Request'}
            </a>
            <button onClick={() => {
              setSubmitted(false);
              setFormData({
                title: '',
                description: '',
                requester: { name: '', email: '', phone: '', organization: '' }
              });
            }} className="btn-new">
              Submit Another Request
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="public-request-container">
      <div className="public-request-header">
        {orgConfig.org_logo_url && (
          <div style={{ textAlign: 'center', marginBottom: '20px' }}>
            <img src={orgConfig.org_logo_url} alt={orgConfig.org_name} style={{ maxHeight: '80px', maxWidth: '300px' }} />
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <h1>Submit a Freedom of Information Request</h1>
          <a href="/login" style={{
            padding: '8px 16px',
            backgroundColor: '#0366d6',
            color: 'white',
            textDecoration: 'none',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '500'
          }}>
            Sign In
          </a>
        </div>
        <p className="subtitle">
          {orgConfig.org_name} - Request access to records and information
        </p>
        {orgConfig.footer_text && (
          <p style={{ fontSize: '13px', color: '#666', marginTop: '10px', fontStyle: 'italic' }}>
            {orgConfig.footer_text}
          </p>
        )}
      </div>

      <form onSubmit={handleSubmit} className="public-request-form">
        <div className="form-section">
          <h2>Request Details</h2>
          
          <div className="form-group">
            <label htmlFor="title">
              Request Title <span className="required">*</span>
            </label>
            <input
              type="text"
              id="title"
              name="title"
              value={formData.title}
              onChange={handleChange}
              required
              placeholder="Brief description of what you're requesting"
              maxLength={200}
            />
          </div>

          {categories.length > 0 && (
            <div className="form-group">
              <label htmlFor="category">
                Request Category
              </label>
              <select
                id="category"
                name="category"
                value={formData.category}
                onChange={(e) => setFormData(prev => ({ ...prev, category: e.target.value }))}
              >
                <option value="">Select a category...</option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>
          )}

          <div className="form-group">
            <label htmlFor="description">
              Detailed Description <span className="required">*</span>
            </label>
            <textarea
              id="description"
              name="description"
              value={formData.description}
              onChange={handleChange}
              required
              placeholder="Provide as much detail as possible about the records you're requesting..."
              rows={8}
            />
            <span className="help-text">
              Be specific about dates, departments, document types, or any other relevant details
            </span>
          </div>
        </div>

        <div className="form-section">
          <h2>Your Contact Information</h2>
          
          <div className="form-group">
            <label htmlFor="requester.name">
              Full Name <span className="required">*</span>
            </label>
            <input
              type="text"
              id="requester.name"
              name="requester.name"
              value={formData.requester.name}
              onChange={handleChange}
              required
              placeholder="John Doe"
            />
          </div>

          <div className="form-group">
            <label htmlFor="requester.email">
              Email Address <span className="required">*</span>
            </label>
            <input
              type="email"
              id="requester.email"
              name="requester.email"
              value={formData.requester.email}
              onChange={handleChange}
              required
              placeholder="john@example.com"
              disabled={!!localStorage.getItem('user')}
              style={localStorage.getItem('user') ? { backgroundColor: '#f5f5f5', cursor: 'not-allowed' } : {}}
            />
            {localStorage.getItem('user') && (
              <small style={{ color: '#666', fontSize: '0.85em', marginTop: '4px', display: 'block' }}>
                Email from your authenticated session
              </small>
            )}
          </div>

          <div className="form-group">
            <label htmlFor="requester.phone">
              Phone Number
            </label>
            <input
              type="tel"
              id="requester.phone"
              name="requester.phone"
              value={formData.requester.phone}
              onChange={handleChange}
              placeholder="(555) 123-4567"
            />
          </div>

          <div className="form-group">
            <label htmlFor="requester.organization">
              Organization (if applicable)
            </label>
            <input
              type="text"
              id="requester.organization"
              name="requester.organization"
              value={formData.requester.organization}
              onChange={handleChange}
              placeholder="ABC News, University of XYZ, etc."
            />
          </div>
        </div>

        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn-submit">
            {submitting ? 'Submitting...' : 'Submit Request'}
          </button>
        </div>

        <div className="form-footer">
          <p>
            <strong>Note:</strong> Under the Freedom of Information Act, we will respond to your request within 30 days.
            You will receive a confirmation email with your tracking number.
          </p>
        </div>
      </form>
    </div>
  );
};

export default PublicRequestForm;
