import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import CaseDetailView from './CaseDetailView';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ caseId: 'case-1' }),
  };
});

// Child panels and workflow widgets each own their own data fetching and
// MUI internals — stub them so these tests exercise CaseDetailView only.
vi.mock('./ReleasePackageActions', () => ({
  default: () => <div data-testid="release-package-actions" />,
}));
vi.mock('./CaseTeamPanel', () => ({
  default: () => <div data-testid="case-team-panel" />,
}));
vi.mock('./CaseApprovalPanel', () => ({
  default: ({ userRole }: { userRole: string }) => (
    <div data-testid="case-approval-panel">{userRole}</div>
  ),
}));
vi.mock('./workflow', () => ({
  ClockManagement: () => <div data-testid="clock-management" />,
  ContributorsPanel: () => <div data-testid="contributors-panel" />,
  RecordsConfirmation: () => <div data-testid="records-confirmation" />,
  TransferCase: () => <div data-testid="transfer-case" />,
}));

const baseCase = {
  id: 'case-1',
  tracking_number: 'FOI-2026-001',
  title: 'Records request',
  description: 'A description of the request',
  status: 'in_progress',
  priority: 'high',
  assignee: null,
  team: null,
  category: 'Personnel',
  requester: {
    name: 'Joe Public',
    email: 'joe@example.com',
    phone: '555-1234',
    organization: 'Acme',
  },
  due_date: '2026-06-01T00:00:00Z',
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-10T00:00:00Z',
  tags: ['urgent'],
  comments: [
    {
      id: 'cm1',
      author_name: 'Alice',
      text: 'First comment',
      type: 'internal',
      created_at: '2026-05-05T00:00:00Z',
    },
  ],
  audit_log: [
    { action: 'case_created', user_name: 'System', timestamp: '2026-05-01T00:00:00Z', details: {} },
  ],
  document_ids: [],
  case_team: [
    { user_id: 'me', role: 'manager', status: 'active' },
  ],
};

/** Register the five GET endpoints CaseDetailView fires on mount. */
function mountHandlers(overrides?: {
  caseData?: any;
  documents?: any[];
  links?: any[];
}) {
  server.use(
    http.get('/api/v1/cases/case-1', () =>
      HttpResponse.json(overrides?.caseData ?? baseCase),
    ),
    http.get('/api/v1/cases/case-1/collection-links', () =>
      HttpResponse.json({ links: overrides?.links ?? [] }),
    ),
    http.get('/api/v1/cases/case-1/documents', () =>
      HttpResponse.json({ documents: overrides?.documents ?? [] }),
    ),
    http.get('/api/v1/auth/users/assignable', () =>
      HttpResponse.json([
        { id: 'u1', name: 'Bob', email: 'bob@example.com', role: 'analyst' },
      ]),
    ),
    http.get('/api/v1/admin/config/public', () =>
      HttpResponse.json({ request_categories: ['Personnel', 'Finance'] }),
    ),
    http.get('/api/v1/templates/', () =>
      HttpResponse.json([
        { id: 't1', name: 'Acknowledgement', category: 'public' },
      ]),
    ),
  );
}

beforeEach(() => {
  mockNavigate.mockReset();
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(window, 'alert').mockImplementation(() => {});
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  localStorage.setItem('token', 'fake');
  localStorage.setItem('userId', 'me');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('CaseDetailView — load states', () => {
  it('shows the loading state first', () => {
    mountHandlers();
    renderWithProviders(<CaseDetailView />);
    expect(screen.getByText(/loading case/i)).toBeInTheDocument();
  });

  it('shows "Case not found" when the case fetch fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1', () =>
        HttpResponse.json({ detail: 'missing' }, { status: 404 }),
      ),
      http.get('/api/v1/cases/case-1/collection-links', () =>
        HttpResponse.json({ links: [] }),
      ),
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [] }),
      ),
      http.get('/api/v1/auth/users/assignable', () => HttpResponse.json([])),
      http.get('/api/v1/admin/config/public', () =>
        HttpResponse.json({ request_categories: [] }),
      ),
      http.get('/api/v1/templates/', () => HttpResponse.json([])),
    );
    renderWithProviders(<CaseDetailView />);
    expect(await screen.findByText(/case not found/i)).toBeInTheDocument();
  });

  it('renders the case header, description and requester block', async () => {
    mountHandlers();
    renderWithProviders(<CaseDetailView />);
    expect(await screen.findByText('Records request')).toBeInTheDocument();
    expect(screen.getByText('FOI-2026-001')).toBeInTheDocument();
    expect(
      screen.getByText('A description of the request'),
    ).toBeInTheDocument();
    expect(screen.getByText('Joe Public')).toBeInTheDocument();
    expect(screen.getByText('joe@example.com')).toBeInTheDocument();
    expect(screen.getByText('555-1234')).toBeInTheDocument();
    expect(screen.getByText('Acme')).toBeInTheDocument();
    // The current user's case-team role is passed to the approval panel.
    expect(screen.getByTestId('case-approval-panel')).toHaveTextContent(
      'manager',
    );
  });

  it('navigates back to the queue', async () => {
    mountHandlers();
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.click(screen.getByRole('button', { name: /back to queue/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/cases');
  });
});

describe('CaseDetailView — documents preview', () => {
  it('shows the empty documents message', async () => {
    mountHandlers();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    expect(
      screen.getByText(/no documents uploaded yet/i),
    ).toBeInTheDocument();
  });

  it('previews up to three documents and a "+N more" row', async () => {
    mountHandlers({
      documents: [
        { id: 'd1', filename: 'a.pdf', size: 2048 },
        { id: 'd2', filename: 'b.docx', size: 1024 },
        { id: 'd3', filename: 'c.eml', size: 512 },
        { id: 'd4', filename: 'd.txt', size: 256 },
      ],
    });
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    expect(screen.getByText('a.pdf')).toBeInTheDocument();
    expect(screen.getByText('c.eml')).toBeInTheDocument();
    expect(screen.queryByText('d.txt')).not.toBeInTheDocument();
    expect(screen.getByText(/\+1 more documents/i)).toBeInTheDocument();
  });

  it('navigates to the documents page', async () => {
    mountHandlers();
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.click(
      screen.getByRole('button', { name: /view all documents/i }),
    );
    expect(mockNavigate).toHaveBeenCalledWith('/cases/case-1/documents');
  });
});

describe('CaseDetailView — sidebar field updates', () => {
  it('updates the case status', async () => {
    let putHit = false;
    mountHandlers();
    server.use(
      http.put('/api/v1/cases/case-1/status', () => {
        putHit = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    // The sidebar selects aren't label-associated; target by current value.
    await user.selectOptions(
      screen.getByDisplayValue('In Progress'),
      'completed',
    );
    await waitFor(() => expect(putHit).toBe(true));
  });

  it('updates the priority', async () => {
    let body: any = null;
    mountHandlers();
    server.use(
      http.put('/api/v1/cases/case-1', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.selectOptions(screen.getByDisplayValue('High'), 'low');
    await waitFor(() => expect(body?.priority).toBe('low'));
  });

  it('assigns the case to a user', async () => {
    let body: any = null;
    mountHandlers();
    server.use(
      http.put('/api/v1/cases/case-1/assign', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.selectOptions(screen.getByDisplayValue('Unassigned'), 'u1');
    await waitFor(() => expect(body?.assignee).toBe('u1'));
  });

  it('updates the category field', async () => {
    let body: any = null;
    mountHandlers();
    server.use(
      http.put('/api/v1/cases/case-1', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    // The category select shows the current value 'Personnel'.
    await user.selectOptions(
      screen.getByDisplayValue('Personnel'),
      'Finance',
    );
    await waitFor(() => expect(body?.category).toBe('Finance'));
  });

  it('logs an error when a field update fails', async () => {
    mountHandlers();
    server.use(
      http.put('/api/v1/cases/case-1', () =>
        HttpResponse.json({ detail: 'no' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.selectOptions(screen.getByDisplayValue('High'), 'low');
    await waitFor(() => expect(console.error).toHaveBeenCalled());
  });
});

describe('CaseDetailView — tags', () => {
  it('adds a new tag on Enter', async () => {
    let body: any = null;
    mountHandlers();
    server.use(
      http.put('/api/v1/cases/case-1', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    const tagInput = screen.getByPlaceholderText(/add tag/i);
    await user.type(tagInput, 'confidential{enter}');
    await waitFor(() =>
      expect(body?.tags).toEqual(['urgent', 'confidential']),
    );
  });

  it('removes an existing tag', async () => {
    let body: any = null;
    mountHandlers();
    server.use(
      http.put('/api/v1/cases/case-1', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.click(screen.getByTitle('Remove tag'));
    await waitFor(() => expect(body?.tags).toEqual([]));
  });
});

describe('CaseDetailView — comments', () => {
  it('renders existing comments', async () => {
    mountHandlers();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    expect(screen.getByText('First comment')).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument();
  });

  it('adds an internal comment', async () => {
    let body: any = null;
    mountHandlers();
    server.use(
      http.post('/api/v1/cases/case-1/comments', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.type(
      screen.getByPlaceholderText(/add internal comment/i),
      'A new note',
    );
    await user.click(screen.getByRole('button', { name: /add comment/i }));
    await waitFor(() => expect(body?.text).toBe('A new note'));
    expect(body.type).toBe('internal');
  });

  it('switches to public comment type and applies a template', async () => {
    mountHandlers();
    server.use(
      http.post('/api/v1/templates/t1/render', () =>
        HttpResponse.json({ rendered_content: 'Dear requester, ...' }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.click(screen.getByRole('button', { name: /^public$/i }));
    const templateSelect = await screen.findByRole('combobox', {
      name: /use a template/i,
    });
    await user.selectOptions(templateSelect, 't1');
    await waitFor(() =>
      expect(
        screen.getByDisplayValue('Dear requester, ...'),
      ).toBeInTheDocument(),
    );
  });

  it('logs an error when adding a comment fails', async () => {
    mountHandlers();
    server.use(
      http.post('/api/v1/cases/case-1/comments', () =>
        HttpResponse.json({ detail: 'no' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.type(
      screen.getByPlaceholderText(/add internal comment/i),
      'oops',
    );
    await user.click(screen.getByRole('button', { name: /add comment/i }));
    await waitFor(() => expect(console.error).toHaveBeenCalled());
  });
});

describe('CaseDetailView — collection links', () => {
  it('creates a collection link through the dialog', async () => {
    let posted = false;
    mountHandlers();
    server.use(
      http.post('/api/v1/cases/case-1/collection-links', () => {
        posted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.click(screen.getByRole('button', { name: /create link/i }));
    await screen.findByRole('heading', { name: /create collection link/i });
    await user.click(
      screen.getByRole('button', { name: /^create link$/i }),
    );
    await waitFor(() => expect(posted).toBe(true));
  });

  it('renders existing links and copies one to the clipboard', async () => {
    mountHandlers({
      links: [
        { id: 'l1', url: '/collect/abc', upload_count: 2, is_active: true },
      ],
    });
    const user = userEvent.setup();
    // userEvent.setup() installs its own navigator.clipboard stub, so the
    // override must come after it.
    const writeText = vi.fn();
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    expect(screen.getByText(/2 uploads/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /copy link/i }));
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('/collect/abc'),
    );
  });

  it('deactivates an active link', async () => {
    let deleted = false;
    mountHandlers({
      links: [
        { id: 'l1', url: '/collect/abc', upload_count: 0, is_active: true },
      ],
    });
    server.use(
      http.delete('/api/v1/cases/case-1/collection-links/l1', () => {
        deleted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.click(screen.getByRole('button', { name: /deactivate/i }));
    await waitFor(() => expect(deleted).toBe(true));
  });
});

describe('CaseDetailView — delete case', () => {
  it('shows the Delete Case button only for admins and deletes', async () => {
    localStorage.setItem('userRole', 'admin');
    let deleted = false;
    mountHandlers();
    server.use(
      http.delete('/api/v1/cases/case-1', () => {
        deleted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.click(screen.getByRole('button', { name: /delete case/i }));
    await waitFor(() => expect(deleted).toBe(true));
    expect(mockNavigate).toHaveBeenCalledWith('/cases');
  });

  it('hides the Delete Case button for non-admins', async () => {
    localStorage.setItem('userRole', 'analyst');
    mountHandlers();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    expect(
      screen.queryByRole('button', { name: /delete case/i }),
    ).not.toBeInTheDocument();
  });

  it('alerts when deleting the case fails', async () => {
    localStorage.setItem('userRole', 'admin');
    mountHandlers();
    server.use(
      http.delete('/api/v1/cases/case-1', () =>
        HttpResponse.json({ detail: 'no' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    await user.click(screen.getByRole('button', { name: /delete case/i }));
    await waitFor(() =>
      expect(window.alert).toHaveBeenCalledWith('Failed to delete case'),
    );
  });
});

describe('CaseDetailView — approval banner & activity log', () => {
  it('shows the review banner when the case is in review', async () => {
    mountHandlers({ caseData: { ...baseCase, status: 'review' } });
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    expect(screen.getByText(/pending review/i)).toBeInTheDocument();
  });

  it('shows the final-approval banner when the case is completed', async () => {
    mountHandlers({ caseData: { ...baseCase, status: 'completed' } });
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    expect(
      screen.getByText(/pending final approval/i),
    ).toBeInTheDocument();
  });

  it('expands the activity log when there are more than five entries', async () => {
    const manyEntries = Array.from({ length: 7 }, (_, i) => ({
      action: `event_${i}`,
      user_name: 'Sys',
      timestamp: '2026-05-01T00:00:00Z',
      details: {},
    }));
    mountHandlers({ caseData: { ...baseCase, audit_log: manyEntries } });
    const user = userEvent.setup();
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    const showAll = screen.getByRole('button', { name: /show all \(7\)/i });
    await user.click(showAll);
    expect(
      screen.getByRole('button', { name: /show less/i }),
    ).toBeInTheDocument();
  });

  it('falls back to the assignee role-only label and renders the no-tags state', async () => {
    mountHandlers({
      caseData: {
        ...baseCase,
        tags: [],
        requester: null,
        case_team: [],
      },
    });
    renderWithProviders(<CaseDetailView />);
    await screen.findByText('Records request');
    expect(screen.getByText(/no tags/i)).toBeInTheDocument();
    // No requester block when requester is null.
    expect(
      screen.queryByText(/requester information/i),
    ).not.toBeInTheDocument();
    // No case-team match => approval panel gets the default 'viewer' role.
    expect(screen.getByTestId('case-approval-panel')).toHaveTextContent(
      'viewer',
    );
  });
});
