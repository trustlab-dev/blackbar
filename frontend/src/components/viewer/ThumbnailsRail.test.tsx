// frontend/src/components/viewer/ThumbnailsRail.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Mock react-pdf BEFORE importing the component so the GlobalWorkerOptions line runs harmlessly.
const mockGetDocument = vi.fn();
vi.mock('react-pdf', () => ({
  pdfjs: {
    GlobalWorkerOptions: { workerSrc: '' },
    getDocument: (...args: any[]) => mockGetDocument(...args),
  },
}));

import { renderWithProviders, screen } from '../../test-utils/render';
import ThumbnailsRail from './ThumbnailsRail';

function makePdfMock(numPages: number, opts: { fail?: boolean; failName?: string } = {}) {
  const pdf = {
    getPage: vi.fn().mockImplementation((pageNum: number) => {
      if (opts.fail) {
        return Promise.reject(Object.assign(new Error('boom'), { name: opts.failName ?? 'Error' }));
      }
      return Promise.resolve({
        getViewport: () => ({ width: 50, height: 70 }),
        render: () => ({ promise: Promise.resolve() }),
      });
    }),
    destroy: vi.fn(),
  };
  const loadingTask = { promise: Promise.resolve(pdf), destroy: vi.fn() };
  mockGetDocument.mockReturnValue(loadingTask);
  return { pdf, loadingTask };
}

beforeEach(() => {
  mockGetDocument.mockReset();
  // jsdom's HTMLCanvasElement.getContext returns null by default; stub it.
  // Provide a minimal 2d context object so the render path runs.
  HTMLCanvasElement.prototype.getContext = (() => ({}) as any) as any;
  HTMLCanvasElement.prototype.toDataURL = () => 'data:image/png;base64,FAKE';
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ThumbnailsRail', () => {
  it('renders one thumbnail box per page', () => {
    mockGetDocument.mockReturnValue({ promise: new Promise(() => {}), destroy: vi.fn() });
    renderWithProviders(
      <ThumbnailsRail
        documentId="doc-1"
        numPages={3}
        currentPage={1}
        onPageClick={() => {}}
        pdfUrl={null}
      />,
    );
    // Placeholder labels (page number) render twice per thumbnail (inside + label). 3 pages.
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2').length).toBeGreaterThan(0);
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
  });

  it('skips PDF loading when pdfUrl is null', () => {
    renderWithProviders(
      <ThumbnailsRail
        documentId="doc-1"
        numPages={2}
        currentPage={1}
        onPageClick={() => {}}
        pdfUrl={null}
      />,
    );
    expect(mockGetDocument).not.toHaveBeenCalled();
  });

  it('marks the current page thumbnail with the active class', () => {
    mockGetDocument.mockReturnValue({ promise: new Promise(() => {}), destroy: vi.fn() });
    const { container } = renderWithProviders(
      <ThumbnailsRail
        documentId="doc-1"
        numPages={2}
        currentPage={2}
        onPageClick={() => {}}
        pdfUrl={null}
      />,
    );
    const active = container.querySelectorAll('.thumbnail.active');
    expect(active.length).toBe(1);
  });

  it('calls onPageClick with the page number when a thumbnail is clicked', async () => {
    mockGetDocument.mockReturnValue({ promise: new Promise(() => {}), destroy: vi.fn() });
    const onPageClick = vi.fn();
    const { container } = renderWithProviders(
      <ThumbnailsRail
        documentId="doc-1"
        numPages={2}
        currentPage={1}
        onPageClick={onPageClick}
        pdfUrl={null}
      />,
    );
    const thumbs = container.querySelectorAll('.thumbnail');
    await userEvent.click(thumbs[1]);
    expect(onPageClick).toHaveBeenCalledWith(2);
  });

  it('renders generated thumbnail images when pdfjs returns pages', async () => {
    makePdfMock(2);
    const { container } = renderWithProviders(
      <ThumbnailsRail
        documentId="doc-1"
        numPages={2}
        currentPage={1}
        onPageClick={() => {}}
        pdfUrl="/tmp/foo.pdf"
      />,
    );
    await waitFor(() => {
      const imgs = container.querySelectorAll('img');
      expect(imgs.length).toBe(2);
      expect(imgs[0].getAttribute('src')).toContain('data:image/png');
    });
  });

  it('swallows MissingPDFException without logging', async () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {});
    const loadingTask = {
      promise: Promise.reject(Object.assign(new Error('missing'), { name: 'MissingPDFException' })),
      destroy: vi.fn(),
    };
    mockGetDocument.mockReturnValue(loadingTask);
    renderWithProviders(
      <ThumbnailsRail
        documentId="doc-1"
        numPages={1}
        currentPage={1}
        onPageClick={() => {}}
        pdfUrl="/tmp/missing.pdf"
      />,
    );
    await new Promise(r => setTimeout(r, 50));
    expect(consoleErr).not.toHaveBeenCalled();
  });

  it('logs other PDF load errors to console.error', async () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {});
    const loadingTask = {
      promise: Promise.reject(new Error('boom')),
      destroy: vi.fn(),
    };
    mockGetDocument.mockReturnValue(loadingTask);
    renderWithProviders(
      <ThumbnailsRail
        documentId="doc-1"
        numPages={1}
        currentPage={1}
        onPageClick={() => {}}
        pdfUrl="/tmp/broken.pdf"
      />,
    );
    await waitFor(() => expect(consoleErr).toHaveBeenCalled());
  });

  it('runs cleanup function (cancels load and destroys task) on unmount', async () => {
    const destroy = vi.fn();
    const loadingTask = { promise: new Promise(() => {}), destroy };
    mockGetDocument.mockReturnValue(loadingTask);
    const { unmount } = renderWithProviders(
      <ThumbnailsRail
        documentId="doc-1"
        numPages={1}
        currentPage={1}
        onPageClick={() => {}}
        pdfUrl="/tmp/x.pdf"
      />,
    );
    unmount();
    expect(destroy).toHaveBeenCalled();
  });
});
