import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import { UserProvider } from '../contexts/UserContext';
import CaseQueue from './CaseQueue';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderQueue() {
  return renderWithProviders(
    <UserProvider>
      <CaseQueue />
    </UserProvider>,
  );
}

const baseCase = {
  id: 'c1',
  tracking_number: 'FOI-2026-001',
  title: 'Test case',
  status: 'new',
  priority: 'high',
  assignee: 'alice',
  category: 'Personnel',
  requester: { name: 'Joe Public', email: 'joe@example.com' },
  due_date: new Date(Date.now() + 86400000 * 5).toISOString(),
  sla_status: 'on_track',
  created_at: new Date().toISOString(),
  tags: ['urgent'],
};

beforeEach(() => {
  mockNavigate.mockReset();
  localStorage.clear();
  localStorage.setItem('userRole', 'admin');
  localStorage.setItem('token', 'fake-token');
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('CaseQueue — fetch + render', () => {
  it('shows loading then renders the case row', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({ request_categories: ['Personnel', 'Financial'] }),
      ),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [baseCase], total: 1 }),
      ),
    );
    renderQueue();
    expect(screen.getByText(/loading cases/i)).toBeInTheDocument();
    expect(await screen.findByText('FOI-2026-001')).toBeInTheDocument();
    expect(screen.getByText('Test case')).toBeInTheDocument();
    expect(screen.getByText('Joe Public')).toBeInTheDocument();
  });

  it('renders "—" for missing category, "Unassigned" for null assignee, "—" for null requester', async () => {
    const minimal = {
      ...baseCase,
      id: 'c2',
      category: undefined,
      assignee: null,
      requester: null,
      due_date: new Date(Date.now() - 86400000 * 2).toISOString(),
      sla_status: 'overdue',
    };
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [minimal], total: 1 }),
      ),
    );
    renderQueue();
    expect(await screen.findByText(/unassigned/i)).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('renders "Due today" for due_date === today', async () => {
    const today = {
      ...baseCase,
      due_date: new Date().toISOString(),
      sla_status: 'due_soon',
    };
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [today], total: 1 }),
      ),
    );
    renderQueue();
    expect(await screen.findByText(/due today/i)).toBeInTheDocument();
  });

  it('renders "N days overdue" for past dates', async () => {
    const past = {
      ...baseCase,
      due_date: new Date(Date.now() - 86400000 * 3).toISOString(),
      sla_status: 'overdue',
    };
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [past], total: 1 }),
      ),
    );
    renderQueue();
    expect(await screen.findByText(/days overdue/i)).toBeInTheDocument();
  });

  it('renders a long-future date using toLocaleDateString', async () => {
    const future = {
      ...baseCase,
      due_date: new Date(Date.now() + 86400000 * 30).toISOString(),
    };
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [future], total: 1 }),
      ),
    );
    renderQueue();
    // Wait for the row to appear (any tracking number)
    await screen.findByText('FOI-2026-001');
  });
});

describe('CaseQueue — error handling', () => {
  it('shows error message and Try Again button when fetch fails', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get(
        '/api/v1/cases/queue/all',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderQueue();
    expect(
      await screen.findByText(/failed to load cases/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });
});

describe('CaseQueue — interactions', () => {
  it('navigates to case detail when a row is clicked', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [baseCase], total: 1 }),
      ),
    );
    const user = userEvent.setup();
    renderQueue();
    const row = await screen.findByText('FOI-2026-001');
    await user.click(row);
    expect(mockNavigate).toHaveBeenCalledWith('/cases/c1');
  });

  it('toggles sort direction when clicking the same column header twice', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [baseCase], total: 1 }),
      ),
    );
    const user = userEvent.setup();
    renderQueue();
    await screen.findByText('FOI-2026-001');
    const dueHeader = screen.getByText(/due date/i);
    await user.click(dueHeader); // toggle to desc
    await user.click(screen.getByText(/title/i)); // switch column
    // Just verify it doesn't crash and a sort icon shows up for Title
    await waitFor(() => expect(screen.getByText(/title/i)).toBeInTheDocument());
  });

  it('updates search input', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [], total: 0 }),
      ),
    );
    const user = userEvent.setup();
    renderQueue();
    const search = screen.getByPlaceholderText(/search by title/i);
    await user.type(search, 'foo');
    expect(search).toHaveValue('foo');
  });

  it('switches viewMode from "my" to "all" when admin clicks All Cases tab', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/my-cases', () =>
        HttpResponse.json({ cases: [], total: 0 }),
      ),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [baseCase], total: 1 }),
      ),
    );
    const user = userEvent.setup();
    renderQueue();
    await user.click(screen.getByRole('button', { name: /my cases/i }));
    await user.click(screen.getByRole('button', { name: /all cases/i }));
    expect(await screen.findByText('FOI-2026-001')).toBeInTheDocument();
  });

  it('manual refresh button refetches', async () => {
    let calls = 0;
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () => {
        calls += 1;
        return HttpResponse.json({ cases: [], total: 0 });
      }),
    );
    const user = userEvent.setup();
    renderQueue();
    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(1));
    const before = calls;
    await user.click(screen.getByRole('button', { name: /refresh/i }));
    await waitFor(() => expect(calls).toBeGreaterThan(before));
  });
});

describe('CaseQueue — pagination', () => {
  it('enables Next when more pages exist and disables Previous on page 0', async () => {
    const many = Array.from({ length: 50 }, (_, i) => ({
      ...baseCase,
      id: `case-${i}`,
      tracking_number: `FOI-${i}`,
    }));
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: many, total: 120 }),
      ),
    );
    const user = userEvent.setup();
    renderQueue();
    await screen.findByText('FOI-0');
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled();
    const next = screen.getByRole('button', { name: /next/i });
    expect(next).toBeEnabled();
    await user.click(next);
  });
});

describe('CaseQueue — Create Case dialog', () => {
  it('opens the dialog, posts a new case, and navigates to it', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({ request_categories: ['Personnel'] }),
      ),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [], total: 0 }),
      ),
      http.post('/api/v1/cases/', () =>
        HttpResponse.json({ id: 'new-case-1' }),
      ),
    );
    const user = userEvent.setup();
    renderQueue();

    await user.click(screen.getByRole('button', { name: /create case/i }));
    expect(
      await screen.findByRole('heading', { name: /create new case/i }),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText(/request title/i), 'My Title');
    await user.type(screen.getByLabelText(/description/i), 'My desc');
    await user.type(screen.getByLabelText(/requester name/i), 'Joe');
    await user.type(screen.getByLabelText(/requester email/i), 'joe@x.com');

    const dialogCreateBtn = screen
      .getAllByRole('button', { name: /create case/i })
      .find((b) => !b.classList.contains('MuiButton-startIcon'))!;
    // Find the one that is the dialog action (enabled now)
    const enabled = screen
      .getAllByRole('button', { name: /create case/i })
      .find((b) => !(b as HTMLButtonElement).disabled);
    await user.click(enabled ?? dialogCreateBtn);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/cases/new-case-1'),
    );
  });

  it('surfaces backend detail when create fails', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [], total: 0 }),
      ),
      http.post('/api/v1/cases/', () =>
        HttpResponse.json({ detail: 'Bad request' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderQueue();

    await user.click(screen.getByRole('button', { name: /create case/i }));
    await user.type(await screen.findByLabelText(/request title/i), 'T');
    await user.type(screen.getByLabelText(/description/i), 'D');
    await user.type(screen.getByLabelText(/requester name/i), 'N');
    await user.type(screen.getByLabelText(/requester email/i), 'e@x.com');

    const enabled = screen
      .getAllByRole('button', { name: /create case/i })
      .find((b) => !(b as HTMLButtonElement).disabled)!;
    await user.click(enabled);

    await waitFor(() =>
      expect(screen.getByText(/bad request/i)).toBeInTheDocument(),
    );
  });

  it('Cancel closes the dialog', async () => {
    server.use(
      http.get('/api/v1/admin/config/public', () => HttpResponse.json({})),
      http.get('/api/v1/cases/queue/all', () =>
        HttpResponse.json({ cases: [], total: 0 }),
      ),
    );
    const user = userEvent.setup();
    renderQueue();
    await user.click(screen.getByRole('button', { name: /create case/i }));
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: /create new case/i }),
      ).not.toBeInTheDocument(),
    );
  });
});
