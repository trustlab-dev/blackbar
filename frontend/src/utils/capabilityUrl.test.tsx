import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import {
  clearCapability,
  replaceAddressBar,
  useCapabilityFromUrl,
} from './capabilityUrl';

const address = () =>
  `${window.location.pathname}${window.location.search}${window.location.hash}`;

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({ usr: null, key: 'k1', idx: 3 }, '', '/');
});

afterEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, '', '/');
});

describe('replaceAddressBar', () => {
  it('rewrites the URL in place and keeps the router history state', () => {
    window.history.replaceState({ usr: null, key: 'k1', idx: 3 }, '', '/collect/tok-1?x=1#y');
    const before = window.history.length;
    replaceAddressBar('/collect');
    expect(address()).toBe('/collect');
    expect(window.history.state).toEqual({ usr: null, key: 'k1', idx: 3 });
    expect(window.history.length).toBe(before);
  });
});

describe('useCapabilityFromUrl', () => {
  it('returns the URL value, strips it from the address bar and stashes it', () => {
    window.history.replaceState(null, '', '/collect/tok-1');
    const { result } = renderHook(() =>
      useCapabilityFromUrl('tok-1', { cleanPath: '/collect', storageKey: 'collect' }),
    );
    expect(result.current).toBe('tok-1');
    expect(address()).toBe('/collect');
    expect(sessionStorage.getItem('blackbar.capability.collect')).toBe('tok-1');
  });

  it('recovers the stashed value after a refresh of the stripped URL', () => {
    sessionStorage.setItem('blackbar.capability.collect', 'tok-1');
    window.history.replaceState(null, '', '/collect');
    const { result } = renderHook(() =>
      useCapabilityFromUrl(undefined, { cleanPath: '/collect', storageKey: 'collect' }),
    );
    expect(result.current).toBe('tok-1');
  });

  it('prefers a new link over an older stash', () => {
    sessionStorage.setItem('blackbar.capability.collect', 'old');
    const { result } = renderHook(() =>
      useCapabilityFromUrl('new', { cleanPath: '/collect', storageKey: 'collect' }),
    );
    expect(result.current).toBe('new');
    expect(sessionStorage.getItem('blackbar.capability.collect')).toBe('new');
  });

  it('does not stash single-use values and returns null after a refresh', () => {
    window.history.replaceState(null, '', '/public/verify/magic');
    const first = renderHook(() =>
      useCapabilityFromUrl('magic', { cleanPath: '/public/verify' }),
    );
    expect(first.result.current).toBe('magic');
    expect(address()).toBe('/public/verify');
    expect(sessionStorage.length).toBe(0);

    const afterRefresh = renderHook(() =>
      useCapabilityFromUrl(null, { cleanPath: '/public/verify' }),
    );
    expect(afterRefresh.result.current).toBeNull();
  });

  it('leaves the address bar alone when there is nothing to strip', () => {
    window.history.replaceState(null, '', '/track?keep=1');
    renderHook(() => useCapabilityFromUrl(null, { cleanPath: '/track', storageKey: 'track' }));
    expect(address()).toBe('/track?keep=1');
  });

  it('clearCapability removes a stash', () => {
    sessionStorage.setItem('blackbar.capability.activation', 'x');
    clearCapability('activation');
    expect(sessionStorage.getItem('blackbar.capability.activation')).toBeNull();
  });
});
