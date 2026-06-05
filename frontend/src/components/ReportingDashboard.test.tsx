import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import ReportingDashboard from './ReportingDashboard';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const summary = {
  total_cases: 10,
  on_track: 5,
  warning: 2,
  urgent: 1,
  overdue: 2,
  requires_attention: 3,
  compliance_rate: 70.5,
  at_risk_rate: 30.2,
};

const attentionCase = {
  id: 'c1',
  case_number: 'FOI-001',
  title: 'Budget records',
  status: 'in_review',
  deadline_info: {
    deadline: '2026-06-01T00:00:00Z',
    status: 'overdue',
    days_remaining: -3,
    business_days_remaining: -2,
    is_overdue: true,
    requires_attention: true,
  },
};

describe('ReportingDashboard', () => {
  it('shows the loading spinner first', () => {
    server.use(
      http.get('/api/v1/cases/deadline-dashboard', async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ summary, attention_required: [] });
      }),
    );
    renderWithProviders(<ReportingDashboard />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders summary cards and compliance metrics', async () => {
    server.use(
      http.get('/api/v1/cases/deadline-dashboard', () =>
        HttpResponse.json({ summary, attention_required: [] }),
      ),
    );
    renderWithProviders(<ReportingDashboard />);
    expect(await screen.findByText('Reporting Dashboard')).toBeInTheDocument();
    expect(screen.getByText('On Track')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('70.5%')).toBeInTheDocument();
    expect(screen.getByText('30.2%')).toBeInTheDocument();
    expect(
      screen.getByText(/no cases requiring immediate attention/i),
    ).toBeInTheDocument();
  });

  it('renders the attention-required list with status chip and overdue styling', async () => {
    server.use(
      http.get('/api/v1/cases/deadline-dashboard', () =>
        HttpResponse.json({ summary, attention_required: [attentionCase] }),
      ),
    );
    renderWithProviders(<ReportingDashboard />);
    expect(
      await screen.findByText(/FOI-001: Budget records/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Status: in_review/)).toBeInTheDocument();
    expect(screen.getByText(/✕ OVERDUE/)).toBeInTheDocument();
    expect(screen.getByText('-3')).toBeInTheDocument();
  });

  it('renders multiple attention cases with a divider between them', async () => {
    const second = {
      ...attentionCase,
      id: 'c2',
      case_number: 'FOI-002',
      title: 'Second',
      deadline_info: {
        ...attentionCase.deadline_info,
        status: 'warning',
        is_overdue: false,
      },
    };
    server.use(
      http.get('/api/v1/cases/deadline-dashboard', () =>
        HttpResponse.json({
          summary,
          attention_required: [attentionCase, second],
        }),
      ),
    );
    renderWithProviders(<ReportingDashboard />);
    expect(await screen.findByText(/FOI-001/)).toBeInTheDocument();
    expect(screen.getByText(/FOI-002/)).toBeInTheDocument();
    expect(screen.getByText(/⚠ Warning/)).toBeInTheDocument();
  });

  it('handles a missing attention_required key gracefully', async () => {
    server.use(
      http.get('/api/v1/cases/deadline-dashboard', () =>
        HttpResponse.json({ summary }),
      ),
    );
    renderWithProviders(<ReportingDashboard />);
    expect(
      await screen.findByText(/no cases requiring immediate attention/i),
    ).toBeInTheDocument();
  });

  it('shows an error alert when the fetch fails', async () => {
    server.use(
      http.get('/api/v1/cases/deadline-dashboard', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<ReportingDashboard />);
    expect(await screen.findByText('boom')).toBeInTheDocument();
  });

  it('falls back to a generic error message when no detail is provided', async () => {
    server.use(
      http.get('/api/v1/cases/deadline-dashboard', () => HttpResponse.error()),
    );
    renderWithProviders(<ReportingDashboard />);
    expect(
      await screen.findByText(/failed to load dashboard/i),
    ).toBeInTheDocument();
  });

  it('renders zero counts when summary fields are absent', async () => {
    server.use(
      http.get('/api/v1/cases/deadline-dashboard', () =>
        HttpResponse.json({ summary: {}, attention_required: [] }),
      ),
    );
    renderWithProviders(<ReportingDashboard />);
    expect(await screen.findByText('Reporting Dashboard')).toBeInTheDocument();
    // compliance / at-risk rates render as 0%
    expect(screen.getAllByText('0%').length).toBeGreaterThan(0);
  });
});
