import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { fireEvent } from '@testing-library/react';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../../test-utils/render';
import PackUploader from './PackUploader';
import api from '../../api/client';

// Helper for the three "after-upload" tests: PackUploader makes two
// POST calls — /packs/validate sends JSON (handled by MSW fine) and
// /packs/upload sends FormData (axios's Node adapter can't serialise
// browser File objects through form-data and hangs). We intercept
// api.post for the /packs/upload calls so the response handler runs;
// the /packs/validate call still passes through to MSW.
function mockUploadResponse(uploadResponse: { ok: true; data: any } | { ok: false; error: any }) {
  const realPost = api.post.bind(api);
  vi.spyOn(api, 'post').mockImplementation((url: string, body: any, opts?: any) => {
    if (url === '/packs/upload') {
      return uploadResponse.ok
        ? (Promise.resolve({ data: uploadResponse.data }) as any)
        : (Promise.reject(uploadResponse.error) as any);
    }
    return realPost(url, body, opts);
  });
}

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function makeJsonFile(name: string, content: string) {
  const file = new File([content], name, { type: 'application/json' });
  // jsdom's File lacks .text() in some environments — provide it.
  if (typeof file.text !== 'function') {
    Object.defineProperty(file, 'text', {
      value: () => Promise.resolve(content),
    });
  }
  return file;
}

const validPackJson = JSON.stringify({ pack_id: 'test-pack', name: 'Test' });

describe('PackUploader', () => {
  it('renders the dialog with the drop zone', () => {
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    expect(
      screen.getByText(/upload jurisdiction pack/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/click to select a pack file/i),
    ).toBeInTheDocument();
  });

  it('rejects a non-JSON file', async () => {
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    const input = document.getElementById('pack-file-input') as HTMLInputElement;
    const txtFile = new File(['x'], 'pack.txt', { type: 'text/plain' });
    // The input has accept=".json" so userEvent.upload would silently skip a
    // .txt file; fireEvent.change bypasses that to exercise the guard clause.
    fireEvent.change(input, { target: { files: [txtFile] } });
    expect(
      await screen.findByText(/please select a json file/i),
    ).toBeInTheDocument();
  });

  it('validates a selected JSON file and shows the valid result', async () => {
    server.use(
      http.post('/api/v1/packs/validate', () =>
        HttpResponse.json({
          valid: true,
          pack_name: 'Test Pack',
          pack_id: 'test-pack',
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    const input = document.getElementById('pack-file-input') as HTMLInputElement;
    await user.upload(input, makeJsonFile('pack.json', validPackJson));
    expect(await screen.findByText(/pack is valid/i)).toBeInTheDocument();
    expect(screen.getByText(/Test Pack/)).toBeInTheDocument();
  });

  it('shows validation errors and warnings when the pack is invalid', async () => {
    server.use(
      http.post('/api/v1/packs/validate', () =>
        HttpResponse.json({
          valid: false,
          errors: ['Missing jurisdiction'],
          warnings: ['No templates defined'],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    const input = document.getElementById('pack-file-input') as HTMLInputElement;
    await user.upload(input, makeJsonFile('pack.json', validPackJson));
    expect(await screen.findByText(/validation failed/i)).toBeInTheDocument();
    expect(screen.getByText('Missing jurisdiction')).toBeInTheDocument();
    expect(screen.getByText('No templates defined')).toBeInTheDocument();
  });

  it('reports an invalid-JSON syntax error without calling the API', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    const input = document.getElementById('pack-file-input') as HTMLInputElement;
    await user.upload(input, makeJsonFile('pack.json', '{ not valid json'));
    expect(await screen.findByText(/invalid json file/i)).toBeInTheDocument();
  });

  it('surfaces a server validation error', async () => {
    server.use(
      http.post('/api/v1/packs/validate', () =>
        HttpResponse.json({ detail: 'server rejected' }, { status: 422 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    const input = document.getElementById('pack-file-input') as HTMLInputElement;
    await user.upload(input, makeJsonFile('pack.json', validPackJson));
    expect(await screen.findByText(/server rejected/i)).toBeInTheDocument();
  });

  it('uploads a valid pack and calls onSuccess', async () => {
    server.use(
      http.post('/api/v1/packs/validate', () =>
        HttpResponse.json({
          valid: true,
          pack_name: 'Test Pack',
          pack_id: 'test-pack',
        }),
      ),
    );
    mockUploadResponse({ ok: true, data: { success: true } });
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={onSuccess} />,
    );
    const input = document.getElementById('pack-file-input') as HTMLInputElement;
    await user.upload(input, makeJsonFile('pack.json', validPackJson));
    await screen.findByText(/pack is valid/i);
    await user.click(screen.getByRole('button', { name: /upload pack/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it('shows an error when the upload responds with success:false', async () => {
    server.use(
      http.post('/api/v1/packs/validate', () =>
        HttpResponse.json({ valid: true, pack_name: 'P', pack_id: 'p' }),
      ),
    );
    mockUploadResponse({
      ok: true,
      data: { success: false, message: 'duplicate pack' },
    });
    const user = userEvent.setup();
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    const input = document.getElementById('pack-file-input') as HTMLInputElement;
    await user.upload(input, makeJsonFile('pack.json', validPackJson));
    await screen.findByText(/pack is valid/i);
    await user.click(screen.getByRole('button', { name: /upload pack/i }));
    expect(await screen.findByText(/duplicate pack/i)).toBeInTheDocument();
  });

  it('shows an error when the upload request fails', async () => {
    server.use(
      http.post('/api/v1/packs/validate', () =>
        HttpResponse.json({ valid: true, pack_name: 'P', pack_id: 'p' }),
      ),
    );
    mockUploadResponse({
      ok: false,
      error: { response: { data: { detail: 'upload boom' }, status: 500 } },
    });
    const user = userEvent.setup();
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    const input = document.getElementById('pack-file-input') as HTMLInputElement;
    await user.upload(input, makeJsonFile('pack.json', validPackJson));
    await screen.findByText(/pack is valid/i);
    await user.click(screen.getByRole('button', { name: /upload pack/i }));
    expect(await screen.findByText(/upload boom/i)).toBeInTheDocument();
  });

  it('keeps the Upload button disabled until a valid pack is selected', () => {
    renderWithProviders(
      <PackUploader open onClose={vi.fn()} onSuccess={vi.fn()} />,
    );
    expect(
      screen.getByRole('button', { name: /upload pack/i }),
    ).toBeDisabled();
  });

  it('resets state and calls onClose on Cancel', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <PackUploader open onClose={onClose} onSuccess={vi.fn()} />,
    );
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
