import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import {
  renderWithProviders,
  screen,
  waitFor,
} from '../../test-utils/render';
import { MagicLinkLogin } from './MagicLinkLogin';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('MagicLinkLogin — initial render', () => {
  it('renders the email entry form with title, email field, optional name field, and submit button', () => {
    renderWithProviders(<MagicLinkLogin />);
    expect(
      screen.getByRole('heading', { name: /continue with your email/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/we'll send you a magic link to sign in/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/your name \(optional\)/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /send magic link/i }),
    ).toBeInTheDocument();
  });

  it('disables the submit button when email is empty', () => {
    renderWithProviders(<MagicLinkLogin />);
    const button = screen.getByRole('button', { name: /send magic link/i });
    expect(button).toBeDisabled();
  });

  it('enables the submit button once an email is entered', async () => {
    const user = userEvent.setup();
    renderWithProviders(<MagicLinkLogin />);
    const email = screen.getByLabelText(/email address/i);
    await user.type(email, 'foo@bar.com');
    expect(
      screen.getByRole('button', { name: /send magic link/i }),
    ).not.toBeDisabled();
  });
});

describe('MagicLinkLogin — successful submission', () => {
  it('sends the magic link and shows the confirmation screen', async () => {
    const user = userEvent.setup();
    let postBody: any = null;
    server.use(
      http.post(
        '/api/v1/auth/public/magic-link/request',
        async ({ request }) => {
          postBody = await request.json();
          return HttpResponse.json({ expires_in: 900 });
        },
      ),
    );

    renderWithProviders(<MagicLinkLogin />);
    await user.type(screen.getByLabelText(/email address/i), 'foo@bar.com');
    await user.type(screen.getByLabelText(/your name/i), 'Foo Bar');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    await waitFor(() =>
      expect(screen.getByText(/check your email/i)).toBeInTheDocument(),
    );
    expect(screen.getByText('foo@bar.com')).toBeInTheDocument();
    expect(screen.getByText(/expire in 15 minutes/i)).toBeInTheDocument();
    expect(localStorage.getItem('magic_link_email')).toBe('foo@bar.com');
    expect(postBody).toEqual({ email: 'foo@bar.com', name: 'Foo Bar' });
  });

  it('omits the name field from the request payload when empty', async () => {
    const user = userEvent.setup();
    let postBody: any = null;
    server.use(
      http.post(
        '/api/v1/auth/public/magic-link/request',
        async ({ request }) => {
          postBody = await request.json();
          return HttpResponse.json({ expires_in: 900 });
        },
      ),
    );

    renderWithProviders(<MagicLinkLogin />);
    await user.type(screen.getByLabelText(/email address/i), 'a@b.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    await waitFor(() =>
      expect(screen.getByText(/check your email/i)).toBeInTheDocument(),
    );
    expect(postBody).toEqual({ email: 'a@b.com' });
  });

  it('invokes onSuccess callback after sending', async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    server.use(
      http.post('/api/v1/auth/public/magic-link/request', () =>
        HttpResponse.json({ expires_in: 900 }),
      ),
    );

    renderWithProviders(<MagicLinkLogin onSuccess={onSuccess} />);
    await user.type(screen.getByLabelText(/email address/i), 'a@b.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  });

  it('allows resetting form via "Use a different email" button', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('/api/v1/auth/public/magic-link/request', () =>
        HttpResponse.json({ expires_in: 900 }),
      ),
    );

    renderWithProviders(<MagicLinkLogin />);
    await user.type(screen.getByLabelText(/email address/i), 'a@b.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    await waitFor(() =>
      expect(screen.getByText(/check your email/i)).toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole('button', { name: /use a different email/i }),
    );
    expect(screen.getByLabelText(/email address/i)).toHaveValue('');
  });
});

describe('MagicLinkLogin — error states', () => {
  it('shows a friendly rate-limit message on 429 response', async () => {
    const user = userEvent.setup();
    server.use(
      http.post(
        '/api/v1/auth/public/magic-link/request',
        () => new HttpResponse(null, { status: 429 }),
      ),
    );

    renderWithProviders(<MagicLinkLogin />);
    await user.type(screen.getByLabelText(/email address/i), 'a@b.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    await waitFor(() =>
      expect(screen.getByText(/too many requests/i)).toBeInTheDocument(),
    );
  });

  it('surfaces backend detail when provided', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('/api/v1/auth/public/magic-link/request', () =>
        HttpResponse.json({ detail: 'Email not allowed' }, { status: 400 }),
      ),
    );

    renderWithProviders(<MagicLinkLogin />);
    await user.type(screen.getByLabelText(/email address/i), 'a@b.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    await waitFor(() =>
      expect(screen.getByText('Email not allowed')).toBeInTheDocument(),
    );
  });

  it('falls back to the default error message when no detail is supplied', async () => {
    const user = userEvent.setup();
    server.use(
      http.post(
        '/api/v1/auth/public/magic-link/request',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderWithProviders(<MagicLinkLogin />);
    await user.type(screen.getByLabelText(/email address/i), 'a@b.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/failed to send magic link/i),
      ).toBeInTheDocument(),
    );
  });

  it('allows dismissing the error via the close button', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('/api/v1/auth/public/magic-link/request', () =>
        HttpResponse.json({ detail: 'Email not allowed' }, { status: 400 }),
      ),
    );

    renderWithProviders(<MagicLinkLogin />);
    await user.type(screen.getByLabelText(/email address/i), 'a@b.com');
    await user.click(screen.getByRole('button', { name: /send magic link/i }));

    await waitFor(() =>
      expect(screen.getByText('Email not allowed')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: /close/i }));
    expect(screen.queryByText('Email not allowed')).not.toBeInTheDocument();
  });
});
