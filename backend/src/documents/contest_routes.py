"""
Redaction Contest and Document Rejection Routes
Handles contesting redactions and rejecting documents
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..cases.permissions import (
    can_contest_redactions,
    can_reject_documents,
    get_user_role_on_case,
    is_case_team_member,
)
from ..database import db
from ..dependencies import get_current_user

router = APIRouter()
redaction_contests = db["redaction_contests"]
document_rejections = db["document_rejections"]


class ContestRedactionRequest(BaseModel):
    """Request to contest a redaction"""

    redaction_index: int
    reason: str


class ResolveContestRequest(BaseModel):
    """Resolve a redaction contest"""

    resolution: str  # "kept", "removed", "modified"
    resolution_notes: str | None = None


class RejectDocumentRequest(BaseModel):
    """Request to reject a document"""

    reason: str
    details: str | None = None


class AddressRejectionRequest(BaseModel):
    """Address a document rejection"""

    resolution_notes: str


@router.post("/{document_id}/redactions/{redaction_index}/contest")
async def contest_redaction(
    document_id: str,
    redaction_index: int,
    request: ContestRedactionRequest,
    current_user=Depends(get_current_user),
):
    """
    Contest a redaction.
    Legal, reviewers, and third-parties can contest redactions.
    """
    # Get document and case
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if not user_role or not can_contest_redactions(user_role):
        raise HTTPException(
            status_code=403, detail="You don't have permission to contest redactions"
        )

    # Get redaction
    redactions = doc.get("redactions", [])
    if redaction_index >= len(redactions):
        raise HTTPException(status_code=404, detail="Redaction not found")

    redaction = redactions[redaction_index]

    # Create contest
    contest_id = str(uuid.uuid4())
    contest = {
        "id": contest_id,
        "case_id": case["id"],
        "document_id": document_id,
        "redaction_index": redaction_index,
        "redaction": redaction,
        "contested_by": current_user["id"],
        "contested_by_role": user_role,
        "contested_by_name": current_user.get("username"),
        "reason": request.reason,
        "status": "open",
        "created_at": datetime.utcnow(),
        "resolved_at": None,
        "resolved_by": None,
        "resolution": None,
        "resolution_notes": None,
    }

    await redaction_contests.insert_one(contest)

    # Update redaction to mark as contested
    await db.documents.update_one(
        {"id": document_id},
        {
            "$set": {
                f"redactions.{redaction_index}.is_contested": True,
                f"redactions.{redaction_index}.status": "contested",
            },
            "$inc": {f"redactions.{redaction_index}.active_contests": 1},
        },
    )

    # Add to audit log
    await db.cases.update_one(
        {"id": case["id"]},
        {
            "$push": {
                "audit_log": {
                    "action": "redaction_contested",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "document_id": document_id,
                        "filename": doc.get("filename"),
                        "redaction_index": redaction_index,
                        "reason": request.reason,
                    },
                }
            }
        },
    )

    return {"success": True, "message": "Redaction contested", "contest_id": contest_id}


@router.get("/{document_id}/contests")
async def get_document_contests(document_id: str, current_user=Depends(get_current_user)):
    """Get all contests for a document"""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check access
    if not is_case_team_member(case.get("case_team", []), current_user["id"]):
        raise HTTPException(status_code=403, detail="You don't have access to this case")

    # Get contests
    cursor = redaction_contests.find({"document_id": document_id})
    contests = await cursor.to_list(length=100)

    # Remove MongoDB _id
    for contest in contests:
        contest.pop("_id", None)

    return {"document_id": document_id, "contests": contests, "count": len(contests)}


@router.put("/contests/{contest_id}/resolve")
async def resolve_contest(
    contest_id: str, request: ResolveContestRequest, current_user=Depends(get_current_user)
):
    """
    Resolve a redaction contest.
    Only analysts and managers can resolve contests.
    """
    contest = await redaction_contests.find_one({"id": contest_id})
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")

    case = await db.cases.find_one({"id": contest["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if user_role not in ["analyst", "manager"]:
        raise HTTPException(
            status_code=403, detail="Only analysts and managers can resolve contests"
        )

    # Update contest
    await redaction_contests.update_one(
        {"id": contest_id},
        {
            "$set": {
                "status": "resolved",
                "resolved_at": datetime.utcnow(),
                "resolved_by": current_user["id"],
                "resolution": request.resolution,
                "resolution_notes": request.resolution_notes,
            }
        },
    )

    # Update redaction based on resolution
    doc_id = contest["document_id"]
    redaction_index = contest["redaction_index"]

    if request.resolution == "removed":
        # Remove the redaction
        await db.documents.update_one(
            {"id": doc_id}, {"$pull": {"redactions": {"$eq": contest["redaction"]}}}
        )
    else:
        # Decrement active contests, update status if no more contests
        doc = await db.documents.find_one({"id": doc_id})
        redactions = doc.get("redactions", [])
        if redaction_index < len(redactions):
            new_contest_count = redactions[redaction_index].get("active_contests", 1) - 1
            new_status = "approved" if new_contest_count == 0 else "contested"

            await db.documents.update_one(
                {"id": doc_id},
                {
                    "$set": {
                        f"redactions.{redaction_index}.active_contests": new_contest_count,
                        f"redactions.{redaction_index}.is_contested": new_contest_count > 0,
                        f"redactions.{redaction_index}.status": new_status,
                    }
                },
            )

    # Add to audit log
    await db.cases.update_one(
        {"id": case["id"]},
        {
            "$push": {
                "audit_log": {
                    "action": "contest_resolved",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "contest_id": contest_id,
                        "resolution": request.resolution,
                        "notes": request.resolution_notes,
                    },
                }
            }
        },
    )

    return {"success": True, "message": f"Contest resolved: {request.resolution}"}


@router.post("/{document_id}/reject")
async def reject_document(
    document_id: str, request: RejectDocumentRequest, current_user=Depends(get_current_user)
):
    """
    Reject a document.
    Reviewers and approvers can reject documents.
    """
    # Get document and case
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if not user_role or not can_reject_documents(user_role):
        raise HTTPException(
            status_code=403, detail="Only reviewers and approvers can reject documents"
        )

    # Create rejection
    rejection_id = str(uuid.uuid4())
    rejection = {
        "id": rejection_id,
        "case_id": case["id"],
        "document_id": document_id,
        "rejected_by": current_user["id"],
        "rejected_by_role": user_role,
        "rejected_by_name": current_user.get("username"),
        "reason": request.reason,
        "details": request.details,
        "status": "open",
        "created_at": datetime.utcnow(),
        "addressed_at": None,
        "addressed_by": None,
        "resolution_notes": None,
    }

    await document_rejections.insert_one(rejection)

    # Update document status
    await db.documents.update_one({"id": document_id}, {"$set": {"status": "rejected"}})

    # Add to audit log
    await db.cases.update_one(
        {"id": case["id"]},
        {
            "$push": {
                "audit_log": {
                    "action": "document_rejected",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "document_id": document_id,
                        "filename": doc.get("filename"),
                        "reason": request.reason,
                        "details": request.details,
                    },
                }
            }
        },
    )

    return {"success": True, "message": "Document rejected", "rejection_id": rejection_id}


@router.get("/{document_id}/rejections")
async def get_document_rejections(document_id: str, current_user=Depends(get_current_user)):
    """Get all rejections for a document"""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check access
    if not is_case_team_member(case.get("case_team", []), current_user["id"]):
        raise HTTPException(status_code=403, detail="You don't have access to this case")

    # Get rejections
    cursor = document_rejections.find({"document_id": document_id})
    rejections = await cursor.to_list(length=100)

    # Remove MongoDB _id
    for rejection in rejections:
        rejection.pop("_id", None)

    return {"document_id": document_id, "rejections": rejections, "count": len(rejections)}


@router.put("/rejections/{rejection_id}/address")
async def address_rejection(
    rejection_id: str, request: AddressRejectionRequest, current_user=Depends(get_current_user)
):
    """
    Address a document rejection.
    Only analysts and managers can address rejections.
    """
    rejection = await document_rejections.find_one({"id": rejection_id})
    if not rejection:
        raise HTTPException(status_code=404, detail="Rejection not found")

    case = await db.cases.find_one({"id": rejection["case_id"]})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if user_role not in ["analyst", "manager"]:
        raise HTTPException(
            status_code=403, detail="Only analysts and managers can address rejections"
        )

    # Update rejection
    await document_rejections.update_one(
        {"id": rejection_id},
        {
            "$set": {
                "status": "addressed",
                "addressed_at": datetime.utcnow(),
                "addressed_by": current_user["id"],
                "resolution_notes": request.resolution_notes,
            }
        },
    )

    # Update document status back to under review
    await db.documents.update_one(
        {"id": rejection["document_id"]}, {"$set": {"status": "under_review"}}
    )

    # Add to audit log
    await db.cases.update_one(
        {"id": case["id"]},
        {
            "$push": {
                "audit_log": {
                    "action": "rejection_addressed",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "rejection_id": rejection_id,
                        "resolution_notes": request.resolution_notes,
                    },
                }
            }
        },
    )

    return {"success": True, "message": "Rejection addressed"}
