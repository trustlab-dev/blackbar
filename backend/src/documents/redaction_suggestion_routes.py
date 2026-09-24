"""
AI redaction-suggestion routes — AI/bulk-driven redaction proposals,
distinct from the manual redaction CRUD in redaction_routes.py.

Split from documents/routes.py in Phase 1.5 (2026-05-11) to keep individual
route modules tractable. Mounted via include_router in documents/routes.py.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from src.utils.ai_redaction import (
    enrich_suggestions_with_coordinates,
    find_text_in_ocr_data,
    get_quick_pii_suggestions,
    get_redaction_suggestions,
)
from src.utils.bulk_redaction import (
    create_redaction_template,
    locate_text_in_pdf,
    pdf_page_geometry,
    preview_bulk_redaction,
)
from src.utils.pdf_limits import PdfLimitExceeded
from src.utils.redaction_records import (
    APPROVED,
    RedactionValidationError,
    new_redaction_record,
    validate_redaction,
)

from ..core.database import get_database_from_request
from ..database import db
from ..dependencies import check_role, get_current_user
from .redaction_store import load_document_pdf

logger = logging.getLogger(__name__)

router = APIRouter()


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


@router.get(
    "/{document_id}/redaction-suggestions",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def get_document_redaction_suggestions(
    request: Request,
    document_id: str,
    quick: bool = False,
    force_regenerate: bool = False,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Get AI-powered redaction suggestions for a document.
    Caches suggestions in database to avoid re-calling OpenAI.

    Args:
        document_id: Document ID
        quick: If True, use quick PII detection (no AI). If False, use full AI analysis.
        force_regenerate: If True, regenerate suggestions even if cached
    """
    # In demo mode there is no live LLM: never call it and never overwrite
    # the curated `ai_suggestions` snapshot (a visitor clicking "Regenerate"
    # must not wipe the demo for everyone until the next nightly reset).
    demo_mode = os.getenv("BLACKBAR_DEMO_MODE", "").lower() == "true"

    # Find document
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if text has been extracted (support both old and new formats)
    extracted_text = doc.get("extracted_text")

    # If no extracted_text, try to get from text_data (new OCR format)
    if not extracted_text:
        text_data = doc.get("text_data")
        if text_data and text_data.get("full_text"):
            extracted_text = text_data.get("full_text")

    if not extracted_text:
        return {
            "suggestions": [],
            "summary": "No text extracted from document yet. Text extraction may still be in progress.",
            "status": "no_text",
        }

    try:
        # Check if we have cached suggestions. In demo mode we ALWAYS prefer
        # the cache and ignore force_regenerate — there is no live LLM.
        if (not force_regenerate or demo_mode) and doc.get("ai_suggestions") and not quick:
            cached = doc.get("ai_suggestions", {})
            cached_suggestions = cached.get("suggestions", [])

            # Auto-regenerate if cache is empty (zero entries)
            if len(cached_suggestions) == 0:
                if demo_mode:
                    # Nothing to regenerate with in demo mode — return empty
                    # without touching the snapshot.
                    return {
                        "suggestions": [],
                        "summary": cached.get("summary", ""),
                        "status": "demo_no_suggestions",
                        "method": cached.get("method", "seeded"),
                    }
                logger.info(
                    f"Cached AI suggestions empty for document {document_id}, auto-regenerating..."
                )
                # Fall through to regeneration below
            else:
                logger.info(
                    f"Returning cached AI suggestions for document {document_id} ({len(cached_suggestions)} suggestions)"
                )

                # Enrich cached suggestions with coordinates if not already present
                text_data = doc.get("text_data")
                needs_enrichment = any(
                    not s.get("coordinates") and not s.get("bbox") for s in cached_suggestions
                )
                pdf_content = await load_document_pdf(doc, db) if needs_enrichment else None
                if pdf_content:
                    logger.info("Enriching cached suggestions with coordinates")
                    cached_suggestions = await asyncio.to_thread(
                        enrich_suggestions_with_coordinates,
                        cached_suggestions,
                        pdf_content,
                        text_data,
                    )

                # Mark rejected suggestions
                rejected_suggestions = doc.get("rejected_ai_suggestions", [])
                rejected_texts = {r["text"] for r in rejected_suggestions}

                for suggestion in cached_suggestions:
                    if suggestion.get("text") in rejected_texts:
                        suggestion["rejected"] = True

                return {
                    "suggestions": cached_suggestions,
                    "summary": cached.get("summary", ""),
                    "status": "cached",
                    "method": cached.get("method", "openai_gpt4"),
                    "generated_at": cached.get("generated_at"),
                }

        if quick:
            # Quick PII detection using patterns
            suggestions = get_quick_pii_suggestions(extracted_text)

            # Enrich with coordinates (GridFS-backed documents too, DOC-12)
            pdf_content = await load_document_pdf(doc, db)
            text_data = doc.get("text_data")
            if pdf_content:
                suggestions = await asyncio.to_thread(
                    enrich_suggestions_with_coordinates, suggestions, pdf_content, text_data
                )

            return {
                "suggestions": suggestions,
                "summary": f"Found {len(suggestions)} potential PII items using pattern matching",
                "status": "quick",
                "method": "pattern_matching",
            }
        else:
            # Full AI analysis. In demo mode there is no live LLM and no
            # snapshot exists for this document — return empty without calling
            # the LLM or persisting an (empty) cache.
            if demo_mode:
                return {
                    "suggestions": [],
                    "summary": "AI suggestions are pre-generated in this demo.",
                    "status": "demo_no_suggestions",
                    "method": "seeded",
                }

            # Get case context if available
            context = None
            if doc.get("case_id"):
                case = await db.cases.find_one({"id": doc["case_id"]})
                if case:
                    context = f"Case: {case.get('title', 'Unknown')}. Type: FOI Request"

            result = await get_redaction_suggestions(extracted_text, context)
            suggestions = result.get("suggestions", [])

            # Enrich with coordinates by searching PDF
            pdf_content = await load_document_pdf(doc, db)
            text_data = doc.get("text_data")
            if pdf_content:
                suggestions = await asyncio.to_thread(
                    enrich_suggestions_with_coordinates, suggestions, pdf_content, text_data
                )
                result["suggestions"] = suggestions

            # Cache the results in the document
            cache_data = {
                "suggestions": suggestions,
                "summary": result.get("summary", ""),
                "method": "openai_gpt4",
                "generated_at": datetime.utcnow(),
            }

            await db.documents.update_one(
                {"id": document_id}, {"$set": {"ai_suggestions": cache_data}}
            )

            logger.info(
                f"Generated and cached {len(suggestions)} AI suggestions for document {document_id}"
            )

            result["status"] = "ai_complete"
            result["method"] = "openai_gpt4"
            return result

    except Exception as e:
        logger.error(f"Error generating redaction suggestions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating suggestions: {str(e)}")


# BULK REDACTION TOOLS


@router.post(
    "/bulk/preview-redaction", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def preview_bulk_redaction_endpoint(
    case_id: str = Body(...),
    search_text: str = Body(...),
    category: str = Body(...),
    current_user=Depends(get_current_user),
):
    """
    Preview what would be redacted across multiple db.documents.

    Args:
        case_id: Case ID to search within
        search_text: Text to find and redact
        category: Redaction category (e.g., S22)
    """
    if not search_text or len(search_text) < 2:
        raise HTTPException(status_code=400, detail="Search text must be at least 2 characters")

    # Get all documents in case (exclude duplicates)
    case_documents = await db.documents.find(
        {"case_id": case_id, "is_duplicate": {"$ne": True}}
    ).to_list(None)

    if not case_documents:
        raise HTTPException(status_code=404, detail="No documents found in case")

    # Generate preview
    preview = preview_bulk_redaction(case_documents, search_text, category)

    return preview


@router.post(
    "/bulk/apply-redaction", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def apply_bulk_redaction_endpoint(
    case_id: str = Body(...),
    search_text: str = Body(...),
    category: str = Body(...),
    reason: str = Body(...),
    current_user=Depends(get_current_user),
):
    """
    Apply redactions to all occurrences of text across db.documents.

    Args:
        case_id: Case ID to apply redactions within
        search_text: Text to redact
        category: Redaction category
        reason: Reason for redaction
    """
    if not search_text or len(search_text) < 2:
        raise HTTPException(status_code=400, detail="Search text must be at least 2 characters")

    # Get all documents in case (exclude duplicates)
    case_documents = await db.documents.find(
        {"case_id": case_id, "is_duplicate": {"$ne": True}}
    ).to_list(None)

    if not case_documents:
        raise HTTPException(status_code=404, detail="No documents found in case")

    # Locate every occurrence on the real pages (DOC-02). Records are built
    # and validated for all documents before anything is written, so a bad
    # box fails the whole request (422) instead of being stored.
    needle = search_text.casefold()
    planned: dict[str, list[dict]] = {}
    matches: dict[str, dict] = {}
    unresolved: list[dict] = []
    errors: list[str] = []

    for doc in case_documents:
        doc_id = doc.get("id")
        text_source = (
            doc.get("extracted_text") or (doc.get("text_data") or {}).get("full_text") or ""
        )
        text_count = text_source.casefold().count(needle)

        def _unresolved(reason: str, located: int = 0, _doc=doc, _count=text_count) -> None:
            unresolved.append(
                {
                    "document_id": _doc.get("id"),
                    "filename": _doc.get("filename"),
                    "occurrences": _count,
                    "located": located,
                    "reason": reason,
                }
            )

        if doc.get("conversion_failed") or doc.get("status") == "conversion_failed":
            if text_count:
                _unresolved("document failed conversion to PDF")
            continue
        pdf_content = await load_document_pdf(doc, db)
        if not pdf_content:
            if text_count:
                _unresolved("document content is not available")
            continue
        try:
            hits, page_sizes, _ = await asyncio.to_thread(
                locate_text_in_pdf, pdf_content, search_text
            )
        except PdfLimitExceeded as exc:
            if text_count:
                _unresolved(str(exc))
            continue
        except Exception:
            if text_count:
                _unresolved("document content is not a readable PDF")
            continue
        if not hits and doc.get("text_data"):
            # Scanned pages: OCR word boxes are already in displayed space.
            hits = find_text_in_ocr_data(search_text, doc["text_data"])
        if not hits:
            if text_count:
                _unresolved("text appears in the extracted text but was not found on any page")
            continue

        records = []
        for hit in hits:
            try:
                geometry = validate_redaction(hit, page_sizes)
            except RedactionValidationError as exc:
                errors.append(f"document {doc_id}: {exc}")
                continue
            records.append(
                new_redaction_record(
                    geometry,
                    status=APPROVED,
                    created_by=current_user.get("id"),
                    created_by_role=current_user.get("role"),
                    source="bulk_text",
                    created_by_name=current_user.get("username", "unknown"),
                    text=search_text,
                    category=category,
                    reason=reason,
                    bulk_operation=True,
                )
            )
        planned[doc_id] = records
        matches[doc_id] = {
            "document_id": doc_id,
            "filename": doc.get("filename"),
            "count": len(records),
        }
        if text_count > len(records):
            _unresolved(
                f"only {len(records)} of {text_count} occurrences were located on the pages",
                located=len(records),
            )

    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Some redactions could not be placed; nothing was saved.",
                "errors": errors,
            },
        )

    documents_affected = 0
    redactions_created = 0
    for doc_id, records in planned.items():
        if not records:
            continue
        await db.documents.update_one({"id": doc_id}, {"$push": {"redactions": {"$each": records}}})
        documents_affected += 1
        redactions_created += len(records)

    # Log in case audit trail
    case = await db.cases.find_one({"id": case_id})
    if case:
        audit_entry = {
            "action": "bulk_redaction_applied",
            "user_id": current_user.get("id", "unknown"),
            "username": current_user.get("username", "unknown"),
            "timestamp": datetime.utcnow(),
            "details": {
                "search_text": search_text,
                "category": category,
                "documents_affected": documents_affected,
                "redactions_created": redactions_created,
                "unresolved_documents": len(unresolved),
            },
        }

        await db.cases.update_one({"id": case_id}, {"$push": {"audit_log": audit_entry}})

    if not redactions_created and not unresolved:
        message = "No matches found"
    else:
        message = f"Created {redactions_created} redactions across {documents_affected} documents"
    if unresolved:
        message += (
            f"; {len(unresolved)} document(s) have occurrences that could not be located "
            "and must be redacted manually"
        )
    return {
        "success": not unresolved,
        "message": message,
        "documents_affected": documents_affected,
        "redactions_created": redactions_created,
        "unresolved_documents": unresolved,
        "matches": matches,
    }


@router.post(
    "/bulk/create-template", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def create_redaction_template_endpoint(
    name: str = Body(...),
    pattern: str = Body(...),
    category: str = Body(...),
    reason: str = Body(...),
    description: str = Body(None),
    current_user=Depends(get_current_user),
):
    """
    Create a reusable redaction template.

    Args:
        name: Template name
        pattern: Text pattern to redact
        category: Redaction category
        reason: Reason for redaction
        description: Optional description
    """
    template = create_redaction_template(name, pattern, category, reason, description)
    template["created_by"] = current_user.get("username", "unknown")
    template["id"] = str(uuid.uuid4())

    # Store template in database (would need a templates collection)
    # For now, just return the template

    return {"success": True, "template": template}


@router.post(
    "/{document_id}/ai-feedback",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def record_ai_feedback(
    document_id: str,
    suggestion_text: str = Body(...),
    suggestion_category: str = Body(...),
    suggestion_reason: str = Body(...),
    feedback: str = Body(...),  # "accepted" or "rejected"
    context: str = Body(None),
    current_user=Depends(get_current_user),
):
    """
    Record user feedback on AI redaction suggestions for model fine-tuning.

    Args:
        document_id: Document ID
        suggestion_text: The text that was suggested for redaction
        suggestion_category: The category suggested
        suggestion_reason: The reason provided by AI
        feedback: "accepted" or "rejected"
        context: Additional context (e.g., "user_rejected_suggestion", "user_rejected_bulk")
    """
    import logging

    logger = logging.getLogger(__name__)

    # Create feedback record
    feedback_record = {
        "id": str(uuid.uuid4()),
        "document_id": document_id,
        "suggestion_text": suggestion_text,
        "suggestion_category": suggestion_category,
        "suggestion_reason": suggestion_reason,
        "feedback": feedback,
        "context": context,
        "user_id": current_user["id"],
        "username": current_user.get("username", "unknown"),
        "timestamp": datetime.utcnow(),
    }

    # Store in ai_feedback collection for later analysis/fine-tuning
    ai_feedback = db["ai_feedback"]
    await ai_feedback.insert_one(feedback_record)

    # Also store rejection in document metadata so it persists across refreshes
    if feedback == "rejected":
        await db.documents.update_one(
            {"id": document_id},
            {
                "$addToSet": {
                    "rejected_ai_suggestions": {
                        "text": suggestion_text,
                        "category": suggestion_category,
                        "reason": suggestion_reason,
                        "rejected_by": current_user.get("username", "unknown"),
                        "rejected_at": datetime.utcnow(),
                    }
                }
            },
        )

    logger.info(
        f"AI feedback recorded: {feedback} for suggestion '{suggestion_text[:50]}...' by {current_user.get('username')}"
    )

    return {"success": True, "message": "Feedback recorded successfully"}


@router.post(
    "/bulk/apply-ai-suggestions", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def apply_ai_suggestions_bulk_endpoint(
    request: Request,
    case_id: str = Body(...),
    category_filter: str | None = Body(None),
    db=Depends(get_db),
    confidence_threshold: str = Body("medium"),
    current_user=Depends(get_current_user),
):
    """
    Apply AI redaction suggestions to all documents in a case.

    Args:
        case_id: Case ID
        category_filter: Optional category filter (e.g., "personal_info")
        confidence_threshold: Minimum confidence (low, medium, high)
    """
    # Get all documents in case
    case_documents = await db.documents.find({"case_id": case_id}).to_list(None)

    if not case_documents:
        raise HTTPException(status_code=404, detail="No documents found in case")

    confidence_levels = {"low": 0, "medium": 1, "high": 2}
    min_confidence = confidence_levels.get(confidence_threshold, 1)

    # Build and validate every record before writing any (DOC-02): the
    # geometry lives under suggestion["coordinates"]; a suggestion whose box
    # does not fit its page fails the request with 422.
    planned: dict[str, list[dict]] = {}
    errors: list[str] = []
    skipped_without_coordinates = 0
    skipped_rejected = 0

    for doc in case_documents:
        doc_id = doc.get("id")
        ai_suggestions = doc.get("ai_suggestions", {}).get("suggestions", [])
        if not ai_suggestions:
            continue
        rejected_texts = {
            (r.get("text") or "").casefold() for r in doc.get("rejected_ai_suggestions", [])
        }

        filtered_suggestions = []
        for suggestion in ai_suggestions:
            if category_filter and suggestion.get("category") != category_filter:
                continue
            conf = suggestion.get("confidence", "medium")
            if confidence_levels.get(conf, 1) < min_confidence:
                continue
            if (suggestion.get("text") or "").casefold() in rejected_texts:
                skipped_rejected += 1
                continue
            if not suggestion.get("has_coordinates") or not suggestion.get("coordinates"):
                skipped_without_coordinates += 1
                continue
            filtered_suggestions.append(suggestion)

        if not filtered_suggestions:
            continue

        if doc.get("conversion_failed") or doc.get("status") == "conversion_failed":
            errors.append(f"document {doc_id}: failed conversion to PDF")
            continue
        pdf_content = await load_document_pdf(doc, db)
        if not pdf_content:
            errors.append(f"document {doc_id}: content is not available")
            continue
        try:
            page_sizes, rotations = await asyncio.to_thread(pdf_page_geometry, pdf_content)
        except Exception as exc:
            errors.append(f"document {doc_id}: {exc}")
            continue

        records: list[dict] = []
        relocated: set[tuple[int, str]] = set()
        for index, suggestion in enumerate(filtered_suggestions):
            text = suggestion.get("text") or ""
            page = suggestion.get("page")
            coords = suggestion.get("coordinates") or {}
            candidates = [
                {"page": page, **{k: coords.get(k) for k in ("x", "y", "width", "height")}}
            ]
            # Text-search coordinates are in unrotated page space; on a
            # rotated page re-locate the text in displayed space (DOC-04).
            if (
                isinstance(page, int)
                and 1 <= page <= len(rotations)
                and rotations[page - 1]
                and text.strip()
            ):
                key = (page, text.casefold())
                if key in relocated:
                    continue
                hits, _, _ = await asyncio.to_thread(locate_text_in_pdf, pdf_content, text, {page})
                if hits:
                    candidates = hits
                    relocated.add(key)

            for candidate in candidates:
                try:
                    geometry = validate_redaction(candidate, page_sizes)
                except RedactionValidationError as exc:
                    errors.append(f"document {doc_id}, suggestion {index}: {exc}")
                    continue
                records.append(
                    new_redaction_record(
                        geometry,
                        status=APPROVED,
                        created_by=current_user.get("id"),
                        created_by_role=current_user.get("role"),
                        source="ai_bulk_apply",
                        created_by_name=current_user.get("username", "unknown"),
                        text=text,
                        category=suggestion.get("section", suggestion.get("category", "S22")),
                        reason=suggestion.get("reason", "AI suggested"),
                        confidence=suggestion.get("confidence"),
                    )
                )
        planned[doc_id] = records

    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Some AI suggestions could not be applied; nothing was saved.",
                "errors": errors,
            },
        )

    documents_processed = 0
    suggestions_applied = 0
    for doc_id, records in planned.items():
        if not records:
            continue
        await db.documents.update_one({"id": doc_id}, {"$push": {"redactions": {"$each": records}}})
        documents_processed += 1
        suggestions_applied += len(records)

    # Log in case audit trail
    case = await db.cases.find_one({"id": case_id})
    if case:
        audit_entry = {
            "action": "ai_suggestions_bulk_applied",
            "user_id": current_user.get("id", "unknown"),
            "username": current_user.get("username", "unknown"),
            "timestamp": datetime.utcnow(),
            "details": {
                "category_filter": category_filter,
                "confidence_threshold": confidence_threshold,
                "documents_processed": documents_processed,
                "suggestions_applied": suggestions_applied,
            },
        }

        await db.cases.update_one({"id": case_id}, {"$push": {"audit_log": audit_entry}})

    return {
        "success": True,
        "message": f"Applied {suggestions_applied} AI suggestions across {documents_processed} documents",
        "documents_processed": documents_processed,
        "suggestions_applied": suggestions_applied,
        "skipped_without_coordinates": skipped_without_coordinates,
        "skipped_rejected": skipped_rejected,
    }


@router.delete(
    "/{document_id}/redaction-suggestions/cache",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def clear_ai_suggestions_cache(document_id: str, current_user=Depends(get_current_user)):
    """
    Clear cached AI suggestions for a document.
    Forces regeneration on next request.
    """
    result = await db.documents.update_one({"id": document_id}, {"$unset": {"ai_suggestions": ""}})

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Document not found or no cache to clear")

    logger.info(
        f"Cleared AI suggestions cache for document {document_id} by {current_user.get('username')}"
    )

    return {
        "success": True,
        "message": "AI suggestions cache cleared. Next request will regenerate suggestions.",
    }
