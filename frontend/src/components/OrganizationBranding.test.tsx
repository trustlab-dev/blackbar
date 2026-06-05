import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import OrganizationBranding from './OrganizationBranding';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('OrganizationBranding — initial load', () => {
  it('shows the loading spinner before the fetch resolves', async () => {
    server.use(
      http.get('/api/v1/admin/config/', async () => {
        await new Promise(() => {}); // never resolve
        return HttpResponse.json({});
      }),
    );
    const { container } = renderWithProviders(<OrganizationBranding />);
    expect(container.querySelector('[role="progressbar"]')).toBeInTheDocument();
  });

  it('renders the form populated with fetched config values', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () =>
        HttpResponse.json({
          org_name: 'Acme FOI',
          primary_color: '#abcdef',
        }),
      ),
    );
    renderWithProviders(<OrganizationBranding />);
    await waitFor(() =>
      expect(screen.getByLabelText(/organization name/i)).toHaveValue('Acme FOI'),
    );
    // Both the <input type="color"> and the small TextField mirror the hex value.
    expect(screen.getAllByDisplayValue('#abcdef').length).toBeGreaterThanOrEqual(2);
  });

  it('falls back to defaults when the API returns empty payload', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () => HttpResponse.json({})),
    );
    renderWithProviders(<OrganizationBranding />);
    await waitFor(() =>
      expect(screen.getByLabelText(/organization name/i)).toHaveValue(''),
    );
    expect(screen.getAllByDisplayValue('#0366d6').length).toBeGreaterThanOrEqual(2);
  });

  it('shows an error alert when the fetch fails', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () => new HttpResponse(null, { status: 500 })),
    );
    renderWithProviders(<OrganizationBranding />);
    await waitFor(() =>
      expect(screen.getByText(/failed to load configuration/i)).toBeInTheDocument(),
    );
  });
});

describe('OrganizationBranding — save', () => {
  it('saves successfully and shows the success alert', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () =>
        HttpResponse.json({ org_name: 'Acme', primary_color: '#111111' }),
      ),
      http.put('/api/v1/admin/config/', () => HttpResponse.json({ ok: true })),
    );
    const user = userEvent.setup();
    renderWithProviders(<OrganizationBranding />);

    await waitFor(() =>
      expect(screen.getByLabelText(/organization name/i)).toHaveValue('Acme'),
    );

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/branding updated successfully/i),
      ).toBeInTheDocument(),
    );
  });

  it('shows backend error.detail when save fails', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () =>
        HttpResponse.json({ org_name: 'Acme', primary_color: '#111111' }),
      ),
      http.put('/api/v1/admin/config/', () =>
        HttpResponse.json({ detail: 'Permission denied' }, { status: 403 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<OrganizationBranding />);

    await waitFor(() =>
      expect(screen.getByLabelText(/organization name/i)).toHaveValue('Acme'),
    );
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() =>
      expect(screen.getByText(/permission denied/i)).toBeInTheDocument(),
    );
  });

  it('shows the default error message when no detail is provided', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () =>
        HttpResponse.json({ org_name: 'Acme', primary_color: '#111111' }),
      ),
      http.put('/api/v1/admin/config/', () => new HttpResponse(null, { status: 500 })),
    );
    const user = userEvent.setup();
    renderWithProviders(<OrganizationBranding />);

    await waitFor(() =>
      expect(screen.getByLabelText(/organization name/i)).toHaveValue('Acme'),
    );
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() =>
      expect(screen.getByText(/failed to save branding/i)).toBeInTheDocument(),
    );
  });
});

describe('OrganizationBranding — form interactions', () => {
  it('updates org_name and primary_color via inputs', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () =>
        HttpResponse.json({ org_name: 'Old', primary_color: '#000000' }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<OrganizationBranding />);

    const nameInput = await screen.findByLabelText(/organization name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'New Org');
    expect(nameInput).toHaveValue('New Org');

    // The hex shows up in both <input type="color"> and the TextField; pick the
    // visible text-typing target by role+display value.
    const hexInputs = screen.getAllByDisplayValue('#000000');
    const hexTextField = hexInputs.find(
      (el) => (el as HTMLInputElement).type === 'text',
    ) as HTMLInputElement;
    await user.clear(hexTextField);
    await user.type(hexTextField, '#ff00ff');
    expect(hexTextField).toHaveValue('#ff00ff');
  });

  it('dismisses the error alert via its close button', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () => new HttpResponse(null, { status: 500 })),
    );
    const user = userEvent.setup();
    renderWithProviders(<OrganizationBranding />);

    await waitFor(() =>
      expect(screen.getByText(/failed to load configuration/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: /close/i }));
    expect(
      screen.queryByText(/failed to load configuration/i),
    ).not.toBeInTheDocument();
  });
});
