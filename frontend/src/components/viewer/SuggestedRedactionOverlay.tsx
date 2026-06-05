import React, { useState } from 'react';
import { Box, Button, Chip } from '@mui/material';
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
  bbox?: number[];
  has_coordinates?: boolean;
}

interface SuggestedRedactionOverlayProps {
  suggestion: Suggestion;
  scale: number;
  onAccept: (suggestion: Suggestion) => void;
  onReject: (suggestion: Suggestion) => void;
}

const getConfidenceColor = (confidence: string): 'success' | 'warning' | 'default' => {
  switch (confidence?.toLowerCase()) {
    case 'high': return 'success';
    case 'medium': return 'warning';
    case 'low': return 'default';
    default: return 'default';
  }
};

const SuggestedRedactionOverlay: React.FC<SuggestedRedactionOverlayProps> = ({
  suggestion,
  scale,
  onAccept,
  onReject
}) => {
  const [showActions, setShowActions] = useState(false);
  
  // Don't render if no coordinates
  if (!suggestion.coordinates) return null;

  const screenRect = pdfRectToScreen(suggestion.coordinates, scale);

  const handleAccept = () => {
    onAccept(suggestion);
  };

  const handleReject = () => {
    onReject(suggestion);
  };

  return (
    <Box
      sx={{
        position: 'absolute',
        left: screenRect.x,
        top: screenRect.y,
        width: screenRect.width,
        height: screenRect.height,
        border: '2px dashed #2196F3',
        backgroundColor: 'rgba(33, 150, 243, 0.1)',
        cursor: 'pointer',
        transition: 'all 0.2s',
        '&:hover': {
          backgroundColor: 'rgba(33, 150, 243, 0.2)',
          borderColor: '#1976D2',
        },
        zIndex: 10, // Below accepted redactions (which are 20)
      }}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      {/* Confidence Badge */}
      <Chip
        label={suggestion.confidence || 'medium'}
        size="small"
        color={getConfidenceColor(suggestion.confidence)}
        sx={{
          position: 'absolute',
          top: -12,
          right: 0,
          fontSize: '10px',
          height: 18,
        }}
      />
      
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
          <Button
            size="small"
            variant="contained"
            color="success"
            onClick={handleAccept}
            sx={{ textTransform: 'none', fontSize: '11px', py: 0.5, px: 1 }}
          >
            ✓ Accept
          </Button>
          <Button
            size="small"
            variant="outlined"
            color="error"
            onClick={handleReject}
            sx={{ textTransform: 'none', fontSize: '11px', py: 0.5, px: 1 }}
          >
            ✗ Reject
          </Button>
        </Box>
      )}
    </Box>
  );
};

export default SuggestedRedactionOverlay;
