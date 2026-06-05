import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';
import * as caseService from './caseService';

// ---------------------------------------------------------------------------
// getCases
// ---------------------------------------------------------------------------
describe('caseService.getCases', () => {
  it('returns the list of cases on 200', async () => {
    server.use(
      http.get('/api/v1/cases', () =>
        HttpResponse.json([
          { id: '1', title: 'First case' },
          { id: '2', title: 'Second case' },
        ]),
      ),
    );
    const cases = await caseService.getCases({});
    expect(cases).toHaveLength(2);
    expect(cases[0].title).toBe('First case');
  });

  it('forwards query params (skip, limit, status, priority, assigned_to, created_by)', async () => {
    let observedUrl: URL | null = null;
    server.use(
      http.get('/api/v1/cases', ({ request }) => {
        observedUrl = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );
    await caseService.getCases({
      skip: 10,
      limit: 50,
      status: 'open',
      priority: 'high',
      assigned_to: 'user-1',
      created_by: 'user-2',
    });
    expect(observedUrl).not.toBeNull();
    const params = observedUrl!.searchParams;
    expect(params.get('skip')).toBe('10');
    expect(params.get('limit')).toBe('50');
    expect(params.get('status')).toBe('open');
    expect(params.get('priority')).toBe('high');
    expect(params.get('assigned_to')).toBe('user-1');
    expect(params.get('created_by')).toBe('user-2');
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/cases',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(caseService.getCases({})).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getCaseById
// ---------------------------------------------------------------------------
describe('caseService.getCaseById', () => {
  it('returns a single case on 200', async () => {
    server.use(
      http.get('/api/v1/cases/abc-123', () =>
        HttpResponse.json({ id: 'abc-123', title: 'Detail case' }),
      ),
    );
    const result = await caseService.getCaseById('abc-123');
    expect(result.id).toBe('abc-123');
    expect(result.title).toBe('Detail case');
  });

  it('throws on 404', async () => {
    server.use(
      http.get(
        '/api/v1/cases/missing',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(caseService.getCaseById('missing')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// createCase
// ---------------------------------------------------------------------------
describe('caseService.createCase', () => {
  it('POSTs the payload and returns the created case', async () => {
    let receivedBody: any = null;
    server.use(
      http.post('/api/v1/cases/', async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({ id: 'new-1', title: 'Created' });
      }),
    );
    const result = await caseService.createCase({
      title: 'Created',
      description: 'desc',
      priority: 'low',
    } as any);
    expect(receivedBody).toEqual({
      title: 'Created',
      description: 'desc',
      priority: 'low',
    });
    expect(result.id).toBe('new-1');
  });

  it('throws on 422', async () => {
    server.use(
      http.post(
        '/api/v1/cases/',
        () => new HttpResponse(null, { status: 422 }),
      ),
    );
    await expect(
      caseService.createCase({ title: 'bad' } as any),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// updateCase
// ---------------------------------------------------------------------------
describe('caseService.updateCase', () => {
  it('PUTs the payload and returns the updated case', async () => {
    let receivedBody: any = null;
    server.use(
      http.put('/api/v1/cases/case-9', async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({ id: 'case-9', title: 'Updated' });
      }),
    );
    const result = await caseService.updateCase('case-9', {
      title: 'Updated',
    } as any);
    expect(receivedBody).toEqual({ title: 'Updated' });
    expect(result.title).toBe('Updated');
  });

  it('throws on 500', async () => {
    server.use(
      http.put(
        '/api/v1/cases/case-9',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      caseService.updateCase('case-9', { title: 'x' } as any),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getCaseDocuments
// ---------------------------------------------------------------------------
describe('caseService.getCaseDocuments', () => {
  it('returns the documents array from the wrapped response', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({
          documents: [{ id: 'doc-1' }, { id: 'doc-2' }],
        }),
      ),
    );
    const docs = await caseService.getCaseDocuments('case-1');
    expect(docs).toHaveLength(2);
    expect(docs[0].id).toBe('doc-1');
  });

  it('returns undefined when the response has no documents key', async () => {
    // Pin: service blindly reads .documents off response.data; tests document
    // that an empty payload yields `undefined` rather than [].
    server.use(
      http.get('/api/v1/cases/case-1/documents', () =>
        HttpResponse.json({}),
      ),
    );
    const docs = await caseService.getCaseDocuments('case-1');
    expect(docs).toBeUndefined();
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/cases/case-1/documents',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      caseService.getCaseDocuments('case-1'),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// addDocumentsToCase
// ---------------------------------------------------------------------------
describe('caseService.addDocumentsToCase', () => {
  it('POSTs the document IDs and returns the response data', async () => {
    let receivedBody: any = null;
    server.use(
      http.post(
        '/api/v1/cases/case-1/documents',
        async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ added: 2 });
        },
      ),
    );
    const result = await caseService.addDocumentsToCase('case-1', [
      'doc-a',
      'doc-b',
    ]);
    expect(receivedBody).toEqual(['doc-a', 'doc-b']);
    expect(result).toEqual({ added: 2 });
  });

  it('throws on 500', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/documents',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      caseService.addDocumentsToCase('case-1', ['doc-a']),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// removeDocumentsFromCase
// ---------------------------------------------------------------------------
describe('caseService.removeDocumentsFromCase', () => {
  it('DELETEs with the document IDs in the body and returns the response', async () => {
    let receivedBody: any = null;
    server.use(
      http.delete(
        '/api/v1/cases/case-1/documents',
        async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ removed: 1 });
        },
      ),
    );
    const result = await caseService.removeDocumentsFromCase('case-1', [
      'doc-a',
    ]);
    expect(receivedBody).toEqual(['doc-a']);
    expect(result).toEqual({ removed: 1 });
  });

  it('throws on 500', async () => {
    server.use(
      http.delete(
        '/api/v1/cases/case-1/documents',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      caseService.removeDocumentsFromCase('case-1', ['doc-a']),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getCaseTeam
// ---------------------------------------------------------------------------
describe('caseService.getCaseTeam', () => {
  it('returns the case team array on 200', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/team', () =>
        HttpResponse.json([{ user_id: 'u-1', role: 'manager' }]),
      ),
    );
    const team = await caseService.getCaseTeam('case-1');
    expect(team).toHaveLength(1);
    expect(team[0].role).toBe('manager');
  });

  it('throws on 403', async () => {
    server.use(
      http.get(
        '/api/v1/cases/case-1/team',
        () => new HttpResponse(null, { status: 403 }),
      ),
    );
    await expect(caseService.getCaseTeam('case-1')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// addCaseTeamMember
// ---------------------------------------------------------------------------
describe('caseService.addCaseTeamMember', () => {
  it('POSTs the full payload (with department + notes) and returns the response', async () => {
    let receivedBody: any = null;
    server.use(
      http.post(
        '/api/v1/cases/case-1/team/members',
        async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ ok: true });
        },
      ),
    );
    const result = await caseService.addCaseTeamMember(
      'case-1',
      'u-1',
      'analyst',
      'Legal',
      'Joined for review',
    );
    expect(receivedBody).toEqual({
      user_id: 'u-1',
      role: 'analyst',
      department: 'Legal',
      notes: 'Joined for review',
    });
    expect(result).toEqual({ ok: true });
  });

  it('omits-as-undefined optional fields when not provided', async () => {
    let receivedBody: any = null;
    server.use(
      http.post(
        '/api/v1/cases/case-1/team/members',
        async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ ok: true });
        },
      ),
    );
    await caseService.addCaseTeamMember('case-1', 'u-2', 'reviewer');
    // axios serializes `undefined` props by dropping them from the JSON
    expect(receivedBody).toEqual({ user_id: 'u-2', role: 'reviewer' });
  });

  it('throws on 409', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/team/members',
        () => new HttpResponse(null, { status: 409 }),
      ),
    );
    await expect(
      caseService.addCaseTeamMember('case-1', 'u-1', 'analyst'),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// removeCaseTeamMember
// ---------------------------------------------------------------------------
describe('caseService.removeCaseTeamMember', () => {
  it('DELETEs the user from the team and returns the response', async () => {
    server.use(
      http.delete('/api/v1/cases/case-1/team/members/u-1', () =>
        HttpResponse.json({ removed: 'u-1' }),
      ),
    );
    const result = await caseService.removeCaseTeamMember(
      'case-1',
      'u-1',
    );
    expect(result).toEqual({ removed: 'u-1' });
  });

  it('throws on 404', async () => {
    server.use(
      http.delete(
        '/api/v1/cases/case-1/team/members/u-1',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(
      caseService.removeCaseTeamMember('case-1', 'u-1'),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// updateCaseTeamMember
// ---------------------------------------------------------------------------
describe('caseService.updateCaseTeamMember', () => {
  it('PUTs the updates payload and returns the response', async () => {
    let receivedBody: any = null;
    server.use(
      http.put(
        '/api/v1/cases/case-1/team/members/u-1',
        async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ updated: true });
        },
      ),
    );
    const result = await caseService.updateCaseTeamMember(
      'case-1',
      'u-1',
      {
        role: 'approver',
        department: 'Compliance',
        notes: 'promoted',
        review_status: 'reviewed',
        approval_status: 'approved',
      },
    );
    expect(receivedBody).toEqual({
      role: 'approver',
      department: 'Compliance',
      notes: 'promoted',
      review_status: 'reviewed',
      approval_status: 'approved',
    });
    expect(result).toEqual({ updated: true });
  });

  it('accepts an empty updates object', async () => {
    let receivedBody: any = null;
    server.use(
      http.put(
        '/api/v1/cases/case-1/team/members/u-1',
        async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ updated: false });
        },
      ),
    );
    await caseService.updateCaseTeamMember('case-1', 'u-1', {});
    expect(receivedBody).toEqual({});
  });

  it('throws on 500', async () => {
    server.use(
      http.put(
        '/api/v1/cases/case-1/team/members/u-1',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      caseService.updateCaseTeamMember('case-1', 'u-1', {
        role: 'analyst',
      }),
    ).rejects.toThrow();
  });
});
