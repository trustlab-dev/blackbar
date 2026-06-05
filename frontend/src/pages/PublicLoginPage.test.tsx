import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import { server } from '../test-utils/msw-handlers';
import {
  renderWithProviders,
  screen,
  waitFor,
} from '../test-utils/render';
import { PublicLoginPage } from './PublicLoginPage';

// MagicLinkLogin owns its own data fetching and email-sending flow — stub it
// so these tests exercise PublicLoginPage's branding + redirect logic only.
vi.mock('../components/auth/MagicLinkLogin', () => ({
  MagicLinkLogin: ({ onSuccess }: { onSuccess: () => void }) => (
    <button data-testid="magic-link-login" onClick={() => onSuccess()}>
      magic-link-login
    </button>
  ),
}));

function NavCapture({ path }: { path: string }) {
  return <div data-testid="nav-target">{path}</div>;
}

function Harness() {
  return (
    <Routes>
      <Route path="/public/login" element={<PublicLoginPage />} />
      <Route
        path="/public/dashboard"
        element={<NavCapture path="/public/dashboard" />}
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

describe('PublicLoginPage — default render', () => {
  it('renders the default org name when config fetch fails', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 500 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/login' });
    expect(
      screen.getByText('Freedom of Information Portal'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/sign in to view and manage your foi requests/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId('magic-link-login')).toBeInTheDocument();
  });

  it('logs an error when config fetch fails', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 500 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/login' });
    await waitFor(() =>
      expect(errSpy).toHaveBeenCalledWith(
        'Error fetching public config:',
        expect.anything(),
      ),
    );
  });
});

describe('PublicLoginPage — branding from config', () => {
  it('renders org name, logo, and footer text from the config endpoint', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          org_name: 'Acme FOI Office',
          org_logo_url: 'https://example.com/logo.png',
          primary_color: '#ff0000',
          footer_text: 'Powered by Acme',
        }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/login' });
    expect(await screen.findByText('Acme FOI Office')).toBeInTheDocument();
    const logo = screen.getByRole('img', {
      name: 'Acme FOI Office',
    }) as HTMLImageElement;
    expect(logo.src).toBe('https://example.com/logo.png');
    expect(screen.getByText('Powered by Acme')).toBeInTheDocument();
  });

  it('falls back to defaults when config fields are missing/null', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          org_name: null,
          org_logo_url: null,
          primary_color: null,
          footer_text: null,
        }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/public/login' });
    expect(
      await screen.findByText('Freedom of Information Portal'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});

describe('PublicLoginPage — auth redirect', () => {
  it('redirects to the dashboard when already authenticated as a public user', async () => {
    localStorage.setItem('token', 'tok');
    localStorage.setItem('user_type', 'public');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/public/login' });
    await waitFor(() =>
      expect(screen.getByTestId('nav-target')).toHaveTextContent(
        '/public/dashboard',
      ),
    );
  });

  it('does not redirect when token is present but user_type is not public', async () => {
    localStorage.setItem('token', 'tok');
    localStorage.setItem('user_type', 'staff');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/public/login' });
    expect(screen.getByTestId('magic-link-login')).toBeInTheDocument();
    expect(screen.queryByTestId('nav-target')).not.toBeInTheDocument();
  });
});

describe('PublicLoginPage — login success callback', () => {
  it('logs a confirmation message when the magic link is sent', async () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<Harness />, { route: '/public/login' });
    screen.getByTestId('magic-link-login').click();
    expect(logSpy).toHaveBeenCalledWith('Magic link sent successfully');
  });
});
