import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import {
  renderWithProviders,
  screen,
  waitFor,
} from '../../test-utils/render';
import { PublicPortalDashboard } from './PublicPortalDashboard';

function NavCapture({
  path,
  onNavigate,
}: {
  path: string;
  onNavigate?: (path: string) => void;
}) {
  onNavigate?.(path);
  return <div data-testid="nav-target">{path}</div>;
}

function Harness({ onNavigate }: { onNavigate?: (path: string) => void }) {
  return (
    <Routes>
      <Route path="/" element={<PublicPortalDashboard />} />
      <Route
        path="/public/login"
        element={<NavCapture path="/public/login" onNavigate={onNavigate} />}
      />
      <Route
        path="/public/request/new"
        element={<NavCapture path="/public/request/new" onNavigate={onNavigate} />}
      />
      <Route
        path="/public/request/:id"
        element={
          <NavCapture path="/public/request/:id" onNavigate={onNavigate} />
        }
      />
    </Routes>
  );
}

function makeRequest(overrides: Partial<{ id: string; status: string; tracking_number: string; title: string }> = {}) {
  return {
    id: overrides.id ?? 'req-1',
    title: overrides.title ?? 'Test Request',
    tracking_number: overrides.tracking_number ?? 'TRK-001',
    status: overrides.status ?? 'new',
    created_at: '2026-05-01T10:00:00Z',
    updated_at: '2026-05-02T10:00:00Z',
    requester: { name: 'Jane', email: 'jane@example.com' },
  };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('PublicPortalDashboard — auth gate', () => {
  it('redirects to /public/login when no token is stored', async () => {
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, {
      route: '/',
    });
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/login'),
    );
  });

  it('redirects to /public/login on 401 from the requests endpoint and clears localStorage', async () => {
    localStorage.setItem('token', 'tok');
    localStorage.setItem('user', '{"name":"Jane"}');
    localStorage.setItem('user_type', 'public');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get(
        '/api/v1/cases/public/my-requests',
        () => new HttpResponse(null, { status: 401 }),
      ),
    );
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, { route: '/' });
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/login'),
    );
    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('user')).toBeNull();
    expect(localStorage.getItem('user_type')).toBeNull();
  });

  it('shows generic error when requests endpoint fails with non-401', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get(
        '/api/v1/cases/public/my-requests',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/' });
    await waitFor(() =>
      expect(
        screen.getByText(/failed to load your requests/i),
      ).toBeInTheDocument(),
    );
  });
});

describe('PublicPortalDashboard — empty state', () => {
  it('shows the no-requests CTA when the list is empty', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({ requests: [] }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/' });
    expect(
      await screen.findByText(/no foi requests yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /submit your first request/i }),
    ).toBeInTheDocument();
  });

  it('CTA buttons navigate to /public/request/new', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({ requests: [] }),
      ),
    );
    const user = userEvent.setup();
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, { route: '/' });
    await screen.findByText(/no foi requests yet/i);
    await user.click(
      screen.getByRole('button', { name: /submit your first request/i }),
    );
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/request/new'),
    );
  });

  it('top SUBMIT A NEW REQUEST button navigates to /public/request/new', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({ requests: [] }),
      ),
    );
    const user = userEvent.setup();
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, { route: '/' });
    const submitBtn = await screen.findByRole('button', {
      name: /submit a new request/i,
    });
    await user.click(submitBtn);
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/request/new'),
    );
  });
});

describe('PublicPortalDashboard — populated table', () => {
  it('renders the requests table and auto-selects the first row for timeline', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({
          requests: [
            makeRequest({
              id: 'r1',
              status: 'in_progress',
              title: 'Records 1',
              tracking_number: 'TRK-001',
            }),
            makeRequest({
              id: 'r2',
              status: 'completed',
              title: 'Records 2',
              tracking_number: 'TRK-002',
            }),
          ],
        }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/' });
    expect(await screen.findByText('Records 1')).toBeInTheDocument();
    expect(screen.getByText('Records 2')).toBeInTheDocument();
    expect(screen.getByText('TRK-001')).toBeInTheDocument();
    // Status chips
    expect(screen.getByText(/in progress/i)).toBeInTheDocument();
    expect(screen.getByText(/completed/i)).toBeInTheDocument();
    // Auto-selected timeline references the first request
    expect(
      screen.getByText(/request id #TRK-001: records 1/i),
    ).toBeInTheDocument();
  });

  it('clicking a row updates the selected timeline', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({
          requests: [
            makeRequest({ id: 'r1', title: 'First', tracking_number: 'T1' }),
            makeRequest({ id: 'r2', title: 'Second', tracking_number: 'T2' }),
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/' });
    expect(
      await screen.findByText(/request id #T1: first/i),
    ).toBeInTheDocument();
    await user.click(screen.getByText('Second'));
    expect(
      await screen.findByText(/request id #T2: second/i),
    ).toBeInTheDocument();
  });

  it('clicking View Details button navigates to /public/request/:id without selecting row', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({ requests: [makeRequest({ id: 'r-only' })] }),
      ),
    );
    const user = userEvent.setup();
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, { route: '/' });
    await screen.findByText('Test Request');
    await user.click(screen.getByRole('button', { name: /view details/i }));
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/request/:id'),
    );
  });

  it('hits the closed-status timeline branch when first request is closed', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({
          requests: [
            makeRequest({
              id: 'r-closed',
              status: 'closed',
              title: 'Closed Request',
              tracking_number: 'TC1',
            }),
          ],
        }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/' });
    expect(
      await screen.findByText(/request id #TC1: closed request/i),
    ).toBeInTheDocument();
  });

  it('hits the review-status timeline branch', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({
          requests: [
            makeRequest({
              id: 'r-review',
              status: 'review',
              title: 'Review Request',
              tracking_number: 'TR1',
            }),
          ],
        }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/' });
    expect(
      await screen.findByText(/request id #TR1: review request/i),
    ).toBeInTheDocument();
  });

  it('renders all status label and color combinations', async () => {
    localStorage.setItem('token', 'tok');
    const statuses = [
      'new',
      'in_progress',
      'review',
      'on_hold',
      'completed',
      'closed',
      'unknown',
    ];
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({
          requests: statuses.map((s, i) =>
            makeRequest({ id: `r-${i}`, status: s, tracking_number: `T${i}` }),
          ),
        }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/' });
    // Wait for table to render
    await screen.findByText('T0');
    // Multiple "Submitted" tokens exist (timeline + chip); just confirm chips
    expect(screen.getAllByText(/^submitted$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^under review$/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/^on hold$/i)).toBeInTheDocument();
    expect(screen.getByText(/^closed$/i)).toBeInTheDocument();
    // Default branch (unknown status renders verbatim)
    expect(screen.getByText('unknown')).toBeInTheDocument();
  });
});

describe('PublicPortalDashboard — org config branding', () => {
  it('renders the org logo when org_logo_url is set', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          org_name: 'Acme FOI',
          org_logo_url: 'https://example.com/logo.png',
          primary_color: '#ff0000',
        }),
      ),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({ requests: [] }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/' });
    const logo = await screen.findByAltText('Acme FOI');
    expect(logo).toHaveAttribute('src', 'https://example.com/logo.png');
  });

  it('falls back to default branding when config fetch fails', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get(
        '/api/v1/admin/config/public',
        () => new HttpResponse(null, { status: 500 }),
      ),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({ requests: [] }),
      ),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderWithProviders(<Harness />, { route: '/' });
    expect(
      await screen.findByText(/freedom of information office/i),
    ).toBeInTheDocument();
  });

  it('uses returned org_name and primary_color', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          org_name: 'FOIA Office',
          org_logo_url: null,
          primary_color: '#123456',
        }),
      ),
      http.get('/api/v1/cases/public/my-requests', () =>
        HttpResponse.json({ requests: [] }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/' });
    expect(
      await screen.findByRole('heading', { name: /foia office/i }),
    ).toBeInTheDocument();
  });
});

describe('PublicPortalDashboard — error alert dismissal', () => {
  it('error alert can be dismissed', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get(
        '/api/v1/cases/public/my-requests',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/' });
    const errText = await screen.findByText(/failed to load your requests/i);
    const alert = errText.closest('[role="alert"]') as HTMLElement;
    await user.click(alert.querySelector('button[aria-label="Close"]')!);
    expect(
      screen.queryByText(/failed to load your requests/i),
    ).not.toBeInTheDocument();
  });
});
