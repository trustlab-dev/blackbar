export interface Case {
  id: string;
  title: string;
  description?: string;
  status: 'open' | 'in_review' | 'on_hold' | 'finalized' | 'closed';
  priority: 'low' | 'medium' | 'high' | 'critical';
  created_at: string;
  updated_at: string;
  created_by: string;
  assigned_user_ids: string[];
  privacy_officer_id?: string;
  due_date?: string;
  document_ids: string[];
  tags: string[];
  metadata: Record<string, any>;
}

export interface CaseCreateRequest {
  title: string;
  description?: string;
  status?: 'open' | 'in_review' | 'on_hold' | 'finalized' | 'closed';
  priority?: 'low' | 'medium' | 'high' | 'critical';
  assigned_user_ids?: string[];
  privacy_officer_id?: string;
  due_date?: string;
  tags?: string[];
  metadata?: Record<string, any>;
}

export interface CaseUpdateRequest {
  title?: string;
  description?: string;
  status?: 'open' | 'in_review' | 'on_hold' | 'finalized' | 'closed';
  priority?: 'low' | 'medium' | 'high' | 'critical';
  assigned_user_ids?: string[];
  privacy_officer_id?: string;
  due_date?: string;
  tags?: string[];
  metadata?: Record<string, any>;
}

export interface CaseDocument {
  id: string;
  filename: string;
  upload_date: string;
  mime_type: string;
  size: number;
  summary?: string;
}

export interface User {
  id: string;
  username: string;
  email: string;
  role: string;
  display_name?: string;
}
