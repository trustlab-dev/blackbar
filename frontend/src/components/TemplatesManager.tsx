import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  IconButton,
  Chip,
  Alert,
  Tooltip
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import InfoIcon from '@mui/icons-material/Info';
import api from '../api/client';

interface Template {
  id: string;
  name: string;
  description: string;
  content: string;
  category: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface Variable {
  name: string;
  description: string;
}

const TemplatesManager: React.FC = () => {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [variables, setVariables] = useState<Variable[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [variablesDialogOpen, setVariablesDialogOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<Template | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    content: '',
    category: 'general',
    is_active: true
  });

  useEffect(() => {
    fetchTemplates();
    fetchVariables();
  }, []);

  const fetchTemplates = async () => {
    try {
      setLoading(true);
      const response = await api.get('/templates/', {
        params: { active_only: false }
      });
      setTemplates(response.data);
    } catch (error) {
      console.error('Error fetching templates:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchVariables = async () => {
    try {
      const response = await api.get('/templates/available-variables/list');
      setVariables(response.data.variables);
    } catch (error) {
      console.error('Error fetching variables:', error);
    }
  };

  const handleOpenDialog = (template?: Template) => {
    if (template) {
      setEditingTemplate(template);
      setFormData({
        name: template.name,
        description: template.description || '',
        content: template.content,
        category: template.category,
        is_active: template.is_active
      });
    } else {
      setEditingTemplate(null);
      setFormData({
        name: '',
        description: '',
        content: '',
        category: 'general',
        is_active: true
      });
    }
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setEditingTemplate(null);
  };

  const handleSave = async () => {
    try {
      if (editingTemplate) {
        await api.put(`/templates/${editingTemplate.id}`, formData);
      } else {
        await api.post('/templates/', formData);
      }
      await fetchTemplates();
      handleCloseDialog();
    } catch (error) {
      console.error('Error saving template:', error);
    }
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this template?')) {
      try {
        await api.delete(`/templates/${id}`);
        await fetchTemplates();
      } catch (error) {
        console.error('Error deleting template:', error);
      }
    }
  };

  const insertVariable = (variableName: string) => {
    const textarea = document.getElementById('template-content') as HTMLTextAreaElement;
    if (textarea) {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const scrollTop = textarea.scrollTop; // Save scroll position
      const content = formData.content;
      const newContent = content.substring(0, start) + variableName + content.substring(end);
      setFormData({ ...formData, content: newContent });
      
      // Restore cursor position and scroll after state update
      setTimeout(() => {
        textarea.scrollTop = scrollTop; // Restore scroll position
        textarea.focus();
        textarea.setSelectionRange(start + variableName.length, start + variableName.length);
      }, 0);
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Message Templates</Typography>
        <Box sx={{ display: 'flex', gap: 2 }}>
          <Button
            variant="outlined"
            startIcon={<InfoIcon />}
            onClick={() => setVariablesDialogOpen(true)}
          >
            View Available Variables
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => handleOpenDialog()}
          >
            Create Template
          </Button>
        </Box>
      </Box>

      <Alert severity="info" sx={{ mb: 3 }}>
        Templates can use variables like {'{requester_name}'}, {'{case_number}'}, etc. 
        Click "View Available Variables" to see all options.
      </Alert>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Category</TableCell>
              <TableCell>Description</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Last Updated</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {templates.map((template) => (
              <TableRow key={template.id}>
                <TableCell>{template.name}</TableCell>
                <TableCell>
                  <Chip label={template.category} size="small" />
                </TableCell>
                <TableCell>{template.description}</TableCell>
                <TableCell>
                  <Chip
                    label={template.is_active ? 'Active' : 'Inactive'}
                    color={template.is_active ? 'success' : 'default'}
                    size="small"
                  />
                </TableCell>
                <TableCell>
                  {new Date(template.updated_at).toLocaleDateString()}
                </TableCell>
                <TableCell align="right">
                  <Tooltip title="Edit">
                    <IconButton
                      size="small"
                      onClick={() => handleOpenDialog(template)}
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Delete">
                    <IconButton
                      size="small"
                      onClick={() => handleDelete(template.id)}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
            {templates.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={6} align="center">
                  No templates found. Create your first template to get started.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Template Editor Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={handleCloseDialog}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          {editingTemplate ? 'Edit Template' : 'Create New Template'}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
            <TextField
              label="Template Name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              fullWidth
              required
            />

            <FormControl fullWidth>
              <InputLabel>Category</InputLabel>
              <Select
                value={formData.category}
                label="Category"
                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
              >
                <MenuItem value="general">General</MenuItem>
                <MenuItem value="response_letter">Response Letter</MenuItem>
                <MenuItem value="status_update">Status Update</MenuItem>
                <MenuItem value="acknowledgment">Acknowledgment</MenuItem>
                <MenuItem value="extension">Extension Notice</MenuItem>
                <MenuItem value="closure">Case Closure</MenuItem>
              </Select>
            </FormControl>

            <TextField
              label="Description"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              fullWidth
              multiline
              rows={2}
            />

            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Template Content
              </Typography>
              <Box sx={{ mb: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                {variables.slice(0, 8).map((variable) => (
                  <Chip
                    key={variable.name}
                    label={variable.name}
                    size="small"
                    onClick={() => insertVariable(variable.name)}
                    sx={{ cursor: 'pointer' }}
                  />
                ))}
                <Chip
                  label="View All..."
                  size="small"
                  onClick={() => setVariablesDialogOpen(true)}
                  sx={{ cursor: 'pointer' }}
                  variant="outlined"
                />
              </Box>
              <TextField
                id="template-content"
                value={formData.content}
                onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                fullWidth
                multiline
                rows={12}
                required
                placeholder="Enter your template content here. Click on variable chips above to insert them."
                sx={{
                  '& .MuiInputBase-root': {
                    fontFamily: 'monospace',
                    fontSize: '0.9rem'
                  }
                }}
              />
            </Box>

            <FormControl component="fieldset">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Typography>Status:</Typography>
                <Select
                  value={formData.is_active ? 'active' : 'inactive'}
                  onChange={(e) =>
                    setFormData({ ...formData, is_active: e.target.value === 'active' })
                  }
                  size="small"
                >
                  <MenuItem value="active">Active</MenuItem>
                  <MenuItem value="inactive">Inactive</MenuItem>
                </Select>
              </Box>
            </FormControl>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            onClick={handleSave}
            variant="contained"
            disabled={!formData.name || !formData.content}
          >
            {editingTemplate ? 'Save Changes' : 'Create Template'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Available Variables Dialog */}
      <Dialog
        open={variablesDialogOpen}
        onClose={() => setVariablesDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Available Template Variables</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            Click on any variable to copy it to your clipboard
          </Alert>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Variable</TableCell>
                  <TableCell>Description</TableCell>
                  <TableCell align="right">Action</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {variables.map((variable) => (
                  <TableRow key={variable.name}>
                    <TableCell>
                      <code style={{ backgroundColor: '#f5f5f5', padding: '2px 6px', borderRadius: '4px' }}>
                        {variable.name}
                      </code>
                    </TableCell>
                    <TableCell>{variable.description}</TableCell>
                    <TableCell align="right">
                      <Tooltip title="Copy to clipboard">
                        <IconButton
                          size="small"
                          onClick={() => {
                            navigator.clipboard.writeText(variable.name);
                          }}
                        >
                          <ContentCopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVariablesDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TemplatesManager;
