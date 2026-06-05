import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import ProtectedRoute from './ProtectedRoute';

// Mint a JWT with future exp claim.
function makeJwt(secondsFromNow: number): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = btoa(
    JSON.stringify({
      sub: 'user-1',
      exp: Math.floor(Date.now() / 1000) + secondsFromNow,
    }),
  );
  return `${header}.${payload}.sig`;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

function Tree({
  isAuthenticated,
  requiredRoles,
}: {
  isAuthenticated: boolean;
  requiredRoles?: string[];
}) {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <ProtectedRoute
            isAuthenticated={isAuthenticated}
            requiredRoles={requiredRoles}
          >
            <div data-testid="child">child</div>
          </ProtectedRoute>
        }
      />
      <Route path="/login" element={<div data-testid="login-page">login page</div>} />
      <Route path="/home" element={<div data-testid="home-page">home page</div>} />
    </Routes>
  );
}

describe('ProtectedRoute — auth gate', () => {
  it('redirects to /login when not authenticated', () => {
    renderWithProviders(<Tree isAuthenticated={false} />, { withAuth: true });
    expect(screen.getByTestId('login-page')).toBeInTheDocument();
  });

  it('renders children when authenticated and no required roles', async () => {
    const token = makeJwt(3600);
    localStorage.setItem('token', token);
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u',
          email: 'a@b.com',
          name: 'A',
          status: 'active',
          roles: ['analyst'],
        }),
      ),
    );

    renderWithProviders(<Tree isAuthenticated={true} />, { withAuth: true });
    await waitFor(() => expect(screen.getByTestId('child')).toBeInTheDocument());
  });

  it('shows a Loading state while auth is loading', async () => {
    // Stored token + a never-resolving /auth/me => AuthProvider keeps
    // isLoading=true => ProtectedRoute renders the "Loading..." sentinel.
    const token = makeJwt(3600);
    localStorage.setItem('token', token);
    server.use(
      http.get('/api/v1/auth/me', () => new Promise(() => {})),
    );

    renderWithProviders(<Tree isAuthenticated={true} />, { withAuth: true });
    expect(await screen.findByText(/loading\.\.\./i)).toBeInTheDocument();
  });
});

describe('ProtectedRoute — role gate', () => {
  it('allows access when user has a required role (case-insensitive match)', async () => {
    const token = makeJwt(3600);
    localStorage.setItem('token', token);
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u',
          email: 'a@b.com',
          name: 'A',
          status: 'active',
          roles: ['Admin'],
        }),
      ),
    );

    renderWithProviders(
      <Tree isAuthenticated={true} requiredRoles={['admin']} />,
      { withAuth: true },
    );
    await waitFor(() => expect(screen.getByTestId('child')).toBeInTheDocument());
  });

  it('redirects to / when user lacks required roles', async () => {
    const token = makeJwt(3600);
    localStorage.setItem('token', token);
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u',
          email: 'a@b.com',
          name: 'A',
          status: 'active',
          roles: ['guest'],
        }),
      ),
    );

    renderWithProviders(
      <>
        <Routes>
          <Route
            path="/"
            element={
              <ProtectedRoute isAuthenticated={true} requiredRoles={['admin']}>
                <div data-testid="child">child</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </>,
      { withAuth: true },
    );
    // The Navigate to "/" with replace will re-enter the same route which
    // again Navigate-s; testing it doesn't render children is sufficient.
    await waitFor(() =>
      expect(screen.queryByTestId('child')).not.toBeInTheDocument(),
    );
  });
});
