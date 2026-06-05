// Vitest hoists vi.mock(...) calls to the top of the file, so axios is
// wrapped before any import statement is evaluated.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('axios', async () => {
  const actual = await vi.importActual<any>('axios');
  const origCreate = actual.default.create.bind(actual.default);
  actual.default.create = (config: any = {}) =>
    origCreate({ ...config, adapter: 'fetch' });
  return actual;
});

// Stub window.location BEFORE importing the component module so its
// module-level getBaseURL() resolves with https + host (the absolute-URL
// branch). The vi.hoisted helper guarantees this runs before any import.
const { __locStub } = vi.hoisted(() => {
  Object.defineProperty(window, 'location', {
    value: {
      protocol: 'https:',
      host: 'localhost:3000',
      hostname: 'localhost',
      pathname: '/',
      search: '',
      href: 'https://localhost:3000/',
    },
    writable: true,
  });
  return { __locStub: true };
});
void __locStub;

import { http, HttpResponse } from 'msw';
import { Routes, Route } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import {
  renderWithProviders,
  screen,
  waitFor,
  within,
} from '../../test-utils/render';
import ContributorPortal from './ContributorPortal';

const API_BASE = 'https://localhost:3000/api/v1';

function Harness() {
  return (
    <Routes>
      <Route
        path="/contribute/:contributorId"
        element={<ContributorPortal />}
      />
    </Routes>
  );
}

interface InfoOverrides {
  is_expired?: boolean;
  records_confirmed?: boolean;
  uploaded_documents?: Array<{
    id: string;
    filename: string;
    uploaded_at: string;
  }>;
}

function makeInfoResponse(overrides: InfoOverrides = {}) {
  const docs = overrides.uploaded_documents ?? [];
  return {
    contributor_id: 'c-1',
    contributor_name: 'Jane Contributor',
    case_tracking_number: 'CASE-001',
    case_title: 'Test Records Request',
    org_name: 'Test Org',
    documents_uploaded: docs.length,
    uploaded_documents: docs,
    is_expired: overrides.is_expired ?? false,
    expires_at: '2026-12-31T23:59:59Z',
    records_confirmed: overrides.records_confirmed ?? false,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ContributorPortal — initial render', () => {
  it('renders loading spinner before info loads', () => {
    server.use(
      http.get(
        `${API_BASE}/contribute/c-1`,
        () => new Promise(() => {}),
      ),
    );
    renderWithProviders(<Harness />, {
      route: '/contribute/c-1?token=tok',
    });
    expect(
      document.querySelector('.MuiCircularProgress-root'),
    ).toBeInTheDocument();
  });

  it('shows error when contributorId is present but token is missing', async () => {
    renderWithProviders(<Harness />, { route: '/contribute/c-1' });
    await waitFor(() =>
      expect(screen.getByText(/access error/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/invalid or missing access token/i),
    ).toBeInTheDocument();
  });
});

describe('ContributorPortal — info fetch', () => {
  it('renders contributor details, case info, and empty document list', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(makeInfoResponse()),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    expect(
      await screen.findByText(/records upload portal/i),
    ).toBeInTheDocument();
    expect(screen.getByText('Jane Contributor')).toBeInTheDocument();
    expect(screen.getByText(/Test Records Request/i)).toBeInTheDocument();
    expect(screen.getByText(/CASE-001/)).toBeInTheDocument();
    expect(screen.getByText(/no documents uploaded yet/i)).toBeInTheDocument();
  });

  it('renders the document table when there are uploaded docs', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(
          makeInfoResponse({
            uploaded_documents: [
              {
                id: 'doc-1',
                filename: 'budget-2024.pdf',
                uploaded_at: '2026-05-01T10:00:00Z',
              },
              {
                id: 'doc-2',
                filename: 'memo.docx',
                uploaded_at: '2026-05-02T11:30:00Z',
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    expect(await screen.findByText('budget-2024.pdf')).toBeInTheDocument();
    expect(screen.getByText('memo.docx')).toBeInTheDocument();
    expect(
      screen.getByText(/uploaded documents \(2\)/i),
    ).toBeInTheDocument();
  });

  it('shows expired banner when is_expired is true', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(makeInfoResponse({ is_expired: true })),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    await waitFor(() =>
      expect(screen.getByText(/this link has expired/i)).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/select files to upload/i),
    ).not.toBeInTheDocument();
  });

  it('shows confirmed banner and hides upload section when records_confirmed is true', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(makeInfoResponse({ records_confirmed: true })),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    expect(
      await screen.findByText(
        /you have confirmed that all records have been submitted/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/select files to upload/i),
    ).not.toBeInTheDocument();
  });
});

describe('ContributorPortal — error states on info fetch', () => {
  it('shows expired/invalid message on 401', async () => {
    server.use(
      http.get(
        `${API_BASE}/contribute/c-1`,
        () => new HttpResponse(null, { status: 401 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    expect(
      await screen.findByText(/this link has expired or is invalid/i),
    ).toBeInTheDocument();
  });

  it('shows expired/invalid message on 403', async () => {
    server.use(
      http.get(
        `${API_BASE}/contribute/c-1`,
        () => new HttpResponse(null, { status: 403 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    expect(
      await screen.findByText(/this link has expired or is invalid/i),
    ).toBeInTheDocument();
  });

  it('shows contributor-not-found message on 404', async () => {
    server.use(
      http.get(
        `${API_BASE}/contribute/c-1`,
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    expect(
      await screen.findByText(/contributor not found/i),
    ).toBeInTheDocument();
  });

  it('shows generic message on other errors', async () => {
    server.use(
      http.get(
        `${API_BASE}/contribute/c-1`,
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    expect(
      await screen.findByText(/failed to load contributor information/i),
    ).toBeInTheDocument();
  });
});

describe('ContributorPortal — upload flow', () => {
  it('uploads files via the file input and refreshes the document list', async () => {
    let infoCalls = 0;
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () => {
        infoCalls++;
        return HttpResponse.json(
          makeInfoResponse({
            uploaded_documents:
              infoCalls === 1
                ? []
                : [
                    {
                      id: 'doc-new',
                      filename: 'test.txt',
                      uploaded_at: '2026-05-13T10:00:00Z',
                    },
                  ],
          }),
        );
      }),
      http.post(`${API_BASE}/contribute/c-1/upload`, () =>
        HttpResponse.json({ id: 'doc-new' }),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    await screen.findByText(/select files to upload/i);

    const file = new File(['hi'], 'test.txt', { type: 'text/plain' });
    const input = document.getElementById('file-upload') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));

    await waitFor(() =>
      expect(
        screen.getByText(/successfully uploaded 1 file/i),
      ).toBeInTheDocument(),
    );
    expect(await screen.findByText('test.txt')).toBeInTheDocument();
  });

  it('does nothing when the input change has no files', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(makeInfoResponse()),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    await screen.findByText(/select files to upload/i);
    const input = document.getElementById('file-upload') as HTMLInputElement;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    expect(screen.queryByText(/uploading\.\.\./i)).not.toBeInTheDocument();
  });

  it('surfaces backend error detail when upload fails', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(makeInfoResponse()),
      ),
      http.post(`${API_BASE}/contribute/c-1/upload`, () =>
        HttpResponse.json({ detail: 'File too large' }, { status: 413 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    await screen.findByText(/select files to upload/i);

    const file = new File(['hi'], 'big.pdf', { type: 'application/pdf' });
    const input = document.getElementById('file-upload') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));

    await waitFor(() =>
      expect(screen.getByText('File too large')).toBeInTheDocument(),
    );
  });

  it('falls back to default upload error message when no detail provided', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(makeInfoResponse()),
      ),
      http.post(
        `${API_BASE}/contribute/c-1/upload`,
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    await screen.findByText(/select files to upload/i);

    const file = new File(['hi'], 'broken.pdf', { type: 'application/pdf' });
    const input = document.getElementById('file-upload') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));

    await waitFor(() =>
      expect(screen.getByText(/failed to upload file/i)).toBeInTheDocument(),
    );
  });
});

describe('ContributorPortal — confirm complete', () => {
  it('renders the confirm button only when there are uploaded documents and not confirmed', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(
          makeInfoResponse({
            uploaded_documents: [
              {
                id: 'd1',
                filename: 'f.pdf',
                uploaded_at: '2026-05-01T10:00:00Z',
              },
            ],
          }),
        ),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    expect(
      await screen.findByRole('button', {
        name: /confirm all records submitted/i,
      }),
    ).toBeInTheDocument();
  });

  it('does NOT render the confirm button when there are no uploaded documents', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(makeInfoResponse()),
      ),
    );
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    await screen.findByText(/select files to upload/i);
    expect(
      screen.queryByRole('button', {
        name: /confirm all records submitted/i,
      }),
    ).not.toBeInTheDocument();
  });

  it('successfully confirms submission and shows success message', async () => {
    let confirmCalls = 0;
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(
          makeInfoResponse({
            records_confirmed: confirmCalls > 0,
            uploaded_documents: [
              {
                id: 'd1',
                filename: 'f.pdf',
                uploaded_at: '2026-05-01T10:00:00Z',
              },
            ],
          }),
        ),
      ),
      http.post(`${API_BASE}/contribute/c-1/confirm-complete`, () => {
        confirmCalls++;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    const confirmBtn = await screen.findByRole('button', {
      name: /confirm all records submitted/i,
    });
    await user.click(confirmBtn);

    await waitFor(() =>
      expect(
        screen.getByText(
          /thank you! your records submission has been confirmed/i,
        ),
      ).toBeInTheDocument(),
    );
  });

  it('surfaces backend detail on confirm failure', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(
          makeInfoResponse({
            uploaded_documents: [
              {
                id: 'd1',
                filename: 'f.pdf',
                uploaded_at: '2026-05-01T10:00:00Z',
              },
            ],
          }),
        ),
      ),
      http.post(`${API_BASE}/contribute/c-1/confirm-complete`, () =>
        HttpResponse.json({ detail: 'Already confirmed' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    const confirmBtn = await screen.findByRole('button', {
      name: /confirm all records submitted/i,
    });
    await user.click(confirmBtn);

    await waitFor(() =>
      expect(screen.getByText('Already confirmed')).toBeInTheDocument(),
    );
  });

  it('falls back to default confirm error when no detail provided', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(
          makeInfoResponse({
            uploaded_documents: [
              {
                id: 'd1',
                filename: 'f.pdf',
                uploaded_at: '2026-05-01T10:00:00Z',
              },
            ],
          }),
        ),
      ),
      http.post(
        `${API_BASE}/contribute/c-1/confirm-complete`,
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    const confirmBtn = await screen.findByRole('button', {
      name: /confirm all records submitted/i,
    });
    await user.click(confirmBtn);

    await waitFor(() =>
      expect(
        screen.getByText(/failed to confirm submission/i),
      ).toBeInTheDocument(),
    );
  });
});

describe('ContributorPortal — alert dismissal', () => {
  it('allows dismissing the success alert via close button', async () => {
    let confirmCalls = 0;
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(
          makeInfoResponse({
            records_confirmed: confirmCalls > 0,
            uploaded_documents: [
              {
                id: 'd1',
                filename: 'f.pdf',
                uploaded_at: '2026-05-01T10:00:00Z',
              },
            ],
          }),
        ),
      ),
      http.post(`${API_BASE}/contribute/c-1/confirm-complete`, () => {
        confirmCalls++;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    await user.click(
      await screen.findByRole('button', {
        name: /confirm all records submitted/i,
      }),
    );

    const successAlert = await screen.findByText(/thank you!/i);
    const alert = successAlert.closest('[role="alert"]') as HTMLElement;
    await user.click(within(alert).getByRole('button', { name: /close/i }));
    expect(screen.queryByText(/thank you!/i)).not.toBeInTheDocument();
  });

  it('allows dismissing the error alert via close button', async () => {
    server.use(
      http.get(`${API_BASE}/contribute/c-1`, () =>
        HttpResponse.json(
          makeInfoResponse({
            uploaded_documents: [
              {
                id: 'd1',
                filename: 'f.pdf',
                uploaded_at: '2026-05-01T10:00:00Z',
              },
            ],
          }),
        ),
      ),
      http.post(
        `${API_BASE}/contribute/c-1/confirm-complete`,
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/contribute/c-1?token=tok' });
    await user.click(
      await screen.findByRole('button', {
        name: /confirm all records submitted/i,
      }),
    );

    const errText = await screen.findByText(/failed to confirm submission/i);
    const alert = errText.closest('[role="alert"]') as HTMLElement;
    await user.click(within(alert).getByRole('button', { name: /close/i }));
    expect(
      screen.queryByText(/failed to confirm submission/i),
    ).not.toBeInTheDocument();
  });
});
