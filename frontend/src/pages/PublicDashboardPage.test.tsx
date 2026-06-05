import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import { PublicDashboardPage } from './PublicDashboardPage';

// PublicPortalDashboard owns its own data fetching — stub it so these tests
// exercise PublicDashboardPage's auth-gate, header, and logout logic only.
vi.mock('../components/public/PublicPortalDashboard', () => ({
  PublicPortalDashboard: () => (
    <div data-testid="public-portal-dashboard">portal-dashboard</div>
  ),
}));

function NavCapture({ path }: { path: string }) {
  return <div data-testid="nav-target">{path}</div>;
}

function Harness() {
  return (
    <Routes>
      <Route path="/public/dashboard" element={<PublicDashboardPage />} />
      <Route
        path="/public/login"
        element={<NavCapture path="/public/login" />}
      />
    </Routes>
  );
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('PublicDashboardPage — auth gate', () => {
  it('redirects to login when no token is present', async () => {
    renderWithProviders(<Harness />, { route: '/public/dashboard' });
    await waitFor(() =>
      expect(screen.getByTestId('nav-target')).toHaveTextContent(
        '/public/login',
      ),
    );
  });

  it('redirects to login when user_type is not public', async () => {
    localStorage.setItem('token', 'tok');
    localStorage.setItem('user_type', 'staff');
    renderWithProviders(<Harness />, { route: '/public/dashboard' });
    await waitFor(() =>
      expect(screen.getByTestId('nav-target')).toHaveTextContent(
        '/public/login',
      ),
    );
  });

  it('renders the dashboard when authenticated as a public user', () => {
    localStorage.setItem('token', 'tok');
    localStorage.setItem('user_type', 'public');
    renderWithProviders(<Harness />, { route: '/public/dashboard' });
    expect(screen.getByTestId('public-portal-dashboard')).toBeInTheDocument();
    expect(screen.getByText('FOI Portal')).toBeInTheDocument();
  });
});

describe('PublicDashboardPage — header', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'tok');
    localStorage.setItem('user_type', 'public');
  });

  it('shows the user email when a user object is stored', () => {
    localStorage.setItem('user', JSON.stringify({ email: 'jane@example.com' }));
    renderWithProviders(<Harness />, { route: '/public/dashboard' });
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
  });

  it('omits the email line when the stored user has no email', () => {
    localStorage.setItem('user', JSON.stringify({}));
    renderWithProviders(<Harness />, { route: '/public/dashboard' });
    expect(screen.queryByText(/@/)).not.toBeInTheDocument();
  });
});

describe('PublicDashboardPage — logout', () => {
  it('clears auth storage and navigates to login on sign out', async () => {
    localStorage.setItem('token', 'tok');
    localStorage.setItem('user_type', 'public');
    localStorage.setItem('user', JSON.stringify({ email: 'jane@example.com' }));
    localStorage.setItem('magic_link_email', 'jane@example.com');
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/public/dashboard' });

    await user.click(screen.getByRole('button', { name: /sign out/i }));

    await waitFor(() =>
      expect(screen.getByTestId('nav-target')).toHaveTextContent(
        '/public/login',
      ),
    );
    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('user')).toBeNull();
    expect(localStorage.getItem('user_type')).toBeNull();
    expect(localStorage.getItem('magic_link_email')).toBeNull();
  });
});
