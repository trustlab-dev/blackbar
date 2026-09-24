import { describe, it, expect } from 'vitest';
import {
  effectiveRedactionStatus,
  getBlockingRedactions,
  isConversionFailed,
  describeBlockingStatus,
} from './redactionStatus';

// Mirrors backend/src/utils/redaction_records.py effective_status /
// partition_redactions (the single export + release rule, DOC-13).
describe('effectiveRedactionStatus', () => {
  it('treats approved and the legacy "accepted" as approved', () => {
    expect(effectiveRedactionStatus({ status: 'approved' })).toBe('approved');
    expect(effectiveRedactionStatus({ status: 'Accepted' })).toBe('approved');
  });

  it('treats rejected as rejected (ignored on export)', () => {
    expect(effectiveRedactionStatus({ status: 'rejected' })).toBe('rejected');
  });

  it('treats legacy staff "pending" as approved', () => {
    for (const role of ['owner', 'admin', 'analyst']) {
      expect(
        effectiveRedactionStatus({ status: 'pending', created_by_role: role }),
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
    const a = { id: 'a', status: 'approved' };
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
