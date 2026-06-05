// frontend/src/components/viewer/HistoryDrawer.test.tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('axios', async () => {
  const actual = await vi.importActual<any>('axios');
  const origCreate = actual.default.create.bind(actual.default);
  actual.default.create = (config: any = {}) =>
    origCreate({ ...config, adapter: 'fetch' });
  return actual;
});

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
import HistoryDrawer from './HistoryDrawer';

const URL = 'https://localhost:3000/api/v1/documents/:id/audit-logs';

beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('HistoryDrawer', () => {
  it('does not fetch when closed', async () => {
    let called = false;
    server.use(
      http.get(URL, () => {
        called = true;
        return HttpResponse.json({ audit_logs: [] });
      }),
    );
    renderWithProviders(
      <HistoryDrawer open={false} onClose={() => {}} documentId="doc-1" />,
    );
    await new Promise(r => setTimeout(r, 30));
    expect(called).toBe(false);
  });

  it('shows empty state when no audit logs returned', async () => {
    server.use(http.get(URL, () => HttpResponse.json({ audit_logs: [] })));
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('No activity history available')).toBeInTheDocument(),
    );
  });

  it('renders audit logs and formats action text', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          audit_logs: [
            {
              action: 'redaction_created',
              user_id: 'u1',
              username: 'Alice',
              timestamp: new Date().toISOString(),
            },
            {
              action: 'redaction_deleted',
              user_id: 'u2',
              username: 'Bob',
              timestamp: new Date().toISOString(),
            },
          ],
        }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('Redaction Created')).toBeInTheDocument(),
    );
    expect(screen.getByText('Redaction Deleted')).toBeInTheDocument();
  });

  it('supports the alt response shape (`logs` key)', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          logs: [
            {
              action: 'search',
              user_id: 'u1',
              username: 'S',
              timestamp: new Date().toISOString(),
            },
          ],
        }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() => expect(screen.getByText('Search')).toBeInTheDocument());
  });

  it('supports a bare-array response shape', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json([
          {
            action: 'ai_suggest',
            user_id: 'u1',
            username: 'S',
            timestamp: new Date().toISOString(),
          },
        ]),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('Ai Suggest')).toBeInTheDocument(),
    );
  });

  it('coerces non-array response into empty list', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({ audit_logs: 'not-an-array' }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('No activity history available')).toBeInTheDocument(),
    );
  });

  it('shows error from response detail on 500', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(
      http.get(URL, () =>
        HttpResponse.json({ detail: 'Server boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('Server boom')).toBeInTheDocument(),
    );
  });

  it('shows generic error when detail is missing', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(http.get(URL, () => new HttpResponse(null, { status: 500 })));
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('Failed to load history')).toBeInTheDocument(),
    );
  });

  it('formats action details for a recent redaction with page/text/category', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          audit_logs: [
            {
              action: 'redaction_added',
              user_id: 'u1',
              username: 'Alice',
              timestamp: new Date().toISOString(),
              details: {
                page: 2,
                text: 'A very long redacted text that should get truncated to 30 characters',
                category: 'PII',
              },
            },
          ],
        }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/Page 2/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/PII/)).toBeInTheDocument();
  });

  it('handles string details', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          audit_logs: [
            {
              action: 'updated_setting',
              user_id: 'u1',
              username: 'Alice',
              timestamp: new Date().toISOString(),
              details: 'config changed',
            },
          ],
        }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('config changed')).toBeInTheDocument(),
    );
  });

  it('handles object details via JSON.stringify branch', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          audit_logs: [
            {
              action: 'misc',
              user_id: 'u1',
              username: 'Alice',
              timestamp: new Date().toISOString(),
              details: { foo: 'bar', baz: 'qux' },
            },
          ],
        }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/foo/)).toBeInTheDocument(),
    );
  });

  it('formats timestamps with relative labels ("Just now", minutes, hours, days)', async () => {
    const now = Date.now();
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          audit_logs: [
            { action: 'a', username: 'u', user_id: '1', timestamp: new Date(now - 5_000).toISOString() }, // Just now (5s)
            { action: 'b', username: 'u', user_id: '1', timestamp: new Date(now - 40_000).toISOString() }, // 40s ago
            { action: 'c', username: 'u', user_id: '1', timestamp: new Date(now - 5 * 60_000).toISOString() }, // 5m ago
            { action: 'd', username: 'u', user_id: '1', timestamp: new Date(now - 2 * 3600_000).toISOString() }, // 2h ago
            { action: 'e', username: 'u', user_id: '1', timestamp: new Date(now - 3 * 86400_000).toISOString() }, // 3d ago
            { action: 'f', username: 'u', user_id: '1', timestamp: new Date(now - 14 * 86400_000).toISOString() }, // 14d ago -> locale date
          ],
        }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/Just now/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/40s ago/)).toBeInTheDocument();
    expect(screen.getByText(/5m ago/)).toBeInTheDocument();
    expect(screen.getByText(/2h ago/)).toBeInTheDocument();
    expect(screen.getByText(/3d ago/)).toBeInTheDocument();
  });

  it('returns raw timestamp when parsing throws', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          audit_logs: [
            {
              action: 'a',
              username: 'u',
              user_id: '1',
              // Pass a value that .endsWith() will fail on (null).
              timestamp: null as any,
            },
          ],
        }),
      ),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() => expect(screen.getByText(/by u/)).toBeInTheDocument());
  });

  it('renders all action-icon branches (add/edit/delete/search/ai/default)', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          audit_logs: [
            { action: 'redaction_created', username: 'u', user_id: '1', timestamp: new Date().toISOString() },
            { action: 'redaction_edited', username: 'u', user_id: '1', timestamp: new Date().toISOString() },
            { action: 'redaction_deleted', username: 'u', user_id: '1', timestamp: new Date().toISOString() },
            { action: 'search_performed', username: 'u', user_id: '1', timestamp: new Date().toISOString() },
            { action: 'ai_invoke', username: 'u', user_id: '1', timestamp: new Date().toISOString() },
            { action: 'mystery', username: 'u', user_id: '1', timestamp: new Date().toISOString() }, // default branch
          ],
        }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText('Mystery')).toBeInTheDocument(),
    );
  });

  it('falls back to "Unknown" when username is missing', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json({
          audit_logs: [
            { action: 'a', user_id: '1', timestamp: new Date().toISOString() },
          ],
        }),
      ),
    );
    renderWithProviders(
      <HistoryDrawer open={true} onClose={() => {}} documentId="doc-1" />,
    );
    await waitFor(() => expect(screen.getByText(/Unknown/)).toBeInTheDocument());
  });

  it('calls onClose when Close button clicked', async () => {
    server.use(http.get(URL, () => HttpResponse.json({ audit_logs: [] })));
    const onClose = vi.fn();
    renderWithProviders(
      <HistoryDrawer open={true} onClose={onClose} documentId="doc-1" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/No activity/)).toBeInTheDocument(),
    );
    const buttons = screen.getAllByRole('button');
    await userEvent.click(buttons[0]);
    expect(onClose).toHaveBeenCalled();
  });
});
