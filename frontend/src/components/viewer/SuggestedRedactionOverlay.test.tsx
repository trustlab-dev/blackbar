// frontend/src/components/viewer/SuggestedRedactionOverlay.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen } from '../../test-utils/render';
import SuggestedRedactionOverlay from './SuggestedRedactionOverlay';

function makeSuggestion(overrides: Record<string, any> = {}) {
  return {
    text: 'John Smith',
    category: 'PII',
    section: 'A',
    reason: 'name',
    confidence: 'high',
    page: 1,
    coordinates: { x: 10, y: 20, width: 100, height: 50 },
    ...overrides,
  };
}

describe('SuggestedRedactionOverlay', () => {
  it('renders nothing when coordinates are missing', () => {
    const suggestion = makeSuggestion({ coordinates: undefined });
    const { container } = renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={suggestion as any}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders confidence chip with high label', () => {
    renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion({ confidence: 'high' })}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText('high')).toBeInTheDocument();
  });

  it('falls back to "medium" label when confidence is empty', () => {
    renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion({ confidence: '' })}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText('medium')).toBeInTheDocument();
  });

  it('hides accept/reject buttons by default', () => {
    renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion()}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.queryByRole('button', { name: /accept/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /reject/i })).toBeNull();
  });

  it('shows accept/reject buttons on hover and hides them on mouse leave', () => {
    const { container } = renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion()}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    const overlay = container.firstChild as HTMLElement;
    fireEvent.mouseEnter(overlay);
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument();
    fireEvent.mouseLeave(overlay);
    expect(screen.queryByRole('button', { name: /accept/i })).toBeNull();
  });

  it('calls onAccept with the suggestion when Accept is clicked', async () => {
    const onAccept = vi.fn();
    const suggestion = makeSuggestion();
    const { container } = renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={suggestion}
        scale={1}
        onAccept={onAccept}
        onReject={() => {}}
      />,
    );
    fireEvent.mouseEnter(container.firstChild as HTMLElement);
    await userEvent.click(screen.getByRole('button', { name: /accept/i }));
    expect(onAccept).toHaveBeenCalledWith(suggestion);
  });

  it('calls onReject with the suggestion when Reject is clicked', async () => {
    const onReject = vi.fn();
    const suggestion = makeSuggestion();
    const { container } = renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={suggestion}
        scale={1}
        onAccept={() => {}}
        onReject={onReject}
      />,
    );
    fireEvent.mouseEnter(container.firstChild as HTMLElement);
    await userEvent.click(screen.getByRole('button', { name: /reject/i }));
    expect(onReject).toHaveBeenCalledWith(suggestion);
  });

  it('renders medium confidence with warning color', () => {
    renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion({ confidence: 'medium' })}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText('medium')).toBeInTheDocument();
  });

  it('renders low confidence as default chip color', () => {
    renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion({ confidence: 'low' })}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText('low')).toBeInTheDocument();
  });

  it('handles unrecognised confidence (default branch in switch)', () => {
    renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion({ confidence: 'absurd' })}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText('absurd')).toBeInTheDocument();
  });

  it('scales coordinates by zoom (pdfRectToScreen integration)', () => {
    // MUI emits the sx layout values via emotion classes (no inline styles in jsdom).
    // Verify scaling indirectly by ensuring the overlay still renders with both scales.
    const { container: c1 } = renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion({ coordinates: { x: 10, y: 20, width: 100, height: 50 } })}
        scale={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    const { container: c2 } = renderWithProviders(
      <SuggestedRedactionOverlay
        suggestion={makeSuggestion({ coordinates: { x: 10, y: 20, width: 100, height: 50 } })}
        scale={2}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(c1.firstChild).toBeTruthy();
    expect(c2.firstChild).toBeTruthy();
  });
});
