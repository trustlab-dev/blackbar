// frontend/src/components/viewer/SuggestionOverlayInline.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen } from '../../test-utils/render';
import SuggestionOverlayInline from './SuggestionOverlayInline';

function makeSuggestion(overrides: Record<string, any> = {}) {
  return {
    text: 'sample',
    category: 'PII',
    section: 'A',
    reason: 'name',
    confidence: 'high',
    page: 1,
    coordinates: { x: 5, y: 10, width: 50, height: 25 },
    ...overrides,
  };
}

describe('SuggestionOverlayInline', () => {
  it('renders nothing when coordinates are missing', () => {
    const { container } = renderWithProviders(
      <SuggestionOverlayInline
        suggestion={makeSuggestion({ coordinates: undefined }) as any}
        zoom={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders confidence label with provided value', () => {
    renderWithProviders(
      <SuggestionOverlayInline
        suggestion={makeSuggestion({ confidence: 'high' })}
        zoom={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText('high')).toBeInTheDocument();
  });

  it('falls back to "medium" label when confidence is empty', () => {
    renderWithProviders(
      <SuggestionOverlayInline
        suggestion={makeSuggestion({ confidence: '' })}
        zoom={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText('medium')).toBeInTheDocument();
  });

  it('does not show accept/reject by default', () => {
    renderWithProviders(
      <SuggestionOverlayInline
        suggestion={makeSuggestion()}
        zoom={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.queryByText(/Accept/)).toBeNull();
    expect(screen.queryByText(/Reject/)).toBeNull();
  });

  it('shows accept/reject buttons on mouseEnter, hides on mouseLeave', () => {
    const { container } = renderWithProviders(
      <SuggestionOverlayInline
        suggestion={makeSuggestion()}
        zoom={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    const overlay = container.firstChild as HTMLElement;
    fireEvent.mouseEnter(overlay);
    expect(screen.getByText(/Accept/)).toBeInTheDocument();
    expect(screen.getByText(/Reject/)).toBeInTheDocument();
    fireEvent.mouseLeave(overlay);
    expect(screen.queryByText(/Accept/)).toBeNull();
  });

  it('invokes onAccept with suggestion when Accept clicked', async () => {
    const onAccept = vi.fn();
    const suggestion = makeSuggestion();
    const { container } = renderWithProviders(
      <SuggestionOverlayInline
        suggestion={suggestion}
        zoom={1}
        onAccept={onAccept}
        onReject={() => {}}
      />,
    );
    fireEvent.mouseEnter(container.firstChild as HTMLElement);
    await userEvent.click(screen.getByText(/Accept/));
    expect(onAccept).toHaveBeenCalledWith(suggestion);
  });

  it('invokes onReject with suggestion when Reject clicked', async () => {
    const onReject = vi.fn();
    const suggestion = makeSuggestion();
    const { container } = renderWithProviders(
      <SuggestionOverlayInline
        suggestion={suggestion}
        zoom={1}
        onAccept={() => {}}
        onReject={onReject}
      />,
    );
    fireEvent.mouseEnter(container.firstChild as HTMLElement);
    await userEvent.click(screen.getByText(/Reject/));
    expect(onReject).toHaveBeenCalledWith(suggestion);
  });

  it.each([
    ['high', '#4caf50'],
    ['medium', '#ff9800'],
    ['low', '#9e9e9e'],
    ['weird', '#9e9e9e'],
  ])('renders %s confidence label', (label) => {
    renderWithProviders(
      <SuggestionOverlayInline
        suggestion={makeSuggestion({ confidence: label })}
        zoom={1}
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
