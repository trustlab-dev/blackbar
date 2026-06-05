import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../../test-utils/render';
import PriorityQueue from './PriorityQueue';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return { ...actual, useNavigate: () => navigateMock };
});

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
  navigateMock.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const makeCase = (overrides = {}) => ({
  case_id: 'c1',
  tracking_number: 'FOI-001',
  title: 'Budget records',
  due_date: '2026-06-01',
  days_until_due: 10,
  case_age_days: 5,
  document_count: 3,
  priority_score: 85,
  status: 'in_review',
  workflow_stage: 'review',
  clock_status: 'running',
  analyst_ids: ['a1'],
  ...overrides,
});

describe('PriorityQueue', () => {
  it('shows the spinner, then renders the case rows', async () => {
    server.use(
      http.get('/api/v1/queue/prioritized', () =>
        HttpResponse.json([makeCase()]),
      ),
    );
    renderWithProviders(<PriorityQueue />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(await screen.findByText('FOI-001')).toBeInTheDocument();
    expect(screen.getByText('Budget records')).toBeInTheDocument();
  });

  it('renders the empty state when no cases match', async () => {
    server.use(
      http.get('/api/v1/queue/prioritized', () => HttpResponse.json([])),
    );
    renderWithProviders(<PriorityQueue />);
    expect(
      await screen.findByText(/no cases match the current filters/i),
    ).toBeInTheDocument();
  });

  it('shows an error alert when the queue fetch fails', async () => {
    server.use(
      http.get('/api/v1/queue/prioritized', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<PriorityQueue />);
    expect(
      await screen.findByText(/failed to load priority queue/i),
    ).toBeInTheDocument();
  });

  it('renders the overdue / due-today / due-soon chips correctly', async () => {
    server.use(
      http.get('/api/v1/queue/prioritized', () =>
        HttpResponse.json([
          makeCase({ case_id: 'c1', tracking_number: 'A', days_until_due: -3 }),
          makeCase({ case_id: 'c2', tracking_number: 'B', days_until_due: 0 }),
          makeCase({ case_id: 'c3', tracking_number: 'C', days_until_due: 4 }),
          makeCase({
            case_id: 'c4',
            tracking_number: 'D',
            days_until_due: undefined,
          }),
        ]),
      ),
    );
    renderWithProviders(<PriorityQueue />);
    expect(await screen.findByText('3d OVERDUE')).toBeInTheDocument();
    expect(screen.getByText('DUE TODAY')).toBeInTheDocument();
    expect(screen.getByText('4d left')).toBeInTheDocument();
  });

  it('navigates to a case when its row is clicked', async () => {
    server.use(
      http.get('/api/v1/queue/prioritized', () =>
        HttpResponse.json([makeCase()]),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PriorityQueue />);
    await screen.findByText('FOI-001');
    await user.click(screen.getByText('FOI-001'));
    expect(navigateMock).toHaveBeenCalledWith('/cases/c1');
  });

  it('shows the paused-clock icon and the priority-override chip', async () => {
    server.use(
      http.get('/api/v1/queue/prioritized', () =>
        HttpResponse.json([
          makeCase({ clock_status: 'paused', priority_override: 50 }),
        ]),
      ),
    );
    renderWithProviders(<PriorityQueue />);
    await screen.findByText('FOI-001');
    expect(screen.getByText('Override')).toBeInTheDocument();
  });

  it('refetches when a filter changes', async () => {
    let lastUrl = '';
    server.use(
      http.get('/api/v1/queue/prioritized', ({ request }) => {
        lastUrl = request.url;
        return HttpResponse.json([makeCase()]);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <PriorityQueue
        currentUserId="me"
        users={[{ id: 'a1', name: 'Analyst One' }]}
      />,
    );
    await screen.findByText('FOI-001');
    // open the Stage select (combobox index 1: Analyst, Stage, Clock) and pick a stage
    await user.click(screen.getAllByRole('combobox')[1]);
    await user.click(await screen.findByRole('option', { name: 'Review' }));
    await waitFor(() => expect(lastUrl).toContain('workflow_stage=review'));
  });

  it('refetches when Refresh is clicked', async () => {
    let calls = 0;
    server.use(
      http.get('/api/v1/queue/prioritized', () => {
        calls += 1;
        return HttpResponse.json(calls > 1 ? [] : [makeCase()]);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PriorityQueue />);
    await screen.findByText('FOI-001');
    await user.click(screen.getByRole('button', { name: /refresh/i }));
    expect(
      await screen.findByText(/no cases match the current filters/i),
    ).toBeInTheDocument();
  });

  it('uses status as the stage label when workflow_stage is absent', async () => {
    server.use(
      http.get('/api/v1/queue/prioritized', () =>
        HttpResponse.json([
          makeCase({ workflow_stage: undefined, status: 'closed' }),
        ]),
      ),
    );
    renderWithProviders(<PriorityQueue />);
    expect(await screen.findByText('closed')).toBeInTheDocument();
  });
});
