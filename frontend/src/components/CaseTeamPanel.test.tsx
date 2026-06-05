import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import CaseTeamPanel from './CaseTeamPanel';

// Stub UserPicker — it has its own /auth/users/search fetch and MUI
// Autocomplete internals that aren't under test here. The stub exposes a
// plain button so tests can drive the parent's newMemberUserId state.
vi.mock('./UserPicker', () => ({
  default: ({ onChange }: { onChange: (id: string) => void }) => (
    <button type="button" onClick={() => onChange('user-99')}>
      pick-user
    </button>
  ),
}));

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

const analystMember = {
  user_id: 'u-analyst',
  role: 'analyst',
  permissions: [],
  added_at: '2026-05-01T00:00:00Z',
  added_by: 'admin',
  status: 'active',
  user_name: 'Alice Analyst',
};

const legalMember = {
  user_id: 'u-legal',
  role: 'legal',
  department: 'Counsel',
  notes: 'reviews exemptions',
  permissions: [],
  added_at: '2026-05-02T00:00:00Z',
  added_by: 'admin',
  status: 'active',
  user_name: 'Larry Legal',
  approval_status: 'pending',
};

describe('CaseTeamPanel — render', () => {
  it('shows the empty state when there are no team members', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ team_members: [] }),
      ),
    );
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    expect(await screen.findByText(/no team members/i)).toBeInTheDocument();
    expect(screen.getByText(/case team \(0\)/i)).toBeInTheDocument();
  });

  it('renders members with role chips, status badge, department and notes', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ team_members: [analystMember, legalMember] }),
      ),
    );
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    expect(await screen.findByText('Alice Analyst')).toBeInTheDocument();
    expect(screen.getByText('Larry Legal')).toBeInTheDocument();
    expect(screen.getByText('Analyst')).toBeInTheDocument();
    expect(screen.getByText('Legal')).toBeInTheDocument();
    expect(screen.getByText('Counsel')).toBeInTheDocument();
    expect(screen.getByText('reviews exemptions')).toBeInTheDocument();
    expect(screen.getByText(/approval pending/i)).toBeInTheDocument();
    expect(screen.getByText(/case team \(2\)/i)).toBeInTheDocument();
  });

  it('shows an error alert when the team fetch fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ detail: 'forbidden' }, { status: 403 }),
      ),
    );
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    expect(await screen.findByText(/forbidden/i)).toBeInTheDocument();
  });

  it('hides the Add Member button when canManageTeam is false', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ team_members: [legalMember] }),
      ),
    );
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={false} />,
    );
    await screen.findByText('Larry Legal');
    expect(
      screen.queryByRole('button', { name: /add member/i }),
    ).not.toBeInTheDocument();
  });
});

describe('CaseTeamPanel — status badges', () => {
  it('renders review-status badges', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({
          team_members: [
            { ...legalMember, user_id: 'r1', approval_status: undefined, review_status: 'pending', user_name: 'R One' },
            { ...legalMember, user_id: 'r2', approval_status: undefined, review_status: 'approved', user_name: 'R Two' },
            { ...legalMember, user_id: 'r3', approval_status: 'approved', user_name: 'R Three' },
          ],
        }),
      ),
    );
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={false} />,
    );
    expect(await screen.findByText(/review pending/i)).toBeInTheDocument();
    expect(screen.getByText(/review complete/i)).toBeInTheDocument();
    expect(screen.getByText(/^approved$/i)).toBeInTheDocument();
  });
});

describe('CaseTeamPanel — add member', () => {
  it('adds a team member through the dialog', async () => {
    let postBody: any = null;
    let teamCalls = 0;
    server.use(
      http.get('/api/v1/cases/case-1/team', () => {
        teamCalls += 1;
        return HttpResponse.json({
          team_members: teamCalls > 1 ? [legalMember] : [],
        });
      }),
      http.post('/api/v1/cases/case-1/team/members', async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    await screen.findByText(/no team members/i);
    await user.click(screen.getByRole('button', { name: /add member/i }));
    await screen.findByRole('heading', { name: /add team member/i });
    // The stubbed UserPicker sets the user id when clicked.
    await user.click(screen.getByRole('button', { name: /pick-user/i }));
    await user.click(
      screen.getByRole('button', { name: /^add member$/i }),
    );
    await waitFor(() => expect(postBody?.user_id).toBe('user-99'));
    expect(postBody.role).toBe('legal');
    // Team list refetches after a successful add.
    expect(await screen.findByText('Larry Legal')).toBeInTheDocument();
  });

  it('shows an error when adding a member fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ team_members: [] }),
      ),
      http.post('/api/v1/cases/case-1/team/members', () =>
        HttpResponse.json({ detail: 'duplicate member' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    await screen.findByText(/no team members/i);
    await user.click(screen.getByRole('button', { name: /add member/i }));
    await screen.findByRole('heading', { name: /add team member/i });
    await user.click(screen.getByRole('button', { name: /pick-user/i }));
    await user.click(
      screen.getByRole('button', { name: /^add member$/i }),
    );
    expect(await screen.findByText(/duplicate member/i)).toBeInTheDocument();
  });

  it('cancels the add-member dialog', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ team_members: [] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    await screen.findByText(/no team members/i);
    await user.click(screen.getByRole('button', { name: /add member/i }));
    await screen.findByRole('heading', { name: /add team member/i });
    await user.click(screen.getByRole('button', { name: /^cancel$/i }));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: /add team member/i }),
      ).not.toBeInTheDocument(),
    );
  });
});

describe('CaseTeamPanel — remove member', () => {
  it('removes a non-analyst member', async () => {
    let deleted = false;
    let teamCalls = 0;
    server.use(
      http.get('/api/v1/cases/case-1/team', () => {
        teamCalls += 1;
        return HttpResponse.json({
          team_members: teamCalls > 1 ? [] : [legalMember],
        });
      }),
      http.delete('/api/v1/cases/case-1/team/members/u-legal', () => {
        deleted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    await screen.findByText('Larry Legal');
    // The delete IconButton has no accessible name; grab it by role.
    await user.click(screen.getByRole('button', { name: '' }));
    await waitFor(() => expect(deleted).toBe(true));
    expect(await screen.findByText(/no team members/i)).toBeInTheDocument();
  });

  it('does not remove when the confirm dialog is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    let deleted = false;
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ team_members: [legalMember] }),
      ),
      http.delete('/api/v1/cases/case-1/team/members/u-legal', () => {
        deleted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    await screen.findByText('Larry Legal');
    await user.click(screen.getByRole('button', { name: '' }));
    expect(deleted).toBe(false);
  });

  it('shows an error when removing a member fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ team_members: [legalMember] }),
      ),
      http.delete('/api/v1/cases/case-1/team/members/u-legal', () =>
        HttpResponse.json({ detail: 'cannot remove' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    await screen.findByText('Larry Legal');
    await user.click(screen.getByRole('button', { name: '' }));
    expect(await screen.findByText(/cannot remove/i)).toBeInTheDocument();
  });

  it('does not show a remove button for analyst members', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json({ team_members: [analystMember] }),
      ),
    );
    renderWithProviders(
      <CaseTeamPanel caseId="case-1" canManageTeam={true} />,
    );
    await screen.findByText('Alice Analyst');
    // Only the Add Member button is present; no unnamed delete IconButton.
    expect(
      screen.queryByRole('button', { name: '' }),
    ).not.toBeInTheDocument();
  });
});
