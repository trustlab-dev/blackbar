// frontend/src/components/viewer/AutoSuggestDrawer.tsx
import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import Button from '@mui/material/Button';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import Checkbox from '@mui/material/Checkbox';
import FormControlLabel from '@mui/material/FormControlLabel';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import Chip from '@mui/material/Chip';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import Close from '@mui/icons-material/Close';
import Refresh from '@mui/icons-material/Refresh';
import Collapse from '@mui/material/Collapse';
import ExpandMore from '@mui/icons-material/ExpandMore';
import ExpandLess from '@mui/icons-material/ExpandLess';
import api from '../../api/client';

interface Suggestion {
  text: string;
  category: string;
  reason: string;
  confidence: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  page?: number;
  bbox?: number[];
  // Rich fields from BC FIPPA v2 classification_pass schema. Optional
  // because legacy packs (Ontario MFIPPA) don't emit these.
  section_subsection?: string;
  reasoning_chain?: string[];
  severance_note?: string;
  exceptions_considered?: string[];
  public_interest_override_flag?: boolean;
  requires_human_review?: boolean;
  harm_identified?: string;
}

interface Redaction {
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  text: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  documentId: string;
  onApplySuggestions: (suggestions: Suggestion[]) => void;
  existingRedactions: Redaction[];
  onNavigateToPage?: (page: number) => void;
}

const AutoSuggestDrawer: React.FC<Props> = ({ open, onClose, documentId, onApplySuggestions, existingRedactions, onNavigateToPage }) => {
  const [activeTab, setActiveTab] = useState(0);
  const [quickPiiSuggestions, setQuickPiiSuggestions] = useState<Suggestion[]>([]);
  const [aiSuggestions, setAiSuggestions] = useState<Suggestion[]>([]);
  const [selectedQuickPii, setSelectedQuickPii] = useState<Set<number>>(new Set());
  const [selectedAi, setSelectedAi] = useState<Set<number>>(new Set());
  const [loadingQuickPii, setLoadingQuickPii] = useState(false);
  const [loadingAi, setLoadingAi] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [aiSuggestionsFetched, setAiSuggestionsFetched] = useState(false);
  const [pageFilter, setPageFilter] = useState<number | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  // Track which AI-suggestion rows have their "Why" reasoning expanded.
  // Indexed by suggestion array position in aiSuggestions.
  const [expandedReasoning, setExpandedReasoning] = useState<Set<number>>(new Set());
  // In a public demo (BLACKBAR_DEMO_MODE) there is no live LLM: the curated
  // AI-suggestion snapshot is served read-only, so the Regenerate affordances
  // are hidden. Sourced from the public config endpoint.
  const [demoMode, setDemoMode] = useState(false);

  useEffect(() => {
    if (open && documentId) {
      // Load Quick PII on open
      fetchQuickPii();
    }
  }, [open, documentId]);

  useEffect(() => {
    let cancelled = false;
    api
      .get('/admin/config/public')
      .then((response) => {
        if (!cancelled) setDemoMode(Boolean(response.data?.demo_mode));
      })
      .catch(() => {
        // Ignore — default to non-demo (Regenerate stays available).
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const isAlreadyRedacted = (suggestion: Suggestion): boolean => {
    // Check if this suggestion overlaps with any existing redaction
    if (!existingRedactions || existingRedactions.length === 0) return false;

    const suggestionPage = suggestion.page || 1;

    return existingRedactions.some(redaction => {
      if (redaction.page !== suggestionPage) return false;

      // Check if text matches exactly (most reliable)
      if (redaction.text && suggestion.text && suggestion.text.length > 2 &&
          redaction.text.toLowerCase() === suggestion.text.toLowerCase()) {
        return true;
      }

      // Check coordinate overlap only if both have real coordinates
      const suggestionX = suggestion.x || suggestion.bbox?.[0];
      const suggestionY = suggestion.y || suggestion.bbox?.[1];
      if (suggestionX != null && suggestionY != null && redaction.x != null && redaction.y != null) {
        if (suggestionX > 0 && suggestionY > 0 && redaction.x > 0 && redaction.y > 0) {
          const xOverlap = Math.abs(redaction.x - suggestionX) < 5;
          const yOverlap = Math.abs(redaction.y - suggestionY) < 5;
          if (xOverlap && yOverlap) return true;
        }
      }

      return false;
    });
  };

  const fetchQuickPii = async () => {
    setLoadingQuickPii(true);
    setErrorMessage('');
    try {
      const response = await api.get(`/documents/${documentId}/redaction-suggestions?quick=true`);
      console.log('Quick PII full response:', response.data);
      console.log('Quick PII array:', response.data.suggestions);
      const allSuggestions = response.data.suggestions || [];
      
      // Filter out already applied suggestions
      const suggestions = allSuggestions.filter((s: Suggestion) => !isAlreadyRedacted(s));
      
      console.log('Quick PII suggestions count (after filtering):', suggestions.length);
      console.log('Filtered out:', allSuggestions.length - suggestions.length);
      console.log('First Quick PII suggestion:', suggestions[0]);
      setQuickPiiSuggestions(suggestions);
      // Select all by default
      setSelectedQuickPii(new Set(suggestions.map((_: any, i: number) => i)));
    } catch (error: any) {
      console.error('Error fetching quick PII:', error);
      setErrorMessage(error.response?.data?.detail || 'Failed to load PII suggestions');
    } finally {
      setLoadingQuickPii(false);
    }
  };

  // forceRegenerate=true bypasses the backend cache and re-calls the LLM.
  // The drawer's "Generate" button does a normal fetch (uses cache if
  // present); the "Regenerate" button passes true so it actually re-runs
  // and picks up any prompt changes since the last cached result.
  const fetchAiSuggestions = async (forceRegenerate: boolean = false) => {
    setLoadingAi(true);
    setErrorMessage('');
    try {
      const qs = forceRegenerate ? '?quick=false&force_regenerate=true' : '?quick=false';
      const response = await api.get(`/documents/${documentId}/redaction-suggestions${qs}`);
      console.log('AI suggestions full response:', response.data);
      console.log('AI suggestions array:', response.data.suggestions);
      const allSuggestions = response.data.suggestions || [];
      
      // Filter out already applied suggestions
      const suggestions = allSuggestions.filter((s: Suggestion) => !isAlreadyRedacted(s));
      
      console.log('AI suggestions count (after filtering):', suggestions.length);
      console.log('Filtered out:', allSuggestions.length - suggestions.length);
      console.log('First suggestion:', suggestions[0]);
      setAiSuggestions(suggestions);
      setAiSuggestionsFetched(true);
      // Don't auto-select AI suggestions - user must explicitly choose
      setSelectedAi(new Set());
    } catch (error: any) {
      console.error('Error fetching AI suggestions:', error);
      setErrorMessage(error.response?.data?.detail || 'Failed to load AI suggestions');
      setAiSuggestionsFetched(true);
    } finally {
      setLoadingAi(false);
    }
  };

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
    // Load AI suggestions when switching to AI tab
    if (newValue === 1 && aiSuggestions.length === 0 && !loadingAi) {
      fetchAiSuggestions();
    }
  };

  const handleToggleQuickPii = (index: number) => {
    const newSelected = new Set(selectedQuickPii);
    if (newSelected.has(index)) {
      newSelected.delete(index);
    } else {
      newSelected.add(index);
    }
    setSelectedQuickPii(newSelected);
  };

  const handleToggleAi = (index: number) => {
    const newSelected = new Set(selectedAi);
    if (newSelected.has(index)) {
      newSelected.delete(index);
    } else {
      newSelected.add(index);
    }
    setSelectedAi(newSelected);
  };

  const handleSelectAllQuickPii = () => {
    if (selectedQuickPii.size === quickPiiSuggestions.length) {
      setSelectedQuickPii(new Set());
    } else {
      setSelectedQuickPii(new Set(quickPiiSuggestions.map((_, i) => i)));
    }
  };

  const handleSelectAllAi = () => {
    if (selectedAi.size === aiSuggestions.length) {
      setSelectedAi(new Set());
    } else {
      setSelectedAi(new Set(aiSuggestions.map((_, i) => i)));
    }
  };

  const handleRejectSuggestion = async (index: number) => {
    const suggestion = aiSuggestions[index];
    
    try {
      // Send rejection feedback to backend for fine-tuning
      await api.post(`/documents/${documentId}/ai-feedback`, {
        suggestion_text: suggestion.text,
        suggestion_category: suggestion.category,
        suggestion_reason: suggestion.reason,
        feedback: 'rejected',
        context: 'user_rejected_suggestion'
      });
      
      // Remove from list
      const remainingSuggestions = aiSuggestions.filter((_, i) => i !== index);
      setAiSuggestions(remainingSuggestions);
      
      // Remove from selected if it was selected
      const newSelected = new Set(selectedAi);
      newSelected.delete(index);
      setSelectedAi(newSelected);
    } catch (error) {
      console.error('Failed to record rejection:', error);
      // Still remove from list even if API call fails
      const remainingSuggestions = aiSuggestions.filter((_, i) => i !== index);
      setAiSuggestions(remainingSuggestions);
    }
  };

  const handleRejectSelected = async () => {
    const selectedSuggestions = aiSuggestions.filter((_, i) => selectedAi.has(i));
    
    // Send all rejections to backend
    for (const suggestion of selectedSuggestions) {
      try {
        await api.post(`/documents/${documentId}/ai-feedback`, {
          suggestion_text: suggestion.text,
          suggestion_category: suggestion.category,
          suggestion_reason: suggestion.reason,
          feedback: 'rejected',
          context: 'user_rejected_bulk'
        });
      } catch (error) {
        console.error('Failed to record rejection:', error);
      }
    }
    
    // Remove rejected suggestions from list
    const remainingSuggestions = aiSuggestions.filter((_, i) => !selectedAi.has(i));
    setAiSuggestions(remainingSuggestions);
    setSelectedAi(new Set());
  };

  const handleBulkAcceptFiltered = async () => {
    const suggestionsToAccept = filteredAiSuggestions;
    
    if (suggestionsToAccept.length === 0) return;
    
    // Apply all filtered suggestions
    onApplySuggestions(suggestionsToAccept);
    
    // Remove applied suggestions from list
    const appliedIndices = new Set(
      filteredAiSuggestions.map(s => aiSuggestions.indexOf(s))
    );
    const remainingSuggestions = aiSuggestions.filter((_, i) => !appliedIndices.has(i));
    setAiSuggestions(remainingSuggestions);
    setSelectedAi(new Set());
    onClose();
  };

  const handleBulkRejectFiltered = async () => {
    const suggestionsToReject = filteredAiSuggestions;
    
    if (suggestionsToReject.length === 0) return;
    
    // Send all rejections to backend
    for (const suggestion of suggestionsToReject) {
      try {
        await api.post(`/documents/${documentId}/ai-feedback`, {
          suggestion_text: suggestion.text,
          suggestion_category: suggestion.category,
          suggestion_reason: suggestion.reason,
          feedback: 'rejected',
          context: 'user_rejected_bulk_filtered'
        });
      } catch (error) {
        console.error('Failed to record rejection:', error);
      }
    }
    
    // Remove rejected suggestions from list
    const rejectedIndices = new Set(
      filteredAiSuggestions.map(s => aiSuggestions.indexOf(s))
    );
    const remainingSuggestions = aiSuggestions.filter((_, i) => !rejectedIndices.has(i));
    setAiSuggestions(remainingSuggestions);
    setSelectedAi(new Set());
  };

  const handleApply = () => {
    const suggestions = activeTab === 0
      ? quickPiiSuggestions.filter((_, i) => selectedQuickPii.has(i))
      : aiSuggestions.filter((_, i) => selectedAi.has(i));
    
    onApplySuggestions(suggestions);
    
    // Remove applied suggestions from the list to prevent duplicates
    if (activeTab === 0) {
      const remainingSuggestions = quickPiiSuggestions.filter((_, i) => !selectedQuickPii.has(i));
      setQuickPiiSuggestions(remainingSuggestions);
      setSelectedQuickPii(new Set());
    } else {
      const remainingSuggestions = aiSuggestions.filter((_, i) => !selectedAi.has(i));
      setAiSuggestions(remainingSuggestions);
      setSelectedAi(new Set());
    }
    
    onClose();
  };

  const getConfidenceColor = (confidence: string) => {
    switch (confidence?.toLowerCase()) {
      case 'high': return 'success';
      case 'medium': return 'warning';
      case 'low': return 'default';
      default: return 'default';
    }
  };

  // Filter AI suggestions based on page and category
  const filteredAiSuggestions = aiSuggestions.filter(s => {
    if (pageFilter && s.page !== pageFilter) return false;
    if (categoryFilter && s.category !== categoryFilter) return false;
    return true;
  });

  // Get unique pages and categories for filters
  const uniquePages = Array.from(new Set(aiSuggestions.map(s => s.page))).sort((a, b) => (a || 0) - (b || 0));
  const uniqueCategories = Array.from(new Set(aiSuggestions.map(s => s.category)));

  // Filter Quick PII suggestions
  const filteredQuickPiiSuggestions = quickPiiSuggestions.filter(s => {
    if (pageFilter && s.page !== pageFilter) return false;
    if (categoryFilter && s.category !== categoryFilter) return false;
    return true;
  });

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      variant="persistent"
      sx={{
        '& .MuiDrawer-paper': {
          width: 400,
          right: '60px',
          height: '100%',
          boxShadow: 3,
          position: 'absolute',
          zIndex: 1200
        }
      }}
      ModalProps={{
        keepMounted: true,
        BackdropProps: {
          invisible: true
        }
      }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Header */}
        <Box sx={{ p: 2, borderBottom: '1px solid var(--border-default)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography variant="h6">Auto Suggestions</Typography>
          <IconButton size="small" onClick={onClose}>
            <Close />
          </IconButton>
        </Box>

        {/* Tabs */}
        <Tabs value={activeTab} onChange={handleTabChange} sx={{ borderBottom: '1px solid var(--border-default)' }}>
          <Tab label={`Quick PII (${filteredQuickPiiSuggestions.length})`} />
          <Tab label={`AI Recommended (${filteredAiSuggestions.length})`} />
        </Tabs>

        {/* Filter Controls */}
        <Box sx={{ p: 2, borderBottom: '1px solid var(--border-default)', display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <FormControl size="small" sx={{ minWidth: 100, flex: 1 }}>
            <InputLabel>Page</InputLabel>
            <Select
              value={pageFilter || ''}
              onChange={(e) => setPageFilter(e.target.value ? Number(e.target.value) : null)}
              label="Page"
            >
              <MenuItem value="">All</MenuItem>
              {uniquePages.map(page => (
                <MenuItem key={page} value={page}>Page {page}</MenuItem>
              ))}
            </Select>
          </FormControl>
          
          <FormControl size="small" sx={{ minWidth: 120, flex: 1 }}>
            <InputLabel>Category</InputLabel>
            <Select
              value={categoryFilter || ''}
              onChange={(e) => setCategoryFilter(e.target.value || null)}
              label="Category"
            >
              <MenuItem value="">All</MenuItem>
              {uniqueCategories.map(cat => (
                <MenuItem key={cat} value={cat}>{cat}</MenuItem>
              ))}
            </Select>
          </FormControl>
          
          {(pageFilter || categoryFilter) && (
            <Button
              size="small"
              onClick={() => {
                setPageFilter(null);
                setCategoryFilter(null);
              }}
              sx={{ textTransform: 'none' }}
            >
              Clear
            </Button>
          )}
        </Box>

        {/* Error Message */}
        {errorMessage && (
          <Alert severity="error" onClose={() => setErrorMessage('')} sx={{ m: 2 }}>
            {errorMessage}
          </Alert>
        )}

        {/* Content */}
        <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
          {/* Quick PII Tab */}
          {activeTab === 0 && (
            <>
              {loadingQuickPii ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                  <CircularProgress />
                </Box>
              ) : filteredQuickPiiSuggestions.length === 0 ? (
                <Alert severity="info">No PII patterns match the current filters</Alert>
              ) : (
                <>
                  <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Button size="small" onClick={handleSelectAllQuickPii}>
                      {selectedQuickPii.size === quickPiiSuggestions.length ? 'Deselect All' : 'Select All'}
                    </Button>
                    <Button size="small" startIcon={<Refresh />} onClick={fetchQuickPii}>
                      Refresh
                    </Button>
                  </Box>
                  {filteredQuickPiiSuggestions.map((suggestion) => {
                    const index = quickPiiSuggestions.indexOf(suggestion);
                    return (<Box
                      key={index}
                      sx={{
                        mb: 1,
                        border: '1px solid var(--border-default)',
                        borderRadius: 1,
                        bgcolor: selectedQuickPii.has(index) ? '#f0f9ff' : 'white',
                        display: 'flex',
                        alignItems: 'flex-start'
                      }}
                    >
                      <Checkbox
                        checked={selectedQuickPii.has(index)}
                        onChange={() => handleToggleQuickPii(index)}
                        size="small"
                        sx={{ p: 1.5, pb: 0 }}
                      />
                      <Box
                        sx={{
                          flex: 1,
                          p: 1.5,
                          pl: 0,
                          cursor: 'pointer',
                          '&:hover': {
                            bgcolor: 'rgba(0, 0, 0, 0.02)'
                          }
                        }}
                        onClick={() => {
                          if (suggestion.page && onNavigateToPage) {
                            onNavigateToPage(suggestion.page);
                          }
                        }}
                      >
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {suggestion.text}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {suggestion.category} - {suggestion.reason}
                        </Typography>
                        {suggestion.page && (
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            Page {suggestion.page}
                          </Typography>
                        )}
                      </Box>
                    </Box>
                  );
                  })}
                </>
              )}
            </>
          )}

          {/* AI Recommendations Tab */}
          {activeTab === 1 && (
            <>
              {loadingAi ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 4, gap: 1.5 }}>
                  <CircularProgress />
                  <Typography variant="body2" color="text.secondary" align="center">
                    Analysing document…
                  </Typography>
                  <Typography variant="caption" color="text.secondary" align="center" sx={{ maxWidth: 280 }}>
                    Typically ~10–25s depending on provider, document length, and current load.
                  </Typography>
                </Box>
              ) : filteredAiSuggestions.length === 0 && !loadingAi ? (
                <Box>
                  <Alert severity={aiSuggestionsFetched ? "success" : "info"} sx={{ mb: 2 }}>
                    {aiSuggestionsFetched 
                      ? 'All AI suggestions have been applied or filtered out'
                      : 'AI suggestions not loaded yet'}
                  </Alert>
                  {!demoMode && (
                    <Button variant="contained" fullWidth onClick={() => fetchAiSuggestions(aiSuggestionsFetched)}>
                      {aiSuggestionsFetched ? 'Regenerate AI Suggestions' : 'Generate AI Suggestions'}
                    </Button>
                  )}
                </Box>
              ) : (
                <>
                  {/* Bulk Action Buttons */}
                  {filteredAiSuggestions.length > 0 && (
                    <Box sx={{ mb: 2, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                      <Button
                        variant="contained"
                        color="success"
                        size="small"
                        onClick={handleBulkAcceptFiltered}
                        sx={{ textTransform: 'none', flex: 1 }}
                      >
                        Accept Filtered ({filteredAiSuggestions.length})
                      </Button>
                      <Button
                        variant="outlined"
                        color="error"
                        size="small"
                        onClick={handleBulkRejectFiltered}
                        sx={{ textTransform: 'none', flex: 1 }}
                      >
                        Reject Filtered ({filteredAiSuggestions.length})
                      </Button>
                    </Box>
                  )}
                  
                  <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Button size="small" onClick={handleSelectAllAi}>
                      {selectedAi.size === aiSuggestions.length ? 'Deselect All' : 'Select All'}
                    </Button>
                    {!demoMode && (
                      <Button size="small" startIcon={<Refresh />} onClick={() => fetchAiSuggestions(true)}>
                        Regenerate
                      </Button>
                    )}
                  </Box>
                  {filteredAiSuggestions.map((suggestion) => {
                    const index = aiSuggestions.indexOf(suggestion);
                    return (<Box
                      key={index}
                      sx={{
                        mb: 1,
                        border: '1px solid var(--border-default)',
                        borderRadius: 1,
                        bgcolor: (suggestion as any).rejected ? 'var(--bg-tertiary)' : (selectedAi.has(index) ? '#f0fdf4' : 'white'),
                        display: 'flex',
                        alignItems: 'flex-start',
                        opacity: (suggestion as any).rejected ? 0.6 : 1
                      }}
                    >
                      <Checkbox
                        checked={selectedAi.has(index)}
                        onChange={() => handleToggleAi(index)}
                        size="small"
                        sx={{ p: 1.5, pb: 0 }}
                      />
                      <Box
                        sx={{
                          flex: 1,
                          p: 1.5,
                          pl: 0,
                          cursor: 'pointer',
                          '&:hover': {
                            bgcolor: 'rgba(0, 0, 0, 0.02)'
                          }
                        }}
                        onClick={() => {
                          if (suggestion.page && onNavigateToPage) {
                            onNavigateToPage(suggestion.page);
                          }
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5, flexWrap: 'wrap' }}>
                          <Typography variant="body2" sx={{ fontWeight: 500, mr: 0.5 }}>
                            {suggestion.text.length > 60 ? `${suggestion.text.slice(0, 60)}…` : suggestion.text}
                          </Typography>
                          {(suggestion as any).rejected ? (
                            <Chip
                              label="Rejected"
                              size="small"
                              sx={{ height: 18, fontSize: '10px', bgcolor: '#9e9e9e', color: 'white' }}
                            />
                          ) : (
                            <Chip
                              label={suggestion.confidence || 'medium'}
                              size="small"
                              color={getConfidenceColor(suggestion.confidence)}
                              sx={{ height: 18, fontSize: '10px' }}
                            />
                          )}
                          {suggestion.requires_human_review && (
                            <Chip
                              label="Review"
                              size="small"
                              sx={{ height: 18, fontSize: '10px', bgcolor: '#ffa726', color: 'white' }}
                              title="Pack flagged this for mandatory human review"
                            />
                          )}
                          {suggestion.public_interest_override_flag && (
                            <Chip
                              label="s.25?"
                              size="small"
                              sx={{ height: 18, fontSize: '10px', bgcolor: '#7e57c2', color: 'white' }}
                              title="Pack flagged this for s.25 public-interest override consideration"
                            />
                          )}
                        </Box>
                        <Typography variant="caption" color="text.secondary">
                          {suggestion.section_subsection || suggestion.category} — {suggestion.reason}
                        </Typography>
                        {suggestion.page && (
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            Page {suggestion.page}
                          </Typography>
                        )}
                        {/* Rich-schema "Why" expander — only renders for suggestions that
                            actually carry reasoning_chain / severance_note / exceptions
                            (i.e. BC FIPPA v2 pack and similar). Legacy suggestions
                            without these fields show nothing here. */}
                        {(suggestion.reasoning_chain?.length ||
                          suggestion.severance_note ||
                          suggestion.harm_identified ||
                          suggestion.exceptions_considered?.length) && (
                          <Box sx={{ mt: 0.5 }}>
                            <Button
                              size="small"
                              onClick={(e) => {
                                e.stopPropagation();
                                setExpandedReasoning(prev => {
                                  const next = new Set(prev);
                                  if (next.has(index)) next.delete(index);
                                  else next.add(index);
                                  return next;
                                });
                              }}
                              endIcon={expandedReasoning.has(index) ? <ExpandLess /> : <ExpandMore />}
                              sx={{ textTransform: 'none', fontSize: '11px', py: 0, minWidth: 0 }}
                            >
                              Why
                            </Button>
                            <Collapse in={expandedReasoning.has(index)} timeout="auto">
                              <Box sx={{ mt: 0.5, pl: 1, borderLeft: '2px solid #e0e0e0', fontSize: '11px' }}>
                                {suggestion.reasoning_chain?.length ? (
                                  <Box sx={{ mb: 1 }}>
                                    <Typography variant="caption" sx={{ fontWeight: 600, display: 'block' }}>
                                      Reasoning
                                    </Typography>
                                    {suggestion.reasoning_chain.map((step, i) => (
                                      <Typography
                                        key={i}
                                        variant="caption"
                                        color="text.secondary"
                                        sx={{ display: 'block', pl: 1 }}
                                      >
                                        {step}
                                      </Typography>
                                    ))}
                                  </Box>
                                ) : null}
                                {suggestion.harm_identified && (
                                  <Box sx={{ mb: 1 }}>
                                    <Typography variant="caption" sx={{ fontWeight: 600, display: 'block' }}>
                                      Harm identified
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary" sx={{ pl: 1 }}>
                                      {suggestion.harm_identified}
                                    </Typography>
                                  </Box>
                                )}
                                {suggestion.severance_note && (
                                  <Box sx={{ mb: 1 }}>
                                    <Typography variant="caption" sx={{ fontWeight: 600, display: 'block' }}>
                                      Severance
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary" sx={{ pl: 1 }}>
                                      {suggestion.severance_note}
                                    </Typography>
                                  </Box>
                                )}
                                {suggestion.exceptions_considered?.length ? (
                                  <Box sx={{ mb: 0.5 }}>
                                    <Typography variant="caption" sx={{ fontWeight: 600, display: 'block' }}>
                                      Exceptions considered
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary" sx={{ pl: 1 }}>
                                      {suggestion.exceptions_considered.join(', ')}
                                    </Typography>
                                  </Box>
                                ) : null}
                              </Box>
                            </Collapse>
                          </Box>
                        )}
                        {!(suggestion as any).rejected && (
                          <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
                            <Button
                              size="small"
                              variant="contained"
                              color="success"
                              onClick={(e) => {
                                e.stopPropagation();
                                // Auto-apply this single suggestion
                                onApplySuggestions([suggestion]);
                                // Remove from list
                                const remainingSuggestions = aiSuggestions.filter((_, i) => i !== index);
                                setAiSuggestions(remainingSuggestions);
                              }}
                              sx={{ textTransform: 'none', fontSize: '11px', py: 0.5 }}
                            >
                              Accept
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              color="error"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleRejectSuggestion(index);
                              }}
                              sx={{ textTransform: 'none', fontSize: '11px', py: 0.5 }}
                            >
                              Reject
                            </Button>
                          </Box>
                        )}
                      </Box>
                    </Box>
                  );
                  })}
                </>
              )}
            </>
          )}
        </Box>

        {/* Footer Actions */}
        <Box
          sx={{
            borderTop: '1px solid var(--border-default)',
            p: 2,
            display: 'flex',
            gap: 1
          }}
        >
          <Button variant="outlined" fullWidth onClick={onClose}>
            Cancel
          </Button>
          {activeTab === 1 && selectedAi.size > 0 && (
            <Button
              variant="outlined"
              color="error"
              fullWidth
              onClick={handleRejectSelected}
            >
              Reject Selected ({selectedAi.size})
            </Button>
          )}
          <Button
            variant="contained"
            fullWidth
            onClick={handleApply}
            disabled={
              (activeTab === 0 && selectedQuickPii.size === 0) ||
              (activeTab === 1 && selectedAi.size === 0)
            }
          >
            Apply Selected ({activeTab === 0 ? selectedQuickPii.size : selectedAi.size})
          </Button>
        </Box>
      </Box>
    </Drawer>
  );
};

export default AutoSuggestDrawer;
