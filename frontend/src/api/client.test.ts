import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';

// IMPORTANT: client.ts builds the axios instance at module-import time and
// captures `getBaseURL()` based on `window.location.protocol` at that moment.
// We need to re-import it in some tests after stubbing location, so the file
// uses dynamic `await import('./client')` everywhere and isolates the module
// registry per-test via `vi.resetModules()`.

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Replace window.location with a writable stub for the duration of a test.
 * jsdom's default window.location is non-configurable, so we have to use
 * Object.defineProperty rather than direct assignment.
 *
 * Returns a teardown that restores the previous descriptor.
 */
function stubLocation(overrides: Partial<Location> = {}): () => void {
  const original = Object.getOwnPropertyDescriptor(window, 'location');
  const fake = {
    href: 'http://localhost/',
    protocol: 'http:',
    host: 'localhost',
    pathname: '/',
    search: '',
    assign: vi.fn(),
    replace: vi.fn(),
    reload: vi.fn(),
    ...overrides,
  } as unknown as Location;
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: fake,
  });
  return () => {
    if (original) {
      Object.defineProperty(window, 'location', original);
    }
  };
}

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// baseURL selection
// ---------------------------------------------------------------------------
describe('client.ts — baseURL selection', () => {
  it('uses the relative /api/v1 baseURL under http (jsdom default)', async () => {
    // jsdom's default protocol is http: — so getBaseURL returns '/api/v1'.
    const { default: api } = await import('./client');
    expect(api.defaults.baseURL).toBe('/api/v1');
  });

  it('uses an absolute https URL when window.location.protocol is https:', async () => {
    const restore = stubLocation({
      protocol: 'https:',
      host: 'example.test',
      pathname: '/',
    });
    try {
      const { default: api } = await import('./client');
      expect(api.defaults.baseURL).toBe('https://example.test/api/v1');
    } finally {
      restore();
    }
  });
});

// ---------------------------------------------------------------------------
// publicApi
// ---------------------------------------------------------------------------
describe('client.ts — publicApi', () => {
  it('shares the same baseURL but is a distinct axios instance', async () => {
    const { default: api, publicApi } = await import('./client');
    expect(publicApi).not.toBe(api);
    expect(publicApi.defaults.baseURL).toBe(api.defaults.baseURL);
  });

  it('does NOT attach the bearer token even when present in localStorage', async () => {
    localStorage.setItem('token', 'should-not-be-sent');
    const { publicApi } = await import('./client');

    let observedAuth: string | null = null;
    server.use(
      http.get('/api/v1/public/ping', ({ request }) => {
        observedAuth = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );

    await publicApi.get('/public/ping');
    expect(observedAuth).toBeNull();
  });

  it('does NOT redirect on 401', async () => {
    const restore = stubLocation({ pathname: '/somewhere' });
    try {
      const { publicApi } = await import('./client');
      server.use(
        http.get(
          '/api/v1/public/ping',
          () => new HttpResponse(null, { status: 401 }),
        ),
      );
      await expect(publicApi.get('/public/ping')).rejects.toThrow();
      // publicApi has no interceptor, so href is unchanged.
      expect(window.location.href).toBe('http://localhost/');
    } finally {
      restore();
    }
  });
});

// ---------------------------------------------------------------------------
// Request interceptor — bearer token
// ---------------------------------------------------------------------------
describe('client.ts — request interceptor (bearer token)', () => {
  it('attaches Authorization: Bearer <token> when localStorage has a token', async () => {
    localStorage.setItem('token', 'abc123');
    const { default: api } = await import('./client');

    let observedAuth: string | null = null;
    server.use(
      http.get('/api/v1/whoami', ({ request }) => {
        observedAuth = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );

    await api.get('/whoami');
    expect(observedAuth).toBe('Bearer abc123');
  });

  it('omits the Authorization header when no token is in localStorage', async () => {
    const { default: api } = await import('./client');

    let observedAuth: string | null = null;
    server.use(
      http.get('/api/v1/whoami', ({ request }) => {
        observedAuth = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );

    await api.get('/whoami');
    expect(observedAuth).toBeNull();
  });

  it('propagates request-side errors via the rejection branch', async () => {
    const { default: api } = await import('./client');

    // Force the request interceptor's request-config function to throw by
    // installing a sabotaging interceptor BEFORE the existing one runs in
    // reverse order (axios runs request interceptors LIFO).
    api.interceptors.request.use(() => {
      throw new Error('boom');
    });
    await expect(api.get('/whoami')).rejects.toThrow(/boom/);
  });
});

// ---------------------------------------------------------------------------
// Response interceptor — 401 redirect + branches
// ---------------------------------------------------------------------------
describe('client.ts — response interceptor (401 redirect)', () => {
  it('on 401 with user_type=public, redirects to /public/login and clears localStorage', async () => {
    localStorage.setItem('token', 'expired');
    localStorage.setItem('user', '{}');
    localStorage.setItem('user_type', 'public');
    localStorage.setItem('userRole', 'r');
    localStorage.setItem('userRoles', '[]');
    localStorage.setItem('userId', 'u1');
    localStorage.setItem('username', 'n');
    localStorage.setItem('magic_link_email', 'm@x.com');

    const restore = stubLocation({ pathname: '/cases/123' });
    try {
      const { default: api } = await import('./client');
      server.use(
        http.get(
          '/api/v1/whoami',
          () => new HttpResponse(null, { status: 401 }),
        ),
      );

      await expect(api.get('/whoami')).rejects.toThrow();

      expect(window.location.href).toBe('/public/login');
      // All auth keys are wiped
      expect(localStorage.getItem('token')).toBeNull();
      expect(localStorage.getItem('user')).toBeNull();
      expect(localStorage.getItem('user_type')).toBeNull();
      expect(localStorage.getItem('userRole')).toBeNull();
      expect(localStorage.getItem('userRoles')).toBeNull();
      expect(localStorage.getItem('userId')).toBeNull();
      expect(localStorage.getItem('username')).toBeNull();
      expect(localStorage.getItem('magic_link_email')).toBeNull();
    } finally {
      restore();
    }
  });

  it('on 401 with no user_type, redirects to /login?redirect=<returnUrl> with pathname+search encoded', async () => {
    const restore = stubLocation({
      pathname: '/cases/42',
      search: '?tab=team&q=hello world',
    });
    try {
      const { default: api } = await import('./client');
      server.use(
        http.get(
          '/api/v1/whoami',
          () => new HttpResponse(null, { status: 401 }),
        ),
      );
      await expect(api.get('/whoami')).rejects.toThrow();

      const expected =
        '/login?redirect=' +
        encodeURIComponent('/cases/42?tab=team&q=hello world');
      expect(window.location.href).toBe(expected);
    } finally {
      restore();
    }
  });

  it('does NOT redirect when already on a /login path (short-circuit)', async () => {
    const restore = stubLocation({ pathname: '/login', href: 'orig-href' });
    try {
      const { default: api } = await import('./client');
      server.use(
        http.get(
          '/api/v1/whoami',
          () => new HttpResponse(null, { status: 401 }),
        ),
      );
      await expect(api.get('/whoami')).rejects.toThrow();
      // href is unchanged because the short-circuit branch was taken
      expect(window.location.href).toBe('orig-href');
      // But localStorage was still cleared
      // (no token was set anyway, but we double-check no crash happened)
      expect(localStorage.getItem('token')).toBeNull();
    } finally {
      restore();
    }
  });

  it('short-circuit also fires when on a public login path (pathname includes /login)', async () => {
    const restore = stubLocation({
      pathname: '/public/login',
      href: 'orig-href',
    });
    try {
      const { default: api } = await import('./client');
      server.use(
        http.get(
          '/api/v1/whoami',
          () => new HttpResponse(null, { status: 401 }),
        ),
      );
      await expect(api.get('/whoami')).rejects.toThrow();
      expect(window.location.href).toBe('orig-href');
    } finally {
      restore();
    }
  });

  it('non-401 errors do NOT trigger redirect or localStorage clearing', async () => {
    localStorage.setItem('token', 'still-good');
    const restore = stubLocation({ pathname: '/somewhere' });
    try {
      const { default: api } = await import('./client');
      server.use(
        http.get(
          '/api/v1/whoami',
          () => new HttpResponse(null, { status: 500 }),
        ),
      );
      await expect(api.get('/whoami')).rejects.toThrow();
      // No navigation
      expect(window.location.href).toBe('http://localhost/');
      // Token retained
      expect(localStorage.getItem('token')).toBe('still-good');
    } finally {
      restore();
    }
  });
});

// ---------------------------------------------------------------------------
// Response interceptor — correlation-ID logging
// ---------------------------------------------------------------------------
describe('client.ts — correlation-ID logging', () => {
  it('logs x-correlation-id and the response body to console.error on error', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { default: api } = await import('./client');

    server.use(
      http.get('/api/v1/whoami', () =>
        HttpResponse.json(
          { detail: 'kaboom' },
          {
            status: 500,
            headers: { 'x-correlation-id': 'corr-xyz' },
          },
        ),
      ),
    );

    await expect(api.get('/whoami')).rejects.toThrow();

    expect(errSpy).toHaveBeenCalledWith(
      'API Error [corr-xyz]:',
      expect.objectContaining({ detail: 'kaboom' }),
    );
  });

  it('does NOT log when the response has no x-correlation-id header', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { default: api } = await import('./client');

    server.use(
      http.get(
        '/api/v1/whoami',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    await expect(api.get('/whoami')).rejects.toThrow();
    // The interceptor should not have called console.error with our correlation prefix.
    const calls = errSpy.mock.calls.map((c) => String(c[0]));
    expect(calls.some((s) => s.startsWith('API Error ['))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// apiClient back-compat class wrapper
// ---------------------------------------------------------------------------
describe('client.ts — apiClient class wrapper', () => {
  it('delegates get() to the underlying axios instance', async () => {
    const { apiClient } = await import('./client');
    server.use(
      http.get('/api/v1/things', () =>
        HttpResponse.json({ things: ['a', 'b'] }),
      ),
    );
    const res = await apiClient.get('/things');
    expect(res.data).toEqual({ things: ['a', 'b'] });
  });

  it('delegates post() and forwards the body', async () => {
    const { apiClient } = await import('./client');
    let received: any = null;
    server.use(
      http.post('/api/v1/things', async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({ created: true });
      }),
    );
    const res = await apiClient.post('/things', { name: 'x' });
    expect(received).toEqual({ name: 'x' });
    expect(res.data).toEqual({ created: true });
  });

  it('delegates put() and forwards the body', async () => {
    const { apiClient } = await import('./client');
    let received: any = null;
    server.use(
      http.put('/api/v1/things/1', async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({ updated: true });
      }),
    );
    const res = await apiClient.put('/things/1', { name: 'y' });
    expect(received).toEqual({ name: 'y' });
    expect(res.data).toEqual({ updated: true });
  });

  it('delegates patch() and forwards the body', async () => {
    const { apiClient } = await import('./client');
    let received: any = null;
    server.use(
      http.patch('/api/v1/things/1', async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({ patched: true });
      }),
    );
    const res = await apiClient.patch('/things/1', { name: 'z' });
    expect(received).toEqual({ name: 'z' });
    expect(res.data).toEqual({ patched: true });
  });

  it('delegates delete() to the underlying axios instance', async () => {
    const { apiClient } = await import('./client');
    server.use(
      http.delete('/api/v1/things/1', () =>
        HttpResponse.json({ deleted: true }),
      ),
    );
    const res = await apiClient.delete('/things/1');
    expect(res.data).toEqual({ deleted: true });
  });

  it('apiClient routes through the same token-attach interceptor as the default export', async () => {
    localStorage.setItem('token', 'shared-tok');
    const { apiClient } = await import('./client');
    let observedAuth: string | null = null;
    server.use(
      http.get('/api/v1/things', ({ request }) => {
        observedAuth = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiClient.get('/things');
    expect(observedAuth).toBe('Bearer shared-tok');
  });
});
