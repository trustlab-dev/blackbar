"""
Document Sharing Routes
Allows analysts to share documents with guest users
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..database import db, users
from ..dependencies import check_role, get_current_user

router = APIRouter()


class ShareDocumentRequest(BaseModel):
    user_id: str
    notes: str = ""


class DocumentShare(BaseModel):
    user_id: str
    user_name: str
    shared_by: str
    shared_by_name: str
    shared_at: str
    notes: str = ""


@router.post(
    "/{document_id}/share", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def share_document(
    document_id: str, request: ShareDocumentRequest, current_user=Depends(get_current_user)
):
    """Share a document with a guest user."""
    # Check document exists
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if target user exists and is a guest
    target_user = await users.find_one({"id": request.user_id})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if target_user.get("role") != "guest":
        raise HTTPException(status_code=400, detail="Can only share with guest users")

    # Check if already shared
    shared_with = doc.get("shared_with", [])
    if any(share.get("user_id") == request.user_id for share in shared_with):
        raise HTTPException(status_code=400, detail="Document already shared with this user")

    # Add share
    share_entry = {
        "user_id": request.user_id,
        "user_name": target_user.get("username"),
        "shared_by": current_user["id"],
        "shared_by_name": current_user.get("username"),
        "shared_at": datetime.utcnow(),
        "notes": request.notes,
    }

    await db.documents.update_one({"id": document_id}, {"$push": {"shared_with": share_entry}})

    return {"message": "Document shared successfully", "share": share_entry}


@router.delete(
    "/{document_id}/share/{user_id}",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def unshare_document(document_id: str, user_id: str, current_user=Depends(get_current_user)):
    """Remove document share from a user."""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove share
    result = await db.documents.update_one(
        {"id": document_id}, {"$pull": {"shared_with": {"user_id": user_id}}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Share not found")

    return {"message": "Document unshared successfully"}


@router.get(
    "/{document_id}/shares", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def list_document_shares(document_id: str, current_user=Depends(get_current_user)):
    """List all users a document is shared with."""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"shares": doc.get("shared_with", [])}


@router.get("/shared-with-me", dependencies=[Depends(check_role(["guest"]))])
async def list_shared_documents(current_user=Depends(get_current_user)):
    """List all documents shared with the current guest user."""
    # Find documents where current user is in shared_with array
    cursor = db.documents.find(
        {"shared_with.user_id": current_user["id"]},
        {"content": 0},  # Exclude binary content
    )

    docs = await cursor.to_list(length=100)

    # Format response
    shared_docs = []
    for doc in docs:
        # Find the share entry for this user
        share_entry = next(
            (s for s in doc.get("shared_with", []) if s.get("user_id") == current_user["id"]), None
        )

        shared_docs.append(
            {
                "id": doc["id"],
                "filename": doc["filename"],
                "case_id": doc.get("case_id"),
                "mime_type": doc.get("mime_type"),
                "size": doc.get("size"),
                "upload_date": doc.get("upload_date"),
                "shared_by": share_entry.get("shared_by_name") if share_entry else None,
                "shared_at": share_entry.get("shared_at") if share_entry else None,
                "notes": share_entry.get("notes") if share_entry else None,
            }
        )

    return {"documents": shared_docs, "total": len(shared_docs)}
