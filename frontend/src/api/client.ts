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

// NOTE: do NOT set a default Content-Type header here. axios's default
// transformRequest auto-derives the correct Content-Type from the body
// type — `application/json` for plain objects, `multipart/form-data;
// boundary=...` for FormData. Setting a global default disables that
// auto-detection and breaks multipart uploads (FE-F10 — same defect class
// as F4 / F5, but at the client level rather than per-component).
const api = axios.create({
  baseURL: getBaseURL(),
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

// Handle authentication errors (session timeout, invalid token) and log
// correlation IDs returned by the backend.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Route public users back to the public login.
      const userType = localStorage.getItem('user_type');

      // Clear stored auth data.
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      localStorage.removeItem('user_type');
      localStorage.removeItem('userRole');
      localStorage.removeItem('userRoles');
      localStorage.removeItem('userId');
      localStorage.removeItem('username');
      localStorage.removeItem('magic_link_email');

      // Only redirect if we're not already on a login page.
      if (!window.location.pathname.includes('/login')) {
        if (userType === 'public') {
          window.location.href = '/public/login';
        } else {
          const returnUrl = encodeURIComponent(
            window.location.pathname + window.location.search
          );
          window.location.href = `/login?redirect=${returnUrl}`;
        }
      }
    }

    // Surface correlation IDs in the console to help support debug requests.
    const correlationId = error.response?.headers?.['x-correlation-id'];
    if (correlationId) {
      console.error(`API Error [${correlationId}]:`, error.response?.data);
    }

    return Promise.reject(error);
  }
);

/**
 * Public API client for unauthenticated endpoints (contributor portal,
 * public request submission). Does NOT attach the bearer token and does
 * NOT redirect on 401.
 */
export const publicApi: AxiosInstance = axios.create({
  baseURL: getBaseURL(),
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
