import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import {
  renderWithProviders,
  screen,
  waitFor,
} from '../test-utils/render';
import PublicRequestForm from './PublicRequestForm';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('PublicRequestForm — initial render', () => {
  it('renders form fields with default org name when config fetch fails', async () => {
    server.use(
      http.get(
        '/api/v1/admin/config/public',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderWithProviders(<PublicRequestForm />);
    expect(
      await screen.findByText(/freedom of information office/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/request title/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/detailed description/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/full name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
  });

  it('renders org logo and footer when provided in config', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({
          org_name: 'Acme Office',
          org_logo_url: 'https://example.com/logo.png',
          contact_email: 'foi@acme.com',
          footer_text: 'Custom footer text here',
          request_categories: ['Records', 'Personnel'],
        }),
      ),
    );
    renderWithProviders(<PublicRequestForm />);
    const logo = await screen.findByAltText('Acme Office');
    expect(logo).toHaveAttribute('src', 'https://example.com/logo.png');
    expect(screen.getByText(/custom footer text here/i)).toBeInTheDocument();
    // Categories appear in the select
    expect(screen.getByLabelText(/request category/i)).toBeInTheDocument();
  });
});

describe('PublicRequestForm — user pre-fill', () => {
  it('pre-fills email and name from localStorage when authenticated', async () => {
    localStorage.setItem(
      'user',
      JSON.stringify({ email: 'jane@example.com', name: 'Jane Doe' }),
    );
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<PublicRequestForm />);
    await waitFor(() => {
      const email = screen.getByLabelText(/email address/i) as HTMLInputElement;
      expect(email.value).toBe('jane@example.com');
    });
    const name = screen.getByLabelText(/full name/i) as HTMLInputElement;
    expect(name.value).toBe('Jane Doe');
    // Email field is disabled when logged in
    expect(screen.getByLabelText(/email address/i)).toBeDisabled();
  });

  it('keeps prior name when localStorage user has no name', async () => {
    localStorage.setItem(
      'user',
      JSON.stringify({ email: 'jane@example.com' }),
    );
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<PublicRequestForm />);
    const email = (await screen.findByLabelText(
      /email address/i,
    )) as HTMLInputElement;
    expect(email.value).toBe('jane@example.com');
  });

  it('does nothing when user JSON parsing fails', async () => {
    localStorage.setItem('user', '{not json');
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/email address/i);
    expect(errSpy).toHaveBeenCalled();
  });

  it('does nothing when authenticated user has no email field', async () => {
    localStorage.setItem('user', JSON.stringify({ name: 'No Email' }));
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    renderWithProviders(<PublicRequestForm />);
    const email = (await screen.findByLabelText(
      /email address/i,
    )) as HTMLInputElement;
    expect(email.value).toBe('');
  });
});

describe('PublicRequestForm — form input handling', () => {
  it('updates title, description, and requester fields on input', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/request title/i);

    await user.type(screen.getByLabelText(/request title/i), 'My title');
    await user.type(
      screen.getByLabelText(/detailed description/i),
      'My description',
    );
    await user.type(screen.getByLabelText(/full name/i), 'Test User');
    await user.type(
      screen.getByLabelText(/email address/i),
      'test@example.com',
    );
    await user.type(
      screen.getByLabelText(/phone number/i),
      '555-1234',
    );
    await user.type(
      screen.getByLabelText(/organization/i),
      'TestOrg',
    );

    expect(
      (screen.getByLabelText(/request title/i) as HTMLInputElement).value,
    ).toBe('My title');
    expect(
      (screen.getByLabelText(/detailed description/i) as HTMLTextAreaElement)
        .value,
    ).toBe('My description');
    expect(
      (screen.getByLabelText(/full name/i) as HTMLInputElement).value,
    ).toBe('Test User');
  });

  it('updates category via select dropdown', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({ request_categories: ['Personnel', 'Budget'] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    const select = (await screen.findByLabelText(
      /request category/i,
    )) as HTMLSelectElement;
    await user.selectOptions(select, 'Budget');
    expect(select.value).toBe('Budget');
  });
});

describe('PublicRequestForm — submission', () => {
  it('submits and shows tracking number on success', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/cases/public/submit', () =>
        HttpResponse.json({ tracking_number: 'TRK-XYZ' }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/request title/i);

    await user.type(screen.getByLabelText(/request title/i), 'T');
    await user.type(screen.getByLabelText(/detailed description/i), 'D');
    await user.type(screen.getByLabelText(/full name/i), 'N');
    await user.type(screen.getByLabelText(/email address/i), 'e@x.com');
    await user.click(screen.getByRole('button', { name: /submit request/i }));

    expect(
      await screen.findByText(/request submitted successfully/i),
    ).toBeInTheDocument();
    expect(screen.getByText('TRK-XYZ')).toBeInTheDocument();
  });

  it('renders track link to /track/:trackingNumber when no user is signed in', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/cases/public/submit', () =>
        HttpResponse.json({ tracking_number: 'TRK-XYZ' }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/request title/i);
    await user.type(screen.getByLabelText(/request title/i), 'T');
    await user.type(screen.getByLabelText(/detailed description/i), 'D');
    await user.type(screen.getByLabelText(/full name/i), 'N');
    await user.type(screen.getByLabelText(/email address/i), 'e@x.com');
    await user.click(screen.getByRole('button', { name: /submit request/i }));

    const link = await screen.findByRole('link', {
      name: /track your request/i,
    });
    expect(link).toHaveAttribute('href', '/track/TRK-XYZ');
  });

  it('shows "View My Requests" link to dashboard when user is signed in', async () => {
    localStorage.setItem(
      'user',
      JSON.stringify({ email: 'a@b.com', name: 'A' }),
    );
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/cases/public/submit', () =>
        HttpResponse.json({ tracking_number: 'TRK-X' }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/request title/i);
    await user.type(screen.getByLabelText(/request title/i), 'T');
    await user.type(screen.getByLabelText(/detailed description/i), 'D');
    await user.type(screen.getByLabelText(/full name/i), 'N');
    await user.click(screen.getByRole('button', { name: /submit request/i }));

    const link = await screen.findByRole('link', {
      name: /view my requests/i,
    });
    expect(link).toHaveAttribute('href', '/public/dashboard');
  });

  it('allows submitting another request after success', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/cases/public/submit', () =>
        HttpResponse.json({ tracking_number: 'TRK-XYZ' }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/request title/i);

    await user.type(screen.getByLabelText(/request title/i), 'T');
    await user.type(screen.getByLabelText(/detailed description/i), 'D');
    await user.type(screen.getByLabelText(/full name/i), 'N');
    await user.type(screen.getByLabelText(/email address/i), 'e@x.com');
    await user.click(screen.getByRole('button', { name: /submit request/i }));
    await screen.findByText(/request submitted successfully/i);

    await user.click(
      screen.getByRole('button', { name: /submit another request/i }),
    );
    expect(
      await screen.findByLabelText(/request title/i),
    ).toHaveValue('');
  });

  it('shows the loading state during submission', async () => {
    let resolve: () => void = () => {};
    const ready = new Promise<void>((r) => {
      resolve = r;
    });
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/cases/public/submit', async () => {
        await ready;
        return HttpResponse.json({ tracking_number: 'TRK' });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/request title/i);
    await user.type(screen.getByLabelText(/request title/i), 'T');
    await user.type(screen.getByLabelText(/detailed description/i), 'D');
    await user.type(screen.getByLabelText(/full name/i), 'N');
    await user.type(screen.getByLabelText(/email address/i), 'e@x.com');
    await user.click(screen.getByRole('button', { name: /submit request/i }));
    expect(
      screen.getByRole('button', { name: /submitting/i }),
    ).toBeDisabled();
    resolve();
    await screen.findByText(/request submitted successfully/i);
  });
});

describe('PublicRequestForm — submission errors', () => {
  it('surfaces backend detail message on failure', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post('/api/v1/cases/public/submit', () =>
        HttpResponse.json({ detail: 'Validation error' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/request title/i);
    await user.type(screen.getByLabelText(/request title/i), 'T');
    await user.type(screen.getByLabelText(/detailed description/i), 'D');
    await user.type(screen.getByLabelText(/full name/i), 'N');
    await user.type(screen.getByLabelText(/email address/i), 'e@x.com');
    await user.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() =>
      expect(screen.getByText('Validation error')).toBeInTheDocument(),
    );
  });

  it('falls back to default error message when no detail provided', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.post(
        '/api/v1/cases/public/submit',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PublicRequestForm />);
    await screen.findByLabelText(/request title/i);
    await user.type(screen.getByLabelText(/request title/i), 'T');
    await user.type(screen.getByLabelText(/detailed description/i), 'D');
    await user.type(screen.getByLabelText(/full name/i), 'N');
    await user.type(screen.getByLabelText(/email address/i), 'e@x.com');
    await user.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() =>
      expect(screen.getByText(/failed to submit request/i)).toBeInTheDocument(),
    );
  });
});
