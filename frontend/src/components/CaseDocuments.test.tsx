import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import CaseDocuments from './CaseDocuments';
import api from '../api/client';

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

const baseDoc = {
  id: 'doc-1',
  filename: 'report.pdf',
  content_type: 'application/pdf',
  mime_type: 'application/pdf',
  size: 12345,
  upload_date: '2026-05-10T12:00:00Z',
  uploaded_by: 'user-1',
  uploaded_by_name: 'Alice',
  status: 'new',
};

beforeEach(() => {
  mockNavigate.mockReset();
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(window, 'alert').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
  // Stub URL.createObjectURL/revokeObjectURL for download tests
  if (!('createObjectURL' in URL))
    (URL as any).createObjectURL = vi.fn(() => 'blob:fake');
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fake');
  if (!('revokeObjectURL' in URL))
    (URL as any).revokeObjectURL = vi.fn();
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('CaseDocuments — initial render', () => {
  it('shows loading then empty state when no documents', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    renderWithProviders(<CaseDocuments />);
    expect(screen.getByText(/loading documents/i)).toBeInTheDocument();
    expect(
      await screen.findByText(/no documents uploaded yet/i),
    ).toBeInTheDocument();
  });

  it('renders a document row with file size and download/share/delete actions', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    renderWithProviders(<CaseDocuments />);
    expect(await screen.findByText('report.pdf')).toBeInTheDocument();
    expect(screen.getByText(/12\.06 KB/)).toBeInTheDocument();
    expect(screen.getByTitle(/^download$/i)).toBeInTheDocument();
    expect(screen.getByTitle(/share with guest/i)).toBeInTheDocument();
    expect(screen.getByTitle(/^delete$/i)).toBeInTheDocument();
  });

  it('shows search empty state when query matches nothing', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    await user.type(screen.getByPlaceholderText(/search documents/i), 'xxx');
    expect(
      await screen.findByText(/no documents match your search/i),
    ).toBeInTheDocument();
  });

  it('navigates back to case when "Back to Case" is clicked', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText(/no documents uploaded yet/i);
    await user.click(screen.getByRole('button', { name: /back to case/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/cases/case-1');
  });
});

describe('CaseDocuments — sorting & filtering', () => {
  const docs = [
    { ...baseDoc, id: 'd1', filename: 'a.pdf', size: 100, upload_date: '2026-01-01T00:00:00Z' },
    { ...baseDoc, id: 'd2', filename: 'b.pdf', size: 500, upload_date: '2026-03-01T00:00:00Z', status: 'approved' },
  ];

  it('toggles sort order via arrow button', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: docs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('a.pdf');
    const orderBtn = screen.getByText('↓');
    await user.click(orderBtn);
    expect(screen.getByText('↑')).toBeInTheDocument();
  });

  it('changes sort field via dropdown', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: docs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('a.pdf');
    const sortSelect = screen.getByDisplayValue('Date');
    await user.selectOptions(sortSelect, 'name');
    expect(sortSelect).toHaveValue('name');
    await user.selectOptions(sortSelect, 'size');
    expect(sortSelect).toHaveValue('size');
  });

  it('filters by workflow status', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: docs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('a.pdf');
    const statusFilter = screen.getByDisplayValue('All Statuses');
    await user.selectOptions(statusFilter, 'approved');
    await waitFor(() =>
      expect(screen.queryByText('a.pdf')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('b.pdf')).toBeInTheDocument();
  });
});

describe('CaseDocuments — selection and bulk actions', () => {
  const docs = [
    { ...baseDoc, id: 'd1', filename: 'a.pdf' },
    { ...baseDoc, id: 'd2', filename: 'b.pdf' },
  ];

  it('selects/deselects via row checkboxes and shows bulk-action bar', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: docs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('a.pdf');
    const checkboxes = screen.getAllByRole('checkbox');
    // checkboxes[0] is the select-all header
    await user.click(checkboxes[1]);
    expect(screen.getByText(/1 selected/i)).toBeInTheDocument();
    await user.click(checkboxes[1]);
    expect(screen.queryByText(/1 selected/i)).not.toBeInTheDocument();
  });

  it('select-all selects every doc; clicking again clears', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: docs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('a.pdf');
    const checkboxes = screen.getAllByRole('checkbox');
    await user.click(checkboxes[0]);
    expect(screen.getByText(/2 selected/i)).toBeInTheDocument();
    await user.click(checkboxes[0]);
    expect(screen.queryByText(/selected/i)).not.toBeInTheDocument();
  });

  it('bulk-update status posts and refreshes', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: docs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.put('/api/v1/documents/bulk/status', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('a.pdf');
    await user.click(screen.getAllByRole('checkbox')[0]); // select all
    const bulkSelect = screen.getByDisplayValue('Change Status...');
    await user.selectOptions(bulkSelect, 'approved');
    await user.click(screen.getByRole('button', { name: /update status/i }));
    await waitFor(() => expect(putBody).not.toBeNull());
    expect(putBody.status).toBe('approved');
  });
});

describe('CaseDocuments — per-row status update', () => {
  it('PUTs new status when row dropdown is changed', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.put('/api/v1/documents/doc-1/status', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    const rowStatus = screen.getByDisplayValue('New');
    await user.selectOptions(rowStatus, 'approved');
    await waitFor(() => expect(putBody?.status).toBe('approved'));
  });
});

describe('CaseDocuments — delete flow', () => {
  it('opens delete modal and deletes a document', async () => {
    let deleted = false;
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.delete('/api/v1/documents/doc-1', () => {
        deleted = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    await user.click(screen.getByTitle(/^delete$/i));
    expect(await screen.findByText(/this action cannot be undone/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^delete document$/i }));
    await waitFor(() => expect(deleted).toBe(true));
    expect(
      await screen.findByText(/document deleted successfully/i),
    ).toBeInTheDocument();
  });
});

describe('CaseDocuments — share dialog', () => {
  it('opens, posts share request, and closes', async () => {
    let sharedBody: any = null;
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () =>
        HttpResponse.json([{ id: 'g1', username: 'guest1', email: 'g1@x.com' }]),
      ),
      http.post('/api/v1/documents/doc-1/share', async ({ request }) => {
        sharedBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    await user.click(screen.getByTitle(/share with guest/i));
    expect(await screen.findByText(/share document/i)).toBeInTheDocument();
    // The Share dialog uses an unlabeled <select>; grab via displayed default.
    const guestSelect = screen.getByDisplayValue(/-- Select a guest --/i);
    await user.selectOptions(guestSelect, 'g1');
    await user.type(screen.getByPlaceholderText(/add a note/i), 'check this');
    await user.click(screen.getByRole('button', { name: /^share$/i }));
    await waitFor(() => expect(sharedBody?.user_id).toBe('g1'));
  });
});

describe('CaseDocuments — upload modal', () => {
  it('opens and closes the upload modal', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText(/no documents uploaded yet/i);
    await user.click(screen.getByRole('button', { name: /upload documents/i }));
    expect(await screen.findByText(/add documents/i)).toBeInTheDocument();
    await user.click(screen.getByText('×'));
    await waitFor(() =>
      expect(screen.queryByText(/add documents/i)).not.toBeInTheDocument(),
    );
  });

  it('selects files, shows them, removes one, and uploads successfully', async () => {
    const uploaded: string[] = [];
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.post('/api/v1/documents/', () => {
        uploaded.push('ok');
        return HttpResponse.json({ id: 'new-doc' });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText(/no documents uploaded yet/i);
    await user.click(screen.getByRole('button', { name: /upload documents/i }));
    await screen.findByText(/add documents/i);

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const f1 = new File(['a'], 'one.pdf', { type: 'application/pdf' });
    const f2 = new File(['bb'], 'two.pdf', { type: 'application/pdf' });
    await user.upload(fileInput, [f1, f2]);

    expect(await screen.findByText(/2 files selected/i)).toBeInTheDocument();
    expect(screen.getByText('one.pdf')).toBeInTheDocument();
    // Remove one file
    await user.click(screen.getAllByTitle(/remove file/i)[0]);
    expect(await screen.findByText(/1 file selected/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /upload 1 file/i }));
    await waitFor(() => expect(uploaded.length).toBe(1));
  });

  // The next two tests assert on UI state AFTER the upload response.
  // axios's Node adapter (jsdom) can't serialise a real File inside
  // FormData (the form-data package needs Buffer/stream inputs, not
  // browser File), so the request hangs and we never see the response
  // handler run. Mock api.post directly to bypass the serialisation
  // step. Same pattern as DocumentUpload.test.tsx — see the note there.
  it('shows upload results modal when an upload fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    vi.spyOn(api, 'post').mockRejectedValue({
      response: { data: { detail: 'bad file' }, status: 400 },
    });
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText(/no documents uploaded yet/i);
    await user.click(screen.getByRole('button', { name: /upload documents/i }));
    await screen.findByText(/add documents/i);
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await user.upload(
      fileInput,
      new File(['a'], 'bad.pdf', { type: 'application/pdf' }),
    );
    await screen.findByText(/1 file selected/i);
    await user.click(screen.getByRole('button', { name: /upload 1 file/i }));
    expect(await screen.findByText(/upload results/i)).toBeInTheDocument();
    expect(screen.getByText(/failed uploads/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /got it/i }));
    await waitFor(() =>
      expect(screen.queryByText(/upload results/i)).not.toBeInTheDocument(),
    );
  });

  it('shows duplicate results when upload reports a duplicate', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        id: 'd',
        is_duplicate: true,
        duplicate_of_filename: 'original.pdf',
      },
    } as never);
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText(/no documents uploaded yet/i);
    await user.click(screen.getByRole('button', { name: /upload documents/i }));
    await screen.findByText(/add documents/i);
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await user.upload(
      fileInput,
      new File(['a'], 'dup.pdf', { type: 'application/pdf' }),
    );
    await screen.findByText(/1 file selected/i);
    await user.click(screen.getByRole('button', { name: /upload 1 file/i }));
    expect(await screen.findByText(/duplicate documents/i)).toBeInTheDocument();
    expect(screen.getByText(/original\.pdf/i)).toBeInTheDocument();
  });
});

describe('CaseDocuments — download & bulk actions', () => {
  const docs = [
    { ...baseDoc, id: 'd1', filename: 'a.pdf' },
    { ...baseDoc, id: 'd2', filename: 'b.pdf' },
  ];

  it('downloads a document via the row action', async () => {
    let downloaded = false;
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.get('/api/v1/documents/doc-1/download', () => {
        downloaded = true;
        return new HttpResponse(new Blob(['pdf-bytes']), {
          headers: { 'content-disposition': 'attachment; filename="report.pdf"' },
        });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    await user.click(screen.getByTitle(/^download$/i));
    await waitFor(() => expect(downloaded).toBe(true));
  });

  it('alerts on download error', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.get('/api/v1/documents/doc-1/download', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    await user.click(screen.getByTitle(/^download$/i));
    await waitFor(() =>
      expect(window.alert).toHaveBeenCalledWith('Failed to download document'),
    );
  });

  it('bulk-downloads selected documents', async () => {
    const hits: string[] = [];
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: docs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.get('/api/v1/documents/:id/download', ({ params }) => {
        hits.push(params.id as string);
        return new HttpResponse(new Blob(['x']));
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('a.pdf');
    await user.click(screen.getAllByRole('checkbox')[0]);
    const bulkDownload = screen
      .getAllByRole('button', { name: /^download$/i })
      .find((b) => b.classList.contains('btn-bulk-action'))!;
    await user.click(bulkDownload);
    await waitFor(() => expect(hits.length).toBe(2));
  });

  it('bulk-deletes selected documents via the modal', async () => {
    const deleted: string[] = [];
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: docs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.delete('/api/v1/documents/:id', ({ params }) => {
        deleted.push(params.id as string);
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('a.pdf');
    await user.click(screen.getAllByRole('checkbox')[0]);
    const bulkDelete = screen
      .getAllByRole('button', { name: /^delete$/i })
      .find((b) => b.classList.contains('btn-bulk-action'))!;
    await user.click(bulkDelete);
    expect(await screen.findByText(/this action cannot be undone/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^delete documents$/i }));
    await waitFor(() => expect(deleted.length).toBe(2));
    expect(await screen.findByText(/deleted 2 of 2 documents/i)).toBeInTheDocument();
  });
});

describe('CaseDocuments — file type icons & special rows', () => {
  it('renders email, word, excel, pptx and duplicate rows', async () => {
    const specialDocs = [
      { ...baseDoc, id: 'e1', filename: 'mail.eml', mime_type: 'message/rfc822', thread_status: 'active' as const, message_id: 'msg-1234567890abcdef' },
      { ...baseDoc, id: 'w1', filename: 'doc.docx' },
      { ...baseDoc, id: 'x1', filename: 'sheet.xlsx' },
      { ...baseDoc, id: 'p1', filename: 'deck.pptx' },
      { ...baseDoc, id: 'orig', filename: 'orig.pdf' },
      { ...baseDoc, id: 'dup', filename: 'copy.pdf', is_duplicate: true, duplicate_of: 'orig' },
      { ...baseDoc, id: 'sup', filename: 'old.eml', thread_status: 'superseded' as const, superseded_by: 'e1', superseded_by_filename: 'mail.eml' },
      { ...baseDoc, id: 'sub', filename: 'submitted.pdf', submitter_name: 'Bob', submitter_email: 'bob@x.com' },
      { ...baseDoc, id: 'sys', filename: 'system.pdf', uploaded_by_name: undefined },
    ];
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: specialDocs }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    renderWithProviders(<CaseDocuments />);
    expect((await screen.findAllByText('mail.eml')).length).toBeGreaterThan(0);
    expect(screen.getByText('doc.docx')).toBeInTheDocument();
    expect(screen.getByText('sheet.xlsx')).toBeInTheDocument();
    expect(screen.getByText('deck.pptx')).toBeInTheDocument();
    expect(screen.getByText(/duplicate of:/i)).toBeInTheDocument();
    expect(screen.getByText(/superseded by:/i)).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('System')).toBeInTheDocument();
  });

  it('renders attachment rows for documents with attachments', async () => {
    const docWithAtt = { ...baseDoc, id: 'parent', filename: 'email.eml', has_attachments: true };
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [docWithAtt] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.get('/api/v1/documents/parent/attachments', () =>
        HttpResponse.json([
          { id: 'att-1', filename: 'attached.pdf', mime_type: 'application/pdf', size: 999, upload_date: '2026-05-10T12:00:00Z' },
        ]),
      ),
    );
    renderWithProviders(<CaseDocuments />);
    expect(await screen.findByText('attached.pdf')).toBeInTheDocument();
    expect(screen.getByText('Attachment')).toBeInTheDocument();
  });
});

describe('CaseDocuments — error & notification paths', () => {
  it('handles documents fetch error gracefully (stays on empty)', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    renderWithProviders(<CaseDocuments />);
    expect(
      await screen.findByText(/no documents uploaded yet/i),
    ).toBeInTheDocument();
  });

  it('shows error notification when delete fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.delete('/api/v1/documents/doc-1', () =>
        HttpResponse.json({ detail: 'no' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    await user.click(screen.getByTitle(/^delete$/i));
    await screen.findByText(/this action cannot be undone/i);
    await user.click(screen.getByRole('button', { name: /^delete document$/i }));
    expect(
      await screen.findByText(/failed to delete document/i),
    ).toBeInTheDocument();
    // Dismiss notification
    await user.click(screen.getByRole('button', { name: /^ok$/i }));
    await waitFor(() =>
      expect(screen.queryByText(/failed to delete document/i)).not.toBeInTheDocument(),
    );
  });

  it('alerts when per-row status update fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
      http.put('/api/v1/documents/doc-1/status', () =>
        HttpResponse.json({ detail: 'no' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    await user.selectOptions(screen.getByDisplayValue('New'), 'approved');
    await waitFor(() =>
      expect(window.alert).toHaveBeenCalledWith(
        'Failed to update document status',
      ),
    );
  });

  it('alerts when share is attempted without selecting a guest', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({ documents: [baseDoc] }),
      ),
      http.get('/api/v1/auth/users/guests', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<CaseDocuments />);
    await screen.findByText('report.pdf');
    await user.click(screen.getByTitle(/share with guest/i));
    await screen.findByText(/share document/i);
    await user.click(screen.getByRole('button', { name: /^share$/i }));
    expect(window.alert).toHaveBeenCalledWith('Please select a guest user');
    // Cancel closes the dialog
    await user.click(screen.getByRole('button', { name: /^cancel$/i }));
    await waitFor(() =>
      expect(screen.queryByText(/share document/i)).not.toBeInTheDocument(),
    );
  });
});
