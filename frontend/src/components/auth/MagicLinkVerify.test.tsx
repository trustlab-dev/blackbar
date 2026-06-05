import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import {
  act,
  renderWithProviders,
  screen,
  waitFor,
} from '../../test-utils/render';
import { MagicLinkVerify } from './MagicLinkVerify';

// Helper component that captures the current location for assertions.
function VerifyHarness({
  onNavigate,
}: {
  onNavigate?: (path: string) => void;
}) {
  return (
    <Routes>
      <Route path="/verify/:token" element={<MagicLinkVerify />} />
      <Route
        path="/public/dashboard"
        element={
          <NavCapture
            path="/public/dashboard"
            onNavigate={onNavigate}
          />
        }
      />
      <Route
        path="/public/login"
        element={
          <NavCapture path="/public/login" onNavigate={onNavigate} />
        }
      />
    </Routes>
  );
}

function NavCapture({
  path,
  onNavigate,
}: {
  path: string;
  onNavigate?: (path: string) => void;
}) {
  // Fire on mount so tests can assert navigation
  onNavigate?.(path);
  return <div data-testid="nav-target">{path}</div>;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('MagicLinkVerify — missing token / email', () => {
  it('shows an error when the URL has no token', async () => {
    // Mount at /verify/ - no token param actually matches the route; instead
    // we route directly to the component without :token by using a wildcard.
    renderWithProviders(
      <Routes>
        <Route path="/verify" element={<MagicLinkVerify />} />
      </Routes>,
      { route: '/verify' },
    );
    await waitFor(() =>
      expect(screen.getByText(/verification failed/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/missing token/i)).toBeInTheDocument();
  });

  it('shows a session-expired error if magic_link_email is not stored', async () => {
    renderWithProviders(<VerifyHarness />, { route: '/verify/abc123' });
    await waitFor(() =>
      expect(screen.getByText(/verification failed/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/session expired/i)).toBeInTheDocument();
  });
});

describe('MagicLinkVerify — successful verification', () => {
  it('stores token, userId, user_type, clears magic_link_email and shows success state', async () => {
    localStorage.setItem('magic_link_email', 'a@b.com');
    server.use(
      http.post(
        '/api/v1/auth/public/magic-link/verify',
        async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          expect(body).toEqual({ token: 'abc123', email: 'a@b.com' });
          return HttpResponse.json({
            access_token: 'access-tok-xyz',
            user: { id: 'user-1' },
          });
        },
      ),
    );

    const navSpy = vi.fn();
    renderWithProviders(<VerifyHarness onNavigate={navSpy} />, {
      route: '/verify/abc123',
    });

    await waitFor(() =>
      expect(screen.getByText(/success!/i)).toBeInTheDocument(),
    );
    expect(localStorage.getItem('token')).toBe('access-tok-xyz');
    expect(localStorage.getItem('userId')).toBe('user-1');
    expect(localStorage.getItem('user_type')).toBe('public');
    expect(localStorage.getItem('magic_link_email')).toBeNull();
  });

  it('falls back to user.user_id when user.id is missing', async () => {
    localStorage.setItem('magic_link_email', 'a@b.com');
    server.use(
      http.post('/api/v1/auth/public/magic-link/verify', () =>
        HttpResponse.json({
          access_token: 'tok',
          user: { user_id: 'legacy-id' },
        }),
      ),
    );

    renderWithProviders(<VerifyHarness />, { route: '/verify/abc' });
    await waitFor(() => expect(screen.getByText(/success!/i)).toBeInTheDocument());
    expect(localStorage.getItem('userId')).toBe('legacy-id');
  });

  it('falls back to "" when both id and user_id are missing', async () => {
    localStorage.setItem('magic_link_email', 'a@b.com');
    server.use(
      http.post('/api/v1/auth/public/magic-link/verify', () =>
        HttpResponse.json({ access_token: 'tok', user: {} }),
      ),
    );

    renderWithProviders(<VerifyHarness />, { route: '/verify/abc' });
    await waitFor(() => expect(screen.getByText(/success!/i)).toBeInTheDocument());
    expect(localStorage.getItem('userId')).toBe('');
  });

  it('redirects to /public/dashboard after a short delay on success', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    localStorage.setItem('magic_link_email', 'a@b.com');
    server.use(
      http.post('/api/v1/auth/public/magic-link/verify', () =>
        HttpResponse.json({ access_token: 'tok', user: { id: 'u1' } }),
      ),
    );

    const navSpy = vi.fn();
    renderWithProviders(<VerifyHarness onNavigate={navSpy} />, {
      route: '/verify/abc',
    });

    await waitFor(() => expect(screen.getByText(/success!/i)).toBeInTheDocument());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/public/dashboard'),
    );

    vi.useRealTimers();
  });
});

describe('MagicLinkVerify — failure states', () => {
  it('shows the invalid-token branch on invalid_token error code', async () => {
    localStorage.setItem('magic_link_email', 'a@b.com');
    server.use(
      http.post('/api/v1/auth/public/magic-link/verify', () =>
        HttpResponse.json({ error: 'invalid_token' }, { status: 400 }),
      ),
    );

    renderWithProviders(<VerifyHarness />, { route: '/verify/abc' });
    await waitFor(() =>
      expect(screen.getByText(/this magic link is invalid/i)).toBeInTheDocument(),
    );
  });

  it('surfaces backend detail on other errors', async () => {
    localStorage.setItem('magic_link_email', 'a@b.com');
    server.use(
      http.post('/api/v1/auth/public/magic-link/verify', () =>
        HttpResponse.json({ detail: 'Rate limited' }, { status: 429 }),
      ),
    );

    renderWithProviders(<VerifyHarness />, { route: '/verify/abc' });
    await waitFor(() =>
      expect(screen.getByText('Rate limited')).toBeInTheDocument(),
    );
  });

  it('falls back to default error message when no detail is provided', async () => {
    localStorage.setItem('magic_link_email', 'a@b.com');
    server.use(
      http.post(
        '/api/v1/auth/public/magic-link/verify',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderWithProviders(<VerifyHarness />, { route: '/verify/abc' });
    await waitFor(() =>
      expect(
        screen.getByText(/failed to verify magic link/i),
      ).toBeInTheDocument(),
    );
  });

  it('clicking "Request a new magic link" navigates to /public/login', async () => {
    localStorage.setItem('magic_link_email', 'a@b.com');
    server.use(
      http.post(
        '/api/v1/auth/public/magic-link/verify',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const user = userEvent.setup();
    const navSpy = vi.fn();
    renderWithProviders(<VerifyHarness onNavigate={navSpy} />, {
      route: '/verify/abc',
    });
    await waitFor(() =>
      expect(
        screen.getByText(/failed to verify magic link/i),
      ).toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole('button', { name: /request a new magic link/i }),
    );
    await waitFor(() => expect(navSpy).toHaveBeenCalledWith('/public/login'));
  });
});

describe('MagicLinkVerify — verifying state', () => {
  it('shows a spinner while the request is in flight', async () => {
    localStorage.setItem('magic_link_email', 'a@b.com');
    let resolve: () => void = () => {};
    const ready = new Promise<void>((r) => {
      resolve = r;
    });
    server.use(
      http.post('/api/v1/auth/public/magic-link/verify', async () => {
        await ready;
        return HttpResponse.json({ access_token: 't', user: { id: 'u' } });
      }),
    );

    renderWithProviders(<VerifyHarness />, { route: '/verify/abc' });
    expect(screen.getByText(/verifying your magic link/i)).toBeInTheDocument();
    resolve();
    await waitFor(() => expect(screen.getByText(/success!/i)).toBeInTheDocument());
  });
});
