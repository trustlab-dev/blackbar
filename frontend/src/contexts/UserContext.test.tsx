import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, renderHook, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { UserProvider, useUser } from './UserContext';

const wrapper = ({ children }: { children: ReactNode }) => (
  <UserProvider>{children}</UserProvider>
);

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

// ---------------------------------------------------------------------------
// useUser outside of provider (defaults from defaultUserContext)
// ---------------------------------------------------------------------------
describe('useUser (outside provider)', () => {
  it('returns the default context shape (currentRole=admin, currentUser=null)', () => {
    // No wrapper — useContext returns the default value (the context was
    // created with defaultUserContext, not `undefined`, so this is safe).
    const { result } = renderHook(() => useUser());
    expect(result.current.currentRole).toBe('admin');
    expect(result.current.currentUser).toBeNull();
    // The default no-op setters should not throw.
    expect(() => result.current.setCurrentRole('analyst')).not.toThrow();
    expect(() => result.current.setCurrentUser({ id: 'x' })).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// UserProvider initial role
// ---------------------------------------------------------------------------
describe('UserProvider — initial state', () => {
  it('defaults currentRole to "admin" when localStorage is empty', () => {
    const { result } = renderHook(() => useUser(), { wrapper });
    expect(result.current.currentRole).toBe('admin');
    expect(result.current.currentUser).toBeNull();
  });

  it('seeds currentRole from localStorage on mount', () => {
    localStorage.setItem('userRole', 'analyst');
    const { result } = renderHook(() => useUser(), { wrapper });
    expect(result.current.currentRole).toBe('analyst');
  });

  it('accepts any of the documented UserRole values from localStorage', () => {
    const roles: Array<'owner' | 'admin' | 'analyst' | 'user' | 'guest'> = [
      'owner',
      'admin',
      'analyst',
      'user',
      'guest',
    ];
    for (const role of roles) {
      localStorage.setItem('userRole', role);
      const { result, unmount } = renderHook(() => useUser(), { wrapper });
      expect(result.current.currentRole).toBe(role);
      unmount();
    }
  });
});

// ---------------------------------------------------------------------------
// setCurrentRole / setCurrentUser (via provider)
// ---------------------------------------------------------------------------
describe('UserProvider — state updates', () => {
  it('setCurrentRole updates currentRole', () => {
    const { result } = renderHook(() => useUser(), { wrapper });
    act(() => {
      result.current.setCurrentRole('owner');
    });
    expect(result.current.currentRole).toBe('owner');
  });

  it('setCurrentUser updates currentUser', () => {
    const { result } = renderHook(() => useUser(), { wrapper });
    const u = { id: 'u-1', name: 'Alice', email: 'a@b.com', role: 'admin' as const };
    act(() => {
      result.current.setCurrentUser(u);
    });
    expect(result.current.currentUser).toEqual(u);
  });
});

// ---------------------------------------------------------------------------
// useEffect sync branch — when stored role differs from initial state
// ---------------------------------------------------------------------------
describe('UserProvider — localStorage sync effect', () => {
  it('does not double-update when storedRole matches the lazy-init value', () => {
    // Lazy init pulls 'analyst' from storage; the useEffect then re-reads
    // and finds storedRole === currentRole, so it must NOT call setCurrentRole.
    localStorage.setItem('userRole', 'analyst');
    const { result } = renderHook(() => useUser(), { wrapper });
    expect(result.current.currentRole).toBe('analyst');
  });

  it('syncs currentRole when storedRole differs from the lazy-init value', () => {
    // Lazy init reads null (empty storage) → currentRole defaults to 'admin'.
    // The useEffect re-reads and now sees 'analyst' (set between init + effect),
    // so it MUST call setCurrentRole('analyst').
    const getItemSpy = vi.spyOn(Storage.prototype, 'getItem');
    getItemSpy.mockImplementationOnce(() => null); // lazy init
    getItemSpy.mockImplementationOnce(() => 'analyst'); // effect
    const { result } = renderHook(() => useUser(), { wrapper });
    expect(result.current.currentRole).toBe('analyst');
    getItemSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// Provider renders children
// ---------------------------------------------------------------------------
describe('UserProvider — children rendering', () => {
  it('renders its children', () => {
    render(
      <UserProvider>
        <div data-testid="kid">hello</div>
      </UserProvider>,
    );
    expect(screen.getByTestId('kid')).toHaveTextContent('hello');
  });
});
