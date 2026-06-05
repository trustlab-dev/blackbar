import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Route, Routes, Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { Box, CircularProgress, MenuItem, IconButton, Avatar, Divider } from '@mui/material';
import Menu from '@mui/material/Menu';
import LogoutIcon from '@mui/icons-material/Logout';
import './App.css';
import CaseQueue from './components/CaseQueue';
import { PriorityQueue } from './components/workflow';
import CaseDetailView from './components/CaseDetailView';
import CaseForm from './components/CaseForm';
import CaseDocuments from './components/CaseDocuments';
import ViewerShell from './components/viewer/ViewerShell';
import AdminConsole from './components/AdminConsole';
import PublicRequestForm from './components/PublicRequestForm';
import FeatureDisabled from './components/FeatureDisabled';
import PublicTrackingPage from './components/PublicTrackingPage';
import PublicUploadPortal from './components/PublicUploadPortal';
import { PublicLoginPage } from './pages/PublicLoginPage';
import { PublicVerifyPage } from './pages/PublicVerifyPage';
import { PublicDashboardPage } from './pages/PublicDashboardPage';
import { PublicRequestDetailPage } from './pages/PublicRequestDetailPage';
import ActivateAccount from './pages/ActivateAccount';
import { UserProvider, useUser } from './contexts/UserContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import HelpGuide from './components/HelpGuide';
import Login from './components/Login';
import SharedDocuments from './components/SharedDocuments';
import ProtectedRoute from './components/ProtectedRoute';
import ContributorPortal from './components/public/ContributorPortal';

const DocumentViewerWrapper: React.FC = () => {
  const { documentId } = useParams();
  if (!documentId) return <div>Document not found</div>;
  return <ViewerShell documentId={documentId} />;
};

const Header: React.FC = () => {
  const { currentRole } = useUser();
  const { user, roles } = useAuth();
  const [orgName, setOrgName] = useState('BlackBar');
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const open = Boolean(anchorEl);

  // Get user info from AuthContext, with fallbacks
  const username = user?.name || localStorage.getItem('username') || 'User';
  const userRole = roles && roles.length > 0 ? roles[0].toLowerCase() : (currentRole || localStorage.getItem('userRole') || '');

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleLogout = () => {
    localStorage.clear();
    window.location.href = '/login';
  };

  // Fetch branding from public config endpoint
  useEffect(() => {
    const fetchBranding = async () => {
      try {
        const response = await fetch('/api/v1/admin/config/public');
        if (response.ok) {
          const data = await response.json();
          setOrgName(data.org_name || 'Freedom of Information Office');
          if (data.primary_color) {
            document.documentElement.style.setProperty('--primary-color', data.primary_color);
          }
        }
      } catch (error) {
        console.error('Error fetching branding:', error);
        setOrgName('Freedom of Information Office');
      }
    };
    fetchBranding();
  }, []);

  return (
    <header className="app-header">
      {/* Logo on the left */}
      <div className="logo">
        <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
          <div style={{
            height: '40px',
            width: '40px',
            borderRadius: '8px',
            background: '#333',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: '900',
            fontSize: '24px',
            color: 'white'
          }}>
            B
          </div>
          <span style={{ fontSize: '22px', fontWeight: '700', color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>blackbar</span>
        </Link>
      </div>

      {/* Navigation in center */}
      <nav>
        <ul>
          {userRole === 'guest' ? (
            <>
              <li><Link to="/shared">Shared Documents</Link></li>
              <li><Link to="/help">Help</Link></li>
            </>
          ) : (
            <>
              <li><Link to="/">Cases</Link></li>
              {/* Only show Admin link for admin roles */}
              {(roles?.some(r => ['owner', 'admin'].includes(r.toLowerCase())) || userRole === 'owner' || userRole === 'admin') && (
                <li><Link to="/admin">Admin</Link></li>
              )}
              <li><Link to="/help">Help</Link></li>
            </>
          )}
        </ul>
      </nav>

      {/* User menu on the right */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
          <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            {orgName}
          </span>
          <span style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: '500' }}>
            {username} {userRole && `(${userRole})`}
          </span>
        </div>
        <IconButton
          onClick={handleClick}
          size="small"
          sx={{
            border: '2px solid var(--border-default)',
            '&:hover': {
              bgcolor: 'var(--bg-secondary)',
              borderColor: 'var(--border-input)'
            }
          }}
        >
          <Avatar sx={{ width: 32, height: 32, bgcolor: 'var(--color-primary)', fontSize: '14px', fontWeight: 600 }}>
            {username.charAt(0).toUpperCase()}
          </Avatar>
        </IconButton>
        <Menu
          anchorEl={anchorEl}
          open={open}
          onClose={handleClose}
          onClick={handleClose}
          PaperProps={{
            elevation: 3,
            sx: {
              minWidth: 200,
              mt: 1.5,
              '& .MuiMenuItem-root': {
                px: 2,
                py: 1.5
              }
            }
          }}
          transformOrigin={{ horizontal: 'right', vertical: 'top' }}
          anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
        >
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-default)' }}>
            <div style={{ fontWeight: 600, fontSize: '14px', color: 'var(--text-primary)' }}>
              {username}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
              {userRole}
            </div>
          </div>
          <Divider />
          <MenuItem onClick={handleLogout}>
            <LogoutIcon fontSize="small" style={{ marginRight: '12px', color: 'var(--text-secondary)' }} />
            Logout
          </MenuItem>
        </Menu>
      </div>
    </header>
  );
};

/** Loading placeholder rendered while AppContent's public-config
 *  fetch is in flight. Centers a spinner so the initial route resolution
 *  doesn't flash content based on stale config defaults. */
const ConfigLoadingGate: React.FC = () => (
  <Box
    sx={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '50vh',
    }}
    role="status"
    aria-label="Loading"
  >
    <CircularProgress />
  </Box>
);

const AppContent = () => {
  const { currentRole } = useUser();
  const navigate = useNavigate();
  // Phase 4 Batch 4.4 (audit F7): the prior default of
  // `enable_public_requests: true` caused the root `/` and `/request`
  // routes to redirect through the magic-link portal on first render
  // — before the async public-config fetch had a chance to land. An
  // org with public requests disabled would never see the intended
  // `/login` page. We now gate the routes that depend on the config
  // on a `configLoaded` flag and render a spinner until the fetch
  // settles (success or failure).
  const [publicConfig, setPublicConfig] = useState({
    enable_public_requests: true,
    enable_request_tracking: true,
    enable_public_upload: true
  });
  const [configLoaded, setConfigLoaded] = useState(false);

  // Fetch public configuration
  useEffect(() => {
    const fetchPublicConfig = async () => {
      try {
        const response = await fetch('/api/v1/admin/config/public');
        const data = await response.json();
        setPublicConfig({
          enable_public_requests: data.enable_public_requests,
          enable_request_tracking: data.enable_request_tracking,
          enable_public_upload: data.enable_public_upload
        });
      } catch (error) {
        console.error('Error fetching public config:', error);
      } finally {
        setConfigLoaded(true);
      }
    };
    fetchPublicConfig();
  }, []);

  // Check if user is authenticated
  const isAuthenticated = () => {
    return localStorage.getItem('token') !== null;
  };

  // Handler for successful login
  const handleLoginSuccess = () => {
    console.log('Login successful');
    navigate('/cases');
  };

  return (
    <div className="App">
      <Routes>
        {/* Public Routes (conditionally enabled) */}
        <Route path="/login" element={<Login onLoginSuccess={handleLoginSuccess} />} />

        {/* Account Activation Route */}
        <Route path="/activate" element={<ActivateAccount />} />

        {/* Magic Link Authentication Routes */}
        <Route path="/public/login" element={<PublicLoginPage />} />
        <Route path="/public/verify/:token" element={<PublicVerifyPage />} />
        <Route path="/public/dashboard" element={<PublicDashboardPage />} />
        <Route path="/public/request/new" element={<PublicRequestForm />} />
        <Route path="/public/request/:requestId" element={<PublicRequestDetailPage />} />

        {/* Legacy public request form - redirect to new login */}
        {/* Phase 4 Batch 4.4 (audit F7): render a spinner until the
            public-config fetch resolves so we don't redirect through
            the magic-link portal when public requests are actually
            disabled. */}
        <Route path="/request" element={
          !configLoaded ? (
            <ConfigLoadingGate />
          ) : publicConfig.enable_public_requests ? (
            <Navigate to="/public/login" replace />
          ) : (
            <FeatureDisabled featureName="Public Requests" />
          )
        } />

        <Route path="/track/:trackingNumber" element={
          publicConfig.enable_request_tracking ? (
            <PublicTrackingPage />
          ) : (
            <FeatureDisabled featureName="Request Tracking" />
          )
        } />

        <Route path="/collect/:token" element={
          publicConfig.enable_public_upload ? (
            <PublicUploadPortal />
          ) : (
            <FeatureDisabled featureName="Public Upload" />
          )
        } />

        {/* Contributor Portal (token-based, no auth) */}
        <Route path="/contribute/:contributorId" element={<ContributorPortal />} />

        {/* Root path - redirect based on auth status */}
        {/* Phase 4 Batch 4.4 (audit F7): wait for the public-config
            fetch before deciding between /request and /login. */}
        <Route path="/" element={
          isAuthenticated() ? (
            <>
              <Header />
              {currentRole === 'guest' ? <SharedDocuments /> : <CaseQueue />}
            </>
          ) : !configLoaded ? (
            <ConfigLoadingGate />
          ) : (
            <Navigate to={publicConfig.enable_public_requests ? "/request" : "/login"} replace />
          )
        } />

        {/* Guest Routes (authenticated) */}
        <Route path="/shared" element={
          isAuthenticated() ? (
            <>
              <Header />
              <SharedDocuments />
            </>
          ) : (
            <Navigate to="/login" replace />
          )
        } />
        {/* Protected Routes - require authentication */}
        <Route path="/cases" element={
          isAuthenticated() ? (
            <>
              <Header />
              <CaseQueue />
            </>
          ) : (
            <Navigate to="/login" replace />
          )
        } />
        {/* Priority Queue Route */}
        <Route path="/queue" element={
          isAuthenticated() ? (
            <>
              <Header />
              <PriorityQueue currentUserId={localStorage.getItem('userId') || undefined} />
            </>
          ) : (
            <Navigate to="/login" replace />
          )
        } />
        <Route path="/cases/new" element={
          isAuthenticated() ? (
            <>
              <Header />
              <CaseForm />
            </>
          ) : (
            <Navigate to="/login" replace />
          )
        } />
        <Route path="/cases/:caseId" element={
          isAuthenticated() ? (
            <>
              <Header />
              <CaseDetailView />
            </>
          ) : (
            <Navigate to="/login" replace />
          )
        } />
        <Route path="/cases/:caseId/documents" element={
          isAuthenticated() ? (
            <>
              <Header />
              <CaseDocuments />
            </>
          ) : (
            <Navigate to="/login" replace />
          )
        } />
        <Route path="/documents/:documentId" element={
          isAuthenticated() ? (
            <DocumentViewerWrapper />
          ) : (
            <Navigate to="/login" replace />
          )
        } />

        {/* Admin Routes - Protected with role checks */}
        <Route path="/admin" element={
          <ProtectedRoute isAuthenticated={isAuthenticated()} requiredRoles={['owner', 'admin']}>
            <Header />
            <AdminConsole />
          </ProtectedRoute>
        } />

        {/* Help Route */}
        <Route path="/help" element={
          isAuthenticated() ? (
            <>
              <Header />
              <HelpGuide />
            </>
          ) : (
            <Navigate to="/login" replace />
          )
        } />
      </Routes>
    </div>
  );
};

function App() {
  return (
    <Router>
      <AuthProvider>
        <UserProvider>
          <AppContent />
        </UserProvider>
      </AuthProvider>
    </Router>
  );
}

export default App;
