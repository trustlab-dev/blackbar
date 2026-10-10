"""
Redaction Proposal Routes
Handles proposed redactions, approvals — extends the main document redaction CRUD.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.utils.redaction_records import (
    APPROVED,
    GEOMETRY_FIELDS,
    REJECTED,
    UNRESOLVED_REASONS,
    coordinate_space_fields,
    effective_status,
    find_redaction,
    has_legacy_coordinates,
    new_redaction_record,
    page_rotation_of,
    review_state,
)

from ..cases.permissions import (
    can_approve_proposed_redactions,
    can_create_redactions,
    can_propose_redactions,
    get_user_role_on_case,
    is_case_team_member,
)
from ..core.authz import assert_document_access, check_document_access
from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user
from .redaction_store import get_page_sizes, page_rotations, validate_or_422

# check_document_access / assert_document_access are imported from
# ..core.authz (single canonical implementation).


router = APIRouter()

# Fields a client may set when adding a redaction (AUTH-07). Everything else
# (id, status, approval/contest state, source, creator) is server-controlled.
_CLIENT_REDACTION_FIELDS = frozenset(
    {
        "x",
        "y",
        "width",
        "height",
        "page",
        "category",
        "description",
        "reason",
        "notes",
        "text",
        "color",
        "section",
    }
)


async def get_db(request: Request):
    return await get_database_from_request(request)


# System roles that may create, move and delete professional redactions on
# any document they can access (mirrors core/authz global access).
_REDACTION_MANAGER_ROLES = frozenset({"owner", "admin", "analyst"})


def can_manage_redactions(current_user: dict, case: dict | None) -> bool:
    """Owner/admin/analyst, or a case-team manager/analyst (DOC-16)."""
    if current_user.get("role") in _REDACTION_MANAGER_ROLES:
        return True
    if not case:
        return False
    case_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    return bool(case_role) and can_create_redactions(case_role)


def assert_can_modify_redaction(redaction: dict, current_user: dict, case: dict | None) -> None:
    """Managers may change any redaction. Everyone else only their own
    redaction while it is still a proposal; approved (and rejected)
    redactions are out of reach for plain case-team members (DOC-16)."""
    if can_manage_redactions(current_user, case):
        return
    own = redaction.get("created_by") == current_user["id"]
    still_proposed = str(redaction.get("status") or "").lower() in ("proposed", "pending")
    if own and still_proposed and effective_status(redaction) != APPROVED:
        return
    raise HTTPException(
        status_code=403,
        detail="Only analysts can change or delete this redaction",
    )


async def _redaction_id_for_ref(db, document_id: str, redactions: list[dict], ref: str):
    """Resolve a path reference (stable id, or legacy index for records
    without an id) to (redaction_id, redaction). Legacy records get an id."""
    found = find_redaction(redactions, ref)
    if not found:
        raise HTTPException(status_code=404, detail="Redaction not found")
    index, redaction = found
    if not redaction.get("id"):
        new_id = str(uuid.uuid4())
        result = await db.documents.update_one(
            {"id": document_id, f"redactions.{index}.id": {"$exists": False}},
            {"$set": {f"redactions.{index}.id": new_id}},
        )
        if result.modified_count == 0:
            raise HTTPException(
                status_code=409, detail="Redactions changed concurrently; reload and retry"
            )
        redaction = {**redaction, "id": new_id}
    return redaction["id"], redaction


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

    page_sizes = await get_page_sizes(doc, db)
    geometry = validate_or_422(data.model_dump(), page_sizes)
    redaction = new_redaction_record(
        geometry,
        status="proposed",
        created_by=current_user["id"],
        created_by_role=user_role,
        source="proposal",
        page_rotation=page_rotation_of(page_sizes, geometry.page),
        category=data.category,
        type="proposed",
        proposed_by=current_user["id"],
        proposed_by_role=user_role,
        proposed_reason=data.reason,
        approval_status="pending",
        is_contested=False,
        active_contests=0,
    )

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


@router.put("/{document_id}/redactions/{redaction_ref}/approve")
async def approve_or_reject_proposed_redaction(
    document_id: str,
    redaction_ref: str,
    request: Request,
    data: ApproveProposedRedactionRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Approve or reject a proposed redaction.

    ``redaction_ref`` is the redaction's stable id. A numeric index is only
    accepted for legacy records that have no id yet (DOC-23).
    """
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    case = await db.cases.find_one({"id": doc["case_id"]}) if doc.get("case_id") else None
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    user_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    system_manager = current_user.get("role") in _REDACTION_MANAGER_ROLES
    if not system_manager and (not user_role or not can_approve_proposed_redactions(user_role)):
        raise HTTPException(status_code=403, detail="Only analysts and managers can approve/reject")
    assert_document_access(doc, current_user, case)

    if data.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    redaction_id, redaction = await _redaction_id_for_ref(
        db, document_id, doc.get("redactions", []), redaction_ref
    )

    # Which records can be decided here (I1): proposals, and legacy records
    # that block release (pending, role-less, legacy boxes on rotated
    # pages, unknown status). Records without usable geometry cannot be
    # approved; they must be deleted and re-added.
    state, reason = review_state(redaction)
    page_sizes: list[list[float]] = []
    if (state == APPROVED and has_legacy_coordinates(redaction)) or (
        data.action == "approve" and reason != "no_geometry"
    ):
        page_sizes = await get_page_sizes(doc, db)
        state, reason = review_state(redaction, page_rotations(page_sizes))
    if state == REJECTED:
        raise HTTPException(status_code=409, detail="This redaction has already been rejected")
    if state == APPROVED:
        raise HTTPException(
            status_code=400, detail="This is not a proposed redaction; it is already approved"
        )
    if reason == "contested":
        raise HTTPException(
            status_code=409,
            detail="This redaction has an open contest; resolve the contest instead",
        )
    if reason == "no_geometry" and data.action == "approve":
        raise HTTPException(status_code=422, detail=UNRESOLVED_REASONS["no_geometry"][0])

    now = datetime.utcnow()
    if data.action == "approve":
        update_fields = {
            "redactions.$.type": "professional",
            "redactions.$.status": "approved",
            "redactions.$.approval_status": "approved",
        }
        # Approval confirms the position the reviewer saw in the viewer,
        # which is displayed space (C1).
        for field, value in coordinate_space_fields(
            page_rotation_of(page_sizes, int(redaction["page"]))
        ).items():
            update_fields[f"redactions.$.{field}"] = value
        message = "Proposed redaction approved"
    else:
        update_fields = {
            "redactions.$.status": "rejected",
            "redactions.$.approval_status": "rejected",
        }
        message = "Proposed redaction rejected"
    update_fields.update(
        {
            "redactions.$.reviewed_by": current_user["id"],
            "redactions.$.reviewed_at": now,
            "redactions.$.review_notes": data.notes,
        }
    )
    if reason and reason != "proposed":
        update_fields["redactions.$.legacy_resolved"] = reason

    # The filter pins the redaction by id AND the status it was decided
    # on, so a stale or concurrent request cannot overwrite a newer state.
    result = await db.documents.update_one(
        {
            "id": document_id,
            "redactions": {"$elemMatch": {"id": redaction_id, "status": redaction.get("status")}},
        },
        {"$set": update_fields},
    )
    if result.modified_count == 0:
        raise HTTPException(
            status_code=409, detail="Redaction changed concurrently; reload and retry"
        )

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
                    "timestamp": now,
                    "details": {
                        "document_id": document_id,
                        "filename": doc.get("filename"),
                        "redaction_id": redaction_id,
                        "notes": data.notes,
                    },
                }
            }
        },
    )

    return {"success": True, "message": message, "redaction_id": redaction_id}


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

    # Object-level access (AUTH-07): fails closed when the document has no
    # case or its case was deleted; previously that skipped the check.
    case = await db.cases.find_one({"id": doc["case_id"]}) if doc.get("case_id") else None
    assert_document_access(doc, current_user, case)

    # Geometry is validated against the document's real pages (DOC-02/07).
    if not isinstance(redaction, dict):
        raise HTTPException(status_code=422, detail="Invalid redaction: expected an object")
    page_sizes = await get_page_sizes(doc, db)
    geometry = validate_or_422(redaction, page_sizes)

    # Only client-editable fields survive; the id and every workflow/status
    # field are set here (no mass assignment, no id collisions).
    extra = {
        k: v
        for k, v in redaction.items()
        if k in _CLIENT_REDACTION_FIELDS and k not in GEOMETRY_FIELDS
    }
    # Analysts (system or case role) create professional redactions that are
    # approved immediately; anyone else creates a proposal that an analyst
    # must approve before it is applied (DOC-13, DOC-16).
    if can_manage_redactions(current_user, case):
        extra.update(type="professional")
        status = "approved"
    else:
        extra.update(
            type="proposed",
            proposed_by=current_user["id"],
            approval_status="pending",
            is_contested=False,
            active_contests=0,
        )
        status = "proposed"
    redaction = new_redaction_record(
        geometry,
        status=status,
        created_by=current_user["id"],
        created_by_role=current_user.get("role", "user"),
        source="manual",
        page_rotation=page_rotation_of(page_sizes, geometry.page),
        created_by_name=current_user.get("username", "Unknown"),
        **extra,
    )

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

    message = "Redaction added" if status == "approved" else "Redaction proposed for review"
    return {"message": message, "id": redaction["id"], "status": status}


# APPROVE OR REJECT REDACTION (New)
@router.put(
    "/{document_id}/redactions/{redaction_id}",
    dependencies=[Depends(check_role(["owner", "admin"]))],
)
async def update_redaction_status(
    request: Request, document_id: str, redaction_id: str, status: str, db=Depends(get_db)
):
    """Reviewers can approve/reject redactions."""
    if status not in ["accepted", "approved", "rejected"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    # "accepted" is the legacy spelling; store the one status the release
    # rule recognises.
    status = "approved" if status == "accepted" else status

    # Phase 4 Batch 4.4 (audit B27): the filter previously used
    # `redactions._id` but `add_redaction` writes the field as
    # `redactions.id`, so the endpoint always returned 404 for normally-
    # added redactions. Use the matching `id` field.
    result = await db.documents.update_one(
        {"id": document_id, "redactions.id": redaction_id},
        {"$set": {"redactions.$.status": status}},
    )
    if result.matched_count == 0:
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

    # Get case for audit logging + object-level access check. The route
    # role gate admits `user`, so a plain user off the case team must be
    # blocked here from editing/moving redactions on another case's doc.
    case = await db.cases.find_one({"id": doc["case_id"]}) if doc.get("case_id") else None
    if not check_document_access(doc, current_user, case):
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    if not isinstance(updates, dict):
        raise HTTPException(status_code=422, detail="Invalid update: expected an object")

    # Find the redaction by stable id
    redactions = doc.get("redactions", [])
    updated_redaction = next((r for r in redactions if r.get("id") == redaction_id), None)
    if updated_redaction is None:
        raise HTTPException(status_code=404, detail="Redaction not found")
    assert_can_modify_redaction(updated_redaction, current_user, case)

    set_fields: dict = {}
    for field in ("reason", "notes"):
        if field in updates:
            set_fields[f"redactions.$.{field}"] = updates[field]
    moved = {k: updates[k] for k in ("x", "y", "width", "height") if k in updates}
    if moved:
        # A moved or resized box is re-validated against the page.
        page_sizes = await get_page_sizes(doc, db)
        geometry = validate_or_422({**updated_redaction, **moved}, page_sizes)
        for field in ("x", "y", "width", "height"):
            set_fields[f"redactions.$.{field}"] = getattr(geometry, field)
        # The box was moved in the viewer, so it is now in displayed space.
        for field, value in coordinate_space_fields(
            page_rotation_of(page_sizes, geometry.page)
        ).items():
            set_fields[f"redactions.$.{field}"] = value
    if set_fields:
        await db.documents.update_one(
            {"id": document_id, "redactions.id": redaction_id}, {"$set": set_fields}
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

    # Object-level access (AUTH-07): fails closed for case-less documents.
    case = await db.cases.find_one({"id": doc["case_id"]}) if doc.get("case_id") else None
    assert_document_access(doc, current_user, case)

    redactions = doc.get("redactions", [])
    deleted_redaction = next((r for r in redactions if r.get("id") == redaction_id), None)
    if not deleted_redaction:
        raise HTTPException(status_code=404, detail="Redaction not found")
    assert_can_modify_redaction(deleted_redaction, current_user, case)

    await db.documents.update_one(
        {"id": document_id}, {"$pull": {"redactions": {"id": redaction_id}}}
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
