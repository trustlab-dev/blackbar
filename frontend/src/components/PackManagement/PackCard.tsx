import React from 'react';
import {
  Card,
  CardContent,
  CardActions,
  Typography,
  Button,
  Chip,
  Box,
  CircularProgress
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import InfoIcon from '@mui/icons-material/Info';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';

interface Pack {
  pack_id: string;
  name: string;
  version: string;
  description: string;
  jurisdiction: {
    country: string;
    region: string;
    legislation_short: string;
  };
  author: string;
  category_count: number;
  status_count: number;
  has_templates: boolean;
  has_ai_prompts: boolean;
  is_active: boolean;
}

interface PackCardProps {
  pack: Pack;
  onActivate: (packId: string) => void;
  onViewDetails: (pack: Pack) => void;
  activating: boolean;
}

const PackCard: React.FC<PackCardProps> = ({ pack, onActivate, onViewDetails, activating }) => {
  const getCountryFlag = (countryCode: string) => {
    const flags: { [key: string]: string } = {
      'CA': '🇨🇦',
      'US': '🇺🇸',
      'GB': '🇬🇧',
      'AU': '🇦🇺',
      'NZ': '🇳🇿'
    };
    return flags[countryCode] || '🌍';
  };

  return (
    <Card 
      className={`pack-card ${pack.is_active ? 'active' : ''}`}
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        border: pack.is_active ? '2px solid #1976d2' : '1px solid #e0e0e0',
        position: 'relative'
      }}
    >
      {pack.is_active && (
        <Chip
          icon={<CheckCircleIcon />}
          label="ACTIVE"
          color="primary"
          size="small"
          sx={{
            position: 'absolute',
            top: 8,
            right: 8,
            fontWeight: 'bold'
          }}
        />
      )}

      <CardContent sx={{ flexGrow: 1, pt: pack.is_active ? 5 : 2 }}>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          <Typography variant="h3" component="span">
            {getCountryFlag(pack.jurisdiction.country)}
          </Typography>
          <Box>
            <Typography variant="h6" component="div">
              {pack.name}
            </Typography>
            <Typography variant="caption" color="textSecondary">
              v{pack.version}
            </Typography>
          </Box>
        </Box>

        <Typography variant="body2" color="textSecondary" gutterBottom>
          {pack.jurisdiction.region}, {pack.jurisdiction.country}
        </Typography>

        <Typography variant="body2" sx={{ mb: 2, minHeight: '40px' }}>
          {pack.description}
        </Typography>

        <Box display="flex" flexWrap="wrap" gap={0.5} mb={1}>
          <Chip 
            label={pack.jurisdiction.legislation_short} 
            size="small" 
            variant="outlined"
            color="primary"
          />
          <Chip 
            label={`${pack.category_count} categories`} 
            size="small" 
            variant="outlined"
          />
          <Chip 
            label={`${pack.status_count} statuses`} 
            size="small" 
            variant="outlined"
          />
        </Box>

        <Box display="flex" gap={0.5}>
          {pack.has_templates && (
            <Chip label="Templates" size="small" color="success" />
          )}
          {pack.has_ai_prompts && (
            <Chip label="AI Ready" size="small" color="secondary" />
          )}
        </Box>

        <Typography variant="caption" color="textSecondary" display="block" mt={2}>
          By {pack.author}
        </Typography>
      </CardContent>

      <CardActions sx={{ justifyContent: 'space-between', px: 2, pb: 2 }}>
        <Button
          size="small"
          startIcon={<InfoIcon />}
          onClick={() => onViewDetails(pack)}
        >
          Details
        </Button>
        {!pack.is_active && (
          <Button
            size="small"
            variant="contained"
            startIcon={activating ? <CircularProgress size={16} /> : <PlayArrowIcon />}
            onClick={() => onActivate(pack.pack_id)}
            disabled={activating}
          >
            {activating ? 'Activating...' : 'Activate'}
          </Button>
        )}
        {pack.is_active && (
          <Chip label="In Use" color="primary" size="small" />
        )}
      </CardActions>
    </Card>
  );
};

export default PackCard;
