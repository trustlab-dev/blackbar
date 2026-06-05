import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, renderHook, waitFor, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';
import { AuthProvider, useAuth } from './AuthContext';
import type { ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a JWT-shaped token whose `exp` claim is `secondsFromNow` seconds in
 * the future (negative = expired). We don't need the signature to be valid;
 * jwt-decode only reads the payload.
 */
function makeJwt(secondsFromNow: number): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = btoa(
    JSON.stringify({
      sub: 'user-1',
      exp: Math.floor(Date.now() / 1000) + secondsFromNow,
    })
  );
  const signature = 'sig';
  return `${header}.${payload}.${signature}`;
}

const wrapper = ({ children }: { children: ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

// Note: api/client.ts 401 interceptor assigns to window.location.href.
// Under jsdom this triggers a "Not implemented: navigation" warning via
// console.error. We don't stub window.location here (MSW relies on it to
// resolve relative URLs) — instead, tests that assert console.error
// behavior do so AFTER the act so the assertion sees both the navigation
// warning AND the AuthContext logs.
beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// useAuth hook guard
// ---------------------------------------------------------------------------
describe('useAuth (outside provider)', () => {
  it('throws if used outside of AuthProvider', () => {
    // Suppress React's error-boundary logging for this expected throw.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useAuth())).toThrow(
      /useAuth must be used within an AuthProvider/,
    );
    errSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// Initial state (no token)
// ---------------------------------------------------------------------------
describe('AuthProvider — initial state', () => {
  it('starts unauthenticated with no token and finishes loading', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.user).toBeNull();
    expect(result.current.token).toBeNull();
    expect(result.current.roles).toEqual([]);
    expect(result.current.isAuthenticated).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Restore from localStorage on mount
// ---------------------------------------------------------------------------
describe('AuthProvider — load from localStorage on mount', () => {
  it('loads a valid token, fetches the user, and becomes authenticated', async () => {
    const token = makeJwt(3600);
    localStorage.setItem('token', token);

    server.use(
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

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(result.current.token).toBe(token);
    expect(result.current.user?.name).toBe('Alice');
    expect(result.current.roles).toEqual(['admin']);
    // Username is persisted for fast next-load display
    expect(localStorage.getItem('username')).toBe('Alice');
  });

  it('does NOT persist username when /auth/me omits name', async () => {
    const token = makeJwt(3600);
    localStorage.setItem('token', token);

    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'user-1',
          email: 'a@b.com',
          name: '',
          status: 'active',
          roles: [],
        }),
      ),
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(localStorage.getItem('username')).toBeNull();
  });

  it('defaults roles to [] when /auth/me omits roles', async () => {
    const token = makeJwt(3600);
    localStorage.setItem('token', token);

    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'user-1',
          email: 'a@b.com',
          name: 'NoRoles',
          status: 'active',
          // no roles key
        }),
      ),
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user?.name).toBe('NoRoles'));
    expect(result.current.roles).toEqual([]);
  });

  it('logs out when the stored token is expired', async () => {
    const expired = makeJwt(-3600);
    localStorage.setItem('token', expired);
    localStorage.setItem('username', 'stale');

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.token).toBeNull();
    // logout() clears the auth-related keys
    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('username')).toBeNull();
  });

  it('treats an undecodable token as expired and stays unauthenticated', async () => {
    localStorage.setItem('token', 'not-a-jwt');
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('logs an error and logs out when /auth/me fails', async () => {
    const token = makeJwt(3600);
    localStorage.setItem('token', token);

    server.use(
      http.get(
        '/api/v1/auth/me',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(errSpy).toHaveBeenCalled();
    expect(localStorage.getItem('token')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// login
// ---------------------------------------------------------------------------
describe('AuthProvider — login', () => {
  it('stores token, roles, userId and fetches the current user', async () => {
    const token = makeJwt(3600);

    let postBody: any = null;
    server.use(
      http.post('/api/v1/auth/login', async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({
          access_token: token,
          roles: ['admin'],
          user_id: 'user-1',
        });
      }),
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

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.login('a@b.com', 'pw');
    });

    expect(postBody).toEqual({ email: 'a@b.com', password: 'pw' });
    expect(result.current.token).toBe(token);
    expect(result.current.isAuthenticated).toBe(true);
    expect(localStorage.getItem('token')).toBe(token);
    expect(localStorage.getItem('userId')).toBe('user-1');
    expect(JSON.parse(localStorage.getItem('userRoles')!)).toEqual(['admin']);
  });

  it('skips userId persistence when not returned by the backend', async () => {
    const token = makeJwt(3600);
    server.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({
          access_token: token,
          roles: ['analyst'],
          // no user_id
        }),
      ),
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'user-1',
          email: 'a@b.com',
          name: 'A',
          status: 'active',
          roles: ['analyst'],
        }),
      ),
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.login('a@b.com', 'pw');
    });

    expect(localStorage.getItem('userId')).toBeNull();
    expect(localStorage.getItem('token')).toBe(token);
  });

  it('rethrows the underlying axios error so callers can read response.data', async () => {
    server.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({ detail: 'Bad credentials' }, { status: 401 }),
      ),
    );

    // Swallow stderr noise (AuthContext logs the error). We assert on the
    // thrown error shape, which Login.tsx and any other caller relies
    // on for surfacing backend-specific messages.
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let captured: any;
    await act(async () => {
      try {
        await result.current.login('a@b.com', 'pw');
      } catch (e) {
        captured = e;
      }
    });
    // Phase 4 Batch 4.4 (audit F1): AuthContext.login now re-throws
    // the original axios error instead of `new Error(detail)`, so
    // callers can branch on `err.response?.data?.detail` or
    // `err.response?.data?.error?.message`.
    expect(captured).toBeDefined();
    expect(captured.response?.status).toBe(401);
    expect(captured.response?.data?.detail).toBe('Bad credentials');
  });

  it('rethrows the original error when the response has no detail', async () => {
    server.use(
      http.post(
        '/api/v1/auth/login',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let captured: any;
    await act(async () => {
      try {
        await result.current.login('a@b.com', 'pw');
      } catch (e) {
        captured = e;
      }
    });
    // Phase 4 Batch 4.4 (audit F1): the rethrown error preserves the
    // axios envelope; the 500 status is observable.
    expect(captured).toBeDefined();
    expect(captured.response?.status).toBe(500);
  });
});

// ---------------------------------------------------------------------------
// logout
// ---------------------------------------------------------------------------
describe('AuthProvider — logout', () => {
  it('clears state and all auth-related localStorage keys', async () => {
    const token = makeJwt(3600);
    localStorage.setItem('token', token);
    localStorage.setItem('username', 'Alice');
    localStorage.setItem('userRole', 'admin');
    localStorage.setItem('userId', 'user-1');
    localStorage.setItem('userRoles', JSON.stringify(['admin']));
    localStorage.setItem('user', '{"name":"Alice"}');
    localStorage.setItem('user_type', 'internal');
    localStorage.setItem('magic_link_email', 'a@b.com');
    localStorage.setItem('dev_current_user', 'admin');
    // unrelated key — should NOT be cleared
    localStorage.setItem('preserve-me', '1');

    server.use(
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

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    act(() => {
      result.current.logout();
    });

    expect(result.current.user).toBeNull();
    expect(result.current.token).toBeNull();
    expect(result.current.roles).toEqual([]);
    expect(result.current.isAuthenticated).toBe(false);

    [
      'token', 'username', 'userRole', 'userId', 'userRoles',
      'user', 'user_type', 'magic_link_email', 'dev_current_user',
    ].forEach((k) => {
      expect(localStorage.getItem(k)).toBeNull();
    });
    expect(localStorage.getItem('preserve-me')).toBe('1');
  });
});

// ---------------------------------------------------------------------------
// Periodic token-expiration check (60s interval)
// ---------------------------------------------------------------------------
describe('AuthProvider — periodic token expiration check', () => {
  it('logs out when the interval ticks and the token has expired', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const token = makeJwt(3600);
    localStorage.setItem('token', token);

    server.use(
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

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    // Jump past the JWT expiry, then advance the 60s heartbeat.
    vi.setSystemTime(new Date(Date.now() + 3700 * 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.token).toBeNull();

    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// Provider renders children
// ---------------------------------------------------------------------------
describe('AuthProvider — children rendering', () => {
  it('renders its children', () => {
    render(
      <AuthProvider>
        <div data-testid="child">hi</div>
      </AuthProvider>,
    );
    expect(screen.getByTestId('child')).toHaveTextContent('hi');
  });
});
