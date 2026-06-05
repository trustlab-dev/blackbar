"""
Case Team Management Routes
Endpoints for managing case-specific collaboration teams
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.database import get_database_from_request
from ..database import db
from ..dependencies import check_role, get_current_user
from .permissions import (
    can_manage_team,
    get_permissions_for_role,
    get_user_role_on_case,
    is_case_team_member,
)

router = APIRouter()


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


# Database collections
users = db["users"]

# Strict case team role restrictions based on system role
ALLOWED_CASE_ROLES: dict[str, list[str]] = {
    "owner": [
        "manager",
        "analyst",
        "legal",
        "subject_matter_expert",
        "reviewer",
        "approver",
        "third_party",
    ],
    "admin": ["manager", "analyst", "legal", "subject_matter_expert", "reviewer", "approver"],
    "analyst": ["analyst", "manager"],
    "user": ["legal", "subject_matter_expert", "reviewer", "approver"],
    "guest": ["third_party"],
}


class AddTeamMemberRequest(BaseModel):
    """Request to add a member to case team"""

    user_id: str
    role: str  # analyst, legal, sme, reviewer, approver, third_party, manager
    department: str | None = None
    notes: str | None = None


class UpdateTeamMemberRequest(BaseModel):
    """Request to update a team member"""

    role: str | None = None
    department: str | None = None
    notes: str | None = None
    review_status: str | None = None
    approval_status: str | None = None


@router.get("/{case_id}/team")
async def get_case_team(
    request: Request, case_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """
    Get the case team members.
    User must be a team member or admin to view.
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

    # Get full user details for each team member
    team_members = []
    for member in case.get("case_team", []):
        # Try to find user by id field first, then by _id (for backwards compatibility)
        user = await users.find_one({"id": member["user_id"]}, {"password_hash": 0})
        if not user:
            # Try finding by MongoDB _id
            try:
                from bson import ObjectId

                user = await users.find_one(
                    {"_id": ObjectId(member["user_id"])}, {"password_hash": 0}
                )
            except:
                pass
        if user:
            team_member_data = {
                **member,
                "user_name": user.get("name") or user.get("email", "").split("@")[0],
                "user_email": user.get("email"),
            }
            team_members.append(team_member_data)
        else:
            # User not found (e.g., mock admin user in DEV_MODE)
            # Still include them but with placeholder info
            team_member_data = {
                **member,
                "user_name": member["user_id"],  # Use ID as name
                "user_email": None,
            }
            team_members.append(team_member_data)

    return {"case_id": case_id, "team_members": team_members}


@router.post(
    "/{case_id}/team/members", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def add_team_member(
    req: Request,
    case_id: str,
    request: AddTeamMemberRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Add a member to the case team.
    Owners, admins, analysts, and managers can add team members.
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission: must be team member with manage_team permission or admin
    user_role_on_case = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if current_user.get("role") not in ["owner", "admin"] and not can_manage_team(
        user_role_on_case or ""
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to manage this team")

    # Validate user exists
    user = await users.find_one({"id": request.user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate case team role is appropriate for user's system role
    user_system_role = user.get("role", "user")
    allowed_case_roles = ALLOWED_CASE_ROLES.get(user_system_role, [])

    if request.role not in allowed_case_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Users with system role '{user_system_role}' cannot be assigned case team role '{request.role}'. Allowed roles: {', '.join(allowed_case_roles)}",
        )

    # Check if user is already on team
    case_team = case.get("case_team", [])
    for member in case_team:
        if member["user_id"] == request.user_id and member["status"] == "active":
            raise HTTPException(status_code=400, detail="User is already on the team")

    # Get permissions for role
    permissions = get_permissions_for_role(request.role)

    # Create new team member
    new_member = {
        "user_id": request.user_id,
        "role": request.role,
        "department": request.department,
        "permissions": permissions,
        "added_at": datetime.utcnow(),
        "added_by": current_user["id"],
        "status": "active",
        "notes": request.notes,
    }

    # Add review/approval status for relevant roles
    if request.role in ["legal", "reviewer"]:
        new_member["review_status"] = "pending"
    if request.role == "approver":
        new_member["approval_status"] = "pending"

    # Update case
    await db.cases.update_one(
        {"id": case_id},
        {
            "$push": {
                "case_team": new_member,
                "audit_log": {
                    "action": "team_member_added",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "added_user_id": request.user_id,
                        "added_user_name": user.get("username"),
                        "role": request.role,
                    },
                },
            }
        },
    )

    return {
        "success": True,
        "message": f"Added {user.get('username')} to case team as {request.role}",
        "member": new_member,
    }


@router.delete("/{case_id}/team/members/{user_id}")
async def remove_team_member(
    request: Request,
    case_id: str,
    user_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Remove a member from the case team.
    Only analysts and managers can remove team members.
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role_on_case = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if current_user.get("role") not in ["owner", "admin"] and not can_manage_team(
        user_role_on_case or ""
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to manage this team")

    # Find the member
    case_team = case.get("case_team", [])
    member_found = False
    for member in case_team:
        if member["user_id"] == user_id and member["status"] == "active":
            member_found = True
            break

    if not member_found:
        raise HTTPException(status_code=404, detail="User not found on team")

    # Get user info for audit log
    user = await users.find_one({"id": user_id})

    # Update member status to "removed" instead of deleting
    await db.cases.update_one(
        {"id": case_id, "case_team.user_id": user_id},
        {
            "$set": {"case_team.$.status": "removed"},
            "$push": {
                "audit_log": {
                    "action": "team_member_removed",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "removed_user_id": user_id,
                        "removed_user_name": user.get("username") if user else "Unknown",
                    },
                }
            },
        },
    )

    return {
        "success": True,
        "message": f"Removed {user.get('username') if user else 'user'} from case team",
    }


@router.put("/{case_id}/team/members/{user_id}")
async def update_team_member(
    req: Request,
    case_id: str,
    user_id: str,
    request: UpdateTeamMemberRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Update a team member's role, status, or other fields.
    Only analysts and managers can update team members.
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role_on_case = get_user_role_on_case(case.get("case_team", []), current_user["id"])
    if current_user.get("role") not in ["owner", "admin"] and not can_manage_team(
        user_role_on_case or ""
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to manage this team")

    # Find the member
    case_team = case.get("case_team", [])
    member_index = None
    for i, member in enumerate(case_team):
        if member["user_id"] == user_id and member["status"] == "active":
            member_index = i
            break

    if member_index is None:
        raise HTTPException(status_code=404, detail="User not found on team")

    # Build update. Typed as dict[str, Any] because the assigned values
    # are heterogeneous (str, list, datetime) — narrowing to str only
    # would re-introduce the BSON-Date-as-string drift fixed in 2c6b67b.
    update_fields: dict[str, Any] = {}
    if request.role:
        update_fields[f"case_team.{member_index}.role"] = request.role
        update_fields[f"case_team.{member_index}.permissions"] = get_permissions_for_role(
            request.role
        )
    if request.department:
        update_fields[f"case_team.{member_index}.department"] = request.department
    if request.notes:
        update_fields[f"case_team.{member_index}.notes"] = request.notes
    if request.review_status:
        update_fields[f"case_team.{member_index}.review_status"] = request.review_status
        if request.review_status in ["approved", "rejected"]:
            update_fields[f"case_team.{member_index}.review_completed_at"] = datetime.utcnow()
    if request.approval_status:
        update_fields[f"case_team.{member_index}.approval_status"] = request.approval_status

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Update case
    await db.cases.update_one(
        {"id": case_id},
        {
            "$set": update_fields,
            "$push": {
                "audit_log": {
                    "action": "team_member_updated",
                    "user_id": current_user["id"],
                    "username": current_user.get("username"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "updated_user_id": user_id,
                        "updates": request.dict(exclude_unset=True),
                    },
                }
            },
        },
    )

    return {"success": True, "message": "Team member updated"}
