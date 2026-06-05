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
import { RequestDetailsPage } from './RequestDetailsPage';

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
      <Route
        path="/public/request/:requestId"
        element={<RequestDetailsPage />}
      />
      <Route
        path="/public/login"
        element={<NavCapture path="/public/login" onNavigate={onNavigate} />}
      />
      <Route
        path="/public/dashboard"
        element={
          <NavCapture path="/public/dashboard" onNavigate={onNavigate} />
        }
      />
    </Routes>
  );
}

function makeRequestDetails(overrides: any = {}) {
  return {
    id: 'r-1',
    tracking_number: 'TRK-001',
    title: 'My Request',
    description: 'Need records about X',
    status: 'in_progress',
    category: 'General',
    created_at: '2026-05-01T10:00:00Z',
    updated_at: '2026-05-02T10:00:00Z',
    due_date: '2026-06-01T10:00:00Z',
    requester: { name: 'Jane', email: 'jane@example.com' },
    timeline: [],
    documents: [],
    document_count: 0,
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('RequestDetailsPage — auth gate', () => {
  it('redirects to /public/login when no token is stored', async () => {
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, {
      route: '/public/request/r-1',
    });
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/login'),
    );
  });

  it('redirects to /public/login and clears token on 401', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get(
        '/api/v1/cases/public/r-1',
        () => new HttpResponse(null, { status: 401 }),
      ),
    );
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, {
      route: '/public/request/r-1',
    });
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/login'),
    );
    expect(localStorage.getItem('token')).toBeNull();
  });
});

describe('RequestDetailsPage — error states', () => {
  it('shows 404 message when request is not found', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get(
        '/api/v1/cases/public/r-1',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/request not found or you do not have access/i),
    ).toBeInTheDocument();
  });

  it('shows generic error on other failures', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get(
        '/api/v1/cases/public/r-1',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/failed to load request details/i),
    ).toBeInTheDocument();
  });

  it('back-to-dashboard button navigates correctly from error state', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get(
        '/api/v1/cases/public/r-1',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    const user = userEvent.setup();
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, {
      route: '/public/request/r-1',
    });
    await screen.findByText(/request not found/i);
    await user.click(
      screen.getByRole('button', { name: /back to dashboard/i }),
    );
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/dashboard'),
    );
  });
});

describe('RequestDetailsPage — happy path', () => {
  it('renders request details, category, due date, and tracking number', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(makeRequestDetails()),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByRole('heading', { name: /my request/i }),
    ).toBeInTheDocument();
    expect(screen.getByText('Need records about X')).toBeInTheDocument();
    expect(screen.getByText('General')).toBeInTheDocument();
    expect(screen.getByText(/tracking number: TRK-001/i)).toBeInTheDocument();
    // Status chip
    expect(screen.getByText(/in progress/i)).toBeInTheDocument();
  });

  it('shows "Not specified" when category is empty', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(makeRequestDetails({ category: '' })),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(await screen.findByText(/not specified/i)).toBeInTheDocument();
  });

  it('hides due date row when due_date is null', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(makeRequestDetails({ due_date: null })),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByRole('heading', { name: /my request/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/due date/i)).not.toBeInTheDocument();
  });

  it('renders all status color branches', async () => {
    localStorage.setItem('token', 'tok');
    for (const status of ['open', 'in_progress', 'completed', 'closed', 'weird']) {
      server.use(
        http.get('/api/v1/cases/public/r-1', () =>
          HttpResponse.json(makeRequestDetails({ status })),
        ),
      );
      const { unmount } = renderWithProviders(<Harness />, {
        route: '/public/request/r-1',
      });
      await screen.findByRole('heading', { name: /my request/i });
      unmount();
    }
  });
});

describe('RequestDetailsPage — back navigation from header', () => {
  it('back-to-dashboard button from header navigates correctly', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(makeRequestDetails()),
      ),
    );
    const user = userEvent.setup();
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, {
      route: '/public/request/r-1',
    });
    await screen.findByRole('heading', { name: /my request/i });
    await user.click(
      screen.getByRole('button', { name: /back to dashboard/i }),
    );
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/dashboard'),
    );
  });
});

describe('RequestDetailsPage — release packages', () => {
  it('renders release packages section with download button when packages exist', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            release_packages: [
              {
                id: 'pkg-1',
                filename: 'release.zip',
                size_bytes: 1024 * 5,
                document_count: 3,
                download_count: 1,
                max_downloads: 5,
                expires_at: '2026-12-31T23:59:59Z',
                access_token: 'access-tok',
                released_at: '2026-05-10T10:00:00Z',
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/available downloads/i),
    ).toBeInTheDocument();
    expect(screen.getByText('release.zip')).toBeInTheDocument();
    expect(screen.getByText(/3 documents/i)).toBeInTheDocument();
    expect(screen.getByText(/5\.0 KB/i)).toBeInTheDocument();
    expect(screen.getByText(/available until/i)).toBeInTheDocument();
    expect(screen.getByText(/downloads: 1 \/ 5/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /download release package/i }),
    ).toBeInTheDocument();
  });

  it('does NOT render release packages section when array is empty', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({ release_packages: [] }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    await screen.findByRole('heading', { name: /my request/i });
    expect(
      screen.queryByText(/available downloads/i),
    ).not.toBeInTheDocument();
  });

  it('renders package without optional expires_at and max_downloads', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            release_packages: [
              {
                id: 'pkg-1',
                filename: 'tiny.zip',
                size_bytes: 500, // < 1KB to hit the bytes branch
                document_count: 1,
                download_count: 0,
                access_token: 'a',
                released_at: '2026-05-10T10:00:00Z',
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(await screen.findByText('tiny.zip')).toBeInTheDocument();
    expect(screen.getByText(/500 B/i)).toBeInTheDocument();
    expect(screen.queryByText(/available until/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/downloads: /i)).not.toBeInTheDocument();
  });

  it('renders MB-size packages correctly', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            release_packages: [
              {
                id: 'p',
                filename: 'big.zip',
                size_bytes: 5 * 1024 * 1024,
                document_count: 10,
                download_count: 0,
                access_token: 't',
                released_at: '2026-05-10T10:00:00Z',
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(await screen.findByText('big.zip')).toBeInTheDocument();
    expect(screen.getByText(/5\.0 MB/)).toBeInTheDocument();
  });

  it('download button opens release URL via window.open', async () => {
    localStorage.setItem('token', 'tok');
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            release_packages: [
              {
                id: 'p',
                filename: 'f.zip',
                size_bytes: 100,
                document_count: 1,
                download_count: 0,
                access_token: 'access-xyz',
                released_at: '2026-05-10T10:00:00Z',
              },
            ],
          }),
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    const dlBtn = await screen.findByRole('button', {
      name: /download release package/i,
    });
    await user.click(dlBtn);
    expect(openSpy).toHaveBeenCalledWith(
      '/api/v1/cases/public/release/access-xyz',
      '_blank',
    );
  });
});

describe('RequestDetailsPage — timeline', () => {
  it('shows the no-events message when timeline is empty', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(makeRequestDetails()),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/no timeline events yet/i),
    ).toBeInTheDocument();
  });

  it('renders known event labels and unknown event titleized', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              { event: 'case_created', timestamp: '2026-05-01T10:00:00Z' },
              { event: 'unknown_event_type', timestamp: '2026-05-02T10:00:00Z' },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/request submitted/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Unknown Event Type/i)).toBeInTheDocument();
  });

  it('formats string event details verbatim', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              {
                event: 'comment_added',
                timestamp: '2026-05-01T10:00:00Z',
                details: 'A free-form note',
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(await screen.findByText('A free-form note')).toBeInTheDocument();
  });

  it('hides details when source is public_portal', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              {
                event: 'case_created',
                timestamp: '2026-05-01T10:00:00Z',
                details: { source: 'public_portal' },
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/request submitted/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/public_portal/i),
    ).not.toBeInTheDocument();
  });

  it('formats status details', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              {
                event: 'status_changed',
                timestamp: '2026-05-01T10:00:00Z',
                details: { status: 'in_progress' },
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(await screen.findByText(/status: in_progress/i)).toBeInTheDocument();
  });

  it('formats assigned_to details', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              {
                event: 'case_assigned',
                timestamp: '2026-05-01T10:00:00Z',
                details: { assigned_to: 'Analyst One' },
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/assigned to: analyst one/i),
    ).toBeInTheDocument();
  });

  it('formats reason details', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              {
                event: 'extension_requested',
                timestamp: '2026-05-01T10:00:00Z',
                details: { reason: 'More time needed' },
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(await screen.findByText('More time needed')).toBeInTheDocument();
  });

  it('formats arbitrary key-value object details', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              {
                event: 'document_uploaded',
                timestamp: '2026-05-01T10:00:00Z',
                details: { filename: 'doc.pdf', size: 1234 },
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/filename: doc\.pdf/i),
    ).toBeInTheDocument();
  });

  it('returns null when all object keys are filtered out (e.g., only non-public-portal source)', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              {
                event: 'case_completed',
                timestamp: '2026-05-01T10:00:00Z',
                details: { source: 'internal_other' },
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    // Detail is null after filtering 'source'; no detail node rendered
    expect(await screen.findByText(/request completed/i)).toBeInTheDocument();
    expect(screen.queryByText(/internal_other/i)).not.toBeInTheDocument();
  });

  it('renders null details cleanly (no detail element when null)', async () => {
    localStorage.setItem('token', 'tok');
    server.use(
      http.get('/api/v1/cases/public/r-1', () =>
        HttpResponse.json(
          makeRequestDetails({
            timeline: [
              {
                event: 'case_completed',
                timestamp: '2026-05-01T10:00:00Z',
                details: null,
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/request/r-1' });
    expect(
      await screen.findByText(/request completed/i),
    ).toBeInTheDocument();
  });
});
