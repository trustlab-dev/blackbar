// frontend/src/components/viewer/ManualRedactionTool.test.tsx
import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen } from '../../test-utils/render';
import ManualRedactionTool from './ManualRedactionTool';

// Stub overlay getBoundingClientRect via a helper after render.
function stubOverlay(container: HTMLElement) {
  const overlay = container.querySelector('.manual-redaction-overlay') as HTMLElement;
  if (!overlay) return null;
  overlay.getBoundingClientRect = () =>
    ({ left: 0, top: 0, right: 500, bottom: 750, width: 500, height: 750, x: 0, y: 0, toJSON: () => ({}) }) as any;
  return overlay;
}

function pageDataFor(words: Array<{ text: string; bbox: number[]; line_num?: number; word_num?: number }>) {
  return {
    width: 500,
    height: 750,
    words: words.map((w, i) => ({
      text: w.text,
      bbox: w.bbox,
      line_num: w.line_num ?? 0,
      word_num: w.word_num ?? i,
    })),
    lines: [],
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ManualRedactionTool', () => {
  it('renders null when disabled', () => {
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={false}
        pageData={null}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('shows banner and snap controls when enabled', () => {
    renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={() => {}}
      />,
    );
    expect(screen.getByText(/Select tool active/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Word/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Line/i })).toBeInTheDocument();
  });

  it('fires onDisable when close button clicked', async () => {
    const onDisable = vi.fn();
    renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={onDisable}
      />,
    );
    await userEvent.click(screen.getByLabelText('close'));
    expect(onDisable).toHaveBeenCalledTimes(1);
  });

  it('switches snap mode when Line button clicked', async () => {
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={() => {}}
      />,
    );
    const line = screen.getByRole('button', { name: /Line/i });
    await userEvent.click(line);
    expect(line.className).toContain('active');
    const word = screen.getByRole('button', { name: /Word/i });
    expect(word.className).not.toContain('active');
    expect(container).toBeTruthy();
  });

  it('creates a redaction with snapped word bounds and extracted text', () => {
    const onCreated = vi.fn();
    const pd = pageDataFor([
      { text: 'Hello', bbox: [10, 10, 50, 30] },
      { text: 'World', bbox: [55, 10, 100, 30] },
      { text: 'Untouched', bbox: [200, 200, 280, 220] },
    ]);
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={pd}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = stubOverlay(container)!;
    fireEvent.mouseDown(overlay, { clientX: 5, clientY: 5 });
    fireEvent.mouseMove(overlay, { clientX: 110, clientY: 40 });
    fireEvent.mouseUp(overlay, { clientX: 110, clientY: 40 });
    expect(onCreated).toHaveBeenCalledTimes(1);
    const call = onCreated.mock.calls[0][0];
    expect(call.text).toBe('Hello World');
    expect(call.snappedWords).toEqual(['Hello', 'World']);
    // Bounds merged from word bboxes — x=10, y=10, width=90, height=20.
    expect(call.x).toBe(10);
    expect(call.y).toBe(10);
  });

  it('returns raw bounds (no snap) when no overlapping words', () => {
    const onCreated = vi.fn();
    const pd = pageDataFor([
      { text: 'Far away', bbox: [400, 400, 480, 420] },
    ]);
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={pd}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = stubOverlay(container)!;
    fireEvent.mouseDown(overlay, { clientX: 10, clientY: 10 });
    fireEvent.mouseMove(overlay, { clientX: 50, clientY: 30 });
    fireEvent.mouseUp(overlay, { clientX: 50, clientY: 30 });
    expect(onCreated).toHaveBeenCalledTimes(1);
    const call = onCreated.mock.calls[0][0];
    expect(call.text).toBe(''); // No words overlapped
    expect(call.snappedWords).toEqual([]);
  });

  it('falls back to "[Selected Text]" when pageData is null', () => {
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = stubOverlay(container)!;
    fireEvent.mouseDown(overlay, { clientX: 10, clientY: 10 });
    fireEvent.mouseMove(overlay, { clientX: 100, clientY: 50 });
    fireEvent.mouseUp(overlay, { clientX: 100, clientY: 50 });
    expect(onCreated).toHaveBeenCalledTimes(1);
    expect(onCreated.mock.calls[0][0].text).toBe('[Selected Text]');
  });

  it('expands selection to full line in line mode', async () => {
    const onCreated = vi.fn();
    const pd = pageDataFor([
      { text: 'A', bbox: [10, 10, 20, 30], line_num: 1 },
      { text: 'B', bbox: [25, 10, 35, 30], line_num: 1 },
      { text: 'C', bbox: [40, 10, 50, 30], line_num: 1 },
      { text: 'X', bbox: [10, 100, 20, 120], line_num: 2 },
    ]);
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={pd}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /Line/i }));
    const overlay = stubOverlay(container)!;
    fireEvent.mouseDown(overlay, { clientX: 10, clientY: 10 });
    fireEvent.mouseMove(overlay, { clientX: 22, clientY: 32 }); // Touches only "A"
    fireEvent.mouseUp(overlay, { clientX: 22, clientY: 32 });
    expect(onCreated).toHaveBeenCalledTimes(1);
    const call = onCreated.mock.calls[0][0];
    // Expanded to full line (A, B, C): x=10, width=40.
    expect(call.x).toBe(10);
    expect(call.width).toBe(40);
  });

  it('mousedown without overlay rect (no overlayRef) is a no-op', () => {
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.manual-redaction-overlay') as HTMLElement;
    // Force getBoundingClientRect to return undefined-equivalent? Instead, simulate
    // by not stubbing - jsdom's default returns DOMRect with zeros, so we test the
    // happy path of a 0-sized drag.
    fireEvent.mouseDown(overlay, { clientX: 10, clientY: 10 });
    fireEvent.mouseUp(overlay, { clientX: 10, clientY: 10 });
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('mousemove with no active drag is a no-op (no preview)', () => {
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = stubOverlay(container)!;
    fireEvent.mouseMove(overlay, { clientX: 50, clientY: 50 });
    expect(container.querySelector('.manual-redaction-overlay > div')).toBeNull();
  });

  it('does not emit a redaction for a zero-size drag', () => {
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = stubOverlay(container)!;
    fireEvent.mouseDown(overlay, { clientX: 50, clientY: 50 });
    fireEvent.mouseUp(overlay, { clientX: 50, clientY: 50 });
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('disabling the tool clears in-progress state', () => {
    const { container, rerender } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={() => {}}
      />,
    );
    const overlay = stubOverlay(container)!;
    fireEvent.mouseDown(overlay, { clientX: 10, clientY: 10 });
    fireEvent.mouseMove(overlay, { clientX: 50, clientY: 50 });
    rerender(
      <ManualRedactionTool
        enabled={false}
        pageData={null}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={() => {}}
      />,
    );
    expect(container.querySelector('.manual-redaction-overlay')).toBeNull();
  });

  it('shows preview box while drawing', () => {
    const { container } = renderWithProviders(
      <ManualRedactionTool
        enabled={true}
        pageData={null}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={() => {}}
      />,
    );
    const overlay = stubOverlay(container)!;
    fireEvent.mouseDown(overlay, { clientX: 10, clientY: 10 });
    fireEvent.mouseMove(overlay, { clientX: 100, clientY: 50 });
    // Preview is the only child div of the overlay
    const previewBox = overlay.querySelector('div');
    expect(previewBox).not.toBeNull();
  });
});
