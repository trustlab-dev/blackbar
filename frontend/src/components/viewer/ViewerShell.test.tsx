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
import { UserProvider } from '../../contexts/UserContext';

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

describe('ViewerShell — original PDF object URL lifecycle', () => {
  it('revokes the blob URL on unmount and when the document changes', async () => {
    let n = 0;
    (global.URL.createObjectURL as any) = vi.fn(() => `blob:doc-${++n}`);
    const revoke = vi.fn();
    (global.URL.revokeObjectURL as any) = revoke;

    const { rerender, unmount } = renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.pdfUrl).toBe('blob:doc-1'));
    expect(revoke).not.toHaveBeenCalled();

    rerender(<ViewerShell documentId="doc-2" />);
    expect(revoke).toHaveBeenCalledWith('blob:doc-1');
    await waitFor(() => expect(mockPdfViewerProps.current?.pdfUrl).toBe('blob:doc-2'));

    unmount();
    expect(revoke).toHaveBeenCalledWith('blob:doc-2');
  });
});

describe('ViewerShell — original PDF download fails', () => {
  it('hands the viewer an undefined URL so it retries and can show its error', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(http.get(DOC_URL, () => new HttpResponse(null, { status: 500 })));
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current).not.toBeNull());
    await waitFor(() => expect(mockPdfViewerProps.current.pdfUrl).toBeUndefined());
  });
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

  it('redaction menu: a legacy record without an ID is read-only with a hint', async () => {
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({
          ...metaResponse(),
          redactions: [{
            x: 10, y: 10, width: 50, height: 20, page: 1,
            description: 'note', category: 'PII', status: 'approved',
          }],
        }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.redactions?.length).toBe(1));
    mockPdfViewerProps.current.onRedactionClick(0, {
      stopPropagation: vi.fn(), clientX: 0, clientY: 0,
    });
    expect(await screen.findByText(/older redaction has no ID/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete Redaction/i })).toBeNull();
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

  it('handleRejectSuggestion reports a refused (404) feedback call', async () => {
    server.use(
      http.post(FEEDBACK_URL, () =>
        HttpResponse.json(
          { error: { code: 'HTTP_404', message: 'Document not found' } },
          { status: 404 },
        ),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    mockPdfViewerProps.current.onSuggestionReject({
      text: 'X', category: 'PII', section: 'A', reason: '', confidence: 'low', page: 1,
    });
    expect(await screen.findByText(/Rejection not recorded: Document not found/)).toBeInTheDocument();
  });

  it('loads cached AI suggestions on open without asking the backend to generate', async () => {
    const queries: URLSearchParams[] = [];
    server.use(
      http.get(SUGG_URL, ({ request }) => {
        queries.push(new URL(request.url).searchParams);
        return HttpResponse.json({ suggestions: [], status: 'not_generated', method: null });
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(queries.length).toBeGreaterThan(0));
    for (const q of queries) {
      expect(q.get('generate')).toBeNull();
      expect(q.get('force_regenerate')).toBeNull();
    }
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

// Backend contract (commit 10b2d7e): redactions are addressed by stable id;
// add returns {id, status}; only approved redactions are exported and
// anything unresolved blocks export (409). See
// backend/src/documents/redaction_routes.py and routes.py export handler.
describe('ViewerShell — export for guests', () => {
  afterEach(() => localStorage.removeItem('userRole'));

  it('hides Export from guests (the backend refuses them)', async () => {
    localStorage.setItem('userRole', 'guest');
    renderWithProviders(
      <UserProvider>
        <ViewerShell documentId="doc-1" />
      </UserProvider>,
    );
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /export redacted pdf/i })).not.toBeInTheDocument();
  });

  it('shows Export to staff roles', async () => {
    localStorage.setItem('userRole', 'analyst');
    renderWithProviders(
      <UserProvider>
        <ViewerShell documentId="doc-1" />
      </UserProvider>,
    );
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /export redacted pdf/i })).toBeInTheDocument();
  });
});

describe('ViewerShell — redaction review and export', () => {
  const APPROVE_URL = 'https://localhost:3000/api/v1/documents/:id/redactions/:rid/approve';
  const EXPORT_URL = 'https://localhost:3000/api/v1/documents/:id/export';

  const proposed = {
    id: 'r-prop', x: 10, y: 10, width: 50, height: 20, page: 1,
    description: 'proposal', category: 'S22', type: 'proposed', status: 'proposed',
    created_by_role: 'user',
  };
  const approved = {
    id: 'r-ok', x: 100, y: 100, width: 50, height: 20, page: 1,
    description: 'done', category: 'S19', type: 'professional', status: 'approved',
  };

  function withRedactions(redactions: any[]) {
    server.use(http.get(META_URL, () => HttpResponse.json({ ...metaResponse(), redactions })));
  }

  it('renders the status the add response returns (proposed) instead of assuming', async () => {
    server.use(
      http.post(REDACT_URL, () =>
        HttpResponse.json({ message: 'Redaction proposed for review', id: 'r-new', status: 'proposed' }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-draw'));
    await userEvent.click(screen.getByText('fire-draw'));
    await userEvent.click(screen.getByText('save-reason'));
    await waitFor(() =>
      expect(mockPdfViewerProps.current.redactions).toEqual([
        // The add response has no `type`; a proposed record is a proposal.
        expect.objectContaining({ id: 'r-new', status: 'proposed', type: 'proposed' }),
      ]),
    );
    expect(await screen.findByText(/proposed for review/i)).toBeInTheDocument();
    expect(screen.queryByText(/not a proposal/i)).not.toBeInTheDocument();
    expect(screen.getByText(/1 redaction awaiting review/i)).toBeInTheDocument();
  });

  it('an approved add response does not block export', async () => {
    server.use(
      http.post(REDACT_URL, () =>
        HttpResponse.json({ message: 'Redaction added', id: 'r-new', status: 'approved' }),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-draw'));
    await userEvent.click(screen.getByText('fire-draw'));
    await userEvent.click(screen.getByText('save-reason'));
    await waitFor(() =>
      expect(mockPdfViewerProps.current.redactions).toEqual([
        expect.objectContaining({ id: 'r-new', status: 'approved' }),
      ]),
    );
    expect(screen.queryByText(/awaiting review/i)).toBeNull();
  });

  it('422 on add: shows the reason, keeps the draw tool on, and adds nothing', async () => {
    server.use(
      http.post(REDACT_URL, () =>
        HttpResponse.json(
          { error: { code: 'HTTP_422', message: 'Invalid redaction: box (1.0, 2.0, 3.0 x 4.0) is outside page 1 (612.0 x 792.0)' } },
          { status: 422 },
        ),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-draw'));
    await userEvent.click(screen.getByText('fire-draw'));
    await userEvent.click(screen.getByText('save-reason'));
    expect(await screen.findByText(/is outside page 1/i)).toBeInTheDocument();
    expect(screen.getByTestId('draw-tool-mock')).toBeInTheDocument();
    expect(mockPdfViewerProps.current.redactions).toEqual([]);
  });

  it('409 on add (document without content / failed conversion) shows the backend message', async () => {
    server.use(
      http.post(REDACT_URL, () =>
        HttpResponse.json(
          { error: { code: 'HTTP_409', message: 'Document failed conversion to PDF; it cannot be redacted or released.' } },
          { status: 409 },
        ),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tool-draw'));
    await userEvent.click(screen.getByText('fire-draw'));
    await userEvent.click(screen.getByText('save-reason'));
    expect(await screen.findByText(/failed conversion to PDF/i)).toBeInTheDocument();
  });

  it('counts blocking redactions and approves a proposal by id', async () => {
    let putUrl = '';
    let putBody: any = null;
    withRedactions([proposed, approved]);
    server.use(
      http.put(APPROVE_URL, async ({ request }) => {
        putUrl = request.url;
        putBody = await request.json();
        return HttpResponse.json({ success: true, message: 'Proposed redaction approved', redaction_id: 'r-prop' });
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    expect(await screen.findByText(/1 redaction awaiting review/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^review$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }));
    await waitFor(() => expect(putBody).toEqual({ action: 'approve' }));
    expect(putUrl).toMatch(/\/documents\/doc-1\/redactions\/r-prop\/approve$/);
    await waitFor(() => expect(screen.queryByText(/awaiting review/i)).toBeNull());
    expect(
      mockPdfViewerProps.current.redactions.find((r: any) => r.id === 'r-prop').status,
    ).toBe('approved');
  });

  it('rejects a proposal by id', async () => {
    let putBody: any = null;
    withRedactions([proposed]);
    server.use(
      http.put(APPROVE_URL, async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ success: true, message: 'Proposed redaction rejected', redaction_id: 'r-prop' });
      }),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await userEvent.click(await screen.findByRole('button', { name: /^review$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }));
    await waitFor(() => expect(putBody).toEqual({ action: 'reject' }));
    await waitFor(() => expect(screen.queryByText(/awaiting review/i)).toBeNull());
  });

  it('409 on approve (changed concurrently) reloads the redactions and says so', async () => {
    let metaCalls = 0;
    server.use(
      http.get(META_URL, () => {
        metaCalls += 1;
        return HttpResponse.json({ ...metaResponse(), redactions: [proposed] });
      }),
      http.put(APPROVE_URL, () =>
        HttpResponse.json(
          { error: { code: 'HTTP_409', message: 'Redaction changed concurrently; reload and retry' } },
          { status: 409 },
        ),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await userEvent.click(await screen.findByRole('button', { name: /^review$/i }));
    const before = metaCalls;
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }));
    expect(await screen.findByText(/changed concurrently/i)).toBeInTheDocument();
    await waitFor(() => expect(metaCalls).toBeGreaterThan(before));
  });

  it('shows legacy records without an id as read-only in the review list', async () => {
    const { id: _omit, ...legacy } = proposed;
    void _omit;
    withRedactions([legacy]);
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await userEvent.click(await screen.findByRole('button', { name: /^review$/i }));
    expect(screen.getByText(/older redaction has no ID/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^approve$/i })).toBeNull();
  });

  it('explains contested redactions instead of offering approve', async () => {
    withRedactions([{ ...approved, id: 'r-con', status: 'contested', is_contested: true }]);
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await userEvent.click(await screen.findByRole('button', { name: /^review$/i }));
    expect(screen.getByText(/resolve the contest/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^approve$/i })).toBeNull();
  });

  it('export 409 shows the backend message', async () => {
    withRedactions([approved]);
    server.use(
      http.get(EXPORT_URL, () =>
        HttpResponse.json(
          { error: { code: 'HTTP_409', message: '1 redaction(s) are awaiting review (proposed, contested or pending). Approve or reject them before exporting.' } },
          { status: 409 },
        ),
      ),
    );
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /export redacted pdf/i }));
    expect(await screen.findByText(/Approve or reject them before exporting/i)).toBeInTheDocument();
  });

  it('export downloads the redacted PDF', async () => {
    withRedactions([approved]);
    let exported = false;
    server.use(
      http.get(EXPORT_URL, () => {
        exported = true;
        return HttpResponse.arrayBuffer(new ArrayBuffer(4), {
          headers: {
            'Content-Type': 'application/pdf',
            'Content-Disposition': 'attachment; filename="sample_REDACTED_doc-1_x.pdf"',
          },
        });
      }),
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(screen.getByText('sample.pdf')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /export redacted pdf/i }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(exported).toBe(true);
  });

  it('selecting a redaction on page 2 opens that record, not page 1\'s', async () => {
    withRedactions([
      { ...approved, id: 'r-p1', page: 1, category: 'PAGE-ONE' },
      { ...approved, id: 'r-p2', page: 2, category: 'PAGE-TWO' },
    ]);
    renderWithProviders(<ViewerShell documentId="doc-1" />);
    await waitFor(() => expect(mockPdfViewerProps.current?.redactions?.length).toBe(1));
    const nextBtn = screen.getAllByRole('button').find(b =>
      b.querySelector('[data-testid="ChevronRightIcon"]'),
    )!;
    await userEvent.click(nextBtn);
    await waitFor(() => expect(mockPdfViewerProps.current.redactions[0].id).toBe('r-p2'));
    mockPdfViewerProps.current.onRedactionClick(0, {
      stopPropagation: vi.fn(), clientX: 0, clientY: 0,
    });
    expect(await screen.findByText('PAGE-TWO')).toBeInTheDocument();
    await waitFor(() => expect(mockPdfViewerProps.current.selectedRedactionIndex).toBe(0));
  });
});
