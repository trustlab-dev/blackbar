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
import type { Breadcrumb, Event } from '@sentry/react';
import { getCLS, getFID, getFCP, getLCP, getTTFB } from 'web-vitals';
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
  FID: 100,      // First Input Delay
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
// Query/fragment parameters whose values must never be sent.
const SENSITIVE_PARAM_NAME = /token|key|secret|passw|code|sig|auth|email|session/i;
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

function scrubStringValues(data: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(data)) {
    if (/email/i.test(key)) {
      out[key] = FILTERED;
    } else if (typeof value === 'string') {
      out[key] = scrubUrl(value);
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
 * `beforeSend` / `beforeSendTransaction` hook, also registered as an event
 * processor so replay events (which skip `beforeSend`) are covered.
 */
export function scrubEvent<T extends Event>(event: T): T {
  const request = event.request;
  if (request) {
    if (request.headers) {
      for (const name of Object.keys(request.headers)) {
        if (SENSITIVE_HEADERS.test(name)) delete request.headers[name];
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

/**
 * Replay `beforeAddRecordingEvent` hook. Custom recording events (tag
 * "breadcrumb" or "performanceSpan") embed URLs for navigations and network
 * requests; DOM snapshots are already masked by `maskAllText`.
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

/**
 * Initialize frontend telemetry
 * Call this in index.tsx before rendering
 */
export function initTelemetry(): void {
  // Initialize Sentry if DSN is configured
  if (SENTRY_DSN) {
    Sentry.init({
      dsn: SENTRY_DSN,
      environment: ENVIRONMENT,
      release: `blackbar-frontend@${VERSION}`,

      // Never attach IPs, cookies or request bodies automatically.
      sendDefaultPii: false,

      // Performance monitoring
      tracesSampleRate: IS_PRODUCTION ? 0.1 : 1.0,

      // Session replay. Text and media are masked, but keep volume low in
      // production: a replay is a recording of someone working a case.
      replaysSessionSampleRate: IS_PRODUCTION ? 0 : 0.1,
      replaysOnErrorSampleRate: IS_PRODUCTION ? 0.1 : 1.0,

      // Integrations
      integrations: [
        // Console breadcrumbs would copy debug logging into every event.
        Sentry.breadcrumbsIntegration({ console: false }),
        Sentry.browserTracingIntegration(),
        Sentry.replayIntegration({
          maskAllText: true,
          blockAllMedia: true,
          beforeAddRecordingEvent: scrubRecordingEvent,
        }),
      ],

      // Filter sensitive data
      beforeBreadcrumb: scrubBreadcrumb,
      beforeSend: scrubEvent,
      beforeSendTransaction: scrubEvent,
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
  getCLS(reportVital);
  getFID(reportVital);
  getFCP(reportVital);
  getLCP(reportVital);
  getTTFB(reportVital);
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
