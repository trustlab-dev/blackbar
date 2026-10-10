import api from './client';

/**
 * POST /documents/{id}/ai-feedback
 * (backend/src/documents/redaction_suggestion_routes.py `record_ai_feedback`).
 *
 * `feedback` must be "accepted" or "rejected" (422 otherwise). The caller
 * must be able to access the document (403/404 otherwise). Category and
 * reason are sent as strings even when a suggestion lacks them, since the
 * backend requires `suggestion_category` and types `suggestion_reason` as a
 * string.
 */
export type AiFeedback = 'accepted' | 'rejected';

export interface AiFeedbackSuggestion {
  text: string;
  category?: string | null;
  reason?: string | null;
}

export function postAiFeedback(
  documentId: string,
  suggestion: AiFeedbackSuggestion,
  feedback: AiFeedback,
  context: string,
) {
  return api.post(`/documents/${documentId}/ai-feedback`, {
    suggestion_text: suggestion.text ?? '',
    suggestion_category: suggestion.category ?? '',
    suggestion_reason: suggestion.reason ?? '',
    feedback,
    context,
  });
}
