/**
 * Client-side upload checks. Defense in depth and a better error message
 * only: the backend (backend/src/documents/processing_service.py
 * `_validate_file`) is the authority. Keep these lists in sync with its
 * ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES and MAX_FILE_SIZE.
 */

export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // backend MAX_FILE_SIZE

export const ALLOWED_UPLOAD_EXTENSIONS = [
  '.pdf',
  '.doc',
  '.docx',
  '.xls',
  '.xlsx',
  '.ppt',
  '.pptx',
  '.eml',
  '.msg',
  '.jpg',
  '.jpeg',
  '.png',
  '.gif',
  '.bmp',
  '.tiff',
  '.tif',
  '.webp',
] as const;

export const ALLOWED_UPLOAD_MIME_TYPES: ReadonlySet<string> = new Set([
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'message/rfc822',
  'application/vnd.ms-outlook',
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/bmp',
  'image/tiff',
  'image/webp',
]);

/** backend EXTENSION_MIME_TYPES: the type each allowed extension is sent as. */
export const EXTENSION_MIME_TYPES: Readonly<Record<string, string>> = {
  '.pdf': 'application/pdf',
  '.doc': 'application/msword',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xls': 'application/vnd.ms-excel',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.ppt': 'application/vnd.ms-powerpoint',
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  '.eml': 'message/rfc822',
  '.msg': 'application/vnd.ms-outlook',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.gif': 'image/gif',
  '.bmp': 'image/bmp',
  '.tiff': 'image/tiff',
  '.tif': 'image/tiff',
  '.webp': 'image/webp',
};

// What a browser reports for a format it has no MIME mapping for (Outlook
// .msg on a machine without Office, for example). An empty type is then sent
// as application/octet-stream in the multipart body, which the backend
// rejects, so such files are re-typed from their extension before upload.
const UNTYPED_MIME = new Set(['', 'application/octet-stream']);

/** Value for an `<input type="file" accept=...>` attribute. */
export const UPLOAD_ACCEPT = ALLOWED_UPLOAD_EXTENSIONS.join(',');

const MAX_UPLOAD_MB = Math.round(MAX_UPLOAD_BYTES / (1024 * 1024));

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot).toLowerCase() : '';
}

/** Returns a user-facing error for `file`, or null when it may be uploaded. */
export function validateUploadFile(file: File): string | null {
  const ext = extensionOf(file.name);
  const typeOk =
    (ALLOWED_UPLOAD_EXTENSIONS as readonly string[]).includes(ext) &&
    // Browsers leave `type` empty, or say octet-stream, for formats they
    // don't know (e.g. .msg). withUploadMimeType fixes the type before upload.
    (UNTYPED_MIME.has(file.type) || ALLOWED_UPLOAD_MIME_TYPES.has(file.type));
  if (!typeOk) {
    return `"${file.name}" is not a supported file type. Allowed: ${ALLOWED_UPLOAD_EXTENSIONS.join(', ')}.`;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `"${file.name}" is too large. The maximum file size is ${MAX_UPLOAD_MB} MB.`;
  }
  return null;
}

/**
 * Give an untyped file (empty or application/octet-stream) the MIME type of
 * its extension, so the multipart part carries a type the backend accepts.
 * The backend's magic-byte sniff remains the real content check.
 */
export function withUploadMimeType(file: File): File {
  if (!UNTYPED_MIME.has(file.type)) return file;
  const ext = extensionOf(file.name);
  if (!Object.prototype.hasOwnProperty.call(EXTENSION_MIME_TYPES, ext)) return file;
  return new File([file], file.name, {
    type: EXTENSION_MIME_TYPES[ext],
    lastModified: file.lastModified,
  });
}

/**
 * Split a selection into uploadable files and one error message per rejected
 * file. Valid files come back typed (withUploadMimeType), ready for FormData.
 */
export function partitionUploadFiles(files: File[]): { valid: File[]; errors: string[] } {
  const valid: File[] = [];
  const errors: string[] = [];
  for (const file of files) {
    const error = validateUploadFile(file);
    if (error) errors.push(error);
    else valid.push(withUploadMimeType(file));
  }
  return { valid, errors };
}

/**
 * Non-fatal problems reported by a successful upload (POST /documents/):
 * `warnings` (email thread consolidation failures, dropped attachments;
 * backend/src/documents/routes.py upload_document) and the single `warning`
 * sent when conversion to PDF failed. Shown to the user after upload.
 */
export function getUploadWarnings(data: unknown): string[] {
  if (typeof data !== 'object' || data === null) return [];
  const record = data as { warnings?: unknown; warning?: unknown };
  const raw: unknown[] = [
    ...(Array.isArray(record.warnings) ? record.warnings : []),
    record.warning,
  ];
  return raw
    .filter((w): w is string => typeof w === 'string')
    .map((w) => w.trim())
    .filter((w) => w !== '');
}
