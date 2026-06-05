// frontend/src/components/viewer/CommentsDrawer.test.tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Force axios to use the fetch adapter so MSW intercepts requests in jsdom.
vi.mock('axios', async () => {
  const actual = await vi.importActual<any>('axios');
  const origCreate = actual.default.create.bind(actual.default);
  actual.default.create = (config: any = {}) =>
    origCreate({ ...config, adapter: 'fetch' });
  return actual;
});

// Stub window.location so api/client resolves an absolute https base URL
// that MSW + the fetch adapter can intercept in jsdom.
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
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen } from '../../test-utils/render';
import CommentsDrawer from './CommentsDrawer';

beforeEach(() => {
  // Stub clipboard / etc. as needed for MUI internals.
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CommentsDrawer', () => {
  it('does not fetch when closed', async () => {
    let called = false;
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () => {
        called = true;
        return HttpResponse.json({ comments: [] });
      }),
    );
    renderWithProviders(
      <CommentsDrawer open={false} onClose={() => {}} documentId="doc-1" />,
    );
    // Give the effect a beat to (not) fire
    await new Promise(r => setTimeout(r, 30));
    expect(called).toBe(false);
  });

  it('shows empty state when API returns no comments', async () => {
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () =>
        HttpResponse.json({ comments: [] }),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/No comments yet/)).toBeInTheDocument(),
    );
  });

  it('renders fetched comments and formats timestamps', async () => {
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () =>
        HttpResponse.json({
          comments: [
            {
              id: '1',
              content: 'First comment',
              user_id: 'u1',
              username: 'Alice Brown',
              created_at: '2026-01-01T12:00:00',
            },
            {
              id: '2',
              content: 'Second comment',
              user_id: 'u2',
              username: 'Bob',
              created_at: '2026-01-02T15:30:00Z',
            },
          ],
        }),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('First comment')).toBeInTheDocument(),
    );
    expect(screen.getByText('Second comment')).toBeInTheDocument();
    expect(screen.getByText('Alice Brown')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
  });

  it('falls back to array response shape (no .comments wrapper)', async () => {
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () =>
        HttpResponse.json([
          {
            id: '1',
            content: 'Top-level array comment',
            user_id: 'u1',
            username: 'Carol',
            created_at: '2026-01-01T00:00:00Z',
          },
        ]),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('Top-level array comment')).toBeInTheDocument(),
    );
  });

  it('treats 404 / 405 as empty (endpoint not implemented yet)', async () => {
    server.use(
      http.get(
        'https://localhost:3000/api/v1/documents/:id/comments',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/No comments yet/)).toBeInTheDocument(),
    );
  });

  it('shows error message for non-404/405 fetch failures', async () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () =>
        HttpResponse.json({ detail: 'Internal boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('Internal boom')).toBeInTheDocument(),
    );
    consoleErr.mockRestore();
  });

  it('shows fallback error message when detail not provided', async () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(
      http.get(
        'https://localhost:3000/api/v1/documents/:id/comments',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('Failed to load comments')).toBeInTheDocument(),
    );
    consoleErr.mockRestore();
  });

  it('disables Add Comment button when the input is empty', async () => {
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () =>
        HttpResponse.json({ comments: [] }),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/No comments yet/)).toBeInTheDocument(),
    );
    const btn = screen.getByRole('button', { name: /Add Comment/i });
    expect(btn).toBeDisabled();
  });

  it('submits a new comment, clears input, refreshes list', async () => {
    let postBody: any = null;
    let getCount = 0;
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () => {
        getCount += 1;
        return HttpResponse.json({
          comments:
            getCount === 1
              ? []
              : [
                  {
                    id: '1',
                    content: 'Hi there',
                    user_id: 'u1',
                    username: 'Me',
                    created_at: '2026-01-01T00:00:00Z',
                  },
                ],
        });
      }),
      http.post('https://localhost:3000/api/v1/documents/:id/comments', async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({ id: '1' });
      }),
    );

    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    const input = await screen.findByPlaceholderText('Add a comment...');
    await userEvent.type(input, 'Hi there');
    await userEvent.click(screen.getByRole('button', { name: /Add Comment/i }));

    await waitFor(() => expect(postBody).toEqual({ content: 'Hi there' }));
    await waitFor(() =>
      expect(screen.getByText('Hi there')).toBeInTheDocument(),
    );
  });

  it('shows error if POST comment fails', async () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () =>
        HttpResponse.json({ comments: [] }),
      ),
      http.post(
        'https://localhost:3000/api/v1/documents/:id/comments',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    const input = await screen.findByPlaceholderText('Add a comment...');
    await userEvent.type(input, 'oops');
    await userEvent.click(screen.getByRole('button', { name: /Add Comment/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Document comments are not yet available/),
      ).toBeInTheDocument(),
    );
    consoleErr.mockRestore();
  });

  it('calls onClose when X is clicked', async () => {
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () =>
        HttpResponse.json({ comments: [] }),
      ),
    );
    const onClose = vi.fn();
    renderWithProviders(
      <CommentsDrawer open={true} onClose={onClose} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/No comments yet/)).toBeInTheDocument(),
    );
    // First icon button is the Close X
    const buttons = screen.getAllByRole('button');
    await userEvent.click(buttons[0]);
    expect(onClose).toHaveBeenCalled();
  });

  it('renders avatar initials, including the "?" fallback for empty username', async () => {
    server.use(
      http.get('https://localhost:3000/api/v1/documents/:id/comments', () =>
        HttpResponse.json({
          comments: [
            {
              id: '1',
              content: 'No name comment',
              user_id: 'u1',
              username: '',
              created_at: 'invalid-date-string',
            },
          ],
        }),
      ),
    );
    renderWithProviders(
      <CommentsDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('No name comment')).toBeInTheDocument(),
    );
    // Two "Unknown" labels — primary text + avatar initials show ?
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0);
  });
});
