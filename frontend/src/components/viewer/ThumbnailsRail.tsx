import React, { useEffect, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { pdfjs } from 'react-pdf';
import './ThumbnailsRail.css';

// Configure PDF.js worker - use local worker from node_modules
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface Props {
  documentId: string;
  numPages: number;
  currentPage: number;
  onPageClick: (page: number) => void;
  pdfUrl: string | null;
}

const ThumbnailsRail: React.FC<Props> = ({ documentId, numPages, currentPage, onPageClick, pdfUrl }) => {
  const [thumbnails, setThumbnails] = useState<{ [key: number]: string }>({});
  const canvasRefs = useRef<{ [key: number]: HTMLCanvasElement | null }>({});

  useEffect(() => {
    if (!pdfUrl) return;

    let cancelled = false;
    let loadingTask: any = null;

    const loadThumbnails = async () => {
      try {
        loadingTask = pdfjs.getDocument(pdfUrl);
        const pdf = await loadingTask.promise;

        // Generate thumbnails for visible pages
        for (let pageNum = 1; pageNum <= numPages; pageNum++) {
          if (cancelled) break;
          const page = await pdf.getPage(pageNum);
          const viewport = page.getViewport({ scale: 0.2 }); // Small scale for thumbnails

          const canvas = document.createElement('canvas');
          const context = canvas.getContext('2d');
          canvas.height = viewport.height;
          canvas.width = viewport.width;

          if (context) {
            const renderContext: any = {
              canvasContext: context,
              viewport: viewport
            };
            await page.render(renderContext).promise;

            if (!cancelled) {
              setThumbnails(prev => ({
                ...prev,
                [pageNum]: canvas.toDataURL()
              }));
            }
          }
        }

        if (!cancelled) pdf.destroy();
      } catch (error: any) {
        if (!cancelled && error?.name !== 'MissingPDFException') {
          console.error('Error loading thumbnails:', error);
        }
      }
    };

    loadThumbnails();

    return () => {
      cancelled = true;
      if (loadingTask) {
        loadingTask.destroy?.();
      }
    };
  }, [pdfUrl, numPages]);

  return (
    <Box className="thumbnails-rail">
      {Array.from({ length: numPages }, (_, i) => i + 1).map((page) => (
        <Box
          key={page}
          className={`thumbnail ${page === currentPage ? 'active' : ''}`}
          onClick={() => onPageClick(page)}
        >
          {thumbnails[page] ? (
            <img 
              src={thumbnails[page]} 
              alt={`Page ${page}`}
              style={{ width: '100%', height: 'auto', display: 'block' }}
            />
          ) : (
            <Box className="thumbnail-placeholder">
              <Typography variant="caption">{page}</Typography>
            </Box>
          )}
          <Typography variant="caption" className="thumbnail-label">
            {page}
          </Typography>
        </Box>
      ))}
    </Box>
  );
};

export default ThumbnailsRail;
