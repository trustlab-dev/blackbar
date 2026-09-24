/**
 * The export/release status rule, mirrored from the backend so the UI can
 * show what will block a document before the server refuses it.
 *
 * Authority: backend/src/utils/redaction_records.py `review_state`,
 * `partition_redactions` and `UNRESOLVED_REASONS` (DOC-13, I1, C1). Only
 * approved redactions are burned in; rejected ones are ignored; anything else
 * blocks export (409) and makes the release package mark the document failed.
 * Keep this file in sync.
 *
 * The document metadata response carries the server's own verdict
 * (`unresolved_redactions` and `review_required` per record,
 * backend/src/documents/routes.py get_document_metadata). Prefer that when it
 * is present; this rule is the fallback for responses without it and for
 * lists (case documents) that only carry raw records.
 */

export type EffectiveRedactionStatus = 'approved' | 'rejected' | 'unresolved';

/** Reason codes, keys of UNRESOLVED_REASONS in redaction_records.py. */
export type UnresolvedReason =
  | 'proposed'
  | 'contested'
  | 'legacy_pending'
  | 'legacy_no_role'
  | 'legacy_rotated_coordinates'
  | 'unknown_status'
  | 'no_geometry';

/** The raw fields of a stored redaction record that decide its status. */
export interface RedactionStatusFields {
  status?: string | null;
  type?: string | null;
  created_by_role?: string | null;
  bulk_operation?: boolean | null;
  needs_coordinates?: boolean | null;
  page?: unknown;
  x?: unknown;
  y?: unknown;
  width?: unknown;
  height?: unknown;
  coord_space?: string | null;
  page_rotation?: number | null;
}

/**
 * One blocking redaction as the backend describes it (`describe_unresolved`):
 * in the metadata `unresolved_redactions` list, as `review_required` on each
 * record, under `error.details.unresolved_redactions` of an export 409, and
 * as `unresolved_redactions` on a failed release package document.
 */
export interface UnresolvedRedaction {
  id?: string | null;
  page?: number | null;
  status?: string | null;
  reason: UnresolvedReason | string;
  message?: string;
  approvable: boolean;
}

interface ReasonInfo {
  /** Short label for lists and banners. */
  label: string;
  /** The backend's message (UNRESOLVED_REASONS[reason][0]). */
  message: string;
  /** The approve/reject route can resolve it. */
  approvable: boolean;
}

export const UNRESOLVED_REASONS: Record<UnresolvedReason, ReasonInfo> = {
  proposed: {
    label: 'Proposed: awaiting approval',
    message: 'Proposed redaction awaiting approval.',
    approvable: true,
  },
  contested: {
    label: 'Contested: resolve the contest first',
    message: 'Redaction has an open contest; resolve the contest first.',
    approvable: false,
  },
  legacy_pending: {
    label: "Legacy 'pending' record: approve or reject",
    message:
      "Created as 'pending' by an older version of BlackBar and never approved; approve or reject it.",
    approvable: true,
  },
  legacy_no_role: {
    label: 'Legacy record without a creator role: approve or reject',
    message:
      'Created by an older version of BlackBar without a recorded creator role; approve or reject it.',
    approvable: true,
  },
  legacy_rotated_coordinates: {
    label: 'Legacy coordinates on a rotated page: check its position, then approve, or delete and re-add',
    message:
      'Created by an older version of BlackBar on a rotated page, so its position is ambiguous. ' +
      'Check where it appears in the viewer, then approve it to confirm that position, or delete ' +
      'it and add it again.',
    approvable: true,
  },
  unknown_status: {
    label: 'No recognised status: approve or reject',
    message: 'Redaction has no recognised review status; approve or reject it.',
    approvable: true,
  },
  no_geometry: {
    label: 'No usable geometry: delete and re-add',
    message:
      'Redaction has no usable position on the page and cannot be approved. Delete it and add ' +
      'it again (re-run bulk apply for bulk or AI redactions).',
    approvable: false,
  },
};

// Reasons whose fix can be deleting the box and adding it again.
const DELETE_TO_RESOLVE = new Set<string>(['no_geometry', 'legacy_rotated_coordinates']);

// System roles whose manually drawn redactions were stored as "pending" by
// older builds but always applied. They count as approved.
const STAFF_ROLES = new Set(['owner', 'admin', 'analyst']);

/** Pydantic-lax number: finite numbers and numeric strings; never booleans. */
function toNumber(value: unknown): number {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim() !== '') return Number(value);
  return Number.NaN;
}

/** Mirrors RedactionGeometry: integral page >= 1, finite x/y, positive size. */
function geometryPage(redaction: RedactionStatusFields): number | null {
  const page = toNumber(redaction.page);
  const x = toNumber(redaction.x);
  const y = toNumber(redaction.y);
  const width = toNumber(redaction.width);
  const height = toNumber(redaction.height);
  if (!Number.isInteger(page) || page < 1) return null;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (!Number.isFinite(width) || !(width > 0)) return null;
  if (!Number.isFinite(height) || !(height > 0)) return null;
  return page;
}

function normaliseRotation(value: unknown): number {
  const n = Math.trunc(toNumber(value));
  return Number.isFinite(n) ? ((n % 360) + 360) % 360 : 0;
}

/**
 * `(state, reason)` for one stored record, as `review_state` computes it.
 * Pass `pageRotations` (one entry per page) when known, so an approved
 * legacy box on a rotated page is held back (`legacy_rotated_coordinates`).
 */
export function reviewState(
  redaction: RedactionStatusFields,
  pageRotations?: readonly number[] | null,
): { state: EffectiveRedactionStatus; reason: UnresolvedReason | null } {
  const status = String(redaction.status ?? '').trim().toLowerCase();
  if (status === 'rejected') return { state: 'rejected', reason: null };
  const page = geometryPage(redaction);
  if (page === null) return { state: 'unresolved', reason: 'no_geometry' };

  let state: EffectiveRedactionStatus;
  let reason: UnresolvedReason | null = null;
  if (status === 'approved' || status === 'accepted') {
    state = 'approved';
  } else if (status === 'proposed' || (redaction.type === 'proposed' && status === 'pending')) {
    state = 'unresolved';
    reason = 'proposed';
  } else if (status === 'contested') {
    state = 'unresolved';
    reason = 'contested';
  } else if (status === 'pending') {
    const role = redaction.created_by_role;
    if (
      STAFF_ROLES.has(String(role ?? '')) &&
      !redaction.bulk_operation &&
      !redaction.needs_coordinates
    ) {
      state = 'approved';
    } else {
      state = 'unresolved';
      reason = role ? 'legacy_pending' : 'legacy_no_role';
    }
  } else {
    state = 'unresolved';
    reason = 'unknown_status';
  }

  if (
    state === 'approved' &&
    pageRotations &&
    !redaction.coord_space &&
    page <= pageRotations.length &&
    normaliseRotation(pageRotations[page - 1]) !== 0
  ) {
    return { state: 'unresolved', reason: 'legacy_rotated_coordinates' };
  }
  return { state, reason };
}

export function effectiveRedactionStatus(
  redaction: RedactionStatusFields,
  pageRotations?: readonly number[] | null,
): EffectiveRedactionStatus {
  return reviewState(redaction, pageRotations).state;
}

/** Redactions that block export/release until a reviewer decides them. */
export function getBlockingRedactions<T extends RedactionStatusFields>(
  redactions: T[] | null | undefined,
  pageRotations?: readonly number[] | null,
): T[] {
  return (redactions ?? []).filter(
    (r) => effectiveRedactionStatus(r, pageRotations) === 'unresolved',
  );
}

/** Client-side `describe_unresolved`: why a record blocks, or null. */
export function describeUnresolved(
  redaction: RedactionStatusFields & { id?: string | null },
  pageRotations?: readonly number[] | null,
): UnresolvedRedaction | null {
  const { state, reason } = reviewState(redaction, pageRotations);
  if (state !== 'unresolved' || reason === null) return null;
  const page = toNumber(redaction.page);
  return {
    id: redaction.id ?? null,
    page: Number.isFinite(page) ? page : null,
    status: redaction.status ?? null,
    reason,
    message: UNRESOLVED_REASONS[reason].message,
    approvable: UNRESOLVED_REASONS[reason].approvable,
  };
}

/** Short label for a reason code; unknown codes are shown as they are. */
export function unresolvedReasonLabel(reason: string): string {
  return (UNRESOLVED_REASONS as Record<string, ReasonInfo>)[reason]?.label ?? reason;
}

/** Whether deleting (and re-adding) the box is a way to resolve it. */
export function canDeleteToResolve(reason: string): boolean {
  return DELETE_TO_RESOLVE.has(reason);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Keeps the well-formed entries of an `unresolved_redactions` list. */
export function parseUnresolvedList(value: unknown): UnresolvedRedaction[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (d): d is UnresolvedRedaction => isObject(d) && typeof d.reason === 'string',
  ).map((d) => ({ ...d, approvable: Boolean(d.approvable) }));
}

/**
 * The blocking redactions listed in an export 409:
 * `{error: {message, details: {unresolved_redactions: [...]}}}`
 * (routes.py export_document_with_redactions, via error_handler.py).
 */
export function unresolvedRedactionsFromError(err: unknown): UnresolvedRedaction[] {
  if (!isObject(err) || !isObject(err.response)) return [];
  const data = err.response.data;
  if (!isObject(data) || !isObject(data.error) || !isObject(data.error.details)) return [];
  return parseUnresolvedList(data.error.details.unresolved_redactions);
}

/** "Page N: <label>" for each blocking redaction. */
export function formatUnresolvedList(details: UnresolvedRedaction[]): string[] {
  return details.map(
    (d) => `Page ${d.page ?? '?'}: ${unresolvedReasonLabel(String(d.reason))}`,
  );
}

/**
 * Page rotations from a document's cached `page_dims` (`[[w, h, rotation],
 * ...]`, redaction_store.py). Undefined when unknown, including entries
 * cached by older builds without the rotation.
 */
export function pageRotationsFromDims(dims: unknown): number[] | undefined {
  if (!Array.isArray(dims) || dims.length === 0) return undefined;
  const rotations: number[] = [];
  for (const entry of dims) {
    if (!Array.isArray(entry) || entry.length < 3) return undefined;
    const rotation = toNumber(entry[2]);
    if (!Number.isFinite(rotation)) return undefined;
    rotations.push(normaliseRotation(rotation));
  }
  return rotations;
}

/**
 * Status of a record from the metadata response. When the response carries
 * the server's `unresolved_redactions` list, a record blocks exactly when it
 * has `review_required`; otherwise the client rule decides.
 */
export function statusFromServerReview(
  redaction: RedactionStatusFields & { id?: string | null; review_required?: unknown },
  hasServerList: boolean,
  pageRotations?: readonly number[] | null,
): { effectiveStatus: EffectiveRedactionStatus; review: UnresolvedRedaction | undefined } {
  if (hasServerList) {
    const [review] = parseUnresolvedList([redaction.review_required]);
    if (review) return { effectiveStatus: 'unresolved', review };
    const rejected = String(redaction.status ?? '').trim().toLowerCase() === 'rejected';
    return { effectiveStatus: rejected ? 'rejected' : 'approved', review: undefined };
  }
  const review = describeUnresolved(redaction, pageRotations) ?? undefined;
  return { effectiveStatus: effectiveRedactionStatus(redaction, pageRotations), review };
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
