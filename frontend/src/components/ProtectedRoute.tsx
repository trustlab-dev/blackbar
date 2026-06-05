import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

interface Props {
  isAuthenticated: boolean;
  children: React.ReactNode;
  requiredRoles?: string[];
}

const ProtectedRoute: React.FC<Props> = ({ isAuthenticated, children, requiredRoles }) => {
  const { roles, isLoading } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to="/login" />;
  }

  if (isLoading) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Loading...</div>;
  }

  // Check user roles if specified
  if (requiredRoles && requiredRoles.length > 0) {
    const userRoles = roles.map(r => r.toLowerCase());
    const hasRequiredRole = requiredRoles.some(role => userRoles.includes(role.toLowerCase()));

    if (!hasRequiredRole) {
      return <Navigate to="/" replace />;
    }
  }

  return <>{children}</>;
};

export default ProtectedRoute;
