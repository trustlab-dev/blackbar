/**
 * Turn an API error into a user-facing message.
 *
 * The backend's global handlers (backend/src/utils/error_handler.py) return
 * `{error: {code, message, details, correlation_id}}`. A route that raises
 * HTTPException with a dict detail containing an `error` key is passed through
 * as-is, e.g. `{error: 'invalid_token', message: '...'}`. Older code paths and
 * test fixtures still use FastAPI's `{detail: string | [{msg}]}`. This helper
 * understands all three and always returns a string (never an object React
 * would refuse to render).
 */

export const DEFAULT_ERROR_MESSAGE = 'Something went wrong. Please try again.';
export const TIMEOUT_ERROR_MESSAGE = 'The request timed out. Please try again.';
/**
 * A magic-link (public portal) token used on a staff endpoint gets
 * 403 `{error: {code: 'PUBLIC_TOKEN_FORBIDDEN'}}` from the auth middleware
 * (backend/src/core/auth_middleware.py). Explain it in requester terms.
 */
export const PUBLIC_TOKEN_FORBIDDEN_MESSAGE =
  'This page is for staff accounts. You are signed in to the public request portal, ' +
  'so please use My Requests to see your requests.';

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

/** First Pydantic/FastAPI validation error as "field: msg" (or just "msg"). */
function firstValidationMessage(errors: unknown): string | null {
  if (!Array.isArray(errors) || !isObject(errors[0])) return null;
  const raw = text(errors[0].msg);
  if (!raw) return null;
  // Pydantic prefixes custom validator errors with "Value error, ".
  const msg = raw.replace(/^Value error,\s*/, '');
  const loc = errors[0].loc;
  const field = Array.isArray(loc)
    ? loc.filter((p, i) => !(i === 0 && ['body', 'query', 'path'].includes(String(p)))).join('.')
    : '';
  return field ? `${field}: ${msg}` : msg;
}

export function getApiErrorMessage(
  err: unknown,
  fallback: string = DEFAULT_ERROR_MESSAGE,
): string {
  if (!isObject(err)) return fallback;
  if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
    return TIMEOUT_ERROR_MESSAGE;
  }

  const response = err.response;
  if (!isObject(response)) return fallback;
  // Server faults: keep the caller's contextual message rather than
  // surfacing "Internal server error".
  if (typeof response.status === 'number' && response.status >= 500) return fallback;

  const data = response.data;
  if (!isObject(data)) return fallback;

  // Standard envelope: {error: {message, details: {errors: [...]}}}
  if (isObject(data.error)) {
    if (data.error.code === 'PUBLIC_TOKEN_FORBIDDEN') return PUBLIC_TOKEN_FORBIDDEN_MESSAGE;
    const message = text(data.error.message);
    if (message) {
      const details = data.error.details;
      const first = isObject(details) ? firstValidationMessage(details.errors) : null;
      return first ? `${message}: ${first}` : message;
    }
  }

  // Pass-through dict detail: {error: 'code', message: '...'}
  if (typeof data.error === 'string') {
    const message = text(data.message);
    if (message) return message;
  }

  // FastAPI default: {detail: '...'} or {detail: [{msg}]}
  const detail = text(data.detail) ?? firstValidationMessage(data.detail);
  if (detail) return detail;

  return text(data.message) ?? fallback;
}
