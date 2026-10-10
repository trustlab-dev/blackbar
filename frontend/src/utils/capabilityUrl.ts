/**
 * Capability URLs: links whose path or query carries the only credential
 * (magic-link verify, account activation, collection links, contributor
 * links, public tracking numbers).
 *
 * A page reached through one reads the token, keeps it in component state
 * (and in sessionStorage when a refresh must keep working), then removes it
 * from the address bar with `history.replaceState`. That keeps the token out
 * of anything that later reads `window.location`: Session Replay's rrweb Meta
 * event, bookmarks, the history dropdown and screen shares.
 *
 * The rewrite goes around React Router on purpose. The router keeps its own
 * location (with the token), so the page keeps rendering; only the visible
 * URL changes. The router's `history.state` entry is preserved so back and
 * forward navigation still line up.
 */
import { useEffect, useState } from 'react';

const STORAGE_PREFIX = 'blackbar.capability.';

/** Replace the address bar URL without navigating or adding a history entry. */
export function replaceAddressBar(cleanPath: string): void {
  try {
    const { pathname, search, hash } = window.location;
    if (`${pathname}${search}${hash}` === cleanPath) return;
    window.history.replaceState(window.history.state, '', cleanPath);
  } catch {
    // A sandboxed or unusual environment; the token stays visible but the
    // page still works.
  }
}

function readStash(key: string): string | null {
  try {
    return sessionStorage.getItem(STORAGE_PREFIX + key);
  } catch {
    return null;
  }
}

function writeStash(key: string, value: string): void {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + key, value);
  } catch {
    // Storage blocked: a refresh will show the "link missing" state.
  }
}

/** Forget a stashed capability (after it has been used up). */
export function clearCapability(key: string): void {
  try {
    sessionStorage.removeItem(STORAGE_PREFIX + key);
  } catch {
    // Nothing to clear.
  }
}

interface Options {
  /** Where the address bar should point once the token is removed. */
  cleanPath: string;
  /**
   * sessionStorage key for tokens that must survive a refresh. Omit it for
   * single-use tokens: a refresh then yields `null` and the page explains
   * that the link has been used.
   */
  storageKey?: string;
}

/**
 * Read a capability from the URL (router params or query), strip it from the
 * address bar after mount, and fall back to the sessionStorage stash when
 * the page is refreshed on the stripped URL.
 */
export function useCapabilityFromUrl(
  fromUrl: string | null | undefined,
  { cleanPath, storageKey }: Options,
): string | null {
  const [stashed] = useState<string | null>(() =>
    !fromUrl && storageKey ? readStash(storageKey) : null,
  );

  useEffect(() => {
    if (!fromUrl) return;
    if (storageKey) writeStash(storageKey, fromUrl);
    replaceAddressBar(cleanPath);
  }, [fromUrl, cleanPath, storageKey]);

  return fromUrl || stashed;
}
