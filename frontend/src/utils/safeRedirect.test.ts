import { describe, it, expect } from 'vitest';
import { getSafeRedirect } from './safeRedirect';

const ORIGIN = 'https://app.example';

describe('getSafeRedirect', () => {
  it('accepts a same-origin path', () => {
    expect(getSafeRedirect('/cases/123', '/', ORIGIN)).toBe('/cases/123');
  });

  it('keeps the query string and hash of a same-origin path', () => {
    expect(getSafeRedirect('/cases/123?tab=docs#top', '/', ORIGIN)).toBe(
      '/cases/123?tab=docs#top',
    );
  });

  it.each([
    ['backslash after the leading slash', '/\\evil.example'],
    ['protocol-relative URL', '//evil.example'],
    ['absolute URL', 'https://evil.example'],
    ['percent-encoded backslash', '/%5Cevil.example'],
    ['lower-case percent-encoded backslash', '/%5cevil.example'],
    ['tab that the URL parser strips', '/\t/evil.example'],
    ['dot segment that collapses to //', '/.//evil.example'],
    ['parent segment that collapses to //', '/a/..//evil.example'],
    ['javascript: URL', 'javascript:alert(1)'],
    ['relative path without a leading slash', 'cases/123'],
  ])('rejects %s', (_label, value) => {
    expect(getSafeRedirect(value, '/', ORIGIN)).toBe('/');
  });

  it('returns the fallback for an empty or missing value', () => {
    expect(getSafeRedirect(null, '/home', ORIGIN)).toBe('/home');
    expect(getSafeRedirect(undefined, '/home', ORIGIN)).toBe('/home');
    expect(getSafeRedirect('', '/home', ORIGIN)).toBe('/home');
  });

  it('defaults the origin to window.location.origin', () => {
    expect(getSafeRedirect('/cases/9')).toBe('/cases/9');
    expect(getSafeRedirect('//evil.example')).toBe('/');
  });
});
