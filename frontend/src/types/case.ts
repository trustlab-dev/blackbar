// Define types for case management

export enum CaseStatus {
  OPEN = 'open',
  IN_REVIEW = 'in_review',
  ON_HOLD = 'on_hold',
  FINALIZED = 'finalized',
  CLOSED = 'closed'
}

export enum CasePriority {
  CRITICAL = 'critical',
  HIGH = 'high',
  MEDIUM = 'medium',
  LOW = 'low'
}

export interface Case {
  id: string;
  title: string;
  description: string;
  status: string; // Using string instead of CaseStatus enum for flexibility
  priority: string; // Using string instead of CasePriority enum for flexibility
  created_by: string;
  assigned_user_ids: string[];
  privacy_officer_id?: string;
  due_date?: string;
  document_ids: string[];
  tags: string[];
  created_at: string;
  updated_at: string;
  review_status?: string; // Added to support review status in CaseList
  case_team?: Array<{
    user_id: string;
    role: string;
    status: string;
    [key: string]: any;
  }>;
}

export interface CaseDocument {
  id: string;
  filename: string;
  mime_type?: string;
  size?: number;
  upload_date: string;
  description?: string;
  summary?: string;
  text_summary?: string;
  text_data?: {
    full_text: string;
    pages: any[];
  };
  tags?: string[];
  status?: string;
}

export interface CaseFormData {
  title: string;
  description: string;
  priority: string;
  status: string;
  tags: string[];
  document_ids?: string[];
  assigned_user_ids?: string[];
}

export interface CaseCreateRequest {
  title: string;
  description: string;
  priority: string;
  status: string;
  tags: string[];
  document_ids?: string[];
  assigned_user_ids?: string[];
}

export interface CaseUpdateRequest {
  title?: string;
  description?: string;
  priority?: string;
  status?: string;
  tags?: string[];
  document_ids?: string[];
  assigned_user_ids?: string[];
  privacy_officer_id?: string;
  due_date?: string;
  assigned_to?: string;
}

export interface CaseListParams {
  limit?: number;
  skip?: number;
  status?: string;
  priority?: string;
  assigned_to?: string;
}

export interface CaseListResponse {
  cases: Case[];
  total: number;
}
