// frontend/src/components/viewer/ViewerShell.tsx
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
// MUI v7 default imports
import AppBar from '@mui/material/AppBar';
import Toolbar from '@mui/material/Toolbar';
import IconButton from '@mui/material/IconButton';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Tooltip from '@mui/material/Tooltip';
import Badge from '@mui/material/Badge';
import Snackbar from '@mui/material/Snackbar';
import Alert from '@mui/material/Alert';
import Popover from '@mui/material/Popover';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import TextField from '@mui/material/TextField';
import Select from '@mui/material/Select';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';

// MUI v7 icons default imports
import ArrowBack from '@mui/icons-material/ArrowBack';
import Undo from '@mui/icons-material/Undo';
import Redo from '@mui/icons-material/Redo';
import Search from '@mui/icons-material/Search';
import ZoomIn from '@mui/icons-material/ZoomIn';
import ZoomOut from '@mui/icons-material/ZoomOut';
import FirstPage from '@mui/icons-material/FirstPage';
import LastPage from '@mui/icons-material/LastPage';
import ChevronLeft from '@mui/icons-material/ChevronLeft';
import ChevronRight from '@mui/icons-material/ChevronRight';
import Share from '@mui/icons-material/Share';
import Help from '@mui/icons-material/Help';
import FormatListNumbered from '@mui/icons-material/FormatListNumbered';
import Delete from '@mui/icons-material/Delete';
import Edit from '@mui/icons-material/Edit';
import Save from '@mui/icons-material/Save';
import Close from '@mui/icons-material/Close';
import api from '../../api/client';
import PDFViewerWithSelection from './PDFViewerWithSelection';
import LeftToolRail from './LeftToolRail';
import RightUtilityBar from './RightUtilityBar';
import CommentsDrawer from './CommentsDrawer';
import ThumbnailsRail from './ThumbnailsRail';
import ManualRedactionTool, { RedactionData } from './ManualRedactionTool';
import DrawRedactionTool from './DrawRedactionTool';
import FindReplaceDrawer from './FindReplaceDrawer';
import AutoSuggestDrawer from './AutoSuggestDrawer';
import HistoryDrawer from './HistoryDrawer';
import ReasonPickerModal, { RedactionReason } from './ReasonPickerModal';
import SuggestedRedactionOverlay from './SuggestedRedactionOverlay';
import './ViewerShell.css';

interface Props {
  documentId: string;
}

interface DocumentMeta {
  filename: string;
  case_id?: string;
  case_number?: string;
  text_data?: {
    pages: Array<{
      page_num: number;
      width: number;
      height: number;
      words: any[];
      lines: any[];
    }>;
  };
}

interface Redaction {
  id?: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  text: string;
  reason?: RedactionReason;
  color?: string;
  createdBy?: string;
  createdByRole?: string;
  createdAt?: string;
  type?: string;
  status?: string;
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
  bbox?: number[];
  has_coordinates?: boolean;
}

const ZOOM_LEVELS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0];
const DEFAULT_ZOOM = 1.5; // 150% - larger for better readability

export const ViewerShell: React.FC<Props> = ({ documentId }) => {
  const navigate = useNavigate();
  const [documentMeta, setDocumentMeta] = useState<DocumentMeta | null>(null);
  const [numPages, setNumPages] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [zoom, setZoom] = useState<number>(DEFAULT_ZOOM);
  const [zoomAnchorEl, setZoomAnchorEl] = useState<null | HTMLElement>(null);
  const [undoStack, setUndoStack] = useState<any[]>([]);
  const [redoStack, setRedoStack] = useState<any[]>([]);
  const [showThumbnails, setShowThumbnails] = useState<boolean>(true);
  const [activeTool, setActiveTool] = useState<string>('select');
  const [manualRedactionEnabled, setManualRedactionEnabled] = useState<boolean>(false);
  const [drawRedactionEnabled, setDrawRedactionEnabled] = useState<boolean>(false);
  const [findReplaceOpen, setFindReplaceOpen] = useState<boolean>(false);
  const [redactions, setRedactions] = useState<Redaction[]>([]);
  const [pendingRedaction, setPendingRedaction] = useState<RedactionData | null>(null);
  const [pendingRedactions, setPendingRedactions] = useState<RedactionData[]>([]);
  const [reasonPickerOpen, setReasonPickerOpen] = useState<boolean>(false);
  const [redactionColor, setRedactionColor] = useState<string>('blue'); // Light blue for all redactions, green for AI suggestions later
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [showError, setShowError] = useState<boolean>(false);
  const [isScrolling, setIsScrolling] = useState<boolean>(false);
  const [pageTransitioning, setPageTransitioning] = useState<boolean>(false);
  const [selectedRedactionIndex, setSelectedRedactionIndex] = useState<number | null>(null);
  const [redactionMenuAnchor, setRedactionMenuAnchor] = useState<{ x: number; y: number } | null>(null);
  const [highlightedMatchBbox, setHighlightedMatchBbox] = useState<number[] | null>(null);
  const [showRedactionPreview, setShowRedactionPreview] = useState<boolean>(true);
  const [autoSuggestOpen, setAutoSuggestOpen] = useState<boolean>(false);
  const [historyOpen, setHistoryOpen] = useState<boolean>(false);
  const [commentsOpen, setCommentsOpen] = useState<boolean>(false);
  const [isEditingRedaction, setIsEditingRedaction] = useState<boolean>(false);
  const [editedCategory, setEditedCategory] = useState<string>('');
  const [editedDescription, setEditedDescription] = useState<string>('');
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState<boolean>(false);

  useEffect(() => {
    fetchDocumentMeta();
    fetchRedactions();
    fetchSuggestions();
  }, [documentId]);

  const fetchDocumentMeta = async () => {
    try {
      const response = await api.get(`/documents/${documentId}/metadata`);
      setDocumentMeta(response.data);

      if (response.data.text_data?.pages) {
        setNumPages(response.data.text_data.pages.length);
      }

      // Fetch case info if available
      if (response.data.case_id) {
        const caseResponse = await api.get(`/cases/${response.data.case_id}`);
        setDocumentMeta(prev => ({
          ...prev!,
          case_number: caseResponse.data.tracking_number
        }));
      }
    } catch (error) {
      console.error('Error fetching document metadata:', error);
    }
  };

  const fetchRedactions = async () => {
    try {
      // Redactions are stored in the document metadata
      const response = await api.get(`/documents/${documentId}/metadata`);
      if (response.data.redactions) {
        // Map backend format to frontend format, keeping all metadata including ID
        const mappedRedactions = response.data.redactions.map((r: any) => ({
          id: r.id, // Important: keep the ID for deletion
          x: r.x,
          y: r.y,
          width: r.width,
          height: r.height,
          page: r.page,
          text: r.description || '',
          reason: {
            categoryName: r.category,
            section: r.section,
            notes: r.description
          },
          color: r.type === 'ai_suggestion' ? 'green' : 'blue',
          createdBy: r.created_by_role ? `User (${r.created_by_role})` : undefined, // Show role instead of UID
          createdByRole: r.created_by_role,
          createdAt: r.created_at,
          type: r.type,
          status: r.status
        }));
        setRedactions(mappedRedactions);
      }
    } catch (error) {
      console.error('Error fetching redactions:', error);
    }
  };

  const fetchSuggestions = async () => {
    setLoadingSuggestions(true);
    try {
      const response = await api.get(`/documents/${documentId}/redaction-suggestions?quick=false`);
      const allSuggestions = response.data.suggestions || [];

      // Filter out already-applied suggestions
      const unapplied = allSuggestions.filter((s: Suggestion) => !isAlreadyApplied(s));
      setSuggestions(unapplied);
    } catch (error) {
      console.error('Error fetching suggestions:', error);
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const isAlreadyApplied = (suggestion: Suggestion): boolean => {
    return redactions.some(r =>
      r.page === suggestion.page &&
      r.text && suggestion.text &&
      r.text.toLowerCase().includes(suggestion.text.toLowerCase())
    );
  };

  const fetchPDF = async () => {
    try {
      const response = await api.get(`/documents/${documentId}`, {
        responseType: 'blob'
      });
      const url = URL.createObjectURL(response.data);
      setPdfUrl(url);
    } catch (error) {
      console.error('Error fetching PDF:', error);
    }
  };

  useEffect(() => {
    fetchPDF();
  }, [documentId]);

  // Escape key closes the redaction menu first, then deselects the
  // redaction on a second press. This lets operators free-up the
  // handles by dismissing the menu without losing the selection.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (redactionMenuAnchor) {
        setRedactionMenuAnchor(null);
        setIsEditingRedaction(false);
      } else if (selectedRedactionIndex !== null) {
        setSelectedRedactionIndex(null);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [redactionMenuAnchor, selectedRedactionIndex]);

  const handleBack = () => {
    if (documentMeta?.case_id) {
      navigate(`/cases/${documentMeta.case_id}/documents`);
    } else {
      window.history.back();
    }
  };

  const handleUndo = () => {
    // TODO(issue: TBD): Implement undo logic
    console.log('Undo');
  };

  const handleRedo = () => {
    // TODO(issue: TBD): Implement redo logic
    console.log('Redo');
  };

  const handleZoomIn = () => {
    const currentIndex = ZOOM_LEVELS.indexOf(zoom);
    if (currentIndex < ZOOM_LEVELS.length - 1) {
      setZoom(ZOOM_LEVELS[currentIndex + 1]);
    }
  };

  const handleZoomOut = () => {
    const currentIndex = ZOOM_LEVELS.indexOf(zoom);
    if (currentIndex > 0) {
      setZoom(ZOOM_LEVELS[currentIndex - 1]);
    }
  };

  const handleZoomSelect = (level: number) => {
    setZoom(level);
    setZoomAnchorEl(null);
  };

  const handlePreviousPage = () => {
    if (currentPage > 1) {
      setCurrentPage(currentPage - 1);
    }
  };

  const handleNextPage = () => {
    if (currentPage < numPages) {
      setCurrentPage(currentPage + 1);
    }
  };

  const handleFirstPage = () => {
    setCurrentPage(1);
  };

  const handleLastPage = () => {
    setCurrentPage(numPages);
  };

  const handleScroll = (e: any) => {
    // Prevent rapid page changes
    if (isScrolling) return;

    // Detect scroll direction
    if (e.deltaY > 0 && currentPage < numPages) {
      // Scrolling down - next page with fade transition
      setIsScrolling(true);
      setPageTransitioning(true);
      setTimeout(() => {
        setCurrentPage(currentPage + 1);
        setPageTransitioning(false);
      }, 150);
      setTimeout(() => setIsScrolling(false), 400);
    } else if (e.deltaY < 0 && currentPage > 1) {
      // Scrolling up - previous page with fade transition
      setIsScrolling(true);
      setPageTransitioning(true);
      setTimeout(() => {
        setCurrentPage(currentPage - 1);
        setPageTransitioning(false);
      }, 150);
      setTimeout(() => setIsScrolling(false), 400);
    }
  };

  const handleToolChange = (toolId: string) => {
    // Disable all tools first
    setManualRedactionEnabled(false);
    setDrawRedactionEnabled(false);
    setFindReplaceOpen(false);

    // Set active tool
    setActiveTool(toolId);

    // Enable the selected tool
    switch (toolId) {
      case 'select':
        // Select tool uses native text selection (no overlay needed)
        // User can highlight text with mouse, and PDFViewerWithSelection will handle it
        break;
      case 'draw-redaction':
        setDrawRedactionEnabled(true);
        break;
      case 'find-replace':
        setFindReplaceOpen(true);
        break;
      case 'rotate':
      case 'tour':
        // TODO(issue: TBD): Implement rotate and tour tools
        console.log(`${toolId} tool selected`);
        break;
      case 'color':
        break;
    }
  };

  const handleRedactionCreated = (redactionData: RedactionData) => {
    // Store pending redaction and open reason picker
    setPendingRedaction(redactionData);
    setPendingRedactions([redactionData]); // Wrap in array for consistency
    setReasonPickerOpen(true);
  };

  const handleMultipleRedactionsCreated = (redactionDataArray: RedactionData[]) => {
    // Store multiple pending redactions and open reason picker once
    setPendingRedaction(redactionDataArray[0]); // For backward compatibility
    setPendingRedactions(redactionDataArray);
    setReasonPickerOpen(true);
  };

  const handleReasonSave = async (reason: RedactionReason) => {
    if (pendingRedactions.length === 0) return;

    // Create redactions for all pending rectangles
    const newRedactions: Redaction[] = pendingRedactions.map(data => ({
      x: data.x,
      y: data.y,
      width: data.width,
      height: data.height,
      page: data.page || currentPage, // Use page from data if available, otherwise current page
      text: data.text,
      reason: reason,
      color: redactionColor
    }));

    // Add to undo stack
    setUndoStack([...undoStack, { type: 'add', redactions: newRedactions }]);
    setRedoStack([]); // Clear redo stack

    // Add to redactions list
    setRedactions([...redactions, ...newRedactions]);

    // Save to backend - save all redactions
    try {
      for (const redaction of newRedactions) {
        await api.post(`/documents/${documentId}/redactions`, {
          x: redaction.x,
          y: redaction.y,
          width: redaction.width,
          height: redaction.height,
          page: redaction.page,
          category: reason.categoryCode || reason.categoryName || 'redacted',
          description: reason.notes || `${reason.categoryName} - ${reason.section}`
        });
      }
    } catch (error: any) {
      console.error('Error saving redaction:', error);
      const message = error.response?.status === 401
        ? 'Authentication required. Please log in to save redactions.'
        : error.response?.data?.detail || 'Failed to save redaction. Please try again.';
      setErrorMessage(message);
      setShowError(true);
    }

    // Clear pending
    setPendingRedaction(null);
    setPendingRedactions([]);
    setReasonPickerOpen(false);

    // Don't auto-exit draw mode - let user stay in the tool to draw multiple redactions
    // User can manually switch tools when done
  };

  const getCurrentPageData = () => {
    if (!documentMeta?.text_data?.pages) return null;
    return documentMeta.text_data.pages.find(p => p.page_num === currentPage) || null;
  };

  const handleRedactMatches = async (matches: any[], searchTerm: string) => {
    console.log('Redacting matches:', matches, 'for term:', searchTerm);

    // Convert search matches to pending redactions format
    // Include page number for each match
    const pendingRedactionsList = matches.map(match => ({
      x: match.bbox[0],
      y: match.bbox[1],
      width: match.bbox[2] - match.bbox[0],
      height: match.bbox[3] - match.bbox[1],
      page: match.page, // Include page from search result
      text: match.text,
      snappedWords: [match.text]
    }));

    // Set pending redactions and open reason picker
    setPendingRedactions(pendingRedactionsList);
    setReasonPickerOpen(true);
  };

  const handleAcceptSuggestion = async (suggestion: Suggestion) => {
    if (!suggestion.coordinates) return;

    try {
      const redactionData = {
        x: suggestion.coordinates.x,
        y: suggestion.coordinates.y,
        width: suggestion.coordinates.width,
        height: suggestion.coordinates.height,
        page: suggestion.page,
        category: suggestion.category || suggestion.section || 'S22',
        description: suggestion.reason || ''
      };

      const response = await api.post(`/documents/${documentId}/redactions`, redactionData);

      // Get current user info
      const userStr = localStorage.getItem('user');
      const currentUser = userStr ? JSON.parse(userStr) : null;

      // Map backend response to frontend format
      const backendRedaction = response.data.redaction || response.data;

      const mappedRedaction = {
        ...redactionData,
        id: backendRedaction.id,
        text: suggestion.text || '',
        reason: {
          categoryName: suggestion.category || 'S22',
          notes: suggestion.reason || ''
        },
        createdBy: backendRedaction.created_by || currentUser?.username || 'Unknown',
        createdByRole: backendRedaction.created_by_role || 'admin',
        createdAt: backendRedaction.created_at || new Date().toISOString(),
        status: 'pending',
        type: backendRedaction.type || 'professional'
      };

      setRedactions(prev => [...prev, mappedRedaction]);
      setSuggestions(prev => prev.filter(s => s !== suggestion));
    } catch (error) {
      console.error('Error accepting suggestion:', error);
      setErrorMessage('Failed to accept suggestion');
      setShowError(true);
    }
  };

  const handleRejectSuggestion = async (suggestion: Suggestion) => {
    try {
      await api.post(`/documents/${documentId}/ai-feedback`, {
        suggestion_text: suggestion.text,
        suggestion_category: suggestion.category,
        suggestion_reason: suggestion.reason,
        feedback: 'rejected',
        context: 'user_rejected_overlay'
      });

      setSuggestions(prev => prev.filter(s => s !== suggestion));
    } catch (error) {
      console.error('Error rejecting suggestion:', error);
    }
  };

  // Look up text in OCR data to find bounding box coordinates
  const findTextInOCR = (text: string, page: number): { x: number; y: number; width: number; height: number } | null => {
    if (!documentMeta?.text_data?.pages) return null;
    const pageData = documentMeta.text_data.pages.find(p => p.page_num === page);
    if (!pageData?.words) return null;

    const search = text.toLowerCase().trim();
    if (!search) return null;

    // OCR words often carry trailing punctuation glued on by the tokenizer
    // (e.g. "555-0188." for a phone number at the end of a sentence) and
    // surrounding brackets/quotes. Strip them so an AI suggestion of plain
    // "555-0188" still matches the OCR word "555-0188.".
    const stripEdgePunct = (s: string) =>
      s.replace(/^[(\[{"'“‘]+/, '').replace(/[.,;:!?)\]}"'”’]+$/g, '');

    // Pass 1: single-word match. Catches the common case — phones, SSNs,
    // emails, single names — without the risk of over-matching surrounding
    // text. We prefer an exact equality match; if none, accept a word that
    // contains the search as a substring (e.g. OCR glued chars onto one
    // side that stripEdgePunct missed).
    let substringFallback: { x: number; y: number; width: number; height: number } | null = null;
    for (const w of pageData.words) {
      const wt = stripEdgePunct((w.text || '').toLowerCase());
      const [wx0, wy0, wx1, wy1] = w.bbox;
      const bbox = { x: wx0, y: wy0, width: wx1 - wx0, height: wy1 - wy0 };
      if (wt === search) {
        return bbox;
      }
      if (!substringFallback && wt.includes(search)) {
        substringFallback = bbox;
      }
    }
    if (substringFallback) return substringFallback;

    // Pass 2: multi-word match (for names like "John Smith"). Find the
    // smallest consecutive window of words whose space-joined text equals
    // the search text after edge-punctuation stripping on each word.
    for (let i = 0; i < pageData.words.length; i++) {
      let combined = '';
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (let j = i; j < pageData.words.length; j++) {
        const word = pageData.words[j];
        const wt = stripEdgePunct((word.text || '').toLowerCase());
        if (combined) combined += ' ';
        combined += wt;
        const [wx0, wy0, wx1, wy1] = word.bbox;
        minX = Math.min(minX, wx0);
        minY = Math.min(minY, wy0);
        maxX = Math.max(maxX, wx1);
        maxY = Math.max(maxY, wy1);
        if (combined === search) {
          return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
        }
        // Once combined is at least as long as the search and not equal,
        // extending further can't help — this window started too early.
        if (combined.length >= search.length) break;
      }
    }
    return null;
  };

  const handleApplySuggestions = async (suggestions: any[]) => {
    console.log('Applying suggestions:', suggestions);

    // Apply each suggestion directly with its category/reason
    for (const suggestion of suggestions) {
      // Use provided coordinates, or look up from OCR data
      let x = suggestion.x || suggestion.bbox?.[0] || 0;
      let y = suggestion.y || suggestion.bbox?.[1] || 0;
      let width = suggestion.width || (suggestion.bbox ? suggestion.bbox[2] - suggestion.bbox[0] : 0);
      let height = suggestion.height || (suggestion.bbox ? suggestion.bbox[3] - suggestion.bbox[1] : 0);
      const page = suggestion.page || 1;

      // If no real coordinates, try to find text in OCR data
      if (x === 0 && y === 0 && suggestion.text) {
        const ocrCoords = findTextInOCR(suggestion.text, page);
        if (ocrCoords) {
          x = ocrCoords.x;
          y = ocrCoords.y;
          width = ocrCoords.width;
          height = ocrCoords.height;
          console.log(`Found OCR coordinates for "${suggestion.text}":`, ocrCoords);
        } else {
          console.warn(`Could not find OCR coordinates for "${suggestion.text}" on page ${page}`);
        }
      }

      const redactionData = {
        x, y, width, height, page,
        category: suggestion.category || 'S22',
        description: suggestion.reason || ''
      };

      try {
        const response = await api.post(`/documents/${documentId}/redactions`, redactionData);

        // Get current user info
        const userStr = localStorage.getItem('user');
        const currentUser = userStr ? JSON.parse(userStr) : null;

        // Map backend response to frontend format
        const backendRedaction = response.data.redaction || response.data;

        // Determine username: backend returns it, or use localStorage as fallback
        const username = backendRedaction.created_by || currentUser?.username || 'Unknown';

        const mappedRedaction = {
          ...redactionData,  // Coordinates and page from request
          id: backendRedaction.id,
          text: suggestion.text || '',
          reason: {
            categoryName: suggestion.category || 'S22',
            notes: suggestion.reason || ''
          },
          createdBy: username,
          createdByRole: backendRedaction.created_by_role || 'admin',
          createdAt: backendRedaction.created_at || new Date().toISOString(),
          status: 'pending',  // Always pending when created from suggestions
          type: backendRedaction.type || 'professional'
        };

        setRedactions(prev => [...prev, mappedRedaction]);
      } catch (error) {
        console.error('Failed to create redaction:', error);
        setErrorMessage('Failed to apply some suggestions');
        setShowError(true);
      }
    }
  };

  const handleRedactionClick = (index: number, event: React.MouseEvent) => {
    event.stopPropagation();
    setSelectedRedactionIndex(index);
    setRedactionMenuAnchor({ x: event.clientX, y: event.clientY });
  };

  // Operator drag-resized a redaction. Update local state immediately for
  // smoothness, then persist via the edit endpoint. On failure we re-fetch
  // so the UI matches the server rather than guessing the rollback shape.
  const handleRedactionResize = async (
    redactionId: string,
    rect: { x: number; y: number; width: number; height: number },
  ) => {
    setRedactions(prev => prev.map(r =>
      r.id === redactionId ? { ...r, x: rect.x, y: rect.y, width: rect.width, height: rect.height } : r
    ));
    try {
      await api.put(`/documents/${documentId}/redactions/${redactionId}/edit`, rect);
    } catch (err) {
      console.error('Failed to persist redaction resize', err);
      setErrorMessage('Could not save the new redaction size. Reloading to recover.');
      setShowError(true);
      // Re-fetch the doc's redactions to get back to a consistent state.
      try {
        const r = await api.get(`/documents/${documentId}/metadata`);
        const fresh = r.data?.redactions || [];
        setRedactions(prev => prev.map(red => {
          const match = fresh.find((f: any) => f.id === red.id);
          return match ? { ...red, x: match.x, y: match.y, width: match.width, height: match.height } : red;
        }));
      } catch (refetchErr) {
        console.error('Refetch after failed resize also failed', refetchErr);
      }
    }
  };

  // Closing the redaction menu used to also clear selectedRedactionIndex,
  // which removed the resize handles the moment the menu closed — making
  // them unreachable. Selection now persists across menu close so the
  // operator can grab handles or drag the box. Use handleDeselectRedaction
  // (or click a different box) to actually clear selection.
  const handleCloseRedactionMenu = () => {
    setRedactionMenuAnchor(null);
    setIsEditingRedaction(false);
  };

  const handleDeselectRedaction = () => {
    setSelectedRedactionIndex(null);
    setRedactionMenuAnchor(null);
    setIsEditingRedaction(false);
  };

  const handleStartEditRedaction = () => {
    if (selectedRedactionIndex === null) return;
    const redaction = redactions[selectedRedactionIndex];
    setEditedCategory(redaction?.reason?.categoryName || '');
    setEditedDescription(redaction?.reason?.notes || '');
    setIsEditingRedaction(true);
  };

  const handleCancelEditRedaction = () => {
    setIsEditingRedaction(false);
    setEditedCategory('');
    setEditedDescription('');
  };

  const handleSaveRedaction = async () => {
    if (selectedRedactionIndex === null) return;
    const redaction = redactions[selectedRedactionIndex];

    const updateData = {
      category: editedCategory,
      description: editedDescription
    };

    console.log('Updating redaction:', redaction.id);
    console.log('Update data:', updateData);

    try {
      // Update backend using the /edit endpoint
      const response = await api.put(`/documents/${documentId}/redactions/${redaction.id}/edit`, updateData);
      console.log('Update response:', response.data);

      // Update local state
      const updatedRedactions = [...redactions];
      updatedRedactions[selectedRedactionIndex] = {
        ...redaction,
        reason: {
          ...redaction.reason,
          categoryName: editedCategory,
          notes: editedDescription
        }
      };
      setRedactions(updatedRedactions);
      setIsEditingRedaction(false);
    } catch (error) {
      console.error('Failed to update redaction:', error);
      setErrorMessage('Failed to update redaction');
      setShowError(true);
    }
  };

  const handleDeleteRedaction = async () => {
    if (selectedRedactionIndex === null) return;

    const redactionToDelete = redactions[selectedRedactionIndex];

    // Need the redaction ID to delete from backend
    if (!redactionToDelete.id) {
      // If no ID, just remove locally
      setRedactions(redactions.filter((_, idx) => idx !== selectedRedactionIndex));
      handleDeselectRedaction();
      setErrorMessage('Redaction removed locally (no ID found).');
      setShowError(true);
      return;
    }

    try {
      // Delete from backend using redaction ID
      await api.delete(`/documents/${documentId}/redactions/${redactionToDelete.id}`);

      // Remove from local state
      setRedactions(redactions.filter((_, idx) => idx !== selectedRedactionIndex));

      handleDeselectRedaction();
    } catch (error: any) {
      console.error('Error deleting redaction:', error);
      const message = error.response?.data?.detail || 'Failed to delete redaction.';
      setErrorMessage(message);
      setShowError(true);
    }
  };

  const handleNavigateToMatch = (page: number, bbox: number[]) => {
    // Navigate to the page
    setCurrentPage(page);

    // Set the highlighted bbox (will be rendered as yellow highlight)
    setHighlightedMatchBbox(bbox);

    // Clear highlight after 2 seconds
    setTimeout(() => {
      setHighlightedMatchBbox(null);
    }, 2000);
  };

  return (
    <Box className="viewer-shell">
      {/* Top Bar */}
      <AppBar position="static" color="default" elevation={1}>
        <Toolbar variant="dense">
          {/* Left Section */}
          <Tooltip title="Back to Documents">
            <IconButton edge="start" onClick={handleBack} size="small">
              <ArrowBack />
            </IconButton>
          </Tooltip>

          <Typography variant="subtitle1" sx={{ ml: 2, mr: 'auto', maxWidth: '300px' }} noWrap>
            {documentMeta?.filename || 'Loading...'}
          </Typography>

          {/* Center Section - Document Controls */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mx: 'auto' }}>
            {/* Undo/Redo Group */}
            <Box sx={{ display: 'flex', gap: 0.5, borderRight: '1px solid var(--border-default)', pr: 2 }}>
              <Button
                size="small"
                onClick={handleUndo}
                disabled={undoStack.length === 0}
                sx={{
                  minWidth: '60px',
                  flexDirection: 'column',
                  py: 0.5,
                  color: 'var(--text-secondary)',
                  '&:hover': { bgcolor: 'var(--bg-tertiary)' }
                }}
              >
                <Undo sx={{ fontSize: 20, mb: 0.3 }} />
                <Typography variant="caption" sx={{ fontSize: '10px', textTransform: 'none' }}>
                  Undo
                </Typography>
              </Button>

              <Button
                size="small"
                onClick={handleRedo}
                disabled={redoStack.length === 0}
                sx={{
                  minWidth: '60px',
                  flexDirection: 'column',
                  py: 0.5,
                  color: 'var(--text-secondary)',
                  '&:hover': { bgcolor: 'var(--bg-tertiary)' }
                }}
              >
                <Redo sx={{ fontSize: 20, mb: 0.3 }} />
                <Typography variant="caption" sx={{ fontSize: '10px', textTransform: 'none' }}>
                  Redo
                </Typography>
              </Button>
            </Box>

            {/* Zoom Controls */}
            <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', borderLeft: '1px solid var(--border-default)', pl: 2 }}>
              <IconButton
                size="small"
                onClick={handleZoomOut}
                sx={{ color: 'var(--text-secondary)' }}
              >
                <ZoomOut sx={{ fontSize: 20 }} />
              </IconButton>

              <Typography variant="body2" sx={{ minWidth: '50px', textAlign: 'center', color: 'var(--text-primary)' }}>
                {Math.round(zoom * 100)}%
              </Typography>

              <IconButton
                size="small"
                onClick={handleZoomIn}
                sx={{ color: 'var(--text-secondary)' }}
              >
                <ZoomIn sx={{ fontSize: 20 }} />
              </IconButton>
            </Box>

            <Menu
              anchorEl={zoomAnchorEl}
              open={Boolean(zoomAnchorEl)}
              onClose={() => setZoomAnchorEl(null)}
            >
              {ZOOM_LEVELS.map((level) => (
                <MenuItem
                  key={level}
                  selected={level === zoom}
                  onClick={() => handleZoomSelect(level)}
                >
                  {Math.round(level * 100)}%
                </MenuItem>
              ))}
            </Menu>

            {/* Page Navigation */}
            <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', borderLeft: '1px solid var(--border-default)', pl: 2 }}>
              <IconButton
                size="small"
                onClick={handleFirstPage}
                disabled={currentPage === 1}
                sx={{ color: 'var(--text-secondary)' }}
              >
                <FirstPage sx={{ fontSize: 18 }} />
              </IconButton>

              <IconButton
                size="small"
                onClick={handlePreviousPage}
                disabled={currentPage === 1}
                sx={{ color: 'var(--text-secondary)' }}
              >
                <ChevronLeft sx={{ fontSize: 18 }} />
              </IconButton>

              <Typography variant="body2" sx={{ mx: 1, color: 'var(--text-primary)', fontSize: '13px' }}>
                {currentPage} of {numPages}
              </Typography>

              <IconButton
                size="small"
                onClick={handleNextPage}
                disabled={currentPage === numPages}
                sx={{ color: 'var(--text-secondary)' }}
              >
                <ChevronRight sx={{ fontSize: 18 }} />
              </IconButton>

              <IconButton
                size="small"
                onClick={handleLastPage}
                disabled={currentPage === numPages}
                sx={{ color: 'var(--text-secondary)' }}
              >
                <LastPage sx={{ fontSize: 18 }} />
              </IconButton>
            </Box>
          </Box>

          {/* Right Section */}
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Share Document">
              <IconButton size="small" sx={{ color: 'var(--text-secondary)' }}>
                <Share sx={{ fontSize: 20 }} />
              </IconButton>
            </Tooltip>

            <Tooltip title="Bates Numbering">
              <IconButton size="small" sx={{ color: 'var(--text-secondary)' }}>
                <FormatListNumbered sx={{ fontSize: 20 }} />
              </IconButton>
            </Tooltip>

            <Tooltip title="Help">
              <IconButton size="small" sx={{ color: 'var(--text-secondary)' }}>
                <Help sx={{ fontSize: 20 }} />
              </IconButton>
            </Tooltip>
          </Box>
        </Toolbar>
      </AppBar>

      {/* Main Content Area */}
      <Box className="viewer-content" sx={{ display: 'flex', flexDirection: 'row', flex: 1, overflow: 'hidden' }}>
        {/* Thumbnails Rail (Left) */}
        {showThumbnails && (
          <ThumbnailsRail
            documentId={documentId}
            numPages={numPages}
            currentPage={currentPage}
            onPageClick={setCurrentPage}
            pdfUrl={pdfUrl}
          />
        )}

        {/* Left Tool Rail */}
        <LeftToolRail activeTool={activeTool} onToolChange={handleToolChange} />

        {/* Find & Replace Drawer */}
        {findReplaceOpen && (
          <Box sx={{ width: 400, flexShrink: 0, borderRight: '1px solid var(--border-default)' }}>
            <FindReplaceDrawer
              open={findReplaceOpen}
              onClose={() => handleToolChange('select')}
              documentId={documentId}
              onRedactMatches={handleRedactMatches}
              onNavigateToMatch={handleNavigateToMatch}
            />
          </Box>
        )}

        {/* PDF Canvas (Center) */}
        <Box className="pdf-canvas-container" onWheel={handleScroll} sx={{ flex: 1, overflow: 'auto' }}>
          <Box sx={{
            opacity: pageTransitioning ? 0.3 : 1,
            transition: 'opacity 150ms ease-in-out',
            position: 'relative'
          }}>
            <PDFViewerWithSelection
              documentId={documentId}
              currentPage={currentPage}
              zoom={zoom}
              onNumPagesChange={setNumPages}
              pdfUrl={pdfUrl}
              redactions={redactions.filter(r => r.page === currentPage)}
              suggestions={suggestions.filter(s => s.page === currentPage)}
              onSuggestionAccept={handleAcceptSuggestion}
              onSuggestionReject={handleRejectSuggestion}
              onTextSelected={activeTool === 'select' ? handleMultipleRedactionsCreated : undefined}
              onRedactionClick={handleRedactionClick}
              onRedactionResize={handleRedactionResize}
              selectedRedactionIndex={selectedRedactionIndex}
              highlightedMatchBbox={highlightedMatchBbox}
              showRedactionPreview={showRedactionPreview}
            />
          </Box>

          {/* Manual Redaction Tool Overlay - Not used in current workflow */}
          {/* Select tool uses native text selection instead */}
          {manualRedactionEnabled && (
            <ManualRedactionTool
              enabled={manualRedactionEnabled}
              pageData={getCurrentPageData()}
              zoom={zoom}
              onRedactionCreated={handleRedactionCreated}
              onDisable={() => handleToolChange('select')}
            />
          )}

          {/* Draw Redaction Tool Overlay */}
          <DrawRedactionTool
            enabled={drawRedactionEnabled}
            zoom={zoom}
            onRedactionCreated={handleRedactionCreated}
            onDisable={() => handleToolChange('select')}
          />
        </Box>

        {/* Right Utility Bar */}
        <RightUtilityBar
          documentId={documentId}
          showRedactionPreview={showRedactionPreview}
          onTogglePreview={setShowRedactionPreview}
          onAutoSuggestClick={() => setAutoSuggestOpen(true)}
          onHistoryClick={() => setHistoryOpen(true)}
          onCommentsClick={() => setCommentsOpen(true)}
        />
      </Box>

      {/* Reason Picker Modal */}
      <ReasonPickerModal
        open={reasonPickerOpen}
        redactionText={pendingRedaction?.text || ''}
        onClose={() => setReasonPickerOpen(false)}
        onSave={handleReasonSave}
      />

      {/* Auto Suggest Drawer */}
      <AutoSuggestDrawer
        open={autoSuggestOpen}
        onClose={() => {
          setAutoSuggestOpen(false);
          // Refresh suggestions when drawer closes in case user applied some
          fetchSuggestions();
        }}
        documentId={documentId}
        onApplySuggestions={handleApplySuggestions}
        existingRedactions={redactions}
        onNavigateToPage={(page) => setCurrentPage(page)}
      />

      {/* History Drawer */}
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        documentId={documentId}
      />

      {/* Comments Drawer */}
      <CommentsDrawer
        open={commentsOpen}
        onClose={() => setCommentsOpen(false)}
        documentId={documentId}
      />

      {/* Redaction Control Box */}
      {selectedRedactionIndex !== null && redactionMenuAnchor && (
        <Popover
          open={true}
          onClose={handleCloseRedactionMenu}
          anchorReference="anchorPosition"
          anchorPosition={{ top: redactionMenuAnchor.y, left: redactionMenuAnchor.x }}
          anchorOrigin={{
            vertical: 'bottom',
            horizontal: 'left',
          }}
          transformOrigin={{
            vertical: 'top',
            horizontal: 'left',
          }}
        >
          <Card sx={{ minWidth: 300, maxWidth: 400, bgcolor: 'white' }}>
            <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                  Redaction Details
                </Typography>
                {!isEditingRedaction && (
                  <IconButton size="small" onClick={handleStartEditRedaction}>
                    <Edit fontSize="small" />
                  </IconButton>
                )}
              </Box>

              {(() => {
                const redaction = redactions[selectedRedactionIndex];
                return (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                    {/* Category */}
                    <Box>
                      <Typography variant="caption" sx={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
                        Category
                      </Typography>
                      {isEditingRedaction ? (
                        <TextField
                          fullWidth
                          size="small"
                          value={editedCategory}
                          onChange={(e) => setEditedCategory(e.target.value)}
                          sx={{ mt: 0.5 }}
                        />
                      ) : (
                        <Typography variant="body2" sx={{ color: 'var(--text-primary)' }}>
                          {redaction?.reason?.categoryName || 'No category specified'}
                        </Typography>
                      )}
                    </Box>

                    {/* Description/Notes */}
                    <Box>
                      <Typography variant="caption" sx={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
                        Description
                      </Typography>
                      {isEditingRedaction ? (
                        <TextField
                          fullWidth
                          multiline
                          rows={3}
                          size="small"
                          value={editedDescription}
                          onChange={(e) => setEditedDescription(e.target.value)}
                          sx={{ mt: 0.5 }}
                        />
                      ) : (
                        <Typography variant="body2" sx={{ color: 'var(--text-primary)' }}>
                          {redaction?.reason?.notes || 'No description'}
                        </Typography>
                      )}
                    </Box>

                    {/* Created By */}
                    {redaction?.createdBy && (
                      <Box>
                        <Typography variant="caption" sx={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
                          Created By
                        </Typography>
                        <Typography variant="body2" sx={{ color: 'var(--text-primary)' }}>
                          {redaction.createdBy}
                          {redaction.createdByRole && ` (${redaction.createdByRole})`}
                        </Typography>
                      </Box>
                    )}

                    {/* Timestamp */}
                    {redaction?.createdAt && (
                      <Box>
                        <Typography variant="caption" sx={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
                          Created At
                        </Typography>
                        <Typography variant="body2" sx={{ color: 'var(--text-primary)' }}>
                          {new Date(redaction.createdAt).toLocaleString()}
                        </Typography>
                      </Box>
                    )}

                    {/* Status */}
                    {redaction?.status && (
                      <Box>
                        <Typography variant="caption" sx={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
                          Status
                        </Typography>
                        <Typography
                          variant="body2"
                          sx={{
                            color: redaction.status === 'approved' ? '#10b981' : '#f59e0b',
                            textTransform: 'capitalize'
                          }}
                        >
                          {redaction.status}
                        </Typography>
                      </Box>
                    )}

                    {/* Action Buttons */}
                    {isEditingRedaction ? (
                      <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
                        <Button
                          fullWidth
                          variant="contained"
                          startIcon={<Save />}
                          onClick={handleSaveRedaction}
                          sx={{ textTransform: 'none' }}
                        >
                          Save
                        </Button>
                        <Button
                          fullWidth
                          variant="outlined"
                          startIcon={<Close />}
                          onClick={handleCancelEditRedaction}
                          sx={{ textTransform: 'none' }}
                        >
                          Cancel
                        </Button>
                      </Box>
                    ) : (
                      <Button
                        fullWidth
                        variant="outlined"
                        color="error"
                        startIcon={<Delete />}
                        onClick={handleDeleteRedaction}
                        sx={{
                          mt: 1,
                          textTransform: 'none',
                          borderColor: '#ef4444',
                          color: '#ef4444',
                          '&:hover': {
                            borderColor: '#dc2626',
                            bgcolor: '#fef2f2'
                          }
                        }}
                      >
                        Delete Redaction
                      </Button>
                    )}
                  </Box>
                );
              })()}
            </CardContent>
          </Card>
        </Popover>
      )}

      {/* Error Snackbar */}
      <Snackbar
        open={showError}
        autoHideDuration={6000}
        onClose={() => setShowError(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setShowError(false)}
          severity="error"
          sx={{ width: '100%' }}
        >
          {errorMessage}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default ViewerShell;
