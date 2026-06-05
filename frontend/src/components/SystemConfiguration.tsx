import React, { useState, useEffect } from 'react';
import api from '../api/client';
import './SystemConfiguration.css';

// API_BASE_URL not needed - api client already has baseURL configured

interface SystemConfig {
  org_name: string;
  org_logo_url?: string;
  contact_email: string;
  primary_color: string;
  footer_text?: string;
  default_due_days: number;
  default_assignee_id?: string;
  default_priority: string;
  session_timeout_minutes: number;
  password_min_length: number;
  enable_public_requests: boolean;
  enable_request_tracking: boolean;
  enable_public_upload: boolean;
  request_categories: string[];
  auto_generate_ai_suggestions: boolean;
  // AI suggestion timeout is configured under Global Admin
  updated_at?: string;
  updated_by?: string;
}

interface User {
  id: string;
  name?: string;
  email: string;
  username?: string;
  role: string;
}

const SystemConfiguration: React.FC = () => {
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    try {
      const response = await api.get('/admin/config/');
      setConfig(response.data);
    } catch (err) {
      console.error('Error fetching configuration:', err);
      setError('Failed to load configuration');
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (field: string, value: any) => {
    if (!config) return;
    setConfig({
      ...config,
      [field]: value
    });
  };

  const handleSave = async () => {
    if (!config) return;

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const response = await api.put('/admin/config/', config);
      setConfig(response.data);
      setSuccess('Configuration saved successfully!');

      // Clear success message after 3 seconds
      setTimeout(() => setSuccess(''), 3000);
    } catch (err: any) {
      console.error('Error saving configuration:', err);
      setError(err.response?.data?.detail || 'Failed to save configuration');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="system-config-container">
        <div className="loading">Loading configuration...</div>
      </div>
    );
  }

  if (!config) {
    return (
      <div className="system-config-container">
        <div className="error">Failed to load configuration</div>
      </div>
    );
  }

  return (
    <div className="system-config-container">
      <div className="system-config-header">
        <h1>System Configuration</h1>
        <p>Customize your FOI management system</p>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {success && <div className="alert alert-success">{success}</div>}

      <div className="config-sections">


        {/* Workflow Defaults */}
        <section className="config-section">
          <h2>Workflow Defaults</h2>

          <div className="form-group">
            <label htmlFor="default_due_days">Default Due Date</label>
            <div className="input-with-suffix">
              <input
                type="number"
                id="default_due_days"
                value={config.default_due_days}
                onChange={(e) => handleChange('default_due_days', parseInt(e.target.value))}
                min={1}
                max={365}
              />
              <span className="suffix">days from case creation</span>
            </div>
            <small>Standard response time (e.g., 30 days for FIPPA)</small>
          </div>

          <div className="form-group">
            <label htmlFor="default_assignee_id">Default Assignee</label>
            <select
              id="default_assignee_id"
              value={config.default_assignee_id || ''}
              onChange={(e) => handleChange('default_assignee_id', e.target.value || undefined)}
            >
              <option value="">None (Unassigned)</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name || user.username || user.email} ({user.role})
                </option>
              ))}
            </select>
            <small>Auto-assign new cases to this user</small>
          </div>

          <div className="form-group">
            <label htmlFor="default_priority">Default Priority</label>
            <select
              id="default_priority"
              value={config.default_priority}
              onChange={(e) => handleChange('default_priority', e.target.value)}
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
            <small>Initial priority for new cases</small>
          </div>
        </section>

        {/* Security Settings */}
        <section className="config-section">
          <h2>Security Settings</h2>

          <div className="form-group">
            <label htmlFor="session_timeout_minutes">Session Timeout</label>
            <div className="input-with-suffix">
              <input
                type="number"
                id="session_timeout_minutes"
                value={config.session_timeout_minutes}
                onChange={(e) => handleChange('session_timeout_minutes', parseInt(e.target.value))}
                min={15}
                max={480}
              />
              <span className="suffix">minutes</span>
            </div>
            <small>Auto-logout after inactivity (15-480 minutes)</small>
          </div>

          <div className="form-group">
            <label htmlFor="password_min_length">Minimum Password Length</label>
            <div className="input-with-suffix">
              <input
                type="number"
                id="password_min_length"
                value={config.password_min_length}
                onChange={(e) => handleChange('password_min_length', parseInt(e.target.value))}
                min={8}
                max={32}
              />
              <span className="suffix">characters</span>
            </div>
            <small>Required for new passwords (8-32 characters)</small>
          </div>
        </section>

        {/* Document Handling */}
        <section className="config-section">
          <h2>Document Handling</h2>
          <p style={{ color: '#586069', fontSize: '14px', marginBottom: '15px' }}>
            Configure how documents are processed after upload.
          </p>

          <div className="form-group checkbox-group">
            <label>
              <input
                type="checkbox"
                checked={config.auto_generate_ai_suggestions}
                onChange={(e) => handleChange('auto_generate_ai_suggestions', e.target.checked)}
              />
              <span>Auto-Generate AI Redaction Suggestions</span>
            </label>
            <small>Automatically run AI analysis on document upload (runs in background)</small>
          </div>

          {/* AI Suggestion Timeout is configured under Global Admin */}
        </section>

        {/* Public Portal */}
        <section className="config-section">
          <h2>Public Portal</h2>

          <div className="form-group checkbox-group">
            <label>
              <input
                type="checkbox"
                checked={config.enable_public_requests}
                onChange={(e) => handleChange('enable_public_requests', e.target.checked)}
              />
              <span>Enable Public Requests</span>
            </label>
            <small>Allow public to submit FOI requests via /request page</small>
          </div>

          <div className="form-group checkbox-group">
            <label>
              <input
                type="checkbox"
                checked={config.enable_request_tracking}
                onChange={(e) => handleChange('enable_request_tracking', e.target.checked)}
              />
              <span>Enable Request Tracking</span>
            </label>
            <small>Allow tracking requests by number via /track/:number</small>
          </div>

          <div className="form-group checkbox-group">
            <label>
              <input
                type="checkbox"
                checked={config.enable_public_upload}
                onChange={(e) => handleChange('enable_public_upload', e.target.checked)}
              />
              <span>Enable Public Upload</span>
            </label>
            <small>Allow document uploads via collection links</small>
          </div>

          <div className="form-group">
            <label htmlFor="footer_text">Footer / Disclaimer Text</label>
            <textarea
              id="footer_text"
              value={config.footer_text || ''}
              onChange={(e) => handleChange('footer_text', e.target.value || undefined)}
              maxLength={500}
              rows={3}
              placeholder="e.g., All information submitted is collected under FOIPPA Section..."
            />
            <small>Displayed on public forms and documents ({config.footer_text?.length || 0}/500)</small>
          </div>
        </section>

        {/* Request Categories */}
        <section className="config-section">
          <h2>Request Categories</h2>
          <p style={{ color: '#586069', fontSize: '14px', marginBottom: '15px' }}>
            Define the types of requests users can select from. These appear in request forms.
          </p>

          <div className="form-group">
            <label>Categories (one per line)</label>
            <textarea
              value={config.request_categories.join('\n')}
              onChange={(e) => handleChange('request_categories', e.target.value.split('\n').filter(c => c.trim()))}
              rows={10}
              placeholder="General Records&#10;Personnel Files&#10;Financial Records"
              style={{ fontFamily: 'monospace' }}
            />
            <small>{config.request_categories.length} categories defined</small>
          </div>
        </section>
      </div>

      <div className="config-actions">
        <button
          onClick={handleSave}
          disabled={saving}
          className="btn-primary"
        >
          {saving ? 'Saving...' : 'Save Configuration'}
        </button>
      </div>

      {config.updated_at && (
        <div className="config-footer">
          <small>
            Last updated: {new Date(config.updated_at).toLocaleString()}
            {config.updated_by && ` by ${config.updated_by}`}
          </small>
        </div>
      )}
    </div>
  );
};

export default SystemConfiguration;
