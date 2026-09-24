import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';

/**
 * Canonical HTTP client for the BlackBar frontend.
 *
 * Exports:
 *   - default: authenticated axios instance (attaches Bearer token, handles 401)
 *   - publicApi: unauthenticated axios instance for public/contributor endpoints
 *   - apiClient: thin class wrapper around the default instance (back-compat)
 *
 * This file is the single source of truth for API base URL, headers, and
 * interceptor behavior. Domain wrappers (see ./workflowApi.ts) build on top
 * of the default export.
 */

// Force HTTPS for production, use relative URLs otherwise.
// Fixes mixed-content errors when the page is served over HTTPS.
const getBaseURL = (): string => {
  if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
    return `https://${window.location.host}/api/v1`;
  }
  return '/api/v1';
};

/**
 * Default request timeout. Without one a stalled backend leaves spinners
 * (viewer, uploads) hanging forever.
 */
export const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Timeout for calls that move whole files (uploads, PDF/package downloads) or
 * wait on slow server-side work (LLM suggestions, OCR on upload). Pass it
 * per request: `api.post(url, form, { timeout: TRANSFER_TIMEOUT_MS })`.
 */
export const TRANSFER_TIMEOUT_MS = 300_000;

// NOTE: do NOT set a default Content-Type header here. axios's default
// transformRequest auto-derives the correct Content-Type from the body
// type — `application/json` for plain objects, `multipart/form-data;
// boundary=...` for FormData. Setting a global default disables that
// auto-detection and breaks multipart uploads (FE-F10 — same defect class
// as F4 / F5, but at the client level rather than per-component).
const api = axios.create({
  baseURL: getBaseURL(),
  timeout: DEFAULT_TIMEOUT_MS,
});

// Attach the bearer token (if present) to every outgoing request.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

/**
 * Why the backend refused a session with 401. The login page shows a message
 * for each (see SESSION_END_MESSAGES in ../components/Login.tsx).
 *
 *  - `revoked`:  "Session has been revoked" — the token_version was bumped by
 *                logout elsewhere, a password change, a role change or a
 *                disable (backend/src/dependencies.py, auth/routes.py /me).
 *  - `inactive`: "Account is not active" — the account is disabled/pending.
 *  - `expired`:  any other 401 while a token was held (expired or invalid).
 */
export type SessionEndReason = 'revoked' | 'inactive' | 'expired';

const AUTH_STORAGE_KEYS = [
  'token',
  'user',
  'user_type',
  'userRole',
  'userRoles',
  'userId',
  'username',
  'magic_link_email',
];

/** Backend 401 bodies are `{error: {code, message}}` (utils/error_handler.py). */
export function sessionEndReason(data: unknown): SessionEndReason {
  const err = (data as { error?: unknown } | null | undefined)?.error;
  const message =
    err && typeof err === 'object' ? String((err as { message?: unknown }).message ?? '') : '';
  if (/session has been revoked/i.test(message)) return 'revoked';
  if (/account is not active/i.test(message)) return 'inactive';
  return 'expired';
}

// One redirect per page life: several requests in flight can all come back
// 401 at once, and none of them may retry or re-trigger navigation.
let redirectingToLogin = false;

// Handle authentication errors (session timeout, revoked session, inactive
// account) and log correlation IDs returned by the backend.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Route public users back to the public login.
      const userType = localStorage.getItem('user_type');
      const hadToken = localStorage.getItem('token') !== null;

      // Clear stored auth data.
      AUTH_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));

      // Only redirect if we're not already on a login page.
      if (!redirectingToLogin && !window.location.pathname.includes('/login')) {
        redirectingToLogin = true;
        if (userType === 'public') {
          window.location.href = '/public/login';
        } else {
          const returnUrl = encodeURIComponent(
            window.location.pathname + window.location.search
          );
          // Say why only when there was a session to lose; a request that
          // never carried a token just needs the login page.
          const reason = hadToken ? `&reason=${sessionEndReason(error.response.data)}` : '';
          window.location.href = `/login?redirect=${returnUrl}${reason}`;
        }
      }
    }
    // 403 PUBLIC_TOKEN_FORBIDDEN (a magic-link token on a staff endpoint) is
    // deliberately NOT a redirect: the caller shows getApiErrorMessage(),
    // which explains it, and the requester keeps their public session.

    // Surface correlation IDs in the console to help support debug requests.
    // Log only the status and error code: response bodies can echo document
    // text or PII back, and console output can reach third-party telemetry.
    const correlationId = error.response?.headers?.['x-correlation-id'];
    if (correlationId) {
      console.error(`API Error [${correlationId}]:`, {
        status: error.response?.status,
        code: error.response?.data?.error?.code,
      });
    }

    return Promise.reject(error);
  }
);

/**
 * Revoke the caller's tokens server-side (`POST /auth/logout` bumps the
 * user's token_version). Fire-and-forget: it never throws or rejects, and it
 * uses `fetch` with `keepalive` so the request survives the navigation to
 * /login that usually follows. Staff tokens only; the backend refuses
 * magic-link tokens on this route.
 */
export function revokeSessionOnServer(token: string | null | undefined): void {
  if (!token) return;
  try {
    const base = getBaseURL();
    const url = /^https?:/.test(base)
      ? `${base}/auth/logout`
      : `${window.location.origin}${base}/auth/logout`;
    void fetch(url, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      keepalive: true,
      credentials: 'omit',
    }).catch(() => undefined);
  } catch {
    // Logging out locally must never fail because the revoke call could not start.
  }
}

/**
 * Public API client for unauthenticated endpoints (contributor portal,
 * public request submission). Does NOT attach the bearer token and does
 * NOT redirect on 401.
 */
export const publicApi: AxiosInstance = axios.create({
  baseURL: getBaseURL(),
  timeout: DEFAULT_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Back-compat class wrapper. Existing callers (`AuthContext`, `UserManagement`)
 * use this shape; new code should import the default export instead.
 */
class ApiClient {
  get(url: string, config?: AxiosRequestConfig) {
    return api.get(url, config);
  }
  post(url: string, data?: any, config?: AxiosRequestConfig) {
    return api.post(url, data, config);
  }
  put(url: string, data?: any, config?: AxiosRequestConfig) {
    return api.put(url, data, config);
  }
  patch(url: string, data?: any, config?: AxiosRequestConfig) {
    // Cast to any: axios' `AxiosInstance` typing under this project's TS
    // resolution doesn't expose `patch` directly even though it exists at
    // runtime.
    return (api as any).patch(url, data, config);
  }
  delete(url: string, config?: AxiosRequestConfig) {
    return api.delete(url, config);
  }
}

export const apiClient = new ApiClient();

export default api;
