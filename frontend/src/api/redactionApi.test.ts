import { describe, it, expect, vi } from 'vitest';

// Blob responses need the fetch adapter under jsdom (same setup as
// ViewerShell.test.tsx).
vi.mock('axios', async () => {
  const actual = await vi.importActual<any>('axios');
  const origCreate = actual.default.create.bind(actual.default);
  actual.default.create = (config: any = {}) => origCreate({ ...config, adapter: 'fetch' });
  return actual;
});

vi.hoisted(() => {
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
});

import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';
import { getApiErrorMessage } from './errors';
import {
  addRedaction,
  reviewProposedRedaction,
  exportRedactedDocument,
  filenameFromContentDisposition,
} from './redactionApi';

const BASE = 'https://localhost:3000/api/v1';

describe('addRedaction', () => {
  it('returns the server-assigned id and status', async () => {
    let body: any = null;
    server.use(
      http.post(`${BASE}/documents/doc-1/redactions`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ message: 'Redaction proposed for review', id: 'r-9', status: 'proposed' });
      }),
    );
    const result = await addRedaction('doc-1', { x: 1, y: 2, width: 3, height: 4, page: 1, category: 'S22' });
    expect(body).toEqual({ x: 1, y: 2, width: 3, height: 4, page: 1, category: 'S22' });
    expect(result).toEqual({ message: 'Redaction proposed for review', id: 'r-9', status: 'proposed' });
  });
});

describe('reviewProposedRedaction', () => {
  it('addresses the redaction by its id in the URL (not an array index)', async () => {
    let url = '';
    let body: any = null;
    server.use(
      http.put(`${BASE}/documents/doc-1/redactions/:ref/approve`, async ({ request }) => {
        url = request.url;
        body = await request.json();
        return HttpResponse.json({ success: true, message: 'Proposed redaction approved', redaction_id: 'r/1' });
      }),
    );
    const result = await reviewProposedRedaction('doc-1', 'r/1', 'approve', 'looks right');
    expect(url).toBe(`${BASE}/documents/doc-1/redactions/r%2F1/approve`);
    expect(body).toEqual({ action: 'approve', notes: 'looks right' });
    expect(result.redaction_id).toBe('r/1');
  });

  it('sends reject without notes', async () => {
    let body: any = null;
    server.use(
      http.put(`${BASE}/documents/doc-1/redactions/r-2/approve`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ success: true, message: 'Proposed redaction rejected', redaction_id: 'r-2' });
      }),
    );
    await reviewProposedRedaction('doc-1', 'r-2', 'reject');
    expect(body).toEqual({ action: 'reject' });
  });
});

describe('exportRedactedDocument', () => {
  it('returns the PDF blob and the filename from Content-Disposition', async () => {
    server.use(
      http.get(`${BASE}/documents/doc-1/export`, () =>
        HttpResponse.arrayBuffer(new ArrayBuffer(4), {
          headers: {
            'Content-Type': 'application/pdf',
            'Content-Disposition':
              "attachment; filename=\"memo_REDACTED_doc-1_20260924.pdf\"; filename*=UTF-8''m%C3%A9mo_REDACTED_doc-1_20260924.pdf",
          },
        }),
      ),
    );
    const result = await exportRedactedDocument('doc-1', 'fallback.pdf');
    expect(result.filename).toBe('mémo_REDACTED_doc-1_20260924.pdf');
    expect(result.blob.size).toBe(4);
  });

  it('rejects with a readable backend message on 409 (unresolved redactions)', async () => {
    server.use(
      http.get(`${BASE}/documents/doc-1/export`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'HTTP_409',
              message:
                '2 redaction(s) are awaiting review (proposed, contested or pending). Approve or reject them before exporting.',
            },
          },
          { status: 409 },
        ),
      ),
    );
    const err = await exportRedactedDocument('doc-1', 'x.pdf').catch((e) => e);
    expect(err.response.status).toBe(409);
    expect(getApiErrorMessage(err, 'fb')).toMatch(/2 redaction\(s\) are awaiting review/);
  });
});

describe('filenameFromContentDisposition', () => {
  it('prefers filename*, falls back to filename, then to the default', () => {
    expect(filenameFromContentDisposition("attachment; filename=\"a.pdf\"; filename*=UTF-8''b%20c.pdf", 'z.pdf')).toBe('b c.pdf');
    expect(filenameFromContentDisposition('attachment; filename="a.pdf"', 'z.pdf')).toBe('a.pdf');
    expect(filenameFromContentDisposition('attachment; filename=a.pdf', 'z.pdf')).toBe('a.pdf');
    expect(filenameFromContentDisposition(undefined, 'z.pdf')).toBe('z.pdf');
    expect(filenameFromContentDisposition("attachment; filename*=UTF-8''%E0%A4%A", 'z.pdf')).toBe('z.pdf');
  });
});
