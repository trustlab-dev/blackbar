/**
 * The export/release status rule, mirrored from the backend so the UI can
 * show what will block a document before the server refuses it.
 *
 * Authority: backend/src/utils/redaction_records.py `effective_status` and
 * `partition_redactions` (DOC-13). Only approved redactions are burned in;
 * rejected ones are ignored; anything else blocks export (409) and makes the
 * release package mark the document failed. Keep this file in sync.
 */

export type EffectiveRedactionStatus = 'approved' | 'rejected' | 'unresolved';

/** The raw fields of a stored redaction record that decide its status. */
export interface RedactionStatusFields {
  status?: string | null;
  type?: string | null;
  created_by_role?: string | null;
  bulk_operation?: boolean | null;
  needs_coordinates?: boolean | null;
}

// System roles whose manually drawn redactions were stored as "pending" by
// older builds but always applied. They count as approved.
const STAFF_ROLES = new Set(['owner', 'admin', 'analyst']);

export function effectiveRedactionStatus(
  redaction: RedactionStatusFields,
): EffectiveRedactionStatus {
  const status = String(redaction.status ?? '').trim().toLowerCase();
  if (status === 'approved' || status === 'accepted') return 'approved';
  if (status === 'rejected') return 'rejected';
  if (
    status === 'pending' &&
    redaction.type !== 'proposed' &&
    !redaction.bulk_operation &&
    !redaction.needs_coordinates &&
    STAFF_ROLES.has(String(redaction.created_by_role ?? ''))
  ) {
    return 'approved';
  }
  return 'unresolved';
}

/** Redactions that block export/release until a reviewer decides them. */
export function getBlockingRedactions<T extends RedactionStatusFields>(
  redactions: T[] | null | undefined,
): T[] {
  return (redactions ?? []).filter((r) => effectiveRedactionStatus(r) === 'unresolved');
}

/** Short label for why a redaction is blocking. */
export function describeBlockingStatus(redaction: RedactionStatusFields): string {
  const status = String(redaction.status ?? '').trim().toLowerCase();
  if (!status) return 'No status';
  return status.charAt(0).toUpperCase() + status.slice(1);
}

/**
 * A document whose conversion to PDF failed holds native bytes only: it
 * cannot be redacted, approved or released (backend returns 409).
 * Mirrors backend/src/documents/redaction_store.py assert_not_conversion_failed.
 */
export function isConversionFailed(
  doc: { status?: string | null; conversion_failed?: boolean | null } | null | undefined,
): boolean {
  return Boolean(doc?.conversion_failed) || doc?.status === 'conversion_failed';
}
