import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor, within } from '../../test-utils/render';
import ContributorsPanel from './ContributorsPanel';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const CASE_ID = 'case-1';

const contributor = {
  id: 'contrib-1',
  case_id: CASE_ID,
  name: 'Bob Records',
  email: 'bob@example.com',
  department: 'HR',
  status: 'invited',
  documents_uploaded: 0,
  invited_by: 'u1',
  created_at: '2026-05-01T00:00:00Z',
  token_expires_at: '2026-06-01T00:00:00Z',
};

describe('ContributorsPanel', () => {
  it('shows the spinner, then the empty state', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([]),
      ),
    );
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(
      await screen.findByText(/no contributors invited yet/i),
    ).toBeInTheDocument();
  });

  it('renders contributors in a table', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([contributor]),
      ),
    );
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    expect(await screen.findByText('Bob Records')).toBeInTheDocument();
    expect(screen.getByText('bob@example.com')).toBeInTheDocument();
    expect(screen.getByText('HR')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });

  it('renders the various status chips', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([
          { ...contributor, id: 'c1', name: 'A', status: 'completed' },
          {
            ...contributor,
            id: 'c2',
            name: 'B',
            status: 'active',
            documents_uploaded: 2,
          },
          {
            ...contributor,
            id: 'c3',
            name: 'C',
            status: 'active',
            documents_uploaded: 0,
          },
          { ...contributor, id: 'c4', name: 'D', status: 'expired' },
        ]),
      ),
    );
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText('A');
    expect(screen.getByText('Complete')).toBeInTheDocument();
    expect(screen.getByText('Uploading')).toBeInTheDocument();
    expect(screen.getByText('Accessed')).toBeInTheDocument();
    expect(screen.getByText('Expired')).toBeInTheDocument();
  });

  it('treats a 404 list as empty without an error', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    );
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    expect(
      await screen.findByText(/no contributors invited yet/i),
    ).toBeInTheDocument();
  });

  it('shows an error on a non-404 fetch failure', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    expect(
      await screen.findByText(/failed to load contributors/i),
    ).toBeInTheDocument();
  });

  it('invites a contributor through the dialog', async () => {
    let invited = false;
    let postBody: any = null;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json(invited ? [contributor] : []),
      ),
      http.post(
        `/api/v1/cases/${CASE_ID}/contributors`,
        async ({ request }) => {
          postBody = await request.json();
          invited = true;
          return HttpResponse.json({
            contributor,
            upload_url: '/upload/abc',
            expires_at: '2026-06-01T00:00:00Z',
          });
        },
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText(/no contributors invited yet/i);
    await user.click(screen.getByRole('button', { name: /^invite$/i }));
    await screen.findByRole('heading', { name: /invite record contributor/i });
    await user.type(screen.getByLabelText(/^name/i), 'Bob Records');
    await user.type(screen.getByLabelText(/^email/i), 'bob@example.com');
    await user.click(
      screen.getByRole('button', { name: /send invitation/i }),
    );
    await waitFor(() => expect(postBody?.email).toBe('bob@example.com'));
    // Upload-URL dialog appears with the absolute link
    expect(
      await screen.findByRole('heading', { name: /invitation sent/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/\/upload\/abc/)).toBeInTheDocument();
  });

  it('shows an error when the invite fails', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([]),
      ),
      http.post(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json({ detail: 'invite failed' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText(/no contributors invited yet/i);
    await user.click(screen.getByRole('button', { name: /^invite$/i }));
    await screen.findByRole('heading', { name: /invite record contributor/i });
    await user.type(screen.getByLabelText(/^name/i), 'X');
    await user.type(screen.getByLabelText(/^email/i), 'x@example.com');
    await user.click(
      screen.getByRole('button', { name: /send invitation/i }),
    );
    expect(await screen.findByText(/invite failed/i)).toBeInTheDocument();
  });

  it('sends a reminder to a contributor', async () => {
    let reminded = false;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([contributor]),
      ),
      http.post(
        `/api/v1/cases/${CASE_ID}/contributors/contrib-1/remind`,
        () => {
          reminded = true;
          return HttpResponse.json({ ok: true });
        },
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText('Bob Records');
    // The actions cell reminder button is the first IconButton wrapping an EmailIcon.
    const row = screen.getByText('Bob Records').closest('tr')!;
    const emailBtn = within(row)
      .getAllByTestId('EmailIcon')
      .map((i) => i.closest('button'))
      .find((b): b is HTMLButtonElement => b !== null)!;
    await user.click(emailBtn);
    expect(
      await screen.findByText(/reminder sent to bob@example.com/i),
    ).toBeInTheDocument();
    expect(reminded).toBe(true);
  });

  it('deletes a contributor after window.confirm', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    let deleted = false;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json(deleted ? [] : [contributor]),
      ),
      http.delete(
        `/api/v1/cases/${CASE_ID}/contributors/contrib-1`,
        () => {
          deleted = true;
          return HttpResponse.json({ ok: true });
        },
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText('Bob Records');
    await user.click(screen.getByTestId('DeleteIcon').closest('button')!);
    expect(
      await screen.findByText(/no contributors invited yet/i),
    ).toBeInTheDocument();
  });

  it('does not delete when the confirm is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([contributor]),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText('Bob Records');
    await user.click(screen.getByTestId('DeleteIcon').closest('button')!);
    expect(screen.getByText('Bob Records')).toBeInTheDocument();
  });

  it('bulk-invites contributors from pasted text', async () => {
    let bulkBody: any = null;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([]),
      ),
      http.post(
        `/api/v1/cases/${CASE_ID}/contributors/bulk`,
        async ({ request }) => {
          bulkBody = await request.json();
          return HttpResponse.json({
            invitations: [
              {
                contributor: { ...contributor, name: 'John Smith' },
                upload_url: '/upload/john',
                expires_at: '2026-06-01T00:00:00Z',
              },
            ],
            count: 1,
          });
        },
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText(/no contributors invited yet/i);
    await user.click(screen.getByRole('button', { name: /bulk/i }));
    await screen.findByRole('heading', { name: /bulk invite contributors/i });
    const textarea = screen.getByPlaceholderText(/john smith/i);
    await user.type(textarea, 'John Smith, john@example.com, HR');
    await user.click(
      screen.getByRole('button', { name: /send invitations/i }),
    );
    await waitFor(() =>
      expect(bulkBody?.contributors?.[0]?.email).toBe('john@example.com'),
    );
    expect(
      await screen.findByRole('heading', { name: /invitations sent/i }),
    ).toBeInTheDocument();
    expect(screen.getByText('John Smith')).toBeInTheDocument();
  });

  it('rejects bulk text with no valid rows', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([]),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText(/no contributors invited yet/i);
    await user.click(screen.getByRole('button', { name: /bulk/i }));
    await screen.findByRole('heading', { name: /bulk invite contributors/i });
    const textarea = screen.getByPlaceholderText(/john smith/i);
    // a line with only a name (no email) yields zero valid contributors
    await user.type(textarea, 'OnlyName');
    await user.click(
      screen.getByRole('button', { name: /send invitations/i }),
    );
    expect(
      await screen.findByText(/no valid contributors found/i),
    ).toBeInTheDocument();
  });

  it('copies an upload link to the clipboard', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json([]),
      ),
      http.post(`/api/v1/cases/${CASE_ID}/contributors`, () =>
        HttpResponse.json({
          contributor,
          upload_url: '/upload/abc',
          expires_at: '2026-06-01T00:00:00Z',
        }),
      ),
    );
    const user = userEvent.setup();
    // userEvent.setup() installs its own clipboard stub — spy AFTER setup.
    const writeText = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockResolvedValue(undefined);
    renderWithProviders(<ContributorsPanel caseId={CASE_ID} />);
    await screen.findByText(/no contributors invited yet/i);
    await user.click(screen.getByRole('button', { name: /^invite$/i }));
    await screen.findByRole('heading', { name: /invite record contributor/i });
    await user.type(screen.getByLabelText(/^name/i), 'Bob');
    await user.type(screen.getByLabelText(/^email/i), 'bob@example.com');
    await user.click(
      screen.getByRole('button', { name: /send invitation/i }),
    );
    const urlDialog = await screen.findByRole('heading', {
      name: /invitation sent/i,
    });
    const dialog = urlDialog.closest('.MuiDialog-root')!;
    await user.click(within(dialog).getByTestId('ContentCopyIcon'));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining('/upload/abc'),
      ),
    );
  });
});
