// frontend/src/components/viewer/DrawRedactionTool.test.tsx
import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen } from '../../test-utils/render';
import DrawRedactionTool from './DrawRedactionTool';

function installFakeCanvas() {
  const canvas = document.createElement('canvas');
  canvas.className = 'react-pdf__Page__canvas';
  // The component queries `.react-pdf__Page canvas`. Create a wrapper.
  const wrapper = document.createElement('div');
  wrapper.className = 'react-pdf__Page';
  wrapper.appendChild(canvas);
  document.body.appendChild(wrapper);
  // Stub getBoundingClientRect.
  canvas.getBoundingClientRect = () =>
    ({ left: 100, top: 50, right: 600, bottom: 800, width: 500, height: 750, x: 100, y: 50, toJSON: () => ({}) }) as any;
  return { wrapper, canvas };
}

afterEach(() => {
  document.querySelectorAll('.react-pdf__Page').forEach(el => el.remove());
  vi.restoreAllMocks();
});

describe('DrawRedactionTool', () => {
  it('renders nothing when disabled', () => {
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={false}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('shows the info banner when enabled', () => {
    renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={() => {}}
      />,
    );
    expect(screen.getByText(/Draw redaction enabled/)).toBeInTheDocument();
  });

  it('fires onDisable when the close button is clicked', async () => {
    const onDisable = vi.fn();
    renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={onDisable}
      />,
    );
    await userEvent.click(screen.getByLabelText('close'));
    expect(onDisable).toHaveBeenCalledTimes(1);
  });

  it('fires onDisable on Escape key', () => {
    const onDisable = vi.fn();
    renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={onDisable}
      />,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onDisable).toHaveBeenCalledTimes(1);
  });

  it('ignores Escape when not enabled', () => {
    const onDisable = vi.fn();
    renderWithProviders(
      <DrawRedactionTool
        enabled={false}
        zoom={1}
        onRedactionCreated={() => {}}
        onDisable={onDisable}
      />,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onDisable).not.toHaveBeenCalled();
  });

  it('does nothing on mousedown when canvas is missing', () => {
    // No canvas installed.
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    fireEvent.mouseDown(overlay, { clientX: 150, clientY: 100 });
    fireEvent.mouseUp(overlay);
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('draws a rectangle and calls onRedactionCreated with PDF-space coords', () => {
    installFakeCanvas();
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    // Start at canvas-relative (50, 30) — clientX=150 - canvasLeft=100 = 50.
    fireEvent.mouseDown(overlay, { clientX: 150, clientY: 80 });
    fireEvent.mouseMove(overlay, { clientX: 250, clientY: 180 });
    fireEvent.mouseUp(overlay);
    expect(onCreated).toHaveBeenCalledTimes(1);
    expect(onCreated.mock.calls[0][0]).toMatchObject({
      x: 50,
      y: 30,
      width: 100,
      height: 100,
      text: '[Drawn Redaction]',
      snappedWords: [],
    });
  });

  it('handles reverse-direction drags (top-left correction)', () => {
    installFakeCanvas();
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    // Drag from bottom-right (200, 200) to top-left (110, 60). PDF coords: (100, 150) -> (10, 10)
    fireEvent.mouseDown(overlay, { clientX: 200, clientY: 200 });
    fireEvent.mouseMove(overlay, { clientX: 110, clientY: 60 });
    fireEvent.mouseUp(overlay);
    expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({
        x: 10,
        y: 10,
        width: 90,
        height: 140,
      }),
    );
  });

  it('does not emit a redaction if the drag is too small', () => {
    installFakeCanvas();
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    fireEvent.mouseDown(overlay, { clientX: 150, clientY: 80 });
    fireEvent.mouseMove(overlay, { clientX: 152, clientY: 82 }); // 2x2 — too small
    fireEvent.mouseUp(overlay);
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('handleMouseMove without an active drag is a no-op', () => {
    installFakeCanvas();
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    fireEvent.mouseMove(overlay, { clientX: 150, clientY: 80 });
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('handleMouseUp without an active rectangle is a no-op', () => {
    installFakeCanvas();
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    fireEvent.mouseUp(overlay);
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('handleMouseMove during draw without canvas is a no-op (clears nothing)', () => {
    const { wrapper } = installFakeCanvas();
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    fireEvent.mouseDown(overlay, { clientX: 150, clientY: 80 });
    // Remove canvas mid-drag; handleMouseMove should bail.
    wrapper.remove();
    fireEvent.mouseMove(overlay, { clientX: 200, clientY: 130 });
    // Without a finish via canvas-based geometry, just confirm we didn't crash.
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('disabling the tool clears any in-progress draw state', () => {
    installFakeCanvas();
    const onCreated = vi.fn();
    const { container, rerender } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    fireEvent.mouseDown(overlay, { clientX: 150, clientY: 80 });
    fireEvent.mouseMove(overlay, { clientX: 200, clientY: 130 });
    rerender(
      <DrawRedactionTool
        enabled={false}
        zoom={1}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    expect(container.querySelector('.draw-redaction-overlay')).toBeNull();
  });

  it('scales coordinates with zoom (zoom=2 halves PDF coordinates)', () => {
    installFakeCanvas();
    const onCreated = vi.fn();
    const { container } = renderWithProviders(
      <DrawRedactionTool
        enabled={true}
        zoom={2}
        onRedactionCreated={onCreated}
        onDisable={() => {}}
      />,
    );
    const overlay = container.querySelector('.draw-redaction-overlay')!;
    // Screen drag of 100x100 at zoom=2 → PDF 50x50.
    fireEvent.mouseDown(overlay, { clientX: 150, clientY: 80 });
    fireEvent.mouseMove(overlay, { clientX: 250, clientY: 180 });
    fireEvent.mouseUp(overlay);
    expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({ width: 50, height: 50 }),
    );
  });
});
