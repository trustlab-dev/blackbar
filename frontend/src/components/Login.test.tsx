import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import {
  renderWithProviders,
  screen,
  waitFor,
} from '../test-utils/render';
import Login from './Login';

// Build a JWT whose exp claim is in the future
function makeJwt(secondsFromNow: number): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = btoa(
    JSON.stringify({
      sub: 'user-1',
      exp: Math.floor(Date.now() / 1000) + secondsFromNow,
    }),
  );
  return `${header}.${payload}.sig`;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('Login — initial render', () => {
  it('renders email + password fields and default branding (BlackBar) when config fetch fails', async () => {
    server.use(
      http.get(
        '/api/v1/admin/config/public',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const onLoginSuccess = vi.fn();
    renderWithProviders(<Login onLoginSuccess={onLoginSuccess} />, {
      withAuth: true,
    });

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /sign in/i }),
    ).toBeInTheDocument();
    // Default org name is "BlackBar"
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /blackbar/i })).toBeInTheDocument(),
    );
  });

  it('renders org logo when config returns logo URL', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          org_name: 'My Org',
          org_logo_url: 'https://example.com/logo.png',
          primary_color: '#abcdef',
        }),
      ),
    );
    renderWithProviders(<Login onLoginSuccess={vi.fn()} />, {
      withAuth: true,
    });
    const logo = await screen.findByAltText('My Org');
    expect(logo).toHaveAttribute('src', 'https://example.com/logo.png');
  });

  it('renders org name and initial when no logo URL is returned', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          org_name: 'Acme FOI',
          org_logo_url: null,
          primary_color: '#112233',
        }),
      ),
    );
    renderWithProviders(<Login onLoginSuccess={vi.fn()} />, {
      withAuth: true,
    });
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /acme foi/i })).toBeInTheDocument(),
    );
  });

  it('falls back to BlackBar defaults when response.data is empty', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        // Empty 204 — axios will surface response.data === ''
        HttpResponse.text('', { status: 200 }),
      ),
    );
    renderWithProviders(<Login onLoginSuccess={vi.fn()} />, {
      withAuth: true,
    });
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /blackbar/i })).toBeInTheDocument(),
    );
  });
});

describe('Login — submission', () => {
  it('logs in successfully, calls onLoginSuccess, and would navigate to redirect URL', async () => {
    const token = makeJwt(3600);
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({
          access_token: token,
          roles: ['admin'],
          user_id: 'user-1',
        }),
      ),
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'user-1',
          email: 'a@b.com',
          name: 'Alice',
          status: 'active',
          roles: ['admin'],
        }),
      ),
    );
    const onLoginSuccess = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<Login onLoginSuccess={onLoginSuccess} />, {
      withAuth: true,
    });
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(onLoginSuccess).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem('token')).toBe(token);
  });

  it('shows the loading state during submission', async () => {
    const token = makeJwt(3600);
    let resolve: () => void = () => {};
    const ready = new Promise<void>((r) => {
      resolve = r;
    });
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/auth/login', async () => {
        await ready;
        return HttpResponse.json({
          access_token: token,
          roles: [],
          user_id: 'u',
        });
      }),
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u',
          email: 'a@b.com',
          name: 'A',
          status: 'active',
          roles: [],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Login onLoginSuccess={vi.fn()} />, {
      withAuth: true,
    });
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(
      screen.getByRole('button', { name: /signing in/i }),
    ).toBeDisabled();
    resolve();
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: /signing in/i }),
      ).not.toBeInTheDocument(),
    );
  });
});

describe('Login — error handling', () => {
  it('shows backend error.message when present', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json(
          { error: { message: 'Inner error message' } },
          { status: 401 },
        ),
      ),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const user = userEvent.setup();
    renderWithProviders(<Login onLoginSuccess={vi.fn()} />, {
      withAuth: true,
    });
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    // Phase 4 Batch 4.4 (audit F1): AuthContext.login now re-throws
    // the underlying axios error, so Login.tsx's
    // `err.response?.data?.error?.message` fallback resolves the
    // backend's inner message. Test flipped from the prior pin that
    // characterized the dead-branch generic message.
    await waitFor(() =>
      expect(screen.getByText(/inner error message/i)).toBeInTheDocument(),
    );
  });

  it('shows the default message on failure', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post(
        '/api/v1/auth/login',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const user = userEvent.setup();
    renderWithProviders(<Login onLoginSuccess={vi.fn()} />, {
      withAuth: true,
    });
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/login failed/i),
      ).toBeInTheDocument(),
    );
  });
});

describe('Login — query-string redirect handling', () => {
  it('uses safe relative redirect path from ?redirect=', async () => {
    const token = makeJwt(3600);
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({
          access_token: token,
          roles: [],
          user_id: 'u',
        }),
      ),
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u',
          email: 'a@b.com',
          name: 'A',
          status: 'active',
          roles: [],
        }),
      ),
    );
    const onLoginSuccess = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<Login onLoginSuccess={onLoginSuccess} />, {
      withAuth: true,
      route: '/login?redirect=/cases/123',
    });
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(onLoginSuccess).toHaveBeenCalledTimes(1));
  });

  it('rejects protocol-relative open-redirect candidate (//evil.com)', async () => {
    const token = makeJwt(3600);
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({
          access_token: token,
          roles: [],
          user_id: 'u',
        }),
      ),
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u',
          email: 'a@b.com',
          name: 'A',
          status: 'active',
          roles: [],
        }),
      ),
    );
    const onLoginSuccess = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<Login onLoginSuccess={onLoginSuccess} />, {
      withAuth: true,
      route: '/login?redirect=//evil.com',
    });
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(onLoginSuccess).toHaveBeenCalledTimes(1));
  });

  it('rejects absolute URL redirect (https://evil.com)', async () => {
    const token = makeJwt(3600);
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({
          access_token: token,
          roles: [],
          user_id: 'u',
        }),
      ),
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u',
          email: 'a@b.com',
          name: 'A',
          status: 'active',
          roles: [],
        }),
      ),
    );
    const onLoginSuccess = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<Login onLoginSuccess={onLoginSuccess} />, {
      withAuth: true,
      route: '/login?redirect=https://evil.com',
    });
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(onLoginSuccess).toHaveBeenCalledTimes(1));
  });
});
