import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import UserPicker from './UserPicker';

const sampleUsers = [
  { id: 'u1', username: 'alice', email: 'alice@example.com', role: 'analyst' },
  { id: 'u2', username: 'bob', email: 'bob@example.com', role: 'admin' },
];

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('UserPicker — initial load', () => {
  it('renders the default label and helper text', async () => {
    server.use(
      http.get('/api/v1/auth/users/search', () =>
        HttpResponse.json({ users: sampleUsers }),
      ),
    );
    renderWithProviders(<UserPicker value="" onChange={vi.fn()} />);
    expect(await screen.findByLabelText(/select user/i)).toBeInTheDocument();
    expect(screen.getByText(/type to search by name or email/i)).toBeInTheDocument();
  });

  it('honors custom label, helperText, and required props', () => {
    server.use(
      http.get('/api/v1/auth/users/search', () => HttpResponse.json({ users: [] })),
    );
    renderWithProviders(
      <UserPicker
        value=""
        onChange={vi.fn()}
        label="Assignee"
        helperText="Pick one"
        required
      />,
    );
    expect(screen.getByLabelText(/assignee/i)).toBeInTheDocument();
    expect(screen.getByText(/pick one/i)).toBeInTheDocument();
  });

  it('handles fetch errors silently (no thrown error to user)', async () => {
    server.use(
      http.get(
        '/api/v1/auth/users/search',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderWithProviders(<UserPicker value="" onChange={vi.fn()} />);
    expect(await screen.findByLabelText(/select user/i)).toBeInTheDocument();
    // Open the dropdown — "No users found" branch is not hit because input
    // is empty; "Type to search..." is shown instead.
    await waitFor(() => expect(console.error).toHaveBeenCalled());
  });
});

describe('UserPicker — interactions', () => {
  it('shows search results in the dropdown after typing', async () => {
    server.use(
      http.get('/api/v1/auth/users/search', () =>
        HttpResponse.json({ users: sampleUsers }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserPicker value="" onChange={vi.fn()} />);

    const input = await screen.findByLabelText(/select user/i);
    await user.click(input);
    await user.type(input, 'al');

    await waitFor(() =>
      expect(screen.getByText('alice@example.com')).toBeInTheDocument(),
    );
  });

  it('calls onChange with the selected user id', async () => {
    server.use(
      http.get('/api/v1/auth/users/search', () =>
        HttpResponse.json({ users: sampleUsers }),
      ),
    );
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<UserPicker value="" onChange={onChange} />);

    const input = await screen.findByLabelText(/select user/i);
    await user.click(input);
    await waitFor(() =>
      expect(screen.getByText('alice@example.com')).toBeInTheDocument(),
    );
    await user.click(screen.getByText('alice@example.com'));

    expect(onChange).toHaveBeenLastCalledWith('u1');
  });

  it('calls onChange with empty string when selection is cleared', async () => {
    server.use(
      http.get('/api/v1/auth/users/search', () =>
        HttpResponse.json({ users: sampleUsers }),
      ),
    );
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<UserPicker value="" onChange={onChange} />);

    const input = await screen.findByLabelText(/select user/i);
    await user.click(input);
    await waitFor(() =>
      expect(screen.getByText('alice@example.com')).toBeInTheDocument(),
    );
    await user.click(screen.getByText('alice@example.com'));
    expect(onChange).toHaveBeenLastCalledWith('u1');

    // MUI Autocomplete renders a Clear icon button that appears on hover/focus.
    // Use title attribute fallback.
    const clearButton = screen.getByTitle(/clear/i);
    await user.click(clearButton);
    expect(onChange).toHaveBeenLastCalledWith('');
  });

  it('shows "Type to search..." sentinel when input is short', async () => {
    server.use(
      http.get('/api/v1/auth/users/search', () =>
        HttpResponse.json({ users: [] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserPicker value="" onChange={vi.fn()} />);

    const input = await screen.findByLabelText(/select user/i);
    await user.click(input);
    await user.type(input, 'a');
    expect(screen.getByText(/type to search\.\.\./i)).toBeInTheDocument();
  });

  it('shows "No users found" sentinel for non-matching ≥2-char query', async () => {
    server.use(
      http.get('/api/v1/auth/users/search', () =>
        HttpResponse.json({ users: [] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserPicker value="" onChange={vi.fn()} />);

    const input = await screen.findByLabelText(/select user/i);
    await user.click(input);
    await user.type(input, 'zz');
    await waitFor(() =>
      expect(screen.getByText(/no users found/i)).toBeInTheDocument(),
    );
  });
});

describe('UserPicker — missing response.data.users', () => {
  it('treats missing users[] as empty array', async () => {
    server.use(
      http.get('/api/v1/auth/users/search', () => HttpResponse.json({})),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserPicker value="" onChange={vi.fn()} />);

    const input = await screen.findByLabelText(/select user/i);
    await user.click(input);
    expect(screen.getByText(/type to search\.\.\./i)).toBeInTheDocument();
  });
});
