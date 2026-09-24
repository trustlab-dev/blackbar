import { describe, it, expect } from 'vitest';
import {
  MAX_UPLOAD_BYTES,
  UPLOAD_ACCEPT,
  validateUploadFile,
  partitionUploadFiles,
  getUploadWarnings,
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
