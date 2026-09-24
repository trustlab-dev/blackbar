/**
 * Validate a post-login `redirect` value so it can only point back into this
 * app. Returns a normalised same-origin path (pathname + search + hash), or
 * `fallback` when the value is missing or could leave the origin.
 *
 * Checking `startsWith('/')` alone is not enough: WHATWG URL parsing treats
 * `\` like `/`, strips tabs and newlines, and resolves dot segments, so values
 * such as `/\evil.example`, `/\t/evil.example` or `/.//evil.example` all end
 * up cross-origin once the router hands them to `history.pushState` (which
 * then falls back to a full `location.assign`).
 */
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

export function getSafeRedirect(
  raw: string | null | undefined,
  fallback = '/',
  origin: string = window.location.origin,
): string {
  if (!raw) return fallback;
  if (!raw.startsWith('/') || raw.startsWith('//')) return fallback;
  if (raw.includes('\\') || /%5c/i.test(raw) || CONTROL_CHARS.test(raw)) {
    return fallback;
  }

  let resolved: URL;
  try {
    resolved = new URL(raw, origin);
  } catch {
    return fallback;
  }

  if (resolved.origin !== origin) return fallback;
  // Dot segments can normalise to a protocol-relative path ("/.//evil").
  if (!resolved.pathname.startsWith('/') || resolved.pathname.startsWith('//')) {
    return fallback;
  }

  return resolved.pathname + resolved.search + resolved.hash;
}
