import { describe, it, expect } from 'vitest';
import {
  MAX_UPLOAD_BYTES,
  UPLOAD_ACCEPT,
  validateUploadFile,
  partitionUploadFiles,
  getUploadWarnings,
  withUploadMimeType,
  ALLOWED_UPLOAD_EXTENSIONS,
  ALLOWED_UPLOAD_MIME_TYPES,
  EXTENSION_MIME_TYPES,
} from './uploadValidation';

function fakeFile(name: string, size: number, type = ''): File {
  const f = new File(['x'], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

describe('upload validation (mirrors backend processing_service limits)', () => {
  it('uses the backend 100 MB cap', () => {
    expect(MAX_UPLOAD_BYTES).toBe(100 * 1024 * 1024);
  });

  it('builds an accept attribute from the extension allow-list', () => {
    expect(UPLOAD_ACCEPT.split(',')).toEqual(
      expect.arrayContaining(['.pdf', '.docx', '.eml', '.msg', '.tif', '.webp']),
    );
  });

  it.each([
    ['report.pdf', 'application/pdf'],
    ['REPORT.PDF', 'application/pdf'],
    ['mail.msg', ''], // browsers often report no type for .msg
    ['scan.tif', 'image/tiff'],
    ['notes.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  ])('accepts %s', (name, type) => {
    expect(validateUploadFile(fakeFile(name, 1024, type))).toBeNull();
  });

  it('accepts a known extension the browser labels application/octet-stream', () => {
    expect(validateUploadFile(fakeFile('mail.msg', 1024, 'application/octet-stream'))).toBeNull();
  });

  it('still rejects octet-stream for an extension outside the allow-list', () => {
    expect(validateUploadFile(fakeFile('tool.bin', 10, 'application/octet-stream'))).toMatch(
      /not a supported file type/i,
    );
  });

  it('rejects files over the size limit', () => {
    expect(validateUploadFile(fakeFile('big.pdf', MAX_UPLOAD_BYTES + 1, 'application/pdf'))).toMatch(
      /too large.*100 MB/i,
    );
  });

  it.each([
    ['script.exe', 'application/x-msdownload'],
    ['page.html', 'text/html'],
    ['image.svg', 'image/svg+xml'],
    ['noext', ''],
  ])('rejects disallowed type %s', (name, type) => {
    expect(validateUploadFile(fakeFile(name, 10, type))).toMatch(/not a supported file type/i);
  });

  it('rejects an allowed extension with a mismatched MIME type', () => {
    expect(validateUploadFile(fakeFile('fake.pdf', 10, 'text/html'))).toMatch(
      /not a supported file type/i,
    );
  });

  it('partitions a selection into valid files and error messages', () => {
    const ok = fakeFile('a.pdf', 10, 'application/pdf');
    const bad = fakeFile('b.exe', 10, 'application/x-msdownload');
    const { valid, errors } = partitionUploadFiles([ok, bad]);
    expect(valid).toEqual([ok]);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain('b.exe');
  });
});

describe('getUploadWarnings (POST /documents/ response)', () => {
  it('collects the warnings list (thread consolidation failures, dropped attachments)', () => {
    expect(
      getUploadWarnings({
        id: 'd1',
        warnings: ['Email thread consolidation failed: boom', 'Attachment x.exe was not saved'],
      }),
    ).toEqual(['Email thread consolidation failed: boom', 'Attachment x.exe was not saved']);
  });

  it('includes the single conversion warning', () => {
    expect(getUploadWarnings({ message: 'Uploaded with conversion warning', warning: 'LibreOffice failed' }))
      .toEqual(['LibreOffice failed']);
  });

  it('ignores blanks, non-strings and missing fields', () => {
    expect(getUploadWarnings({ warnings: ['', 3, null, ' ok '] })).toEqual(['ok']);
    expect(getUploadWarnings({ id: 'd1' })).toEqual([]);
    expect(getUploadWarnings(undefined)).toEqual([]);
    expect(getUploadWarnings('nope')).toEqual([]);
  });
});

describe('MIME type for files the browser cannot type (backend rejects octet-stream)', () => {
  it('maps every allowed extension to an allowed MIME type', () => {
    for (const ext of ALLOWED_UPLOAD_EXTENSIONS) {
      expect(ALLOWED_UPLOAD_MIME_TYPES.has(EXTENSION_MIME_TYPES[ext])).toBe(true);
    }
  });

  it.each(['', 'application/octet-stream'])(
    're-wraps a .msg reported as %j with the Outlook MIME type',
    async (type) => {
      const original = new File(['msg-bytes'], 'Quarterly.MSG', { type, lastModified: 42 });
      const wrapped = withUploadMimeType(original);
      expect(wrapped).not.toBe(original);
      expect(wrapped.type).toBe('application/vnd.ms-outlook');
      expect(wrapped.name).toBe('Quarterly.MSG');
      expect(wrapped.lastModified).toBe(42);
      expect(await wrapped.text()).toBe('msg-bytes');
    },
  );

  it('leaves a file the browser already typed untouched', () => {
    const pdf = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    expect(withUploadMimeType(pdf)).toBe(pdf);
  });

  it('leaves an unknown extension alone (validation rejects it)', () => {
    const odd = new File(['x'], 'constructor', { type: '' });
    expect(withUploadMimeType(odd)).toBe(odd);
  });

  it('partitionUploadFiles hands back typed files ready for FormData', () => {
    const msg = new File(['m'], 'mail.msg', { type: '' });
    const { valid, errors } = partitionUploadFiles([msg]);
    expect(errors).toEqual([]);
    expect(valid).toHaveLength(1);
    expect(valid[0].name).toBe('mail.msg');
    expect(valid[0].type).toBe('application/vnd.ms-outlook');
  });
});
