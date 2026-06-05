import React, { useState, useEffect } from "react";
import api from "../api/client";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import './Login.css';

interface Props {
  onLoginSuccess: () => void;
}

interface OrgConfig {
  org_name: string;
  org_logo_url: string | null;
  org_primary_color?: string;
}

const Login: React.FC<Props> = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [orgConfig, setOrgConfig] = useState<OrgConfig>({
    org_name: 'BlackBar',
    org_logo_url: null,
    org_primary_color: '#0366d6'
  });
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  // Get redirect URL from query params — validate to prevent open redirect
  const searchParams = new URLSearchParams(location.search);
  const rawRedirect = searchParams.get('redirect') || '/';
  const redirectUrl = rawRedirect.startsWith('/') && !rawRedirect.startsWith('//') ? rawRedirect : '/';

  // Fetch org branding on mount
  useEffect(() => {
    const fetchOrgConfig = async () => {
      try {
        const response = await api.get('/admin/config/public');
        if (response.data) {
          setOrgConfig({
            org_name: response.data.org_name || 'BlackBar',
            org_logo_url: response.data.org_logo_url,
            org_primary_color: response.data.primary_color || '#0366d6'
          });
        }
      } catch (err) {
        // Ignore error, use defaults
        console.log('Could not load org config, using defaults');
      }
    };
    fetchOrgConfig();
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // Use AuthContext login to keep state in sync
      await login(username, password);

      onLoginSuccess();
      // Redirect to the original page or home
      navigate(redirectUrl);
    } catch (err: any) {
      console.error('Login error:', err);
      const errorMessage = err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        "Login failed. Please check your credentials.";
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-container">
        <div className="login-header">
          <div className="login-logo">
            {orgConfig.org_logo_url ? (
              <img
                src={orgConfig.org_logo_url}
                alt={orgConfig.org_name}
                style={{ maxHeight: '60px', maxWidth: '200px' }}
              />
            ) : (
              <>
                <div className="logo-icon" style={{ backgroundColor: orgConfig.org_primary_color }}>
                  {orgConfig.org_name.charAt(0).toUpperCase()}
                </div>
                <h1>{orgConfig.org_name}</h1>
              </>
            )}
          </div>
          <p className="login-subtitle">Freedom of Information Request Management</p>
        </div>

        <form onSubmit={handleLogin} className="login-form">
          <h2>Sign In</h2>

          {error && (
            <div className="error-message">
              {error}
            </div>
          )}

          <div className="form-group">
            <label htmlFor="username">Email</label>
            <input
              id="username"
              type="email"
              placeholder="Enter your email"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            className="login-button"
            disabled={loading}
            style={{ backgroundColor: orgConfig.org_primary_color }}
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default Login;

