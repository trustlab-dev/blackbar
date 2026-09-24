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
from typing import Literal

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


# Result fields surfaced from a generation (and its cache) to the client.
_ANALYSIS_FIELDS = (
    "analysis_truncated",
    "analysed_chars",
    "total_chars",
    "chunks",
    "output_truncated",
    "invalid_suggestions",
    "disclosed_count",
    "provider",
    "model",
    "config_id",
    "endpoint_host",
    "error",
    "error_code",
    "reference",
)
# Error codes raised before any document text left the server: such results
# are not cached, so the next request tries again once AI is fixed.
_NO_EGRESS_ERRORS = {
    "ai_disabled",
    "ai_not_configured",
    "api_key_required",
    "endpoint_not_allowed",
    "prompt_setup_failed",
}


async def _auto_generate_enabled(database) -> bool:
    from src.admin.config_routes import get_system_config

    config = await get_system_config(database)
    return bool(config.get("auto_generate_ai_suggestions", False))


def _enforce_llm_limits(current_user: dict, doc: dict) -> None:
    """Per-user rate limit and per-document cooldown on user-triggered LLM
    analysis (LLM-14). Raises 429 with Retry-After."""
    from limits import parse

    from src.config import llm_settings
    from src.core.rate_limit import limiter

    cooldown = llm_settings.regenerate_cooldown_seconds
    last = doc.get("last_llm_request_at")
    if cooldown and isinstance(last, datetime):
        waited = (datetime.utcnow() - last).total_seconds()
        if waited < cooldown:
            retry_after = max(1, int(cooldown - waited))
            raise HTTPException(
                status_code=429,
                detail=(
                    "This document was sent for AI analysis moments ago. "
                    f"Try again in {retry_after} seconds."
                ),
                headers={"Retry-After": str(retry_after)},
            )

    item = parse(llm_settings.user_rate_limit)
    if not limiter.limiter.hit(item, "llm-analysis", current_user.get("id", "anonymous")):
        raise HTTPException(
            status_code=429,
            detail="Too many AI analysis requests. Please wait a minute and try again.",
            headers={"Retry-After": str(int(item.get_expiry()))},
        )


def _cached_response(cached: dict, suggestions: list[dict]) -> dict:
    response = {
        "suggestions": suggestions,
        "summary": cached.get("summary", ""),
        "status": "cached",
        "method": cached.get("method", "llm"),
        "generated_at": cached.get("generated_at"),
    }
    response.update({k: cached[k] for k in _ANALYSIS_FIELDS if k in cached})
    return response


@router.get(
    "/{document_id}/redaction-suggestions",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def get_document_redaction_suggestions(
    request: Request,
    document_id: str,
    quick: bool = False,
    force_regenerate: bool = False,
    generate: bool = False,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Get AI-powered redaction suggestions for a document.

    Args:
        document_id: Document ID
        quick: If True, use quick PII detection (no AI).
        generate: Explicit request to run AI analysis when nothing is cached.
        force_regenerate: Re-run AI analysis even if a result is cached.

    LLM-04: opening a document never sends it to the LLM by itself. With no
    cached result the text is only sent when the org's
    ``auto_generate_ai_suggestions`` setting is on, or the caller passes
    ``generate=true`` / ``force_regenerate=true``; otherwise the response
    has ``status: "not_generated"``. Results, including "no suggestions",
    are cached and not regenerated on view. User-triggered analysis is rate
    limited per user and per document (429 + Retry-After).
    """
    # In demo mode there is no live LLM: never call it and never overwrite
    # the curated `ai_suggestions` snapshot (a visitor clicking "Regenerate"
    # must not wipe the demo for everyone until the next nightly reset).
    demo_mode = os.getenv("BLACKBAR_DEMO_MODE", "").lower() == "true"

    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    extracted_text = doc.get("extracted_text")
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
        cached = doc.get("ai_suggestions")
        if cached and not quick and (not force_regenerate or demo_mode):
            cached_suggestions = cached.get("suggestions", [])

            if not cached_suggestions and demo_mode:
                return {
                    "suggestions": [],
                    "summary": cached.get("summary", ""),
                    "status": "demo_no_suggestions",
                    "method": cached.get("method", "seeded"),
                }

            # Geometry must come from the server-side search: anything not
            # marked as located (including legacy entries carrying
            # model-supplied coordinates) is re-located (LLM-06).
            text_data = doc.get("text_data")
            needs_enrichment = any(not s.get("has_coordinates") for s in cached_suggestions)
            pdf_content = await load_document_pdf(doc, db) if needs_enrichment else None
            if pdf_content:
                cached_suggestions = await asyncio.to_thread(
                    enrich_suggestions_with_coordinates,
                    cached_suggestions,
                    pdf_content,
                    text_data,
                )

            rejected_texts = {r.get("text") for r in doc.get("rejected_ai_suggestions", [])}
            for suggestion in cached_suggestions:
                if suggestion.get("text") in rejected_texts:
                    suggestion["rejected"] = True

            return _cached_response(cached, cached_suggestions)

        if quick:
            suggestions = get_quick_pii_suggestions(extracted_text)

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

        if demo_mode:
            return {
                "suggestions": [],
                "summary": "AI suggestions are pre-generated in this demo.",
                "status": "demo_no_suggestions",
                "method": "seeded",
            }

        explicit = force_regenerate or generate
        if not explicit and not await _auto_generate_enabled(db):
            return {
                "suggestions": [],
                "summary": (
                    "AI suggestions have not been generated for this document. "
                    "Choose Generate to send it for AI analysis."
                ),
                "status": "not_generated",
                "method": None,
            }

        _enforce_llm_limits(current_user, doc)
        await db.documents.update_one(
            {"id": document_id}, {"$set": {"last_llm_request_at": datetime.utcnow()}}
        )

        # Data minimisation (LLM-17): the case title is only sent when
        # LLM_SEND_CASE_CONTEXT is on.
        from src.config import llm_settings

        context = None
        if llm_settings.send_case_context and doc.get("case_id"):
            case = await db.cases.find_one({"id": doc["case_id"]})
            if case:
                context = f"Case: {case.get('title', 'Unknown')}. Type: FOI Request"

        result = await get_redaction_suggestions(extracted_text, context)
        suggestions = result.get("suggestions", [])

        if result.get("error_code") in _NO_EGRESS_ERRORS:
            await db.documents.update_one(
                {"id": document_id}, {"$unset": {"last_llm_request_at": ""}}
            )
            return {**result, "status": "ai_unavailable", "method": None}

        pdf_content = await load_document_pdf(doc, db)
        text_data = doc.get("text_data")
        if pdf_content:
            suggestions = await asyncio.to_thread(
                enrich_suggestions_with_coordinates, suggestions, pdf_content, text_data
            )
            result["suggestions"] = suggestions

        # Cache everything, including "no suggestions" and provider errors,
        # so a view never re-sends the document (LLM-04). Provenance records
        # which provider/model received the text (LLM-16).
        cache_data = {
            "suggestions": suggestions,
            "summary": result.get("summary", ""),
            "method": "llm",
            "generated_at": datetime.utcnow(),
            "requested_by": current_user.get("id"),
            **{k: result[k] for k in _ANALYSIS_FIELDS if k in result},
        }
        await db.documents.update_one({"id": document_id}, {"$set": {"ai_suggestions": cache_data}})

        logger.info(
            f"Generated and cached {len(suggestions)} AI suggestions for document {document_id}"
        )

        result["status"] = "ai_error" if result.get("error") else "ai_complete"
        result["method"] = "llm"
        return result

    except HTTPException:
        raise
    except Exception as e:
        from src.llm.safety import new_error_reference

        reference = new_error_reference()
        logger.error(
            f"Error generating redaction suggestions for {document_id} "
            f"(reference {reference}): {type(e).__name__}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error generating suggestions (reference {reference})",
        ) from None


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


def _feedback_text_hash(text: str) -> str:
    import hashlib
    import unicodedata

    normalised = " ".join(unicodedata.normalize("NFC", text or "").casefold().split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


@router.post(
    "/{document_id}/ai-feedback",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def record_ai_feedback(
    document_id: str,
    suggestion_text: str = Body(..., max_length=2000),
    suggestion_category: str = Body(..., max_length=100),
    suggestion_reason: str = Body("", max_length=2000),
    feedback: Literal["accepted", "rejected"] = Body(...),
    context: str | None = Body(None, max_length=100),
    current_user=Depends(get_current_user),
):
    """
    Record user feedback on an AI redaction suggestion.

    LLM-12: the caller must be able to access the document. The
    ``ai_feedback`` collection keeps a hash of the suggestion text (never the
    text itself) and expires after AI_FEEDBACK_RETENTION_DAYS via a TTL
    index. A rejection is also recorded on the document so the viewer can
    mark the suggestion as rejected.
    """
    from datetime import timedelta

    from src.config import llm_settings
    from src.core.authz import assert_document_access

    doc = await db.documents.find_one(
        {"id": document_id}, {"_id": 0, "id": 1, "case_id": 1, "shared_with": 1}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    case = await db.cases.find_one({"id": doc["case_id"]}) if doc.get("case_id") else None
    assert_document_access(doc, current_user, case)

    now = datetime.utcnow()
    feedback_record = {
        "id": str(uuid.uuid4()),
        "document_id": document_id,
        "suggestion_hash": _feedback_text_hash(suggestion_text),
        "suggestion_length": len(suggestion_text),
        "suggestion_category": suggestion_category,
        "feedback": feedback,
        "context": context,
        "user_id": current_user["id"],
        "timestamp": now,
        "expires_at": now + timedelta(days=llm_settings.feedback_retention_days),
    }

    ai_feedback = db["ai_feedback"]
    await ai_feedback.create_index("expires_at", expireAfterSeconds=0)
    await ai_feedback.insert_one(feedback_record)

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
                        "rejected_at": now,
                    }
                }
            },
        )

    logger.info(
        f"AI feedback recorded: {feedback} on document {document_id} by user {current_user['id']}"
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
