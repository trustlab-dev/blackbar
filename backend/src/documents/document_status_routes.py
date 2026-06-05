"""
Document status routes — single and bulk status updates with audit logging.

Split from documents/routes.py in Phase 1.5 (2026-05-11) to keep individual
route modules tractable. Mounted via include_router in documents/routes.py.
The 'document_' prefix disambiguates from cases/status_routes.py.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user
from .models import DocumentStatus

logger = logging.getLogger(__name__)

router = APIRouter()


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


# Phase 4 Batch 4.4 (audit B33): `/bulk/status` MUST be registered
# before `/{document_id}/status`. FastAPI matches in declaration order
# and `bulk` would otherwise be captured by the single-doc `{document_id}`
# parameter, returning 404 "Document not found" instead of routing to
# the bulk handler. Same defect class as B12/B48.


@router.put("/bulk/status", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def bulk_update_document_status(
    request: Request,
    document_ids: list[str] = Body(...),
    status: DocumentStatus = Body(...),
    db=Depends(get_db),
    notes: str | None = Body(None),
    current_user=Depends(get_current_user),
):
    """Bulk update document statuses"""
    updated_count = 0

    for doc_id in document_ids:
        try:
            doc = await db.documents.find_one({"id": doc_id})
            if not doc:
                continue

            old_status = doc.get("status", "new")

            # Update document
            await db.documents.update_one(
                {"id": doc_id},
                {
                    "$set": {
                        "status": status.value,
                        "status_updated_at": datetime.utcnow(),
                        "status_updated_by": current_user["id"],
                    }
                },
            )

            # Add audit log to case
            if doc.get("case_id"):
                audit_entry = {
                    "action": "document_status_changed",
                    "user_id": current_user["id"],
                    "username": current_user.get(
                        "username", current_user.get("email", "Unknown User")
                    ),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "document_id": doc_id,
                        "filename": doc.get("filename"),
                        "old_status": old_status,
                        "new_status": status.value,
                        "notes": notes,
                        "bulk_update": True,
                    },
                }

                await db.cases.update_one(
                    {"id": doc["case_id"]}, {"$push": {"audit_log": audit_entry}}
                )

            updated_count += 1
        except Exception as e:
            logger.error(f"Error updating document {doc_id}: {str(e)}")
            continue

    return {"success": True, "updated_count": updated_count, "total_requested": len(document_ids)}


@router.put(
    "/{document_id}/status", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def update_document_status(
    request: Request,
    document_id: str,
    status: DocumentStatus = Body(...),
    db=Depends(get_db),
    notes: str | None = Body(None),
    current_user=Depends(get_current_user),
):
    """Update document status with audit logging"""
    # Find document
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    old_status = doc.get("status", "new")

    # Update document status
    await db.documents.update_one(
        {"id": document_id},
        {
            "$set": {
                "status": status.value,
                "status_updated_at": datetime.utcnow(),
                "status_updated_by": current_user["id"],
            }
        },
    )

    # Add audit log to case if document is associated with a case
    if doc.get("case_id"):
        audit_entry = {
            "action": "document_status_changed",
            "user_id": current_user["id"],
            "username": current_user.get("username", current_user.get("email", "Unknown User")),
            "timestamp": datetime.utcnow(),
            "details": {
                "document_id": document_id,
                "filename": doc.get("filename"),
                "old_status": old_status,
                "new_status": status.value,
                "notes": notes,
            },
        }

        await db.cases.update_one({"id": doc["case_id"]}, {"$push": {"audit_log": audit_entry}})

    return {
        "success": True,
        "document_id": document_id,
        "old_status": old_status,
        "new_status": status.value,
    }
