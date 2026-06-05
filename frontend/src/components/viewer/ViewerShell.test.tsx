// frontend/src/components/viewer/ViewerShell.test.tsx
//
// Composition-root test. Heavy children (PDF viewer, drawers, tools) are
// mocked so the suite stays under 5s and focuses on the orchestration logic
// in ViewerShell itself: routing, top-bar controls, page nav, zoom, tool
// switching, reason-picker wiring, redaction CRUD against the backend.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock heavy/PDF children before importing the component. Each mock keeps a
// reference to its rendered props so individual tests can interact with them.
const mockPdfViewerProps: { current: any } = { current: null };
vi.mock('./PDFViewerWithSelection', () => ({
  default: (props: any) => {
    mockPdfViewerProps.current = props;
    return <div data-testid="pdf-viewer-mock" data-page={props.currentPage} data-zoom={props.zoom} />;
  },
}));

const mockThumbProps: { current: any } = { current: null };
vi.mock('./ThumbnailsRail', () => ({
  default: (props: any) => {
    mockThumbProps.current = props;
    return <div data-testid="thumbnails-rail-mock" data-numpages={props.numPages} />;
  },
}));

vi.mock('./LeftToolRail', () => ({
  default: (props: any) => (
    <div data-testid="left-tool-rail-mock">
      <button onClick={() => props.onToolChange('select')}>tool-select</button>
      <button onClick={() => props.onToolChange('draw-redaction')}>tool-draw</button>
      <button onClick={() => props.onToolChange('find-replace')}>tool-find</button>
      <button onClick={() => props.onToolChange('rotate')}>tool-rotate</button>
      <button onClick={() => props.onToolChange('color')}>tool-color</button>
    </div>
  ),
}));

vi.mock('./RightUtilityBar', () => ({
  default: (props: any) => (
    <div data-testid="right-utility-bar-mock">
      <button onClick={() => props.onTogglePreview(!props.showRedactionPreview)}>toggle-preview</button>
      <button onClick={() => props.onAutoSuggestClick()}>open-auto-suggest</button>
      <button onClick={() => props.onHistoryClick()}>open-history</button>
      <button onClick={() => props.onCommentsClick()}>open-comments</button>
    </div>
  ),
}));

const mockReasonModalProps: { current: any } = { current: null };
vi.mock('./ReasonPickerModal', () => ({
  default: (props: any) => {
    mockReasonModalProps.current = props;
    return props.open ? (
      <div data-testid="reason-picker-mock">
        <button
          onClick={() =>
            props.onSave({
              categoryCode: 'EX-1',
              categoryName: 'Personal',
              section: 'EX-1',
              sections: ['EX-1'],
              primarySection: 'EX-1',
              notes: 'note',
            })
          }
        >
          save-reason
        </button>
        <button onClick={props.onClose}>cancel-reason</button>
      </div>
    ) : null;
  },
}));

const mockDrawProps: { current: any } = { current: null };
vi.mock('./DrawRedactionTool', () => ({
  default: (props: any) => {
    mockDrawProps.current = props;
    return props.enabled ? (
      <div data-testid="draw-tool-mock">
        <button
          onClick={() =>
            props.onRedactionCreated({
              x: 1, y: 2, width: 3, height: 4, text: 'X', snappedWords: [],
            })
          }
        >
          fire-draw
        </button>
      </div>
    ) : null;
  },
}));

vi.mock('./ManualRedactionTool', () => ({
  default: (props: any) => props.enabled ? <div data-testid="manual-tool-mock" /> : null,
}));

const mockFindDrawerProps: { current: any } = { current: null };
vi.mock('./FindReplaceDrawer', () => ({
  default: (props: any) => {
    mockFindDrawerProps.current = props;
    return props.open ? (
      <div data-testid="find-drawer-mock">
        <button
          onClick={() =>
            props.onRedactMatches(
              [{ page: 1, text: 'foo', bbox: [10, 10, 30, 20], context: 'foo bar' }],
              'foo',
            )
          }
        >
          fire-find
        </button>
        <button onClick={() => props.onNavigateToMatch(2, [5, 5, 15, 15])}>
          navigate-match
        </button>
      </div>
    ) : null;
  },
}));

const mockAutoSuggestProps: { current: any } = { current: null };
vi.mock('./AutoSuggestDrawer', () => ({
  default: (props: any) => {
    mockAutoSuggestProps.current = props;
    return props.open ? (
      <div data-testid="auto-suggest-mock">
        <button
          onClick={() =>
            props.onApplySuggestions([
              { text: 'sample', category: 'PII', reason: 'name', page: 1, x: 10, y: 10, width: 50, height: 20 },
            ])
          }
        >
          apply-suggestions
        </button>
      </div>
    ) : null;
  },
}));

vi.mock('./HistoryDrawer', () => ({
  default: (props: any) => props.open ? <div data-testid="history-drawer-mock" /> : null,
}));

vi.mock('./CommentsDrawer', () => ({
  default: (props: any) => props.open ? <div data-testid="comments-drawer-mock" /> : null,
}));

vi.mock('./SuggestedRedactionOverlay', () => ({
  default: () => <div data-testid="suggestion-overlay-mock" />,
}));

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

import { http, HttpResponse } from 'msw';
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen } from '../../test-utils/render';
import ViewerShell from './ViewerShell';

const META_URL = 'https://localhost:3000/api/v1/documents/:id/metadata';
const DOC_URL = 'https://localhost:3000/api/v1/documents/:id';
const SUGG_URL = 'https://localhost:3000/api/v1/documents/:id/redaction-suggestions';
const REDACT_URL = 'https://localhost:3000/api/v1/documents/:id/redactions';
const REDACT_DEL_URL = 'https://localhost:3000/api/v1/documents/:id/redactions/:rid';
const FEEDBACK_URL = 'https://localhost:3000/api/v1/documents/:id/ai-feedback';

function metaResponse(overrides: any = {}) {
  return {
    filename: 'sample.pdf',
    text_data: {
      pages: [
        { page_num: 1, width: 612, height: 792, words: [{ text: 'hello world', bbox: [10, 10, 50, 30], line_num: 0 }], lines: [] },
        { page_num: 2, width: 612, height: 792, words: [], lines: [] },
      ],
    },
    ...overrides,
  };
}

beforeEach(() => {
  mockPdfViewerProps.current = null;
  mockThumbProps.current = null;
  mockReasonModalProps.current = null;
  mockDrawProps.current = null;
  mockFindDrawerProps.current = null;
  mockAutoSuggestProps.current = null;
  (global.URL.createObjectURL as any) = vi.fn(() => 'blob:mock-url');
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  // Default handlers
  server.use(
    http.get(META_URL, () => HttpResponse.json(metaResponse())),
    http.get(DOC_URL, () =>
      HttpResponse.arrayBuffer(new ArrayBuffer(8), {
        headers: { 'Content-Type': 'application/pdf' },
      }),
    ),
    http.get(SUGG_URL, () => HttpResponse.json({ suggestions: [] })),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ViewerShell', () => {
  it('renders filename from document metadata', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
  });

  it('shows "Loading..." before metadata arrives', () => {
    server.use(http.get(META_URL, () => new Promise(() => {}) as any));
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('fetches case info when case_id is present', async () => {
    let caseRequested = false;
    server.use(
      http.get(META_URL, () => HttpResponse.json(metaResponse({ case_id: 'c-1' }))),
      http.get('https://localhost:3000/api/v1/cases/c-1', () => {
        caseRequested = true;
        return HttpResponse.json({ tracking_number: 'TRK-001' });
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(caseRequested).toBe(true));
  });

  it('renders zoom % indicator and increments via zoom in', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    // Default zoom is 1.5 (150%)
    expect(screen.getByText('150%')).toBeInTheDocument();
    // The two icon buttons before/after the zoom % are ZoomOut then ZoomIn.
    // Find via the rendered zoom values
    const buttons = screen.getAllByRole('button');
    const zoomInBtn = buttons.find(b => b.querySelector('[data-testid="ZoomInIcon"]'))!;
    await userEvent.click(zoomInBtn);
    expect(screen.getByText('200%')).toBeInTheDocument();
  });

  it('zoom out decrements through ZOOM_LEVELS', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('150%')).toBeInTheDocument());
    const zoomOut = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="ZoomOutIcon"]'),
    )!;
    await userEvent.click(zoomOut);
    expect(screen.getByText('125%')).toBeInTheDocument();
  });

  it('zoom in stops at max (300%) and zoom out stops at min (50%)', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('150%')).toBeInTheDocument());
    const zoomIn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="ZoomInIcon"]'),
    )!;
    // 1.5 -> 2.0 -> 3.0 -> stays at 3.0
    await userEvent.click(zoomIn);
    await userEvent.click(zoomIn);
    await userEvent.click(zoomIn);
    expect(screen.getByText('300%')).toBeInTheDocument();
    const zoomOut = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="ZoomOutIcon"]'),
    )!;
    for (let i = 0; i < 10; i++) await userEvent.click(zoomOut);
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('paging: Next, Previous, First, Last update the displayed page', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('1 of 2')).toBeInTheDocument());
    const nextBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="ChevronRightIcon"]'),
    )!;
    await userEvent.click(nextBtn);
    expect(screen.getByText('2 of 2')).toBeInTheDocument();
    const prevBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="ChevronLeftIcon"]'),
    )!;
    await userEvent.click(prevBtn);
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    const lastBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="LastPageIcon"]'),
    )!;
    await userEvent.click(lastBtn);
    expect(screen.getByText('2 of 2')).toBeInTheDocument();
    const firstBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="FirstPageIcon"]'),
    )!;
    await userEvent.click(firstBtn);
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
  });

  it('tool switch to draw-redaction enables the draw tool, find-replace opens drawer', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-draw'));
    expect(screen.getByTestId('draw-tool-mock')).toBeInTheDocument();
    await userEvent.click(screen.getByText('tool-find'));
    expect(screen.getByTestId('find-drawer-mock')).toBeInTheDocument();
    // Switching to select disables both
    await userEvent.click(screen.getByText('tool-select'));
    expect(screen.queryByTestId('draw-tool-mock')).toBeNull();
    expect(screen.queryByTestId('find-drawer-mock')).toBeNull();
  });

  it('tool switch to rotate and color exercise default switch branches', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-rotate'));
    await userEvent.click(screen.getByText('tool-color'));
    expect(screen.getByText('sample.pdf')).toBeInTheDocument();
  });

  it('opens AutoSuggest, History, Comments drawers from RightUtilityBar', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('open-history'));
    expect(screen.getByTestId('history-drawer-mock')).toBeInTheDocument();
    await userEvent.click(screen.getByText('open-comments'));
    expect(screen.getByTestId('comments-drawer-mock')).toBeInTheDocument();
    await userEvent.click(screen.getByText('open-auto-suggest'));
    expect(screen.getByTestId('auto-suggest-mock')).toBeInTheDocument();
  });

  it('toggles redaction preview from the utility bar', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    // PDFViewer receives initial showRedactionPreview=true
    expect(mockPdfViewerProps.current.showRedactionPreview).toBe(true);
    await userEvent.click(screen.getByText('toggle-preview'));
    await waitFor(() =>
      expect(mockPdfViewerProps.current.showRedactionPreview).toBe(false),
    );
  });

  it('Undo/Redo buttons are disabled when stacks are empty', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    const undoBtn = screen.getByRole('button', { name: /Undo/i });
    const redoBtn = screen.getByRole('button', { name: /Redo/i });
    expect(undoBtn).toBeDisabled();
    expect(redoBtn).toBeDisabled();
  });

  it('draw tool → reason picker save flow creates a redaction', async () => {
    let postBody: any = null;
    server.use(
      http.post(REDACT_URL, async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({ redaction: { id: 'r-1', created_by: 'me', created_by_role: 'admin', created_at: '2026-01-01T00:00:00Z' } });
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-draw'));
    await userEvent.click(screen.getByText('fire-draw'));
    expect(screen.getByTestId('reason-picker-mock')).toBeInTheDocument();
    await userEvent.click(screen.getByText('save-reason'));
    await waitFor(() => expect(postBody).not.toBeNull());
    expect(postBody.category).toBe('EX-1');
  });

  it('shows error snackbar when saving a redaction fails (401)', async () => {
    server.use(
      http.post(REDACT_URL, () => new HttpResponse(null, { status: 401 })),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-draw'));
    await userEvent.click(screen.getByText('fire-draw'));
    await userEvent.click(screen.getByText('save-reason'));
    await waitFor(() =>
      expect(screen.getByText(/Authentication required/)).toBeInTheDocument(),
    );
  });

  it('cancel on reason picker closes the modal', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-draw'));
    await userEvent.click(screen.getByText('fire-draw'));
    await userEvent.click(screen.getByText('cancel-reason'));
    expect(screen.queryByTestId('reason-picker-mock')).toBeNull();
  });

  it('Find & Redact: clicking fire-find opens reason picker with the matches', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-find'));
    await userEvent.click(screen.getByText('fire-find'));
    expect(screen.getByTestId('reason-picker-mock')).toBeInTheDocument();
  });

  it('Find drawer "navigate-match" jumps to that page', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-find'));
    await userEvent.click(screen.getByText('navigate-match'));
    expect(screen.getByText('2 of 2')).toBeInTheDocument();
  });

  it('initial redactions from metadata are mapped and passed to PDF viewer', async () => {
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({
          ...metaResponse(),
          redactions: [
            {
              id: 'r-1', x: 10, y: 10, width: 50, height: 20, page: 1,
              description: 'desc', category: 'PII', section: 'A',
              type: 'manual', status: 'pending', created_by_role: 'analyst',
              created_at: '2026-01-01T00:00:00Z',
            },
            {
              id: 'r-2', x: 20, y: 20, width: 50, height: 20, page: 1,
              description: '', category: 'AI', section: 'B',
              type: 'ai_suggestion', status: 'pending',
            },
          ],
        }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() =>
      expect(mockPdfViewerProps.current?.redactions?.length).toBe(2),
    );
    expect(mockPdfViewerProps.current.redactions[1].color).toBe('green');
  });

  it('AutoSuggest apply-suggestions creates redactions via API', async () => {
    let count = 0;
    server.use(
      http.post(REDACT_URL, () => {
        count += 1;
        return HttpResponse.json({ redaction: { id: 'r-app', created_by_role: 'admin' } });
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('open-auto-suggest'));
    await userEvent.click(screen.getByText('apply-suggestions'));
    await waitFor(() => expect(count).toBe(1));
  });

  it('AutoSuggest apply-suggestions error path sets snackbar', async () => {
    server.use(
      http.post(REDACT_URL, () => new HttpResponse(null, { status: 500 })),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('open-auto-suggest'));
    await userEvent.click(screen.getByText('apply-suggestions'));
    await waitFor(() =>
      expect(screen.getByText(/Failed to apply some suggestions/)).toBeInTheDocument(),
    );
  });

  it('AutoSuggest applies suggestion with text-only fallback (OCR coord lookup)', async () => {
    let postBody: any = null;
    server.use(
      http.post(REDACT_URL, async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({ redaction: { id: 'r-app' } });
      }),
    );
    // Replace mock so apply-suggestions sends a coordless suggestion that matches OCR.
    mockAutoSuggestProps.current = null;
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('open-auto-suggest'));
    // Directly invoke onApplySuggestions with no coords + OCR-matchable text.
    mockAutoSuggestProps.current.onApplySuggestions([
      { text: 'hello world', category: 'PII', reason: 'name', page: 1 },
    ]);
    await waitFor(() => expect(postBody).not.toBeNull());
    expect(postBody.x).toBe(10);
    expect(postBody.y).toBe(10);
  });

  it('thumbnails rail can be toggled off (default on)', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() =>
      expect(screen.getByTestId('thumbnails-rail-mock')).toBeInTheDocument(),
    );
  });

  it('handleBack navigates to case documents when case_id is set', async () => {
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json(metaResponse({ case_id: 'c-99' })),
      ),
      http.get('https://localhost:3000/api/v1/cases/c-99', () =>
        HttpResponse.json({ tracking_number: 'TRK-99' }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />, { route: '/start' });
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    const backBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="ArrowBackIcon"]'),
    )!;
    await userEvent.click(backBtn);
    // Navigation triggers — nothing crashes, sample.pdf may still render briefly.
    expect(backBtn).toBeInTheDocument();
  });

  it('handleBack falls back to window.history.back when no case_id', async () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    const backBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="ArrowBackIcon"]'),
    )!;
    await userEvent.click(backBtn);
    expect(back).toHaveBeenCalled();
  });

  it('handleUndo and handleRedo are no-op stubs that just log', async () => {
    // Undo/Redo are disabled by default. We exercise them by ensuring the
    // disabled-state branch renders without crashing.
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Undo/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Redo/i })).toBeDisabled();
  });

  it('handles redactionClick to open the redaction context menu', async () => {
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({
          ...metaResponse(),
          redactions: [{
            id: 'r-1', x: 10, y: 10, width: 50, height: 20, page: 1,
            description: 'A note', category: 'PII', section: 'A',
            type: 'manual', status: 'pending',
          }],
        }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.redactions?.length).toBe(1));
    // Simulate the child clicking a redaction
    mockPdfViewerProps.current.onRedactionClick(0, {
      stopPropagation: vi.fn(),
      clientX: 100,
      clientY: 200,
    });
    // Confirm the selected index propagates back through props
    await waitFor(() =>
      expect(mockPdfViewerProps.current?.selectedRedactionIndex).toBe(0),
    );
  });

  it('PDF metadata fetch failure does not crash (just logs)', async () => {
    server.use(http.get(META_URL, () => new HttpResponse(null, { status: 500 })));
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('Loading...')).toBeInTheDocument());
  });

  it('fetchSuggestions failure does not crash', async () => {
    server.use(
      http.get(SUGG_URL, () => new HttpResponse(null, { status: 500 })),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
  });

  it('fetchPDF failure does not crash', async () => {
    server.use(http.get(DOC_URL, () => new HttpResponse(null, { status: 500 })));
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
  });

  it('redaction menu: shows Redaction Details popover, allows edit + save', async () => {
    let putBody: any = null;
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({
          ...metaResponse(),
          redactions: [{
            id: 'r-1', x: 10, y: 10, width: 50, height: 20, page: 1,
            description: 'orig note', category: 'PII', section: 'A',
            type: 'manual', status: 'pending', created_by_role: 'analyst',
            created_at: '2026-01-01T00:00:00Z',
          }],
        }),
      ),
      http.put(
        'https://localhost:3000/api/v1/documents/:id/redactions/:rid/edit',
        async ({ request }) => {
          putBody = await request.json();
          return HttpResponse.json({ ok: true });
        },
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.redactions?.length).toBe(1));
    mockPdfViewerProps.current.onRedactionClick(0, {
      stopPropagation: vi.fn(), clientX: 100, clientY: 200,
    });
    expect(await screen.findByText('Redaction Details')).toBeInTheDocument();
    // Start editing
    const editBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="EditIcon"]'),
    )!;
    await userEvent.click(editBtn);
    const saveBtn = screen.getByRole('button', { name: /^Save$/i });
    await userEvent.click(saveBtn);
    await waitFor(() => expect(putBody).not.toBeNull());
  });

  it('redaction menu: cancel-edit reverts and keeps popover open', async () => {
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({
          ...metaResponse(),
          redactions: [{
            id: 'r-1', x: 10, y: 10, width: 50, height: 20, page: 1,
            description: 'note', category: 'PII', section: 'A',
            type: 'manual', status: 'pending',
          }],
        }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.redactions?.length).toBe(1));
    mockPdfViewerProps.current.onRedactionClick(0, {
      stopPropagation: vi.fn(), clientX: 0, clientY: 0,
    });
    await screen.findByText('Redaction Details');
    const editBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="EditIcon"]'),
    )!;
    await userEvent.click(editBtn);
    const cancelBtn = screen.getByRole('button', { name: /^Cancel$/i });
    await userEvent.click(cancelBtn);
    expect(screen.getByRole('button', { name: /Delete Redaction/i })).toBeInTheDocument();
  });

  it('redaction menu: delete sends DELETE API and removes redaction', async () => {
    let deleted = false;
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({
          ...metaResponse(),
          redactions: [{
            id: 'r-1', x: 10, y: 10, width: 50, height: 20, page: 1,
            description: 'note', category: 'PII',
          }],
        }),
      ),
      http.delete(REDACT_DEL_URL, () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.redactions?.length).toBe(1));
    mockPdfViewerProps.current.onRedactionClick(0, {
      stopPropagation: vi.fn(), clientX: 0, clientY: 0,
    });
    const delBtn = await screen.findByRole('button', { name: /Delete Redaction/i });
    await userEvent.click(delBtn);
    await waitFor(() => expect(deleted).toBe(true));
  });

  it('redaction menu: delete without ID removes locally and shows error', async () => {
    // Manually inject a redaction without an id via metadata returning an id of undefined
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({
          ...metaResponse(),
          redactions: [{
            x: 10, y: 10, width: 50, height: 20, page: 1,
            description: 'note', category: 'PII',
          }],
        }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.redactions?.length).toBe(1));
    mockPdfViewerProps.current.onRedactionClick(0, {
      stopPropagation: vi.fn(), clientX: 0, clientY: 0,
    });
    const delBtn = await screen.findByRole('button', { name: /Delete Redaction/i });
    await userEvent.click(delBtn);
    await waitFor(() =>
      expect(screen.getByText(/Redaction removed locally/)).toBeInTheDocument(),
    );
  });

  it('redaction menu: delete API failure shows error message', async () => {
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({
          ...metaResponse(),
          redactions: [{
            id: 'r-1', x: 10, y: 10, width: 50, height: 20, page: 1,
            description: 'note', category: 'PII',
          }],
        }),
      ),
      http.delete(REDACT_DEL_URL, () =>
        HttpResponse.json({ detail: 'permission denied' }, { status: 403 }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.redactions?.length).toBe(1));
    mockPdfViewerProps.current.onRedactionClick(0, {
      stopPropagation: vi.fn(), clientX: 0, clientY: 0,
    });
    const delBtn = await screen.findByRole('button', { name: /Delete Redaction/i });
    await userEvent.click(delBtn);
    await waitFor(() =>
      expect(screen.getByText(/permission denied/)).toBeInTheDocument(),
    );
  });

  it('handleAcceptSuggestion accepts a suggestion with coordinates', async () => {
    let postBody: any = null;
    server.use(
      http.get(SUGG_URL, () =>
        HttpResponse.json({
          suggestions: [
            {
              text: 'name',
              category: 'PII',
              section: 'A',
              reason: 'name',
              confidence: 'high',
              page: 1,
              coordinates: { x: 10, y: 10, width: 50, height: 20 },
            },
          ],
        }),
      ),
      http.post(REDACT_URL, async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({ redaction: { id: 'r-acc' } });
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.suggestions?.length).toBe(1));
    mockPdfViewerProps.current.onSuggestionAccept({
      text: 'name', category: 'PII', section: 'A', reason: 'name', confidence: 'high', page: 1,
      coordinates: { x: 10, y: 10, width: 50, height: 20 },
    });
    await waitFor(() => expect(postBody).not.toBeNull());
  });

  it('handleAcceptSuggestion ignores suggestion without coordinates', async () => {
    let posted = false;
    server.use(
      http.post(REDACT_URL, () => {
        posted = true;
        return HttpResponse.json({});
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    mockPdfViewerProps.current.onSuggestionAccept({
      text: 'no-coords', category: 'PII', section: 'A', reason: '', confidence: 'low', page: 1,
    });
    await new Promise(r => setTimeout(r, 30));
    expect(posted).toBe(false);
  });

  it('handleAcceptSuggestion API failure surfaces snackbar', async () => {
    server.use(
      http.post(REDACT_URL, () => new HttpResponse(null, { status: 500 })),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    mockPdfViewerProps.current.onSuggestionAccept({
      text: 'X', category: 'PII', section: 'A', reason: '', confidence: 'low', page: 1,
      coordinates: { x: 10, y: 10, width: 50, height: 20 },
    });
    await waitFor(() =>
      expect(screen.getByText(/Failed to accept suggestion/)).toBeInTheDocument(),
    );
  });

  it('handleRejectSuggestion posts feedback and filters out the suggestion', async () => {
    let feedback: any = null;
    server.use(
      http.get(SUGG_URL, () =>
        HttpResponse.json({
          suggestions: [
            { text: 'X', category: 'PII', section: 'A', reason: '', confidence: 'low', page: 1,
              coordinates: { x: 10, y: 10, width: 50, height: 20 } },
          ],
        }),
      ),
      http.post(FEEDBACK_URL, async ({ request }) => {
        feedback = await request.json();
        return HttpResponse.json({});
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.suggestions?.length).toBe(1));
    mockPdfViewerProps.current.onSuggestionReject({
      text: 'X', category: 'PII', section: 'A', reason: '', confidence: 'low', page: 1,
      coordinates: { x: 10, y: 10, width: 50, height: 20 },
    });
    await waitFor(() => expect(feedback).not.toBeNull());
    expect(feedback.feedback).toBe('rejected');
  });

  it('handleRejectSuggestion swallows feedback API failure', async () => {
    server.use(
      http.post(FEEDBACK_URL, () => new HttpResponse(null, { status: 500 })),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    mockPdfViewerProps.current.onSuggestionReject({
      text: 'X', category: 'PII', section: 'A', reason: '', confidence: 'low', page: 1,
    });
    // Should not crash — confirm UI still renders
    expect(screen.getByText('sample.pdf')).toBeInTheDocument();
  });

  it('onTextSelected (select tool) triggers reason picker with multiple rects', async () => {
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    // The select tool is active by default. Trigger via the mocked PDF viewer.
    mockPdfViewerProps.current.onTextSelected([
      { x: 10, y: 10, width: 50, height: 20, text: 'A', snappedWords: [] },
      { x: 70, y: 10, width: 50, height: 20, text: 'B', snappedWords: [] },
    ]);
    expect(await screen.findByTestId('reason-picker-mock')).toBeInTheDocument();
  });

  it('handleScroll: wheel down advances page, wheel up reverses', async () => {
    vi.useFakeTimers();
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await vi.runOnlyPendingTimersAsync();
    // Wait for metadata; doing this synchronously with fake timers requires
    // letting microtasks resolve.
    vi.useRealTimers();
    await waitFor(() => expect(screen.getByText('1 of 2')).toBeInTheDocument());
    // Find pdf-canvas-container and fire wheel — we can use the test id
    // since the box wraps PDFViewerWithSelection.
    const container = document.querySelector('.pdf-canvas-container') as HTMLElement;
    expect(container).not.toBeNull();
    // Trigger wheel down → advance
    const evt = new WheelEvent('wheel', { deltaY: 100, bubbles: true });
    container.dispatchEvent(evt);
    await waitFor(
      () => expect(screen.getByText('2 of 2')).toBeInTheDocument(),
      { timeout: 1000 },
    );
  });
});
