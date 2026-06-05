// frontend/src/components/viewer/coordinates.test.ts
//
// Pure-function unit tests for PDF↔screen coordinate math.
// 100% line + branch coverage required (critical-path redaction canvas logic).

import { describe, it, expect } from 'vitest';
import {
  clientPointToPdf,
  screenRectToPdf,
  pdfRectToScreen,
  rectOverlapsBbox,
  mergeBboxes,
} from './coordinates';

// ---------------------------------------------------------------------------
// clientPointToPdf
// ---------------------------------------------------------------------------
describe('clientPointToPdf', () => {
  it('subtracts container offset and divides by zoom = 1', () => {
    const result = clientPointToPdf(100, 200, { left: 10, top: 20 }, 1);
    expect(result).toEqual({ x: 90, y: 180 });
  });

  it('handles zoom > 1 (zoomed in)', () => {
    const result = clientPointToPdf(200, 300, { left: 0, top: 0 }, 2);
    expect(result).toEqual({ x: 100, y: 150 });
  });

  it('handles fractional zoom (zoomed out)', () => {
    const result = clientPointToPdf(50, 100, { left: 0, top: 0 }, 0.5);
    expect(result).toEqual({ x: 100, y: 200 });
  });

  it('handles negative offsets (point above/left of container)', () => {
    const result = clientPointToPdf(5, 5, { left: 10, top: 10 }, 1);
    expect(result).toEqual({ x: -5, y: -5 });
  });

  it('handles zero coordinates', () => {
    const result = clientPointToPdf(0, 0, { left: 0, top: 0 }, 1);
    expect(result).toEqual({ x: 0, y: 0 });
  });
});

// ---------------------------------------------------------------------------
// screenRectToPdf
// ---------------------------------------------------------------------------
describe('screenRectToPdf', () => {
  it('divides all dimensions by zoom = 1 (identity)', () => {
    const result = screenRectToPdf(
      { x: 10, y: 20, width: 100, height: 200 },
      1,
    );
    expect(result).toEqual({ x: 10, y: 20, width: 100, height: 200 });
  });

  it('divides by zoom = 2 (halves all dimensions)', () => {
    const result = screenRectToPdf(
      { x: 20, y: 40, width: 200, height: 400 },
      2,
    );
    expect(result).toEqual({ x: 10, y: 20, width: 100, height: 200 });
  });

  it('handles fractional zoom (doubles for zoom 0.5)', () => {
    const result = screenRectToPdf(
      { x: 5, y: 10, width: 50, height: 100 },
      0.5,
    );
    expect(result).toEqual({ x: 10, y: 20, width: 100, height: 200 });
  });

  it('handles zero rect', () => {
    const result = screenRectToPdf({ x: 0, y: 0, width: 0, height: 0 }, 1);
    expect(result).toEqual({ x: 0, y: 0, width: 0, height: 0 });
  });
});

// ---------------------------------------------------------------------------
// pdfRectToScreen
// ---------------------------------------------------------------------------
describe('pdfRectToScreen', () => {
  it('multiplies all dimensions by zoom = 1 (identity)', () => {
    const result = pdfRectToScreen(
      { x: 10, y: 20, width: 100, height: 200 },
      1,
    );
    expect(result).toEqual({ x: 10, y: 20, width: 100, height: 200 });
  });

  it('multiplies by zoom = 2 (doubles all dimensions)', () => {
    const result = pdfRectToScreen(
      { x: 10, y: 20, width: 100, height: 200 },
      2,
    );
    expect(result).toEqual({ x: 20, y: 40, width: 200, height: 400 });
  });

  it('handles fractional zoom (halves for zoom 0.5)', () => {
    const result = pdfRectToScreen(
      { x: 10, y: 20, width: 100, height: 200 },
      0.5,
    );
    expect(result).toEqual({ x: 5, y: 10, width: 50, height: 100 });
  });

  it('round-trips through screenRectToPdf', () => {
    const original = { x: 12, y: 34, width: 56, height: 78 };
    const round = screenRectToPdf(pdfRectToScreen(original, 1.5), 1.5);
    expect(round).toEqual(original);
  });
});

// ---------------------------------------------------------------------------
// rectOverlapsBbox
// ---------------------------------------------------------------------------
describe('rectOverlapsBbox', () => {
  it('returns true when rect fully contains bbox', () => {
    const rect = { x: 0, y: 0, width: 100, height: 100 };
    const bbox = [10, 10, 50, 50];
    expect(rectOverlapsBbox(rect, bbox)).toBe(true);
  });

  it('returns true when bbox fully contains rect', () => {
    const rect = { x: 10, y: 10, width: 5, height: 5 };
    const bbox = [0, 0, 100, 100];
    expect(rectOverlapsBbox(rect, bbox)).toBe(true);
  });

  it('returns true when rects partially overlap', () => {
    const rect = { x: 5, y: 5, width: 10, height: 10 };
    const bbox = [10, 10, 20, 20];
    expect(rectOverlapsBbox(rect, bbox)).toBe(true);
  });

  it('returns false when rect is entirely to the right of bbox', () => {
    const rect = { x: 100, y: 0, width: 10, height: 10 };
    const bbox = [0, 0, 50, 50];
    expect(rectOverlapsBbox(rect, bbox)).toBe(false);
  });

  it('returns false when rect is entirely to the left of bbox', () => {
    const rect = { x: 0, y: 0, width: 5, height: 10 };
    const bbox = [10, 0, 20, 10];
    expect(rectOverlapsBbox(rect, bbox)).toBe(false);
  });

  it('returns false when rect is entirely below bbox', () => {
    const rect = { x: 0, y: 100, width: 10, height: 10 };
    const bbox = [0, 0, 50, 50];
    expect(rectOverlapsBbox(rect, bbox)).toBe(false);
  });

  it('returns false when rect is entirely above bbox', () => {
    const rect = { x: 0, y: 0, width: 10, height: 5 };
    const bbox = [0, 10, 10, 20];
    expect(rectOverlapsBbox(rect, bbox)).toBe(false);
  });

  it('returns true when rect touches bbox edge (inclusive overlap)', () => {
    const rect = { x: 0, y: 0, width: 10, height: 10 };
    const bbox = [10, 0, 20, 10];
    // Edge case — rect.x + rect.width = 10 == bbox.x0 = 10, not less than, so overlaps.
    expect(rectOverlapsBbox(rect, bbox)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// mergeBboxes
// ---------------------------------------------------------------------------
describe('mergeBboxes', () => {
  it('returns zero rect for empty array', () => {
    expect(mergeBboxes([])).toEqual({ x: 0, y: 0, width: 0, height: 0 });
  });

  it('returns the original bbox dimensions for a single bbox', () => {
    expect(mergeBboxes([[10, 20, 30, 40]])).toEqual({
      x: 10,
      y: 20,
      width: 20,
      height: 20,
    });
  });

  it('merges two non-overlapping bboxes into enclosing rect', () => {
    const result = mergeBboxes([
      [0, 0, 10, 10],
      [20, 20, 30, 30],
    ]);
    expect(result).toEqual({ x: 0, y: 0, width: 30, height: 30 });
  });

  it('merges three overlapping bboxes', () => {
    const result = mergeBboxes([
      [5, 5, 15, 15],
      [10, 10, 20, 20],
      [0, 8, 12, 18],
    ]);
    expect(result).toEqual({ x: 0, y: 5, width: 20, height: 15 });
  });

  it('handles bboxes with same min/max (degenerate point bboxes)', () => {
    const result = mergeBboxes([
      [5, 5, 5, 5],
      [5, 5, 5, 5],
    ]);
    expect(result).toEqual({ x: 5, y: 5, width: 0, height: 0 });
  });
});
