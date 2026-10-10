import { pdfjs } from 'react-pdf';

// Configure the pdf.js worker once. It is bundled by Vite and served from our
// own origin (no CDN), which keeps `worker-src 'self'` in the CSP sufficient.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

/**
 * Hardened pdf.js document options for untrusted PDFs (the public
 * contributor and collection portals accept arbitrary uploads).
 * `isEvalSupported: false` stops the worker compiling PostScript functions
 * with `new Function`, so a CSP without 'unsafe-eval' keeps working.
 *
 * Module-level constant on purpose: react-pdf reloads the document whenever
 * the `options` object identity changes.
 */
export const PDF_DOCUMENT_OPTIONS = Object.freeze({
  isEvalSupported: false,
});
