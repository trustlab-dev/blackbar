import api from '../api/client';
import { CaseDocument } from '../types/case';

// Get all documents with optional filters
export const getDocuments = async (params?: {
  skip?: number;
  limit?: number;
  file_type?: string;
  uploaded_by?: string;
  tags?: string[];
}) => {
  const response = await api.get('/documents', { params });
  return response.data;
};

// Get a specific document by ID
export const getDocumentById = async (documentId: string) => {
  const response = await api.get(`/documents/${documentId}`);
  return response.data as CaseDocument;
};
