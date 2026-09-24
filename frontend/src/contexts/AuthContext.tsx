import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { jwtDecode } from 'jwt-decode';
import { apiClient, revokeSessionOnServer } from '../api/client';
import { clearUser as clearTelemetryUser } from '../utils/telemetry';

interface User {
  id: string;
  email: string;
  name: string;
  status: string;
  roles: string[];
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  roles: string[];
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /**
   * End the session: asks the backend to revoke the token (POST
   * /auth/logout, fire-and-forget) and clears local auth state regardless of
   * the outcome.
   */
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [roles, setRoles] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const isTokenExpired = useCallback((t: string): boolean => {
    try {
      const decoded = jwtDecode<{ exp: number }>(t);
      return decoded.exp * 1000 < Date.now();
    } catch {
      return true;
    }
  }, []);

  useEffect(() => {
    // Load token from localStorage on mount
    const storedToken = localStorage.getItem('token');
    if (storedToken && !isTokenExpired(storedToken)) {
      setToken(storedToken);
      fetchCurrentUser(storedToken);
    } else {
      if (storedToken) {
        // Token exists but expired — clean up locally; the server already
        // refuses it, so there is nothing to revoke.
        clearSession();
      }
      setIsLoading(false);
    }
  }, []);

  // Periodically check token expiration (every 60s)
  useEffect(() => {
    if (!token) return;
    const interval = setInterval(() => {
      if (isTokenExpired(token)) {
        clearSession();
      }
    }, 60_000);
    return () => clearInterval(interval);
  }, [token, isTokenExpired]);

  const fetchCurrentUser = async (authToken: string) => {
    try {
      const response = await apiClient.get('/auth/me', {
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });
      setUser(response.data);
      setRoles(response.data.roles || []);

      // Persist username to localStorage for immediate display on next load
      if (response.data.name) {
        localStorage.setItem('username', response.data.name);
      }
    } catch (error) {
      console.error('[AuthContext] Failed to fetch current user:', error);
      clearSession();
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email: string, password: string) => {
    try {
      const response = await apiClient.post('/auth/login', {
        email,
        password,
      });

      const { access_token, roles: userRoles, user_id } = response.data;

      setToken(access_token);
      setRoles(userRoles);
      localStorage.setItem('token', access_token);
      if (user_id) localStorage.setItem('userId', user_id);
      localStorage.setItem('userRoles', JSON.stringify(userRoles));

      // Fetch full user details
      await fetchCurrentUser(access_token);
    } catch (error: any) {
      // Phase 4 Batch 4.4 (audit F1): re-throw the underlying axios
      // error so callers (e.g. `Login.tsx`) can pass it to
      // `getApiErrorMessage` and show backend-specific messages. The previous `throw new Error(...)` flattened the
      // error and made `Login.tsx`'s fallback branches unreachable.
      console.error('Login failed:', error);
      throw error;
    }
  };

  /** Forget the session locally (state, localStorage, telemetry user). */
  const clearSession = () => {
    setUser(null);
    setToken(null);
    setRoles([]);
    // Clear all auth-related localStorage keys
    const authKeys = [
      'token', 'username', 'userRole', 'userId', 'userRoles',
      'user', 'user_type', 'magic_link_email', 'dev_current_user'
    ];
    authKeys.forEach(key => localStorage.removeItem(key));
    clearTelemetryUser();
  };

  const logout = () => {
    // Read the token before clearing: revocation needs it, and the local
    // clear must happen whatever the server says.
    const current = token ?? localStorage.getItem('token');
    // Magic-link sessions cannot call the staff logout route (403).
    if (localStorage.getItem('user_type') !== 'public') {
      revokeSessionOnServer(current);
    }
    clearSession();
  };

  const value: AuthContextType = {
    user,
    token,
    roles,
    isAuthenticated: !!token && !!user,
    isLoading,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

/**
 * Like useAuth, but returns undefined outside an AuthProvider instead of
 * throwing. For components that are also rendered standalone (tests, embeds).
 */
export const useOptionalAuth = (): AuthContextType | undefined => useContext(AuthContext);

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
