// frontend/src/components/viewer/coordinates.ts
//
// Pure-function coordinate math shared by viewer components. PDF coordinates
// are page-space units (what the backend stores in bboxes); screen coordinates
// are CSS pixels after react-pdf rendering at the current zoom level. Keep
// this DOM-free where possible so it stays unit-testable without canvas setup.

export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Word/line bbox as `[x0, y0, x1, y1]` (top-left + bottom-right), matching OCR output. */
export type Bbox = [number, number, number, number] | number[];

/** Convert a client point (e.g. `event.clientX/Y`) relative to a rect into PDF page space at the given zoom. */
export function clientPointToPdf(
  clientX: number,
  clientY: number,
  containerRect: { left: number; top: number },
  zoom: number,
): Point {
  return {
    x: (clientX - containerRect.left) / zoom,
    y: (clientY - containerRect.top) / zoom,
  };
}

/** Convert a screen rect (CSS pixels relative to the page canvas) into PDF page space at the given zoom. */
export function screenRectToPdf(
  rect: { x: number; y: number; width: number; height: number },
  zoom: number,
): Rect {
  return {
    x: rect.x / zoom,
    y: rect.y / zoom,
    width: rect.width / zoom,
    height: rect.height / zoom,
  };
}

/** Convert a PDF-space rect into screen pixels at the given zoom. */
export function pdfRectToScreen(rect: Rect, zoom: number): Rect {
  return {
    x: rect.x * zoom,
    y: rect.y * zoom,
    width: rect.width * zoom,
    height: rect.height * zoom,
  };
}

/** Return true if a PDF-space rect overlaps an OCR word bbox `[x0, y0, x1, y1]`. */
export function rectOverlapsBbox(rect: Rect, bbox: Bbox): boolean {
  const [x0, y0, x1, y1] = bbox;
  return !(
    rect.x > x1 ||
    rect.x + rect.width < x0 ||
    rect.y > y1 ||
    rect.y + rect.height < y0
  );
}

/** Merge an array of OCR bboxes `[x0, y0, x1, y1]` into a single enclosing PDF-space rect. */
export function mergeBboxes(bboxes: Bbox[]): Rect {
  if (bboxes.length === 0) return { x: 0, y: 0, width: 0, height: 0 };

  const minX = Math.min(...bboxes.map(b => b[0]));
  const minY = Math.min(...bboxes.map(b => b[1]));
  const maxX = Math.max(...bboxes.map(b => b[2]));
  const maxY = Math.max(...bboxes.map(b => b[3]));

  return {
    x: minX,
    y: minY,
    width: maxX - minX,
    height: maxY - minY,
  };
}
