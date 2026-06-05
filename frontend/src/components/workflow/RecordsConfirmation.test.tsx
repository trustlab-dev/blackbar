import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../../test-utils/render';
import RecordsConfirmation from './RecordsConfirmation';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const CASE_ID = 'case-1';

describe('RecordsConfirmation', () => {
  it('shows the loading state first', () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ confirmed: false });
      }),
    );
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders the in-progress state when records are not confirmed', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({ confirmed: false }),
      ),
    );
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    expect(
      await screen.findByText(/collection in progress/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /confirm all uploaded/i }),
    ).toBeInTheDocument();
  });

  it('renders the confirmed state with attribution', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({
          confirmed: true,
          confirmed_by_name: 'Alice',
          confirmed_at: '2026-05-01T10:00:00Z',
          notes: 'all good',
        }),
      ),
    );
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    expect(
      await screen.findByText(/all records uploaded/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Confirmed by Alice/)).toBeInTheDocument();
    expect(screen.getByText(/all good/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /revoke/i }),
    ).toBeInTheDocument();
  });

  it('treats a 404 as the unconfirmed state without an error', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    );
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    expect(
      await screen.findByText(/collection in progress/i),
    ).toBeInTheDocument();
  });

  it('shows an error alert on a non-404 fetch failure', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    expect(
      await screen.findByText(/failed to load confirmation status/i),
    ).toBeInTheDocument();
  });

  it('confirms records through the dialog', async () => {
    let confirmed = false;
    let postBody: any = null;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({
          confirmed,
          confirmed_by_name: 'Me',
          confirmed_at: '2026-05-02T10:00:00Z',
        }),
      ),
      http.post(
        `/api/v1/cases/${CASE_ID}/records-confirmation`,
        async ({ request }) => {
          postBody = await request.json();
          confirmed = true;
          return HttpResponse.json({ confirmed: true });
        },
      ),
    );
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <RecordsConfirmation caseId={CASE_ID} onConfirmationChange={onChange} />,
    );
    await screen.findByText(/collection in progress/i);
    await user.click(
      screen.getByRole('button', { name: /confirm all uploaded/i }),
    );
    await screen.findByRole('heading', {
      name: /confirm all records uploaded/i,
    });
    await user.type(
      screen.getByLabelText(/notes/i),
      'collection complete',
    );
    await user.click(screen.getByRole('button', { name: /^confirm$/i }));
    await waitFor(() =>
      expect(postBody?.notes).toBe('collection complete'),
    );
    expect(await screen.findByText(/all records uploaded/i)).toBeInTheDocument();
    expect(onChange).toHaveBeenCalled();
  });

  it('shows an error when confirmation fails', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({ confirmed: false }),
      ),
      http.post(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({ detail: 'confirm failed' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    await screen.findByText(/collection in progress/i);
    await user.click(
      screen.getByRole('button', { name: /confirm all uploaded/i }),
    );
    await screen.findByRole('heading', {
      name: /confirm all records uploaded/i,
    });
    await user.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(await screen.findByText(/confirm failed/i)).toBeInTheDocument();
  });

  it('revokes a confirmation after window.confirm', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    let confirmed = true;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({
          confirmed,
          confirmed_by_name: 'Alice',
          confirmed_at: '2026-05-01T10:00:00Z',
        }),
      ),
      http.delete(`/api/v1/cases/${CASE_ID}/records-confirmation`, () => {
        confirmed = false;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    await screen.findByText(/all records uploaded/i);
    await user.click(screen.getByRole('button', { name: /revoke/i }));
    expect(
      await screen.findByText(/collection in progress/i),
    ).toBeInTheDocument();
  });

  it('does not revoke when the confirm is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({
          confirmed: true,
          confirmed_by_name: 'Alice',
          confirmed_at: '2026-05-01T10:00:00Z',
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    await screen.findByText(/all records uploaded/i);
    await user.click(screen.getByRole('button', { name: /revoke/i }));
    expect(screen.getByText(/all records uploaded/i)).toBeInTheDocument();
  });

  it('shows an error when revoke fails', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({
          confirmed: true,
          confirmed_by_name: 'Alice',
          confirmed_at: '2026-05-01T10:00:00Z',
        }),
      ),
      http.delete(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({ detail: 'revoke failed' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    await screen.findByText(/all records uploaded/i);
    await user.click(screen.getByRole('button', { name: /revoke/i }));
    expect(await screen.findByText(/revoke failed/i)).toBeInTheDocument();
  });

  it('cancels the confirm dialog', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/records-confirmation`, () =>
        HttpResponse.json({ confirmed: false }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<RecordsConfirmation caseId={CASE_ID} />);
    await screen.findByText(/collection in progress/i);
    await user.click(
      screen.getByRole('button', { name: /confirm all uploaded/i }),
    );
    await screen.findByRole('heading', {
      name: /confirm all records uploaded/i,
    });
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', {
          name: /confirm all records uploaded/i,
        }),
      ).not.toBeInTheDocument(),
    );
  });
});
