import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import CaseApprovalPanel from './CaseApprovalPanel';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

const pendingStatus = {
  approval_status: null,
  approved_by: null,
  approved_at: null,
  approval_notes: null,
};

describe('CaseApprovalPanel — status badges', () => {
  it('shows the Pending Approval badge when no status is set', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
    );
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="reviewer" />);
    expect(await screen.findByText(/pending approval/i)).toBeInTheDocument();
  });

  it('shows the Approved badge and notes when status is approved', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json({
          approval_status: 'approved',
          approved_by: 'u1',
          approved_at: '2026-05-10T12:00:00Z',
          approval_notes: 'Looks good',
        }),
      ),
    );
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="reviewer" />);
    expect(
      await screen.findByText(/approved for release/i),
    ).toBeInTheDocument();
    expect(screen.getByText('Looks good')).toBeInTheDocument();
  });

  it('shows the Rejected badge when status is rejected', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json({
          approval_status: 'rejected',
          approved_by: null,
          approved_at: null,
          approval_notes: null,
        }),
      ),
    );
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="reviewer" />);
    expect(await screen.findByText(/approval rejected/i)).toBeInTheDocument();
  });

  it('silently ignores a 403 from approval-status', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json({ detail: 'forbidden' }, { status: 403 }),
      ),
    );
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="reviewer" />);
    // Falls back to the default Pending Approval badge, no console.error
    expect(await screen.findByText(/pending approval/i)).toBeInTheDocument();
  });

  it('logs a non-403 error from approval-status', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="reviewer" />);
    await waitFor(() => expect(console.error).toHaveBeenCalled());
  });
});

describe('CaseApprovalPanel — permissions', () => {
  it('shows approve/reject buttons for an approver', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
    );
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="approver" />);
    expect(
      await screen.findByRole('button', { name: /approve case/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument();
  });

  it('shows the read-only message for a non-approver role', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
    );
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="legal" />);
    expect(
      await screen.findByText(/only approvers and managers can approve/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /approve case/i }),
    ).not.toBeInTheDocument();
  });

  it('hides action buttons once the case is already approved', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json({
          approval_status: 'approved',
          approved_by: 'u1',
          approved_at: null,
          approval_notes: null,
        }),
      ),
    );
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="approver" />);
    await screen.findByText(/approved for release/i);
    expect(
      screen.queryByRole('button', { name: /approve case/i }),
    ).not.toBeInTheDocument();
  });
});

describe('CaseApprovalPanel — approve flow', () => {
  it('opens the approve dialog, posts, and shows success', async () => {
    let body: any = null;
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
      http.post('/api/v1/cases/case-1/approve', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="approver" />);
    await user.click(
      await screen.findByRole('button', { name: /approve case/i }),
    );
    await screen.findByRole('heading', { name: /approve case for release/i });
    await user.type(
      screen.getByLabelText(/notes \(optional\)/i),
      'approving now',
    );
    await user.click(
      screen.getByRole('button', { name: /^approve case$/i }),
    );
    await waitFor(() => expect(body?.notes).toBe('approving now'));
    expect(
      await screen.findByText(/case approved for release/i),
    ).toBeInTheDocument();
  });

  it('shows an error when approve fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
      http.post('/api/v1/cases/case-1/approve', () =>
        HttpResponse.json({ detail: 'not allowed' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="approver" />);
    await user.click(
      await screen.findByRole('button', { name: /approve case/i }),
    );
    await screen.findByRole('heading', { name: /approve case for release/i });
    await user.click(
      screen.getByRole('button', { name: /^approve case$/i }),
    );
    expect(await screen.findByText(/not allowed/i)).toBeInTheDocument();
  });

  it('cancels the approve dialog', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="approver" />);
    await user.click(
      await screen.findByRole('button', { name: /approve case/i }),
    );
    await screen.findByRole('heading', { name: /approve case for release/i });
    await user.click(screen.getByRole('button', { name: /^cancel$/i }));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: /approve case for release/i }),
      ).not.toBeInTheDocument(),
    );
  });
});

describe('CaseApprovalPanel — reject flow', () => {
  it('requires a reason before rejecting', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="approver" />);
    await user.click(await screen.findByRole('button', { name: /reject/i }));
    await screen.findByRole('heading', { name: /reject case approval/i });
    // The Reject Approval button is disabled with no reason — assert that,
    // then type a reason and confirm it enables.
    const rejectBtn = screen.getByRole('button', {
      name: /reject approval/i,
    });
    expect(rejectBtn).toBeDisabled();
    await user.type(
      screen.getByLabelText(/reason for rejection/i),
      'needs more redaction',
    );
    expect(rejectBtn).toBeEnabled();
  });

  it('posts the rejection and shows success', async () => {
    let body: any = null;
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
      http.post('/api/v1/cases/case-1/reject-approval', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="approver" />);
    await user.click(await screen.findByRole('button', { name: /reject/i }));
    await screen.findByRole('heading', { name: /reject case approval/i });
    await user.type(
      screen.getByLabelText(/reason for rejection/i),
      'incomplete',
    );
    await user.click(
      screen.getByRole('button', { name: /reject approval/i }),
    );
    await waitFor(() => expect(body?.reason).toBe('incomplete'));
    expect(
      await screen.findByText(/case approval rejected/i),
    ).toBeInTheDocument();
  });

  it('shows an error when reject fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/approval-status', () =>
        HttpResponse.json(pendingStatus),
      ),
      http.post('/api/v1/cases/case-1/reject-approval', () =>
        HttpResponse.json({ detail: 'server boom' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseApprovalPanel caseId="case-1" userRole="approver" />);
    await user.click(await screen.findByRole('button', { name: /reject/i }));
    await screen.findByRole('heading', { name: /reject case approval/i });
    await user.type(
      screen.getByLabelText(/reason for rejection/i),
      'incomplete',
    );
    await user.click(
      screen.getByRole('button', { name: /reject approval/i }),
    );
    expect(await screen.findByText(/server boom/i)).toBeInTheDocument();
  });
});
