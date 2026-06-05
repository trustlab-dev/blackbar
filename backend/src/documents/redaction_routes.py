"""
Redaction Proposal Routes
Handles proposed redactions, approvals — extends the main document redaction CRUD.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..cases.permissions import (
    can_approve_proposed_redactions,
    can_propose_redactions,
    get_user_role_on_case,
    is_case_team_member,
)
from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user


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
        return is_case_team_member(case.get("case_team", []), user_id)

    return False


router = APIRouter()


async def get_db(request: Request):
    return await get_database_from_request(request)


class ProposeRedactionRequest(BaseModel):
    x: float
    y: float
    width: float
    height: float
    page: int
    category: str
    reason: str


class ApproveProposedRedactionRequest(BaseModel):
    action: str  # "approve" or "reject"
    notes: str | None = None


@router.post("/{document_id}/redactions/propose")
async def propose_redaction(
    document_id: str,
    request: Request,
    data: ProposeRedactionRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Propose a redaction (blue). Requires analyst/manager approval.
    """
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    user_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if not user_role or not can_propose_redactions(user_role):
        raise HTTPException(
            status_code=403, detail="You don't have permission to propose redactions"
        )

    redaction = {
        **data.dict(exclude={"reason"}),
        "type": "proposed",
        "status": "proposed",
        "created_by": current_user["id"],
        "created_by_role": user_role,
        "created_at": datetime.utcnow(),
        "proposed_by": current_user["id"],
        "proposed_by_role": user_role,
        "proposed_reason": data.reason,
        "approval_status": "pending",
        "is_contested": False,
        "active_contests": 0,
    }

    await db.documents.update_one({"id": document_id}, {"$push": {"redactions": redaction}})

    await db.cases.update_one(
        {"id": case["id"]},
        {
            "$push": {
                "audit_log": {
                    "action": "redaction_proposed",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "document_id": document_id,
                        "filename": doc.get("filename"),
                        "page": data.page,
                        "category": data.category,
                        "reason": data.reason,
                    },
                }
            }
        },
    )

    return {
        "success": True,
        "message": "Redaction proposed (pending approval)",
        "redaction": redaction,
    }


@router.get("/{document_id}/redactions/proposed")
async def get_proposed_redactions(
    document_id: str, request: Request, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Get all proposed redactions for a document."""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if not is_case_team_member(case.get("case_team", []), current_user["id"]):
        raise HTTPException(status_code=403, detail="You don't have access to this case")

    proposed = [r for r in doc.get("redactions", []) if r.get("type") == "proposed"]
    return {"document_id": document_id, "proposed_redactions": proposed, "count": len(proposed)}


@router.put("/{document_id}/redactions/{redaction_index}/approve")
async def approve_or_reject_proposed_redaction(
    document_id: str,
    redaction_index: int,
    request: Request,
    data: ApproveProposedRedactionRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Approve or reject a proposed redaction."""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    user_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if not user_role or not can_approve_proposed_redactions(user_role):
        raise HTTPException(status_code=403, detail="Only analysts and managers can approve/reject")

    redactions = doc.get("redactions", [])
    if redaction_index >= len(redactions):
        raise HTTPException(status_code=404, detail="Redaction not found")

    redaction = redactions[redaction_index]
    if redaction.get("type") != "proposed":
        raise HTTPException(status_code=400, detail="This is not a proposed redaction")

    if data.action == "approve":
        update_fields = {
            f"redactions.{redaction_index}.type": "professional",
            f"redactions.{redaction_index}.status": "approved",
            f"redactions.{redaction_index}.approval_status": "approved",
            f"redactions.{redaction_index}.reviewed_by": current_user["id"],
            f"redactions.{redaction_index}.reviewed_at": datetime.utcnow(),
            f"redactions.{redaction_index}.review_notes": data.notes,
        }
        message = "Proposed redaction approved"
    elif data.action == "reject":
        update_fields = {
            f"redactions.{redaction_index}.status": "rejected",
            f"redactions.{redaction_index}.approval_status": "rejected",
            f"redactions.{redaction_index}.reviewed_by": current_user["id"],
            f"redactions.{redaction_index}.reviewed_at": datetime.utcnow(),
            f"redactions.{redaction_index}.review_notes": data.notes,
        }
        message = "Proposed redaction rejected"
    else:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    await db.documents.update_one({"id": document_id}, {"$set": update_fields})

    # Phase 4 Batch 4.4 (audit B26): map approve -> approved, reject ->
    # rejected. The prior `f"redaction_proposal_{data.action}d"` form
    # worked for "approve" by coincidence ("approve" + "d") but produced
    # the typo "redaction_proposal_rejectd" for "reject".
    audit_action = f"redaction_proposal_{'approved' if data.action == 'approve' else 'rejected'}"

    await db.cases.update_one(
        {"id": case["id"]},
        {
            "$push": {
                "audit_log": {
                    "action": audit_action,
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "document_id": document_id,
                        "filename": doc.get("filename"),
                        "redaction_index": redaction_index,
                        "notes": data.notes,
                    },
                }
            }
        },
    )

    return {"success": True, "message": message}


# GET DOCUMENT REDACTIONS (Fixed to be a GET)
@router.get(
    "/{document_id}/redactions",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user", "guest"]))],
)
async def get_redactions(
    request: Request, document_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):

    # Fetch the document
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access (includes guest shares)
    case = await db.cases.find_one({"id": doc["case_id"]})
    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    redactions = doc.get("redactions", [])
    needs_update = False

    # Ensure all redactions have IDs
    for redaction in redactions:
        if "id" not in redaction:
            redaction["id"] = str(uuid.uuid4())
            needs_update = True

    # Update document if we added IDs
    if needs_update:
        await db.documents.update_one({"id": document_id}, {"$set": {"redactions": redactions}})

    return redactions


# ADD REDACTION (New)
@router.post(
    "/{document_id}/redactions",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def add_redaction(
    request: Request,
    document_id: str,
    redaction: dict,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Users can add redactions, but they need approval."""

    # Check document exists and get case
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check case access
    from ..cases.permissions import is_case_team_member

    case = await db.cases.find_one({"id": doc["case_id"]})
    # Owner and admin have full access, others need to be case team members
    if case and current_user.get("role") not in ["owner", "admin"]:
        if not is_case_team_member(case.get("case_team", []), current_user["id"]):
            raise HTTPException(status_code=403, detail="You don't have access to this document")

    # Ensure redaction has an ID and add creator info
    from datetime import datetime

    if "id" not in redaction:
        redaction["id"] = str(uuid.uuid4())

    # Add creator information
    redaction["created_by"] = current_user["id"]
    redaction["created_by_role"] = current_user.get("role", "user")
    redaction["created_by_name"] = current_user.get("username", "Unknown")
    redaction["created_at"] = datetime.utcnow()
    redaction["status"] = "pending"

    result = await db.documents.update_one(
        {"id": document_id}, {"$push": {"redactions": redaction}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")

    # Add to case audit log
    if case:
        await db.cases.update_one(
            {"id": case["id"]},
            {
                "$push": {
                    "audit_log": {
                        "action": "redaction_created",
                        "user_id": current_user["id"],
                        "username": current_user.get("username"),
                        "timestamp": datetime.utcnow(),
                        "details": {
                            "document_id": document_id,
                            "filename": doc.get("filename"),
                            "redaction_id": redaction["id"],
                            "category": redaction.get("category"),
                            "page": redaction.get("page"),
                        },
                    }
                }
            },
        )

    return {"message": "Redaction added for review", "id": redaction["id"]}


# APPROVE OR REJECT REDACTION (New)
@router.put(
    "/{document_id}/redactions/{redaction_id}",
    dependencies=[Depends(check_role(["owner", "admin"]))],
)
async def update_redaction_status(
    request: Request, document_id: str, redaction_id: str, status: str, db=Depends(get_db)
):
    """Reviewers can approve/reject redactions."""
    if status not in ["accepted", "rejected"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    # Phase 4 Batch 4.4 (audit B27): the filter previously used
    # `redactions._id` but `add_redaction` writes the field as
    # `redactions.id`, so the endpoint always returned 404 for normally-
    # added redactions. Use the matching `id` field.
    result = await db.documents.update_one(
        {"id": document_id, "redactions.id": redaction_id},
        {"$set": {"redactions.$.status": status}},
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Redaction not found")

    return {"message": f"Redaction {redaction_id} marked as {status}"}


# UPDATE REDACTION (Edit reason and notes)
@router.put(
    "/{document_id}/redactions/{redaction_id}/edit",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def update_redaction(
    request: Request,
    document_id: str,
    redaction_id: str,
    updates: dict,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Update a specific redaction's reason and notes."""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get case for audit logging
    case = await db.cases.find_one({"id": doc["case_id"]}) if doc.get("case_id") else None

    # Find and update the redaction
    redactions = doc.get("redactions", [])
    found = False
    updated_redaction = None

    for redaction in redactions:
        if redaction.get("id") == redaction_id:
            # Update allowed fields
            if "reason" in updates:
                redaction["reason"] = updates["reason"]
            if "notes" in updates:
                redaction["notes"] = updates["notes"]
            # Update coordinates if provided
            if "x" in updates:
                redaction["x"] = float(updates["x"])
            if "y" in updates:
                redaction["y"] = float(updates["y"])
            if "width" in updates:
                redaction["width"] = float(updates["width"])
            if "height" in updates:
                redaction["height"] = float(updates["height"])
            found = True
            updated_redaction = redaction
            break

    if not found:
        raise HTTPException(status_code=404, detail="Redaction not found")

    result = await db.documents.update_one(
        {"id": document_id}, {"$set": {"redactions": redactions}}
    )

    # Add to case audit log
    if case:
        await db.cases.update_one(
            {"id": case["id"]},
            {
                "$push": {
                    "audit_log": {
                        "action": "redaction_edited",
                        "user_id": current_user["id"],
                        "username": current_user.get("username"),
                        "timestamp": datetime.utcnow(),
                        "details": {
                            "document_id": document_id,
                            "filename": doc.get("filename"),
                            "redaction_id": redaction_id,
                            "category": updated_redaction.get("category"),
                            "page": updated_redaction.get("page"),
                            "updated_fields": list(updates.keys()),
                        },
                    }
                }
            },
        )

    return {"message": "Redaction updated successfully"}


# DELETE REDACTION
@router.delete(
    "/{document_id}/redactions/{redaction_id}",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def delete_redaction(
    request: Request,
    document_id: str,
    redaction_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Delete a specific redaction from a document."""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check case access
    from ..cases.permissions import is_case_team_member

    case = await db.cases.find_one({"id": doc["case_id"]})
    # Owner and admin have full access, others need to be case team members
    if case and current_user.get("role") not in ["owner", "admin"]:
        if not is_case_team_member(case.get("case_team", []), current_user["id"]):
            raise HTTPException(status_code=403, detail="You don't have access to this document")

    # Filter out the redaction with matching id
    redactions = doc.get("redactions", [])
    deleted_redaction = None
    updated_redactions = []
    for r in redactions:
        if r.get("id") == redaction_id:
            deleted_redaction = r
        else:
            updated_redactions.append(r)

    if not deleted_redaction:
        raise HTTPException(status_code=404, detail="Redaction not found")

    result = await db.documents.update_one(
        {"id": document_id}, {"$set": {"redactions": updated_redactions}}
    )

    # Add to case audit log
    if case:
        await db.cases.update_one(
            {"id": case["id"]},
            {
                "$push": {
                    "audit_log": {
                        "action": "redaction_deleted",
                        "user_id": current_user["id"],
                        "username": current_user.get("username"),
                        "timestamp": datetime.utcnow(),
                        "details": {
                            "document_id": document_id,
                            "filename": doc.get("filename"),
                            "redaction_id": redaction_id,
                            "category": deleted_redaction.get("category"),
                            "page": deleted_redaction.get("page"),
                        },
                    }
                }
            },
        )

    return {"message": "Redaction deleted successfully"}
