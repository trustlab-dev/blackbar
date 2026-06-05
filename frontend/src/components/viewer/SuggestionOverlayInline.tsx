import React, { useState } from 'react';
import { Box } from '@mui/material';
import { pdfRectToScreen } from './coordinates';

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
  suggestion: Suggestion;
  zoom: number;
  onAccept: (suggestion: Suggestion) => void;
  onReject: (suggestion: Suggestion) => void;
}

const SuggestionOverlayInline: React.FC<Props> = ({ suggestion, zoom, onAccept, onReject }) => {
  const [showActions, setShowActions] = useState(false);
  
  if (!suggestion.coordinates) {
    return null;
  }
  
  const getConfidenceColor = (confidence: string) => {
    switch (confidence?.toLowerCase()) {
      case 'high': return '#4caf50';
      case 'medium': return '#ff9800';
      case 'low': return '#9e9e9e';
      default: return '#9e9e9e';
    }
  };
  
  const screenRect = pdfRectToScreen(suggestion.coordinates, zoom);

  return (
    <Box
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
      sx={{
        position: 'absolute',
        left: `${screenRect.x}px`,
        top: `${screenRect.y}px`,
        width: `${screenRect.width}px`,
        height: `${screenRect.height}px`,
        border: '2px dashed #2196F3',
        backgroundColor: 'rgba(33, 150, 243, 0.1)',
        cursor: 'pointer',
        transition: 'all 0.2s',
        '&:hover': {
          backgroundColor: 'rgba(33, 150, 243, 0.2)',
          borderColor: '#1976D2',
        },
        zIndex: 10,
      }}
    >
      {/* Confidence Badge */}
      <Box
        component="span"
        sx={{
          position: 'absolute',
          top: -12,
          right: 0,
          fontSize: '10px',
          height: 18,
          px: 0.5,
          borderRadius: '4px',
          backgroundColor: getConfidenceColor(suggestion.confidence),
          color: 'white',
          display: 'inline-block',
        }}
      >
        {suggestion.confidence || 'medium'}
      </Box>
      
      {/* Quick Actions on Hover */}
      {showActions && (
        <Box
          sx={{
            position: 'absolute',
            bottom: -40,
            left: 0,
            display: 'flex',
            gap: 1,
            backgroundColor: 'white',
            padding: '4px',
            borderRadius: '4px',
            boxShadow: 2,
          }}
        >
          <button
            onClick={() => onAccept(suggestion)}
            style={{
              padding: '4px 8px',
              fontSize: '11px',
              backgroundColor: '#4caf50',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            ✓ Accept
          </button>
          <button
            onClick={() => onReject(suggestion)}
            style={{
              padding: '4px 8px',
              fontSize: '11px',
              backgroundColor: 'white',
              color: '#f44336',
              border: '1px solid #f44336',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            ✗ Reject
          </button>
        </Box>
      )}
    </Box>
  );
};

export default SuggestionOverlayInline;
