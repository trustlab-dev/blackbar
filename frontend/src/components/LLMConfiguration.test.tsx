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
  model_name: 'example-model-1',
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
    expect(screen.getByText('example-model-1')).toBeInTheDocument();
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

  it('shows a failed save inside the dialog', async () => {
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
    expect(await screen.findByText('bad')).toBeInTheDocument();
    // The dialog stays open so the admin can fix the input.
    expect(screen.getByRole('heading', { name: /add llm configuration/i })).toBeInTheDocument();
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

// ---- LLM contract (backend commit 885de89) --------------------------------

function useConfigs(configs: any[]) {
  server.use(
    http.get('/api/v1/llm/configs', () => HttpResponse.json(configs)),
    http.get('/api/v1/llm/default', () =>
      HttpResponse.json({ detail: 'none' }, { status: 404 }),
    ),
  );
}

async function openEdit(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText('Prod OpenAI');
  await user.click(screen.getByTestId('EditIcon').closest('button')!);
  await screen.findByRole('heading', { name: /edit llm configuration/i });
}

describe('LLMConfiguration — api_key_set', () => {
  it('flags a config whose key must be re-entered and disables its test', async () => {
    let tested = false;
    useConfigs([{ ...baseConfig, api_key_set: false }]);
    server.use(
      http.post('/api/v1/llm/test', () => {
        tested = true;
        return HttpResponse.json({ success: true, message: 'ok' });
      }),
    );
    renderWithProviders(<LLMConfiguration />);
    expect(await screen.findByText(/API key must be re-entered/i)).toBeInTheDocument();
    const testButton = screen.getByTestId('PlayArrowIcon').closest('button')!;
    expect(testButton).toBeDisabled();
    expect(tested).toBe(false);
  });

  it('requires a key before saving an enabled config without one', async () => {
    let putBody: any = null;
    useConfigs([{ ...baseConfig, api_key_set: false }]);
    server.use(
      http.put('/api/v1/llm/configs/cfg1', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ ...baseConfig, api_key_set: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await openEdit(user);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getAllByText(/API key must be re-entered/i).length).toBeGreaterThan(0);
    await user.click(within(dialog).getByRole('button', { name: /^save$/i }));
    expect(await within(dialog).findByText(/Enter the API key/i)).toBeInTheDocument();
    expect(putBody).toBeNull();

    await user.type(within(dialog).getByLabelText(/api key/i), 'sk-new');
    await user.click(within(dialog).getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(putBody?.api_key).toBe('sk-new'));
  });
});

describe('LLMConfiguration — endpoint/provider change clears the key', () => {
  it('warns before saving and requires a new key while enabled', async () => {
    let putBody: any = null;
    useConfigs([{ ...baseConfig, api_key_set: true }]);
    server.use(
      http.put('/api/v1/llm/configs/cfg1', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json(baseConfig);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await openEdit(user);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).queryByText(/clears the stored API key/i)).toBeNull();

    const endpoint = within(dialog).getByLabelText(/api endpoint/i);
    await user.clear(endpoint);
    await user.type(endpoint, 'https://api.example.com/v1/chat/completions');
    expect(within(dialog).getByText(/clears the stored API key/i)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: /^save$/i }));
    expect(await within(dialog).findByText(/Enter the API key/i)).toBeInTheDocument();
    expect(putBody).toBeNull();

    await user.type(within(dialog).getByLabelText(/api key/i), 'sk-new');
    expect(within(dialog).queryByText(/clears the stored API key/i)).toBeNull();
    await user.click(within(dialog).getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(putBody?.api_key).toBe('sk-new'));
    expect(putBody.api_endpoint).toBe('https://api.example.com/v1/chat/completions');
  });

  it('warns when the provider changes without a new key', async () => {
    useConfigs([{ ...baseConfig, api_key_set: true }]);
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await openEdit(user);
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getAllByRole('combobox')[0]);
    await user.click(await screen.findByRole('option', { name: 'Anthropic' }));
    expect(within(dialog).getByText(/clears the stored API key/i)).toBeInTheDocument();
  });
});

describe('LLMConfiguration — masked headers', () => {
  it('shows header names only and never sends the masked value back as a change', async () => {
    let putBody: any = null;
    useConfigs([
      { ...baseConfig, api_key_set: true, headers: { 'X-Org-Id': '********' } },
    ]);
    server.use(
      http.put('/api/v1/llm/configs/cfg1', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json(baseConfig);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await openEdit(user);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/X-Org-Id/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/\*{8}/)).toBeNull();
    const nameField = within(dialog).getByLabelText(/^name/i);
    await user.clear(nameField);
    await user.type(nameField, 'Renamed');
    await user.click(within(dialog).getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(putBody?.name).toBe('Renamed'));
    expect(putBody).not.toHaveProperty('headers');
    expect(JSON.stringify(putBody)).not.toContain('********');
  });
});

describe('LLMConfiguration — backend errors', () => {
  it('shows the 422 unsafe-endpoint message from the backend', async () => {
    useConfigs([]);
    server.use(
      http.post('/api/v1/llm/configs', () =>
        HttpResponse.json(
          {
            error: {
              code: 'HTTP_422',
              message: 'LLM endpoint must use https (http is only allowed for localhost).',
            },
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText(/no llm configurations yet/i);
    await user.click(screen.getByRole('button', { name: /add llm/i }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText(/^name/i), 'X');
    await user.type(within(dialog).getByLabelText(/api endpoint/i), 'http://10.0.0.5/v1');
    await user.type(within(dialog).getByLabelText(/api key/i), 'k');
    await user.type(within(dialog).getByLabelText(/model name/i), 'm');
    await user.click(within(dialog).getByRole('button', { name: /^save$/i }));
    expect(
      await within(dialog).findByText(/must use https \(http is only allowed for localhost\)/),
    ).toBeInTheDocument();
  });

  it('shows the 503 encryption-key message from the backend', async () => {
    useConfigs([]);
    server.use(
      http.post('/api/v1/llm/configs', () =>
        HttpResponse.json(
          {
            error: {
              code: 'HTTP_503',
              message:
                'LLM API keys cannot be stored: LLM_API_KEY_ENCRYPTION_KEY is missing or invalid.',
            },
          },
          { status: 503 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText(/no llm configurations yet/i);
    await user.click(screen.getByRole('button', { name: /add llm/i }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText(/^name/i), 'X');
    await user.type(within(dialog).getByLabelText(/api key/i), 'k');
    await user.click(within(dialog).getByRole('button', { name: /^save$/i }));
    expect(
      await within(dialog).findByText(/LLM_API_KEY_ENCRYPTION_KEY is missing or invalid/),
    ).toBeInTheDocument();
  });

  it('shows error_code and reference from a failed connection test', async () => {
    useConfigs([{ ...baseConfig, api_key_set: true }]);
    server.use(
      http.post('/api/v1/llm/test', () =>
        HttpResponse.json({
          success: false,
          message: 'Connection failed (0.8s): The AI provider rejected the API key.',
          error_code: 'provider_auth_failed',
          reference: 'ref-abc123',
          response: null,
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByTestId('PlayArrowIcon').closest('button')!);
    expect(await screen.findByText(/rejected the API key/)).toBeInTheDocument();
    expect(screen.getByText(/Error code: provider_auth_failed/)).toBeInTheDocument();
    expect(screen.getByText(/Reference: ref-abc123/)).toBeInTheDocument();
  });

  it('shows "try again in N seconds" when the test is rate limited', async () => {
    let calls = 0;
    useConfigs([{ ...baseConfig, api_key_set: true }]);
    server.use(
      http.post('/api/v1/llm/test', () => {
        calls += 1;
        return HttpResponse.json(
          { error: 'Rate limit exceeded: 10 per 1 minute' },
          { status: 429, headers: { 'Retry-After': '12' } },
        );
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText('Prod OpenAI');
    await user.click(screen.getByTestId('PlayArrowIcon').closest('button')!);
    expect(await screen.findByText(/Try again in 12 seconds/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(calls).toBe(1);
  });
});

describe('LLMConfiguration — model hints', () => {
  it('suggests current Anthropic model IDs and no retired ones', async () => {
    useConfigs([]);
    const user = userEvent.setup();
    renderWithProviders(<LLMConfiguration />);
    await screen.findByText(/no llm configurations yet/i);
    await user.click(screen.getByRole('button', { name: /add llm/i }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByText(/claude-3/)).toBeNull();
    expect(within(dialog).getByText(/provider's documentation/i)).toBeInTheDocument();
    await user.click(within(dialog).getAllByRole('combobox')[0]);
    await user.click(await screen.findByRole('option', { name: 'Anthropic' }));
    const hint = within(dialog).getByText(/claude-sonnet-5/);
    expect(hint).toHaveTextContent('claude-opus-5-5');
    expect(hint).toHaveTextContent('claude-fable-5-1');
    expect(hint).toHaveTextContent('claude-haiku-4-5-20251001');
    expect(within(dialog).queryByText(/claude-3/)).toBeNull();
  });
});
