import os as _os

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import Response

from ..core.database import get_database_from_request


def _sanitize_filename(name: str) -> str:
    """Strip path separators, newlines, and null bytes from filenames for Content-Disposition."""
    return _os.path.basename(name).replace("\n", "").replace("\r", "").replace("\x00", "")


import logging
import os
import uuid
from datetime import datetime

import gridfs

from src.utils.ai_processing import (
    generate_document_summary,  # noqa: F401 — re-exported for processing_service
    process_attachment_async,
)
from src.utils.ai_redaction import (
    enrich_suggestions_with_coordinates,
    get_redaction_suggestions,
)
from src.utils.email_threads import (  # noqa: F401 — re-exported for processing_service
    consolidate_email_thread,
    extract_thread_identifiers,
    find_thread_emails,
)
from src.utils.ocr import (  # noqa: F401 — re-exported for processing_service
    extract_text_with_coordinates,
    get_text_summary,
)

from ..database import db
from ..dependencies import check_role, get_current_user

# NOTE on re-exports above (extract_text_with_coordinates, get_text_summary,
# generate_document_summary, consolidate_email_thread,
# extract_thread_identifiers, find_thread_emails):
# src.documents.processing_service uses lazy `from src.documents.routes
# import ...` to reach these helpers, and tests monkeypatch them on this
# module. Long-term direction: processing_service should import the
# originals directly from utils/. Until then, these re-exports must stay.

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


def check_document_access(doc: dict, current_user: dict, case: dict = None) -> bool:
    """
    Check if user has access to a document.
    - Owner/Admin: always has access
    - Guest: only if document is shared with them
    - Others: if on case team
    """
    user_role = current_user.get("role")
    user_id = current_user["id"]

    # Owner and Admin always have access
    if user_role in ["owner", "admin"]:
        return True

    # Guest: check if document is shared with them
    if user_role == "guest":
        shared_with = doc.get("shared_with", [])
        return any(share.get("user_id") == user_id for share in shared_with)

    # Others: check case team membership
    if case:
        from ..cases.permissions import is_case_team_member

        return is_case_team_member(case.get("case_team", []), user_id)

    return False


# LIST DOCUMENTS
@router.get("/", dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))])
async def list_documents(
    request: Request, current_user=Depends(get_current_user), db=Depends(get_db)
):
    cursor = db.documents.find({}, {"content": 0})  # Exclude binary content
    docs = await cursor.to_list(length=None)
    return [
        {
            "id": doc["id"],
            "filename": doc["filename"],
            "redactions": len(doc.get("redactions", [])),
            "uploadDate": doc.get("upload_date", None),
            "mimeType": doc.get("mime_type", "application/pdf"),
            "hasAttachments": doc.get("has_attachments", False),
        }
        for doc in docs
    ]


# GET DOCUMENT PDF CONTENT
@router.get(
    "/{document_id}",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user", "guest"]))],
)
async def get_document(
    request: Request, document_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access (includes guest shares)
    case = await db.cases.find_one({"id": doc.get("case_id")}) if doc.get("case_id") else None
    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    # Check if content is stored in GridFS (for collection link uploads)
    if doc.get("content_file_id"):
        try:
            from pymongo import MongoClient

            from src.config import MONGODB_URI

            sync_client = MongoClient(MONGODB_URI)
            db_name = db.name
            sync_db = sync_client[db_name]
            fs = gridfs.GridFS(sync_db)

            grid_out = fs.get(doc["content_file_id"])
            content = grid_out.read()
            sync_client.close()

            return Response(content=content, media_type="application/pdf")
        except Exception as e:
            logger.warning(
                f"GridFS retrieval failed for {document_id}, falling back to document content: {e}"
            )
            # Fall through to legacy content check below

    # Legacy: content stored directly in document
    if doc.get("content"):
        return Response(content=doc["content"], media_type="application/pdf")

    # No content found anywhere
    logger.error(
        f"No content found for document {document_id} - neither GridFS nor embedded content"
    )
    raise HTTPException(status_code=404, detail="Document content not found")


# DOWNLOAD ORIGINAL FILE
@router.get(
    "/{document_id}/download",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user", "guest"]))],
)
async def download_original_file(
    request: Request, document_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Download the original file (before PDF conversion) if available."""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access (includes guest shares)
    case = await db.cases.find_one({"id": doc.get("case_id")}) if doc.get("case_id") else None
    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    # If there's an original file in GridFS, return it
    if doc.get("original_file_id"):
        try:
            # Get the synchronous database for GridFS
            from pymongo import MongoClient

            from src.config import MONGODB_URI

            sync_client = MongoClient(MONGODB_URI)
            db_name = db.name
            sync_db = sync_client[db_name]
            fs = gridfs.GridFS(sync_db)

            grid_out = fs.get(doc["original_file_id"])
            content = grid_out.read()

            # Use original filename and content type
            filename = doc.get("original_filename", doc["filename"])
            content_type = grid_out.content_type or "application/octet-stream"

            sync_client.close()

            logger.info(f"Downloading original file: {filename} (type: {content_type})")
            return Response(
                content=content,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{_sanitize_filename(filename)}"'
                },
            )
        except Exception as e:
            logger.error(f"Error retrieving original file from GridFS: {e}")
            # Fall back to PDF if GridFS retrieval fails

    # Otherwise, return the PDF (check GridFS first for collection link uploads)
    if doc.get("content_file_id"):
        try:
            from pymongo import MongoClient

            from src.config import MONGODB_URI

            sync_client = MongoClient(MONGODB_URI)
            db_name = db.name
            sync_db = sync_client[db_name]
            fs = gridfs.GridFS(sync_db)

            grid_out = fs.get(doc["content_file_id"])
            content = grid_out.read()
            sync_client.close()

            return Response(
                content=content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'},
            )
        except Exception as e:
            logger.warning(
                f"GridFS retrieval failed for download {document_id}, falling back to document content: {e}"
            )
            # Fall through to legacy content check below

    # Legacy: content stored directly in document
    if doc.get("content"):
        logger.info(f"Returning embedded PDF content for {doc['filename']}")
        return Response(
            content=doc["content"],
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'},
        )

    # No content found anywhere
    logger.error(
        f"No content found for document {document_id} download - neither GridFS nor embedded content"
    )
    raise HTTPException(status_code=404, detail="Document content not found")


# GET DOCUMENT METADATA
@router.get(
    "/{document_id}/metadata",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user", "guest"]))],
)
async def get_document_metadata(
    request: Request, document_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    doc = await db.documents.find_one({"id": document_id}, {"content": 0})  # Exclude binary content
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access (includes guest shares)
    case = await db.cases.find_one({"id": doc.get("case_id")}) if doc.get("case_id") else None
    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    # Get text_data - if not available, create from extracted_text
    text_data = doc.get("text_data")
    if not text_data and doc.get("extracted_text"):
        # Convert simple extracted_text to text_data format for compatibility
        text_data = {
            "full_text": doc.get("extracted_text"),
            "pages": [],  # No page-level data for simple extraction
        }

    return {
        "id": doc["id"],
        "filename": doc["filename"],
        "redactions": doc.get("redactions", []),
        "text_data": text_data,
        "text_summary": doc.get("text_summary"),
        "mime_type": doc.get("mime_type"),
        "size": doc.get("size"),
    }


# EXPORT DOCUMENT WITH APPLIED REDACTIONS
@router.get(
    "/{document_id}/export",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def export_document_with_redactions(request: Request, document_id: str, db=Depends(get_db)):
    """Export a document with redactions applied permanently."""
    try:
        # Get the document
        doc = await db.documents.find_one({"id": document_id})
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # Get the redactions
        redactions = doc.get("redactions", [])
        logger.info(f"Exporting document with {len(redactions)} redactions")

        # If no redactions, return the original document with descriptive filename
        if not redactions:
            from datetime import datetime

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            original_name = doc["filename"].replace(".pdf", "")
            doc_id_short = document_id[:8]
            export_filename = f"{original_name}_NOREDACTIONS_{doc_id_short}_{timestamp}.pdf"

            return Response(
                content=doc["content"],
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="{_sanitize_filename(export_filename)}"'
                },
            )

        # Apply redactions to the PDF
        from io import BytesIO

        import fitz  # PyMuPDF

        # Load the PDF
        pdf_content = BytesIO(doc["content"])
        pdf_document = fitz.open("pdf", pdf_content.read())

        # Apply each redaction
        for redaction in redactions:
            # Apply all redactions except explicitly rejected ones
            status = redaction.get("status", "pending")
            if status != "rejected":
                page_number = redaction.get("page", 1) - 1  # Convert to 0-based index
                x1 = float(redaction.get("x", 0))
                y1 = float(redaction.get("y", 0))
                width = float(redaction.get("width", 100))
                height = float(redaction.get("height", 20))
                x2 = x1 + width
                y2 = y1 + height

                # Ensure page number is valid
                if 0 <= page_number < len(pdf_document):
                    page = pdf_document[page_number]

                    # Add redaction annotation with black fill and text overlay
                    rect = fitz.Rect(x1, y1, x2, y2)
                    # Add the redaction with section code as overlay text
                    section_code = redaction.get("reason", "REDACTED")
                    page.add_redact_annot(
                        rect, text=section_code, fill=(0, 0, 0), text_color=(1, 1, 1)
                    )
                    logger.info(
                        f"Added redaction at page {page_number + 1}: ({x1}, {y1}, {x2}, {y2})"
                    )

        # Apply the redactions - this permanently removes the text under the boxes
        for page in pdf_document:
            page.apply_redactions()

        # Save to BytesIO
        output_pdf = BytesIO()
        pdf_document.save(output_pdf, garbage=4, deflate=True)
        pdf_document.close()
        output_pdf.seek(0)

        # Generate descriptive filename with document ID and timestamp
        from datetime import datetime

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        original_name = doc["filename"].replace(".pdf", "")
        doc_id_short = document_id[:8]  # First 8 chars of UUID
        export_filename = f"{original_name}_REDACTED_{doc_id_short}_{timestamp}.pdf"

        # Return the redacted PDF
        return Response(
            content=output_pdf.read(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{_sanitize_filename(export_filename)}"'
            },
        )

    except HTTPException:
        # Phase 4 Batch 4.4 (audit B39): preserve intentional HTTPException
        # status codes (e.g. the 404 raised above for missing documents).
        # The broad `except Exception` below would otherwise re-emit them
        # as 500, hiding the real cause from clients.
        raise
    except Exception as e:
        logger.error(f"Error exporting document with redactions: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# File upload constants
ALLOWED_MIME_TYPES = [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "message/rfc822",
    "application/vnd.ms-outlook",
    "application/x-ole-storage",  # MSG files may be detected as OLE
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/webp",
]
ALLOWED_EXTENSIONS = [
    ".pdf",
    ".doc",
    ".docx",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".eml",
    ".msg",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
]
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB — matches processing_service.py


async def merge_attachments_into_existing_email(
    existing_doc: dict, attachments: list[dict], background_tasks: BackgroundTasks
) -> int:
    """Merge newly extracted attachments into an existing email document.

    Attachments are deduplicated by (filename, size) and associated with the
    existing email. New attachment documents are created for any that don't
    already exist on the email.
    """
    if not attachments:
        return 0

    email_doc_id = existing_doc["id"]
    existing_attachment_ids = existing_doc.get("attachment_ids", [])

    # Load existing attachments for deduplication index
    existing_attachments = []
    if existing_attachment_ids:
        existing_attachments = await db.documents.find(
            {"id": {"$in": existing_attachment_ids}}
        ).to_list(length=1000)

    existing_index = {
        (att.get("filename"), att.get("size", 0)): att["id"] for att in existing_attachments
    }

    new_attachment_docs = []
    new_attachment_ids: list[str] = []

    for attachment in attachments:
        filename = attachment.get("filename")
        size = attachment.get("size", 0)
        key = (filename, size)

        # Skip if this attachment (by name/size) already exists on the email
        if key in existing_index:
            continue

        attachment_path = attachment.get("path")
        if not attachment_path or not os.path.exists(attachment_path):
            continue

        with open(attachment_path, "rb") as f_attachment:
            attachment_content = f_attachment.read()

        attachment_id = str(uuid.uuid4())
        attachment_doc = {
            "id": attachment_id,
            "filename": filename,
            "content": attachment_content,
            "upload_date": datetime.utcnow(),
            "redactions": [],
            "is_attachment": True,
            "parent_document_id": email_doc_id,
            "mime_type": attachment.get("mime_type", "application/octet-stream"),
            "size": size,
        }

        new_attachment_docs.append(attachment_doc)
        new_attachment_ids.append(attachment_id)
        existing_index[key] = attachment_id

    if not new_attachment_docs:
        return 0

    # Insert new attachments and update main email doc metadata
    await db.documents.insert_many(new_attachment_docs)

    updated_attachment_ids = existing_attachment_ids + new_attachment_ids
    update_fields = {
        "has_attachments": True,
        "attachment_ids": updated_attachment_ids,
        "total_attachments": len(updated_attachment_ids),
    }

    await db.documents.update_one({"id": email_doc_id}, {"$set": update_fields})

    # Queue background processing for new attachments
    for attachment_doc in new_attachment_docs:
        background_tasks.add_task(process_attachment_async, attachment_doc["id"], email_doc_id)

    logger.info(
        f"Merged {len(new_attachment_docs)} new attachments into existing email {email_doc_id}"
    )
    return len(new_attachment_docs)


async def aggregate_attachments_to_canonical(canonical_id: str, superseded_ids: list[str]) -> None:
    """Aggregate attachments from superseded emails onto the canonical email.

    This ensures the active email in a thread exposes all attachments from the
    entire thread, while older emails can be hidden from the UI.
    """
    if not superseded_ids:
        return

    canonical_doc = await db.documents.find_one({"id": canonical_id})
    if not canonical_doc:
        logger.warning(f"Canonical email {canonical_id} not found for attachment aggregation")
        return

    canonical_attachment_ids = canonical_doc.get("attachment_ids", [])

    # Build dedup index from canonical attachments
    canonical_attachments = []
    if canonical_attachment_ids:
        canonical_attachments = await db.documents.find(
            {"id": {"$in": canonical_attachment_ids}}
        ).to_list(length=1000)

    attachment_index = {
        (att.get("filename"), att.get("size", 0)): att["id"] for att in canonical_attachments
    }

    new_ids: list[str] = []

    for email_id in superseded_ids:
        email_doc = await db.documents.find_one({"id": email_id})
        if not email_doc:
            continue

        email_attachment_ids = email_doc.get("attachment_ids", [])
        if not email_attachment_ids:
            continue

        email_attachments = await db.documents.find({"id": {"$in": email_attachment_ids}}).to_list(
            length=1000
        )

        for att in email_attachments:
            key = (att.get("filename"), att.get("size", 0))
            if key in attachment_index:
                continue

            # Re-associate attachment with canonical email
            await db.documents.update_one(
                {"id": att["id"]}, {"$set": {"parent_document_id": canonical_id}}
            )

            attachment_index[key] = att["id"]
            new_ids.append(att["id"])

    if not new_ids:
        return

    updated_attachment_ids = canonical_attachment_ids + new_ids
    await db.documents.update_one(
        {"id": canonical_id},
        {
            "$set": {
                "has_attachments": True,
                "attachment_ids": updated_attachment_ids,
                "total_attachments": len(updated_attachment_ids),
            }
        },
    )

    logger.info(f"Aggregated {len(new_ids)} attachments to canonical email {canonical_id}")


# UPLOAD & CONVERT DOCUMENT (Fixed with Role-Based Access)
@router.post("/", dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))])
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    case_id: str | None = Form(None),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Upload a document with full processing pipeline.

    Uses shared DocumentProcessingService for consistent handling:
    - Deduplication (content hash + email message_id)
    - Conversion to PDF
    - OCR text extraction
    - AI summary generation (respects org settings)
    - GridFS storage
    - Email thread consolidation
    - Attachment processing
    """
    from .processing_service import DocumentProcessingService, ProcessingStatus, UploadContext

    # Read file content
    content = await file.read()

    # Use shared processing service
    service = DocumentProcessingService(db)
    context = UploadContext(
        case_id=case_id,
        uploaded_by=current_user["id"],
        uploaded_by_name=current_user.get("username", current_user.get("email")),
        process_attachments=True,
        consolidate_email_threads=True,
    )

    result = await service.process_upload(
        file_content=content,
        filename=file.filename,
        content_type=file.content_type,
        context=context,
        background_tasks=background_tasks,
    )

    # Handle result based on status
    if result.status == ProcessingStatus.DUPLICATE:
        return {
            "message": "Duplicate document detected",
            "is_duplicate": True,
            "duplicate_of_id": result.duplicate_of_id,
            "duplicate_of_filename": result.duplicate_of_filename,
            "upload_date": None,  # Could fetch from DB if needed
        }
    elif result.status == ProcessingStatus.VALIDATION_FAILED:
        raise HTTPException(status_code=400, detail=result.message)
    elif result.status == ProcessingStatus.CONVERSION_FAILED:
        # Still return success but with warning
        logger.warning(f"Conversion failed for {file.filename}: {result.error}")
        return {
            "id": result.document_id,
            "filename": result.filename,
            "message": "Uploaded with conversion warning",
            "warning": result.error,
            "attachments": result.attachment_count,
        }
    elif result.status == ProcessingStatus.ERROR:
        raise HTTPException(status_code=500, detail=result.error)

    # Success response
    response = {
        "id": result.document_id,
        "filename": result.filename,
        "message": "Uploaded successfully",
        "attachments": result.attachment_count,
        "has_ocr": result.has_ocr,
        "has_ai_summary": result.has_ai_summary,
    }

    # Add thread consolidation info if applicable
    if result.thread_consolidation:
        response["thread_consolidation"] = result.thread_consolidation

    # Add warnings if any
    if result.warnings:
        response["warnings"] = result.warnings

    return response


# Background task to generate AI suggestions
async def generate_ai_suggestions_async(
    document_id: str,
    timeout: int = 120,
    db=None,  # Accept existing connection
):
    """
    Background task to generate AI suggestions for a document.

    Args:
        document_id: Document ID
        timeout: Timeout in seconds for AI generation
        db: Existing database connection (optional)
    """
    import asyncio

    try:
        logger.info(f"Starting AI suggestion generation for document {document_id}")

        # Get database if not provided
        if db is None:
            from ..core.database import get_database

            db = get_database()

        # Update status to show AI is processing
        await db.documents.update_one(
            {"id": document_id}, {"$set": {"processing_status": "ai_processing"}}
        )
        logger.info(f"✓ Document {document_id} - Status: AI_PROCESSING (background task started)")

        # Get document
        doc = await db.documents.find_one({"id": document_id})
        if not doc:
            logger.error(
                f"Document {document_id} not found for AI suggestion generation in database {db.name}"
            )
            # Try to list all documents to debug
            all_docs = await db.documents.find({}).to_list(length=10)
            logger.error(f"Available documents: {[d.get('id') for d in all_docs]}")
            return

        # Check if text has been extracted
        extracted_text = doc.get("extracted_text")
        if not extracted_text:
            text_data = doc.get("text_data")
            if text_data and text_data.get("full_text"):
                extracted_text = text_data.get("full_text")

        if not extracted_text:
            logger.warning(f"No text extracted for document {document_id}, skipping AI suggestions")
            return

        # Get case context if available
        context = None
        if doc.get("case_id"):
            case = await db.cases.find_one({"id": doc["case_id"]})
            if case:
                context = f"Case: {case.get('title', 'Unknown')}. Type: FOI Request"

        # Generate suggestions with timeout
        result = await asyncio.wait_for(
            get_redaction_suggestions(extracted_text, context), timeout=timeout
        )

        suggestions = result.get("suggestions", [])

        # Enrich with coordinates
        pdf_content = doc.get("content")
        text_data = doc.get("text_data")
        if pdf_content:
            suggestions = enrich_suggestions_with_coordinates(suggestions, pdf_content, text_data)
            result["suggestions"] = suggestions

        # Cache the results
        cache_data = {
            "suggestions": suggestions,
            "summary": result.get("summary", ""),
            "method": "openai_gpt4",
            "generated_at": datetime.utcnow(),
            "auto_generated": True,
        }

        await db.documents.update_one(
            {"id": document_id},
            {"$set": {"ai_suggestions": cache_data, "processing_status": "ai_complete"}},
        )

        logger.info(
            f"✓ Document {document_id} - Status: AI_COMPLETE ({len(suggestions)} suggestions generated)"
        )

    except TimeoutError:
        logger.error(f"✗ Document {document_id} - Status: AI_TIMEOUT (generation timed out)")
        await db.documents.update_one(
            {"id": document_id},
            {
                "$set": {
                    "ai_suggestions": {
                        "suggestions": [],
                        "summary": "AI suggestion generation timed out",
                        "error": "timeout",
                        "generated_at": datetime.utcnow(),
                    },
                    "processing_status": "ai_timeout",
                }
            },
        )
    except Exception as e:
        logger.error(f"✗ Document {document_id} - Status: AI_ERROR - {str(e)}")
        await db.documents.update_one(
            {"id": document_id},
            {
                "$set": {
                    "ai_suggestions": {
                        "suggestions": [],
                        "summary": f"Error: {str(e)}",
                        "error": str(e),
                        "generated_at": datetime.utcnow(),
                    },
                    "processing_status": "ai_error",
                }
            },
        )


# DELETE DOCUMENT (New)
@router.delete("/{document_id}", dependencies=[Depends(check_role(["owner", "admin"]))])
async def delete_document(request: Request, document_id: str, db=Depends(get_db)):
    """
    Admins and Managers can delete documents.
    This will cascade delete:
    - The document itself
    - All attachments (where parent_document_id == document_id)
    - Remove document from case's document_ids array
    - Clean up any GridFS originals
    """
    # First, find the document to get its metadata
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case_id = doc.get("case_id")

    # Delete all attachments associated with this document
    attachment_delete_result = await db.documents.delete_many({"parent_document_id": document_id})
    logger.info(
        f"Deleted {attachment_delete_result.deleted_count} attachments for document {document_id}"
    )

    # Clean up thread relationships if this is an email
    if doc.get("mime_type") in ["message/rfc822", "application/vnd.ms-outlook"]:
        # If other emails were superseded by this one, mark them as active again
        await db.documents.update_many(
            {"superseded_by": document_id},
            {"$set": {"thread_status": "active", "superseded_by": None}},
        )
        logger.info(f"Cleared superseded_by references to document {document_id}")

    # Delete the main document
    result = await db.documents.delete_one({"id": document_id})
    logger.info(f"Delete result for document {document_id}: deleted_count={result.deleted_count}")

    if result.deleted_count == 0:
        logger.error(f"Failed to delete document {document_id} - document not found in database")
        raise HTTPException(status_code=500, detail="Failed to delete document from database")

    # Verify deletion
    verify_doc = await db.documents.find_one({"id": document_id})
    if verify_doc:
        logger.error(
            f"CRITICAL: Document {document_id} still exists after delete_one! This should not happen."
        )
        # Try to force delete again
        await db.documents.delete_many({"id": document_id})
        verify_again = await db.documents.find_one({"id": document_id})
        if verify_again:
            logger.error(f"CRITICAL: Document {document_id} STILL exists after delete_many!")
        else:
            logger.info(f"Document {document_id} successfully deleted with delete_many")
    else:
        logger.info(f"Verified: Document {document_id} successfully deleted from database")

    # Remove document from case's document_ids array
    if case_id:
        await db.cases.update_one({"id": case_id}, {"$pull": {"document_ids": document_id}})
        logger.info(f"Removed document {document_id} from case {case_id}")

    # Clean up GridFS originals if they exist
    try:
        if "original_file_id" in doc:
            # Get the synchronous database for GridFS
            from pymongo import MongoClient

            mongo_uri = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
            sync_client = MongoClient(mongo_uri)
            sync_db = sync_client["blackbar"]
            fs = gridfs.GridFS(sync_db)

            fs.delete(doc["original_file_id"])
            logger.info(f"Deleted GridFS original for document {document_id}")
            sync_client.close()
    except Exception as gridfs_error:
        logger.warning(f"Could not delete GridFS original: {gridfs_error}")

    return {
        "message": "Document deleted successfully",
        "attachments_deleted": attachment_delete_result.deleted_count,
    }


# CHECK DOCUMENT PROCESSING STATUS
@router.get(
    "/{document_id}/processing_status",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def get_processing_status(request: Request, document_id: str, db=Depends(get_db)):
    """Get the processing status of a document's attachments."""
    try:
        # Phase 4 Batch 4.4 (audit B38): include the legacy-doc fields
        # (`has_attachments`, `attachment_ids`) in the projection so
        # the fallback branch below can actually inspect them. The
        # prior 2-field projection masked those keys, leaving the
        # legacy-fallback dead code.
        doc = await db.documents.find_one(
            {"id": document_id},
            {
                "total_attachments": 1,
                "processed_attachments": 1,
                "has_attachments": 1,
                "attachment_ids": 1,
            },
        )

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        total = doc.get("total_attachments", 0)
        processed = doc.get("processed_attachments", 0)

        # If the document doesn't have these fields but exists, it means
        # it either has no attachments or was created before we added this feature
        if "total_attachments" not in doc:
            # Check if it has attachments
            has_attachments = doc.get("has_attachments", False)
            if not has_attachments:
                total = 0
                processed = 0
            else:
                # It has attachments but was uploaded before this feature
                attachment_ids = doc.get("attachment_ids", [])
                total = len(attachment_ids)
                processed = total  # Assume all processed for older documents

        return {
            "total_attachments": total,
            "processed_attachments": processed,
            "is_complete": processed >= total,  # >= to handle edge cases
            "progress_percentage": 100 if total == 0 else int((processed / total) * 100),
        }

    except HTTPException:
        # Phase 4 Batch 4.4 (audit B40): preserve intentional
        # HTTPException status codes (e.g. the 404 raised above for
        # missing documents). Same defect class as B6/B39.
        raise
    except Exception as e:
        logger.error(f"Error getting processing status: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# GET DOCUMENT AUDIT LOGS
@router.get(
    "/{document_id}/audit-logs", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def get_document_audit_logs(
    request: Request, document_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Get audit logs related to a specific document"""
    # Get document
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get case
    case_id = doc.get("case_id")
    if not case_id:
        return {"logs": []}

    case = await db.cases.find_one({"id": case_id})
    if not case:
        return {"logs": []}

    # Check access
    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    # Filter audit logs to those related to this document ONLY
    all_logs = case.get("audit_log", [])
    document_logs = []

    for log in all_logs:
        details = log.get("details", {})
        action = log.get("action", "")

        # Only include if explicitly mentions this document_id or filename
        # Do NOT include generic document actions without specific document reference
        if details.get("document_id") == document_id or details.get("filename") == doc.get(
            "filename"
        ):
            document_logs.append(
                {
                    "action": action,
                    "username": log.get("username"),
                    "timestamp": log.get("timestamp"),
                    "details": details,
                }
            )

    # Sort by timestamp, most recent first
    document_logs.sort(key=lambda x: x.get("timestamp", datetime.min), reverse=True)

    return {"logs": document_logs}


# Include redaction and contest management routes
from .attachment_routes import router as attachment_router
from .contest_routes import router as contest_router
from .document_status_routes import router as document_status_router
from .redaction_routes import router as redaction_router
from .redaction_suggestion_routes import router as redaction_suggestion_router
from .search_routes import router as search_router

router.include_router(redaction_router)
router.include_router(contest_router)
router.include_router(redaction_suggestion_router)
router.include_router(attachment_router)
router.include_router(document_status_router)
router.include_router(search_router)
