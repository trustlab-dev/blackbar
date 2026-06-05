"""
Document attachment routes — list, fetch, and retrieve AI analysis
for per-document attachments.

Split from documents/routes.py in Phase 1.5 (2026-05-11) to keep individual
route modules tractable. Mounted via include_router in documents/routes.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user

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
    "/{document_id}/attachments",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user", "guest"]))],
)
async def list_attachments(
    request: Request, document_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """List all attachments for a document."""
    # First, check if the document exists and has attachments
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access (includes guest shares)
    case = await db.cases.find_one({"id": doc["case_id"]})
    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    # If no attachments, return empty list
    if not doc.get("has_attachments", False) or not doc.get("attachment_ids", []):
        return []

    # Get all attachments
    attachment_ids = doc.get("attachment_ids", [])
    cursor = db.documents.find({"id": {"$in": attachment_ids}})

    # Convert to list and remove binary content for the response
    attachments = []
    async for attachment in cursor:
        attachments.append(
            {
                "id": attachment["id"],
                "filename": attachment["filename"],
                "mime_type": attachment.get("mime_type", "application/octet-stream"),
                "size": attachment.get("size", 0),
                "upload_date": attachment["upload_date"],
            }
        )

    return attachments


# GET ATTACHMENT CONTENT
@router.get(
    "/{document_id}/attachments/{attachment_id}",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def get_attachment(
    request: Request, document_id: str, attachment_id: str, db=Depends(get_db)
):
    """Get a specific attachment for a document."""
    # First check if the main document exists and contains this attachment ID
    doc = await db.documents.find_one({"id": document_id})
    if not doc or attachment_id not in doc.get("attachment_ids", []):
        raise HTTPException(status_code=404, detail="Document or attachment not found")

    # Get the attachment
    attachment = await db.documents.find_one({"id": attachment_id})
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Create a response with the appropriate content type
    content = attachment["content"]
    filename = attachment["filename"]
    mime_type = attachment.get("mime_type", "application/octet-stream")

    response = Response(
        content=content,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

    return response


# GET ATTACHMENT SUMMARY AND AI SUGGESTIONS
@router.get(
    "/{document_id}/attachments/{attachment_id}/analysis",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def get_attachment_analysis(
    request: Request, document_id: str, attachment_id: str, db=Depends(get_db)
):
    """Get the AI-generated summary and suggestions for an attachment."""
    # First check if the main document exists and contains this attachment ID
    doc = await db.documents.find_one({"id": document_id})
    if not doc or attachment_id not in doc.get("attachment_ids", []):
        raise HTTPException(status_code=404, detail="Document or attachment not found")

    # Get the attachment
    attachment = await db.documents.find_one(
        {"id": attachment_id},
        {"summary": 1, "ai_suggestions": 1, "processed": 1, "processing_error": 1, "filename": 1},
    )

    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Create response
    result = {
        "id": attachment_id,
        "filename": attachment.get("filename", ""),
        "processed": attachment.get("processed", False),
        "summary": attachment.get("summary", None),
        "ai_suggestions": attachment.get("ai_suggestions", []),
        "processing_error": attachment.get("processing_error", None),
    }

    return result
