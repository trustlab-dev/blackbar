import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor, within } from '../test-utils/render';
import LLMConfiguration from './LLMConfiguration';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const baseConfig = {
  id: 'cfg1',
  name: 'Prod OpenAI',
  enabled: true,
  api_endpoint: 'https://api.openai.com/v1/chat/completions',
  model_name: 'gpt-4-turbo',
  request_format: 'openai',
  default_settings: { temperature: 0.7, max_tokens: 4000, top_p: 1.0 },
  notes: 'Primary',
  created_at: '2026-01-01T00:00:00Z',
};

describe('LLMConfiguration — listing', () => {
  it('shows the spinner, then the empty state', async () => {
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
    );
    renderWithProviders(<LLMConfiguration />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(
      await screen.findByText(/no llm configurations yet/i),
    ).toBeInTheDocument();
  });

  it('renders configs in a table with the default-LLM alert', async () => {
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([baseConfig])),
      http.get('/api/v1/llm/default', () => HttpResponse.json(baseConfig)),
    );
    renderWithProviders(<LLMConfiguration />);
    expect(await screen.findByText('Prod OpenAI')).toBeInTheDocument();
    expect(screen.getByText('gpt-4-turbo')).toBeInTheDocument();
    expect(screen.getByText('Enabled')).toBeInTheDocument();
    // Default alert + Default chip both present
    expect(screen.getByText(/Default:/)).toBeInTheDocument();
    expect(screen.getAllByText('Default').length).toBeGreaterThan(0);
  });

  it('keeps rendering when the configs fetch fails', async () => {
    server.use(
      http.get('/api/v1/llm/configs', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
    );
    renderWithProviders(<LLMConfiguration />);
    expect(
      await screen.findByText(/no llm configurations yet/i),
    ).toBeInTheDocument();
  });
});

describe('LLMConfiguration — add / edit', () => {
  it('opens the add dialog and creates a config', async () => {
    let postBody: any = null;
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.post('/api/v1/llm/configs', async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText(/no llm configurations yet/i);
    await user.click(screen.getByRole('button', { name: /add llm/i }));
    await screen.findByRole('heading', { name: /add llm configuration/i });
    await user.type(screen.getByLabelText(/^name/i), 'New Config');
    await user.type(
      screen.getByLabelText(/api endpoint/i),
      'https://api.test/v1',
    );
    await user.type(screen.getByLabelText(/api key/i), 'sk-secret');
    await user.type(screen.getByLabelText(/model name/i), 'test-model');
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(postBody?.name).toBe('New Config'));
    expect(postBody.api_key).toBe('sk-secret');
  });

  it('opens the edit dialog prefilled and PUTs the update', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([baseConfig])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.put('/api/v1/llm/configs/cfg1', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByTestId('EditIcon').closest('button')!);
    await screen.findByRole('heading', { name: /edit llm configuration/i });
    const nameField = screen.getByLabelText(/^name/i);
    expect(nameField).toHaveValue('Prod OpenAI');
    await user.clear(nameField);
    await user.type(nameField, 'Renamed');
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(putBody?.name).toBe('Renamed'));
    // api_key omitted when blank on edit
    expect(putBody.api_key).toBeUndefined();
  });

  it('alerts on a failed save', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.post('/api/v1/llm/configs', () =>
        HttpResponse.json({ detail: 'bad' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText(/no llm configurations yet/i);
    await user.click(screen.getByRole('button', { name: /add llm/i }));
    await screen.findByRole('heading', { name: /add llm configuration/i });
    await user.type(screen.getByLabelText(/^name/i), 'X');
    await user.type(screen.getByLabelText(/api key/i), 'k');
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() =>
      expect(alertSpy).toHaveBeenCalledWith('Failed to save configuration'),
    );
  });

  it('cancels the dialog', async () => {
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText(/no llm configurations yet/i);
    await user.click(screen.getByRole('button', { name: /add llm/i }));
    await screen.findByRole('heading', { name: /add llm configuration/i });
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: /add llm configuration/i }),
      ).not.toBeInTheDocument(),
    );
  });
});

describe('LLMConfiguration — delete / default / test', () => {
  it('deletes a config after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    let deleted = false;
    server.use(
      http.get('/api/v1/llm/configs', () =>
        HttpResponse.json(deleted ? [] : [baseConfig]),
      ),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.delete('/api/v1/llm/configs/cfg1', () => {
        deleted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByTestId('DeleteIcon').closest('button')!);
    expect(
      await screen.findByText(/no llm configurations yet/i),
    ).toBeInTheDocument();
  });

  it('does not delete when the confirm is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([baseConfig])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByTestId('DeleteIcon').closest('button')!);
    expect(screen.getByText('Prod OpenAI')).toBeInTheDocument();
  });

  it('alerts when delete fails', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([baseConfig])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.delete('/api/v1/llm/configs/cfg1', () =>
        HttpResponse.json({ detail: 'in use' }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByTestId('DeleteIcon').closest('button')!);
    await waitFor(() => expect(alertSpy).toHaveBeenCalledWith('in use'));
  });

  it('sets a config as default', async () => {
    let isDefault = false;
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([baseConfig])),
      http.get('/api/v1/llm/default', () =>
        isDefault
          ? HttpResponse.json(baseConfig)
          : HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.put('/api/v1/llm/default/cfg1', () => {
        isDefault = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByRole('button', { name: /set default/i }));
    expect(await screen.findByText(/Default:/)).toBeInTheDocument();
  });

  it('alerts when set-default fails', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([baseConfig])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.put('/api/v1/llm/default/cfg1', () => HttpResponse.error()),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByRole('button', { name: /set default/i }));
    await waitFor(() =>
      expect(alertSpy).toHaveBeenCalledWith('Failed to set default LLM'),
    );
  });

  it('runs a connection test and shows the success result', async () => {
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([baseConfig])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.post('/api/v1/llm/test', () =>
        HttpResponse.json({
          success: true,
          message: 'Connected',
          response: 'pong',
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByTestId('PlayArrowIcon').closest('button')!);
    expect(await screen.findByText(/LLM Response: "pong"/)).toBeInTheDocument();
  });

  it('shows a failed test result and lets it be dismissed', async () => {
    server.use(
      http.get('/api/v1/llm/configs', () => HttpResponse.json([baseConfig])),
      http.get('/api/v1/llm/default', () =>
        HttpResponse.json({ detail: 'none' }, { status: 404 }),
      ),
      http.post('/api/v1/llm/test', () =>
        HttpResponse.json({ detail: 'auth failed' }, { status: 401 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByTestId('PlayArrowIcon').closest('button')!);
    const alert = await screen.findByText('auth failed');
    expect(alert).toBeInTheDocument();
    // dismiss the result alert
    const closeBtn = within(alert.closest('.MuiAlert-root')!).getByRole(
      'button',
    );
    await user.click(closeBtn);
    await waitFor(() =>
      expect(screen.queryByText('auth failed')).not.toBeInTheDocument(),
    );
  });
});
