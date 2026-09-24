import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Sentry and web-vitals are mocked at the import level — telemetry.ts is a
// thin wrapper, so these tests assert it forwards to the SDK correctly
// (or no-ops) depending on whether VITE_SENTRY_DSN is configured.
const sentryMock = vi.hoisted(() => ({
  init: vi.fn(),
  setUser: vi.fn(),
  setContext: vi.fn(),
  setMeasurement: vi.fn(),
  addBreadcrumb: vi.fn(),
  captureException: vi.fn(),
  captureMessage: vi.fn(),
  withScope: vi.fn((cb: (scope: any) => void) =>
    cb({ setExtras: vi.fn() }),
  ),
  startInactiveSpan: vi.fn(() => ({ end: vi.fn() })),
  addEventProcessor: vi.fn(),
  breadcrumbsIntegration: vi.fn(() => 'breadcrumbs'),
  browserTracingIntegration: vi.fn(() => 'browser-tracing'),
  replayIntegration: vi.fn(() => 'replay'),
  ErrorBoundary: 'ErrorBoundary',
  withProfiler: vi.fn(),
  withErrorBoundary: vi.fn(),
}));

const vitalsMock = vi.hoisted(() => ({
  getCLS: vi.fn(),
  getFID: vi.fn(),
  getFCP: vi.fn(),
  getLCP: vi.fn(),
  getTTFB: vi.fn(),
}));

vi.mock('@sentry/react', () => sentryMock);
vi.mock('web-vitals', () => vitalsMock);

/**
 * Re-import telemetry.ts with a given env so the module-level SENTRY_DSN /
 * ENVIRONMENT constants are recomputed. Returns the fresh module namespace.
 */
async function loadTelemetry(env: Record<string, string>, prodBuild = false) {
  vi.resetModules();
  vi.stubEnv('PROD', prodBuild);
  vi.stubEnv('VITE_SENTRY_DSN', env.VITE_SENTRY_DSN ?? '');
  vi.stubEnv('VITE_ENVIRONMENT', env.VITE_ENVIRONMENT ?? 'development');
  vi.stubEnv('VITE_VERSION', env.VITE_VERSION ?? '1.0.0');
  return import('./telemetry');
}

beforeEach(() => {
  Object.values(sentryMock).forEach((v) => {
    if (typeof v === 'function' && 'mockClear' in v) v.mockClear();
  });
  Object.values(vitalsMock).forEach((v) => v.mockClear());
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('initTelemetry — DSN configured', () => {
  it('initializes Sentry with the configured DSN and registers web vitals', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({
      VITE_SENTRY_DSN: 'https://key@sentry.io/1',
      VITE_ENVIRONMENT: 'production',
      VITE_VERSION: '2.3.4',
    });
    t.initTelemetry();

    expect(sentryMock.init).toHaveBeenCalledTimes(1);
    const cfg = sentryMock.init.mock.calls[0][0];
    expect(cfg.dsn).toBe('https://key@sentry.io/1');
    expect(cfg.environment).toBe('production');
    expect(cfg.release).toBe('blackbar-frontend@2.3.4');
    expect(cfg.tracesSampleRate).toBe(0.1);

    expect(vitalsMock.getCLS).toHaveBeenCalled();
    expect(vitalsMock.getFID).toHaveBeenCalled();
    expect(vitalsMock.getFCP).toHaveBeenCalled();
    expect(vitalsMock.getLCP).toHaveBeenCalled();
    expect(vitalsMock.getTTFB).toHaveBeenCalled();
  });

  it('uses a full traces sample rate outside production', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({
      VITE_SENTRY_DSN: 'https://key@sentry.io/1',
      VITE_ENVIRONMENT: 'staging',
    });
    t.initTelemetry();
    expect(sentryMock.init.mock.calls[0][0].tracesSampleRate).toBe(1.0);
  });

  it('beforeSend strips sensitive headers and filters PII breadcrumbs', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.initTelemetry();
    const { beforeSend } = sentryMock.init.mock.calls[0][0];

    const event = {
      request: {
        headers: { Authorization: 'Bearer x', Cookie: 'c', 'X-Keep': 'ok' },
      },
      breadcrumbs: [
        { data: { email: 'a@b.com', other: 1 } },
        { data: { other: 2 } },
        {},
      ],
    };
    const result = beforeSend(event);
    expect(result.request.headers.Authorization).toBeUndefined();
    expect(result.request.headers.Cookie).toBeUndefined();
    expect(result.request.headers['X-Keep']).toBe('ok');
    expect(result.breadcrumbs[0].data.email).toBe('[FILTERED]');
    expect(result.breadcrumbs[1].data.email).toBeUndefined();
  });

  it('wires the scrubbing hooks, disables default PII and console breadcrumbs', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.initTelemetry();
    const cfg = sentryMock.init.mock.calls[0][0];
    expect(cfg.sendDefaultPii).toBe(false);
    expect(cfg.beforeBreadcrumb).toBe(t.scrubBreadcrumb);
    expect(cfg.beforeSend).toBe(t.scrubEvent);
    expect(cfg.beforeSendTransaction).toBe(t.scrubEvent);
    expect(sentryMock.breadcrumbsIntegration).toHaveBeenCalledWith({ console: false });
    expect(sentryMock.replayIntegration).toHaveBeenCalledWith(
      expect.objectContaining({
        maskAllText: true,
        blockAllMedia: true,
        beforeAddRecordingEvent: t.scrubRecordingEvent,
      }),
    );
    expect(sentryMock.addEventProcessor).toHaveBeenCalledWith(t.scrubEvent);
  });

  it('uses low sample rates for a production build even when VITE_ENVIRONMENT is unset', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.resetModules();
    vi.stubEnv('PROD', true);
    vi.stubEnv('VITE_SENTRY_DSN', 'https://key@sentry.io/1');
    vi.stubEnv('VITE_ENVIRONMENT', '');
    const t = await import('./telemetry');
    t.initTelemetry();
    const cfg = sentryMock.init.mock.calls[0][0];
    expect(cfg.environment).toBe('production');
    expect(cfg.tracesSampleRate).toBe(0.1);
    expect(cfg.replaysSessionSampleRate).toBe(0);
    expect(cfg.replaysOnErrorSampleRate).toBe(0.1);
  });

  it('uses full sample rates in a development build', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.initTelemetry();
    const cfg = sentryMock.init.mock.calls[0][0];
    expect(cfg.tracesSampleRate).toBe(1.0);
    expect(cfg.replaysSessionSampleRate).toBe(0.1);
    expect(cfg.replaysOnErrorSampleRate).toBe(1.0);
  });

  it('beforeSend handles events without request headers or breadcrumbs', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.initTelemetry();
    const { beforeSend } = sentryMock.init.mock.calls[0][0];
    expect(beforeSend({})).toEqual({});
  });
});

describe('initTelemetry — DSN not configured', () => {
  it('does not initialize Sentry but still registers web vitals', async () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: '' });
    t.initTelemetry();
    expect(sentryMock.init).not.toHaveBeenCalled();
    expect(logSpy).toHaveBeenCalledWith(
      '[Telemetry] Sentry DSN not configured, error tracking disabled',
    );
    expect(vitalsMock.getCLS).toHaveBeenCalled();
  });
});

describe('web vitals reporting callback', () => {
  async function getReporter(env: Record<string, string>) {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry(env);
    t.initTelemetry();
    // Every getX receives the same reportVital callback.
    return vitalsMock.getCLS.mock.calls[0][0] as (m: any) => void;
  }

  it('logs vitals in development and rates good metrics', async () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_ENVIRONMENT: 'development' });
    t.initTelemetry();
    const report = vitalsMock.getCLS.mock.calls[0][0] as (m: any) => void;
    report({ name: 'LCP', value: 1000 });
    expect(logSpy).toHaveBeenCalledWith(
      expect.stringContaining('[Web Vitals] LCP: 1000.00 (good)'),
    );
  });

  it('does not log vitals in production but sends them to Sentry as measurements', async () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const report = await getReporter({
      VITE_SENTRY_DSN: 'https://key@sentry.io/1',
      VITE_ENVIRONMENT: 'production',
    });
    logSpy.mockClear();
    report({ name: 'FCP', value: 500 });
    expect(
      logSpy.mock.calls.some((c) => String(c[0]).includes('[Web Vitals]')),
    ).toBe(false);
    expect(sentryMock.setMeasurement).toHaveBeenCalledWith(
      'FCP',
      500,
      'millisecond',
    );
  });

  it('uses an empty unit for the unitless CLS measurement', async () => {
    const report = await getReporter({
      VITE_SENTRY_DSN: 'https://key@sentry.io/1',
      VITE_ENVIRONMENT: 'production',
    });
    report({ name: 'CLS', value: 0.05 });
    expect(sentryMock.setMeasurement).toHaveBeenCalledWith('CLS', 0.05, '');
  });

  it('tracks a poor-performance event when a metric exceeds its threshold', async () => {
    const report = await getReporter({ VITE_ENVIRONMENT: 'development' });
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    report({ name: 'LCP', value: 9999 });
    // trackEvent logs "[Telemetry] Event: web_vital_poor" in development.
    expect(
      logSpy.mock.calls.some(
        (c) => String(c[0]) === '[Telemetry] Event: web_vital_poor',
      ),
    ).toBe(true);
  });

  it('rates an unknown metric name as "unknown" and skips threshold tracking', async () => {
    const report = await getReporter({ VITE_ENVIRONMENT: 'development' });
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    report({ name: 'INP', value: 123 });
    expect(logSpy).toHaveBeenCalledWith(
      expect.stringContaining('(unknown)'),
    );
  });
});

describe('setUser / clearUser / setContext', () => {
  it('forwards to Sentry when the DSN is configured', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.setUser('user-1', 'u@example.com');
    expect(sentryMock.setUser).toHaveBeenCalledWith({
      id: 'user-1',
      email: 'u@example.com',
    });
    t.clearUser();
    expect(sentryMock.setUser).toHaveBeenLastCalledWith(null);
    t.setContext('case', { id: 'c1' });
    expect(sentryMock.setContext).toHaveBeenCalledWith('case', { id: 'c1' });
  });

  it('no-ops when the DSN is not configured', async () => {
    const t = await loadTelemetry({ VITE_SENTRY_DSN: '' });
    t.setUser('user-1');
    t.clearUser();
    t.setContext('case', {});
    expect(sentryMock.setUser).not.toHaveBeenCalled();
    expect(sentryMock.setContext).not.toHaveBeenCalled();
  });
});

describe('addBreadcrumb / trackEvent', () => {
  it('adds a breadcrumb via Sentry when configured', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.addBreadcrumb('did a thing', 'nav', { a: 1 });
    expect(sentryMock.addBreadcrumb).toHaveBeenCalledWith({
      message: 'did a thing',
      category: 'nav',
      data: { a: 1 },
      level: 'info',
    });
  });

  it('addBreadcrumb no-ops without a DSN', async () => {
    const t = await loadTelemetry({ VITE_SENTRY_DSN: '' });
    t.addBreadcrumb('msg');
    expect(sentryMock.addBreadcrumb).not.toHaveBeenCalled();
  });

  it('trackEvent logs in development and records a breadcrumb', async () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({
      VITE_SENTRY_DSN: 'https://key@sentry.io/1',
      VITE_ENVIRONMENT: 'development',
    });
    t.trackEvent('my_event', { k: 'v' });
    expect(sentryMock.addBreadcrumb).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Event: my_event', category: 'event' }),
    );
    expect(logSpy).toHaveBeenCalledWith('[Telemetry] Event: my_event', {
      k: 'v',
    });
  });

  it('trackEvent does not log in production', async () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_ENVIRONMENT: 'production' });
    logSpy.mockClear();
    t.trackEvent('my_event');
    expect(
      logSpy.mock.calls.some((c) => String(c[0]).includes('[Telemetry] Event')),
    ).toBe(false);
  });
});

describe('captureError / captureMessage', () => {
  it('always logs the error and forwards to Sentry with context when configured', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    const err = new Error('boom');
    t.captureError(err, { caseId: 'c1' });
    expect(errSpy).toHaveBeenCalledWith('[Telemetry] Error captured:', err);
    expect(sentryMock.withScope).toHaveBeenCalled();
    expect(sentryMock.captureException).toHaveBeenCalledWith(err);
  });

  it('captureError logs but does not call Sentry when no DSN is set', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: '' });
    t.captureError(new Error('boom'));
    expect(errSpy).toHaveBeenCalled();
    expect(sentryMock.withScope).not.toHaveBeenCalled();
  });

  it('captureError works without a context object', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.captureError(new Error('boom'));
    expect(sentryMock.captureException).toHaveBeenCalled();
  });

  it('captureMessage forwards to Sentry with the given level when configured', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.captureMessage('hello', 'warning');
    expect(sentryMock.captureMessage).toHaveBeenCalledWith('hello', 'warning');
  });

  it('captureMessage defaults to the info level', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.captureMessage('hello');
    expect(sentryMock.captureMessage).toHaveBeenCalledWith('hello', 'info');
  });

  it('captureMessage no-ops without a DSN', async () => {
    const t = await loadTelemetry({ VITE_SENTRY_DSN: '' });
    t.captureMessage('hello');
    expect(sentryMock.captureMessage).not.toHaveBeenCalled();
  });
});

describe('startTransaction', () => {
  it('starts an inactive Sentry span when configured', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    const span = t.startTransaction('load', 'navigation');
    expect(sentryMock.startInactiveSpan).toHaveBeenCalledWith({
      name: 'load',
      op: 'navigation',
    });
    expect(span).toBeDefined();
  });

  it('defaults the op to "navigation"', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const t = await loadTelemetry({ VITE_SENTRY_DSN: 'https://key@sentry.io/1' });
    t.startTransaction('load');
    expect(sentryMock.startInactiveSpan).toHaveBeenCalledWith({
      name: 'load',
      op: 'navigation',
    });
  });

  it('returns undefined when no DSN is configured', async () => {
    const t = await loadTelemetry({ VITE_SENTRY_DSN: '' });
    expect(t.startTransaction('load')).toBeUndefined();
    expect(sentryMock.startInactiveSpan).not.toHaveBeenCalled();
  });
});

describe('re-exported Sentry helpers', () => {
  it('re-exports ErrorBoundary, Profiler, and withErrorBoundary from Sentry', async () => {
    const t = await loadTelemetry({ VITE_SENTRY_DSN: '' });
    expect(t.ErrorBoundary).toBe(sentryMock.ErrorBoundary);
    expect(t.Profiler).toBe(sentryMock.withProfiler);
    expect(t.withErrorBoundary).toBe(sentryMock.withErrorBoundary);
  });
});

describe('scrubbing helpers', () => {
  async function load() {
    return loadTelemetry({ VITE_SENTRY_DSN: '' });
  }

  describe('scrubUrl', () => {
    it.each([
      [
        'https://app.example/public/verify/magic-abc123',
        'https://app.example/public/verify/[FILTERED]',
      ],
      ['/collect/col-tok-9', '/collect/[FILTERED]'],
      [
        '/api/v1/cases/collect/col-tok-9/upload',
        '/api/v1/cases/collect/[FILTERED]/upload',
      ],
      [
        '/contribute/c-1?token=contrib-secret',
        '/contribute/[FILTERED]?token=[FILTERED]',
      ],
      [
        '/api/v1/cases/public/release/rel-tok',
        '/api/v1/cases/public/release/[FILTERED]',
      ],
      [
        '/activate?email=a%40b.com&token=act-tok',
        '/activate?email=[FILTERED]&token=[FILTERED]',
      ],
      ['/cb#access_token=jwt.abc.def&state=1', '/cb#access_token=[FILTERED]&state=1'],
      ['/track/FOI-2026-007-K7QX2M9A', '/track/[FILTERED]'],
      [
        '/api/v1/cases/public/track/FOI-2026-007-K7QX2M9A',
        '/api/v1/cases/public/track/[FILTERED]',
      ],
      ['/cases?status=open&page=2', '/cases?status=open&page=2'],
      ['/cases/123/documents', '/cases/123/documents'],
    ])('%s', async (input, expected) => {
      const t = await load();
      expect(t.scrubUrl(input)).toBe(expected);
    });
  });

  describe('scrubBreadcrumb', () => {
    it('drops console breadcrumbs', async () => {
      const t = await load();
      expect(
        t.scrubBreadcrumb({
          category: 'console',
          message: 'Selected text: Jane Doe, DOB 1970-01-01',
          data: { arguments: ['Selected text:', 'Jane Doe'] },
        }),
      ).toBeNull();
    });

    it('redacts tokens in navigation and XHR breadcrumbs', async () => {
      const t = await load();
      expect(
        t.scrubBreadcrumb({
          category: 'navigation',
          data: { from: '/public/verify/magic-1', to: '/public/dashboard' },
        }),
      ).toEqual({
        category: 'navigation',
        data: { from: '/public/verify/[FILTERED]', to: '/public/dashboard' },
      });
      expect(
        t.scrubBreadcrumb({
          category: 'xhr',
          data: {
            method: 'GET',
            url: '/api/v1/contribute/c-1?token=abc',
            status_code: 200,
          },
        })?.data,
      ).toEqual({
        method: 'GET',
        url: '/api/v1/contribute/[FILTERED]?token=[FILTERED]',
        status_code: 200,
      });
    });

    it('masks emails and scrubs URLs inside messages', async () => {
      const t = await load();
      const out = t.scrubBreadcrumb({
        category: 'event',
        message: 'opened /collect/abc',
        data: { email: 'a@b.com' },
      });
      expect(out?.message).toBe('opened /collect/[FILTERED]');
      expect(out?.data?.email).toBe('[FILTERED]');
    });
  });

  describe('scrubEvent', () => {
    it('scrubs request URL, headers, transaction name, breadcrumbs and spans', async () => {
      const t = await load();
      const event: any = {
        transaction: '/public/verify/magic-xyz',
        message: 'failed at /collect/tok-1',
        request: {
          url: 'https://app.example/contribute/c-1?token=abc',
          query_string: 'token=abc&x=1',
          headers: { authorization: 'Bearer x', 'User-Agent': 'ua' },
          cookies: { s: '1' },
        },
        exception: { values: [{ value: 'GET /api/v1/cases/public/release/rel-1 failed' }] },
        breadcrumbs: [
          { category: 'console', message: 'Redacting matches: Jane' },
          { category: 'navigation', data: { to: '/collect/tok-2' } },
        ],
        spans: [
          { description: 'GET /api/v1/cases/collect/tok-3', data: { url: '/collect/tok-3' } },
        ],
      };
      const out = t.scrubEvent(event);
      expect(out.transaction).toBe('/public/verify/[FILTERED]');
      expect(out.message).toBe('failed at /collect/[FILTERED]');
      expect(out.request.url).toBe(
        'https://app.example/contribute/[FILTERED]?token=[FILTERED]',
      );
      expect(out.request.query_string).toBe('token=[FILTERED]&x=1');
      expect(out.request.headers).toEqual({ 'User-Agent': 'ua' });
      expect(out.request.cookies).toBeUndefined();
      expect(out.exception.values[0].value).toBe(
        'GET /api/v1/cases/public/release/[FILTERED] failed',
      );
      expect(out.breadcrumbs).toEqual([
        { category: 'navigation', data: { to: '/collect/[FILTERED]' } },
      ]);
      expect(out.spans[0].description).toBe('GET /api/v1/cases/collect/[FILTERED]');
      expect(out.spans[0].data.url).toBe('/collect/[FILTERED]');
    });

    it('drops a non-string query_string and scrubs replay URLs', async () => {
      const t = await load();
      const out: any = t.scrubEvent({
        request: { query_string: [['token', 'abc']] },
        urls: ['https://app.example/public/verify/magic-1'],
      } as any);
      expect(out.request.query_string).toBeUndefined();
      expect(out.urls).toEqual(['https://app.example/public/verify/[FILTERED]']);
    });
  });

  describe('scrubRecordingEvent', () => {
    it('scrubs URLs in replay performance spans and breadcrumbs', async () => {
      const t = await load();
      const out: any = t.scrubRecordingEvent({
        type: 5,
        data: {
          tag: 'performanceSpan',
          payload: {
            op: 'navigation.push',
            description: 'https://app.example/collect/tok-1',
            data: { url: '/contribute/c-1?token=abc' },
          },
        },
      });
      expect(out.data.payload.description).toBe('https://app.example/collect/[FILTERED]');
      expect(out.data.payload.data.url).toBe('/contribute/[FILTERED]?token=[FILTERED]');
    });

    it('drops console breadcrumbs and passes non-custom events through', async () => {
      const t = await load();
      expect(
        t.scrubRecordingEvent({
          type: 5,
          data: { tag: 'breadcrumb', payload: { category: 'console', message: 'x' } },
        }),
      ).toBeNull();
      const snapshot = { type: 2, data: { node: {} } };
      expect(t.scrubRecordingEvent(snapshot)).toBe(snapshot);
    });
  });
});
