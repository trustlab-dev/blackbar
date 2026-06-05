import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen } from '../test-utils/render';
import ErrorBoundary from './ErrorBoundary';

vi.mock('../utils/telemetry', () => ({
  captureError: vi.fn(),
}));

function BoomChild(): JSX.Element {
  throw new Error('boom');
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders children when no error occurs', () => {
    renderWithProviders(
      <ErrorBoundary>
        <div data-testid="ok">all good</div>
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('ok')).toBeInTheDocument();
  });

  it('renders the fallback UI when a child throws and calls captureError', async () => {
    const { captureError } = await import('../utils/telemetry');
    renderWithProviders(
      <ErrorBoundary>
        <BoomChild />
      </ErrorBoundary>,
    );

    expect(
      screen.getByRole('heading', { name: /something went wrong/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /refresh page/i })).toBeInTheDocument();
    expect(captureError).toHaveBeenCalledTimes(1);
    expect((captureError as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBeInstanceOf(Error);
  });

  it('shows error details in dev mode', () => {
    renderWithProviders(
      <ErrorBoundary>
        <BoomChild />
      </ErrorBoundary>,
    );
    // import.meta.env.DEV is true under vitest by default
    expect(screen.getByText(/error details/i)).toBeInTheDocument();
    expect(screen.getByText(/error: boom/i)).toBeInTheDocument();
  });

  it('Refresh Page button calls window.location.reload', async () => {
    const reload = vi.fn();
    // jsdom: replace location with a stub
    const originalLocation = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: { ...originalLocation, reload },
    });

    const user = userEvent.setup();
    renderWithProviders(
      <ErrorBoundary>
        <BoomChild />
      </ErrorBoundary>,
    );
    await user.click(screen.getByRole('button', { name: /refresh page/i }));
    expect(reload).toHaveBeenCalledTimes(1);

    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: originalLocation,
    });
  });
});
