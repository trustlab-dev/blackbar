// frontend/src/components/viewer/FindReplaceDrawer.tsx
import React, { useState, useEffect } from 'react';
import Drawer from '@mui/material/Drawer';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Alert from '@mui/material/Alert';
import Checkbox from '@mui/material/Checkbox';
import FormControlLabel from '@mui/material/FormControlLabel';
import Collapse from '@mui/material/Collapse';
import Close from '@mui/icons-material/Close';
import Search from '@mui/icons-material/Search';
import ChevronRight from '@mui/icons-material/ChevronRight';
import ExpandMore from '@mui/icons-material/ExpandMore';
import ExpandLess from '@mui/icons-material/ExpandLess';
import api from '../../api/client';
import './FindReplaceDrawer.css';

interface Props {
  open: boolean;
  onClose: () => void;
  documentId: string;
  onRedactMatches: (matches: SearchMatch[], reason: string) => void;
  onNavigateToMatch?: (page: number, bbox: number[]) => void;
}

interface SearchMatch {
  page: number;
  text: string;
  bbox: number[];
  context: string;
}

interface GroupedMatches {
  [page: number]: SearchMatch[];
}

const FindReplaceDrawer: React.FC<Props> = ({
  open,
  onClose,
  documentId,
  onRedactMatches,
  onNavigateToMatch
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [wholeWord, setWholeWord] = useState(false);
  const [useRegex, setUseRegex] = useState(false);
  const [useBracketSyntax, setUseBracketSyntax] = useState(false);
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const [groupedMatches, setGroupedMatches] = useState<GroupedMatches>({});
  const [selectedMatches, setSelectedMatches] = useState<Set<number>>(new Set());
  const [expandedPages, setExpandedPages] = useState<Set<number>>(new Set());
  const [searching, setSearching] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>('');

  useEffect(() => {
    if (open) {
      // Reset state when drawer opens
      setMatches([]);
      setGroupedMatches({});
      setSelectedMatches(new Set());
      setExpandedPages(new Set());
    }
  }, [open]);

  // Real-time search as user types
  useEffect(() => {
    if (searchTerm.trim()) {
      const debounceTimer = setTimeout(() => {
        handleSearch();
      }, 300); // 300ms debounce
      
      return () => clearTimeout(debounceTimer);
    } else {
      // Clear results when search is empty
      setMatches([]);
      setGroupedMatches({});
      setSelectedMatches(new Set());
    }
  }, [searchTerm, caseSensitive, wholeWord]);

  const handleSearch = async () => {
    if (!searchTerm.trim()) return;

    setSearching(true);
    try {
      // Call backend search API
      const response = await api.post(`/documents/${documentId}/search`, {
        query: searchTerm,
        case_sensitive: caseSensitive,
        whole_word: wholeWord
      });
      
      const matches = response.data.matches || [];
      setMatches(matches);

      // Group by page
      const grouped: GroupedMatches = {};
      matches.forEach((match, index) => {
        if (!grouped[match.page]) {
          grouped[match.page] = [];
        }
        grouped[match.page].push(match);
      });
      setGroupedMatches(grouped);

      // Select all by default
      setSelectedMatches(new Set(matches.map((_, i) => i)));

      // Expand all pages
      setExpandedPages(new Set(Object.keys(grouped).map(Number)));
    } catch (error: any) {
      console.error('Search error:', error);
      // Clear results on error
      setMatches([]);
      setGroupedMatches({});
      
      // Show error message
      if (error.response?.status === 400) {
        setErrorMessage(error.response?.data?.detail || 'This document does not have OCR data.');
      } else if (error.response?.status === 403) {
        setErrorMessage('You do not have permission to search this document.');
      } else {
        setErrorMessage('An error occurred while searching. Please try again.');
      }
    } finally {
      setSearching(false);
    }
  };

  const handleTogglePage = (page: number) => {
    const newExpanded = new Set(expandedPages);
    if (newExpanded.has(page)) {
      newExpanded.delete(page);
    } else {
      newExpanded.add(page);
    }
    setExpandedPages(newExpanded);
  };

  const handleToggleMatch = (index: number) => {
    const newSelected = new Set(selectedMatches);
    if (newSelected.has(index)) {
      newSelected.delete(index);
    } else {
      newSelected.add(index);
    }
    setSelectedMatches(newSelected);
  };

  const handleSelectAllOnPage = (page: number) => {
    const pageMatches = groupedMatches[page] || [];
    const pageIndices = matches
      .map((m, i) => (m.page === page ? i : -1))
      .filter(i => i !== -1);

    const allSelected = pageIndices.every(i => selectedMatches.has(i));
    const newSelected = new Set(selectedMatches);

    if (allSelected) {
      pageIndices.forEach(i => newSelected.delete(i));
    } else {
      pageIndices.forEach(i => newSelected.add(i));
    }

    setSelectedMatches(newSelected);
  };

  const handleRedactSelected = () => {
    const selectedMatchesList = matches.filter((_, i) => selectedMatches.has(i));
    if (selectedMatchesList.length === 0) return;

    // Open reason picker with selected matches
    onRedactMatches(selectedMatchesList, searchTerm);
    onClose();
  };

  const handleKeyPress = (e: any) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  return (
    <Box sx={{ 
      height: '100%', 
      display: 'flex', 
      flexDirection: 'column',
      bgcolor: 'white',
      p: 2
    }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6">Find & Redact</Typography>
        <IconButton onClick={onClose} size="small">
          <Close />
        </IconButton>
      </Box>

      <Divider sx={{ mb: 2 }} />

      {/* Search Input */}
      <TextField
        fullWidth
        label="Search term"
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        onKeyPress={handleKeyPress}
        placeholder="Enter text to find"
        sx={{ mb: 2 }}
        InputProps={{
          endAdornment: (
            <IconButton onClick={handleSearch} disabled={searching}>
              <Search />
            </IconButton>
          )
        }}
      />

      {/* Search Options */}
      <Box sx={{ mb: 2 }}>
        <FormControlLabel
          control={
            <Checkbox
              checked={caseSensitive}
              onChange={(e) => setCaseSensitive(e.target.checked)}
              size="small"
            />
          }
          label="Case sensitive"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={wholeWord}
              onChange={(e) => setWholeWord(e.target.checked)}
              size="small"
            />
          }
          label="Whole word"
        />
      </Box>

      <Divider sx={{ mb: 2 }} />

      {/* Results Summary */}
      {matches.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Found {matches.length} match{matches.length !== 1 ? 'es' : ''} across{' '}
            {Object.keys(groupedMatches).length} page{Object.keys(groupedMatches).length !== 1 ? 's' : ''}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {selectedMatches.size} selected
          </Typography>
        </Box>
      )}

      {/* Results List */}
      {matches.length > 0 && (
        <Box sx={{ flexGrow: 1, overflow: 'auto', mb: 2, maxHeight: 'calc(100vh - 450px)' }}>
          {Object.entries(groupedMatches)
            .sort(([a], [b]) => Number(a) - Number(b))
            .map(([page, pageMatches]) => {
              const pageNum = Number(page);
              const isExpanded = expandedPages.has(pageNum);
              const pageIndices = matches
                .map((m, i) => (m.page === pageNum ? i : -1))
                .filter(i => i !== -1);
              const allSelected = pageIndices.every(i => selectedMatches.has(i));

              return (
                <Box key={page} sx={{ mb: 1 }}>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      p: 1,
                      bgcolor: 'var(--bg-tertiary)',
                      borderRadius: 1,
                      cursor: 'pointer'
                    }}
                  >
                    <Checkbox
                      checked={allSelected}
                      onChange={() => handleSelectAllOnPage(pageNum)}
                      size="small"
                      onClick={(e) => e.stopPropagation()}
                    />
                    <Box
                      sx={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}
                      onClick={() => handleTogglePage(pageNum)}
                    >
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        Page {page}
                      </Typography>
                      <Chip
                        label={pageMatches.length}
                        size="small"
                        sx={{ ml: 1, height: 20 }}
                      />
                    </Box>
                    <IconButton size="small" onClick={() => handleTogglePage(pageNum)}>
                      {isExpanded ? <ExpandLess /> : <ChevronRight />}
                    </IconButton>
                  </Box>

                  <Collapse in={isExpanded}>
                    <List dense sx={{ pl: 2 }}>
                      {pageMatches.map((match, idx) => {
                        const globalIndex = matches.findIndex(
                          m => m.page === match.page && m.bbox === match.bbox
                        );
                        return (
                          <ListItem
                            key={idx}
                            sx={{
                              pl: 1,
                              cursor: 'pointer',
                              '&:hover': { bgcolor: '#fff8dc' }
                            }}
                            onClick={() => onNavigateToMatch?.(match.page, match.bbox)}
                          >
                            <Checkbox
                              checked={selectedMatches.has(globalIndex)}
                              onChange={() => handleToggleMatch(globalIndex)}
                              size="small"
                              onClick={(e) => e.stopPropagation()}
                            />
                            <ListItemText
                              primary={match.text}
                              secondary={match.context}
                              primaryTypographyProps={{ variant: 'body2' }}
                              secondaryTypographyProps={{
                                variant: 'caption',
                                sx: {
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  display: '-webkit-box',
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: 'vertical'
                                }
                              }}
                            />
                          </ListItem>
                        );
                      })}
                    </List>
                  </Collapse>
                </Box>
              );
            })}
        </Box>
      )}

      {/* Action Buttons - Fixed to bottom */}
      <Box 
        sx={{ 
          position: 'sticky',
          bottom: 0,
          bgcolor: 'white',
          borderTop: matches.length > 0 ? '1px solid var(--border-default)' : 'none',
          pt: matches.length > 0 ? 2 : 0,
          pb: 2,
          mt: 'auto',
          display: 'flex', 
          gap: 1
        }}
      >
        {matches.length > 0 && (
          <Button
            variant="contained"
            fullWidth
            onClick={handleRedactSelected}
            disabled={selectedMatches.size === 0}
          >
            Redact Selected ({selectedMatches.size})
          </Button>
        )}
      </Box>

      {/* Empty State */}
      {matches.length === 0 && !searching && searchTerm && !errorMessage && (
        <Alert severity="info">
          No matches found for "{searchTerm}"
        </Alert>
      )}

      {/* Error Message */}
      {errorMessage && (
        <Alert 
          severity="error" 
          onClose={() => setErrorMessage('')}
          sx={{ mt: 2 }}
        >
          {errorMessage}
        </Alert>
      )}
    </Box>
  );
};

export default FindReplaceDrawer;
