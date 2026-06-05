"""Team management routes"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..core.database import get_database_from_request
from ..database import users
from ..dependencies import check_role, get_current_user
from .models import TeamCreate, TeamUpdate


def convert_mongo_doc_to_json(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert MongoDB document to JSON serializable format."""
    if doc is None:
        return None

    result = {}
    for key, value in doc.items():
        if key == "_id":
            continue
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = convert_mongo_doc_to_json(value)
        elif isinstance(value, list):
            result[key] = [
                convert_mongo_doc_to_json(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


router = APIRouter(prefix="/teams", tags=["Teams"])


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


@router.post("/", dependencies=[Depends(check_role(["owner", "admin"]))])
async def create_team(
    request: Request, team: TeamCreate, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Create a new team."""
    team_id = str(uuid.uuid4())

    # Validate manager exists
    if team.manager_id:
        manager = await users.find_one({"id": team.manager_id})
        if not manager:
            raise HTTPException(status_code=404, detail="Manager not found")

    # Validate members exist
    for member_id in team.member_ids:
        member = await users.find_one({"id": member_id})
        if not member:
            raise HTTPException(status_code=404, detail=f"User {member_id} not found")

    team_data = {
        "id": team_id,
        **team.dict(),
        "last_assigned_index": 0,
        "active_cases": 0,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": current_user["id"],
    }

    await db.teams.insert_one(team_data)

    new_team = await db.teams.find_one({"id": team_id})
    return convert_mongo_doc_to_json(new_team)


@router.get("/", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def list_teams(request: Request, current_user=Depends(get_current_user), db=Depends(get_db)):
    """List all teams."""
    cursor = db.teams.find({})
    result = await cursor.to_list(length=100)

    return {"teams": [convert_mongo_doc_to_json(doc) for doc in result]}


@router.get("/{team_id}", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def get_team(
    request: Request, team_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Get a team by ID."""
    team = await db.teams.find_one({"id": team_id})

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Get member details
    member_ids = team.get("member_ids", [])
    members = []
    for member_id in member_ids:
        user = await users.find_one({"id": member_id}, {"password": 0})
        if user:
            members.append(convert_mongo_doc_to_json(user))

    team_dict = convert_mongo_doc_to_json(team)
    team_dict["members"] = members

    return team_dict


@router.put("/{team_id}", dependencies=[Depends(check_role(["owner", "admin"]))])
async def update_team(
    request: Request,
    team_id: str,
    team_update: TeamUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Update a team."""
    team = await db.teams.find_one({"id": team_id})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check permission (only manager or admin)
    user_role = current_user.get("role")
    if user_role != "admin" and current_user["id"] != team.get("manager_id"):
        raise HTTPException(status_code=403, detail="You don't have permission to update this team")

    # Validate new manager if provided
    if team_update.manager_id:
        manager = await users.find_one({"id": team_update.manager_id})
        if not manager:
            raise HTTPException(status_code=404, detail="Manager not found")

    # Validate new members if provided
    if team_update.member_ids:
        for member_id in team_update.member_ids:
            member = await users.find_one({"id": member_id})
            if not member:
                raise HTTPException(status_code=404, detail=f"User {member_id} not found")

    update_data = {k: v for k, v in team_update.dict(exclude_unset=True).items() if v is not None}
    if not update_data:
        return convert_mongo_doc_to_json(team)

    update_data["updated_at"] = datetime.utcnow()

    await db.teams.update_one({"id": team_id}, {"$set": update_data})

    updated_team = await db.teams.find_one({"id": team_id})
    return convert_mongo_doc_to_json(updated_team)


@router.delete("/{team_id}", dependencies=[Depends(check_role(["owner", "admin"]))])
async def delete_team(
    request: Request, team_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Delete a team (admin only)."""
    team = await db.teams.find_one({"id": team_id})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if team has active cases
    active_cases = await db.cases.count_documents(
        {"team": team_id, "status": {"$nin": ["completed", "closed"]}}
    )
    if active_cases > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete team with {active_cases} active cases. Reassign or close them first.",
        )

    await db.teams.delete_one({"id": team_id})

    return {"success": True, "message": "Team deleted"}


@router.get("/{team_id}/cases", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def get_team_cases(
    request: Request,
    team_id: str,
    skip: int = 0,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Get all cases assigned to a team."""
    team = await db.teams.find_one({"id": team_id})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check permission
    user_role = current_user.get("role")
    if user_role not in ["admin", "manager"] and current_user["id"] not in team.get(
        "member_ids", []
    ):
        raise HTTPException(
            status_code=403, detail="You don't have permission to view this team's cases"
        )

    cursor = db.cases.find({"team": team_id}).skip(skip).limit(limit).sort("created_at", -1)
    result = await cursor.to_list(length=limit)
    total = await db.cases.count_documents({"team": team_id})

    return {
        "cases": [convert_mongo_doc_to_json(doc) for doc in result],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/{team_id}/members/{user_id}", dependencies=[Depends(check_role(["owner", "admin"]))])
async def add_team_member(
    request: Request,
    team_id: str,
    user_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Add a member to a team."""
    team = await db.teams.find_one({"id": team_id})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    user = await users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check permission
    user_role = current_user.get("role")
    if user_role != "admin" and current_user["id"] != team.get("manager_id"):
        raise HTTPException(status_code=403, detail="You don't have permission to modify this team")

    # Add member if not already in team
    if user_id not in team.get("member_ids", []):
        await db.teams.update_one(
            {"id": team_id},
            {"$addToSet": {"member_ids": user_id}, "$set": {"updated_at": datetime.utcnow()}},
        )

    updated_team = await db.teams.find_one({"id": team_id})
    return convert_mongo_doc_to_json(updated_team)


@router.delete(
    "/{team_id}/members/{user_id}", dependencies=[Depends(check_role(["owner", "admin"]))]
)
async def remove_team_member(
    request: Request,
    team_id: str,
    user_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Remove a member from a team."""
    team = await db.teams.find_one({"id": team_id})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check permission
    user_role = current_user.get("role")
    if user_role != "admin" and current_user["id"] != team.get("manager_id"):
        raise HTTPException(status_code=403, detail="You don't have permission to modify this team")

    await db.teams.update_one(
        {"id": team_id},
        {"$pull": {"member_ids": user_id}, "$set": {"updated_at": datetime.utcnow()}},
    )

    updated_team = await db.teams.find_one({"id": team_id})
    return convert_mongo_doc_to_json(updated_team)
