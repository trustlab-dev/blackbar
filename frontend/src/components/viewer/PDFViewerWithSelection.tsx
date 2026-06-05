// frontend/src/components/viewer/PDFViewerWithSelection.tsx
import React, { useState, useEffect, useRef } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { Box, CircularProgress } from '@mui/material';
import api from '../../api/client';
import SuggestionOverlayInline from './SuggestionOverlayInline';
import {
  screenRectToPdf,
  pdfRectToScreen,
  rectOverlapsBbox,
  mergeBboxes,
} from './coordinates';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import './PDFViewerWithSelection.css';

// Type assertion for react-pdf v10 compatibility
const DocumentComponent = Document as any;
const PageComponent = Page as any;

// Set PDF.js worker - use local worker from node_modules
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface Redaction {
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  text: string;
  reason?: any;
  color?: string;
}

interface Suggestion {
  text: string;
  category: string;
  section: string;
  reason: string;
  confidence: string;
  page: number;
  coordinates?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}

interface Props {
  documentId: string;
  currentPage: number;
  zoom: number;
  onNumPagesChange: (numPages: number) => void;
  pdfUrl?: string | null;
  redactions?: Redaction[];
  suggestions?: Suggestion[];
  onSuggestionAccept?: (suggestion: Suggestion) => void;
  onSuggestionReject?: (suggestion: Suggestion) => void;
  onTextSelected?: (redactionData: { x: number; y: number; width: number; height: number; text: string; snappedWords: string[] }[]) => void;
  onRedactionClick?: (index: number, event: React.MouseEvent) => void;
  /** Called when the operator drag-resizes a redaction box. Coordinates are
   *  in PDF page space. Parent should persist via the redaction-edit API.
   *  Receives the redaction's stable id so the parent can locate it in the
   *  full (unfiltered) state. */
  onRedactionResize?: (redactionId: string, rect: { x: number; y: number; width: number; height: number }) => void;
  selectedRedactionIndex?: number | null;
  highlightedMatchBbox?: number[] | null;
  showRedactionPreview?: boolean;
}

type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w';

const HANDLE_CURSORS: Record<ResizeHandle, string> = {
  nw: 'nwse-resize', se: 'nwse-resize',
  ne: 'nesw-resize', sw: 'nesw-resize',
  n: 'ns-resize',   s: 'ns-resize',
  e: 'ew-resize',   w: 'ew-resize',
};

const HANDLE_POSITIONS: Record<ResizeHandle, { left: string; top: string }> = {
  nw: { left: '-4px',  top: '-4px'  },
  n:  { left: '50%',   top: '-4px'  },
  ne: { left: '100%',  top: '-4px'  },
  e:  { left: '100%',  top: '50%'   },
  se: { left: '100%',  top: '100%'  },
  s:  { left: '50%',   top: '100%'  },
  sw: { left: '-4px',  top: '100%'  },
  w:  { left: '-4px',  top: '50%'   },
};

interface SelectionData {
  text: string;
  page: number;
  rects: DOMRect[];
  pdfCoords?: { x: number; y: number; width: number; height: number };
}

interface PageOCRData {
  page_num: number;
  text: string;
  width: number;
  height: number;
  words: Array<{
    text: string;
    bbox: number[];
    confidence: number;
    line_num: number;
    word_num: number;
  }>;
  lines: Array<{
    text: string;
    bbox: number[];
    line_num: number;
  }>;
}

const PDFViewerWithSelection: React.FC<Props> = ({
  documentId,
  currentPage,
  zoom,
  onNumPagesChange,
  pdfUrl: externalPdfUrl,
  redactions = [],
  suggestions = [],
  onSuggestionAccept,
  onSuggestionReject,
  onTextSelected,
  onRedactionClick,
  onRedactionResize,
  selectedRedactionIndex,
  highlightedMatchBbox,
  showRedactionPreview = true
}) => {
  const [pdfUrl, setPdfUrl] = useState<string | null>(externalPdfUrl || null);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedText, setSelectedText] = useState<SelectionData | null>(null);
  const [ocrData, setOcrData] = useState<PageOCRData[]>([]);
  const pageRef = useRef<HTMLDivElement>(null);

  // Active resize/move op. `mode='resize'` uses `handle` to know which
  // edge(s) follow the cursor; `mode='move'` translates the whole rect.
  // The override rect is what the box renders as during the drag, so
  // feedback is instant and we only push to the parent on mouse-up.
  const [dragState, setDragState] = useState<{
    index: number;
    id: string;
    mode: 'resize' | 'move';
    handle?: ResizeHandle;
    startClient: { x: number; y: number };
    startRect: { x: number; y: number; width: number; height: number };
    hasMoved: boolean;
  } | null>(null);
  const [dragOverride, setDragOverride] = useState<
    { x: number; y: number; width: number; height: number } | null
  >(null);
  // Set to true on mouse-up after a real drag/resize so the synthesised
  // click event that follows can be ignored (otherwise the menu would
  // re-open at the release point).
  const suppressNextClickRef = useRef(false);

  useEffect(() => {
    if (!dragState) return;

    const MIN = 4;            // PDF units — minimum size / detect movement
    const MOVE_THRESHOLD = 2; // PDF units delta before counting as a drag

    const handleMove = (e: MouseEvent) => {
      const dx = (e.clientX - dragState.startClient.x) / zoom;
      const dy = (e.clientY - dragState.startClient.y) / zoom;

      if (!dragState.hasMoved && Math.hypot(dx, dy) > MOVE_THRESHOLD) {
        setDragState({ ...dragState, hasMoved: true });
      }

      let r = { ...dragState.startRect };
      if (dragState.mode === 'resize' && dragState.handle) {
        if (dragState.handle.includes('n')) { r.y += dy; r.height -= dy; }
        if (dragState.handle.includes('s')) { r.height += dy; }
        if (dragState.handle.includes('w')) { r.x += dx; r.width -= dx; }
        if (dragState.handle.includes('e')) { r.width += dx; }
        if (r.width < MIN)  { r.x = dragState.startRect.x + dragState.startRect.width - MIN; r.width = MIN; }
        if (r.height < MIN) { r.y = dragState.startRect.y + dragState.startRect.height - MIN; r.height = MIN; }
      } else {
        // 'move': translate, leave dimensions alone.
        r.x += dx;
        r.y += dy;
      }
      setDragOverride(r);
    };

    const handleUp = () => {
      if (dragState.hasMoved && dragOverride && onRedactionResize) {
        onRedactionResize(dragState.id, dragOverride);
        // Eat the upcoming synthesised click so the box's onClick (which
        // opens the menu) doesn't fire after a successful move/resize.
        suppressNextClickRef.current = true;
      }
      setDragState(null);
      setDragOverride(null);
    };

    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    return () => {
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };
  }, [dragState, dragOverride, zoom, onRedactionResize]);

  // TODO: Text highlighting feature - currently too complex with PDF.js text layer
  // Will implement when we have proper search API with text positions

  useEffect(() => {
    if (externalPdfUrl) {
      setPdfUrl(externalPdfUrl);
      setLoading(false);
    } else {
      fetchPDF();
    }
    fetchOCRData();
  }, [documentId, externalPdfUrl]);

  const fetchPDF = async () => {
    if (externalPdfUrl) return; // Don't fetch if URL provided
    
    try {
      setLoading(true);
      const response = await api.get(`/documents/${documentId}`, {
        responseType: 'blob'
      });
      const url = URL.createObjectURL(response.data);
      setPdfUrl(url);
    } catch (error) {
      console.error('Error fetching PDF:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchOCRData = async () => {
    try {
      const response = await api.get(`/documents/${documentId}/metadata`);
      if (response.data.text_data?.pages) {
        setOcrData(response.data.text_data.pages);
      }
    } catch (error) {
      console.error('Error fetching OCR data:', error);
    }
  };

  const handleDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    onNumPagesChange(numPages);
  };

  const handleTextSelection = () => {
    const selection = window.getSelection();
    if (!selection || selection.toString().trim().length === 0) {
      setSelectedText(null);
      return;
    }

    const range = selection.getRangeAt(0);
    const rects = Array.from(range.getClientRects());

    // Get the PDF canvas element position (not the container)
    const canvas = document.querySelector('.react-pdf__Page canvas') as HTMLElement;
    if (!canvas) return;
    
    const canvasRect = canvas.getBoundingClientRect();
    
    // Filter out ghost/phantom rectangles (width or height near 0)
    const validRects = rects.filter(rect => rect.width > 2 && rect.height > 2);
    
    if (validRects.length === 0) return;
    
    // Map selection to PDF coordinates (for display purposes)
    const pdfCoords = mapSelectionToPDFCoords(validRects, canvasRect);

    const selectedTextData = {
      text: selection.toString(),
      page: currentPage,
      rects: rects as DOMRect[],
      pdfCoords
    };
    
    setSelectedText(selectedTextData);

    console.log('Selected text:', selection.toString());
    console.log('PDF coordinates:', pdfCoords);

    // Trigger redaction creation callback - pass all rectangles at once
    if (onTextSelected) {
      const redactionData = validRects.map((rect) => {
        const pdfRect = screenRectToPdf(
          {
            x: rect.left - canvasRect.left,
            y: rect.top - canvasRect.top,
            width: rect.width,
            height: rect.height,
          },
          zoom,
        );

        return {
          ...pdfRect,
          text: selection.toString(),
          snappedWords: [],
        };
      });

      onTextSelected(redactionData);

      // Clear selection after triggering
      selection.removeAllRanges();
    }
  };

  const mapSelectionToPDFCoords = (
    rects: ClientRect[],
    canvasRect: DOMRect
  ): { x: number; y: number; width: number; height: number } | undefined => {
    if (rects.length === 0) {
      console.warn('No rects provided for coordinate mapping');
      return undefined;
    }

    console.log('Canvas rect:', canvasRect);
    console.log('Valid rects (before dedup):', rects.length);
    console.log('Zoom:', zoom);

    // Deduplicate very similar rectangles (within 2px tolerance)
    const uniqueRects: ClientRect[] = [];
    const tolerance = 2;

    for (const rect of rects) {
      const isDuplicate = uniqueRects.some(existing =>
        Math.abs(existing.left - rect.left) < tolerance &&
        Math.abs(existing.top - rect.top) < tolerance &&
        Math.abs(existing.width - rect.width) < tolerance &&
        Math.abs(existing.height - rect.height) < tolerance
      );

      if (!isDuplicate) {
        uniqueRects.push(rect);
      }
    }

    console.log('Valid rects (after dedup):', uniqueRects.length);

    // Find bounding box of all unique rects (relative to PDF canvas)
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

    uniqueRects.forEach((rect, idx) => {
      const x = rect.left - canvasRect.left;
      const y = rect.top - canvasRect.top;
      console.log(`Rect ${idx}:`, {
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
        relativeX: x,
        relativeY: y
      });
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x + rect.width);
      maxY = Math.max(maxY, y + rect.height);
    });

    console.log('Bounding box (before zoom):', { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY });

    // Check if we got valid coordinates
    if (!isFinite(minX) || !isFinite(minY) || !isFinite(maxX) || !isFinite(maxY)) {
      console.warn('Invalid coordinates calculated from rects');
      return undefined;
    }

    // Convert to PDF coordinates (accounting for zoom)
    const coords = screenRectToPdf(
      { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
      zoom,
    );

    console.log('Final PDF coords (after zoom division):', coords);

    return coords;
  };

  const snapSelectionToWords = (coords: { x: number; y: number; width: number; height: number }, page: number) => {
    const pageData = ocrData.find(p => p.page_num === page);
    if (!pageData) return coords;

    const overlappingWords = pageData.words.filter(word => rectOverlapsBbox(coords, word.bbox));
    if (overlappingWords.length === 0) return coords;

    return mergeBboxes(overlappingWords.map(w => w.bbox));
  };

  if (loading) {
    return (
      <Box className="pdf-viewer-loading">
        <CircularProgress />
      </Box>
    );
  }

  if (!pdfUrl) {
    return <Box className="pdf-viewer-error">Failed to load PDF</Box>;
  }

  return (
    <Box
      className="pdf-viewer-with-selection"
      onMouseUp={handleTextSelection}
    >
      <Box
        ref={pageRef}
        sx={{ position: 'relative', display: 'inline-block' }}
      >
        <DocumentComponent
          key={pdfUrl}
          file={pdfUrl}
          onLoadSuccess={handleDocumentLoadSuccess}
          onLoadError={(error: any) => {
            console.error('PDF load error:', error);
            setLoading(false);
          }}
          loading={<CircularProgress />}
          error={<Box className="pdf-viewer-error">Failed to load PDF file.</Box>}
        >
          <PageComponent
            key={`page-${currentPage}`}
            pageNumber={currentPage}
            scale={zoom}
            renderTextLayer={true}
            renderAnnotationLayer={false}
            error={<Box p={2}>Failed to load page {currentPage}</Box>}
          />
        </DocumentComponent>

        {/* Redaction overlays - positioned relative to page */}
        {redactions.map((redaction, idx) => {
          const isSelected = selectedRedactionIndex === idx;
          
          // When preview is off, show black (final redaction appearance)
          // When preview is on, show colored overlays (blue for manual, green for AI)
          const getBackgroundColor = () => {
            if (!showRedactionPreview) {
              return 'rgba(0, 0, 0, 1)'; // Solid black for final preview
            }
            return redaction.color === 'green' ? 'rgba(34, 197, 94, 0.5)' : 'rgba(59, 130, 246, 0.5)';
          };
          
          const getHoverColor = () => {
            if (!showRedactionPreview) {
              return 'rgba(0, 0, 0, 1)'; // Stay black on hover
            }
            return redaction.color === 'green' ? 'rgba(34, 197, 94, 0.7)' : 'rgba(59, 130, 246, 0.7)';
          };
          
          // Use the live override rect while this redaction is being
          // resized / moved so the box visually tracks the cursor; on
          // mouse-up the parent persists and the override is cleared.
          const livePdfRect =
            (dragState && dragState.index === idx && dragOverride)
              ? dragOverride
              : redaction;
          const screenRect = pdfRectToScreen(livePdfRect, zoom);
          const draggable = isSelected && !!onRedactionResize && !!redaction.id;
          return (
            <Box
              key={idx}
              className="redaction-overlay"
              onMouseDown={(e) => {
                // Only the selected box is draggable. Mouse-down on a
                // handle stops propagation before reaching here, so
                // hitting a handle starts a resize and never a move.
                if (!draggable) return;
                if (e.button !== 0) return;
                e.stopPropagation();
                e.preventDefault();
                setDragState({
                  index: idx,
                  id: redaction.id!,
                  mode: 'move',
                  startClient: { x: e.clientX, y: e.clientY },
                  startRect: { x: redaction.x, y: redaction.y, width: redaction.width, height: redaction.height },
                  hasMoved: false,
                });
                setDragOverride({ x: redaction.x, y: redaction.y, width: redaction.width, height: redaction.height });
              }}
              onClick={(e) => {
                // Suppress the synthesised click that fires after a real
                // drag/resize (otherwise the menu would re-open at the
                // release point).
                if (suppressNextClickRef.current) {
                  suppressNextClickRef.current = false;
                  e.stopPropagation();
                  return;
                }
                onRedactionClick?.(idx, e);
              }}
              sx={{
                position: 'absolute',
                left: `${screenRect.x}px`,
                top: `${screenRect.y}px`,
                width: `${screenRect.width}px`,
                height: `${screenRect.height}px`,
                backgroundColor: getBackgroundColor(),
                border: isSelected ? '2px solid #2563eb' : (showRedactionPreview ? '1px solid #3b82f6' : 'none'),
                boxShadow: isSelected ? '0 0 0 2px rgba(37, 99, 235, 0.3)' : 'none',
                cursor: draggable ? 'move' : 'pointer',
                pointerEvents: 'auto',
                zIndex: isSelected ? 20 : 10,
                '&:hover': {
                  backgroundColor: getHoverColor(),
                }
              }}
            >
              {/* Resize handles — only rendered on the selected redaction.
                  Outer wrapper is 18×18 transparent so the hit target is
                  big enough to grab on small phone-number-sized boxes;
                  the visible 10×10 white square is centered inside via
                  a ::before pseudo-element. */}
              {isSelected && onRedactionResize && (Object.keys(HANDLE_CURSORS) as ResizeHandle[]).map((h) => (
                <Box
                  key={h}
                  onMouseDown={(e) => {
                    if (!redaction.id) return;
                    e.stopPropagation();
                    e.preventDefault();
                    setDragState({
                      index: idx,
                      id: redaction.id,
                      mode: 'resize',
                      handle: h,
                      startClient: { x: e.clientX, y: e.clientY },
                      startRect: { x: redaction.x, y: redaction.y, width: redaction.width, height: redaction.height },
                      hasMoved: false,
                    });
                    setDragOverride({ x: redaction.x, y: redaction.y, width: redaction.width, height: redaction.height });
                  }}
                  onClick={(e) => {
                    // Stop the synthesised click from bubbling to the box,
                    // otherwise mouse-up after resize re-opens the menu.
                    e.stopPropagation();
                  }}
                  sx={{
                    position: 'absolute',
                    width: '18px',
                    height: '18px',
                    cursor: HANDLE_CURSORS[h],
                    pointerEvents: 'auto',
                    zIndex: 30,
                    transform: 'translate(-50%, -50%)',
                    left: HANDLE_POSITIONS[h].left,
                    top: HANDLE_POSITIONS[h].top,
                    // Visible white square in the centre; the outer 18×18 is
                    // the click target.
                    '&::before': {
                      content: '""',
                      position: 'absolute',
                      top: '50%',
                      left: '50%',
                      width: '10px',
                      height: '10px',
                      transform: 'translate(-50%, -50%)',
                      backgroundColor: '#ffffff',
                      border: '1.5px solid #2563eb',
                      borderRadius: '2px',
                      pointerEvents: 'none',
                    },
                  }}
                />
              ))}
            </Box>
          );
        })}

        {/* Suggestion overlays - dashed blue boxes */}
        {suggestions.map((suggestion, idx) => (
          <SuggestionOverlayInline
            key={`suggestion-${idx}`}
            suggestion={suggestion}
            zoom={zoom}
            onAccept={onSuggestionAccept || (() => {})}
            onReject={onSuggestionReject || (() => {})}
          />
        ))}
      </Box>

      {/* Selection indicator overlay */}
      {selectedText && (
        <Box className="selection-indicator">
          Selected: "{selectedText.text.substring(0, 50)}{selectedText.text.length > 50 ? '...' : ''}"
        </Box>
      )}
    </Box>
  );
};

export default PDFViewerWithSelection;
