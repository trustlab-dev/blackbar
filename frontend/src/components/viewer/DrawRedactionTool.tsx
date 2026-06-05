// frontend/src/components/viewer/DrawRedactionTool.tsx
import React, { useState, useRef, useEffect } from 'react';
import { Box, Alert, IconButton, Tooltip } from '@mui/material';
import { Close } from '@mui/icons-material';
import { clientPointToPdf, pdfRectToScreen } from './coordinates';
import './DrawRedactionTool.css';

interface Props {
  enabled: boolean;
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
}

interface Rectangle {
  x: number;
  y: number;
  width: number;
  height: number;
}

const DrawRedactionTool: React.FC<Props> = ({
  enabled,
  zoom,
  onRedactionCreated,
  onDisable
}) => {
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPos, setStartPos] = useState<{ x: number; y: number } | null>(null);
  const [currentRect, setCurrentRect] = useState<Rectangle | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!enabled) {
      setIsDrawing(false);
      setStartPos(null);
      setCurrentRect(null);
    }
    
    // Add escape key handler to exit drawing mode
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && enabled) {
        onDisable();
      }
    };
    
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [enabled, onDisable]);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (!enabled) return;

    // Get the PDF canvas element position (not the overlay)
    const canvas = document.querySelector('.react-pdf__Page canvas') as HTMLElement;
    if (!canvas) return;
    
    const canvasRect = canvas.getBoundingClientRect();

    const { x, y } = clientPointToPdf(e.clientX, e.clientY, canvasRect, zoom);

    setIsDrawing(true);
    setStartPos({ x, y });
    setCurrentRect({ x, y, width: 0, height: 0 });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDrawing || !startPos) return;

    // Get the PDF canvas element position (not the overlay)
    const canvas = document.querySelector('.react-pdf__Page canvas') as HTMLElement;
    if (!canvas) return;

    const canvasRect = canvas.getBoundingClientRect();

    const { x, y } = clientPointToPdf(e.clientX, e.clientY, canvasRect, zoom);

    const width = x - startPos.x;
    const height = y - startPos.y;

    setCurrentRect({
      x: width >= 0 ? startPos.x : x,
      y: height >= 0 ? startPos.y : y,
      width: Math.abs(width),
      height: Math.abs(height)
    });
  };

  const handleMouseUp = () => {
    if (!isDrawing || !currentRect) return;

    // Only create redaction if rectangle has meaningful size
    if (currentRect.width > 5 && currentRect.height > 5) {
      onRedactionCreated({
        x: currentRect.x,
        y: currentRect.y,
        width: currentRect.width,
        height: currentRect.height,
        text: '[Drawn Redaction]',
        snappedWords: []
      });
    }

    setIsDrawing(false);
    setStartPos(null);
    setCurrentRect(null);
  };

  if (!enabled) return null;

  return (
    <>
      {/* Banner */}
      <Alert
        severity="info"
        sx={{
          position: 'absolute',
          top: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 1000,
          minWidth: '400px'
        }}
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
        Draw redaction enabled. Click and drag to draw rectangular redactions.
      </Alert>

      {/* Drawing Overlay - only covers PDF area, not tool rails */}
      <Box
        ref={overlayRef}
        className="draw-redaction-overlay"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        sx={{
          position: 'absolute',
          top: 0,
          left: '60px', // Leave space for left tool rail
          right: '60px', // Leave space for right utility bar
          bottom: 0,
          cursor: 'crosshair',
          zIndex: 10,
          pointerEvents: 'auto'
        }}
      >
        {/* Current drawing preview - positioned relative to canvas */}
        {currentRect && (() => {
          const canvas = document.querySelector('.react-pdf__Page canvas') as HTMLElement;
          if (!canvas) return null;
          
          const overlayRect = overlayRef.current?.getBoundingClientRect();
          const canvasRect = canvas.getBoundingClientRect();
          
          if (!overlayRect) return null;
          
          // Calculate offset from overlay to canvas
          const offsetX = canvasRect.left - overlayRect.left;
          const offsetY = canvasRect.top - overlayRect.top;
          const screenRect = pdfRectToScreen(currentRect, zoom);

          return (
            <Box
              sx={{
                position: 'absolute',
                left: `${offsetX + screenRect.x}px`,
                top: `${offsetY + screenRect.y}px`,
                width: `${screenRect.width}px`,
                height: `${screenRect.height}px`,
                border: '2px dashed #0078d4',
                backgroundColor: 'rgba(0, 120, 212, 0.1)',
                pointerEvents: 'none'
              }}
            />
          );
        })()}
      </Box>
    </>
  );
};

export default DrawRedactionTool;
