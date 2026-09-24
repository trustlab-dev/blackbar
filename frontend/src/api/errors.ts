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

export interface ApiErrorMessageOptions {
  /**
   * 5xx statuses whose backend message is meant for the user, e.g. the LLM
   * admin routes' 503 "LLM_API_KEY_ENCRYPTION_KEY is missing or invalid"
   * (backend/src/admin/llm_routes.py). Other 5xx keep the fallback.
   */
  serverMessageStatuses?: number[];
}

export function getApiErrorMessage(
  err: unknown,
  fallback: string = DEFAULT_ERROR_MESSAGE,
  options: ApiErrorMessageOptions = {},
): string {
  if (!isObject(err)) return fallback;
  if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
    return TIMEOUT_ERROR_MESSAGE;
  }

  const response = err.response;
  if (!isObject(response)) return fallback;
  // Server faults: keep the caller's contextual message rather than
  // surfacing "Internal server error".
  if (
    typeof response.status === 'number' &&
    response.status >= 500 &&
    !options.serverMessageStatuses?.includes(response.status)
  ) {
    return fallback;
  }

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

  // FastAPI default: {detail: '...'} or {detail: [{msg}]}, or a dict
  // detail such as {detail: {message, errors}}.
  const detail =
    text(data.detail) ??
    firstValidationMessage(data.detail) ??
    (isObject(data.detail) ? text(data.detail.message) : null);
  if (detail) return detail;

  return text(data.message) ?? fallback;
}

export const RATE_LIMIT_MESSAGE = 'Too many requests.';

function headerValue(headers: unknown, name: string): string | null {
  if (!isObject(headers)) return null;
  const getter = (headers as { get?: unknown }).get;
  if (typeof getter === 'function') {
    const value: unknown = getter.call(headers, name);
    if (typeof value === 'string' || typeof value === 'number') return String(value);
  }
  const key = Object.keys(headers).find((k) => k.toLowerCase() === name);
  const value = key ? headers[key] : undefined;
  return typeof value === 'string' || typeof value === 'number' ? String(value) : null;
}

/**
 * Seconds to wait before retrying a 429, from its `Retry-After` header
 * (delta-seconds or an HTTP date). Null when the error is not a 429 or the
 * header is missing or unreadable. The LLM routes send it on per-user and
 * per-document limits (backend/src/documents/redaction_suggestion_routes.py
 * `_enforce_llm_limits`; error_handler.py keeps HTTPException headers).
 */
export function getRetryAfterSeconds(err: unknown): number | null {
  if (!isObject(err) || !isObject(err.response) || err.response.status !== 429) return null;
  const raw = headerValue(err.response.headers, 'retry-after')?.trim();
  if (!raw) return null;
  if (/^\d+$/.test(raw)) return Number(raw);
  const date = Date.parse(raw);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

/**
 * User-facing text for a 429: "<lead> Try again in N seconds." when the
 * response carries Retry-After, else the backend's message, else a generic
 * "please wait". Callers show it once; nothing retries automatically.
 */
export function getRateLimitMessage(err: unknown, lead: string = RATE_LIMIT_MESSAGE): string {
  const seconds = getRetryAfterSeconds(err);
  if (seconds !== null) {
    const unit = seconds === 1 ? 'second' : 'seconds';
    return `${lead} Try again in ${seconds} ${unit}.`;
  }
  return getApiErrorMessage(err, `${lead} Please wait and try again.`);
}

export function isRateLimited(err: unknown): boolean {
  return isObject(err) && isObject(err.response) && err.response.status === 429;
}

/**
 * A request made with `responseType: 'blob'` (file downloads) gets its error
 * body as a Blob too, which getApiErrorMessage cannot read. Returns the error
 * with a JSON error body parsed in place, so the backend's message (e.g. the
 * export 409 "redactions are awaiting review") reaches the user. Anything
 * that is not a JSON blob is returned unchanged.
 */
export async function withParsedBlobErrorBody<T>(err: T): Promise<T> {
  if (!isObject(err) || !isObject(err.response)) return err;
  const data = err.response.data;
  if (typeof Blob === 'undefined' || !(data instanceof Blob)) return err;
  if (!/json/i.test(data.type)) return err;
  try {
    const parsed: unknown = JSON.parse(await data.text());
    return { ...err, response: { ...err.response, data: parsed } } as T;
  } catch {
    return err;
  }
}
