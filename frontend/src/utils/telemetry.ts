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
import { getCLS, getFID, getFCP, getLCP, getTTFB } from 'web-vitals';
import type { Metric } from 'web-vitals';

// Configuration from environment
const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN || '';
const ENVIRONMENT = import.meta.env.VITE_ENVIRONMENT || 'development';
const VERSION = import.meta.env.VITE_VERSION || '1.0.0';

// Web Vitals thresholds (in ms)
const VITALS_THRESHOLDS = {
  CLS: 0.1,      // Cumulative Layout Shift (unitless)
  FID: 100,      // First Input Delay
  FCP: 1800,     // First Contentful Paint
  LCP: 2500,     // Largest Contentful Paint
  TTFB: 800,     // Time to First Byte
};

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
      
      // Performance monitoring
      tracesSampleRate: ENVIRONMENT === 'production' ? 0.1 : 1.0,
      
      // Session replay (optional)
      replaysSessionSampleRate: 0.1,
      replaysOnErrorSampleRate: 1.0,
      
      // Integrations
      integrations: [
        Sentry.browserTracingIntegration(),
        Sentry.replayIntegration({
          maskAllText: true,
          blockAllMedia: true,
        }),
      ],
      
      // Filter sensitive data
      beforeSend(event) {
        // Remove sensitive headers
        if (event.request?.headers) {
          delete event.request.headers['Authorization'];
          delete event.request.headers['Cookie'];
        }
        
        // Remove PII from breadcrumbs
        if (event.breadcrumbs) {
          event.breadcrumbs = event.breadcrumbs.map(breadcrumb => {
            if (breadcrumb.data?.email) {
              breadcrumb.data.email = '[FILTERED]';
            }
            return breadcrumb;
          });
        }
        
        return event;
      },
    });
    
    console.log('[Telemetry] Sentry initialized');
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
    if (ENVIRONMENT !== 'production') {
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
  if (ENVIRONMENT !== 'production') {
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
