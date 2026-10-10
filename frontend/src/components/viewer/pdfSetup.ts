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
 *
 * pdf.js 6 removed `isEvalSupported`: PostScript functions are compiled to
 * WebAssembly or run by a JS interpreter, never through `new Function`, so a
 * CSP without 'unsafe-eval' keeps working with no option needed. Under our
 * CSP (no 'wasm-unsafe-eval') pdf.js falls back to the JS interpreter.
 * `enableXfa: false` is the pdf.js default; it is pinned here so XFA forms
 * in an upload are never rendered as live HTML if that default changes.
 *
 * Module-level constant on purpose: react-pdf reloads the document whenever
 * the `options` object identity changes.
 */
export const PDF_DOCUMENT_OPTIONS = Object.freeze({
  enableXfa: false,
});
