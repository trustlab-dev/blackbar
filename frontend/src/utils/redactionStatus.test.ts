import { describe, it, expect } from 'vitest';
import {
  effectiveRedactionStatus,
  getBlockingRedactions,
  isConversionFailed,
  describeBlockingStatus,
  reviewState,
  describeUnresolved,
  unresolvedReasonLabel,
  canDeleteToResolve,
  unresolvedRedactionsFromError,
  formatUnresolvedList,
  pageRotationsFromDims,
  statusFromServerReview,
} from './redactionStatus';

// A usable box on page 1 (the backend checks geometry before status).
const geo = { page: 1, x: 10, y: 10, width: 50, height: 20 };

// Mirrors backend/src/utils/redaction_records.py effective_status /
// partition_redactions (the single export + release rule, DOC-13).
describe('effectiveRedactionStatus', () => {
  it('treats approved and the legacy "accepted" as approved', () => {
    expect(effectiveRedactionStatus({ ...geo, status: 'approved' })).toBe('approved');
    expect(effectiveRedactionStatus({ ...geo, status: 'Accepted' })).toBe('approved');
  });

  it('treats rejected as rejected (ignored on export)', () => {
    expect(effectiveRedactionStatus({ status: 'rejected' })).toBe('rejected');
  });

  it('treats legacy staff "pending" as approved', () => {
    for (const role of ['owner', 'admin', 'analyst']) {
      expect(
        effectiveRedactionStatus({ ...geo, status: 'pending', created_by_role: role }),
      ).toBe('approved');
    }
  });

  it('keeps "pending" unresolved for plain users, proposals, bulk and coordinate-less records', () => {
    expect(effectiveRedactionStatus({ status: 'pending', created_by_role: 'user' })).toBe('unresolved');
    expect(effectiveRedactionStatus({ status: 'pending' })).toBe('unresolved');
    expect(
      effectiveRedactionStatus({ status: 'pending', created_by_role: 'admin', type: 'proposed' }),
    ).toBe('unresolved');
    expect(
      effectiveRedactionStatus({ status: 'pending', created_by_role: 'admin', bulk_operation: true }),
    ).toBe('unresolved');
    expect(
      effectiveRedactionStatus({ status: 'pending', created_by_role: 'admin', needs_coordinates: true }),
    ).toBe('unresolved');
  });

  it('treats proposed, contested and missing status as unresolved', () => {
    expect(effectiveRedactionStatus({ status: 'proposed' })).toBe('unresolved');
    expect(effectiveRedactionStatus({ status: 'contested' })).toBe('unresolved');
    expect(effectiveRedactionStatus({})).toBe('unresolved');
    expect(effectiveRedactionStatus({ status: null })).toBe('unresolved');
  });
});

describe('getBlockingRedactions', () => {
  it('returns only the unresolved records, in order', () => {
    const a = { ...geo, id: 'a', status: 'approved' };
    const b = { id: 'b', status: 'proposed' };
    const c = { id: 'c', status: 'rejected' };
    const d = { id: 'd', status: 'contested' };
    expect(getBlockingRedactions([a, b, c, d])).toEqual([b, d]);
  });

  it('handles a missing list', () => {
    expect(getBlockingRedactions(undefined)).toEqual([]);
    expect(getBlockingRedactions(null)).toEqual([]);
  });
});

describe('isConversionFailed', () => {
  it('is true for the flag or the status', () => {
    expect(isConversionFailed({ conversion_failed: true })).toBe(true);
    expect(isConversionFailed({ status: 'conversion_failed' })).toBe(true);
    expect(isConversionFailed({ status: 'approved', conversion_failed: false })).toBe(false);
    expect(isConversionFailed(undefined)).toBe(false);
  });
});

describe('describeBlockingStatus', () => {
  it('labels each unresolved kind', () => {
    expect(describeBlockingStatus({ status: 'proposed' })).toBe('Proposed');
    expect(describeBlockingStatus({ status: 'contested' })).toBe('Contested');
    expect(describeBlockingStatus({ status: 'pending' })).toBe('Pending');
    expect(describeBlockingStatus({})).toBe('No status');
  });
});

// review_state in backend/src/utils/redaction_records.py (I1, C1).
describe('reviewState', () => {
  it('gives the backend reason code for each unresolved kind', () => {
    expect(reviewState({ ...geo, status: 'proposed' })).toEqual({ state: 'unresolved', reason: 'proposed' });
    expect(reviewState({ ...geo, status: 'pending', type: 'proposed' })).toEqual({ state: 'unresolved', reason: 'proposed' });
    expect(reviewState({ ...geo, status: 'contested' })).toEqual({ state: 'unresolved', reason: 'contested' });
    expect(reviewState({ ...geo, status: 'pending', created_by_role: 'user' })).toEqual({ state: 'unresolved', reason: 'legacy_pending' });
    expect(reviewState({ ...geo, status: 'pending' })).toEqual({ state: 'unresolved', reason: 'legacy_no_role' });
    expect(reviewState({ ...geo, status: 'weird' })).toEqual({ state: 'unresolved', reason: 'unknown_status' });
    expect(reviewState({ ...geo })).toEqual({ state: 'unresolved', reason: 'unknown_status' });
  });

  it('marks a record with no usable geometry as no_geometry, whatever its status', () => {
    expect(reviewState({ status: 'approved' })).toEqual({ state: 'unresolved', reason: 'no_geometry' });
    expect(reviewState({ ...geo, width: 0, status: 'approved' }).reason).toBe('no_geometry');
    expect(reviewState({ ...geo, height: -1, status: 'approved' }).reason).toBe('no_geometry');
    expect(reviewState({ ...geo, page: 0, status: 'approved' }).reason).toBe('no_geometry');
    expect(reviewState({ ...geo, page: 1.5, status: 'approved' }).reason).toBe('no_geometry');
    expect(reviewState({ ...geo, x: null, status: 'approved' }).reason).toBe('no_geometry');
    expect(reviewState({ ...geo, x: Number.NaN, status: 'approved' }).reason).toBe('no_geometry');
    expect(reviewState({ ...geo, x: true as unknown as number, status: 'approved' }).reason).toBe('no_geometry');
    expect(effectiveRedactionStatus({ status: 'approved' })).toBe('unresolved');
  });

  it('keeps a rejected record rejected even without geometry', () => {
    expect(reviewState({ status: 'rejected' })).toEqual({ state: 'rejected', reason: null });
  });

  it('holds back an approved legacy box on a rotated page (legacy_rotated_coordinates)', () => {
    const legacy = { ...geo, page: 2, status: 'approved' };
    expect(reviewState(legacy, [0, 90])).toEqual({ state: 'unresolved', reason: 'legacy_rotated_coordinates' });
    expect(effectiveRedactionStatus(legacy, [0, 90])).toBe('unresolved');
    // Unrotated page, unknown rotations, or a record in displayed space: approved.
    expect(reviewState(legacy, [0, 0]).state).toBe('approved');
    expect(reviewState(legacy).state).toBe('approved');
    expect(reviewState({ ...legacy, coord_space: 'displayed', page_rotation: 90 }, [0, 90]).state).toBe('approved');
    // Rotation 360 normalises to 0.
    expect(reviewState(legacy, [0, 360]).state).toBe('approved');
    // A proposal keeps its own reason on a rotated page.
    expect(reviewState({ ...legacy, status: 'proposed' }, [0, 90]).reason).toBe('proposed');
  });

  it('getBlockingRedactions applies page rotations', () => {
    const legacy = { ...geo, id: 'l', status: 'approved' };
    expect(getBlockingRedactions([legacy], [90])).toEqual([legacy]);
    expect(getBlockingRedactions([legacy], [0])).toEqual([]);
  });
});

describe('describeUnresolved', () => {
  it('mirrors describe_unresolved: id, page, status, reason, message, approvable', () => {
    expect(describeUnresolved({ ...geo, id: 'r1', status: 'proposed' })).toEqual({
      id: 'r1',
      page: 1,
      status: 'proposed',
      reason: 'proposed',
      message: expect.any(String),
      approvable: true,
    });
    expect(describeUnresolved({ id: 'r2', page: 3, status: 'approved' })).toMatchObject({
      reason: 'no_geometry',
      approvable: false,
    });
    expect(describeUnresolved({ ...geo, id: 'r3', status: 'contested' })).toMatchObject({
      reason: 'contested',
      approvable: false,
    });
    expect(describeUnresolved({ ...geo, id: 'r4', status: 'approved' }, [90])).toMatchObject({
      reason: 'legacy_rotated_coordinates',
      approvable: true,
    });
    expect(describeUnresolved({ ...geo, id: 'r5', status: 'approved' })).toBeNull();
    expect(describeUnresolved({ ...geo, id: 'r6', status: 'rejected' })).toBeNull();
  });
});

describe('unresolved reason helpers', () => {
  it('labels every reason, including the new geometry ones', () => {
    expect(unresolvedReasonLabel('no_geometry')).toMatch(/no usable geometry: delete and re-add/i);
    expect(unresolvedReasonLabel('legacy_rotated_coordinates')).toMatch(/legacy coordinates on a rotated page/i);
    expect(unresolvedReasonLabel('contested')).toMatch(/resolve the contest/i);
    expect(unresolvedReasonLabel('something_new')).toBe('something_new');
  });

  it('offers delete for the reasons whose fix is to re-add the box', () => {
    expect(canDeleteToResolve('no_geometry')).toBe(true);
    expect(canDeleteToResolve('legacy_rotated_coordinates')).toBe(true);
    expect(canDeleteToResolve('proposed')).toBe(false);
    expect(canDeleteToResolve('contested')).toBe(false);
  });

  it('reads error.details.unresolved_redactions from an export 409', () => {
    const list = [
      { id: 'r1', page: 2, status: 'approved', reason: 'no_geometry', message: 'm', approvable: false },
    ];
    const err = {
      response: {
        status: 409,
        data: { error: { code: 'HTTP_409', message: '1 redaction(s)...', details: { unresolved_redactions: list } } },
      },
    };
    expect(unresolvedRedactionsFromError(err)).toEqual(list);
    expect(unresolvedRedactionsFromError({ response: { data: { error: { message: 'x', details: {} } } } })).toEqual([]);
    expect(unresolvedRedactionsFromError(new Error('boom'))).toEqual([]);
    // Malformed entries are dropped.
    expect(
      unresolvedRedactionsFromError({
        response: { data: { error: { details: { unresolved_redactions: [null, 'x', { page: 1 }] } } } },
      }),
    ).toEqual([]);
  });

  it('formats a list as one line per redaction', () => {
    expect(
      formatUnresolvedList([
        { id: 'r1', page: 2, reason: 'no_geometry', approvable: false },
        { id: 'r2', page: null, reason: 'proposed', approvable: true },
      ]),
    ).toEqual([
      'Page 2: No usable geometry: delete and re-add',
      'Page ?: Proposed: awaiting approval',
    ]);
  });

  it('reads page rotations from cached page_dims', () => {
    expect(pageRotationsFromDims([[612, 792, 0], [792, 612, 90]])).toEqual([0, 90]);
    // Entries cached by older builds carry no rotation: unknown.
    expect(pageRotationsFromDims([[612, 792]])).toBeUndefined();
    expect(pageRotationsFromDims(undefined)).toBeUndefined();
    expect(pageRotationsFromDims('nope')).toBeUndefined();
  });
});

describe('statusFromServerReview', () => {
  it('trusts review_required when the server sent the unresolved list', () => {
    const review = { id: 'r1', page: 1, reason: 'legacy_rotated_coordinates', approvable: true };
    expect(statusFromServerReview({ ...geo, status: 'approved', review_required: review }, true)).toEqual({
      effectiveStatus: 'unresolved',
      review,
    });
    // Not listed by the server: approved (or rejected), whatever the client rule says.
    expect(statusFromServerReview({ status: 'approved' }, true)).toEqual({ effectiveStatus: 'approved', review: undefined });
    expect(statusFromServerReview({ status: 'rejected' }, true)).toEqual({ effectiveStatus: 'rejected', review: undefined });
  });

  it('falls back to the client rule without a server list', () => {
    expect(statusFromServerReview({ ...geo, id: 'r1', status: 'proposed' }, false)).toEqual({
      effectiveStatus: 'unresolved',
      review: expect.objectContaining({ reason: 'proposed', approvable: true }),
    });
    expect(statusFromServerReview({ ...geo, status: 'approved' }, false)).toEqual({
      effectiveStatus: 'approved',
      review: undefined,
    });
  });
});
