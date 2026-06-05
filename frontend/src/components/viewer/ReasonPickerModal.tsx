// frontend/src/components/viewer/ReasonPickerModal.tsx
import React, { useState, useEffect } from 'react';
// MUI v7 default imports
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import FormControl from '@mui/material/FormControl';
import FormLabel from '@mui/material/FormLabel';
import TextField from '@mui/material/TextField';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';
import Chip from '@mui/material/Chip';
import Autocomplete from '@mui/material/Autocomplete';
import api from '../../api/client';
import './ReasonPickerModal.css';

interface Props {
  open: boolean;
  redactionText: string;
  onClose: () => void;
  onSave: (reason: RedactionReason) => void;
}

export interface RedactionReason {
  categoryId?: string;
  categoryCode?: string;
  categoryName?: string;
  section?: string;
  sections?: string[];  // Multiple sections
  primarySection?: string;  // Primary section
  notes?: string;
}

interface RedactionCategory {
  id: string;
  code: string;
  name: string;
  section: string;
  description: string;
  color: string;
  guidance?: string;
}

interface ExemptionSection {
  code: string;
  name: string;
  description: string;
  category_id?: string;
}

const ReasonPickerModal: React.FC<Props> = ({
  open,
  redactionText,
  onClose,
  onSave
}) => {
  const [sections, setSections] = useState<ExemptionSection[]>([]);
  const [selectedSections, setSelectedSections] = useState<ExemptionSection[]>([]);
  const [primarySection, setPrimarySection] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [inputValue, setInputValue] = useState<string>('');

  useEffect(() => {
    if (open) {
      fetchSections();
    }
  }, [open]);

  const fetchSections = async () => {
    try {
      setLoading(true);
      // Fetch sections from active pack
      const response = await api.get('/packs/active/sections');
      setSections(response.data.sections || []);
    } catch (error) {
      console.error('Error fetching sections:', error);
      setError('Failed to load exemption sections');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = () => {
    // Validation: Must have at least one section selected
    if (selectedSections.length === 0) {
      setError('You must select at least one exemption section.');
      return;
    }

    const primary = primarySection || selectedSections[0].code;
    const primarySectionData = selectedSections.find(s => s.code === primary) || selectedSections[0];

    const reason: RedactionReason = {
      categoryId: primarySectionData.category_id,
      categoryCode: primarySectionData.code,
      categoryName: primarySectionData.name,
      section: primarySectionData.code,
      sections: selectedSections.map(s => s.code),
      primarySection: primary,
      notes: notes || undefined
    };

    onSave(reason);
    handleClose();
  };

  const handleClose = () => {
    // Reset form
    setSelectedSections([]);
    setPrimarySection('');
    setNotes('');
    setInputValue('');
    setError('');
    onClose();
  };

  const handleSectionChange = (event: any, newValue: ExemptionSection[]) => {
    setSelectedSections(newValue);
    // If primary is removed, set first as primary
    if (primarySection && !newValue.find(s => s.code === primarySection)) {
      setPrimarySection(newValue[0]?.code || '');
    }
    // If no primary and we have sections, set first as primary
    if (!primarySection && newValue.length > 0) {
      setPrimarySection(newValue[0].code);
    }
  };

  const handleSetPrimary = (code: string) => {
    setPrimarySection(code);
  };

  const isValid = selectedSections.length > 0;

  const filteredSections = inputValue
    ? sections.filter(s =>
        s.code.toLowerCase().includes(inputValue.toLowerCase()) ||
        s.name.toLowerCase().includes(inputValue.toLowerCase()) ||
        s.description.toLowerCase().includes(inputValue.toLowerCase())
      )
    : sections;

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="md"
      fullWidth
      className="reason-picker-modal"
    >
      <DialogTitle>Add Redaction Reason</DialogTitle>
      
      <DialogContent dividers>
        <Typography variant="subtitle2" gutterBottom>
          Select exemption section(s) for this redaction
        </Typography>

        <Box sx={{ mb: 2 }}>
          <Typography variant="caption" color="textSecondary">
            Selected text: "{redactionText.substring(0, 100)}{redactionText.length > 100 ? '...' : ''}"
          </Typography>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
            <Typography>Loading sections...</Typography>
          </Box>
        ) : (
          <>
            {/* Multi-Section Selection */}
            <Box sx={{ mb: 3 }}>
              <FormLabel sx={{ mb: 1 }}>Exemption Section(s) *</FormLabel>
              <Autocomplete
                multiple
                options={sections}
                value={selectedSections}
                onChange={handleSectionChange}
                inputValue={inputValue}
                onInputChange={(event, newInputValue) => setInputValue(newInputValue)}
                getOptionLabel={(option) => `${option.code} - ${option.name}`}
                isOptionEqualToValue={(option, value) => option.code === value.code}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    placeholder="Search sections..."
                    variant="outlined"
                  />
                )}
                renderTags={(value, getTagProps) =>
                  value.map((option, index) => (
                    <Chip
                      {...getTagProps({ index })}
                      key={option.code}
                      label={option.code}
                      color={option.code === primarySection ? 'primary' : 'default'}
                      onClick={() => handleSetPrimary(option.code)}
                      title={option.code === primarySection ? 'Primary section' : 'Click to set as primary'}
                    />
                  ))
                }
                renderOption={(props, option) => (
                  <li {...props} key={option.code}>
                    <Box>
                      <Typography variant="body2" fontWeight={500}>
                        {option.code} - {option.name}
                      </Typography>
                      <Typography variant="caption" color="textSecondary">
                        {option.description}
                      </Typography>
                    </Box>
                  </li>
                )}
              />
              {selectedSections.length === 0 && (
                <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>
                  You must select at least one exemption section
                </Typography>
              )}
              {selectedSections.length > 1 && (
                <Typography variant="caption" color="textSecondary" sx={{ mt: 1, display: 'block' }}>
                  Click a section chip to set it as the primary section. Primary: <strong>{primarySection}</strong>
                </Typography>
              )}
            </Box>

            {/* Selected Section Details */}
            {selectedSections.length > 0 && (
              <Box sx={{ mb: 3, p: 2, bgcolor: '#f5f5f5', borderRadius: 1 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Selected Sections:
                </Typography>
                {selectedSections.map((section) => (
                  <Box key={section.code} sx={{ mb: 1 }}>
                    <Typography variant="body2" fontWeight={section.code === primarySection ? 600 : 400}>
                      {section.code === primarySection && '★ '}{section.code}: {section.name}
                    </Typography>
                    <Typography variant="caption" color="textSecondary" sx={{ pl: 2 }}>
                      {section.description}
                    </Typography>
                  </Box>
                ))}
              </Box>
            )}

            {/* Notes */}
            <Box>
              <FormLabel sx={{ mb: 1 }}>Additional Notes (optional)</FormLabel>
              <TextField
                fullWidth
                multiline
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Add any additional context or notes..."
              />
            </Box>
          </>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={handleClose}>
          Cancel
        </Button>
        <Button
          onClick={handleSave}
          variant="contained"
          disabled={!isValid}
        >
          Add Reason
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ReasonPickerModal;
