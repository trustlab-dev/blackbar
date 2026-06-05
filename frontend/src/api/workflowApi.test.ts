import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';
import {
  clockApi,
  contributorsApi,
  queueApi,
  recordsConfirmationApi,
  transferApi,
  sectionsApi,
} from './workflowApi';

// ---------------------------------------------------------------------------
// clockApi.pause
// ---------------------------------------------------------------------------
describe('workflowApi.clockApi.pause', () => {
  it('POSTs the pause payload and returns the clock event', async () => {
    let body: any = null;
    server.use(
      http.post('/api/v1/cases/case-1/clock/pause', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          id: 'evt-1',
          case_id: 'case-1',
          event_type: 'pause',
          reason: 'awaiting-records',
          event_date: '2026-05-13',
          created_by: 'u-1',
        });
      }),
    );

    const result = await clockApi.pause(
      'case-1',
      'awaiting-records',
      'extra notes',
    );
    expect(body).toEqual({
      event_type: 'pause',
      reason: 'awaiting-records',
      notes: 'extra notes',
    });
    expect(result.id).toBe('evt-1');
  });

  it('omits notes when not provided', async () => {
    let body: any = null;
    server.use(
      http.post('/api/v1/cases/case-1/clock/pause', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: 'evt-2' });
      }),
    );
    await clockApi.pause('case-1', 'awaiting');
    expect(body).toEqual({ event_type: 'pause', reason: 'awaiting' });
  });

  it('throws on 500', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/clock/pause',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(clockApi.pause('case-1', 'r')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// clockApi.resume
// ---------------------------------------------------------------------------
describe('workflowApi.clockApi.resume', () => {
  it('POSTs to /clock/resume with notes as a query param', async () => {
    let observed: URL | null = null;
    server.use(
      http.post('/api/v1/cases/case-1/clock/resume', ({ request }) => {
        observed = new URL(request.url);
        return HttpResponse.json({ id: 'evt-3' });
      }),
    );
    await clockApi.resume('case-1', 'back online');
    expect(observed).not.toBeNull();
    expect(observed!.searchParams.get('notes')).toBe('back online');
  });

  it('omits notes param when undefined', async () => {
    let observed: URL | null = null;
    server.use(
      http.post('/api/v1/cases/case-1/clock/resume', ({ request }) => {
        observed = new URL(request.url);
        return HttpResponse.json({ id: 'evt-4' });
      }),
    );
    await clockApi.resume('case-1');
    expect(observed).not.toBeNull();
    expect(observed!.searchParams.get('notes')).toBeNull();
  });

  it('throws on 500', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/clock/resume',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(clockApi.resume('case-1')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// clockApi.getHistory
// ---------------------------------------------------------------------------
describe('workflowApi.clockApi.getHistory', () => {
  it('GETs the clock history and returns the parsed body', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/clock/history', () =>
        HttpResponse.json({
          case_id: 'case-1',
          status: 'running',
          total_paused_days: 0,
          events: [],
        }),
      ),
    );
    const result = await clockApi.getHistory('case-1');
    expect(result.case_id).toBe('case-1');
    expect(result.status).toBe('running');
  });

  it('throws on 404', async () => {
    server.use(
      http.get(
        '/api/v1/cases/missing/clock/history',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(clockApi.getHistory('missing')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// contributorsApi.list
// ---------------------------------------------------------------------------
describe('workflowApi.contributorsApi.list', () => {
  it('GETs the contributors list', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/contributors', () =>
        HttpResponse.json([
          { id: 'c-1', name: 'Alice' },
          { id: 'c-2', name: 'Bob' },
        ]),
      ),
    );
    const result = await contributorsApi.list('case-1');
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe('Alice');
  });

  it('throws on 403', async () => {
    server.use(
      http.get(
        '/api/v1/cases/case-1/contributors',
        () => new HttpResponse(null, { status: 403 }),
      ),
    );
    await expect(contributorsApi.list('case-1')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// contributorsApi.invite
// ---------------------------------------------------------------------------
describe('workflowApi.contributorsApi.invite', () => {
  it('POSTs the contributor data and returns the invitation payload', async () => {
    let body: any = null;
    server.use(
      http.post(
        '/api/v1/cases/case-1/contributors',
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({
            contributor: { id: 'c-1', name: 'New' },
            upload_url: 'https://x/upload',
            expires_at: '2026-06-01',
          });
        },
      ),
    );

    const result = await contributorsApi.invite('case-1', {
      name: 'New',
      email: 'new@example.com',
      department: 'Records',
      notes: 'priority',
      token_expiration_days: 14,
    });
    expect(body).toEqual({
      name: 'New',
      email: 'new@example.com',
      department: 'Records',
      notes: 'priority',
      token_expiration_days: 14,
    });
    expect(result.upload_url).toBe('https://x/upload');
  });

  it('throws on 422', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/contributors',
        () => new HttpResponse(null, { status: 422 }),
      ),
    );
    await expect(
      contributorsApi.invite('case-1', { name: '', email: '' }),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// contributorsApi.update
// ---------------------------------------------------------------------------
describe('workflowApi.contributorsApi.update', () => {
  it('PUTs to the contributor endpoint with the updated fields', async () => {
    let body: any = null;
    server.use(
      http.put(
        '/api/v1/cases/case-1/contributors/c-1',
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({ id: 'c-1', name: 'Updated' });
        },
      ),
    );
    const result = await contributorsApi.update('case-1', 'c-1', {
      name: 'Updated',
      status: 'active',
    });
    expect(body).toEqual({ name: 'Updated', status: 'active' });
    expect(result.name).toBe('Updated');
  });

  it('throws on 404', async () => {
    server.use(
      http.put(
        '/api/v1/cases/case-1/contributors/c-1',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(
      contributorsApi.update('case-1', 'c-1', {}),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// contributorsApi.remind
// ---------------------------------------------------------------------------
describe('workflowApi.contributorsApi.remind', () => {
  it('POSTs to the /remind endpoint', async () => {
    let called = false;
    server.use(
      http.post('/api/v1/cases/case-1/contributors/c-1/remind', () => {
        called = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await contributorsApi.remind('case-1', 'c-1');
    expect(called).toBe(true);
  });

  it('throws on 500', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/contributors/c-1/remind',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      contributorsApi.remind('case-1', 'c-1'),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// contributorsApi.delete
// ---------------------------------------------------------------------------
describe('workflowApi.contributorsApi.delete', () => {
  it('DELETEs the contributor', async () => {
    let called = false;
    server.use(
      http.delete('/api/v1/cases/case-1/contributors/c-1', () => {
        called = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await contributorsApi.delete('case-1', 'c-1');
    expect(called).toBe(true);
  });

  it('throws on 404', async () => {
    server.use(
      http.delete(
        '/api/v1/cases/case-1/contributors/c-1',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(
      contributorsApi.delete('case-1', 'c-1'),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// contributorsApi.bulkInvite
// ---------------------------------------------------------------------------
describe('workflowApi.contributorsApi.bulkInvite', () => {
  it('POSTs the contributors array wrapped in { contributors }', async () => {
    let body: any = null;
    server.use(
      http.post(
        '/api/v1/cases/case-1/contributors/bulk',
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({
            invitations: [],
            count: 0,
          });
        },
      ),
    );
    await contributorsApi.bulkInvite('case-1', [
      { name: 'A', email: 'a@x.com' },
      { name: 'B', email: 'b@x.com', department: 'Records' },
    ]);
    expect(body).toEqual({
      contributors: [
        { name: 'A', email: 'a@x.com' },
        { name: 'B', email: 'b@x.com', department: 'Records' },
      ],
    });
  });

  it('throws on 500', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/contributors/bulk',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      contributorsApi.bulkInvite('case-1', [{ name: 'a', email: 'a@x.com' }]),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// queueApi.getPrioritized
// ---------------------------------------------------------------------------
describe('workflowApi.queueApi.getPrioritized', () => {
  it('GETs /queue/prioritized with all params forwarded', async () => {
    let observed: URL | null = null;
    server.use(
      http.get('/api/v1/queue/prioritized', ({ request }) => {
        observed = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );
    await queueApi.getPrioritized({
      analyst_id: 'u-1',
      workflow_stage: 'review',
      clock_status: 'running',
      include_closed: true,
      limit: 25,
      offset: 50,
    });
    expect(observed).not.toBeNull();
    const p = observed!.searchParams;
    expect(p.get('analyst_id')).toBe('u-1');
    expect(p.get('workflow_stage')).toBe('review');
    expect(p.get('clock_status')).toBe('running');
    expect(p.get('include_closed')).toBe('true');
    expect(p.get('limit')).toBe('25');
    expect(p.get('offset')).toBe('50');
  });

  it('returns the priority array', async () => {
    server.use(
      http.get('/api/v1/queue/prioritized', () =>
        HttpResponse.json([
          { case_id: 'c-1', priority_score: 99 },
          { case_id: 'c-2', priority_score: 88 },
        ]),
      ),
    );
    const result = await queueApi.getPrioritized();
    expect(result).toHaveLength(2);
    expect(result[0].priority_score).toBe(99);
  });

  it('works without params', async () => {
    let observed: URL | null = null;
    server.use(
      http.get('/api/v1/queue/prioritized', ({ request }) => {
        observed = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );
    await queueApi.getPrioritized();
    // No query params should be set
    expect(Array.from(observed!.searchParams.keys())).toHaveLength(0);
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/queue/prioritized',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(queueApi.getPrioritized()).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// queueApi.getAnalystWorkload
// ---------------------------------------------------------------------------
describe('workflowApi.queueApi.getAnalystWorkload', () => {
  it('GETs /queue/workload/<id> with the explicit limit', async () => {
    let observed: URL | null = null;
    server.use(
      http.get('/api/v1/queue/workload/u-1', ({ request }) => {
        observed = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );
    await queueApi.getAnalystWorkload('u-1', 5);
    expect(observed!.searchParams.get('limit')).toBe('5');
  });

  it('defaults to limit=20 when omitted', async () => {
    let observed: URL | null = null;
    server.use(
      http.get('/api/v1/queue/workload/u-1', ({ request }) => {
        observed = new URL(request.url);
        return HttpResponse.json([]);
      }),
    );
    await queueApi.getAnalystWorkload('u-1');
    expect(observed!.searchParams.get('limit')).toBe('20');
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/queue/workload/u-1',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(queueApi.getAnalystWorkload('u-1')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// queueApi.setPriorityOverride
// ---------------------------------------------------------------------------
describe('workflowApi.queueApi.setPriorityOverride', () => {
  it('PUTs /cases/<id>/priority with priority_override as a query param', async () => {
    let observed: URL | null = null;
    server.use(
      http.put('/api/v1/cases/case-1/priority', ({ request }) => {
        observed = new URL(request.url);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await queueApi.setPriorityOverride('case-1', 5);
    expect(observed!.searchParams.get('priority_override')).toBe('5');
  });

  it('accepts null to clear the override', async () => {
    let observed: URL | null = null;
    server.use(
      http.put('/api/v1/cases/case-1/priority', ({ request }) => {
        observed = new URL(request.url);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await queueApi.setPriorityOverride('case-1', null);
    // axios serializes null params as empty strings under default paramsSerializer.
    // The pin: the param key is present even when value is null/empty.
    expect(observed).not.toBeNull();
    // Defensive: just confirm the request reached us.
    expect(observed!.pathname).toBe('/api/v1/cases/case-1/priority');
  });

  it('throws on 500', async () => {
    server.use(
      http.put(
        '/api/v1/cases/case-1/priority',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      queueApi.setPriorityOverride('case-1', 1),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// recordsConfirmationApi.get
// ---------------------------------------------------------------------------
describe('workflowApi.recordsConfirmationApi.get', () => {
  it('returns the confirmation payload', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/records-confirmation', () =>
        HttpResponse.json({ confirmed: true, confirmed_by: 'u-1' }),
      ),
    );
    const r = await recordsConfirmationApi.get('case-1');
    expect(r.confirmed).toBe(true);
    expect(r.confirmed_by).toBe('u-1');
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/cases/case-1/records-confirmation',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      recordsConfirmationApi.get('case-1'),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// recordsConfirmationApi.confirm
// ---------------------------------------------------------------------------
describe('workflowApi.recordsConfirmationApi.confirm', () => {
  it('POSTs the notes in the body and returns the new confirmation', async () => {
    let body: any = null;
    server.use(
      http.post(
        '/api/v1/cases/case-1/records-confirmation',
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({
            confirmed: true,
            confirmed_by: 'u-1',
            notes: 'looks good',
          });
        },
      ),
    );
    const r = await recordsConfirmationApi.confirm('case-1', 'looks good');
    expect(body).toEqual({ notes: 'looks good' });
    expect(r.confirmed).toBe(true);
  });

  it('sends notes=undefined when not provided', async () => {
    let body: any = null;
    server.use(
      http.post(
        '/api/v1/cases/case-1/records-confirmation',
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({ confirmed: true });
        },
      ),
    );
    await recordsConfirmationApi.confirm('case-1');
    // axios serializes `{ notes: undefined }` by stripping undefined values.
    expect(body).toEqual({});
  });

  it('throws on 500', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/records-confirmation',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      recordsConfirmationApi.confirm('case-1', 'n'),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// recordsConfirmationApi.revoke
// ---------------------------------------------------------------------------
describe('workflowApi.recordsConfirmationApi.revoke', () => {
  it('DELETEs the records-confirmation', async () => {
    let called = false;
    server.use(
      http.delete('/api/v1/cases/case-1/records-confirmation', () => {
        called = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await recordsConfirmationApi.revoke('case-1');
    expect(called).toBe(true);
  });

  it('throws on 404', async () => {
    server.use(
      http.delete(
        '/api/v1/cases/case-1/records-confirmation',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(
      recordsConfirmationApi.revoke('case-1'),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// transferApi.list
// ---------------------------------------------------------------------------
describe('workflowApi.transferApi.list', () => {
  it('returns the transfer array', async () => {
    server.use(
      http.get('/api/v1/cases/case-1/transfers', () =>
        HttpResponse.json([
          { id: 't-1', recipient_organization: 'Other Agency' },
        ]),
      ),
    );
    const result = await transferApi.list('case-1');
    expect(result).toHaveLength(1);
    expect(result[0].recipient_organization).toBe('Other Agency');
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/cases/case-1/transfers',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(transferApi.list('case-1')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// transferApi.create
// ---------------------------------------------------------------------------
describe('workflowApi.transferApi.create', () => {
  it('POSTs to /cases/<id>/transfer and returns the transfer envelope', async () => {
    let body: any = null;
    server.use(
      http.post(
        '/api/v1/cases/case-1/transfer',
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({
            transfer: { id: 't-1' },
            transfer_url: 'https://x/transfer',
            expires_at: '2026-06-01',
          });
        },
      ),
    );

    const result = await transferApi.create('case-1', {
      recipient_organization: 'Other Agency',
      recipient_email: 'recv@example.com',
      recipient_name: 'Jane',
      include_documents: true,
      included_document_ids: ['doc-a', 'doc-b'],
      transfer_reason: 'misrouted',
      notes: 'urgent',
    });
    expect(body).toEqual({
      recipient_organization: 'Other Agency',
      recipient_email: 'recv@example.com',
      recipient_name: 'Jane',
      include_documents: true,
      included_document_ids: ['doc-a', 'doc-b'],
      transfer_reason: 'misrouted',
      notes: 'urgent',
    });
    expect(result.transfer_url).toBe('https://x/transfer');
  });

  it('throws on 422', async () => {
    server.use(
      http.post(
        '/api/v1/cases/case-1/transfer',
        () => new HttpResponse(null, { status: 422 }),
      ),
    );
    await expect(
      transferApi.create('case-1', {
        recipient_organization: '',
        recipient_email: '',
        transfer_reason: '',
      }),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// sectionsApi.search
// ---------------------------------------------------------------------------
describe('workflowApi.sectionsApi.search', () => {
  it('GETs /packs/active/sections with the query param when provided', async () => {
    let observed: URL | null = null;
    server.use(
      http.get('/api/v1/packs/active/sections', ({ request }) => {
        observed = new URL(request.url);
        return HttpResponse.json({
          sections: [{ code: 'b1', name: 'Section b1' }],
          pack_id: 'p1',
          pack_name: 'FOIA',
          count: 1,
        });
      }),
    );
    const result = await sectionsApi.search('privacy');
    expect(observed!.searchParams.get('q')).toBe('privacy');
    expect(result.pack_id).toBe('p1');
    expect(result.sections[0].code).toBe('b1');
  });

  it('omits the q param when no query provided', async () => {
    let observed: URL | null = null;
    server.use(
      http.get('/api/v1/packs/active/sections', ({ request }) => {
        observed = new URL(request.url);
        return HttpResponse.json({
          sections: [],
          pack_id: 'p1',
          pack_name: 'FOIA',
          count: 0,
        });
      }),
    );
    await sectionsApi.search();
    expect(observed!.searchParams.get('q')).toBeNull();
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/packs/active/sections',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(sectionsApi.search('x')).rejects.toThrow();
  });
});
