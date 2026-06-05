// frontend/src/components/viewer/LeftToolRail.tsx
import React, { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Tooltip from '@mui/material/Tooltip';
import MouseOutlined from '@mui/icons-material/MouseOutlined';
import RotateRight from '@mui/icons-material/RotateRight';
import CropSquare from '@mui/icons-material/CropSquare';
import Palette from '@mui/icons-material/Palette';
import FindReplace from '@mui/icons-material/FindReplace';
import TourOutlined from '@mui/icons-material/TourOutlined';
import './LeftToolRail.css';

interface Props {
  activeTool: string;
  onToolChange: (toolId: string) => void;
}

const LeftToolRail: React.FC<Props> = ({ activeTool, onToolChange }) => {
  const mainTools = [
    { id: 'select', icon: MouseOutlined, label: 'Select' },
    { id: 'draw-redaction', icon: CropSquare, label: 'Draw' },
    { id: 'find-replace', icon: FindReplace, label: 'Find & Redact' },
  ];

  const bottomTools = [
    { id: 'tour', icon: TourOutlined, label: 'Tour' },
  ];

  const renderTool = (tool: any) => {
    const Icon = tool.icon;
    const isActive = activeTool === tool.id;
    
    return (
      <Tooltip key={tool.id} title={tool.label} placement="right">
        <Button
          onClick={() => onToolChange(tool.id)}
          sx={{
            minWidth: '50px',
            width: '50px',
            flexDirection: 'column',
            py: 1,
            px: 0.5,
            color: isActive ? 'var(--color-primary)' : 'var(--text-secondary)',
            bgcolor: isActive ? '#e8f4ff' : 'transparent',
            borderRadius: '6px',
            '&:hover': {
              bgcolor: isActive ? '#e8f4ff' : 'var(--bg-tertiary)'
            }
          }}
        >
          <Icon sx={{ fontSize: 40, mb: 0.5 }} />
          <Typography 
            variant="caption" 
            sx={{ 
              fontSize: '9px', 
              textTransform: 'none',
              lineHeight: 1,
              color: isActive ? 'var(--color-primary)' : 'var(--text-secondary)'
            }}
          >
            {tool.label}
          </Typography>
        </Button>
      </Tooltip>
    );
  };

  return (
    <Box className="left-tool-rail" sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Box>
        {mainTools.map(renderTool)}
      </Box>
      <Box sx={{ marginTop: 'auto' }}>
        {bottomTools.map(renderTool)}
      </Box>
    </Box>
  );
};

export default LeftToolRail;
