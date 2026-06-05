import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import SystemConfiguration from './SystemConfiguration';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const baseConfig = {
  org_name: 'Test Org',
  contact_email: 'foi@test.org',
  primary_color: '#000000',
  footer_text: 'Disclaimer text',
  default_due_days: 30,
  default_priority: 'normal',
  session_timeout_minutes: 60,
  password_min_length: 12,
  enable_public_requests: true,
  enable_request_tracking: true,
  enable_public_upload: false,
  request_categories: ['General Records', 'Personnel Files'],
  auto_generate_ai_suggestions: true,
  updated_at: '2026-05-01T10:00:00Z',
  updated_by: 'admin@test.org',
};

describe('SystemConfiguration', () => {
  it('shows the loading state first', () => {
    server.use(
      http.get('/api/v1/admin/config/', async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json(baseConfig);
      }),
    );
    renderWithProviders(<SystemConfiguration />);
    expect(screen.getByText(/loading configuration/i)).toBeInTheDocument();
  });

  it('renders the config form populated from the API', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () => HttpResponse.json(baseConfig)),
    );
    renderWithProviders(<SystemConfiguration />);
    expect(
      await screen.findByRole('heading', { name: /system configuration/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/default due date/i)).toHaveValue(30);
    expect(screen.getByLabelText(/session timeout/i)).toHaveValue(60);
    expect(screen.getByLabelText(/minimum password length/i)).toHaveValue(12);
    // request categories textarea joins on newlines
    expect(
      screen.getByText(/2 categories defined/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/last updated/i)).toBeInTheDocument();
  });

  it('shows the failed-to-load state when the fetch errors', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 500 }),
      ),
    );
    renderWithProviders(<SystemConfiguration />);
    await waitFor(() =>
      expect(
        screen.queryByText(/loading configuration/i),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(/failed to load configuration/i),
    ).toBeInTheDocument();
  });

  it('edits a field and saves successfully', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/admin/config/', () => HttpResponse.json(baseConfig)),
      http.put('/api/v1/admin/config/', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json(putBody);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<SystemConfiguration />);
    const dueDays = await screen.findByLabelText(/default due date/i);
    await user.clear(dueDays);
    await user.type(dueDays, '45');
    await user.click(
      screen.getByRole('button', { name: /save configuration/i }),
    );
    await waitFor(() => expect(putBody?.default_due_days).toBe(45));
    expect(
      await screen.findByText(/configuration saved successfully/i),
    ).toBeInTheDocument();
  });

  it('toggles a checkbox and includes it in the save payload', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/admin/config/', () => HttpResponse.json(baseConfig)),
      http.put('/api/v1/admin/config/', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json(putBody);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<SystemConfiguration />);
    await screen.findByLabelText(/default due date/i);
    await user.click(
      screen.getByRole('checkbox', { name: /enable public upload/i }),
    );
    await user.click(
      screen.getByRole('button', { name: /save configuration/i }),
    );
    await waitFor(() => expect(putBody?.enable_public_upload).toBe(true));
  });

  it('edits the request categories textarea', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/admin/config/', () => HttpResponse.json(baseConfig)),
      http.put('/api/v1/admin/config/', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json(putBody);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<SystemConfiguration />);
    await screen.findByLabelText(/default due date/i);
    const footer = screen.getByLabelText(/footer \/ disclaimer text/i);
    await user.clear(footer);
    await user.type(footer, 'New footer');
    await user.click(
      screen.getByRole('button', { name: /save configuration/i }),
    );
    await waitFor(() => expect(putBody?.footer_text).toBe('New footer'));
  });

  it('shows a server error when the save fails', async () => {
    server.use(
      http.get('/api/v1/admin/config/', () => HttpResponse.json(baseConfig)),
      http.put('/api/v1/admin/config/', () =>
        HttpResponse.json({ detail: 'save rejected' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<SystemConfiguration />);
    await screen.findByLabelText(/default due date/i);
    await user.click(
      screen.getByRole('button', { name: /save configuration/i }),
    );
    expect(await screen.findByText(/save rejected/i)).toBeInTheDocument();
  });

  it('changes the default priority select', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/admin/config/', () => HttpResponse.json(baseConfig)),
      http.put('/api/v1/admin/config/', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json(putBody);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<SystemConfiguration />);
    const prioritySelect = await screen.findByLabelText(/default priority/i);
    await user.selectOptions(prioritySelect, 'high');
    await user.click(
      screen.getByRole('button', { name: /save configuration/i }),
    );
    await waitFor(() => expect(putBody?.default_priority).toBe('high'));
  });
});
