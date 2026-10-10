/**
 * Frontend Telemetry Module for BlackBar.
 *
 * Provides:
 * - Sentry error tracking
 * - Web Vitals performance monitoring
 * - Custom event tracking
 */

import React from 'react';
import * as Sentry from '@sentry/react';
import type { Breadcrumb, BrowserOptions, Event } from '@sentry/react';
import { onCLS, onFCP, onINP, onLCP, onTTFB } from 'web-vitals';
import type { Metric } from 'web-vitals';

// Configuration from environment. VITE_ENVIRONMENT is optional and no deploy
// file sets it, so fall back to the Vite build mode rather than assuming
// "development" for a production bundle.
const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN || '';
const ENVIRONMENT =
  import.meta.env.VITE_ENVIRONMENT || (import.meta.env.PROD ? 'production' : 'development');
const IS_PRODUCTION = import.meta.env.PROD || ENVIRONMENT === 'production';
const VERSION = import.meta.env.VITE_VERSION || '1.0.0';

// Web Vitals thresholds (in ms)
const VITALS_THRESHOLDS = {
  CLS: 0.1,      // Cumulative Layout Shift (unitless)
  INP: 200,      // Interaction to Next Paint (replaced First Input Delay)
  FCP: 1800,     // First Contentful Paint
  LCP: 2500,     // Largest Contentful Paint
  TTFB: 800,     // Time to First Byte
};

// ---------------------------------------------------------------------------
// Scrubbing. Everything that leaves the browser for Sentry goes through these.
// ---------------------------------------------------------------------------

export const FILTERED = '[FILTERED]';

// Path segments that carry a capability token: magic-link verify
// (/public/verify/<token>), public collection links (/collect/<token>,
// /api/v1/cases/collect/<token>/upload), contributor portal
// (/contribute/<id>), release downloads (/cases/public/release/<token>) and
// public tracking (/track/<number>, /cases/public/track/<number>): the
// tracking number's random suffix is the only credential for that lookup.
const TOKEN_PATH_SEGMENT = /(\/(?:verify|collect|contribute|release|track)\/)[^/?#\s"']+/gi;
// Query/fragment parameters whose values must never be sent (substring match).
const SENSITIVE_PARAM_TERMS = ['token', 'key', 'secret', 'passw', 'code', 'sig', 'auth', 'email', 'session'];
const SENSITIVE_PARAM_NAME = new RegExp(SENSITIVE_PARAM_TERMS.join('|'), 'i');
const QUERY_PAIR = /([?&#;])([^=&#?\s"']+)=([^&#\s"']*)/g;
const SENSITIVE_HEADERS = /^(authorization|cookie|set-cookie|x-contributor-token|x-api-key)$/i;

/**
 * Redact capability tokens and sensitive query parameters from a URL, or from
 * any string that contains one (breadcrumb messages, transaction names).
 */
export function scrubUrl(value: string): string {
  return value
    .replace(TOKEN_PATH_SEGMENT, `$1${FILTERED}`)
    .replace(QUERY_PAIR, (match, sep: string, key: string) =>
      SENSITIVE_PARAM_NAME.test(key) ? `${sep}${key}=${FILTERED}` : match,
    );
}

// Keys whose value is a bare query string or fragment with the leading "?"
// or "#" stripped (span attributes `url.query`, `url.fragment`, `http.query`).
const QUERY_LIKE_KEY = /(?:^|[._])(?:query|query_string|fragment)$/i;

function scrubQueryLike(value: string): string {
  return /^[?#]/.test(value) ? scrubUrl(value) : scrubUrl(`?${value}`).slice(1);
}

function scrubStringValues(data: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(data)) {
    const scrub = QUERY_LIKE_KEY.test(key) ? scrubQueryLike : scrubUrl;
    if (/email/i.test(key)) {
      out[key] = FILTERED;
    } else if (typeof value === 'string') {
      out[key] = scrub(value);
    } else if (Array.isArray(value)) {
      // Header attributes such as `http.request.header.referer` are arrays.
      out[key] = value.map((v: unknown) => (typeof v === 'string' ? scrub(v) : v));
    } else {
      out[key] = value;
    }
  }
  return out;
}

/**
 * `beforeBreadcrumb` hook. Console breadcrumbs are dropped outright: the
 * viewer and API paths have historically logged redaction text and detector
 * output. Other breadcrumbs keep their shape with URLs and emails redacted.
 */
export function scrubBreadcrumb(breadcrumb: Breadcrumb): Breadcrumb | null {
  if (breadcrumb.category === 'console') return null;
  const scrubbed: Breadcrumb = { ...breadcrumb };
  if (typeof scrubbed.message === 'string') {
    scrubbed.message = scrubUrl(scrubbed.message);
  }
  if (scrubbed.data) {
    scrubbed.data = scrubStringValues(scrubbed.data);
  }
  return scrubbed;
}

/**
 * `beforeSend` hook, also registered as an event processor so replay events
 * (which skip `beforeSend`) are covered. Spans are not events in
 * @sentry/react 11: they are streamed and scrubbed by `scrubSpan`.
 */
export function scrubEvent<T extends Event>(event: T): T {
  const request = event.request;
  if (request) {
    if (request.headers) {
      for (const [name, value] of Object.entries(request.headers)) {
        if (SENSITIVE_HEADERS.test(name)) {
          delete request.headers[name];
        } else if (typeof value === 'string') {
          // Referer carries the previous page URL, which can hold a token.
          request.headers[name] = scrubUrl(value);
        }
      }
    }
    delete request.cookies;
    if (typeof request.url === 'string') request.url = scrubUrl(request.url);
    if (typeof request.query_string === 'string') {
      request.query_string = scrubUrl(`?${request.query_string}`).slice(1);
    } else if (request.query_string !== undefined) {
      delete request.query_string;
    }
  }

  if (typeof event.transaction === 'string') {
    event.transaction = scrubUrl(event.transaction);
  }
  if (typeof event.message === 'string') {
    event.message = scrubUrl(event.message);
  }
  event.exception?.values?.forEach((ex) => {
    if (typeof ex.value === 'string') ex.value = scrubUrl(ex.value);
  });

  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs
      .map(scrubBreadcrumb)
      .filter((b): b is Breadcrumb => b !== null);
  }

  event.spans?.forEach((span) => {
    if (typeof span.description === 'string') {
      span.description = scrubUrl(span.description);
    }
    if (span.data) {
      span.data = scrubStringValues(span.data) as typeof span.data;
    }
  });

  // Replay events carry the list of page URLs visited during the segment.
  const replayUrls = (event as { urls?: unknown }).urls;
  if (Array.isArray(replayUrls)) {
    (event as { urls?: unknown }).urls = replayUrls.map((u) =>
      typeof u === 'string' ? scrubUrl(u) : u,
    );
  }

  return event;
}

// The span payload `beforeSendSpan` receives (StreamedSpanJSON in
// @sentry/core, which @sentry/react does not re-export).
type StreamedSpan = Parameters<NonNullable<BrowserOptions['beforeSendSpan']>>[0];

/**
 * `beforeSendSpan` hook. With span streaming (the 11.x default, pinned in
 * `initTelemetry`) every span, including the segment span that replaced the
 * transaction, is sent on its own and never passes through `beforeSend`,
 * `beforeSendTransaction` or event processors. The name holds the route or
 * request URL; attributes hold `url.full`, `url.query`, `http.request.header.referer`,
 * `sentry.segment.name` and the scope user (`user.email` is masked here).
 */
export function scrubSpan<T extends Pick<StreamedSpan, 'name' | 'attributes'>>(span: T): T {
  if (typeof span.name === 'string') span.name = scrubUrl(span.name);
  if (span.attributes) {
    span.attributes = scrubStringValues(span.attributes) as T['attributes'];
  }
  return span;
}

/**
 * Replay `beforeAddRecordingEvent` hook. Custom recording events (tag
 * "breadcrumb" or "performanceSpan") embed URLs for navigations and network
 * requests; DOM snapshots are already masked by `maskAllText`.
 *
 * Limitation: Sentry only passes custom events (rrweb type 5) through this
 * hook, in 8.x and still in 11.x. The rrweb Meta event (type 4,
 * `data.href = window.location.href`) that opens every full snapshot never
 * arrives here, which is why Replay is kept off token
 * routes entirely (see `isReplayExcludedPath`) and those pages strip the
 * token from the address bar (`utils/capabilityUrl.ts`).
 */
export function scrubRecordingEvent<T extends { type?: number; data?: unknown }>(
  event: T,
): T | null {
  const data = event.data as { tag?: string; payload?: Record<string, unknown> } | undefined;
  if (!data || typeof data !== 'object' || !data.payload) return event;
  if (data.payload.category === 'console') return null;

  const payload: Record<string, unknown> = scrubStringValues(data.payload);
  if (payload.data && typeof payload.data === 'object' && !Array.isArray(payload.data)) {
    payload.data = scrubStringValues(payload.data as Record<string, unknown>);
  }
  return { ...event, data: { ...data, payload } };
}

// ---------------------------------------------------------------------------
// Session Replay gating.
// ---------------------------------------------------------------------------

// Requester-facing and capability-token routes: magic-link verify and the
// public portal (/public/...), account activation, collection links,
// contributor links, public tracking and the public request form. Replay
// never records these. Every rrweb full snapshot starts with a Meta event
// carrying window.location.href, and in @sentry/react 8.x through 11.x that
// event skips beforeAddRecordingEvent, so no scrubber can reach the token in it.
const REPLAY_EXCLUDED_ROUTE =
  /^\/(?:public|activate|collect|contribute|track|request)(?:\/|$)/i;

export function isReplayExcludedPath(pathname: string): boolean {
  return REPLAY_EXCLUDED_ROUTE.test(pathname);
}

/**
 * Stop Replay (session recording or the on-error buffer) when the app
 * navigates onto a public or token route. Once stopped it stays off for the
 * rest of the page life; a staff page reached afterwards is not recorded.
 * Called from the router on every location change.
 */
export function syncReplayWithRoute(pathname: string): void {
  if (!SENTRY_DSN || !isReplayExcludedPath(pathname)) return;
  const replay = Sentry.getReplay();
  if (replay) void replay.stop();
}

/**
 * `dataCollection` for Sentry 11. Each category is pinned rather than left to
 * the SDK default, which turned permissive in 11.x.
 */
export const SAFE_DATA_COLLECTION = {
  // No automatic user.* fields, and no IP inference (`infer_ip: "never"`) on
  // events, sessions, spans or replays.
  userInfo: false,
  cookies: false,
  // The browser SDK only sends User-Agent and Referer. Referer is the
  // previous page URL, which can carry a capability token.
  httpHeaders: { request: { allow: ['user-agent'] }, response: false },
  httpBodies: [],
  // The parameter names scrubUrl filters, applied by the SDK before the
  // scrubbers above see the URL.
  urlQueryParams: { deny: SENSITIVE_PARAM_TERMS },
  graphQL: { document: false, variables: false },
  genAI: { inputs: false, outputs: false },
  databaseQueryData: false,
  queues: false,
  stackFrameVariables: false,
} satisfies NonNullable<BrowserOptions['dataCollection']>;

// Default integrations kept from Sentry's list: the 8.x defaults, except
// Breadcrumbs no longer covers console. Dropped: Console (console
// breadcrumbs; the viewer has logged redaction text), CultureContext (locale,
// time zone and calendar; not sent by 8.x), ConversationId (gen-AI spans
// only) and anything a future release adds.
export const KEPT_DEFAULT_INTEGRATIONS: ReadonlySet<string> = new Set([
  'EventFilters',
  'FunctionToString',
  'BrowserApiErrors',
  'Breadcrumbs',
  'GlobalHandlers',
  'LinkedErrors',
  'Dedupe',
  'HttpContext',
  'BrowserSession',
]);

/**
 * Initialize frontend telemetry
 * Call this in index.tsx before rendering
 */
export function initTelemetry(): void {
  // Initialize Sentry if DSN is configured
  if (SENTRY_DSN) {
    // Replay starts recording (or buffering for on-error replays) at init,
    // so a page loaded on a public/token route never gets the integration.
    const recordReplay =
      typeof window === 'undefined' || !isReplayExcludedPath(window.location.pathname);

    Sentry.init({
      dsn: SENTRY_DSN,
      environment: ENVIRONMENT,
      release: `blackbar-frontend@${VERSION}`,

      // 11.x replaced `sendDefaultPii` with `dataCollection`, and an unset
      // `dataCollection` now collects user info, cookies, headers and bodies.
      // Pin every category so nothing personal is attached automatically.
      dataCollection: SAFE_DATA_COLLECTION,

      // Performance monitoring. Spans are streamed (the 11.x default, pinned
      // here because `beforeSendSpan: scrubSpan` only runs in this mode).
      tracesSampleRate: IS_PRODUCTION ? 0.1 : 1.0,
      traceLifecycle: 'stream',

      // Session replay. Text and media are masked, but keep volume low in
      // production: a replay is a recording of someone working a case.
      replaysSessionSampleRate: IS_PRODUCTION ? 0 : 0.1,
      replaysOnErrorSampleRate: IS_PRODUCTION ? 0.1 : 1.0,

      // Integrations. Defaults are filtered through an allowlist so that a
      // default added by a later SDK release does not start sending data.
      integrations: (defaults) => [
        ...defaults.filter((integration) => KEPT_DEFAULT_INTEGRATIONS.has(integration.name)),
        Sentry.browserTracingIntegration(),
        ...(recordReplay
          ? [
              Sentry.replayIntegration({
                maskAllText: true,
                maskAllInputs: true,
                blockAllMedia: true,
                // No request/response headers or bodies in replays.
                networkDetailAllowUrls: [],
                beforeAddRecordingEvent: scrubRecordingEvent,
              }),
            ]
          : []),
      ],

      // Filter sensitive data
      beforeBreadcrumb: scrubBreadcrumb,
      beforeSend: scrubEvent,
      beforeSendSpan: scrubSpan,
    });
    // Replay events bypass beforeSend; event processors see every event type.
    Sentry.addEventProcessor(scrubEvent);

    if (!IS_PRODUCTION) console.log('[Telemetry] Sentry initialized');
  } else {
    console.log('[Telemetry] Sentry DSN not configured, error tracking disabled');
  }
  
  // Initialize Web Vitals reporting
  initWebVitals();
}

/**
 * Initialize Web Vitals monitoring
 */
function initWebVitals(): void {
  const reportVital = (metric: Metric) => {
    const { name, value } = metric;
    
    // Determine rating based on thresholds
    const threshold = VITALS_THRESHOLDS[name as keyof typeof VITALS_THRESHOLDS];
    const rating = threshold ? (value <= threshold ? 'good' : 'poor') : 'unknown';
    
    // Log to console in development
    if (!IS_PRODUCTION) {
      console.log(`[Web Vitals] ${name}: ${value.toFixed(2)} (${rating})`);
    }
    
    // Send to Sentry as custom measurement
    if (SENTRY_DSN) {
      Sentry.setMeasurement(name, value, name === 'CLS' ? '' : 'millisecond');
    }
    
    // Track poor performance
    if (threshold && value > threshold) {
      trackEvent('web_vital_poor', {
        metric: name,
        value: value.toString(),
        threshold: threshold.toString(),
        rating,
      });
    }
  };
  
  // Register all Web Vitals
  onCLS(reportVital);
  onINP(reportVital);
  onFCP(reportVital);
  onLCP(reportVital);
  onTTFB(reportVital);
}

/**
 * Set user context for error tracking
 */
export function setUser(userId: string, email?: string): void {
  if (SENTRY_DSN) {
    Sentry.setUser({
      id: userId,
      email: email,
    });
  }
}

/**
 * Clear user context (on logout)
 */
export function clearUser(): void {
  if (SENTRY_DSN) {
    Sentry.setUser(null);
  }
}

/**
 * Set additional context
 */
export function setContext(name: string, data: Record<string, unknown>): void {
  if (SENTRY_DSN) {
    Sentry.setContext(name, data);
  }
}

/**
 * Add a breadcrumb for debugging
 */
export function addBreadcrumb(
  message: string,
  category: string = 'info',
  data?: Record<string, unknown>
): void {
  if (SENTRY_DSN) {
    Sentry.addBreadcrumb({
      message,
      category,
      data,
      level: 'info',
    });
  }
}

/**
 * Track a custom event
 */
export function trackEvent(
  name: string,
  data?: Record<string, string>
): void {
  // Add breadcrumb
  addBreadcrumb(`Event: ${name}`, 'event', data);
  
  // Log in development
  if (!IS_PRODUCTION) {
    console.log(`[Telemetry] Event: ${name}`, data);
  }
}

/**
 * Capture an error manually
 */
export function captureError(
  error: Error,
  context?: Record<string, unknown>
): void {
  console.error('[Telemetry] Error captured:', error);
  
  if (SENTRY_DSN) {
    Sentry.withScope((scope) => {
      if (context) {
        scope.setExtras(context);
      }
      Sentry.captureException(error);
    });
  }
}

/**
 * Capture a message
 */
export function captureMessage(
  message: string,
  level: 'info' | 'warning' | 'error' = 'info'
): void {
  if (SENTRY_DSN) {
    Sentry.captureMessage(message, level);
  }
}

/**
 * Start a performance transaction
 */
export function startTransaction(
  name: string,
  op: string = 'navigation'
): Sentry.Span | undefined {
  if (SENTRY_DSN) {
    return Sentry.startInactiveSpan({
      name,
      op,
    });
  }
  return undefined;
}

/**
 * React Error Boundary wrapper
 */
export const ErrorBoundary = Sentry.ErrorBoundary;

/**
 * React profiler for performance monitoring
 */
export const Profiler = Sentry.withProfiler;

/**
 * HOC to wrap components with error boundary
 * Note: Use in .tsx files with JSX fallback
 */
export const withErrorBoundary = Sentry.withErrorBoundary;
