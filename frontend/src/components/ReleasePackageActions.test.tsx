import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import ReleasePackageActions from './ReleasePackageActions';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  if (!('createObjectURL' in URL))
    (URL as any).createObjectURL = vi.fn(() => 'blob:fake');
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fake');
  if (!('revokeObjectURL' in URL)) (URL as any).revokeObjectURL = vi.fn();
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

const emptyState = { current_draft: null, current_release: null };

const approvedDocs = [
  { id: 'd1', filename: 'a.pdf', status: 'approved', redactions: [{}, {}] },
  { id: 'd2', filename: 'b.pdf', status: 'released' },
  { id: 'd3', filename: 'c.pdf', status: 'new' },
];

const draftPackage = {
  id: 'pkg-1',
  case_id: 'case-1',
  status: 'draft' as const,
  filename: 'pkg.zip',
  size_bytes: 2048,
  document_count: 2,
  total_redactions: 5,
  included_documents: [],
  generation_progress: 100,
  download_count: 0,
  created_at: '2026-05-10T00:00:00Z',
  created_by_name: 'Alice',
};

function renderActions(props?: Partial<React.ComponentProps<typeof ReleasePackageActions>>) {
  return renderWithProviders(
    <ReleasePackageActions
      caseId="case-1"
      caseNumber="FOI-2026-001"
      documents={approvedDocs}
      {...props}
    />,
  );
}

describe('ReleasePackageActions — initial states', () => {
  it('shows the Generate button when there is no package', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json(emptyState),
      ),
    );
    renderActions();
    expect(
      await screen.findByRole('button', { name: /generate package/i }),
    ).toBeEnabled();
  });

  it('disables Generate when there are no approved documents', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json(emptyState),
      ),
    );
    renderActions({ documents: [{ id: 'x', filename: 'x.pdf', status: 'new' }] });
    expect(
      await screen.findByRole('button', { name: /generate package/i }),
    ).toBeDisabled();
  });

  it('shows a progress bar while a draft is generating', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({
          current_draft: {
            ...draftPackage,
            status: 'generating',
            generation_progress: 40,
            generation_message: 'Applying redactions',
          },
          current_release: null,
        }),
      ),
    );
    renderActions();
    expect(
      await screen.findByRole('button', { name: /generating/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/applying redactions/i)).toBeInTheDocument();
  });

  it('shows Regenerate, Download and Release for a ready draft', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({ current_draft: draftPackage, current_release: null }),
      ),
    );
    renderActions();
    expect(
      await screen.findByRole('button', { name: /regenerate package/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /download package/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /release package/i }),
    ).toBeInTheDocument();
  });

  it('shows the released chip and stats when a release exists', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({
          current_draft: null,
          current_release: {
            ...draftPackage,
            status: 'released',
            released_at: '2026-05-11T00:00:00Z',
            download_count: 3,
            max_downloads: 10,
            expires_at: '2026-06-11T00:00:00Z',
          },
        }),
      ),
    );
    renderActions();
    expect(await screen.findByText(/released/i)).toBeInTheDocument();
    expect(screen.getByText(/downloads: 3/i)).toBeInTheDocument();
  });

  it('logs an error when the package-state fetch fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderActions();
    await waitFor(() => expect(console.error).toHaveBeenCalled());
  });
});

describe('ReleasePackageActions — generate flow', () => {
  it('opens the generate dialog, lists approved docs, and posts', async () => {
    let body: any = null;
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json(emptyState),
      ),
      http.post('/api/v1/cases/case-1/release-package/generate', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderActions();
    await user.click(
      await screen.findByRole('button', { name: /generate package/i }),
    );
    await screen.findByRole('heading', { name: /generate release package/i });
    expect(screen.getByText('a.pdf')).toBeInTheDocument();
    expect(screen.getByText('b.pdf')).toBeInTheDocument();
    expect(screen.queryByText('c.pdf')).not.toBeInTheDocument();
    await user.click(
      screen.getByRole('button', { name: /start generation/i }),
    );
    // All approved docs selected => document_ids is sent as null.
    await waitFor(() => expect(body).not.toBeNull());
    expect(body.document_ids).toBeNull();
    expect(body.include_cover_letter).toBe(true);
  });

  it('sends an explicit document_ids list after deselecting a doc', async () => {
    let body: any = null;
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json(emptyState),
      ),
      http.post('/api/v1/cases/case-1/release-package/generate', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderActions();
    await user.click(
      await screen.findByRole('button', { name: /generate package/i }),
    );
    await screen.findByRole('heading', { name: /generate release package/i });
    const checkboxes = screen.getAllByRole('checkbox');
    // Deselect the first approved doc.
    await user.click(checkboxes[0]);
    await user.click(
      screen.getByRole('button', { name: /start generation/i }),
    );
    await waitFor(() => expect(body).not.toBeNull());
    expect(Array.isArray(body.document_ids)).toBe(true);
    expect(body.document_ids).toHaveLength(1);
  });

  it('shows an error when generation fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json(emptyState),
      ),
      http.post('/api/v1/cases/case-1/release-package/generate', () =>
        HttpResponse.json({ detail: 'generation broke' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderActions();
    await user.click(
      await screen.findByRole('button', { name: /generate package/i }),
    );
    await screen.findByRole('heading', { name: /generate release package/i });
    await user.click(
      screen.getByRole('button', { name: /start generation/i }),
    );
    expect(await screen.findByText(/generation broke/i)).toBeInTheDocument();
  });

  it('disables Start Generation when no documents are selected', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json(emptyState),
      ),
    );
    const user = userEvent.setup();
    renderActions();
    await user.click(
      await screen.findByRole('button', { name: /generate package/i }),
    );
    await screen.findByRole('heading', { name: /generate release package/i });
    const checkboxes = screen.getAllByRole('checkbox');
    await user.click(checkboxes[0]);
    await user.click(checkboxes[1]);
    expect(
      screen.getByRole('button', { name: /start generation/i }),
    ).toBeDisabled();
  });
});

describe('ReleasePackageActions — download flow', () => {
  it('downloads the draft package', async () => {
    let hit = false;
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({ current_draft: draftPackage, current_release: null }),
      ),
      http.get('/api/v1/cases/case-1/release-package/pkg-1/download', () => {
        hit = true;
        return new HttpResponse(new Blob(['zip-bytes']));
      }),
    );
    const user = userEvent.setup();
    renderActions();
    await user.click(
      await screen.findByRole('button', { name: /download package/i }),
    );
    await waitFor(() => expect(hit).toBe(true));
  });

  it('shows a toast error when the download fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({ current_draft: draftPackage, current_release: null }),
      ),
      http.get('/api/v1/cases/case-1/release-package/pkg-1/download', () =>
        HttpResponse.json({ detail: 'download failed' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderActions();
    await user.click(
      await screen.findByRole('button', { name: /download package/i }),
    );
    // The download request is responseType:'blob', so axios delivers the
    // 500 body as a Blob rather than a parsed { detail } object — the
    // component falls back to its generic message.
    expect(
      await screen.findByText(/failed to download package/i),
    ).toBeInTheDocument();
  });
});

describe('ReleasePackageActions — release flow', () => {
  it('opens the release dialog, posts, and fires onPackageReleased', async () => {
    let body: any = null;
    const onPackageReleased = vi.fn();
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({ current_draft: draftPackage, current_release: null }),
      ),
      http.post('/api/v1/cases/case-1/release-package/pkg-1/release', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderActions({ onPackageReleased });
    await user.click(
      await screen.findByRole('button', { name: /release package/i }),
    );
    await screen.findByRole('heading', { name: /release package to requester/i });
    expect(screen.getByText(/2 documents/i)).toBeInTheDocument();
    await user.click(
      screen.getByRole('button', { name: /release to requester/i }),
    );
    await waitFor(() => expect(body).not.toBeNull());
    expect(body.expires_in_days).toBe(30);
    expect(body.notify_requester).toBe(true);
    await waitFor(() => expect(onPackageReleased).toHaveBeenCalled());
  });

  it('hides the custom message field when notify is unchecked', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({ current_draft: draftPackage, current_release: null }),
      ),
    );
    const user = userEvent.setup();
    renderActions();
    await user.click(
      await screen.findByRole('button', { name: /release package/i }),
    );
    await screen.findByRole('heading', { name: /release package to requester/i });
    expect(
      screen.getByLabelText(/custom message/i),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole('checkbox', { name: /send email notification/i }),
    );
    await waitFor(() =>
      expect(
        screen.queryByLabelText(/custom message/i),
      ).not.toBeInTheDocument(),
    );
  });

  it('shows an error when release fails', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/release-packages', () =>
        HttpResponse.json({ current_draft: draftPackage, current_release: null }),
      ),
      http.post('/api/v1/cases/case-1/release-package/pkg-1/release', () =>
        HttpResponse.json({ detail: 'release blocked' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderActions();
    await user.click(
      await screen.findByRole('button', { name: /release package/i }),
    );
    await screen.findByRole('heading', { name: /release package to requester/i });
    await user.click(
      screen.getByRole('button', { name: /release to requester/i }),
    );
    expect(await screen.findByText(/release blocked/i)).toBeInTheDocument();
  });
});
