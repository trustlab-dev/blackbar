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

describe('ActivateAccount — token leaves the address bar', () => {
  afterEach(() => window.history.replaceState(null, '', '/'));

  it('strips email and token from the URL but keeps them for the form', async () => {
    window.history.replaceState(null, '', '/activate?email=a@b.com&token=abc123');
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=abc123',
    });
    await waitFor(() => expect(window.location.search).toBe(''));
    expect(window.location.pathname).toBe('/activate');
    expect(screen.getByLabelText(/email/i)).toHaveValue('a@b.com');
  });

  it('survives a refresh on the stripped URL and submits the original token', async () => {
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=abc123',
    }).unmount();

    let body: Record<string, unknown> | undefined;
    server.use(
      http.post('/api/v1/auth/activate-owner', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ message: 'ok' });
      }),
    );
    // Refresh: same tab, token no longer in the URL.
    renderWithProviders(<Harness />, { route: '/activate' });
    expect(screen.queryByText(/invalid activation link/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toHaveValue('a@b.com');

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^new password/i), 'CorrectHorse12!');
    await user.type(screen.getByLabelText(/confirm password/i), 'CorrectHorse12!');
    await user.click(screen.getByRole('button', { name: /activate account/i }));
    await waitFor(() => expect(body).toBeDefined());
    expect(body).toMatchObject({ email: 'a@b.com', token: 'abc123' });
    // Used up: the stash is cleared once activation succeeds.
    await waitFor(() => expect(sessionStorage.length).toBe(0));
  });
});

describe('ActivateAccount — form validation', () => {
  it('shows error when passwords do not match', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.type(screen.getByLabelText(/^new password/i), 'password1234');
    await user.type(screen.getByLabelText(/confirm password/i), 'different');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
  });

  it('shows error when password is shorter than 12 characters', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    // 11 characters: accepted by the old 8-character rule, refused now.
    await user.type(screen.getByLabelText(/^new password/i), 'password123');
    await user.type(screen.getByLabelText(/confirm password/i), 'password123');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    expect(
      screen.getByText(/password must be at least 12 characters/i),
    ).toBeInTheDocument();
  });

  it('shows error when password is longer than 72 bytes', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    const long = 'a'.repeat(73);
    await user.type(screen.getByLabelText(/^new password/i), long);
    await user.type(screen.getByLabelText(/confirm password/i), long);
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    expect(screen.getByText(/password must be at most 72 bytes/i)).toBeInTheDocument();
  });

  it('states the 12-character requirement in the helper text', () => {
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    expect(screen.getByText(/^At least 12 characters/)).toBeInTheDocument();
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
    await user.type(screen.getByLabelText(/^new password/i), 'password1234');
    await user.type(screen.getByLabelText(/confirm password/i), 'password1234');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    await waitFor(() =>
      expect(screen.getByText(/account activated!/i)).toBeInTheDocument(),
    );
    expect(postBody).toEqual({
      email: 'a@b.com',
      token: 'tok',
      password: 'password1234',
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
    await user.type(screen.getByLabelText(/^new password/i), 'password1234');
    await user.type(screen.getByLabelText(/confirm password/i), 'password1234');
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
    await user.type(screen.getByLabelText(/^new password/i), 'password1234');
    await user.type(screen.getByLabelText(/confirm password/i), 'password1234');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/failed to activate account/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows the backend's 422 password-policy message", async () => {
    server.use(
      http.post('/api/v1/auth/activate-owner', () =>
        HttpResponse.json(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: 'Invalid request data',
              details: {
                errors: [
                  {
                    loc: ['body', 'password'],
                    msg: 'Value error, Password must be at least 12 characters',
                  },
                ],
              },
            },
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, {
      route: '/activate?email=a@b.com&token=tok',
    });
    await user.type(screen.getByLabelText(/^new password/i), 'password1234');
    await user.type(screen.getByLabelText(/confirm password/i), 'password1234');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    expect(
      await screen.findByText(
        'Invalid request data: password: Password must be at least 12 characters',
      ),
    ).toBeInTheDocument();
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
    await user.type(screen.getByLabelText(/^new password/i), 'password1234');
    await user.type(screen.getByLabelText(/confirm password/i), 'password1234');
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
