// frontend/src/components/DocumentUpload.tsx
import React, { useState } from 'react';
import api from '../api/client';

interface Props {
  onUpload?: (files: File[]) => Promise<void>;
  onUploadSuccess?: (documentId: string) => void;
}

export const DocumentUpload: React.FC<Props> = ({ onUpload, onUploadSuccess }) => {
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
        const response = await api.post('/documents/', formData);
        
        if (response.data.existing) {
          setMessage('This document was already uploaded. Loading existing version...');
        } else {
          setMessage('Document uploaded successfully!');
        }
        
        onUploadSuccess(response.data.id);
      }
    } catch (error) {
      console.error('Upload failed:', error);
      setMessage('Failed to upload document. Please try again.');
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
