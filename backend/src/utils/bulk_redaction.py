"""
Bulk Redaction Tools
Apply redactions across multiple documents efficiently
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def find_text_in_documents(
    documents: list[dict], search_text: str, case_sensitive: bool = False
) -> dict:
    """
    Find all occurrences of text across multiple documents.

    Args:
        documents: List of documents to search
        search_text: Text to find
        case_sensitive: Whether search is case-sensitive

    Returns:
        Dict mapping document IDs to list of occurrences
    """
    results = {}

    for doc in documents:
        doc_id = doc.get("id")
        extracted_text = doc.get("extracted_text", "")

        if not extracted_text:
            continue

        # Search for text
        search_lower = search_text if case_sensitive else search_text.lower()
        text_lower = extracted_text if case_sensitive else extracted_text.lower()

        occurrences = []
        start = 0

        while True:
            pos = text_lower.find(search_lower, start)
            if pos == -1:
                break

            occurrences.append(
                {
                    "position": pos,
                    "text": extracted_text[pos : pos + len(search_text)],
                    "context_before": extracted_text[max(0, pos - 50) : pos],
                    "context_after": extracted_text[
                        pos + len(search_text) : pos + len(search_text) + 50
                    ],
                }
            )

            start = pos + 1

        if occurrences:
            results[doc_id] = {
                "document_id": doc_id,
                "filename": doc.get("filename"),
                "occurrences": occurrences,
                "count": len(occurrences),
            }

    return results


def create_bulk_redactions(
    text_matches: dict, category: str, reason: str, user_id: str
) -> list[dict]:
    """
    Create redaction records for bulk application.

    Args:
        text_matches: Results from find_text_in_documents
        category: Redaction category (e.g., S22)
        reason: Reason for redaction
        user_id: User creating redactions

    Returns:
        List of redaction records to be created
    """
    redactions = []

    for doc_id, match_data in text_matches.items():
        for occurrence in match_data["occurrences"]:
            redaction = {
                "document_id": doc_id,
                "text": occurrence["text"],
                "position": occurrence["position"],
                "category": category,
                "reason": reason,
                "created_by": user_id,
                "created_at": datetime.utcnow(),
                "status": "pending",  # Needs coordinate mapping
                "bulk_operation": True,
            }
            redactions.append(redaction)

    return redactions


def create_redaction_template(
    name: str, pattern: str, category: str, reason: str, description: str = None
) -> dict:
    """
    Create a reusable redaction template.

    Args:
        name: Template name
        pattern: Text pattern or regex
        category: Redaction category
        reason: Reason for redaction
        description: Optional description

    Returns:
        Template dict
    """
    return {
        "name": name,
        "pattern": pattern,
        "category": category,
        "reason": reason,
        "description": description or f"Redact all instances of {pattern}",
        "created_at": datetime.utcnow(),
        "is_regex": False,  # Could be extended for regex support
    }


def apply_template_to_documents(template: dict, documents: list[dict]) -> dict:
    """
    Apply a redaction template to multiple documents.

    Args:
        template: Redaction template
        documents: List of documents

    Returns:
        Results of template application
    """
    pattern = template.get("pattern", "")
    category = template.get("category", "S22")
    reason = template.get("reason", "Template redaction")

    # Find all matches
    matches = find_text_in_documents(documents, pattern, case_sensitive=False)

    # Create redactions
    redactions = create_bulk_redactions(matches, category, reason, "template_system")

    return {
        "template_name": template.get("name"),
        "documents_affected": len(matches),
        "total_redactions": len(redactions),
        "redactions": redactions,
        "matches": matches,
    }


def copy_redactions_between_pages(
    source_redactions: list[dict], source_page: int, target_pages: list[int]
) -> list[dict]:
    """
    Copy redactions from one page to other pages.

    Args:
        source_redactions: Redactions from source page
        source_page: Source page number
        target_pages: List of target page numbers

    Returns:
        List of new redactions for target pages
    """
    new_redactions = []

    # Filter redactions for source page
    page_redactions = [r for r in source_redactions if r.get("page") == source_page]

    # Copy to each target page
    for target_page in target_pages:
        for redaction in page_redactions:
            new_redaction = redaction.copy()
            new_redaction["page"] = target_page
            new_redaction["copied_from_page"] = source_page
            new_redaction["created_at"] = datetime.utcnow()
            new_redactions.append(new_redaction)

    return new_redactions


def preview_bulk_redaction(documents: list[dict], search_text: str, category: str) -> dict:
    """
    Preview what would be redacted without applying.

    Args:
        documents: List of documents
        search_text: Text to redact
        category: Redaction category

    Returns:
        Preview information
    """
    matches = find_text_in_documents(documents, search_text)

    summary = {
        "search_text": search_text,
        "category": category,
        "documents_affected": len(matches),
        "total_occurrences": sum(m["count"] for m in matches.values()),
        "preview": [],
    }

    # Create preview for each document
    for doc_id, match_data in matches.items():
        summary["preview"].append(
            {
                "document_id": doc_id,
                "filename": match_data["filename"],
                "occurrences": match_data["count"],
                "sample_contexts": [
                    {
                        "before": occ["context_before"],
                        "match": occ["text"],
                        "after": occ["context_after"],
                    }
                    for occ in match_data["occurrences"][:3]  # Show first 3
                ],
            }
        )

    return summary


def validate_bulk_operation(document_ids: list[str], max_documents: int = 100) -> bool:
    """
    Validate bulk operation parameters.

    Args:
        document_ids: List of document IDs
        max_documents: Maximum allowed documents

    Returns:
        True if valid, raises exception if invalid
    """
    if not document_ids:
        raise ValueError("No documents specified for bulk operation")

    if len(document_ids) > max_documents:
        raise ValueError(f"Bulk operation limited to {max_documents} documents at a time")

    return True


def create_undo_record(
    operation_type: str, affected_documents: list[str], redactions_created: list[dict], user_id: str
) -> dict:
    """
    Create an undo record for bulk operations.

    Args:
        operation_type: Type of operation
        affected_documents: List of affected document IDs
        redactions_created: List of created redactions
        user_id: User who performed operation

    Returns:
        Undo record
    """
    return {
        "operation_type": operation_type,
        "affected_documents": affected_documents,
        "redactions_created": [r.get("id") for r in redactions_created if r.get("id")],
        "created_by": user_id,
        "created_at": datetime.utcnow(),
        "can_undo": True,
        "undo_deadline": datetime.utcnow(),  # Could add time limit
    }


def undo_bulk_operation(undo_record: dict, documents_collection) -> dict:
    """
    Undo a bulk redaction operation.

    Args:
        undo_record: Undo record from create_undo_record
        documents_collection: MongoDB documents collection

    Returns:
        Result of undo operation
    """
    if not undo_record.get("can_undo"):
        raise ValueError("This operation cannot be undone")

    redaction_ids = undo_record.get("redactions_created", [])

    # This would need to be implemented with actual database operations
    # For now, return structure
    return {
        "success": True,
        "redactions_removed": len(redaction_ids),
        "documents_affected": len(undo_record.get("affected_documents", [])),
    }
