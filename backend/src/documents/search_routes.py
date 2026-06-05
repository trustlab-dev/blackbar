"""
Document search routes — GET and POST in-document text search.

Split from documents/routes.py in Phase 1.5 (2026-05-11) to keep individual
route modules tractable. Mounted via include_router in documents/routes.py.
"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..core.database import get_database_from_request
from ..database import db
from ..dependencies import check_role, get_current_user

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


@router.get(
    "/{document_id}/search",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def search_document_text(request: Request, document_id: str, query: str, db=Depends(get_db)):
    """Search for text within a document."""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    text_data = doc.get("text_data", {})
    results = []

    query_lower = query.lower()

    for page in text_data.get("pages", []):
        page_num = page["page_num"]
        page_text = page["text"].lower()

        if query_lower in page_text:
            # Find all occurrences with context
            start = 0
            while True:
                pos = page_text.find(query_lower, start)
                if pos == -1:
                    break

                # Get context (50 chars before and after)
                context_start = max(0, pos - 50)
                context_end = min(len(page_text), pos + len(query_lower) + 50)
                context = page["text"][context_start:context_end]

                results.append(
                    {"page": page_num, "position": pos, "context": context, "match": query}
                )

                start = pos + 1

    return {"query": query, "total_matches": len(results), "results": results}


@router.post(
    "/{document_id}/search",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def search_document_text(
    document_id: str,
    query: str = Body(..., embed=True),
    case_sensitive: bool = Body(False, embed=True),
    whole_word: bool = Body(False, embed=True),
    current_user=Depends(get_current_user),
):
    """
    Search for text in a document and return matches with coordinates.
    Returns actual bbox coordinates from OCR data for accurate redaction placement.
    """
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check permissions
    case = None
    if doc.get("case_id"):
        case = await db.cases.find_one({"id": doc["case_id"]})

    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")

    # Get text_data from document
    text_data = doc.get("text_data")
    if not text_data:
        logger.warning(f"Document {document_id} has no text_data field")
        raise HTTPException(
            status_code=400,
            detail="No OCR data available for this document. Please re-upload the document.",
        )

    if not text_data.get("pages"):
        logger.warning(
            f"Document {document_id} has text_data but no pages: {list(text_data.keys())}"
        )
        raise HTTPException(
            status_code=400, detail="OCR data is incomplete. Please re-upload the document."
        )

    # Check if pages have words
    has_words = any(page.get("words") for page in text_data.get("pages", []))
    if not has_words:
        logger.warning(f"Document {document_id} has pages but no word-level data")
        raise HTTPException(
            status_code=400,
            detail="OCR data does not contain word-level coordinates. Please re-upload the document.",
        )

    matches = []
    search_term = query if case_sensitive else query.lower()

    # Search through each page
    for page_data in text_data["pages"]:
        page_num = page_data["page_num"]
        words = page_data.get("words", [])

        if not words:
            continue

        # Search through words
        for i, word_data in enumerate(words):
            word_text = word_data["text"]
            compare_text = word_text if case_sensitive else word_text.lower()

            # Check for match
            is_match = False
            if whole_word:
                is_match = compare_text == search_term
            else:
                is_match = search_term in compare_text

            if is_match:
                # Get context: 3 words before and after
                context_words = []
                start_idx = max(0, i - 3)
                end_idx = min(len(words), i + 4)

                for j in range(start_idx, end_idx):
                    if j == i:
                        context_words.append(f"**{words[j]['text']}**")
                    else:
                        context_words.append(words[j]["text"])

                context = " ".join(context_words)
                if start_idx > 0:
                    context = "..." + context
                if end_idx < len(words):
                    context = context + "..."

                matches.append(
                    {
                        "page": page_num,
                        "text": word_text,
                        "bbox": word_data["bbox"],
                        "context": context,
                        "confidence": word_data.get("confidence", 1.0),
                    }
                )

    logger.info(f"Found {len(matches)} matches for '{query}' in document {document_id}")

    return {"matches": matches, "query": query, "total": len(matches)}
