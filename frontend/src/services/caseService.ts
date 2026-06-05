import api from '../api/client';
import { Case, CaseCreateRequest, CaseUpdateRequest } from '../types/case';

// Get all cases with optional filters
export const getCases = async (params: {
  skip?: number;
  limit?: number;
  status?: string;
  priority?: string;
  assigned_to?: string;
  created_by?: string;
}) => {
  const response = await api.get('/cases', { params });
  return response.data;
};

// Get a specific case by ID
export const getCaseById = async (caseId: string) => {
  const response = await api.get(`/cases/${caseId}`);
  return response.data as Case;
};

// Create a new case
export const createCase = async (caseData: CaseCreateRequest) => {
  const response = await api.post('/cases/', caseData);
  return response.data as Case;
};

// Update an existing case
export const updateCase = async (caseId: string, caseData: CaseUpdateRequest) => {
  const response = await api.put(`/cases/${caseId}`, caseData);
  return response.data as Case;
};

// Get documents associated with a case
export const getCaseDocuments = async (caseId: string) => {
  const response = await api.get(`/cases/${caseId}/documents`);
  return response.data.documents;
};

// Add documents to a case
export const addDocumentsToCase = async (caseId: string, documentIds: string[]) => {
  const response = await api.post(`/cases/${caseId}/documents`, documentIds);
  return response.data;
};

// Remove documents from a case
export const removeDocumentsFromCase = async (caseId: string, documentIds: string[]) => {
  const response = await api.delete(`/cases/${caseId}/documents`, { data: documentIds });
  return response.data;
};

// Case Team Management

// Get case team members
export const getCaseTeam = async (caseId: string) => {
  const response = await api.get(`/cases/${caseId}/team`);
  return response.data;
};

// Add a member to case team with case role
export const addCaseTeamMember = async (
  caseId: string, 
  userId: string, 
  role: string, // Case role: manager, analyst, legal, subject_matter_expert, reviewer, approver, third_party
  department?: string,
  notes?: string
) => {
  const response = await api.post(`/cases/${caseId}/team/members`, {
    user_id: userId,
    role,
    department,
    notes
  });
  return response.data;
};

// Remove a member from case team
export const removeCaseTeamMember = async (caseId: string, userId: string) => {
  const response = await api.delete(`/cases/${caseId}/team/members/${userId}`);
  return response.data;
};

// Update case team member
export const updateCaseTeamMember = async (
  caseId: string,
  userId: string,
  updates: {
    role?: string;
    department?: string;
    notes?: string;
    review_status?: string;
    approval_status?: string;
  }
) => {
  const response = await api.put(`/cases/${caseId}/team/members/${userId}`, updates);
  return response.data;
};
