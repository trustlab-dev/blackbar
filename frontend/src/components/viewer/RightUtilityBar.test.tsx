// frontend/src/components/viewer/RightUtilityBar.test.tsx
import { describe, it, expect, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen } from '../../test-utils/render';
import RightUtilityBar from './RightUtilityBar';

function makeProps(overrides: Partial<React.ComponentProps<typeof RightUtilityBar>> = {}) {
  return {
    documentId: 'doc-1',
    showRedactionPreview: false,
    onTogglePreview: vi.fn(),
    onAutoSuggestClick: vi.fn(),
    onHistoryClick: vi.fn(),
    onCommentsClick: vi.fn(),
    ...overrides,
  };
}

describe('RightUtilityBar', () => {
  it('shows "Show" label when preview is hidden', () => {
    const props = makeProps({ showRedactionPreview: false });
    renderWithProviders(<RightUtilityBar {...props} />);
    expect(screen.getByText('Show')).toBeInTheDocument();
  });

  it('shows "Hide" label when preview is visible', () => {
    const props = makeProps({ showRedactionPreview: true });
    renderWithProviders(<RightUtilityBar {...props} />);
    expect(screen.getByText('Hide')).toBeInTheDocument();
  });

  it('renders Auto Suggest, History, Comments labels', () => {
    const props = makeProps();
    renderWithProviders(<RightUtilityBar {...props} />);
    expect(screen.getByText('Auto Suggest')).toBeInTheDocument();
    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByText('Comments')).toBeInTheDocument();
  });

  it('calls onTogglePreview with inverted value when toggled', async () => {
    const onTogglePreview = vi.fn();
    const props = makeProps({ showRedactionPreview: false, onTogglePreview });
    renderWithProviders(<RightUtilityBar {...props} />);
    const buttons = screen.getAllByRole('button');
    await userEvent.click(buttons[0]); // first IconButton is the preview toggle
    expect(onTogglePreview).toHaveBeenCalledWith(true);
  });

  it('calls onTogglePreview with false when currently shown', async () => {
    const onTogglePreview = vi.fn();
    const props = makeProps({ showRedactionPreview: true, onTogglePreview });
    renderWithProviders(<RightUtilityBar {...props} />);
    const buttons = screen.getAllByRole('button');
    await userEvent.click(buttons[0]);
    expect(onTogglePreview).toHaveBeenCalledWith(false);
  });

  it('calls onAutoSuggestClick, onHistoryClick, onCommentsClick', async () => {
    const onAutoSuggestClick = vi.fn();
    const onHistoryClick = vi.fn();
    const onCommentsClick = vi.fn();
    const props = makeProps({ onAutoSuggestClick, onHistoryClick, onCommentsClick });
    renderWithProviders(<RightUtilityBar {...props} />);
    const buttons = screen.getAllByRole('button');
    await userEvent.click(buttons[1]); // Auto Suggest
    await userEvent.click(buttons[2]); // History
    await userEvent.click(buttons[3]); // Comments
    expect(onAutoSuggestClick).toHaveBeenCalledTimes(1);
    expect(onHistoryClick).toHaveBeenCalledTimes(1);
    expect(onCommentsClick).toHaveBeenCalledTimes(1);
  });
});
