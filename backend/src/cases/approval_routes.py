"""
Case Approval Routes
Endpoints for case approval workflow
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.database import get_database_from_request
from ..dependencies import get_current_user
from .permissions import get_user_role_on_case, is_case_team_member

router = APIRouter()


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


# Database collections
class ApprovalRequest(BaseModel):
    """Request to approve a case"""

    notes: str | None = None


class RejectApprovalRequest(BaseModel):
    """Request to reject case approval"""

    reason: str


@router.post("/{case_id}/approve")
async def approve_case(
    req: Request,
    case_id: str,
    request: ApprovalRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Approve a case for release.
    Only Approvers and Managers can approve cases.
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission: must be approver, manager, or analyst
    user_role_on_case = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if user_role_on_case not in ["approver", "manager", "analyst"]:
        raise HTTPException(
            status_code=403, detail="Only Approvers, Managers, and Analysts can approve cases"
        )

    # Update case
    await db.cases.update_one(
        {"id": case_id},
        {
            "$set": {
                "approval_status": "approved",
                "approved_by": current_user["id"],
                "approved_at": datetime.utcnow(),
                "approval_notes": request.notes,
                "updated_at": datetime.utcnow(),
            },
            "$push": {
                "audit_log": {
                    "action": "case_approved",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {"notes": request.notes},
                }
            },
        },
    )

    return {"success": True, "message": "Case approved for release", "approval_status": "approved"}


@router.post("/{case_id}/reject-approval")
async def reject_case_approval(
    req: Request,
    case_id: str,
    request: RejectApprovalRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Reject case approval.
    Only Approvers and Managers can reject approval.
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission: must be approver, manager, or analyst
    user_role_on_case = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if user_role_on_case not in ["approver", "manager", "analyst"]:
        raise HTTPException(
            status_code=403, detail="Only Approvers, Managers, and Analysts can reject approval"
        )

    # Update case
    await db.cases.update_one(
        {"id": case_id},
        {
            "$set": {
                "approval_status": "rejected",
                "approved_by": current_user["id"],
                "approved_at": datetime.utcnow(),
                "approval_notes": request.reason,
                "updated_at": datetime.utcnow(),
            },
            "$push": {
                "audit_log": {
                    "action": "case_approval_rejected",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {"reason": request.reason},
                }
            },
        },
    )

    return {"success": True, "message": "Case approval rejected", "approval_status": "rejected"}


@router.get("/{case_id}/approval-status")
async def get_approval_status(
    request: Request, case_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """
    Get case approval status.
    All team members can view.
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check access: must be team member, analyst, admin, or OWNER
    user_role = current_user.get("role")
    if user_role not in ["owner", "admin", "analyst"] and not is_case_team_member(
        case.get("case_team", []), current_user["id"]
    ):
        raise HTTPException(status_code=403, detail="You don't have access to this case")

    return {
        "case_id": case_id,
        "approval_status": case.get("approval_status"),
        "approved_by": case.get("approved_by"),
        "approved_at": case.get("approved_at"),
        "approval_notes": case.get("approval_notes"),
    }
