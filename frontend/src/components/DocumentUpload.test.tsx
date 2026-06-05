import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import { DocumentUpload } from './DocumentUpload';
import api from '../api/client';

// We mock api.post directly rather than letting MSW intercept the
// network call. Reason: DocumentUpload sends a FormData with a real
// File object; axios's Node adapter (used by jsdom test runs) routes
// multipart serialisation through the `form-data` package, which
// doesn't accept browser File objects and hangs the request. This
// surfaced after commit e049d29 removed the global
// Content-Type:application/json default that was previously masking
// the issue (axios JSON-stringified FormData -> "{}" -> MSW handler
// matched the empty body).
beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('DocumentUpload — initial render', () => {
  it('renders a file input that accepts the allowed extensions', () => {
    renderWithProviders(<DocumentUpload />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.accept).toBe('.pdf,.docx,.eml');
    expect(input.disabled).toBe(false);
  });

  it('does not render Uploading… or status message until something happens', () => {
    renderWithProviders(<DocumentUpload />);
    expect(screen.queryByText(/uploading/i)).not.toBeInTheDocument();
  });
});

describe('DocumentUpload — onUpload prop branch', () => {
  it('invokes provided onUpload with the chosen files and shows success message', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<DocumentUpload onUpload={onUpload} />);
    const user = userEvent.setup();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['hi'], 'a.pdf', { type: 'application/pdf' });
    await user.upload(input, file);
    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    expect(onUpload).toHaveBeenCalledWith([file]);
    expect(
      await screen.findByText(/document uploaded successfully/i),
    ).toBeInTheDocument();
  });

  it('shows failure message when onUpload rejects', async () => {
    const onUpload = vi.fn().mockRejectedValue(new Error('boom'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderWithProviders(<DocumentUpload onUpload={onUpload} />);
    const user = userEvent.setup();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['hi'], 'a.pdf', { type: 'application/pdf' });
    await user.upload(input, file);
    expect(
      await screen.findByText(/failed to upload document/i),
    ).toBeInTheDocument();
  });
});

describe('DocumentUpload — onUploadSuccess (API) branch', () => {
  it('POSTs to /documents and notifies on success', async () => {
    const postSpy = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: { id: 'doc-1', existing: false } } as never);
    const onUploadSuccess = vi.fn();
    renderWithProviders(<DocumentUpload onUploadSuccess={onUploadSuccess} />);
    const user = userEvent.setup();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['hi'], 'a.pdf', { type: 'application/pdf' });
    await user.upload(input, file);
    await waitFor(() => expect(onUploadSuccess).toHaveBeenCalledWith('doc-1'));
    expect(postSpy).toHaveBeenCalledWith('/documents/', expect.any(FormData));
    expect(
      await screen.findByText(/document uploaded successfully/i),
    ).toBeInTheDocument();
  });

  it('shows the existing-document message when the API reports an existing doc', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 'doc-1', existing: true },
    } as never);
    const onUploadSuccess = vi.fn();
    renderWithProviders(<DocumentUpload onUploadSuccess={onUploadSuccess} />);
    const user = userEvent.setup();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['hi'], 'a.pdf', { type: 'application/pdf' });
    await user.upload(input, file);
    await waitFor(() => expect(onUploadSuccess).toHaveBeenCalledWith('doc-1'));
    expect(
      await screen.findByText(/already uploaded/i),
    ).toBeInTheDocument();
  });

  it('shows failure message when API call rejects', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(new Error('500'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const onUploadSuccess = vi.fn();
    renderWithProviders(<DocumentUpload onUploadSuccess={onUploadSuccess} />);
    const user = userEvent.setup();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['hi'], 'a.pdf', { type: 'application/pdf' });
    await user.upload(input, file);
    expect(
      await screen.findByText(/failed to upload document/i),
    ).toBeInTheDocument();
    expect(onUploadSuccess).not.toHaveBeenCalled();
  });
});

describe('DocumentUpload — early-return guards', () => {
  it('no-ops when neither onUpload nor onUploadSuccess provided', async () => {
    renderWithProviders(<DocumentUpload />);
    const user = userEvent.setup();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['hi'], 'a.pdf', { type: 'application/pdf' });
    await user.upload(input, file);
    // No message rendered because neither callback ran the success branch.
    expect(screen.queryByText(/uploaded successfully/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/failed to upload/i)).not.toBeInTheDocument();
  });
});
