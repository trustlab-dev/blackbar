import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from './test-utils/msw-handlers';

// App.tsx is the root BrowserRouter + route table. It is mostly JSX route
// declarations, so this is a shallow smoke suite: every heavy child is
// stubbed and we assert that App mounts and routes resolve to the right
// component without throwing. Branch-level logic lives in the children's
// own test suites.
vi.mock('./components/CaseQueue', () => ({
  default: () => <div data-testid="case-queue" />,
}));
vi.mock('./components/workflow', () => ({
  PriorityQueue: () => <div data-testid="priority-queue" />,
}));
vi.mock('./components/CaseDetailView', () => ({
  default: () => <div data-testid="case-detail-view" />,
}));
vi.mock('./components/CaseForm', () => ({
  default: () => <div data-testid="case-form" />,
}));
vi.mock('./components/CaseDocuments', () => ({
  default: () => <div data-testid="case-documents" />,
}));
vi.mock('./components/viewer/ViewerShell', () => ({
  default: () => <div data-testid="viewer-shell" />,
}));
vi.mock('./components/AdminConsole', () => ({
  default: () => <div data-testid="admin-console" />,
}));
vi.mock('./components/PublicRequestForm', () => ({
  default: () => <div data-testid="public-request-form" />,
}));
vi.mock('./components/FeatureDisabled', () => ({
  default: ({ featureName }: { featureName: string }) => (
    <div data-testid="feature-disabled">{featureName}</div>
  ),
}));
vi.mock('./components/PublicTrackingPage', () => ({
  default: () => <div data-testid="public-tracking-page" />,
}));
vi.mock('./components/PublicUploadPortal', () => ({
  default: () => <div data-testid="public-upload-portal" />,
}));
vi.mock('./pages/PublicLoginPage', () => ({
  PublicLoginPage: () => <div data-testid="public-login-page" />,
}));
vi.mock('./pages/PublicVerifyPage', () => ({
  PublicVerifyPage: () => <div data-testid="public-verify-page" />,
}));
vi.mock('./pages/PublicDashboardPage', () => ({
  PublicDashboardPage: () => <div data-testid="public-dashboard-page" />,
}));
vi.mock('./pages/PublicRequestDetailPage', () => ({
  PublicRequestDetailPage: () => (
    <div data-testid="public-request-detail-page" />
  ),
}));
vi.mock('./pages/ActivateAccount', () => ({
  default: () => <div data-testid="activate-account" />,
}));
vi.mock('./components/HelpGuide', () => ({
  default: () => <div data-testid="help-guide" />,
}));
vi.mock('./components/Login', () => ({
  default: () => <div data-testid="login" />,
}));
vi.mock('./components/SharedDocuments', () => ({
  default: () => <div data-testid="shared-documents" />,
}));
vi.mock('./components/ProtectedRoute', () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="protected-route">{children}</div>
  ),
}));
vi.mock('./components/public/ContributorPortal', () => ({
  default: () => <div data-testid="contributor-portal" />,
}));

import App from './App';

/**
 * App owns its own BrowserRouter, so route is driven via window.history
 * rather than renderWithProviders' MemoryRouter.
 */
function renderAppAt(path: string) {
  window.history.pushState({}, '', path);
  return render(<App />);
}

beforeEach(() => {
  localStorage.clear();
  server.use(
    http.get('/api/v1/admin/config/public', () =>
      HttpResponse.json({
        org_name: 'Test Org',
        primary_color: '#123456',
        enable_public_requests: true,
        enable_request_tracking: true,
        enable_public_upload: true,
      }),
    ),
  );
});

afterEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  window.history.pushState({}, '', '/');
});

describe('App — mounts', () => {
  it('renders without throwing', () => {
    expect(() => renderAppAt('/login')).not.toThrow();
  });

  it('wraps content in the .App container', () => {
    const { container } = renderAppAt('/login');
    expect(container.querySelector('.App')).toBeInTheDocument();
  });
});

describe('App — public routes', () => {
  it('renders the login page at /login', () => {
    renderAppAt('/login');
    expect(screen.getByTestId('login')).toBeInTheDocument();
  });

  it('renders the account activation page at /activate', () => {
    renderAppAt('/activate');
    expect(screen.getByTestId('activate-account')).toBeInTheDocument();
  });

  it('renders the magic-link login page at /public/login', () => {
    renderAppAt('/public/login');
    expect(screen.getByTestId('public-login-page')).toBeInTheDocument();
  });

  it('renders the magic-link verify page at /public/verify/:token', () => {
    renderAppAt('/public/verify/abc123');
    expect(screen.getByTestId('public-verify-page')).toBeInTheDocument();
  });

  it('renders the public dashboard at /public/dashboard', () => {
    renderAppAt('/public/dashboard');
    expect(screen.getByTestId('public-dashboard-page')).toBeInTheDocument();
  });

  it('renders the public request form at /public/request/new', () => {
    renderAppAt('/public/request/new');
    expect(screen.getByTestId('public-request-form')).toBeInTheDocument();
  });

  it('renders the public request detail page at /public/request/:requestId', () => {
    renderAppAt('/public/request/req-1');
    expect(
      screen.getByTestId('public-request-detail-page'),
    ).toBeInTheDocument();
  });

  it('renders the contributor portal at /contribute/:contributorId', () => {
    renderAppAt('/contribute/contrib-1');
    expect(screen.getByTestId('contributor-portal')).toBeInTheDocument();
  });
});

describe('App — feature-flagged routes', () => {
  it('renders the tracking page when request tracking is enabled', async () => {
    renderAppAt('/track/TRK-1');
    expect(
      await screen.findByTestId('public-tracking-page'),
    ).toBeInTheDocument();
  });

  it('renders FeatureDisabled for tracking when the feature is off', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          enable_public_requests: true,
          enable_request_tracking: false,
          enable_public_upload: true,
        }),
      ),
    );
    renderAppAt('/track/TRK-1');
    await waitFor(() =>
      expect(screen.getByTestId('feature-disabled')).toHaveTextContent(
        'Request Tracking',
      ),
    );
  });

  it('renders the upload portal when public upload is enabled', async () => {
    renderAppAt('/collect/tok-1');
    expect(
      await screen.findByTestId('public-upload-portal'),
    ).toBeInTheDocument();
  });

  it('renders FeatureDisabled for upload when the feature is off', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          enable_public_requests: true,
          enable_request_tracking: true,
          enable_public_upload: false,
        }),
      ),
    );
    renderAppAt('/collect/tok-1');
    await waitFor(() =>
      expect(screen.getByTestId('feature-disabled')).toHaveTextContent(
        'Public Upload',
      ),
    );
  });
});

describe('App — protected routes (unauthenticated)', () => {
  it('redirects /cases to /login when there is no token', () => {
    renderAppAt('/cases');
    expect(screen.getByTestId('login')).toBeInTheDocument();
    expect(screen.queryByTestId('case-queue')).not.toBeInTheDocument();
  });

  it('redirects /shared to /login when there is no token', () => {
    renderAppAt('/shared');
    expect(screen.getByTestId('login')).toBeInTheDocument();
  });

  it('redirects /help to /login when there is no token', () => {
    renderAppAt('/help');
    expect(screen.getByTestId('login')).toBeInTheDocument();
  });
});

describe('App — protected routes (authenticated)', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'tok');
  });

  it('renders the case queue at /cases with the header', () => {
    renderAppAt('/cases');
    expect(screen.getByTestId('case-queue')).toBeInTheDocument();
  });

  it('renders the priority queue at /queue', () => {
    renderAppAt('/queue');
    expect(screen.getByTestId('priority-queue')).toBeInTheDocument();
  });

  it('renders the case form at /cases/new', () => {
    renderAppAt('/cases/new');
    expect(screen.getByTestId('case-form')).toBeInTheDocument();
  });

  it('renders the case detail view at /cases/:caseId', () => {
    renderAppAt('/cases/case-1');
    expect(screen.getByTestId('case-detail-view')).toBeInTheDocument();
  });

  it('renders case documents at /cases/:caseId/documents', () => {
    renderAppAt('/cases/case-1/documents');
    expect(screen.getByTestId('case-documents')).toBeInTheDocument();
  });

  it('renders the viewer shell at /documents/:documentId', () => {
    renderAppAt('/documents/doc-1');
    expect(screen.getByTestId('viewer-shell')).toBeInTheDocument();
  });

  it('renders the help guide at /help', () => {
    renderAppAt('/help');
    expect(screen.getByTestId('help-guide')).toBeInTheDocument();
  });

  it('renders the admin console behind a ProtectedRoute at /admin', () => {
    renderAppAt('/admin');
    expect(screen.getByTestId('protected-route')).toBeInTheDocument();
    expect(screen.getByTestId('admin-console')).toBeInTheDocument();
  });

  it('renders the case queue at the root path when authenticated', () => {
    renderAppAt('/');
    expect(screen.getByTestId('case-queue')).toBeInTheDocument();
  });
});

describe('App — root redirect (unauthenticated)', () => {
  it('redirects the root path to /request when public requests are enabled', async () => {
    renderAppAt('/');
    // /request itself redirects to /public/login.
    await waitFor(() =>
      expect(screen.getByTestId('public-login-page')).toBeInTheDocument(),
    );
  });

  it('redirects to /login when public requests resolve to disabled (F7)', async () => {
    // Phase 4 Batch 4.4 (audit F7): the root route now waits for the
    // public-config fetch (rendering a spinner via ConfigLoadingGate)
    // before deciding between /request and /login. With public requests
    // disabled the user lands on /login, not on the magic-link portal.
    // Test flipped from the prior "lands on the magic-link login"
    // characterization that pinned the race.
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          enable_public_requests: false,
          enable_request_tracking: true,
          enable_public_upload: true,
        }),
      ),
    );
    renderAppAt('/');
    await waitFor(() =>
      expect(screen.getByTestId('login')).toBeInTheDocument(),
    );
    // Public-login portal should NOT have been transiently mounted.
    expect(screen.queryByTestId('public-login-page')).not.toBeInTheDocument();
  });
});
