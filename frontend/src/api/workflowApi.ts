/**
 * Workflow API Module.
 *
 * API functions for workflow features:
 * - Clock management (statutory clock pause/resume)
 * - Internal messaging
 * - Contributors (named record providers)
 * - Reminders
 * - Priority queue
 * - Records confirmation
 * - Request transfer
 */
import api from './client';

// =============================================================================
// Types
// =============================================================================

export interface ClockEvent {
  id: string;
  case_id: string;
  event_type: 'start' | 'pause' | 'resume' | 'extend';
  reason?: string;
  event_date: string;
  created_by: string;
  created_by_name?: string;
  notes?: string;
  days_elapsed_at_event?: number;
}

export interface ClockStatus {
  case_id: string;
  status: 'running' | 'paused';
  original_due_date?: string;
  adjusted_due_date?: string;
  total_paused_days: number;
  current_pause_start?: string;
  current_pause_reason?: string;
  events: ClockEvent[];
}

export interface CaseContributor {
  id: string;
  case_id: string;
  name: string;
  email: string;
  department?: string;
  status: 'invited' | 'active' | 'completed' | 'expired';
  documents_uploaded: number;
  last_upload_at?: string;
  invited_by: string;
  invited_by_name?: string;
  created_at: string;
  token_expires_at: string;
  notes?: string;
}

export interface CasePriorityScore {
  case_id: string;
  tracking_number: string;
  title: string;
  due_date?: string;
  days_until_due?: number;
  case_age_days: number;
  document_count: number;
  priority_score: number;
  priority_override?: number;
  status: string;
  workflow_stage?: string;
  clock_status: string;
  analyst_ids: string[];
}

export interface RecordsConfirmation {
  confirmed: boolean;
  confirmed_by?: string;
  confirmed_by_name?: string;
  confirmed_at?: string;
  notes?: string;
}

export interface CaseTransfer {
  id: string;
  case_id: string;
  tracking_number: string;
  recipient_organization: string;
  recipient_email: string;
  recipient_name?: string;
  include_documents: boolean;
  transfer_reason: string;
  notes?: string;
  status: string;
  transferred_by: string;
  transferred_by_name?: string;
  transferred_at: string;
  token_expires_at: string;
}

export interface ExemptionSection {
  code: string;
  name: string;
  description: string;
  category_id: string;
  parent_code?: string;
  subsections?: ExemptionSection[];
}

// =============================================================================
// Clock Management
// =============================================================================

export const clockApi = {
  pause: async (caseId: string, reason: string, notes?: string): Promise<ClockEvent> => {
    const response = await api.post(`/cases/${caseId}/clock/pause`, {
      event_type: 'pause',
      reason,
      notes
    });
    return response.data;
  },

  resume: async (caseId: string, notes?: string): Promise<ClockEvent> => {
    const response = await api.post(`/cases/${caseId}/clock/resume`, null, {
      params: { notes }
    });
    return response.data;
  },

  getHistory: async (caseId: string): Promise<ClockStatus> => {
    const response = await api.get(`/cases/${caseId}/clock/history`);
    return response.data;
  }
};

// =============================================================================
// Contributors
// =============================================================================

export const contributorsApi = {
  list: async (caseId: string): Promise<CaseContributor[]> => {
    const response = await api.get(`/cases/${caseId}/contributors`);
    return response.data;
  },

  invite: async (
    caseId: string,
    data: {
      name: string;
      email: string;
      department?: string;
      notes?: string;
      token_expiration_days?: number;
    }
  ): Promise<{ contributor: CaseContributor; upload_url: string; expires_at: string }> => {
    const response = await api.post(`/cases/${caseId}/contributors`, data);
    return response.data;
  },

  update: async (
    caseId: string,
    contributorId: string,
    data: { name?: string; department?: string; notes?: string; status?: string }
  ): Promise<CaseContributor> => {
    const response = await api.put(`/cases/${caseId}/contributors/${contributorId}`, data);
    return response.data;
  },

  remind: async (caseId: string, contributorId: string): Promise<void> => {
    await api.post(`/cases/${caseId}/contributors/${contributorId}/remind`);
  },

  delete: async (caseId: string, contributorId: string): Promise<void> => {
    await api.delete(`/cases/${caseId}/contributors/${contributorId}`);
  },

  bulkInvite: async (
    caseId: string,
    contributors: Array<{ name: string; email: string; department?: string }>
  ): Promise<{ invitations: Array<{ contributor: CaseContributor; upload_url: string; expires_at: string }>; count: number }> => {
    const response = await api.post(`/cases/${caseId}/contributors/bulk`, { contributors });
    return response.data;
  }
};

// =============================================================================
// Priority Queue
// =============================================================================

export const queueApi = {
  getPrioritized: async (params?: {
    analyst_id?: string;
    workflow_stage?: string;
    clock_status?: string;
    include_closed?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<CasePriorityScore[]> => {
    const response = await api.get('/queue/prioritized', { params });
    return response.data;
  },

  getAnalystWorkload: async (analystId: string, limit = 20): Promise<CasePriorityScore[]> => {
    const response = await api.get(`/queue/workload/${analystId}`, {
      params: { limit }
    });
    return response.data;
  },

  setPriorityOverride: async (caseId: string, priorityOverride: number | null): Promise<void> => {
    await api.put(`/cases/${caseId}/priority`, null, {
      params: { priority_override: priorityOverride }
    });
  }
};

// =============================================================================
// Records Confirmation
// =============================================================================

export const recordsConfirmationApi = {
  get: async (caseId: string): Promise<RecordsConfirmation> => {
    const response = await api.get(`/cases/${caseId}/records-confirmation`);
    return response.data;
  },

  confirm: async (caseId: string, notes?: string): Promise<RecordsConfirmation> => {
    const response = await api.post(`/cases/${caseId}/records-confirmation`, { notes });
    return response.data;
  },

  revoke: async (caseId: string): Promise<void> => {
    await api.delete(`/cases/${caseId}/records-confirmation`);
  }
};

// =============================================================================
// Request Transfer
// =============================================================================

export const transferApi = {
  list: async (caseId: string): Promise<CaseTransfer[]> => {
    const response = await api.get(`/cases/${caseId}/transfers`);
    return response.data;
  },

  create: async (
    caseId: string,
    data: {
      recipient_organization: string;
      recipient_email: string;
      recipient_name?: string;
      include_documents?: boolean;
      included_document_ids?: string[];  // Selective document inclusion
      transfer_reason: string;
      notes?: string;
    }
  ): Promise<{ transfer: CaseTransfer; transfer_url: string; expires_at: string }> => {
    const response = await api.post(`/cases/${caseId}/transfer`, data);
    return response.data;
  }
};

// =============================================================================
// Section Lookup (for redaction)
// =============================================================================

export const sectionsApi = {
  search: async (query?: string): Promise<{ sections: ExemptionSection[]; pack_id: string; pack_name: string; count: number }> => {
    const response = await api.get('/packs/active/sections', {
      params: query ? { q: query } : undefined
    });
    return response.data;
  }
};
