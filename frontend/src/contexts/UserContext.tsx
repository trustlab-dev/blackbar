import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

type UserRole = 'owner' | 'admin' | 'analyst' | 'user' | 'guest';

const USER_ROLES: readonly UserRole[] = ['owner', 'admin', 'analyst', 'user', 'guest'];

/**
 * UI-only role hint. The backend enforces every permission; this just decides
 * which tabs and links to render. It defaults to `null` (no elevated UI)
 * rather than a privileged role, and ignores unknown values in storage.
 */
interface UserContextType {
  currentRole: UserRole | null;
  setCurrentRole: (role: UserRole | null) => void;
  currentUser: {
    id: string;
    name: string;
    email: string;
    role: UserRole;
  } | null;
  setCurrentUser: (user: any) => void;
}

const defaultUserContext: UserContextType = {
  currentRole: null,
  setCurrentRole: () => {},
  currentUser: null,
  setCurrentUser: () => {}
};

function readStoredRole(): UserRole | null {
  const stored = localStorage.getItem('userRole');
  return USER_ROLES.includes(stored as UserRole) ? (stored as UserRole) : null;
}

/**
 * Roles that AuthContext saved at login (`userRoles`), lower-cased. A UI hint
 * for components rendered outside AuthProvider; never an authorization check.
 */
export function getStoredRoles(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem('userRoles') || '[]');
    return Array.isArray(parsed)
      ? parsed.filter((r): r is string => typeof r === 'string').map((r) => r.toLowerCase())
      : [];
  } catch {
    return [];
  }
}

const UserContext = createContext<UserContextType>(defaultUserContext);

export const useUser = () => useContext(UserContext);

export const UserProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [currentRole, setCurrentRole] = useState<UserRole | null>(readStoredRole);
  const [currentUser, setCurrentUser] = useState(null);

  // Sync with localStorage changes
  useEffect(() => {
    const storedRole = readStoredRole();
    if (storedRole && storedRole !== currentRole) {
      setCurrentRole(storedRole);
    }
  }, []);

  return (
    <UserContext.Provider value={{ currentRole, setCurrentRole, currentUser, setCurrentUser }}>
      {children}
    </UserContext.Provider>
  );
};
