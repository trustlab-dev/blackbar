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
async function loadTelemetry(env: Record<string, string>) {
  vi.resetModules();
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
