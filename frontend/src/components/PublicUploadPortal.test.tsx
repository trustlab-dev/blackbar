import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// vi.mock is hoisted to top — wraps axios.create so the publicApi instance
// in src/api/client.ts uses the fetch adapter (MSW under jsdom only patches
// global fetch; axios's default node adapter bypasses it for multipart uploads).
vi.mock('axios', async () => {
  const actual = await vi.importActual<any>('axios');
  const origCreate = actual.default.create.bind(actual.default);
  actual.default.create = (config: any = {}) =>
    origCreate({ ...config, adapter: 'fetch' });
  return actual;
});

// client.ts's getBaseURL() returns an absolute URL only when
// window.location.protocol === 'https:'. Force https BEFORE imports so the
// fetch adapter (which requires absolute URLs) has a host to resolve against.
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
import { server } from '../test-utils/msw-handlers';
import {
  renderWithProviders,
  screen,
  waitFor,
} from '../test-utils/render';
import PublicUploadPortal from './PublicUploadPortal';

const API_BASE = 'https://localhost:3000/api/v1';

function Harness() {
  return (
    <Routes>
      <Route path="/upload/:token" element={<PublicUploadPortal />} />
    </Routes>
  );
}

function makeCollectionInfo(overrides: any = {}) {
  return {
    case_title: 'My Case',
    case_tracking_number: 'CASE-001',
    upload_count: 0,
    max_uploads: 5,
    ...overrides,
  };
}

beforeEach(() => {
  // Nothing
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('PublicUploadPortal — loading state', () => {
  it('shows loading text before collection info loads', () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () => new Promise(() => {})),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});

describe('PublicUploadPortal — collection info errors', () => {
  it('shows backend detail when collection link is invalid', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json({ detail: 'Link expired' }, { status: 404 }),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    expect(await screen.findByText(/link expired/i)).toBeInTheDocument();
    expect(
      screen.getByText(/link not available/i),
    ).toBeInTheDocument();
  });

  it('falls back to default message when no detail provided', async () => {
    server.use(
      http.get(
        `${API_BASE}/cases/collect/tok`,
        () => new HttpResponse(null, { status: 500 }),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    expect(
      await screen.findByText(/collection link not found or expired/i),
    ).toBeInTheDocument();
  });
});

describe('PublicUploadPortal — happy path render', () => {
  it('renders form fields, case info, and upload counter', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo({ upload_count: 2 })),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    expect(await screen.findByText('My Case')).toBeInTheDocument();
    expect(screen.getByText('CASE-001')).toBeInTheDocument();
    expect(screen.getByText(/2 \/ 5/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/john doe/i)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/john@example\.com/i),
    ).toBeInTheDocument();
  });

  it('hides upload counter when max_uploads is not set', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json({
          case_title: 'C',
          case_tracking_number: 'T',
          upload_count: 1,
        }),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('C');
    expect(screen.queryByText(/uploads:/i)).not.toBeInTheDocument();
  });

  it('renders footer text from public config', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({ footer_text: 'Legal footer' }),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    expect(await screen.findByText(/legal footer/i)).toBeInTheDocument();
  });

  it('handles public config fetch failure silently', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(
        `${API_BASE}/admin/config/public`,
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    expect(await screen.findByText('My Case')).toBeInTheDocument();
  });
});

describe('PublicUploadPortal — file selection and removal', () => {
  it('selects files via the hidden file input', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    const file = new File(['a'], 'a.txt', { type: 'text/plain' });
    const input = document.getElementById('file-input') as HTMLInputElement;
    Object.defineProperty(input, 'files', {
      value: [file],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));

    expect(await screen.findByText('a.txt')).toBeInTheDocument();
    expect(screen.getByText(/files to upload \(1\)/i)).toBeInTheDocument();
  });

  it('handles drag and drop', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    const dropZone = document.querySelector('.drop-zone') as HTMLElement;
    const file = new File(['a'], 'dropped.txt');

    // dragover then drop
    const dragOver = new Event('dragover', { bubbles: true, cancelable: true });
    Object.defineProperty(dragOver, 'preventDefault', { value: vi.fn() });
    dropZone.dispatchEvent(dragOver);

    const dragLeave = new Event('dragleave', {
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(dragLeave, 'preventDefault', { value: vi.fn() });
    dropZone.dispatchEvent(dragLeave);

    const drop = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(drop, 'preventDefault', { value: vi.fn() });
    Object.defineProperty(drop, 'dataTransfer', {
      value: { files: [file] },
    });
    dropZone.dispatchEvent(drop);

    expect(await screen.findByText('dropped.txt')).toBeInTheDocument();
  });

  it('removes a pending file via the remove button', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    const input = document.getElementById('file-input') as HTMLInputElement;
    const file = new File(['a'], 'remove-me.txt');
    Object.defineProperty(input, 'files', {
      value: [file],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await screen.findByText('remove-me.txt');

    await user.click(screen.getByRole('button', { name: '✕' }));
    expect(screen.queryByText('remove-me.txt')).not.toBeInTheDocument();
  });

  it('clicking the drop zone forwards click to the hidden file input', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');
    const input = document.getElementById('file-input') as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');
    const dropZone = document.querySelector('.drop-zone') as HTMLElement;
    dropZone.click();
    expect(clickSpy).toHaveBeenCalled();
  });
});

describe('PublicUploadPortal — submission validation', () => {
  it('shows validation error when no files are selected (form submit bypass)', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    await user.type(screen.getByPlaceholderText(/john doe/i), 'Name');
    await user.type(
      screen.getByPlaceholderText(/john@example\.com/i),
      'a@b.com',
    );

    // Submit button is disabled when no files; dispatch directly.
    const form = document.querySelector('form') as HTMLFormElement;
    form.requestSubmit
      ? form.requestSubmit()
      : form.dispatchEvent(
          new Event('submit', { cancelable: true, bubbles: true }),
        );

    await waitFor(() =>
      expect(
        screen.getByText(/please select at least one file/i),
      ).toBeInTheDocument(),
    );
  });

  it('shows validation error when name and email are missing (form submit bypass)', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    // Add a file (so the files-length guard passes when we reach it)
    const input = document.getElementById('file-input') as HTMLInputElement;
    Object.defineProperty(input, 'files', {
      value: [new File(['a'], 'a.txt')],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await screen.findByText('a.txt');

    // Bypass disabled-state by dispatching submit directly without filling
    // name/email fields. fireEvent dispatches the synthetic submit that
    // React listens for.
    const form = document.querySelector('form') as HTMLFormElement;
    const submitEvent = new Event('submit', {
      cancelable: true,
      bubbles: true,
    });
    form.dispatchEvent(submitEvent);

    await waitFor(() =>
      expect(
        screen.getByText(/please provide your name and email/i),
      ).toBeInTheDocument(),
    );
  });
});

describe('PublicUploadPortal — upload flow', () => {
  it('uploads files and shows the success screen', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
      http.post(`${API_BASE}/cases/collect/tok/upload`, () =>
        HttpResponse.json({ ok: true }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    await user.type(screen.getByPlaceholderText(/john doe/i), 'Tester');
    await user.type(screen.getByPlaceholderText(/john@example\.com/i), 't@x.com');
    await user.type(
      screen.getByPlaceholderText(/any additional information/i),
      'Some notes',
    );

    const input = document.getElementById('file-input') as HTMLInputElement;
    Object.defineProperty(input, 'files', {
      value: [
        new File(['a'], 'a.txt'),
        new File(['b'], 'b.txt'),
      ],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await screen.findByText('a.txt');
    await screen.findByText('b.txt');

    await user.click(screen.getByRole('button', { name: /upload 2 files/i }));

    await waitFor(() =>
      expect(screen.getByText(/upload complete/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/successfully uploaded 2 of 2 files/i)).toBeInTheDocument();
  });

  it('shows error indicators when upload fails per-file', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
      http.post(`${API_BASE}/cases/collect/tok/upload`, () =>
        HttpResponse.json({ detail: 'too big' }, { status: 413 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    await user.type(screen.getByPlaceholderText(/john doe/i), 'T');
    await user.type(screen.getByPlaceholderText(/john@example\.com/i), 'a@b.com');
    const input = document.getElementById('file-input') as HTMLInputElement;
    Object.defineProperty(input, 'files', {
      value: [new File(['a'], 'a.txt')],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await screen.findByText('a.txt');

    await user.click(screen.getByRole('button', { name: /upload 1 file/i }));
    await waitFor(() =>
      expect(screen.getByText(/successfully uploaded 0 of 1 files/i)).toBeInTheDocument(),
    );
  });

  it('handles network error with default fallback message during upload', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
      http.post(
        `${API_BASE}/cases/collect/tok/upload`,
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    await user.type(screen.getByPlaceholderText(/john doe/i), 'T');
    await user.type(screen.getByPlaceholderText(/john@example\.com/i), 'a@b.com');
    const input = document.getElementById('file-input') as HTMLInputElement;
    Object.defineProperty(input, 'files', {
      value: [new File(['a'], 'a.txt')],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await screen.findByText('a.txt');

    await user.click(screen.getByRole('button', { name: /upload 1 file/i }));
    await waitFor(() =>
      expect(screen.getByText(/successfully uploaded 0 of 1 files/i)).toBeInTheDocument(),
    );
  });

  it('shows "Upload More Files" button on success and reloads page on click', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
      http.post(`${API_BASE}/cases/collect/tok/upload`, () =>
        HttpResponse.json({ ok: true }),
      ),
    );
    const user = userEvent.setup();
    // Stub reload — jsdom doesn't implement it
    const reloadSpy = vi.fn();
    Object.defineProperty(window.location, 'reload', {
      value: reloadSpy,
      configurable: true,
    });
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');

    await user.type(screen.getByPlaceholderText(/john doe/i), 'T');
    await user.type(screen.getByPlaceholderText(/john@example\.com/i), 'a@b.com');
    const input = document.getElementById('file-input') as HTMLInputElement;
    Object.defineProperty(input, 'files', {
      value: [new File(['a'], 'a.txt')],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await screen.findByText('a.txt');

    await user.click(screen.getByRole('button', { name: /upload 1 file/i }));
    await screen.findByText(/upload complete/i);
    await user.click(
      screen.getByRole('button', { name: /upload more files/i }),
    );
    expect(reloadSpy).toHaveBeenCalled();
  });
});

describe('PublicUploadPortal — file size formatting', () => {
  it('renders 0 Bytes for empty files', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');
    const input = document.getElementById('file-input') as HTMLInputElement;
    // File with no content — size 0
    const empty = new File([], 'empty.txt');
    Object.defineProperty(input, 'files', {
      value: [empty],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    expect(await screen.findByText(/0 bytes/i)).toBeInTheDocument();
  });

  it('renders KB sizes', async () => {
    server.use(
      http.get(`${API_BASE}/cases/collect/tok`, () =>
        HttpResponse.json(makeCollectionInfo()),
      ),
      http.get(`${API_BASE}/admin/config/public`, () =>
        HttpResponse.json({}),
      ),
    );
    renderWithProviders(<Harness />, { route: '/upload/tok' });
    await screen.findByText('My Case');
    const input = document.getElementById('file-input') as HTMLInputElement;
    const kb = new File([new Uint8Array(2048)], 'two-kb.bin');
    Object.defineProperty(input, 'files', {
      value: [kb],
      configurable: true,
    });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    expect(await screen.findByText(/two-kb\.bin/)).toBeInTheDocument();
    expect(screen.getByText(/2 KB/i)).toBeInTheDocument();
  });
});
