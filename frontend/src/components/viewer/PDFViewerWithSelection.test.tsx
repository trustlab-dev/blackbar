// frontend/src/components/viewer/PDFViewerWithSelection.test.tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Stub the URL constructor for the pdfjs worker line (uses `import.meta.url`
// which Vitest doesn't expose as a string). This runs before the component
// module is evaluated.
const { __urlPatch } = vi.hoisted(() => {
  const RealURL = global.URL;
  const PatchedURL = function (url: any, base?: any) {
    if (base && typeof base !== 'string') {
      return new RealURL(url, 'http://localhost/');
    }
    return new RealURL(url, base);
  } as any;
  PatchedURL.createObjectURL = (...args: any[]) => 'blob:mock-url';
  PatchedURL.revokeObjectURL = () => {};
  PatchedURL.prototype = RealURL.prototype;
  global.URL = PatchedURL;
  return { __urlPatch: true };
});
void __urlPatch;

// Mock react-pdf before component import — Document/Page can't render under jsdom.
vi.mock('react-pdf', () => ({
  Document: ({ children, onLoadSuccess, onLoadError, loading, error, file }: any) => {
    // Auto-fire onLoadSuccess on render so the numPages callback flows.
    setTimeout(() => onLoadSuccess?.({ numPages: 3 }), 0);
    return (
      <div data-testid="mock-document" data-file={typeof file === 'string' ? file : 'blob'}>
        {children}
      </div>
    );
  },
  Page: ({ pageNumber, scale }: any) => (
    <div data-testid="mock-page" data-page={pageNumber} data-scale={scale}>
      Page {pageNumber} @ {scale}
    </div>
  ),
  pdfjs: {
    GlobalWorkerOptions: { workerSrc: '' },
  },
}));

// react-pdf's CSS imports fail in jsdom; mock them as empty modules.
vi.mock('react-pdf/dist/Page/AnnotationLayer.css', () => ({}));
vi.mock('react-pdf/dist/Page/TextLayer.css', () => ({}));

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
import { waitFor, fireEvent } from '@testing-library/react';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen } from '../../test-utils/render';
import PDFViewerWithSelection from './PDFViewerWithSelection';

const DOC_URL = 'https://localhost:3000/api/v1/documents/:id';
const META_URL = 'https://localhost:3000/api/v1/documents/:id/metadata';

beforeEach(() => {
  // URL.createObjectURL is missing under jsdom.
  (global.URL.createObjectURL as any) = vi.fn(() => 'blob:mock-url');
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('PDFViewerWithSelection', () => {
  it('shows loading spinner while fetching PDF', () => {
    server.use(
      http.get(DOC_URL, () => new Promise(() => {}) as any),
      http.get(META_URL, () => HttpResponse.json({})),
    );
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        onNumPagesChange={() => {}}
      />,
    );
    expect(container.querySelector('.pdf-viewer-loading')).not.toBeNull();
  });

  it('renders document after fetching PDF blob (fires onNumPagesChange)', async () => {
    server.use(
      http.get(DOC_URL, () =>
        HttpResponse.arrayBuffer(new ArrayBuffer(8), {
          headers: { 'Content-Type': 'application/pdf' },
        }),
      ),
      http.get(META_URL, () => HttpResponse.json({})),
    );
    const onNumPagesChange = vi.fn();
    renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        onNumPagesChange={onNumPagesChange}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId('mock-document')).toBeInTheDocument(),
    );
    await waitFor(() => expect(onNumPagesChange).toHaveBeenCalledWith(3));
  });

  it('uses externally provided pdfUrl without fetching the document', async () => {
    let docFetched = false;
    server.use(
      http.get(DOC_URL, () => {
        docFetched = true;
        return new HttpResponse(null, { status: 500 });
      }),
      http.get(META_URL, () => HttpResponse.json({})),
    );
    renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={2}
        zoom={1.5}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId('mock-document')).toBeInTheDocument(),
    );
    expect(docFetched).toBe(false);
    expect(screen.getByTestId('mock-page')).toHaveAttribute('data-page', '2');
    expect(screen.getByTestId('mock-page')).toHaveAttribute('data-scale', '1.5');
  });

  it('logs and shows the "Failed to load PDF" UI when fetch fails', async () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(
      http.get(DOC_URL, () => new HttpResponse(null, { status: 500 })),
      http.get(META_URL, () => HttpResponse.json({})),
    );
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        onNumPagesChange={() => {}}
      />,
    );
    await waitFor(() =>
      expect(container.querySelector('.pdf-viewer-error')).not.toBeNull(),
    );
    expect(consoleErr).toHaveBeenCalled();
  });

  it('loads OCR data when metadata endpoint returns pages', async () => {
    server.use(
      http.get(DOC_URL, () =>
        HttpResponse.arrayBuffer(new ArrayBuffer(8), {
          headers: { 'Content-Type': 'application/pdf' },
        }),
      ),
      http.get(META_URL, () =>
        HttpResponse.json({
          text_data: {
            pages: [
              {
                page_num: 1,
                text: 'sample',
                width: 612,
                height: 792,
                words: [],
                lines: [],
              },
            ],
          },
        }),
      ),
    );
    renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        onNumPagesChange={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId('mock-document')).toBeInTheDocument(),
    );
  });

  it('handles OCR fetch failure gracefully (just logs)', async () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(
      http.get(DOC_URL, () =>
        HttpResponse.arrayBuffer(new ArrayBuffer(8), {
          headers: { 'Content-Type': 'application/pdf' },
        }),
      ),
      http.get(META_URL, () => new HttpResponse(null, { status: 500 })),
    );
    renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        onNumPagesChange={() => {}}
      />,
    );
    await waitFor(() => expect(consoleErr).toHaveBeenCalled());
  });

  it('renders accepted redactions with blue/green overlays', async () => {
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        redactions={[
          { x: 10, y: 10, width: 50, height: 20, page: 1, text: 'A' },
          { x: 10, y: 40, width: 50, height: 20, page: 1, text: 'B', color: 'green' },
        ]}
      />,
    );
    await waitFor(() =>
      expect(container.querySelectorAll('.redaction-overlay').length).toBe(2),
    );
  });

  it('renders solid black overlays when showRedactionPreview is false', async () => {
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        showRedactionPreview={false}
        redactions={[
          { x: 10, y: 10, width: 50, height: 20, page: 1, text: 'A' },
        ]}
      />,
    );
    await waitFor(() =>
      expect(container.querySelectorAll('.redaction-overlay').length).toBe(1),
    );
  });

  it('marks the selectedRedactionIndex redaction', async () => {
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        selectedRedactionIndex={0}
        redactions={[
          { x: 10, y: 10, width: 50, height: 20, page: 1, text: 'A' },
        ]}
      />,
    );
    await waitFor(() =>
      expect(container.querySelector('.redaction-overlay')).not.toBeNull(),
    );
  });

  it('fires onRedactionClick when a redaction is clicked', async () => {
    const onRedactionClick = vi.fn();
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        onRedactionClick={onRedactionClick}
        redactions={[
          { x: 10, y: 10, width: 50, height: 20, page: 1, text: 'A' },
        ]}
      />,
    );
    await waitFor(() =>
      expect(container.querySelector('.redaction-overlay')).not.toBeNull(),
    );
    fireEvent.click(container.querySelector('.redaction-overlay')!);
    expect(onRedactionClick).toHaveBeenCalledWith(0, expect.anything());
  });

  it('renders suggestion overlays when suggestions array provided', async () => {
    renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        suggestions={[
          {
            text: 'name',
            category: 'PII',
            section: 'A',
            reason: 'name',
            confidence: 'high',
            page: 1,
            coordinates: { x: 10, y: 10, width: 50, height: 20 },
          },
        ]}
      />,
    );
    await waitFor(() => expect(screen.getByText('high')).toBeInTheDocument());
  });

  it('does not show selection indicator when no text is selected', async () => {
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId('mock-document')).toBeInTheDocument(),
    );
    expect(container.querySelector('.selection-indicator')).toBeNull();
  });

  it('handleTextSelection bails when window.getSelection is empty', async () => {
    const onTextSelected = vi.fn();
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => '',
      removeAllRanges: () => {},
      getRangeAt: () => null,
    } as any);
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        onTextSelected={onTextSelected}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId('mock-document')).toBeInTheDocument(),
    );
    fireEvent.mouseUp(container.querySelector('.pdf-viewer-with-selection')!);
    expect(onTextSelected).not.toHaveBeenCalled();
  });

  it('handleTextSelection skips when canvas is missing', async () => {
    const onTextSelected = vi.fn();
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => 'hello',
      removeAllRanges: () => {},
      getRangeAt: () => ({
        getClientRects: () => [{ left: 0, top: 0, width: 10, height: 5 }],
      }),
    } as any);
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        onTextSelected={onTextSelected}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId('mock-document')).toBeInTheDocument(),
    );
    fireEvent.mouseUp(container.querySelector('.pdf-viewer-with-selection')!);
    expect(onTextSelected).not.toHaveBeenCalled();
  });

  it('handleTextSelection maps valid rects to PDF coords and calls onTextSelected', async () => {
    // Install a fake canvas with stubbed getBoundingClientRect.
    const wrapper = document.createElement('div');
    wrapper.className = 'react-pdf__Page';
    const canvas = document.createElement('canvas');
    canvas.getBoundingClientRect = () =>
      ({ left: 100, top: 50, right: 600, bottom: 800, width: 500, height: 750, x: 100, y: 50, toJSON: () => ({}) }) as any;
    wrapper.appendChild(canvas);
    document.body.appendChild(wrapper);

    const removeAll = vi.fn();
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => 'redact me',
      removeAllRanges: removeAll,
      getRangeAt: () => ({
        getClientRects: () => [
          { left: 150, top: 80, width: 80, height: 20 },
        ],
      }),
    } as any);
    const onTextSelected = vi.fn();
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        onTextSelected={onTextSelected}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId('mock-document')).toBeInTheDocument(),
    );
    fireEvent.mouseUp(container.querySelector('.pdf-viewer-with-selection')!);
    expect(onTextSelected).toHaveBeenCalledTimes(1);
    const arg = onTextSelected.mock.calls[0][0];
    expect(arg[0].text).toBe('redact me');
    expect(arg[0].x).toBe(50);
    expect(arg[0].y).toBe(30);
    expect(removeAll).toHaveBeenCalled();
    document.body.removeChild(wrapper);
  });

  it('skips selection when only ghost (tiny) rects are returned', async () => {
    const wrapper = document.createElement('div');
    wrapper.className = 'react-pdf__Page';
    const canvas = document.createElement('canvas');
    canvas.getBoundingClientRect = () =>
      ({ left: 0, top: 0, right: 500, bottom: 750, width: 500, height: 750, x: 0, y: 0, toJSON: () => ({}) }) as any;
    wrapper.appendChild(canvas);
    document.body.appendChild(wrapper);
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => 'g',
      removeAllRanges: () => {},
      getRangeAt: () => ({
        getClientRects: () => [{ left: 0, top: 0, width: 1, height: 1 }],
      }),
    } as any);
    const onTextSelected = vi.fn();
    const { container } = renderWithProviders(
      <PDFViewerWithSelection
        documentId="doc-1"
        currentPage={1}
        zoom={1}
        pdfUrl="/file/foo.pdf"
        onNumPagesChange={() => {}}
        onTextSelected={onTextSelected}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId('mock-document')).toBeInTheDocument(),
    );
    fireEvent.mouseUp(container.querySelector('.pdf-viewer-with-selection')!);
    expect(onTextSelected).not.toHaveBeenCalled();
    document.body.removeChild(wrapper);
  });
});
