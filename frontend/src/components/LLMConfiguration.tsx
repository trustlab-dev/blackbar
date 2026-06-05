import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  CircularProgress,
  Tooltip
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import StarIcon from '@mui/icons-material/Star';
import TestIcon from '@mui/icons-material/PlayArrow';
import SuccessIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import api from '../api/client';

interface LLMConfigData {
  id: string;
  name: string;
  enabled: boolean;
  api_endpoint: string;
  model_name: string;
  request_format: string;
  default_settings: {
    temperature: number;
    max_tokens: number;
    top_p: number;
  };
  notes?: string;
  created_at: string;
}

const LLMConfiguration: React.FC = () => {
  const [configs, setConfigs] = useState<LLMConfigData[]>([]);
  const [defaultLLM, setDefaultLLM] = useState<LLMConfigData | null>(null);
  const [loading, setLoading] = useState(true);
  const [openDialog, setOpenDialog] = useState(false);
  const [editingConfig, setEditingConfig] = useState<LLMConfigData | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({});
  const [testing, setTesting] = useState<Record<string, boolean>>({});

  const [formData, setFormData] = useState({
    name: '',
    api_endpoint: '',
    api_key: '',
    model_name: '',
    request_format: 'openai',
    temperature: 0.7,
    max_tokens: 4000,
    top_p: 1.0,
    notes: '',
    enabled: true
  });

  useEffect(() => {
    fetchConfigs();
    fetchDefaultLLM();
  }, []);

  const fetchConfigs = async () => {
    try {
      const response = await api.get('/llm/configs');
      setConfigs(response.data);
    } catch (error) {
      console.error('Error fetching LLM configs:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchDefaultLLM = async () => {
    try {
      const response = await api.get('/llm/default');
      setDefaultLLM(response.data);
    } catch (error) {
      // No default set yet
    }
  };

  const handleOpenDialog = (config?: LLMConfigData) => {
    if (config) {
      setEditingConfig(config);
      setFormData({
        name: config.name,
        api_endpoint: config.api_endpoint,
        api_key: '',
        model_name: config.model_name,
        request_format: config.request_format,
        temperature: config.default_settings.temperature,
        max_tokens: config.default_settings.max_tokens,
        top_p: config.default_settings.top_p,
        notes: config.notes || '',
        enabled: config.enabled
      });
    } else {
      setEditingConfig(null);
      setFormData({
        name: '',
        api_endpoint: '',
        api_key: '',
        model_name: '',
        request_format: 'openai',
        temperature: 0.7,
        max_tokens: 4000,
        top_p: 1.0,
        notes: '',
        enabled: true
      });
    }
    setOpenDialog(true);
  };

  const handleCloseDialog = () => {
    setOpenDialog(false);
    setEditingConfig(null);
  };

  const handleSave = async () => {
    try {
      const payload = {
        name: formData.name,
        api_endpoint: formData.api_endpoint,
        model_name: formData.model_name,
        request_format: formData.request_format,
        default_settings: {
          temperature: formData.temperature,
          max_tokens: formData.max_tokens,
          top_p: formData.top_p
        },
        notes: formData.notes,
        enabled: formData.enabled,
        ...(formData.api_key && { api_key: formData.api_key })
      };

      if (editingConfig) {
        await api.put(`/llm/configs/${editingConfig.id}`, payload);
      } else {
        await api.post('/llm/configs', { ...payload, api_key: formData.api_key });
      }

      fetchConfigs();
      // The backend auto-promotes the first enabled config to default —
      // refetch so the "Default" chip shows immediately without a reload.
      fetchDefaultLLM();
      handleCloseDialog();
    } catch (error) {
      console.error('Error saving LLM config:', error);
      alert('Failed to save configuration');
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('Are you sure you want to delete this LLM configuration?')) {
      return;
    }
    try {
      await api.delete(`/llm/configs/${id}`);
      fetchConfigs();
    } catch (error: any) {
      alert(error.response?.data?.detail || 'Failed to delete configuration');
    }
  };

  const handleSetDefault = async (id: string) => {
    try {
      await api.put(`/llm/default/${id}`);
      fetchDefaultLLM();
    } catch (error) {
      alert('Failed to set default LLM');
    }
  };

  const handleTest = async (config: LLMConfigData) => {
    setTesting(prev => ({ ...prev, [config.id]: true }));
    setTestResults(prev => ({ ...prev, [config.id]: undefined as any }));
    try {
      const response = await api.post('/llm/test', { config_id: config.id });
      const data = response.data;
      setTestResults(prev => ({
        ...prev,
        [config.id]: {
          success: data.success,
          message: data.message + (data.response ? `\n\nLLM Response: "${data.response}"` : '')
        }
      }));
    } catch (error: any) {
      setTestResults(prev => ({
        ...prev,
        [config.id]: { success: false, message: error.response?.data?.detail || 'Connection failed' }
      }));
    } finally {
      setTesting(prev => ({ ...prev, [config.id]: false }));
    }
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">LLM Configuration</Typography>
        <Button variant="contained" color="primary" startIcon={<AddIcon />} onClick={() => handleOpenDialog()}>
          Add LLM
        </Button>
      </Box>

      {defaultLLM ? (
        <Alert severity="info" sx={{ mb: 3 }}>
          <strong>Default:</strong> {defaultLLM.name} ({defaultLLM.model_name})
        </Alert>
      ) : configs.length > 0 ? (
        <Alert severity="warning" sx={{ mb: 3 }}>
          No default LLM is set. AI features (suggestions, summaries) require a
          default — click <strong>Set Default</strong> on an enabled row below.
        </Alert>
      ) : null}

      {configs.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="textSecondary">No LLM configurations yet. Add one to enable AI features.</Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Provider</TableCell>
                <TableCell>Model</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Default</TableCell>
                <TableCell>Test</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {configs.map((config) => (
                <TableRow key={config.id}>
                  <TableCell>
                    <Typography variant="body1">{config.name}</Typography>
                    {config.notes && (
                      <Typography variant="caption" color="textSecondary">{config.notes}</Typography>
                    )}
                  </TableCell>
                  <TableCell><Chip label={config.request_format} size="small" /></TableCell>
                  <TableCell>{config.model_name}</TableCell>
                  <TableCell>
                    <Chip label={config.enabled ? 'Enabled' : 'Disabled'} color={config.enabled ? 'success' : 'default'} size="small" />
                  </TableCell>
                  <TableCell>
                    {defaultLLM?.id === config.id ? (
                      <Chip icon={<StarIcon />} label="Default" color="primary" size="small" />
                    ) : (
                      <Button size="small" onClick={() => handleSetDefault(config.id)}>Set Default</Button>
                    )}
                  </TableCell>
                  <TableCell>
                    {testing[config.id] ? (
                      <CircularProgress size={20} />
                    ) : testResults[config.id] ? (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        {testResults[config.id].success ? <SuccessIcon color="success" fontSize="small" /> : <ErrorIcon color="error" fontSize="small" />}
                        <IconButton size="small" onClick={() => handleTest(config)}><TestIcon fontSize="small" /></IconButton>
                      </Box>
                    ) : (
                      <IconButton size="small" onClick={() => handleTest(config)}><TestIcon /></IconButton>
                    )}
                  </TableCell>
                  <TableCell>
                    <IconButton size="small" onClick={() => handleOpenDialog(config)}><EditIcon /></IconButton>
                    <IconButton size="small" onClick={() => handleDelete(config.id)}><DeleteIcon /></IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Test Results */}
      {Object.entries(testResults).map(([configId, result]) => result && (
        <Alert
          key={configId}
          severity={result.success ? 'success' : 'error'}
          sx={{ mt: 2, whiteSpace: 'pre-wrap' }}
          onClose={() => setTestResults(prev => {
            const next = { ...prev };
            delete next[configId];
            return next;
          })}
        >
          {result.message}
        </Alert>
      ))}

      <Dialog open={openDialog} onClose={handleCloseDialog} maxWidth="md" fullWidth>
        <DialogTitle>{editingConfig ? 'Edit LLM Configuration' : 'Add LLM Configuration'}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
            <TextField label="Name" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} fullWidth required />
            <FormControl fullWidth required>
              <InputLabel>Request Format</InputLabel>
              <Select value={formData.request_format} onChange={(e) => setFormData({ ...formData, request_format: e.target.value })}>
                <MenuItem value="openai">OpenAI</MenuItem>
                <MenuItem value="anthropic">Anthropic</MenuItem>
                <MenuItem value="google">Google</MenuItem>
                <MenuItem value="cohere">Cohere</MenuItem>
              </Select>
            </FormControl>
            <TextField label="API Endpoint" value={formData.api_endpoint} onChange={(e) => setFormData({ ...formData, api_endpoint: e.target.value })} fullWidth required helperText="Full URL (e.g., https://api.openai.com/v1/chat/completions)" />
            <TextField label="API Key" type="password" value={formData.api_key} onChange={(e) => setFormData({ ...formData, api_key: e.target.value })} fullWidth required={!editingConfig} helperText={editingConfig ? "Leave blank to keep existing key" : "Required"} />
            <TextField label="Model Name" value={formData.model_name} onChange={(e) => setFormData({ ...formData, model_name: e.target.value })} fullWidth required helperText="e.g., gpt-4o-mini, gpt-4o, claude-3-5-sonnet-latest" />
            <TextField label="Temperature" type="number" value={formData.temperature} onChange={(e) => setFormData({ ...formData, temperature: parseFloat(e.target.value) })} inputProps={{ min: 0, max: 2, step: 0.1 }} fullWidth />
            <TextField label="Max Tokens" type="number" value={formData.max_tokens} onChange={(e) => setFormData({ ...formData, max_tokens: parseInt(e.target.value) })} inputProps={{ min: 1 }} fullWidth />
            <TextField label="Notes" value={formData.notes} onChange={(e) => setFormData({ ...formData, notes: e.target.value })} fullWidth multiline rows={2} />
            <FormControl fullWidth>
              <InputLabel>Status</InputLabel>
              <Select value={String(formData.enabled)} onChange={(e) => setFormData({ ...formData, enabled: e.target.value === 'true' })}>
                <MenuItem value="true">Enabled</MenuItem>
                <MenuItem value="false">Disabled</MenuItem>
              </Select>
            </FormControl>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button onClick={handleSave} variant="contained" color="primary">Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default LLMConfiguration;
