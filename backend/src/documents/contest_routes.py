"""
Redaction Contest and Document Rejection Routes
Handles contesting redactions and rejecting documents
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.utils.redaction_records import find_redaction

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

_RESOLUTIONS = frozenset({"kept", "removed", "modified"})
# Statuses a contest resolution may turn into "approved" (I2).
_DECIDABLE_STATUSES = frozenset({"proposed", "contested"})
document_rejections = db["document_rejections"]


class ContestRedactionRequest(BaseModel):
    """Request to contest a redaction.

    The redaction is identified by the path (its stable id). The body's
    ``redaction_index`` is accepted for backwards compatibility and ignored.
    """

    redaction_index: int | None = None
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


@router.post("/{document_id}/redactions/{redaction_ref}/contest")
async def contest_redaction(
    document_id: str,
    redaction_ref: str,
    request: ContestRedactionRequest,
    current_user=Depends(get_current_user),
):
    """
    Contest a redaction.
    Legal, reviewers, and third-parties can contest redactions.

    ``redaction_ref`` is the redaction's stable id; a numeric index is only
    accepted for legacy records that have no id yet (DOC-23).
    """
    # Get document and case
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]}) if doc.get("case_id") else None
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
    found = find_redaction(redactions, redaction_ref)
    if not found:
        raise HTTPException(status_code=404, detail="Redaction not found")
    index, redaction = found
    current_status = str(redaction.get("status") or "").lower()
    if current_status == "rejected":
        raise HTTPException(
            status_code=409, detail="A rejected redaction is not applied and cannot be contested"
        )
    redaction_id = redaction.get("id")
    if not redaction_id:
        redaction_id = str(uuid.uuid4())
        assigned = await db.documents.update_one(
            {"id": document_id, f"redactions.{index}.id": {"$exists": False}},
            {"$set": {f"redactions.{index}.id": redaction_id}},
        )
        if assigned.modified_count == 0:
            raise HTTPException(
                status_code=409, detail="Redactions changed concurrently; reload and retry"
            )
        redaction = {**redaction, "id": redaction_id}

    # Create contest
    contest_id = str(uuid.uuid4())
    contest = {
        "id": contest_id,
        "case_id": case["id"],
        "document_id": document_id,
        "redaction_id": redaction_id,
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

    # Update redaction to mark as contested (addressed by id, DOC-23). The
    # status it had before its first open contest is kept for the record.
    set_fields = {"redactions.$.is_contested": True, "redactions.$.status": "contested"}
    if current_status != "contested":
        set_fields["redactions.$.status_before_contest"] = redaction.get("status")
    await db.documents.update_one(
        {"id": document_id, "redactions.id": redaction_id},
        {"$set": set_fields, "$inc": {"redactions.$.active_contests": 1}},
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
                        "redaction_id": redaction_id,
                        "reason": request.reason,
                    },
                }
            }
        },
    )

    return {
        "success": True,
        "message": "Redaction contested",
        "contest_id": contest_id,
        "redaction_id": redaction_id,
    }


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

    if request.resolution not in _RESOLUTIONS:
        raise HTTPException(
            status_code=400, detail="Resolution must be 'kept', 'removed' or 'modified'"
        )
    if contest.get("status") != "open":
        raise HTTPException(status_code=409, detail="This contest has already been resolved")

    # Locate the contested redaction. Contests reference it by stable id
    # (DOC-23); legacy contests fall back to the snapshot's id, then to the
    # stored index, then (for "removed") to the full snapshot.
    doc_id = contest["document_id"]
    redaction_id = contest.get("redaction_id") or (contest.get("redaction") or {}).get("id")
    doc = await db.documents.find_one({"id": doc_id}) or {}
    redactions = doc.get("redactions", [])
    if redaction_id:
        index = next((i for i, r in enumerate(redactions) if r.get("id") == redaction_id), None)
    else:
        legacy_index = contest.get("redaction_index")
        index = (
            legacy_index
            if isinstance(legacy_index, int) and 0 <= legacy_index < len(redactions)
            else None
        )
    current = redactions[index] if index is not None else None

    # Keeping a redaction after its last contest approves it, so only a
    # redaction that is still awaiting a decision may be kept (I2).
    keeps = request.resolution != "removed"
    if keeps and current is not None:
        status = str(current.get("status") or "").lower()
        if status not in _DECIDABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The redaction is {status or 'without a status'}; resolving this "
                    "contest cannot approve it"
                ),
            )

    # Claim the contest: only one request can move it out of "open", so a
    # repeated resolve cannot decrement the contest count twice.
    now = datetime.utcnow()
    claimed = await redaction_contests.update_one(
        {"id": contest_id, "status": "open"},
        {
            "$set": {
                "status": "resolved",
                "resolved_at": now,
                "resolved_by": current_user["id"],
                "resolution": request.resolution,
                "resolution_notes": request.resolution_notes,
            }
        },
    )
    if claimed.modified_count == 0:
        raise HTTPException(status_code=409, detail="This contest has already been resolved")

    if not keeps:
        if redaction_id:
            await db.documents.update_one(
                {"id": doc_id}, {"$pull": {"redactions": {"id": redaction_id}}}
            )
        elif current is not None or contest.get("redaction"):
            await db.documents.update_one(
                {"id": doc_id},
                {"$pull": {"redactions": {"$eq": current or contest["redaction"]}}},
            )
    elif current is not None:
        new_count = max(int(current.get("active_contests") or 1) - 1, 0)
        prefix = "redactions.$" if redaction_id else f"redactions.{index}"
        update = {
            f"{prefix}.active_contests": new_count,
            f"{prefix}.is_contested": new_count > 0,
            f"{prefix}.status": "approved" if new_count == 0 else "contested",
        }
        if new_count == 0:
            update.update(
                {
                    f"{prefix}.approval_status": "approved",
                    f"{prefix}.reviewed_by": current_user["id"],
                    f"{prefix}.reviewed_at": now,
                }
            )
            if current.get("type") == "proposed":
                update[f"{prefix}.type"] = "professional"
        if redaction_id:
            match = {
                "id": doc_id,
                "redactions": {
                    "$elemMatch": {
                        "id": redaction_id,
                        "status": {"$in": sorted(_DECIDABLE_STATUSES)},
                    }
                },
            }
        else:
            match = {
                "id": doc_id,
                f"redactions.{index}.status": {"$in": sorted(_DECIDABLE_STATUSES)},
            }
        result = await db.documents.update_one(match, {"$set": update})
        if result.modified_count == 0:
            # The redaction changed underneath us: give the contest back.
            await redaction_contests.update_one(
                {"id": contest_id},
                {
                    "$set": {
                        "status": "open",
                        "resolved_at": None,
                        "resolved_by": None,
                        "resolution": None,
                        "resolution_notes": None,
                    }
                },
            )
            raise HTTPException(
                status_code=409, detail="Redaction changed concurrently; reload and retry"
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
