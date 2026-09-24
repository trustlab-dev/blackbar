import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import SharedDocuments from './SharedDocuments';

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
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const sharedDoc = {
  id: 'doc-1',
  filename: 'shared-report.pdf',
  case_id: 'case-1',
  mime_type: 'application/pdf',
  size: 2048,
  upload_date: '2026-05-01T00:00:00Z',
  shared_by: 'Alice',
  shared_at: '2026-05-10T00:00:00Z',
  notes: 'Please review',
};

describe('SharedDocuments', () => {
  it('shows the loading state first', () => {
    server.use(
      http.get('/api/v1/documents/shared-with-me', () =>
        HttpResponse.json({ documents: [] }),
      ),
    );
    renderWithProviders(<SharedDocuments />);
    expect(
      screen.getByText(/loading shared documents/i),
    ).toBeInTheDocument();
  });

  it('renders the empty state when nothing is shared', async () => {
    server.use(
      http.get('/api/v1/documents/shared-with-me', () =>
        HttpResponse.json({ documents: [] }),
      ),
    );
    renderWithProviders(<SharedDocuments />);
    expect(
      await screen.findByText(/no documents have been shared with you yet/i),
    ).toBeInTheDocument();
  });

  it('renders shared document cards with metadata', async () => {
    server.use(
      http.get('/api/v1/documents/shared-with-me', () =>
        HttpResponse.json({ documents: [sharedDoc] }),
      ),
    );
    renderWithProviders(<SharedDocuments />);
    expect(
      await screen.findByText('shared-report.pdf'),
    ).toBeInTheDocument();
    expect(screen.getByText(/2\.0 KB/)).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Please review')).toBeInTheDocument();
  });

  it('formats sizes across B / KB / MB ranges', async () => {
    server.use(
      http.get('/api/v1/documents/shared-with-me', () =>
        HttpResponse.json({
          documents: [
            { ...sharedDoc, id: 'b', filename: 'tiny.txt', size: 512, notes: '' },
            { ...sharedDoc, id: 'm', filename: 'big.pdf', size: 5 * 1024 * 1024, notes: '' },
          ],
        }),
      ),
    );
    renderWithProviders(<SharedDocuments />);
    expect(await screen.findByText('tiny.txt')).toBeInTheDocument();
    expect(screen.getByText(/512 B/)).toBeInTheDocument();
    expect(screen.getByText(/5\.0 MB/)).toBeInTheDocument();
  });

  it('navigates to the document viewer when a card is clicked', async () => {
    server.use(
      http.get('/api/v1/documents/shared-with-me', () =>
        HttpResponse.json({ documents: [sharedDoc] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<SharedDocuments />);
    await user.click(await screen.findByText('shared-report.pdf'));
    expect(mockNavigate).toHaveBeenCalledWith('/documents/doc-1');
  });

  it('shows an error message when the fetch fails', async () => {
    server.use(
      http.get('/api/v1/documents/shared-with-me', () =>
        HttpResponse.json({ error: { code: 'HTTP_400', message: 'server unavailable' } }, { status: 400 }),
      ),
    );
    renderWithProviders(<SharedDocuments />);
    expect(
      await screen.findByText(/server unavailable/i),
    ).toBeInTheDocument();
  });

  it('leaves a 401 to the api client, keeping reason and return path', async () => {
    const originalLocation = Object.getOwnPropertyDescriptor(window, 'location')!;
    const assignments: string[] = [];
    let href = 'http://localhost/shared';
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        origin: 'http://localhost',
        protocol: 'http:',
        host: 'localhost',
        hostname: 'localhost',
        pathname: '/shared',
        search: '',
        get href() {
          return href;
        },
        set href(v: string) {
          assignments.push(v);
          href = v;
        },
      },
    });
    localStorage.setItem('token', 'guest-token');
    try {
      server.use(
        http.get('/api/v1/documents/shared-with-me', () =>
          HttpResponse.json(
            { error: { code: 'HTTP_401', message: 'Invalid or expired token' } },
            { status: 401 },
          ),
        ),
      );
      renderWithProviders(<SharedDocuments />);
      await waitFor(() => expect(assignments.length).toBeGreaterThan(0));
      await new Promise((r) => setTimeout(r, 20));
      expect(assignments).toEqual([
        `/login?redirect=${encodeURIComponent('/shared')}&reason=expired`,
      ]);
      expect(localStorage.getItem('token')).toBeNull();
    } finally {
      Object.defineProperty(window, 'location', originalLocation);
    }
  });
});
