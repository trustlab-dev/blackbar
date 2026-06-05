import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor, within } from '../../test-utils/render';
import TransferCase from './TransferCase';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const CASE_ID = 'case-1';

const transfer = {
  id: 't1',
  case_id: CASE_ID,
  tracking_number: 'FOI-001',
  recipient_organization: 'City of Vancouver',
  recipient_email: 'foi@vancouver.ca',
  include_documents: false,
  transfer_reason: 'Wrong jurisdiction',
  status: 'pending',
  transferred_by: 'u1',
  transferred_at: '2026-05-01T00:00:00Z',
  token_expires_at: '2026-06-01T00:00:00Z',
};

const documents = [
  { id: 'doc-1', original_filename: 'report.pdf', status: 'processed' },
  { id: 'doc-2', original_filename: 'memo.pdf', status: 'processed' },
];

function mockBase({
  transfers = [] as any[],
  docs = [] as any[],
} = {}) {
  server.use(
    http.get(`/api/v1/cases/${CASE_ID}/transfers`, () =>
      HttpResponse.json(transfers),
    ),
    http.get(`/api/v1/cases/${CASE_ID}/documents`, () =>
      HttpResponse.json(docs),
    ),
  );
}

describe('TransferCase', () => {
  it('shows the spinner, then the empty state', async () => {
    mockBase();
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(
      await screen.findByText(/no transfers yet/i),
    ).toBeInTheDocument();
  });

  it('renders existing transfers in a table', async () => {
    mockBase({ transfers: [transfer] });
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    expect(await screen.findByText('City of Vancouver')).toBeInTheDocument();
    expect(screen.getByText('foi@vancouver.ca')).toBeInTheDocument();
    expect(screen.getByText('Wrong jurisdiction')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });

  it('renders the various status chips', async () => {
    mockBase({
      transfers: [
        { ...transfer, id: 't1', status: 'downloaded' },
        { ...transfer, id: 't2', status: 'accessed' },
        { ...transfer, id: 't3', status: 'expired' },
      ],
    });
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    expect(await screen.findByText('Downloaded')).toBeInTheDocument();
    expect(screen.getByText('Accessed')).toBeInTheDocument();
    expect(screen.getByText('Expired')).toBeInTheDocument();
  });

  it('treats a 404 transfers list as empty', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/transfers`, () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
      http.get(`/api/v1/cases/${CASE_ID}/documents`, () =>
        HttpResponse.json([]),
      ),
    );
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    expect(await screen.findByText(/no transfers yet/i)).toBeInTheDocument();
  });

  it('shows an error on a non-404 transfers fetch failure', async () => {
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/transfers`, () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
      http.get(`/api/v1/cases/${CASE_ID}/documents`, () =>
        HttpResponse.json([]),
      ),
    );
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    expect(
      await screen.findByText(/failed to load transfers/i),
    ).toBeInTheDocument();
  });

  it('creates a transfer through the dialog', async () => {
    let created = false;
    let postBody: any = null;
    server.use(
      http.get(`/api/v1/cases/${CASE_ID}/transfers`, () =>
        HttpResponse.json(created ? [transfer] : []),
      ),
      http.get(`/api/v1/cases/${CASE_ID}/documents`, () =>
        HttpResponse.json([]),
      ),
      http.post(
        `/api/v1/cases/${CASE_ID}/transfer`,
        async ({ request }) => {
          postBody = await request.json();
          created = true;
          return HttpResponse.json({
            transfer,
            transfer_url: '/transfer/abc',
            expires_at: '2026-06-01T00:00:00Z',
          });
        },
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    await screen.findByText(/no transfers yet/i);
    await user.click(screen.getByRole('button', { name: /^transfer$/i }));
    await screen.findByRole('heading', {
      name: /transfer request to another public body/i,
    });
    await user.type(
      screen.getByLabelText(/recipient organization/i),
      'City of Vancouver',
    );
    await user.type(
      screen.getByLabelText(/recipient email/i),
      'foi@vancouver.ca',
    );
    await user.type(
      screen.getByLabelText(/reason for transfer/i),
      'Wrong jurisdiction',
    );
    await user.click(
      screen.getByRole('button', { name: /transfer request/i }),
    );
    await waitFor(() =>
      expect(postBody?.recipient_organization).toBe('City of Vancouver'),
    );
    expect(
      await screen.findByRole('heading', { name: /transfer initiated/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/\/transfer\/abc/)).toBeInTheDocument();
  });

  it('shows an error when the transfer fails', async () => {
    mockBase();
    server.use(
      http.post(`/api/v1/cases/${CASE_ID}/transfer`, () =>
        HttpResponse.json({ detail: 'transfer failed' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    await screen.findByText(/no transfers yet/i);
    await user.click(screen.getByRole('button', { name: /^transfer$/i }));
    await screen.findByRole('heading', {
      name: /transfer request to another public body/i,
    });
    await user.type(
      screen.getByLabelText(/recipient organization/i),
      'Org',
    );
    await user.type(
      screen.getByLabelText(/recipient email/i),
      'o@example.com',
    );
    await user.type(
      screen.getByLabelText(/reason for transfer/i),
      'Reason',
    );
    await user.click(
      screen.getByRole('button', { name: /transfer request/i }),
    );
    expect(await screen.findByText(/transfer failed/i)).toBeInTheDocument();
  });

  it('shows the document picker when "include documents" is checked', async () => {
    mockBase({ docs: documents });
    const user = userEvent.setup();
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    await screen.findByText(/no transfers yet/i);
    await user.click(screen.getByRole('button', { name: /^transfer$/i }));
    await screen.findByRole('heading', {
      name: /transfer request to another public body/i,
    });
    await user.click(
      screen.getByRole('checkbox', { name: /include documents in transfer/i }),
    );
    expect(await screen.findByText('report.pdf')).toBeInTheDocument();
    expect(screen.getByText('memo.pdf')).toBeInTheDocument();
    // all docs selected by default
    expect(screen.getByText(/2 of 2 selected/i)).toBeInTheDocument();
    // clear, then select-all
    await user.click(screen.getByRole('button', { name: /^clear$/i }));
    expect(screen.getByText(/0 of 2 selected/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /select all/i }));
    expect(screen.getByText(/2 of 2 selected/i)).toBeInTheDocument();
  });

  it('shows the no-documents note when include is checked but none exist', async () => {
    mockBase({ docs: [] });
    const user = userEvent.setup();
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    await screen.findByText(/no transfers yet/i);
    await user.click(screen.getByRole('button', { name: /^transfer$/i }));
    await screen.findByRole('heading', {
      name: /transfer request to another public body/i,
    });
    await user.click(
      screen.getByRole('checkbox', { name: /include documents in transfer/i }),
    );
    expect(
      await screen.findByText(/no documents uploaded to this case yet/i),
    ).toBeInTheDocument();
  });

  it('toggles individual document checkboxes', async () => {
    mockBase({ docs: documents });
    const user = userEvent.setup();
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    await screen.findByText(/no transfers yet/i);
    await user.click(screen.getByRole('button', { name: /^transfer$/i }));
    await screen.findByRole('heading', {
      name: /transfer request to another public body/i,
    });
    await user.click(
      screen.getByRole('checkbox', { name: /include documents in transfer/i }),
    );
    await screen.findByText('report.pdf');
    const reportCheckbox = screen
      .getByText('report.pdf')
      .closest('label')!
      .querySelector('input')!;
    await user.click(reportCheckbox); // uncheck
    expect(screen.getByText(/1 of 2 selected/i)).toBeInTheDocument();
    await user.click(reportCheckbox); // re-check
    expect(screen.getByText(/2 of 2 selected/i)).toBeInTheDocument();
  });

  it('cancels the transfer dialog', async () => {
    mockBase();
    const user = userEvent.setup();
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    await screen.findByText(/no transfers yet/i);
    await user.click(screen.getByRole('button', { name: /^transfer$/i }));
    await screen.findByRole('heading', {
      name: /transfer request to another public body/i,
    });
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', {
          name: /transfer request to another public body/i,
        }),
      ).not.toBeInTheDocument(),
    );
  });

  it('copies the transfer link to the clipboard', async () => {
    mockBase();
    server.use(
      http.post(`/api/v1/cases/${CASE_ID}/transfer`, () =>
        HttpResponse.json({
          transfer,
          transfer_url: '/transfer/abc',
          expires_at: '2026-06-01T00:00:00Z',
        }),
      ),
    );
    const user = userEvent.setup();
    // userEvent.setup() installs its own clipboard stub — spy AFTER setup.
    const writeText = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockResolvedValue(undefined);
    renderWithProviders(<TransferCase caseId={CASE_ID} />);
    await screen.findByText(/no transfers yet/i);
    await user.click(screen.getByRole('button', { name: /^transfer$/i }));
    await screen.findByRole('heading', {
      name: /transfer request to another public body/i,
    });
    await user.type(
      screen.getByLabelText(/recipient organization/i),
      'Org',
    );
    await user.type(
      screen.getByLabelText(/recipient email/i),
      'o@example.com',
    );
    await user.type(
      screen.getByLabelText(/reason for transfer/i),
      'Reason',
    );
    await user.click(
      screen.getByRole('button', { name: /transfer request/i }),
    );
    const heading = await screen.findByRole('heading', {
      name: /transfer initiated/i,
    });
    const dialog = heading.closest('.MuiDialog-root')!;
    await user.click(within(dialog).getByTestId('ContentCopyIcon'));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining('/transfer/abc'),
      ),
    );
  });
});
