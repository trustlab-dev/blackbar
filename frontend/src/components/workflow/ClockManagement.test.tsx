import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../../test-utils/render';
import ClockManagement from './ClockManagement';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const CASE_ID = 'case-1';

const runningStatus = {
  case_id: CASE_ID,
  status: 'running',
  total_paused_days: 0,
  events: [],
};

const pausedStatus = {
  case_id: CASE_ID,
  status: 'paused',
  total_paused_days: 3,
  current_pause_start: '2026-05-01T10:00:00Z',
  current_pause_reason: 'fee_pending',
  adjusted_due_date: '2026-06-15T00:00:00Z',
  original_due_date: '2026-06-12T00:00:00Z',
  events: [
    {
      id: 'e1',
      case_id: CASE_ID,
      event_type: 'pause',
      reason: 'fee_pending',
      event_date: '2026-05-01T10:00:00Z',
      created_by: 'u1',
      created_by_name: 'Alice',
      notes: 'awaiting payment',
    },
    {
      id: 'e2',
      case_id: CASE_ID,
      event_type: 'start',
      event_date: '2026-04-01T10:00:00Z',
      created_by: 'u1',
    },
  ],
};

describe('ClockManagement', () => {
  it('shows the loading state first', () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json(runningStatus);
      }),
    );
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    expect(screen.getByText(/loading clock status/i)).toBeInTheDocument();
  });

  it('renders the running clock with a Pause button', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(runningStatus),
      ),
    );
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    expect(await screen.findByText('RUNNING')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /pause clock/i }),
    ).toBeInTheDocument();
  });

  it('renders the paused clock with reason alert and adjusted due date', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(pausedStatus),
      ),
    );
    renderWithProviders(<ClockManagement caseId={CASE_ID} dueDate="2026-06-12" />);
    expect(await screen.findByText('PAUSED')).toBeInTheDocument();
    expect(screen.getByText(/3 days paused/)).toBeInTheDocument();
    expect(screen.getByText(/Fee Payment Pending/)).toBeInTheDocument();
    expect(screen.getByText(/Adjusted due date:/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /resume clock/i }),
    ).toBeInTheDocument();
  });

  it('falls back to a running clock on a 404', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    );
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    expect(await screen.findByText('RUNNING')).toBeInTheDocument();
  });

  it('shows an error on a non-404 fetch failure', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    expect(
      await screen.findByText(/failed to load clock status/i),
    ).toBeInTheDocument();
  });

  it('pauses the clock through the dialog', async () => {
    let paused = false;
    let postBody: any = null;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(paused ? pausedStatus : runningStatus),
      ),
      http.post(
        `/api/v1/cases/${CASE_ID}/clock/pause`,
        async ({ request }) => {
          postBody = await request.json();
          paused = true;
          return HttpResponse.json({ id: 'e1' });
        },
      ),
    );
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <ClockManagement caseId={CASE_ID} onClockChange={onChange} />,
    );
    await screen.findByText('RUNNING');
    await user.click(screen.getByRole('button', { name: /pause clock/i }));
    await screen.findByRole('heading', { name: /pause statutory clock/i });
    await user.click(screen.getByRole('combobox'));
    await user.click(
      await screen.findByRole('option', { name: /fee payment pending/i }),
    );
    await user.click(
      screen.getByRole('button', { name: /^pause clock$/i }),
    );
    await waitFor(() => expect(postBody?.reason).toBe('fee_pending'));
    expect(await screen.findByText('PAUSED')).toBeInTheDocument();
    expect(onChange).toHaveBeenCalled();
  });

  it('shows an error when pausing fails', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(runningStatus),
      ),
      http.post(`/api/v1/cases/${CASE_ID}/clock/pause`, () =>
        HttpResponse.json({ detail: 'pause failed' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    await screen.findByText('RUNNING');
    await user.click(screen.getByRole('button', { name: /pause clock/i }));
    await screen.findByRole('heading', { name: /pause statutory clock/i });
    await user.click(screen.getByRole('combobox'));
    await user.click(
      await screen.findByRole('option', { name: /third party consultation/i }),
    );
    await user.click(
      screen.getByRole('button', { name: /^pause clock$/i }),
    );
    expect(await screen.findByText(/pause failed/i)).toBeInTheDocument();
  });

  it('resumes a paused clock', async () => {
    let paused = true;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(paused ? pausedStatus : runningStatus),
      ),
      http.post(`/api/v1/cases/${CASE_ID}/clock/resume`, () => {
        paused = false;
        return HttpResponse.json({ id: 'e3' });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    await screen.findByText('PAUSED');
    await user.click(screen.getByRole('button', { name: /resume clock/i }));
    expect(await screen.findByText('RUNNING')).toBeInTheDocument();
  });

  it('shows an error when resuming fails', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(pausedStatus),
      ),
      http.post(`/api/v1/cases/${CASE_ID}/clock/resume`, () =>
        HttpResponse.json({ detail: 'resume failed' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    await screen.findByText('PAUSED');
    await user.click(screen.getByRole('button', { name: /resume clock/i }));
    expect(await screen.findByText(/resume failed/i)).toBeInTheDocument();
  });

  it('opens the history dialog and lists clock events', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(pausedStatus),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    await screen.findByText('PAUSED');
    await user.click(
      screen.getByRole('button', { name: /view clock history/i }),
    );
    await screen.findByRole('heading', { name: /clock history/i });
    expect(screen.getByText('Clock Paused')).toBeInTheDocument();
    expect(screen.getByText('Clock Started')).toBeInTheDocument();
    expect(screen.getByText(/awaiting payment/)).toBeInTheDocument();
  });

  it('shows the no-events message when history is empty', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(runningStatus),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    await screen.findByText('RUNNING');
    await user.click(
      screen.getByRole('button', { name: /view clock history/i }),
    );
    expect(
      await screen.findByText(/no clock events recorded yet/i),
    ).toBeInTheDocument();
  });

  it('cancels the pause dialog', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/clock/history`, () =>
        HttpResponse.json(runningStatus),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ClockManagement caseId={CASE_ID} />);
    await screen.findByText('RUNNING');
    await user.click(screen.getByRole('button', { name: /pause clock/i }));
    await screen.findByRole('heading', { name: /pause statutory clock/i });
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: /pause statutory clock/i }),
      ).not.toBeInTheDocument(),
    );
  });
});
