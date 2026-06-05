// frontend/src/components/viewer/ManualRedactionTool.tsx
import React, { useState, useRef, useEffect } from 'react';
import { Box, Alert, IconButton, Tooltip } from '@mui/material';
import { Close } from '@mui/icons-material';
import {
  clientPointToPdf,
  pdfRectToScreen,
  rectOverlapsBbox,
  mergeBboxes,
} from './coordinates';
import './ManualRedactionTool.css';

interface Props {
  enabled: boolean;
  pageData: {
    width: number;
    height: number;
    words: Array<{
      text: string;
      bbox: number[];
      line_num: number;
      word_num: number;
    }>;
    lines: Array<{
      text: string;
      bbox: number[];
      line_num: number;
    }>;
  } | null;
  zoom: number;
  onRedactionCreated: (redaction: RedactionData) => void;
  onDisable: () => void;
}

export interface RedactionData {
  x: number;
  y: number;
  width: number;
  height: number;
  text: string;
  snappedWords: string[];
  page?: number; // Optional page number for batch redactions from search
}

type SnapMode = 'word' | 'line' | 'sentence' | 'paragraph';

interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

const ManualRedactionTool: React.FC<Props> = ({
  enabled,
  pageData,
  zoom,
  onRedactionCreated,
  onDisable
}) => {
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPos, setStartPos] = useState<{ x: number; y: number } | null>(null);
  const [currentPos, setCurrentPos] = useState<{ x: number; y: number } | null>(null);
  const [previewBounds, setPreviewBounds] = useState<Bounds | null>(null);
  const [snapMode, setSnapMode] = useState<SnapMode>('word');
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!enabled) {
      setIsDrawing(false);
      setStartPos(null);
      setCurrentPos(null);
      setPreviewBounds(null);
    }
  }, [enabled]);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (!enabled) return;

    const rect = overlayRef.current?.getBoundingClientRect();
    if (!rect) return;

    const { x, y } = clientPointToPdf(e.clientX, e.clientY, rect, zoom);

    setIsDrawing(true);
    setStartPos({ x, y });
    setCurrentPos({ x, y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDrawing || !startPos) return;

    const rect = overlayRef.current?.getBoundingClientRect();
    if (!rect) return;

    const { x, y } = clientPointToPdf(e.clientX, e.clientY, rect, zoom);

    setCurrentPos({ x, y });

    // Calculate current selection bounds
    const bounds = {
      x: Math.min(startPos.x, x),
      y: Math.min(startPos.y, y),
      width: Math.abs(x - startPos.x),
      height: Math.abs(y - startPos.y)
    };

    // Snap to words/lines based on mode if pageData is available
    const snapped = pageData ? snapToBounds(bounds, pageData, snapMode) : bounds;
    setPreviewBounds(snapped);
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (!isDrawing || !startPos || !currentPos) return;

    const rect = overlayRef.current?.getBoundingClientRect();
    if (!rect) return;

    const { x, y } = clientPointToPdf(e.clientX, e.clientY, rect, zoom);

    // Calculate final bounds
    const bounds = {
      x: Math.min(startPos.x, x),
      y: Math.min(startPos.y, y),
      width: Math.abs(x - startPos.x),
      height: Math.abs(y - startPos.y)
    };

    // Snap to words/lines if pageData is available
    const snapped = pageData ? snapToBounds(bounds, pageData, snapMode) : bounds;

    if (snapped.width > 0 && snapped.height > 0) {
      // Extract text from snapped bounds if pageData is available
      let text = '[Selected Text]';
      let overlappingWords: string[] = [];
      
      if (pageData) {
        const words = findOverlappingWords(snapped, pageData);
        text = words.map(w => w.text).join(' ');
        overlappingWords = words.map(w => w.text);
      }

      onRedactionCreated({
        x: snapped.x,
        y: snapped.y,
        width: snapped.width,
        height: snapped.height,
        text: text,
        snappedWords: overlappingWords
      });
    }

    // Reset
    setIsDrawing(false);
    setStartPos(null);
    setCurrentPos(null);
    setPreviewBounds(null);
  };

  const snapToBounds = (
    bounds: { x: number; y: number; width: number; height: number },
    pageData: any,
    mode: SnapMode
  ) => {
    const overlapping = findOverlappingWords(bounds, pageData);

    if (overlapping.length === 0) {
      return bounds;
    }

    if (mode === 'word') {
      // Snap to exact words
      return mergeBboxes(overlapping.map(w => w.bbox));
    }

    if (mode === 'line') {
      // Expand to include full lines
      const lineNums = new Set(overlapping.map(w => w.line_num));
      const lineWords = pageData.words.filter((w: any) => lineNums.has(w.line_num));
      return mergeBboxes(lineWords.map((w: any) => w.bbox));
    }

    // TODO(issue: TBD): Implement sentence and paragraph snapping
    return mergeBboxes(overlapping.map(w => w.bbox));
  };

  const findOverlappingWords = (
    bounds: { x: number; y: number; width: number; height: number },
    pageData: any
  ) => {
    return pageData.words.filter((word: any) => rectOverlapsBbox(bounds, word.bbox));
  };

  const getPreviewStyle = () => {
    if (!previewBounds) return {};

    const screenRect = pdfRectToScreen(previewBounds, zoom);
    return {
      position: 'absolute' as const,
      left: screenRect.x,
      top: screenRect.y,
      width: screenRect.width,
      height: screenRect.height,
      backgroundColor: 'rgba(59, 130, 246, 0.3)', // Light blue
      border: '2px solid #3b82f6',
      pointerEvents: 'none' as const
    };
  };

  if (!enabled) return null;

  return (
    <>
      {/* Banner */}
      <Alert
        severity="info"
        className="manual-redaction-banner"
        action={
          <IconButton
            aria-label="close"
            color="inherit"
            size="small"
            onClick={onDisable}
          >
            <Close fontSize="inherit" />
          </IconButton>
        }
      >
        Select tool active. Highlight text to create a redaction.
      </Alert>

      {/* Overlay for drawing */}
      <Box
        ref={overlayRef}
        className="manual-redaction-overlay"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        style={{
          cursor: 'crosshair',
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 10 // Lower z-index so tool rail buttons are clickable
        }}
      >
        {/* Preview box while drawing */}
        {isDrawing && previewBounds && (
          <Box style={getPreviewStyle()} />
        )}
      </Box>

      {/* Snap mode controls */}
      <Box className="snap-mode-controls">
        <Tooltip title="Snap to words">
          <button
            className={snapMode === 'word' ? 'active' : ''}
            onClick={() => setSnapMode('word')}
          >
            Word
          </button>
        </Tooltip>
        <Tooltip title="Snap to full lines">
          <button
            className={snapMode === 'line' ? 'active' : ''}
            onClick={() => setSnapMode('line')}
          >
            Line
          </button>
        </Tooltip>
      </Box>
    </>
  );
};

export default ManualRedactionTool;
