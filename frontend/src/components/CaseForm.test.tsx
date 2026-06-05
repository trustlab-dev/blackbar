import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import CaseForm from './CaseForm';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return { ...actual, useNavigate: () => mockNavigate };
});

beforeEach(() => {
  mockNavigate.mockReset();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CaseForm — initial render', () => {
  it('renders required title field and Create button (disabled until title)', () => {
    renderWithProviders(<CaseForm />);
    expect(screen.getByLabelText(/title/i)).toBeRequired();
    expect(screen.getByRole('button', { name: /create case/i })).toBeDisabled();
  });

  it('renders Status and Priority selects with defaults', () => {
    renderWithProviders(<CaseForm />);
    expect(screen.getByText(/^New$/)).toBeInTheDocument();
    expect(screen.getByText(/^Medium$/i)).toBeInTheDocument();
  });
});

describe('CaseForm — tag management', () => {
  it('adds a tag and clears the input', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CaseForm />);
    const tagInput = screen.getByLabelText(/add tag/i);
    await user.type(tagInput, 'urgent');
    await user.click(screen.getByRole('button', { name: /^add$/i }));

    expect(screen.getByText('urgent')).toBeInTheDocument();
    expect(tagInput).toHaveValue('');
  });

  it('does not add a duplicate tag', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CaseForm />);
    const tagInput = screen.getByLabelText(/add tag/i);
    await user.type(tagInput, 'urgent');
    await user.click(screen.getByRole('button', { name: /^add$/i }));
    await user.type(tagInput, 'urgent');
    await user.click(screen.getByRole('button', { name: /^add$/i }));

    // Only one chip rendered
    expect(screen.getAllByText('urgent')).toHaveLength(1);
  });

  it('removes a tag when its delete icon is clicked', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CaseForm />);
    const tagInput = screen.getByLabelText(/add tag/i);
    await user.type(tagInput, 'urgent');
    await user.click(screen.getByRole('button', { name: /^add$/i }));

    expect(screen.getByText('urgent')).toBeInTheDocument();
    // Chip delete icon has role=button via MUI's Cancel svg; use test-id approach
    const deleteIcon = document.querySelector('.MuiChip-deleteIcon');
    expect(deleteIcon).not.toBeNull();
    await user.click(deleteIcon as Element);
    expect(screen.queryByText('urgent')).not.toBeInTheDocument();
  });

  it('disables the Add button until tag text is non-blank', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CaseForm />);
    const addBtn = screen.getByRole('button', { name: /^add$/i });
    expect(addBtn).toBeDisabled();
    await user.type(screen.getByLabelText(/add tag/i), '   ');
    expect(addBtn).toBeDisabled();
    await user.type(screen.getByLabelText(/add tag/i), 'x');
    expect(addBtn).toBeEnabled();
  });
});

describe('CaseForm — submission', () => {
  it('shows success message and navigates after successful create', async () => {
    server.use(
      http.post('/api/v1/cases/', () =>
        HttpResponse.json({ id: 'case-99', title: 'Hello' }),
      ),
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<CaseForm />);

    await user.type(screen.getByLabelText(/title/i), 'Hello');
    await user.click(screen.getByRole('button', { name: /create case/i }));

    await waitFor(() =>
      expect(screen.getByText(/case created successfully/i)).toBeInTheDocument(),
    );

    await vi.advanceTimersByTimeAsync(1600);
    expect(mockNavigate).toHaveBeenCalledWith('/cases/case-99');
    vi.useRealTimers();
  });

  it('shows an error alert when the backend rejects', async () => {
    server.use(
      http.post('/api/v1/cases/', () => new HttpResponse(null, { status: 500 })),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseForm />);

    await user.type(screen.getByLabelText(/title/i), 'Hello');
    await user.click(screen.getByRole('button', { name: /create case/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/request failed with status code 500|an error occurred while creating the case/i),
      ).toBeInTheDocument(),
    );
  });
});

describe('CaseForm — title validation', () => {
  it('shows "Title is required" if the form submits with empty title', async () => {
    // The submit button is disabled when title is empty, so trigger submit via
    // the form element directly using fireEvent.submit.
    const { container } = renderWithProviders(<CaseForm />);
    const form = container.querySelector('form');
    expect(form).not.toBeNull();
    form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await waitFor(() =>
      expect(screen.getByText(/title is required/i)).toBeInTheDocument(),
    );
  });
});

describe('CaseForm — Cancel', () => {
  it('navigates to /cases on Cancel', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CaseForm />);
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/cases');
  });
});
