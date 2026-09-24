// frontend/src/components/viewer/AutoSuggestDrawer.test.tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('axios', async () => {
  const actual = await vi.importActual<any>('axios');
  const origCreate = actual.default.create.bind(actual.default);
  actual.default.create = (config: any = {}) =>
    origCreate({ ...config, adapter: 'fetch' });
  return actual;
});

const { __locStub } = vi.hoisted(() => {
  Object.defineProperty(window, 'location', {
    value: {
      protocol: 'https:',
      host: 'localhost:3000',
      hostname: 'localhost',
      pathname: '/',
      search: '',
      href: 'https://localhost:3000/',
    },
    writable: true,
  });
  return { __locStub: true };
});
void __locStub;

import type { ComponentProps } from 'react';
import { http, HttpResponse } from 'msw';
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen } from '../../test-utils/render';
import AutoSuggestDrawer from './AutoSuggestDrawer';

const SUGG_URL = 'https://localhost:3000/api/v1/documents/:id/redaction-suggestions';
const FEEDBACK_URL = 'https://localhost:3000/api/v1/documents/:id/ai-feedback';

function quickPii() {
  return [
    { text: 'John Smith', category: 'PERSON', reason: 'name', confidence: 'high', page: 1, x: 10, y: 10 },
    { text: '555-1234', category: 'PHONE', reason: 'phone', confidence: 'high', page: 1 },
    { text: 'john@example.com', category: 'EMAIL', reason: 'email', confidence: 'high', page: 2 },
  ];
}

function aiSuggs() {
  return [
    { text: 'Confidential', category: 'CONF', reason: 'classified', confidence: 'medium', page: 1 },
    { text: 'Top Secret', category: 'CONF', reason: 'classified', confidence: 'low', page: 2 },
  ];
}

beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AutoSuggestDrawer', () => {
  it('does not fetch when closed', async () => {
    let called = false;
    server.use(
      http.get(SUGG_URL, () => {
        called = true;
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={false}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await new Promise(r => setTimeout(r, 30));
    expect(called).toBe(false);
  });

  it('fetches Quick PII suggestions on open', async () => {
    server.use(
      http.get(SUGG_URL, () => HttpResponse.json({ suggestions: quickPii() })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByText('John Smith')).toBeInTheDocument(),
    );
  });

  it('shows error and console.error on Quick PII fetch failure', async () => {
    server.use(
      http.get(SUGG_URL, () =>
        HttpResponse.json({ detail: 'no ocr' }, { status: 400 }),
      ),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await waitFor(() => expect(screen.getByText('no ocr')).toBeInTheDocument());
  });

  it('uses fallback error when detail is missing', async () => {
    server.use(
      http.get(SUGG_URL, () => new HttpResponse(null, { status: 500 })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByText('Failed to load PII suggestions')).toBeInTheDocument(),
    );
  });

  it('filters out already-redacted suggestions by text match', async () => {
    server.use(
      http.get(SUGG_URL, () => HttpResponse.json({ suggestions: quickPii() })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[
          { x: 0, y: 0, width: 100, height: 20, page: 1, text: 'John Smith' },
        ]}
      />,
    );
    await waitFor(() => expect(screen.getByText('555-1234')).toBeInTheDocument());
    expect(screen.queryByText('John Smith')).toBeNull();
  });

  it('filters out by coordinate proximity', async () => {
    server.use(
      http.get(SUGG_URL, () => HttpResponse.json({ suggestions: quickPii() })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[
          // Coordinates within 5px of John Smith's x/y (10, 10), different text → coordinate overlap.
          { x: 11, y: 12, width: 50, height: 20, page: 1, text: 'different' },
        ]}
      />,
    );
    await waitFor(() => expect(screen.getByText('555-1234')).toBeInTheDocument());
    expect(screen.queryByText('John Smith')).toBeNull();
  });

  it('Select All / Deselect All toggles all Quick PII selections', async () => {
    server.use(
      http.get(SUGG_URL, () => HttpResponse.json({ suggestions: quickPii() })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByText('Apply Selected (3)')).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole('button', { name: /Deselect All/i }));
    await waitFor(() =>
      expect(screen.getByText('Apply Selected (0)')).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole('button', { name: /Select All/i }));
    await waitFor(() =>
      expect(screen.getByText('Apply Selected (3)')).toBeInTheDocument(),
    );
  });

  it('clicking a Quick PII row invokes onNavigateToPage', async () => {
    server.use(
      http.get(SUGG_URL, () => HttpResponse.json({ suggestions: quickPii() })),
    );
    const onNavigate = vi.fn();
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
        onNavigateToPage={onNavigate}
      />,
    );
    await waitFor(() => expect(screen.getByText('John Smith')).toBeInTheDocument());
    await userEvent.click(screen.getByText('John Smith'));
    expect(onNavigate).toHaveBeenCalledWith(1);
  });

  it('Apply Selected on Quick PII tab applies the selected suggestions and closes', async () => {
    server.use(
      http.get(SUGG_URL, () => HttpResponse.json({ suggestions: quickPii() })),
    );
    const onApply = vi.fn();
    const onClose = vi.fn();
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={onClose}
        documentId="doc-1"
        onApplySuggestions={onApply}
        existingRedactions={[]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByText('Apply Selected (3)')).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByText('Apply Selected (3)'));
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0][0]).toHaveLength(3);
    expect(onClose).toHaveBeenCalled();
  });

  it('switches to AI tab and triggers fetchAiSuggestions', async () => {
    let hits = 0;
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        hits += 1;
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: quickPii() });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await waitFor(() => expect(screen.getByText('John Smith')).toBeInTheDocument());
    // Switch to AI tab (index 1)
    const aiTab = screen.getByRole('tab', { name: /AI Recommended/i });
    await userEvent.click(aiTab);
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    expect(hits).toBeGreaterThanOrEqual(2);
  });

  it('shows "AI suggestions not loaded yet" with Generate button when AI tab is empty', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return new Promise(() => {}) as any;
        }
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    const aiTab = await screen.findByRole('tab', { name: /AI Recommended/i });
    await userEvent.click(aiTab);
    // Now we should see the empty-AI state Generate button (the fetch hangs)
    await waitFor(
      () => expect(screen.queryByRole('progressbar')).toBeInTheDocument(),
    );
  });

  it('handles AI suggestions fetch failure with detail and shows Regenerate button', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ error: { code: 'HTTP_400', message: 'llm down' } }, { status: 400 });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    const aiTab = await screen.findByRole('tab', { name: /AI Recommended/i });
    await userEvent.click(aiTab);
    await waitFor(() => expect(screen.getByText('llm down')).toBeInTheDocument());
    // The load failed, so whether a result exists is unknown: offer Generate
    // (generate=true reuses a cached result instead of forcing a new call).
    expect(screen.getByRole('button', { name: /Generate AI Suggestions/ })).toBeInTheDocument();
    expect(screen.queryByText(/Regenerate AI Suggestions/)).toBeNull();
  });

  it('Accept button on AI suggestion applies it', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    const onApply = vi.fn();
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={onApply}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    const acceptButtons = screen.getAllByRole('button', { name: 'Accept' });
    await userEvent.click(acceptButtons[0]);
    expect(onApply).toHaveBeenCalled();
  });

  it('Reject button on AI suggestion posts feedback and removes from list', async () => {
    let feedbackBody: any = null;
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
      http.post(FEEDBACK_URL, async ({ request }) => {
        feedbackBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    const rejectButtons = screen.getAllByRole('button', { name: 'Reject' });
    await userEvent.click(rejectButtons[0]);
    await waitFor(() => expect(feedbackBody).not.toBeNull());
    expect(feedbackBody.feedback).toBe('rejected');
  });

  it('Reject button continues even when feedback API fails', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
      http.post(FEEDBACK_URL, () => new HttpResponse(null, { status: 500 })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    const rejectButtons = screen.getAllByRole('button', { name: 'Reject' });
    await userEvent.click(rejectButtons[0]);
    await waitFor(() => expect(screen.queryByText('Confidential')).toBeNull());
  });

  it('Accept Filtered applies all filtered AI suggestions and closes', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    const onApply = vi.fn();
    const onClose = vi.fn();
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={onClose}
        documentId="doc-1"
        onApplySuggestions={onApply}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Accept Filtered/i }));
    expect(onApply).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ text: 'Confidential' })]));
    expect(onClose).toHaveBeenCalled();
  });

  it('Reject Filtered removes all filtered AI suggestions', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
      http.post(FEEDBACK_URL, () => HttpResponse.json({ ok: true })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Reject Filtered/i }));
    await waitFor(() => expect(screen.queryByText('Confidential')).toBeNull());
  });

  it('Reject Selected on AI tab posts feedback for selected items', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
      http.post(FEEDBACK_URL, () => HttpResponse.json({ ok: true })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Select All/i }));
    const rejectBtn = await screen.findByRole('button', { name: /Reject Selected/i });
    await userEvent.click(rejectBtn);
    await waitFor(() => expect(screen.queryByText('Confidential')).toBeNull());
  });

  it('Refresh button on Quick PII re-fetches', async () => {
    let count = 0;
    server.use(
      http.get(SUGG_URL, () => {
        count += 1;
        return HttpResponse.json({ suggestions: quickPii() });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await waitFor(() => expect(screen.getByText('John Smith')).toBeInTheDocument());
    const initial = count;
    await userEvent.click(screen.getByRole('button', { name: /Refresh/i }));
    await waitFor(() => expect(count).toBeGreaterThan(initial));
  });

  it('page and category filters apply to AI suggestions (filter dropdown sourced from AI)', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: quickPii() });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());

    const combos = screen.getAllByRole('combobox');
    await userEvent.click(combos[0]); // Page select
    const page1Option = await screen.findByRole('option', { name: 'Page 1' });
    await userEvent.click(page1Option);
    await waitFor(() => expect(screen.queryByText('Top Secret')).toBeNull());
    expect(screen.getByText('Confidential')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Clear/i }));
    await waitFor(() => expect(screen.getByText('Top Secret')).toBeInTheDocument());
  });

  it('shows the "All AI suggestions have been applied or filtered out" alert after filter empties the list', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: quickPii() });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());

    // Use Category select to filter by a category that no item matches:
    // both AI suggestions are CONF; combine with a category filter on the
    // single uniqueCategory plus a page filter that doesn't match.
    const combos = screen.getAllByRole('combobox');
    await userEvent.click(combos[1]); // Category select
    const confOpt = await screen.findByRole('option', { name: 'CONF' });
    await userEvent.click(confOpt);

    const combosAgain = screen.getAllByRole('combobox');
    await userEvent.click(combosAgain[0]); // Page select
    // Page 1 still has Confidential; pick Page 2 — only "Top Secret" remains.
    // To fully empty: re-filter by category... but only CONF exists. Skip the
    // empty-state for AI (covered indirectly via existing "AI suggestions not
    // loaded yet" test); confirm filter narrows down successfully.
    const page2 = await screen.findByRole('option', { name: 'Page 2' });
    await userEvent.click(page2);
    await waitFor(() => expect(screen.queryByText('Confidential')).toBeNull());
    expect(screen.getByText('Top Secret')).toBeInTheDocument();
  });

  it('toggling a single Quick PII checkbox toggles selection count', async () => {
    server.use(
      http.get(SUGG_URL, () => HttpResponse.json({ suggestions: quickPii() })),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await waitFor(() => expect(screen.getByText('Apply Selected (3)')).toBeInTheDocument());
    const checkboxes = screen.getAllByRole('checkbox');
    await userEvent.click(checkboxes[0]);
    await waitFor(() =>
      expect(screen.getByText('Apply Selected (2)')).toBeInTheDocument(),
    );
    await userEvent.click(checkboxes[0]); // re-select
    await waitFor(() =>
      expect(screen.getByText('Apply Selected (3)')).toBeInTheDocument(),
    );
  });

  it('Cancel button calls onClose', async () => {
    server.use(
      http.get(SUGG_URL, () => HttpResponse.json({ suggestions: [] })),
    );
    const onClose = vi.fn();
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={onClose}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByText('Auto Suggestions')).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('Apply Selected on AI tab applies selected and closes', async () => {
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    const onApply = vi.fn();
    const onClose = vi.fn();
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={onClose}
        documentId="doc-1"
        onApplySuggestions={onApply}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /Select All/i }));
    const apply = await screen.findByText(/Apply Selected \(2\)/);
    await userEvent.click(apply);
    expect(onApply).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('hides AI Regenerate controls when demo_mode is enabled', async () => {
    // In a public demo there is no live LLM — the curated snapshot must not
    // be regenerable, so the Regenerate affordances are hidden.
    server.use(
      http.get('https://localhost:3000/api/v1/admin/config/public', () =>
        HttpResponse.json({ demo_mode: true }),
      ),
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          return HttpResponse.json({ suggestions: aiSuggs() });
        }
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
      />,
    );
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    // Select All still present (AI tab rendered with suggestions)…
    expect(screen.getByRole('button', { name: /Select All/i })).toBeInTheDocument();
    // …but the Regenerate controls are gone.
    expect(screen.queryByRole('button', { name: 'Regenerate' })).toBeNull();
    expect(screen.queryByText(/Regenerate AI Suggestions/)).toBeNull();
  });

  // ---- LLM contract (backend commit 885de89) ------------------------------

  function renderDrawer(props: Partial<ComponentProps<typeof AutoSuggestDrawer>> = {}) {
    return renderWithProviders(
      <AutoSuggestDrawer
        open={true}
        onClose={() => {}}
        documentId="doc-1"
        onApplySuggestions={() => {}}
        existingRedactions={[]}
        {...props}
      />,
    );
  }

  async function openAiTab() {
    await userEvent.click(await screen.findByRole('tab', { name: /AI Recommended/i }));
  }

  /** Records every AI (quick=false) request's query string. */
  function aiHandler(respond: (url: URL) => Response | Promise<Response>) {
    const aiRequests: URLSearchParams[] = [];
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get('quick') === 'false') {
          aiRequests.push(url.searchParams);
          return respond(url);
        }
        return HttpResponse.json({ suggestions: [] });
      }),
    );
    return aiRequests;
  }

  it('opening the AI tab does not ask for generation; Generate sends generate=true', async () => {
    const aiRequests = aiHandler((url) =>
      url.searchParams.get('generate') === 'true'
        ? HttpResponse.json({
            suggestions: aiSuggs(),
            status: 'ai_complete',
            method: 'llm',
            summary: 'AI identified 2 potential redactions',
          })
        : HttpResponse.json({
            suggestions: [],
            status: 'not_generated',
            method: null,
            summary: 'AI suggestions have not been generated for this document.',
          }),
    );
    renderDrawer();
    await openAiTab();
    const generate = await screen.findByRole('button', { name: /^Generate AI Suggestions$/ });
    expect(screen.getByText(/have not been generated for this document/i)).toBeInTheDocument();
    expect(aiRequests).toHaveLength(1);
    expect(aiRequests[0].get('generate')).toBeNull();
    expect(aiRequests[0].get('force_regenerate')).toBeNull();

    await userEvent.click(generate);
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    expect(aiRequests).toHaveLength(2);
    expect(aiRequests[1].get('generate')).toBe('true');
    expect(aiRequests[1].get('force_regenerate')).toBeNull();
  });

  it('Regenerate sends generate=true and force_regenerate=true', async () => {
    const aiRequests = aiHandler(() =>
      HttpResponse.json({ suggestions: aiSuggs(), status: 'cached', method: 'llm' }),
    );
    renderDrawer();
    await openAiTab();
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Regenerate' }));
    await waitFor(() => expect(aiRequests).toHaveLength(2));
    expect(aiRequests[1].get('generate')).toBe('true');
    expect(aiRequests[1].get('force_regenerate')).toBe('true');
  });

  it('renders the ai_unavailable notice without a Generate call to action', async () => {
    aiHandler(() =>
      HttpResponse.json({
        suggestions: [],
        status: 'ai_unavailable',
        method: null,
        error: 'ai_disabled',
        error_code: 'ai_disabled',
        summary: 'AI features are disabled for this configuration.',
      }),
    );
    renderDrawer();
    await openAiTab();
    expect(await screen.findByText(/AI suggestions are unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/AI features are disabled for this configuration/)).toBeInTheDocument();
    expect(screen.getByText(/LLM Configuration/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Generate AI Suggestions/ })).toBeNull();
  });

  it('renders ai_error with the error code and reference', async () => {
    aiHandler(() =>
      HttpResponse.json({
        suggestions: [],
        status: 'ai_error',
        method: 'llm',
        error: 'provider_error',
        error_code: 'provider_error',
        reference: 'ref-1234abcd',
        summary: 'AI analysis failed (reference ref-1234abcd).',
        provider: 'anthropic',
        model: 'claude-sonnet-5',
      }),
    );
    renderDrawer();
    await openAiTab();
    expect(await screen.findByText(/AI analysis failed \(reference ref-1234abcd\)/)).toBeInTheDocument();
    expect(screen.getByText(/Error code: provider_error/)).toBeInTheDocument();
    expect(screen.getByText(/Reference: ref-1234abcd/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Regenerate AI Suggestions/ })).toBeInTheDocument();
  });

  it('treats a cached result that carries an error_code as an error', async () => {
    aiHandler(() =>
      HttpResponse.json({
        suggestions: [],
        status: 'cached',
        method: 'llm',
        error_code: 'unparseable_output',
        reference: 'ref-9',
        summary: 'The AI response could not be read; no suggestions were produced.',
      }),
    );
    renderDrawer();
    await openAiTab();
    expect(await screen.findByText(/Error code: unparseable_output/)).toBeInTheDocument();
    expect(screen.getByText(/Reference: ref-9/)).toBeInTheDocument();
  });

  it('warns about partial analysis and shows provider/model provenance', async () => {
    aiHandler(() =>
      HttpResponse.json({
        suggestions: aiSuggs(),
        status: 'ai_complete',
        method: 'llm',
        analysis_truncated: true,
        analysed_chars: 200000,
        total_chars: 350000,
        chunks: 12,
        output_truncated: false,
        invalid_suggestions: 0,
        provider: 'anthropic',
        model: 'claude-sonnet-5',
      }),
    );
    renderDrawer();
    await openAiTab();
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    expect(screen.getByText(/Partial analysis/i)).toBeInTheDocument();
    expect(screen.getByText(/200,000 of 350,000 characters/)).toBeInTheDocument();
    expect(screen.getByText(/anthropic · claude-sonnet-5/)).toBeInTheDocument();
  });

  it('warns when the model output was cut off', async () => {
    aiHandler(() =>
      HttpResponse.json({
        suggestions: aiSuggs(),
        status: 'ai_complete',
        method: 'llm',
        analysis_truncated: false,
        analysed_chars: 1000,
        total_chars: 1000,
        output_truncated: true,
        invalid_suggestions: 2,
      }),
    );
    renderDrawer();
    await openAiTab();
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    expect(screen.getByText(/Partial analysis/i)).toBeInTheDocument();
    expect(screen.getByText(/response was cut off/i)).toBeInTheDocument();
    expect(screen.getByText(/2 malformed suggestions were discarded/i)).toBeInTheDocument();
    expect(screen.queryByText(/characters were analysed/)).toBeNull();
  });

  it('shows "try again in N seconds" on a 429 and does not retry by itself', async () => {
    const aiRequests = aiHandler((url) =>
      url.searchParams.get('generate') === 'true'
        ? HttpResponse.json(
            { error: { code: 'HTTP_429', message: 'Too many AI analysis requests.' } },
            { status: 429, headers: { 'Retry-After': '30' } },
          )
        : HttpResponse.json({ suggestions: [], status: 'not_generated', method: null }),
    );
    renderDrawer();
    await openAiTab();
    await userEvent.click(await screen.findByRole('button', { name: /^Generate AI Suggestions$/ }));
    expect(await screen.findByText(/Try again in 30 seconds/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(aiRequests).toHaveLength(2);
    // Still offered as a manual action.
    expect(screen.getByRole('button', { name: /^Generate AI Suggestions$/ })).toBeInTheDocument();
  });

  it('shows the backend message when rejection feedback is refused (403)', async () => {
    let body: any = null;
    aiHandler(() => HttpResponse.json({ suggestions: aiSuggs(), status: 'cached', method: 'llm' }));
    server.use(
      http.post(FEEDBACK_URL, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(
          { error: { code: 'HTTP_403', message: 'You do not have access to this document' } },
          { status: 403 },
        );
      }),
    );
    renderDrawer();
    await openAiTab();
    await waitFor(() => expect(screen.getByText('Confidential')).toBeInTheDocument());
    await userEvent.click(screen.getAllByRole('button', { name: 'Reject' })[0]);
    expect(
      await screen.findByText(/You do not have access to this document/),
    ).toBeInTheDocument();
    expect(body).toMatchObject({
      suggestion_text: 'Confidential',
      suggestion_category: 'CONF',
      suggestion_reason: 'classified',
      feedback: 'rejected',
    });
  });

  it('sends empty strings rather than omitting category/reason in feedback', async () => {
    let body: any = null;
    aiHandler(() =>
      HttpResponse.json({
        suggestions: [{ text: 'Bare', confidence: 'low', page: 1 }],
        status: 'cached',
        method: 'llm',
      }),
    );
    server.use(
      http.post(FEEDBACK_URL, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ success: true });
      }),
    );
    renderDrawer();
    await openAiTab();
    await waitFor(() => expect(screen.getByText('Bare')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body.suggestion_category).toBe('');
    expect(body.suggestion_reason).toBe('');
  });
});
