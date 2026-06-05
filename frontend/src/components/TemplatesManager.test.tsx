import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor, within } from '../test-utils/render';
import TemplatesManager from './TemplatesManager';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const baseTemplate = {
  id: 't1',
  name: 'Acknowledgment Letter',
  description: 'Sent on intake',
  content: 'Dear {requester_name},',
  category: 'acknowledgment',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-02-01T00:00:00Z',
};

const variables = {
  variables: [
    { name: '{requester_name}', description: 'The requester name' },
    { name: '{case_number}', description: 'The case tracking number' },
  ],
};

describe('TemplatesManager — listing', () => {
  it('renders templates from the API', async () => {
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([baseTemplate])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
    );
    renderWithProviders(<TemplatesManager />);
    expect(
      await screen.findByText('Acknowledgment Letter'),
    ).toBeInTheDocument();
    expect(screen.getByText('Sent on intake')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('renders the empty state when there are no templates', async () => {
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
    );
    renderWithProviders(<TemplatesManager />);
    expect(
      await screen.findByText(/no templates found/i),
    ).toBeInTheDocument();
  });

  it('survives a failed templates fetch', async () => {
    server.use(
      http.get('/api/v1/templates/', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
    );
    renderWithProviders(<TemplatesManager />);
    expect(
      await screen.findByText(/no templates found/i),
    ).toBeInTheDocument();
  });

  it('survives a failed variables fetch', async () => {
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([baseTemplate])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<TemplatesManager />);
    expect(
      await screen.findByText('Acknowledgment Letter'),
    ).toBeInTheDocument();
  });
});

describe('TemplatesManager — create / edit / delete', () => {
  it('creates a new template', async () => {
    let postBody: any = null;
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
      http.post('/api/v1/templates/', async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<TemplatesManager />);
    await screen.findByText(/no templates found/i);
    await user.click(screen.getByRole('button', { name: /create template/i }));
    await screen.findByRole('heading', { name: /create new template/i });
    await user.type(screen.getByLabelText(/template name/i), 'New Template');
    await user.type(
      screen.getByPlaceholderText(/enter your template content/i),
      'Body text',
    );
    await user.click(
      screen.getByRole('button', { name: /^create template$/i }),
    );
    await waitFor(() => expect(postBody?.name).toBe('New Template'));
    expect(postBody.content).toBe('Body text');
  });

  it('disables the create button until name and content are filled', async () => {
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<TemplatesManager />);
    await screen.findByText(/no templates found/i);
    await user.click(screen.getByRole('button', { name: /create template/i }));
    await screen.findByRole('heading', { name: /create new template/i });
    expect(
      screen.getByRole('button', { name: /^create template$/i }),
    ).toBeDisabled();
  });

  it('edits an existing template prefilled in the dialog', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([baseTemplate])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
      http.put('/api/v1/templates/t1', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<TemplatesManager />);
    await screen.findByText('Acknowledgment Letter');
    await user.click(screen.getByTestId('EditIcon').closest('button')!);
    await screen.findByRole('heading', { name: /edit template/i });
    const nameField = screen.getByLabelText(/template name/i);
    expect(nameField).toHaveValue('Acknowledgment Letter');
    await user.clear(nameField);
    await user.type(nameField, 'Renamed Template');
    await user.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(putBody?.name).toBe('Renamed Template'));
  });

  it('deletes a template after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    let deleted = false;
    server.use(
      http.get('/api/v1/templates/', () =>
        HttpResponse.json(deleted ? [] : [baseTemplate]),
      ),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
      http.delete('/api/v1/templates/t1', () => {
        deleted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<TemplatesManager />);
    await screen.findByText('Acknowledgment Letter');
    await user.click(screen.getByTestId('DeleteIcon').closest('button')!);
    expect(
      await screen.findByText(/no templates found/i),
    ).toBeInTheDocument();
  });

  it('does not delete when confirm is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([baseTemplate])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<TemplatesManager />);
    await screen.findByText('Acknowledgment Letter');
    await user.click(screen.getByTestId('DeleteIcon').closest('button')!);
    expect(screen.getByText('Acknowledgment Letter')).toBeInTheDocument();
  });

  it('handles a save error without crashing', async () => {
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
      http.post('/api/v1/templates/', () =>
        HttpResponse.json({ detail: 'bad' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<TemplatesManager />);
    await screen.findByText(/no templates found/i);
    await user.click(screen.getByRole('button', { name: /create template/i }));
    await screen.findByRole('heading', { name: /create new template/i });
    await user.type(screen.getByLabelText(/template name/i), 'X');
    await user.type(
      screen.getByPlaceholderText(/enter your template content/i),
      'Y',
    );
    await user.click(
      screen.getByRole('button', { name: /^create template$/i }),
    );
    // dialog stays open because the save threw
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /create new template/i }),
      ).toBeInTheDocument(),
    );
  });
});

describe('TemplatesManager — variables', () => {
  it('opens the available-variables dialog and copies a variable', async () => {
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
    );
    const user = userEvent.setup();
    // userEvent.setup() installs its own navigator.clipboard stub — spy AFTER setup.
    const writeText = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockResolvedValue(undefined);
    renderWithProviders(<TemplatesManager />);
    await screen.findByText(/no templates found/i);
    await user.click(
      screen.getByRole('button', { name: /view available variables/i }),
    );
    await screen.findByRole('heading', {
      name: /available template variables/i,
    });
    expect(screen.getByText('The requester name')).toBeInTheDocument();
    await user.click(screen.getAllByTestId('ContentCopyIcon')[0]);
    expect(writeText).toHaveBeenCalledWith('{requester_name}');
  });

  it('inserts a variable chip into the template content', async () => {
    server.use(
      http.get('/api/v1/templates/', () => HttpResponse.json([])),
      http.get('/api/v1/templates/available-variables/list', () =>
        HttpResponse.json(variables),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<TemplatesManager />);
    await screen.findByText(/no templates found/i);
    await user.click(screen.getByRole('button', { name: /create template/i }));
    await screen.findByRole('heading', { name: /create new template/i });
    const contentField = screen.getByPlaceholderText(
      /enter your template content/i,
    ) as HTMLTextAreaElement;
    // click a variable chip inside the dialog
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByText('{requester_name}'));
    await waitFor(() =>
      expect(contentField.value).toContain('{requester_name}'),
    );
  });
});
