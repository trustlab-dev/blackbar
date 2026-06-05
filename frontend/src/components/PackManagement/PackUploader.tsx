import React, { useState } from 'react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Alert from '@mui/material/Alert';
import LinearProgress from '@mui/material/LinearProgress';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';
import api from '../../api/client';

interface PackUploaderProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const PackUploader: React.FC<PackUploaderProps> = ({ open, onClose, onSuccess }) => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;

    if (!selectedFile.name.endsWith('.json')) {
      setError('Please select a JSON file');
      return;
    }

    setFile(selectedFile);
    setError(null);
    setValidation(null);

    // Validate the file
    try {
      setValidating(true);
      const text = await selectedFile.text();
      const packData = JSON.parse(text);

      const response = await api.post('/packs/validate', packData);
      setValidation(response.data);
    } catch (err: any) {
      if (err instanceof SyntaxError) {
        setError('Invalid JSON file');
      } else {
        setError(err.response?.data?.detail || 'Validation failed');
      }
    } finally {
      setValidating(false);
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    try {
      setUploading(true);
      setError(null);

      const formData = new FormData();
      formData.append('file', file);

      // Let axios derive the multipart Content-Type (with boundary) from the
      // FormData body. Setting the header by hand omits the boundary and
      // produces a malformed request (see audit Section 11 FE-F5).
      const response = await api.post('/packs/upload', formData);

      if (response.data.success) {
        onSuccess();
        handleClose();
      } else {
        setError(response.data.message || 'Upload failed');
      }
    } catch (err: any) {
      console.error('Error uploading pack:', err);
      setError(err.response?.data?.detail || 'Failed to upload pack');
    } finally {
      setUploading(false);
    }
  };

  const handleClose = () => {
    setFile(null);
    setValidation(null);
    setError(null);
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Upload Jurisdiction Pack</DialogTitle>

      <DialogContent>
        <Typography variant="body2" color="textSecondary" paragraph>
          Upload a custom jurisdiction pack JSON file. The pack will be validated before upload.
        </Typography>

        <Box
          sx={{
            border: '2px dashed #ccc',
            borderRadius: 2,
            p: 3,
            textAlign: 'center',
            bgcolor: '#f9f9f9',
            cursor: 'pointer',
            '&:hover': {
              bgcolor: '#f0f0f0'
            }
          }}
          onClick={() => document.getElementById('pack-file-input')?.click()}
        >
          <CloudUploadIcon sx={{ fontSize: 48, color: '#999', mb: 1 }} />
          <Typography variant="body1" gutterBottom>
            {file ? file.name : 'Click to select a pack file'}
          </Typography>
          <Typography variant="caption" color="textSecondary">
            JSON files only
          </Typography>
          <input
            id="pack-file-input"
            type="file"
            accept=".json"
            style={{ display: 'none' }}
            onChange={handleFileChange}
          />
        </Box>

        {validating && (
          <Box mt={2}>
            <Typography variant="body2" gutterBottom>Validating pack...</Typography>
            <LinearProgress />
          </Box>
        )}

        {validation && (
          <Box mt={2}>
            {validation.valid ? (
              <Alert severity="success" icon={<CheckCircleIcon />}>
                <Typography variant="body2">
                  <strong>Pack is valid!</strong>
                </Typography>
                <Typography variant="caption" display="block">
                  {validation.pack_name} (v{validation.pack_id})
                </Typography>
              </Alert>
            ) : (
              <Alert severity="error" icon={<ErrorIcon />}>
                <Typography variant="body2">
                  <strong>Validation failed</strong>
                </Typography>
              </Alert>
            )}

            {validation.errors && validation.errors.length > 0 && (
              <Box mt={1}>
                <Typography variant="caption" color="error" display="block" gutterBottom>
                  <strong>Errors:</strong>
                </Typography>
                <List dense>
                  {validation.errors.map((err: string, index: number) => (
                    <ListItem key={index}>
                      <ListItemIcon sx={{ minWidth: 32 }}>
                        <ErrorIcon color="error" fontSize="small" />
                      </ListItemIcon>
                      <ListItemText 
                        primary={err}
                        primaryTypographyProps={{ variant: 'caption' }}
                      />
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}

            {validation.warnings && validation.warnings.length > 0 && (
              <Box mt={1}>
                <Typography variant="caption" color="warning.main" display="block" gutterBottom>
                  <strong>Warnings:</strong>
                </Typography>
                <List dense>
                  {validation.warnings.map((warning: string, index: number) => (
                    <ListItem key={index}>
                      <ListItemIcon sx={{ minWidth: 32 }}>
                        <WarningIcon color="warning" fontSize="small" />
                      </ListItemIcon>
                      <ListItemText 
                        primary={warning}
                        primaryTypographyProps={{ variant: 'caption' }}
                      />
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}

        {uploading && (
          <Box mt={2}>
            <Typography variant="body2" gutterBottom>Uploading pack...</Typography>
            <LinearProgress />
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={handleClose} disabled={uploading}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleUpload}
          disabled={!file || !validation?.valid || uploading}
          startIcon={uploading ? null : <CloudUploadIcon />}
        >
          {uploading ? 'Uploading...' : 'Upload Pack'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default PackUploader;
