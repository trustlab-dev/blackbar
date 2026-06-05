// frontend/src/components/viewer/RightUtilityBar.tsx
import React from 'react';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Visibility from '@mui/icons-material/Visibility';
import VisibilityOff from '@mui/icons-material/VisibilityOff';
import AutoAwesome from '@mui/icons-material/AutoAwesome';
import History from '@mui/icons-material/History';
import Comment from '@mui/icons-material/Comment';
import './RightUtilityBar.css';

interface Props {
  documentId: string;
  showRedactionPreview: boolean;
  onTogglePreview: (value: boolean) => void;
  onAutoSuggestClick: () => void;
  onHistoryClick: () => void;
  onCommentsClick: () => void;
}

const RightUtilityBar: React.FC<Props> = ({ documentId, showRedactionPreview, onTogglePreview, onAutoSuggestClick, onHistoryClick, onCommentsClick }) => {

  return (
    <Box className="right-utility-bar">
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', mb: 2 }}>
        <IconButton
          size="medium"
          onClick={() => onTogglePreview(!showRedactionPreview)}
          sx={{
            color: showRedactionPreview ? 'var(--color-primary)' : 'var(--text-secondary)',
            mb: 0.5
          }}
        >
          {showRedactionPreview ? (
            <Visibility sx={{ fontSize: 40 }} />
          ) : (
            <VisibilityOff sx={{ fontSize: 40 }} />
          )}
        </IconButton>
        <Box sx={{ fontSize: '11px', color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '60px' }}>
          {showRedactionPreview ? 'Hide' : 'Show'}
        </Box>
      </Box>

      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', mb: 2 }}>
        <IconButton size="medium" onClick={onAutoSuggestClick} sx={{ color: 'var(--text-secondary)', mb: 0.5 }}>
          <AutoAwesome sx={{ fontSize: 40 }} />
        </IconButton>
        <Box sx={{ fontSize: '11px', color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '60px' }}>
          Auto Suggest
        </Box>
      </Box>

      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', mb: 2 }}>
        <IconButton size="medium" onClick={onHistoryClick} sx={{ color: 'var(--text-secondary)', mb: 0.5 }}>
          <History sx={{ fontSize: 40 }} />
        </IconButton>
        <Box sx={{ fontSize: '11px', color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '60px' }}>
          History
        </Box>
      </Box>

      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <IconButton size="medium" onClick={onCommentsClick} sx={{ color: 'var(--text-secondary)', mb: 0.5 }}>
          <Comment sx={{ fontSize: 40 }} />
        </IconButton>
        <Box sx={{ fontSize: '11px', color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '60px' }}>
          Comments
        </Box>
      </Box>
    </Box>
  );
};

export default RightUtilityBar;
