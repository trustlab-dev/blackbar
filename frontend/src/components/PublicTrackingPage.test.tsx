import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import { server } from '../test-utils/msw-handlers';
import {
  renderWithProviders,
  screen,
  waitFor,
} from '../test-utils/render';
import PublicTrackingPage from './PublicTrackingPage';

function Harness() {
  return (
    <Routes>
      <Route path="/track/:trackingNumber" element={<PublicTrackingPage />} />
      <Route path="/track" element={<PublicTrackingPage />} />
    </Routes>
  );
}

function makeTrackingData(overrides: any = {}) {
  return {
    tracking_number: 'TRK-001',
    title: 'My Request',
    status: 'new',
    received_date: '2026-05-01T10:00:00Z',
    due_date: '2026-06-01T10:00:00Z',
    sla_status: 'on_track',
    comments: [],
    last_updated: '2026-05-02T10:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  // Nothing
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('PublicTrackingPage — loading state', () => {
  it('shows loading text before data arrives', () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        new Promise(() => {}),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});

describe('PublicTrackingPage — error states', () => {
  it('shows backend detail error message', async () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        HttpResponse.json({ detail: 'Tracking number not found' }, { status: 404 }),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    expect(
      await screen.findByText(/tracking number not found/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /submit a new request/i }),
    ).toHaveAttribute('href', '/request');
  });

  it('falls back to default error message when no detail provided', async () => {
    server.use(
      http.get(
        '/api/v1/cases/public/track/TRK-001',
        () => new HttpResponse(null, { status: 500 }),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    expect(
      await screen.findByText(/tracking number not found/i),
    ).toBeInTheDocument();
  });
});

describe('PublicTrackingPage — happy path', () => {
  it('renders tracking number, title, status, dates, and on-track SLA badge', async () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        HttpResponse.json(makeTrackingData()),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    expect(await screen.findByText('TRK-001')).toBeInTheDocument();
    expect(screen.getByText('My Request')).toBeInTheDocument();
    expect(screen.getByText(/^new$/i)).toBeInTheDocument();
    expect(screen.getByText(/on track/i)).toBeInTheDocument();
  });

  it('renders overdue SLA badge', async () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        HttpResponse.json(makeTrackingData({ sla_status: 'overdue' })),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    expect(await screen.findByText(/overdue/i)).toBeInTheDocument();
  });

  it('renders due-soon SLA badge', async () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        HttpResponse.json(makeTrackingData({ sla_status: 'due_soon' })),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    expect(await screen.findByText(/due soon/i)).toBeInTheDocument();
  });

  it('renders all status label and color branches', async () => {
    const statuses = ['new', 'in_progress', 'review', 'on_hold', 'completed', 'closed', 'unknown_status'];
    for (const status of statuses) {
      server.use(
        http.get('/api/v1/cases/public/track/TRK-001', () =>
          HttpResponse.json(makeTrackingData({ status })),
        ),
        http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      );
      const { unmount } = renderWithProviders(<Harness />, {
        route: '/track/TRK-001',
      });
      await screen.findByText('TRK-001');
      unmount();
    }
  });

  it('renders comments when present', async () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        HttpResponse.json(
          makeTrackingData({
            comments: [
              {
                id: 'c1',
                author_name: 'Analyst A',
                text: 'We need more info',
                type: 'note',
                created_at: '2026-05-02T10:00:00Z',
              },
            ],
          }),
        ),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    expect(await screen.findByText(/we need more info/i)).toBeInTheDocument();
    expect(screen.getByText(/analyst a/i)).toBeInTheDocument();
  });

  it('does NOT render comments section when array is empty', async () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        HttpResponse.json(makeTrackingData()),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    await screen.findByText('TRK-001');
    // 'Updates' h2 in the comments card; only present when there are comments
    expect(screen.queryByRole('heading', { name: /^updates$/i })).not.toBeInTheDocument();
  });
});

describe('PublicTrackingPage — footer text', () => {
  it('renders footer text when provided by public config', async () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        HttpResponse.json(makeTrackingData()),
      ),
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({ footer_text: 'Some legal footer' }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    expect(await screen.findByText(/some legal footer/i)).toBeInTheDocument();
  });

  it('handles config fetch failure silently', async () => {
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        HttpResponse.json(makeTrackingData()),
      ),
      http.get(
        '/api/v1/admin/config/public',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderWithProviders(<Harness />, { route: '/track/TRK-001' });
    await screen.findByText('TRK-001');
    // No crash — footer just doesn't render
  });
});

describe('PublicTrackingPage — defensive null guard', () => {
  it('returns null when fetch succeeds but data is null', async () => {
    // Engineer a path where setError(''), setLoading(false), setData(null) all
    // happen — by returning a 200 with explicit null JSON. The component
    // does setData(response.data) which would be null, then the guard at
    // `if (!data) return null` fires.
    server.use(
      http.get('/api/v1/cases/public/track/TRK-001', () =>
        new HttpResponse('null', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    const { container } = renderWithProviders(<Harness />, {
      route: '/track/TRK-001',
    });
    // Wait for loading to clear (data set to null)
    await waitFor(() =>
      expect(screen.queryByText(/loading/i)).not.toBeInTheDocument(),
    );
    // No tracking content rendered
    expect(screen.queryByText('TRK-001')).not.toBeInTheDocument();
  });
});

describe('PublicTrackingPage — missing tracking number', () => {
  it('still calls config and stays loading without trackingNumber param', () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/track' });
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});
