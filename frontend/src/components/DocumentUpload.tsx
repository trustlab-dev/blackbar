// frontend/src/components/DocumentUpload.tsx
import React, { useState } from 'react';
import api, { TRANSFER_TIMEOUT_MS } from '../api/client';
import { getApiErrorMessage } from '../api/errors';

interface Props {
  onUpload?: (files: File[]) => Promise<void>;
  onUploadSuccess?: (documentId: string) => void;
  /**
   * Case the upload belongs to. Required for the built-in API upload: the
   * backend answers 400 "case_id is required" for team-scoped (`user`) callers
   * that omit it (backend/src/documents/routes.py upload_document).
   */
  caseId?: string;
}

export const NO_CASE_UPLOAD_MESSAGE =
  'Open a case before uploading: documents must be uploaded to a case.';

export const DocumentUpload: React.FC<Props> = ({ onUpload, onUploadSuccess, caseId }) => {
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string>('');

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files?.length) return;

    setUploading(true);
    setMessage('');
    const file = event.target.files[0];
    const files = Array.from(event.target.files);
    const formData = new FormData();
    formData.append('file', file);

    try {
      // If onUpload prop is provided, use that
      if (onUpload) {
        await onUpload(files);
        setMessage('Document uploaded successfully!');
      } 
      // Otherwise use the default API upload
      else if (onUploadSuccess) {
        if (!caseId) {
          // Fail here with a clear message instead of a silent 400.
          setMessage(NO_CASE_UPLOAD_MESSAGE);
          return;
        }
        formData.append('case_id', caseId);
        const response = await api.post('/documents/', formData, {
          timeout: TRANSFER_TIMEOUT_MS,
        });
        
        if (response.data.existing) {
          setMessage('This document was already uploaded. Loading existing version...');
        } else {
          setMessage('Document uploaded successfully!');
        }
        
        onUploadSuccess(response.data.id);
      }
    } catch (error) {
      console.error('Upload failed:', error);
      setMessage(getApiErrorMessage(error, 'Failed to upload document. Please try again.'));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="upload-container">
      <input 
        type="file" 
        accept=".pdf,.docx,.eml"
        onChange={handleFileUpload}
        disabled={uploading}
      />
      {uploading && <div className="upload-status">Uploading...</div>}
      {message && <div className="upload-message">{message}</div>}
    </div>
  );
};
