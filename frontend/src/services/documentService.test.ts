import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';
import * as documentService from './documentService';

// ---------------------------------------------------------------------------
// getDocuments
// ---------------------------------------------------------------------------
describe('documentService.getDocuments', () => {
  it('returns the list of documents on 200', async () => {
    server.use(
      http.get('/api/v1/documents', () =>
        HttpResponse.json([
          { id: 'd-1', filename: 'a.pdf' },
          { id: 'd-2', filename: 'b.pdf' },
        ]),
      ),
    );
    const docs = await documentService.getDocuments();
    expect(docs).toHaveLength(2);
    expect(docs[0].filename).toBe('a.pdf');
  });

  it('forwards query params (skip, limit, file_type, uploaded_by, tags)', async () => {
    let observedUrl: URL | null = null;
    server.use(
      http.get('/api/v1/documents', ({ request }) => {
        observedUrl = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );
    await documentService.getDocuments({
      skip: 5,
      limit: 25,
      file_type: 'pdf',
      uploaded_by: 'user-7',
      tags: ['urgent', 'review'],
    });
    expect(observedUrl).not.toBeNull();
    const params = observedUrl!.searchParams;
    expect(params.get('skip')).toBe('5');
    expect(params.get('limit')).toBe('25');
    expect(params.get('file_type')).toBe('pdf');
    expect(params.get('uploaded_by')).toBe('user-7');
    // axios serializes arrays as repeated keys by default
    expect(params.getAll('tags[]')).toEqual(['urgent', 'review']);
  });

  it('works with no params (undefined branch)', async () => {
    let observedUrl: URL | null = null;
    server.use(
      http.get('/api/v1/documents', ({ request }) => {
        observedUrl = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );
    const docs = await documentService.getDocuments();
    expect(docs).toEqual([]);
    expect(observedUrl).not.toBeNull();
    // No params should be appended to the URL when params arg is undefined
    expect(observedUrl!.searchParams.toString()).toBe('');
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/documents',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(documentService.getDocuments()).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getDocumentById
// ---------------------------------------------------------------------------
describe('documentService.getDocumentById', () => {
  it('returns a single document on 200', async () => {
    server.use(
      http.get('/api/v1/documents/doc-42', () =>
        HttpResponse.json({ id: 'doc-42', filename: 'redacted.pdf' }),
      ),
    );
    const result = await documentService.getDocumentById('doc-42');
    expect(result.id).toBe('doc-42');
    expect(result.filename).toBe('redacted.pdf');
  });

  it('throws on 404', async () => {
    server.use(
      http.get(
        '/api/v1/documents/missing',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(
      documentService.getDocumentById('missing'),
    ).rejects.toThrow();
  });
});
