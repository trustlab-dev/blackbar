/**
 * Section Picker Component.
 *
 * Allows selecting multiple exemption sections for a redaction.
 * Supports autocomplete search and displays section descriptions.
 */
import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import Chip from '@mui/material/Chip';
import Autocomplete from '@mui/material/Autocomplete';
import Typography from '@mui/material/Typography';
import CircularProgress from '@mui/material/CircularProgress';
import Paper from '@mui/material/Paper';
import { sectionsApi, ExemptionSection } from '../../api/workflowApi';

interface SectionPickerProps {
  selectedSections: string[];
  primarySection?: string;
  onChange: (sections: string[], primarySection?: string) => void;
  disabled?: boolean;
  label?: string;
  placeholder?: string;
}

const SectionPicker: React.FC<SectionPickerProps> = ({
  selectedSections,
  primarySection,
  onChange,
  disabled = false,
  label = 'Exemption Sections',
  placeholder = 'Search sections...'
}) => {
  const [sections, setSections] = useState<ExemptionSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [inputValue, setInputValue] = useState('');

  useEffect(() => {
    fetchSections();
  }, []);

  const fetchSections = async (query?: string) => {
    try {
      setLoading(true);
      const result = await sectionsApi.search(query);
      setSections(result.sections);
    } catch (err) {
      console.error('Failed to load sections:', err);
      setSections([]);
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (event: any, newValue: ExemptionSection[]) => {
    const newCodes = newValue.map(s => s.code);
    // If primary section is removed, set first remaining as primary
    let newPrimary = primarySection;
    if (primarySection && !newCodes.includes(primarySection)) {
      newPrimary = newCodes[0] || undefined;
    }
    // If no primary and we have sections, set first as primary
    if (!newPrimary && newCodes.length > 0) {
      newPrimary = newCodes[0];
    }
    onChange(newCodes, newPrimary);
  };

  const handleSetPrimary = (code: string) => {
    onChange(selectedSections, code);
  };

  const getSelectedSectionObjects = (): ExemptionSection[] => {
    return selectedSections
      .map(code => sections.find(s => s.code === code))
      .filter((s): s is ExemptionSection => s !== undefined);
  };

  return (
    <Box>
      <Autocomplete
        multiple
        options={sections}
        value={getSelectedSectionObjects()}
        onChange={handleChange}
        inputValue={inputValue}
        onInputChange={(event, newInputValue) => {
          setInputValue(newInputValue);
        }}
        getOptionLabel={(option) => `${option.code} - ${option.name}`}
        isOptionEqualToValue={(option, value) => option.code === value.code}
        loading={loading}
        disabled={disabled}
        renderInput={(params) => (
          <TextField
            {...params}
            label={label}
            placeholder={selectedSections.length === 0 ? placeholder : ''}
            InputProps={{
              ...params.InputProps,
              endAdornment: (
                <>
                  {loading ? <CircularProgress color="inherit" size={20} /> : null}
                  {params.InputProps.endAdornment}
                </>
              ),
            }}
          />
        )}
        renderOption={(props, option) => (
          <li {...props} key={option.code}>
            <Box>
              <Typography variant="body2" fontWeight={500}>
                {option.code}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {option.name}
              </Typography>
              {option.description && (
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                  {option.description.substring(0, 100)}
                  {option.description.length > 100 ? '...' : ''}
                </Typography>
              )}
            </Box>
          </li>
        )}
        renderTags={(value, getTagProps) =>
          value.map((option, index) => (
            <Chip
              {...getTagProps({ index })}
              key={option.code}
              label={option.code}
              size="small"
              color={option.code === primarySection ? 'primary' : 'default'}
              onClick={() => handleSetPrimary(option.code)}
              title={option.code === primarySection ? 'Primary section' : 'Click to set as primary'}
            />
          ))
        }
        PaperComponent={(props) => (
          <Paper {...props} elevation={8} />
        )}
      />
      {selectedSections.length > 1 && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
          Click a section chip to set it as primary. Primary: <strong>{primarySection}</strong>
        </Typography>
      )}
    </Box>
  );
};

export default SectionPicker;
