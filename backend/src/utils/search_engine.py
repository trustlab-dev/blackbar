"""
Full-Text Search Engine
Search across all documents and cases
"""

import logging
import re

logger = logging.getLogger(__name__)


def highlight_text(text: str, query: str, context_chars: int = 100) -> list[dict]:
    """
    Find and highlight search query in text.

    Args:
        text: Text to search
        query: Search query
        context_chars: Characters of context around match

    Returns:
        List of matches with context
    """
    if not text or not query:
        return []

    matches = []
    query_lower = query.lower()
    text_lower = text.lower()

    # Find all occurrences
    start = 0
    while True:
        pos = text_lower.find(query_lower, start)
        if pos == -1:
            break

        # Get context around match
        context_start = max(0, pos - context_chars)
        context_end = min(len(text), pos + len(query) + context_chars)

        # Extract context
        before = text[context_start:pos]
        match = text[pos : pos + len(query)]
        after = text[pos + len(query) : context_end]

        # Add ellipsis if truncated
        if context_start > 0:
            before = "..." + before
        if context_end < len(text):
            after = after + "..."

        matches.append(
            {
                "position": pos,
                "before": before,
                "match": match,
                "after": after,
                "context": before + match + after,
            }
        )

        start = pos + 1

    return matches


def build_search_query(query: str, fields: list[str] = None) -> dict:
    """
    Build MongoDB text search query.

    Args:
        query: Search query string
        fields: Optional list of fields to search

    Returns:
        MongoDB query dict
    """
    if not query:
        return {}

    # If specific fields provided, use regex search
    if fields:
        or_conditions = []
        for field in fields:
            or_conditions.append({field: {"$regex": re.escape(query), "$options": "i"}})
        return {"$or": or_conditions}

    # Otherwise use text search (requires text index)
    return {"$text": {"$search": query}}


def search_documents(query: str, filters: dict = None, limit: int = 50) -> dict:
    """
    Build search query for documents.

    Args:
        query: Search query
        filters: Additional filters (case_id, status, etc.)
        limit: Maximum results

    Returns:
        Search query configuration
    """
    # Build base query
    search_fields = ["filename", "extracted_text", "submitter_name", "submitter_email"]

    base_query = build_search_query(query, search_fields)

    # Add filters
    if filters:
        base_query.update(filters)

    return {"query": base_query, "limit": limit, "sort": [("uploaded_at", -1)]}  # Most recent first


def search_cases(query: str, filters: dict = None, limit: int = 50) -> dict:
    """
    Build search query for cases.

    Args:
        query: Search query
        filters: Additional filters (status, priority, etc.)
        limit: Maximum results

    Returns:
        Search query configuration
    """
    # Build base query
    search_fields = ["case_number", "title", "description", "requester_name", "requester_email"]

    base_query = build_search_query(query, search_fields)

    # Add filters
    if filters:
        base_query.update(filters)

    return {"query": base_query, "limit": limit, "sort": [("created_at", -1)]}  # Most recent first


def rank_results(results: list[dict], query: str) -> list[dict]:
    """
    Rank search results by relevance.

    Args:
        results: List of search results
        query: Original search query

    Returns:
        Ranked results
    """
    query_lower = query.lower()

    for result in results:
        score = 0

        # Check filename match
        filename = result.get("filename", "").lower()
        if query_lower in filename:
            score += 10

        # Check exact match in text
        text = result.get("extracted_text", "").lower()
        if query_lower in text:
            score += 5
            # Bonus for multiple occurrences
            score += text.count(query_lower)

        # Check submitter match
        submitter = result.get("submitter_name", "").lower()
        if query_lower in submitter:
            score += 8

        result["relevance_score"] = score

    # Sort by score (descending)
    results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    return results


def create_search_index_config() -> dict:
    """
    Get configuration for creating MongoDB text indexes.

    Returns:
        Index configuration
    """
    return {
        "documents": {
            "fields": {
                "filename": "text",
                "extracted_text": "text",
                "submitter_name": "text",
                "submitter_email": "text",
            },
            "weights": {"filename": 10, "submitter_name": 5, "extracted_text": 1},
        },
        "cases": {
            "fields": {
                "case_number": "text",
                "title": "text",
                "description": "text",
                "requester_name": "text",
            },
            "weights": {"case_number": 10, "title": 8, "requester_name": 5, "description": 1},
        },
    }


def extract_keywords(query: str) -> list[str]:
    """
    Extract keywords from search query.

    Args:
        query: Search query

    Returns:
        List of keywords
    """
    # Remove common words
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "was",
        "are",
        "were",
        "be",
    }

    # Split and clean
    words = re.findall(r"\w+", query.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    return keywords


def format_search_results(
    results: list[dict], query: str, include_highlights: bool = True
) -> list[dict]:
    """
    Format search results for API response.

    Args:
        results: Raw search results
        query: Search query
        include_highlights: Whether to include text highlights

    Returns:
        Formatted results
    """
    formatted = []

    for result in results:
        formatted_result = {
            "id": result.get("id"),
            "type": "document" if "filename" in result else "case",
            "title": result.get("filename") or result.get("title"),
            "relevance_score": result.get("relevance_score", 0),
        }

        # Add highlights if requested
        if include_highlights and "extracted_text" in result:
            highlights = highlight_text(result.get("extracted_text", ""), query, context_chars=150)
            formatted_result["highlights"] = highlights[:3]  # Top 3 matches
            formatted_result["match_count"] = len(highlights)

        # Add metadata
        if "filename" in result:
            # Document result
            formatted_result["metadata"] = {
                "filename": result.get("filename"),
                "case_id": result.get("case_id"),
                "uploaded_at": result.get("uploaded_at"),
                "submitter": result.get("submitter_name"),
            }
        else:
            # Case result
            formatted_result["metadata"] = {
                "case_number": result.get("case_number"),
                "status": result.get("status"),
                "created_at": result.get("created_at"),
            }

        formatted.append(formatted_result)

    return formatted
