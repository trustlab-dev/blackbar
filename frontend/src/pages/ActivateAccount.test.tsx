import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import {
  act,
  renderWithProviders,
  screen,
  waitFor,
} from '../test-utils/render';
import ActivateAccount from './ActivateAccount';

function NavCapture({
  path,
  onNavigate,
}: {
  path: string;
  onNavigate?: (path: string) => void;
}) {
  onNavigate?.(path);
  return <div data-testid="nav-target">{path}</div>;
}

function Harness({ onNavigate }: { onNavigate?: (path: string) => void }) {
  return (
    <Routes>
      <Route path="/activate" element={<ActivateAccount />} />
      <Route
        path="/login"
        element={<NavCapture path="/login" onNavigate={onNavigate} />}
      />
    </Routes>
  );
}

beforeEach(() => {
  // Phase 4 Batch 4.4 (audit F2): ActivateAccount now uses the shared
  // `publicApi` (baseURL '/api/v1'), so MSW handlers below match
  // path-only URLs rooted at `/api/v1`.
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ActivateAccount — URL params', () => {
  it('shows invalid-link error when no email or token in URL', () => {
    renderWithProviders(<Harness />, { route: '/activate' });
    expect(screen.getByText(/invalid activation link/i)).toBeInTheDocument();
  });

  it('shows invalid-link error when only email is provided', () => {
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com',
    });
    expect(screen.getByText(/invalid activation link/i)).toBeInTheDocument();
  });

  it('pre-fills email field from URL parameters and disables it', () => {
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=abc123',
    });
    const emailField = screen.getByLabelText(/email/i) as HTMLInputElement;
    expect(emailField).toHaveValue('a@b.com');
    expect(emailField).toBeDisabled();
  });
});

describe('ActivateAccount — form validation', () => {
  it('shows error when passwords do not match', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.type(screen.getByLabelText(/^new password/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'different');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
  });

  it('shows error when password is shorter than 8 characters', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.type(screen.getByLabelText(/^new password/i), 'short');
    await user.type(screen.getByLabelText(/confirm password/i), 'short');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    expect(
      screen.getByText(/password must be at least 8 characters/i),
    ).toBeInTheDocument();
  });

  it('disables the submit button when fields are missing', () => {
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    expect(
      screen.getByRole('button', { name: /activate account/i }),
    ).toBeDisabled();
  });
});

describe('ActivateAccount — successful activation', () => {
  it('posts to /auth/activate-owner, shows success state, and redirects after delay', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let postBody: any = null;
    server.use(
      http.post(
        '/api/v1/auth/activate-owner',
        async ({ request }) => {
          postBody = await request.json();
          return HttpResponse.json({ ok: true });
        },
      ),
    );

    const navSpy = vi.fn();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<Harness onNavigate={navSpy} />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.type(screen.getByLabelText(/^new password/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    await waitFor(() =>
      expect(screen.getByText(/account activated!/i)).toBeInTheDocument(),
    );
    expect(postBody).toEqual({
      email: 'a@b.com',
      token: 'tok',
      password: 'password123',
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    await waitFor(() => expect(navSpy).toHaveBeenCalledWith('/login'));

    vi.useRealTimers();
  });
});

describe('ActivateAccount — error handling', () => {
  it('surfaces backend detail message', async () => {
    server.use(
      http.post('/api/v1/auth/activate-owner', () =>
        HttpResponse.json({ detail: 'Token already used' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.type(screen.getByLabelText(/^new password/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    await waitFor(() =>
      expect(screen.getByText(/token already used/i)).toBeInTheDocument(),
    );
  });

  it('shows default error message when no detail is provided', async () => {
    server.use(
      http.post(
        '/api/v1/auth/activate-owner',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.type(screen.getByLabelText(/^new password/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/failed to activate account/i),
      ).toBeInTheDocument(),
    );
  });

  it('shows a loading spinner during submission', async () => {
    let resolve: () => void = () => {};
    const ready = new Promise<void>((r) => {
      resolve = r;
    });
    server.use(
      http.post('/api/v1/auth/activate-owner', async () => {
        await ready;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.type(screen.getByLabelText(/^new password/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    // Submit button shows a CircularProgress while loading — the button
    // contains a progress element when loading is true. Use type="submit"
    // selector since accessible name disappears.
    await waitFor(() => {
      const submitBtn = document.querySelector('button[type="submit"]');
      expect(submitBtn).toBeDisabled();
    });
    resolve();
    await waitFor(() => expect(screen.getByText(/account activated!/i)).toBeInTheDocument());
  });
});

describe('ActivateAccount — navigation', () => {
  it('navigates to /login when "Log in" link is clicked from form', async () => {
    const user = userEvent.setup();
    const navSpy = vi.fn();
    renderWithProviders(<Harness onNavigate={navSpy} />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.click(screen.getByRole('button', { name: /^log in$/i }));
    await waitFor(() => expect(navSpy).toHaveBeenCalledWith('/login'));
  });
});
