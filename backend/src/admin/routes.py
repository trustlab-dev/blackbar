import re as re_module

from fastapi import APIRouter, Depends, Request

from ..core.dependencies import require_admin_access
from ..database import db

router = APIRouter(prefix="/admin", tags=["Admin"])

users = db["users"]


@router.get("/users/search", dependencies=[Depends(require_admin_access)])
async def search_users(
    request: Request, q: str | None = None, role: str | None = None, limit: int = 20
):
    """
    Search users for team assignment.
    Returns users matching query by username or email.
    """
    query: dict = {"status": "active"}

    search_conditions = []
    if q and len(q) >= 2:
        escaped_q = re_module.escape(q)
        search_conditions.append({"email": {"$regex": escaped_q, "$options": "i"}})
        search_conditions.append({"name": {"$regex": escaped_q, "$options": "i"}})

    if search_conditions:
        query["$or"] = search_conditions

    if role:
        query["role"] = role.lower()

    cursor = users.find(query, {"password_hash": 0, "password": 0}).limit(limit)
    user_results = await cursor.to_list(length=limit)

    matching_users = []
    for user_doc in user_results:
        matching_users.append(
            {
                "id": user_doc.get("id"),
                "username": user_doc.get("email", "").split("@")[0],
                "name": user_doc.get("name"),
                "email": user_doc.get("email"),
                "role": user_doc.get("role", "user"),
            }
        )

    return {"users": matching_users}
