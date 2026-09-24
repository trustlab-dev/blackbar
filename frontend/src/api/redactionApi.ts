/**
 * Redaction endpoints (backend/src/documents/redaction_routes.py and
 * routes.py export handler). Redactions are addressed by their stable `id`
 * (a uuid on every record), never by array index (DOC-23).
 */
import api, { TRANSFER_TIMEOUT_MS } from './client';
import { withParsedBlobErrorBody } from './errors';

export interface AddRedactionPayload {
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  category?: string;
  description?: string;
  reason?: string;
  notes?: string;
  text?: string;
  section?: string;
}

/**
 * POST /documents/{id}/redactions. Staff and case analysts get `approved`
 * immediately; everyone else gets a `proposed` record an analyst must approve.
 */
export interface AddRedactionResponse {
  message: string;
  id: string;
  status: string;
}

export async function addRedaction(
  documentId: string,
  payload: AddRedactionPayload,
): Promise<AddRedactionResponse> {
  const response = await api.post(`/documents/${encodeURIComponent(documentId)}/redactions`, payload);
  return response.data;
}

export type RedactionReviewAction = 'approve' | 'reject';

export interface RedactionReviewResponse {
  success: boolean;
  message: string;
  redaction_id: string;
}

/**
 * PUT /documents/{id}/redactions/{redaction_id}/approve. Analysts/managers on
 * the case only. 409 means the redaction changed concurrently: reload.
 */
export async function reviewProposedRedaction(
  documentId: string,
  redactionId: string,
  action: RedactionReviewAction,
  notes?: string,
): Promise<RedactionReviewResponse> {
  const body: { action: RedactionReviewAction; notes?: string } = { action };
  if (notes) body.notes = notes;
  const response = await api.put(
    `/documents/${encodeURIComponent(documentId)}/redactions/${encodeURIComponent(redactionId)}/approve`,
    body,
  );
  return response.data;
}

/** Filename from an RFC 6266 header: `filename*` first, then `filename`. */
export function filenameFromContentDisposition(
  header: string | null | undefined,
  fallback: string,
): string {
  if (!header) return fallback;
  const extended = header.match(/filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/);
  if (extended) {
    try {
      return decodeURIComponent(extended[1].trim());
    } catch {
      // fall through to the ASCII filename
    }
  }
  const plain = header.match(/filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;\s]+)/);
  if (plain) return plain[1] || plain[2];
  return fallback;
}

/**
 * GET /documents/{id}/export: the PDF with approved redactions burned in.
 * Rejects with 409 when redactions are awaiting review or the document failed
 * conversion, 413 over the page limit, 422 when it cannot be safely redacted.
 * The error body is parsed so getApiErrorMessage shows the server's reason.
 */
export async function exportRedactedDocument(
  documentId: string,
  fallbackFilename: string,
): Promise<{ blob: Blob; filename: string }> {
  try {
    const response = await api.get(`/documents/${encodeURIComponent(documentId)}/export`, {
      responseType: 'blob',
      timeout: TRANSFER_TIMEOUT_MS,
    });
    const header = response.headers?.['content-disposition'];
    return {
      blob: response.data,
      filename: filenameFromContentDisposition(
        typeof header === 'string' ? header : undefined,
        fallbackFilename,
      ),
    };
  } catch (err) {
    throw await withParsedBlobErrorBody(err);
  }
}
