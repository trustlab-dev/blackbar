"""
Document Processing Service

Centralized service for processing uploaded documents. All upload routes should use this
service to ensure consistent handling of:
- Deduplication (content hash + email message_id)
- File conversion to PDF
- OCR text extraction
- AI summary generation (respects org settings)
- GridFS storage
- Email thread consolidation
- Attachment processing

Usage:
    from src.documents.processing_service import DocumentProcessingService

    service = DocumentProcessingService(db)
    result = await service.process_upload(
        file_content=content,
        filename=file.filename,
        content_type=file.content_type,
        case_id=case_id,
        uploaded_by=user_id,
        uploaded_by_name=username,
        background_tasks=background_tasks  # Optional, for AI processing
    )
"""

import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import gridfs
from fastapi import BackgroundTasks
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import MongoClient

from src.config import MONGODB_URI
from src.utils.conversion import (
    calculate_file_hash,
    convert_to_pdf,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
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
}

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "message/rfc822",
    "application/vnd.ms-outlook",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/webp",
}

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


# =============================================================================
# Result Types
# =============================================================================


class ProcessingStatus(str, Enum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    CONVERSION_FAILED = "conversion_failed"
    VALIDATION_FAILED = "validation_failed"
    ERROR = "error"


@dataclass
class ProcessingResult:
    """Result of document processing"""

    status: ProcessingStatus
    document_id: str | None = None
    filename: str | None = None
    message: str = ""

    # Duplicate info
    is_duplicate: bool = False
    duplicate_of_id: str | None = None
    duplicate_of_filename: str | None = None

    # Processing details
    conversion_status: str = "not_needed"
    has_ocr: bool = False
    has_ai_summary: bool = False
    attachment_count: int = 0
    attachment_ids: list[str] = field(default_factory=list)

    # Thread consolidation (for emails)
    thread_consolidation: dict[str, Any] | None = None

    # Warnings/errors
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class UploadContext:
    """Context for document upload"""

    case_id: str | None = None
    uploaded_by: str = "system"
    uploaded_by_name: str = "System"

    # For contributor uploads
    contributor_id: str | None = None
    contributor_name: str | None = None

    # For collection link uploads
    collection_link_id: str | None = None
    submitter_name: str | None = None
    submitter_email: str | None = None
    submitter_notes: str | None = None

    # Processing options
    process_attachments: bool = True
    consolidate_email_threads: bool = True


# =============================================================================
# Document Processing Service
# =============================================================================


class DocumentProcessingService:
    """
    Centralized document processing service.

    Handles all document upload processing including:
    - Validation
    - Deduplication
    - Conversion to PDF
    - OCR text extraction
    - AI summary generation
    - GridFS storage
    - Email thread consolidation
    - Attachment processing
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.temp_dir = tempfile.mkdtemp(prefix="blackbar_uploads_")
        os.makedirs(self.temp_dir, exist_ok=True)

    async def process_upload(
        self,
        file_content: bytes,
        filename: str,
        content_type: str | None,
        context: UploadContext,
        background_tasks: BackgroundTasks | None = None,
    ) -> ProcessingResult:
        """
        Process an uploaded file through the complete pipeline.

        Args:
            file_content: Raw file bytes
            filename: Original filename
            content_type: MIME type (optional)
            context: Upload context with case_id, uploader info, etc.
            background_tasks: FastAPI BackgroundTasks for async AI processing

        Returns:
            ProcessingResult with document ID and processing status
        """
        result = ProcessingResult(status=ProcessingStatus.SUCCESS)

        try:
            # Step 1: Validate file
            validation_error = self._validate_file(file_content, filename, content_type)
            if validation_error:
                result.status = ProcessingStatus.VALIDATION_FAILED
                result.error = validation_error
                result.message = validation_error
                return result

            # Step 2: Calculate content hash for deduplication
            content_hash = calculate_file_hash(file_content)
            logger.info(
                f"Calculated hash for {filename}: {content_hash[:16]}... (size: {len(file_content)} bytes)"
            )

            # Step 3: Check for duplicate by content hash
            duplicate = await self._check_duplicate_by_hash(content_hash, context.case_id)
            if duplicate:
                result.status = ProcessingStatus.DUPLICATE
                result.is_duplicate = True
                result.duplicate_of_id = duplicate["id"]
                result.duplicate_of_filename = duplicate.get("filename")
                result.message = "Duplicate document detected"
                logger.info(f"Duplicate detected by hash: {filename} matches {duplicate['id']}")
                return result

            # Step 4: Convert to PDF
            ext = Path(filename).suffix.lower()
            conversion_result = await self._convert_to_pdf(file_content, filename, ext)

            if not conversion_result["success"]:
                result.status = ProcessingStatus.CONVERSION_FAILED
                result.error = conversion_result.get("error", "Conversion failed")
                result.message = f"Failed to convert {filename}"
                result.warnings.append(conversion_result.get("error", "Unknown conversion error"))
                # Still create document record for manual processing
                conversion_result["pdf_content"] = None

            pdf_content = conversion_result.get("pdf_content")
            final_filename = conversion_result.get("final_filename", filename)
            mime_type = conversion_result.get("mime_type", content_type)
            message_id = conversion_result.get("message_id")
            extracted_text = conversion_result.get("extracted_text")
            attachments = conversion_result.get("attachments", [])

            result.conversion_status = (
                "converted" if pdf_content and ext != ".pdf" else "not_needed"
            )

            # Step 5: Check for duplicate email by message_id
            if message_id and ext in [".eml", ".msg"]:
                email_duplicate = await self._check_duplicate_by_message_id(
                    message_id, context.case_id
                )
                if email_duplicate:
                    # Merge attachments into existing email if any
                    if attachments and context.process_attachments:
                        await self._merge_attachments_into_email(
                            email_duplicate, attachments, context
                        )

                    result.status = ProcessingStatus.DUPLICATE
                    result.is_duplicate = True
                    result.duplicate_of_id = email_duplicate["id"]
                    result.duplicate_of_filename = email_duplicate.get("filename")
                    result.message = "Duplicate email detected"
                    logger.info(
                        f"Duplicate email by message_id: {filename} matches {email_duplicate['id']}"
                    )
                    return result

            # Step 6: OCR text extraction
            text_data = None
            text_summary = None
            if pdf_content:
                text_data, text_summary = await self._extract_text(pdf_content, filename)
                result.has_ocr = text_data is not None

            # Step 7: AI summary generation (respects org settings)
            summary = None
            if pdf_content:
                summary = await self._generate_summary(pdf_content, final_filename, mime_type)
                result.has_ai_summary = summary is not None

            # Step 8: Store files in GridFS
            gridfs_ids = await self._store_in_gridfs(
                file_content, pdf_content, filename, final_filename, content_type, ext
            )

            # Step 9: Create document record
            document_id = str(uuid.uuid4())
            document = self._build_document_record(
                document_id=document_id,
                filename=filename,
                final_filename=final_filename,
                content_hash=content_hash,
                pdf_content=pdf_content,
                mime_type=mime_type,
                message_id=message_id,
                extracted_text=extracted_text,
                text_data=text_data,
                text_summary=text_summary,
                summary=summary,
                gridfs_ids=gridfs_ids,
                context=context,
                ext=ext,
                conversion_result=conversion_result,
            )

            # Step 10: Process attachments
            attachment_docs = []
            if attachments and context.process_attachments:
                attachment_docs = await self._process_attachments(attachments, document_id, context)
                document["attachment_ids"] = [a["id"] for a in attachment_docs]
                document["has_attachments"] = len(attachment_docs) > 0
                document["total_attachments"] = len(attachment_docs)
                result.attachment_count = len(attachment_docs)
                result.attachment_ids = document["attachment_ids"]

            # Step 11: Insert document
            await self.db.documents.insert_one(document)
            logger.info(f"Created document {document_id}: {final_filename}")

            # Step 12: Insert attachments
            if attachment_docs:
                await self.db.documents.insert_many(attachment_docs)
                logger.info(f"Created {len(attachment_docs)} attachment documents")

            # Step 13: Add to case if provided
            if context.case_id:
                await self.db.cases.update_one(
                    {"id": context.case_id}, {"$addToSet": {"document_ids": document_id}}
                )

            # Step 14: Email thread consolidation
            if ext in [".eml", ".msg"] and context.consolidate_email_threads:
                thread_result = await self._consolidate_email_thread(document, context.case_id)
                if thread_result:
                    result.thread_consolidation = thread_result

            # Step 15: Queue background AI processing if enabled
            if background_tasks and pdf_content:
                await self._queue_ai_processing(document_id, background_tasks)

            result.document_id = document_id
            result.filename = final_filename
            result.message = "Document processed successfully"

            return result

        except Exception as e:
            logger.error(f"Error processing document {filename}: {str(e)}", exc_info=True)
            result.status = ProcessingStatus.ERROR
            result.error = str(e)
            result.message = f"Error processing document: {str(e)}"
            return result

    # =========================================================================
    # Validation
    # =========================================================================

    def _validate_file(self, content: bytes, filename: str, content_type: str | None) -> str | None:
        """Validate file extension, size, and MIME type. Returns error message or None."""
        ext = Path(filename).suffix.lower()

        if ext not in ALLOWED_EXTENSIONS:
            return f"Invalid file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"

        if len(content) > MAX_FILE_SIZE:
            return f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)}MB"

        if content_type and content_type not in ALLOWED_MIME_TYPES:
            return f"Invalid MIME type '{content_type}' for {filename}. Upload a supported file format."

        return None

    # =========================================================================
    # Deduplication
    # =========================================================================

    async def _check_duplicate_by_hash(self, content_hash: str, case_id: str | None) -> dict | None:
        """Check for duplicate by content hash."""
        query = {"content_hash": content_hash}
        if case_id:
            query["case_id"] = case_id
        return await self.db.documents.find_one(query)

    async def _check_duplicate_by_message_id(
        self, message_id: str, case_id: str | None
    ) -> dict | None:
        """Check for duplicate email by message_id."""
        query = {"message_id": message_id}
        if case_id:
            query["case_id"] = case_id
        return await self.db.documents.find_one(query)

    # =========================================================================
    # Conversion
    # =========================================================================

    async def _convert_to_pdf(self, content: bytes, filename: str, ext: str) -> dict[str, Any]:
        """Convert file to PDF. Returns dict with pdf_content, final_filename, etc."""
        result = {
            "success": False,
            "pdf_content": None,
            "final_filename": filename,
            "mime_type": "application/pdf",
            "message_id": None,
            "extracted_text": None,
            "attachments": [],
            "error": None,
        }

        try:
            if ext == ".pdf":
                result["success"] = True
                result["pdf_content"] = content
                result["final_filename"] = filename
                return result

            # Save to temp file for conversion
            temp_input = os.path.join(self.temp_dir, f"{uuid.uuid4()}{ext}")
            with open(temp_input, "wb") as f:
                f.write(content)

            try:
                conversion = convert_to_pdf(temp_input, self.temp_dir)

                if conversion["success"]:
                    with open(conversion["pdf_path"], "rb") as f:
                        result["pdf_content"] = f.read()

                    # Build final filename
                    original_name = Path(filename).stem
                    result["final_filename"] = f"{original_name}{ext}.pdf"
                    result["success"] = True
                    result["message_id"] = conversion.get("message_id")
                    result["extracted_text"] = conversion.get("extracted_text")
                    result["attachments"] = conversion.get("attachments", [])

                    # Set appropriate MIME type for emails
                    if ext == ".eml":
                        result["mime_type"] = "message/rfc822"
                    elif ext == ".msg":
                        result["mime_type"] = "application/vnd.ms-outlook"
                else:
                    result["error"] = conversion.get("error", "Conversion failed")

            finally:
                # Cleanup temp file
                if os.path.exists(temp_input):
                    os.remove(temp_input)

            return result

        except Exception as e:
            logger.error(f"Conversion error for {filename}: {str(e)}")
            result["error"] = str(e)
            return result

    # =========================================================================
    # Text Extraction (OCR)
    # =========================================================================

    async def _extract_text(
        self, pdf_content: bytes, filename: str
    ) -> tuple[dict | None, str | None]:
        """Extract text with OCR coordinates from PDF."""
        try:
            from src.documents.routes import extract_text_with_coordinates, get_text_summary

            text_data = await extract_text_with_coordinates(pdf_content)
            text_summary = get_text_summary(text_data)

            logger.info(
                f"Extracted {len(text_data.get('full_text', ''))} characters from {filename}"
            )

            # Limit text_data to prevent MongoDB size issues
            max_pages = 50
            if len(text_data.get("pages", [])) > max_pages:
                logger.warning(f"Limiting pages from {len(text_data['pages'])} to {max_pages}")
                text_data["pages"] = text_data["pages"][:max_pages]
                text_data["truncated"] = True

            if len(text_data.get("full_text", "")) > 500000:
                logger.warning("Truncating full_text to 500000 chars")
                text_data["full_text"] = text_data["full_text"][:500000]
                text_data["truncated"] = True

            return text_data, text_summary

        except Exception as e:
            logger.error(f"OCR failed for {filename}: {str(e)}")
            return None, None

    # =========================================================================
    # AI Summary
    # =========================================================================

    async def _generate_summary(
        self, pdf_content: bytes, filename: str, mime_type: str
    ) -> str | None:
        """Generate AI summary if enabled in org settings."""
        try:
            from src.admin.config_routes import get_system_config
            from src.documents.routes import generate_document_summary

            # Check org settings
            system_config = await get_system_config(self.db)
            if not system_config.get("auto_generate_ai_suggestions", False):
                logger.info(f"AI summary disabled, skipping for {filename}")
                return None

            summary = await generate_document_summary(pdf_content, filename, mime_type)
            return summary

        except Exception as e:
            logger.error(f"AI summary generation failed for {filename}: {str(e)}")
            return None

    # =========================================================================
    # GridFS Storage
    # =========================================================================

    async def _store_in_gridfs(
        self,
        original_content: bytes,
        pdf_content: bytes | None,
        original_filename: str,
        pdf_filename: str,
        content_type: str | None,
        ext: str,
    ) -> dict[str, Any]:
        """Store files in GridFS. Returns dict with file IDs."""
        result = {"content_file_id": None, "original_file_id": None}

        try:
            # Use synchronous PyMongo for GridFS
            # Use the same database name as the db to ensure consistency
            sync_client = MongoClient(MONGODB_URI)
            db_name = self.db.name  # Use actual database name from db
            sync_db = sync_client[db_name]
            fs = gridfs.GridFS(sync_db)

            # Store PDF content (or original if no PDF)
            content_to_store = pdf_content if pdf_content else original_content
            store_filename = pdf_filename if pdf_content else original_filename
            store_content_type = "application/pdf" if pdf_content else content_type

            result["content_file_id"] = fs.put(
                content_to_store, filename=store_filename, content_type=store_content_type
            )
            logger.info(
                f"Stored content in GridFS: {result['content_file_id']} ({len(content_to_store)} bytes)"
            )

            # Store original if it was converted
            if pdf_content and ext != ".pdf":
                result["original_file_id"] = fs.put(
                    original_content, filename=original_filename, content_type=content_type
                )
                logger.info(
                    f"Stored original in GridFS: {result['original_file_id']} ({len(original_content)} bytes)"
                )

            sync_client.close()

        except Exception as e:
            logger.error(f"GridFS storage error: {str(e)}")

        return result

    # =========================================================================
    # Document Record Building
    # =========================================================================

    def _build_document_record(
        self,
        document_id: str,
        filename: str,
        final_filename: str,
        content_hash: str,
        pdf_content: bytes | None,
        mime_type: str,
        message_id: str | None,
        extracted_text: str | None,
        text_data: dict | None,
        text_summary: str | None,
        summary: str | None,
        gridfs_ids: dict[str, Any],
        context: UploadContext,
        ext: str,
        conversion_result: dict,
    ) -> dict[str, Any]:
        """Build the document record for MongoDB."""
        now = datetime.utcnow()

        document = {
            "id": document_id,
            "filename": final_filename,
            "original_filename": filename if ext != ".pdf" else None,
            "content_hash": content_hash,
            "mime_type": mime_type,
            "size": len(pdf_content) if pdf_content else 0,
            "upload_date": now,
            "uploaded_at": now,
            "updated_at": now,
            # GridFS references (no binary content in document)
            "content_file_id": gridfs_ids.get("content_file_id"),
            "original_file_id": gridfs_ids.get("original_file_id"),
            # Text extraction
            "text_data": text_data,
            "text_summary": text_summary,
            "extracted_text": extracted_text,
            # AI summary
            "summary": summary,
            # Processing status
            "status": "new",
            "processing_status": "ocr_complete" if text_data else "pending",
            "conversion_status": "converted" if pdf_content and ext != ".pdf" else "not_needed",
            # Relationships
            "case_id": context.case_id,
            "redactions": [],
            "has_attachments": False,
            "attachment_ids": [],
            # Uploader info
            "uploaded_by": context.uploaded_by,
            "uploaded_by_name": context.uploaded_by_name,
        }

        # Add contributor info if present
        if context.contributor_id:
            document["uploaded_by_contributor"] = context.contributor_id
            document["contributor_name"] = context.contributor_name

        # Add collection link info if present
        if context.collection_link_id:
            document["collection_link_id"] = context.collection_link_id
            document["submitter_name"] = context.submitter_name
            document["submitter_email"] = context.submitter_email
            document["submitter_notes"] = context.submitter_notes

        # Add email-specific fields
        if ext in [".eml", ".msg"]:
            document["message_id"] = message_id
            if ext == ".eml":
                document["original_mime_type"] = "message/rfc822"
            elif (
                ext == ".msg"
            ):  # pragma: no branch  # guarded by outer `ext in [.eml,.msg]`; B23 in audit Section 11
                document["original_mime_type"] = "application/vnd.ms-outlook"
            document["converted_mime_type"] = "application/pdf"

        return document

    # =========================================================================
    # Attachment Processing
    # =========================================================================

    async def _process_attachments(
        self, attachments: list[dict], parent_document_id: str, context: UploadContext
    ) -> list[dict]:
        """Process email attachments as separate documents."""
        attachment_docs = []

        for attachment in attachments:
            try:
                att_filename = attachment.get("filename", "attachment")
                att_path = attachment.get("path")
                att_mime = attachment.get("mime_type", "application/octet-stream")

                if not att_path or not os.path.exists(att_path):
                    logger.warning(f"Attachment file not found: {att_path}")
                    continue

                logger.info(f"Processing attachment: {att_filename}")

                # Convert attachment to PDF
                conversion = convert_to_pdf(att_path, self.temp_dir)

                if not conversion["success"]:
                    logger.warning(
                        f"Could not convert attachment {att_filename}: {conversion.get('error')}"
                    )
                    continue

                with open(conversion["pdf_path"], "rb") as f:
                    att_pdf_content = f.read()

                # OCR and summary for attachment
                att_text_data, att_text_summary = await self._extract_text(
                    att_pdf_content, att_filename
                )
                att_summary = await self._generate_summary(
                    att_pdf_content, att_filename, "application/pdf"
                )

                # Store in GridFS. Phase 4 Batch 4.4 (audit B25/B58):
                # open() in a `with` block to release the file handle
                # eagerly; the prior `open(att_path, "rb").read()`
                # without a `with` left the FD open until GC.
                with open(att_path, "rb") as att_f:
                    att_original_bytes = att_f.read()

                att_gridfs = await self._store_in_gridfs(
                    att_original_bytes,
                    att_pdf_content,
                    att_filename,
                    Path(att_filename).stem + ".pdf",
                    att_mime,
                    Path(att_filename).suffix.lower(),
                )

                # Create attachment document
                att_id = str(uuid.uuid4())
                att_doc = {
                    "id": att_id,
                    "filename": Path(att_filename).stem + ".pdf",
                    "original_filename": att_filename,
                    "content_hash": calculate_file_hash(att_pdf_content),
                    "mime_type": "application/pdf",
                    "original_mime_type": att_mime,
                    "size": len(att_pdf_content),
                    "upload_date": datetime.utcnow(),
                    "uploaded_at": datetime.utcnow(),
                    # GridFS
                    "content_file_id": att_gridfs.get("content_file_id"),
                    "original_file_id": att_gridfs.get("original_file_id"),
                    # Text
                    "text_data": att_text_data,
                    "text_summary": att_text_summary,
                    "summary": att_summary,
                    # Status
                    "status": "new",
                    "processing_status": "ocr_complete" if att_text_data else "pending",
                    # Relationships
                    "is_attachment": True,
                    "parent_document_id": parent_document_id,
                    "case_id": context.case_id,
                    "redactions": [],
                    # Uploader
                    "uploaded_by": context.uploaded_by,
                    "uploaded_by_name": context.uploaded_by_name,
                }

                attachment_docs.append(att_doc)
                logger.info(f"Processed attachment {att_filename} -> {att_id}")

            except Exception as e:
                logger.error(f"Failed to process attachment {attachment.get('filename')}: {str(e)}")

        return attachment_docs

    async def _merge_attachments_into_email(
        self, existing_email: dict, new_attachments: list[dict], context: UploadContext
    ) -> int:
        """Merge new attachments into an existing duplicate email."""
        # This handles the case where the same email is uploaded again
        # but might have different/additional attachments
        merged_count = 0

        existing_att_ids = existing_email.get("attachment_ids", [])

        for attachment in new_attachments:
            try:
                # Check if this attachment already exists (by filename + size)
                att_filename = attachment.get("filename")
                att_path = attachment.get("path")

                if not att_path or not os.path.exists(att_path):
                    continue

                att_size = os.path.getsize(att_path)

                # Check existing attachments
                existing_atts = await self.db.documents.find(
                    {"id": {"$in": existing_att_ids}}
                ).to_list(length=1000)

                is_duplicate = any(
                    a.get("original_filename") == att_filename and a.get("size") == att_size
                    for a in existing_atts
                )

                if is_duplicate:
                    continue

                # Process and add new attachment
                att_docs = await self._process_attachments(
                    [attachment], existing_email["id"], context
                )

                if att_docs:
                    await self.db.documents.insert_many(att_docs)
                    new_ids = [a["id"] for a in att_docs]

                    await self.db.documents.update_one(
                        {"id": existing_email["id"]},
                        {
                            "$push": {"attachment_ids": {"$each": new_ids}},
                            "$set": {"has_attachments": True},
                        },
                    )
                    merged_count += len(att_docs)

            except Exception as e:
                logger.error(f"Error merging attachment: {str(e)}")

        return merged_count

    # =========================================================================
    # Email Thread Consolidation
    # =========================================================================

    async def _consolidate_email_thread(self, document: dict, case_id: str | None) -> dict | None:
        """Consolidate email threads (find related emails, mark superseded)."""
        try:
            from src.documents.routes import (
                consolidate_email_thread,
                extract_thread_identifiers,
                find_thread_emails,
            )

            extracted_text = document.get("extracted_text", "")
            message_id = document.get("message_id")

            if not extracted_text:
                return None

            thread_identifiers = extract_thread_identifiers(extracted_text, message_id)
            if not thread_identifiers:
                return None

            # Update document with thread metadata
            await self.db.documents.update_one(
                {"id": document["id"]},
                {"$set": {"thread_metadata": thread_identifiers, "thread_status": "pending"}},
            )

            # Find related emails
            thread_emails = await find_thread_emails(self.db, thread_identifiers, case_id)

            if not thread_emails:
                await self.db.documents.update_one(
                    {"id": document["id"]}, {"$set": {"thread_status": "active"}}
                )
                return None

            # Consolidate thread
            result = await consolidate_email_thread(self.db, document, thread_emails)
            logger.info(f"Thread consolidation result: {result}")

            return result

        except Exception as e:
            logger.error(f"Email thread consolidation error: {str(e)}")
            return None

    # =========================================================================
    # Background AI Processing
    # =========================================================================

    async def _queue_ai_processing(
        self, document_id: str, background_tasks: BackgroundTasks
    ) -> None:
        """Queue AI suggestion generation as background task if enabled."""
        try:
            from src.admin.config_routes import get_system_config
            from src.database import db as main_db
            from src.documents.routes import generate_ai_suggestions_async

            system_config = await get_system_config(self.db)

            if not system_config.get("auto_generate_ai_suggestions", False):
                return

            # Read AI timeout from admin settings
            global_ai_config = await main_db.system_config.find_one({"id": "global_ai_settings"})
            ai_timeout = (
                global_ai_config.get("ai_suggestion_timeout", 120) if global_ai_config else 120
            )

            await self.db.documents.update_one(
                {"id": document_id}, {"$set": {"processing_status": "ai_queued"}}
            )

            background_tasks.add_task(
                generate_ai_suggestions_async, document_id, ai_timeout, self.db
            )

            logger.info(
                f"Queued AI suggestion generation for {document_id} (timeout: {ai_timeout}s)"
            )

        except Exception as e:
            logger.error(f"Error queuing AI processing: {str(e)}")
