import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

type UserRole = 'owner' | 'admin' | 'analyst' | 'user' | 'guest';

interface UserContextType {
  currentRole: UserRole;
  setCurrentRole: (role: UserRole) => void;
  currentUser: {
    id: string;
    name: string;
    email: string;
    role: UserRole;
  } | null;
  setCurrentUser: (user: any) => void;
}

const defaultUserContext: UserContextType = {
  currentRole: 'admin',
  setCurrentRole: () => {},
  currentUser: null,
  setCurrentUser: () => {}
};

const UserContext = createContext<UserContextType>(defaultUserContext);

export const useUser = () => useContext(UserContext);

export const UserProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [currentRole, setCurrentRole] = useState<UserRole>(() => {
    // Initialize from localStorage
    const storedRole = localStorage.getItem('userRole');
    return (storedRole as UserRole) || 'admin';
  });
  const [currentUser, setCurrentUser] = useState(null);

  // Sync with localStorage changes
  useEffect(() => {
    const storedRole = localStorage.getItem('userRole');
    if (storedRole && storedRole !== currentRole) {
      setCurrentRole(storedRole as UserRole);
    }
  }, []);

  return (
    <UserContext.Provider value={{ currentRole, setCurrentRole, currentUser, setCurrentUser }}>
      {children}
    </UserContext.Provider>
  );
};
