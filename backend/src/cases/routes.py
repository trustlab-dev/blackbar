import logging
import re as re_module
import uuid
from datetime import datetime, timedelta
from typing import Any

from bson.objectid import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user
from .models import (
    CaseCreate,
    CaseDB,
    CasePriority,
    CaseStatus,
    CaseUpdate,
    CommentCreate,
    CommentType,
)
from .permissions import get_permissions_for_role, is_case_team_member
from .utils import generate_tracking_number

logger = logging.getLogger(__name__)


# Helper function to convert MongoDB documents to JSON serializable format
def convert_mongo_doc_to_json(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert MongoDB document to JSON serializable format."""
    if doc is None:
        return None

    result = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = convert_mongo_doc_to_json(value)
        elif isinstance(value, list):
            result[key] = [
                (
                    convert_mongo_doc_to_json(item)
                    if isinstance(item, dict)
                    else str(item)
                    if isinstance(item, ObjectId)
                    else item
                )
                for item in value
            ]
        else:
            result[key] = value
    return result


router = APIRouter(prefix="/cases", tags=["Cases"])

# Mount sub-routers BEFORE any @router.<verb>("/{case_id}") decorators
# below (B12 fix). FastAPI matches routes in registration order, so
# single-segment URLs like /search and /deadline-dashboard from
# queue_router must register first or they get caught by the
# /{case_id} catch-all and return 404.
from .team_routes import router as team_router

router.include_router(team_router)

from .approval_routes import router as approval_router

router.include_router(approval_router)

# Case queue, search, dashboard, and deadline routes — includes
# /search and /deadline-dashboard which would otherwise be shadowed
# by /{case_id}.
from .queue_routes import router as queue_router

router.include_router(queue_router)

# Collection-link routes (per-case upload links + public /collect/{token}).
from .collection_link_routes import router as collection_link_router

router.include_router(collection_link_router)

# Release-package routes (generate, list, retrieve, download, release, delete).
from .release_routes import router as release_router

router.include_router(release_router)


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


# AUTHENTICATED ENDPOINTS


# Create a new case
@router.post(
    "/", response_model=CaseDB, dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def create_case(
    request: Request, case: CaseCreate, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Create a new case with the given details."""
    from ..admin.config_routes import get_system_config

    case_id = str(uuid.uuid4())

    # Generate tracking number
    current_year = datetime.utcnow().year
    year_cases = await db.cases.count_documents(
        {"tracking_number": {"$regex": f"^FOI-{re_module.escape(str(current_year))}"}}
    )
    sequence = year_cases + 1
    tracking_number = generate_tracking_number(current_year, sequence)

    # Get system configuration for defaults
    config = await get_system_config()

    case_data = case.dict()

    # Apply default due date if not provided. Stored as a BSON Date
    # (raw datetime) — Mongo can then use date operators ($gt/$lte) and
    # date indexes against it. Pydantic models serialise it to ISO on
    # response.
    if not case_data.get("due_date"):
        from src.packs.loader import get_pack_timelines

        timelines = get_pack_timelines()
        default_due_days = timelines.get("default_response_days", 30)
        case_data["due_date"] = datetime.utcnow() + timedelta(days=default_due_days)

    # Apply default assignee if not provided and configured
    if not case_data.get("assignee") and config.get("default_assignee_id"):
        case_data["assignee"] = config.get("default_assignee_id")

    # Apply default priority if not provided
    if not case_data.get("priority"):
        case_data["priority"] = config.get("default_priority", "normal")

    # Initialize case team with assignee as analyst (or creator if no assignee)
    analyst_id = case_data.get("assignee") or current_user["id"]
    initial_team_member = {
        "user_id": analyst_id,
        "role": "analyst",
        "department": None,
        "permissions": get_permissions_for_role("analyst"),
        "added_at": datetime.utcnow(),
        "added_by": current_user["id"],
        "status": "active",
        "notes": "Assigned as case analyst" if case_data.get("assignee") else "Case creator",
    }

    now = datetime.utcnow()
    case_db = {
        "id": case_id,
        "tracking_number": tracking_number,
        **case_data,
        "created_by": current_user["id"],
        # created_at + updated_at written together — the public-portal
        # path sets both via received_date; the authenticated route used
        # to skip created_at, which surfaced as "1969-12-31" in the
        # public dashboard because JS's new Date(null) returns epoch.
        "created_at": now,
        "updated_at": now,
        "document_ids": [],
        "case_team": [initial_team_member],
    }

    # Insert the case into the database
    await db.cases.insert_one(case_db)

    # Get the inserted document and return it
    new_case = await db.cases.find_one({"id": case_id})
    return convert_mongo_doc_to_json(new_case)


# Get all cases (with pagination and filtering)
@router.get("/", dependencies=[Depends(check_role(["owner", "admin", "analyst", "user", "guest"]))])
async def list_cases(
    request: Request,
    skip: int = 0,
    limit: int = 20,
    status: CaseStatus = None,
    priority: CasePriority = None,
    assigned_to: str = None,
    created_by: str = None,
    current_user=Depends(get_current_user),
):
    """List cases with filtering options based on system role."""
    db = await get_db(request)
    query = {}
    if status:
        query["status"] = status
    if priority:
        query["priority"] = priority
    if assigned_to:
        query["assigned_user_ids"] = assigned_to
    if created_by:
        query["created_by"] = created_by

    # Access control based on system role
    user_system_role = current_user.get("role")

    if user_system_role == "admin":
        # Admin sees all cases
        pass
    elif user_system_role == "analyst":
        # Analyst sees all cases
        pass
    else:  # user or guest
        # Only see cases they're on the case team for
        query["case_team"] = {"$elemMatch": {"user_id": current_user["id"], "status": "active"}}

    # Execute the query with pagination
    cursor = db.cases.find(query).skip(skip).limit(limit).sort("created_at", -1)
    raw_result = await cursor.to_list(length=limit)

    # Convert MongoDB documents to JSON serializable format
    result = [convert_mongo_doc_to_json(doc) for doc in raw_result]

    # Get total count
    total = await db.cases.count_documents(query)

    return {"cases": result, "total": total, "skip": skip, "limit": limit}


# Get a specific case by ID
@router.get(
    "/{case_id}",
    response_model=CaseDB,
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def get_case(
    request: Request, case_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Get a case by its ID."""
    case = await db.cases.find_one({"id": case_id})

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check if user has permission to view this case
    user_role = current_user.get("role")
    is_team_member = is_case_team_member(case.get("case_team", []), current_user["id"])

    if (
        user_role not in ["owner", "admin", "manager"]
        and not is_team_member
        and current_user["id"] not in case.get("assigned_user_ids", [])
        and current_user["id"] != case.get("created_by")
        and current_user["id"] != case.get("privacy_officer_id")
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to view this case")

    return convert_mongo_doc_to_json(case)


# Update a case
@router.put(
    "/{case_id}",
    response_model=CaseDB,
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def update_case(
    request: Request,
    case_id: str,
    case_update: CaseUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Update a case with new information."""
    existing_case = await db.cases.find_one({"id": case_id})
    if not existing_case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check if user has permission to update this case
    user_role = current_user.get("role")
    if (
        user_role not in ["owner", "admin", "manager"]
        and current_user["id"] not in existing_case.get("assigned_user_ids", [])
        and current_user["id"] != existing_case.get("created_by")
        and current_user["id"] != existing_case.get("privacy_officer_id")
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to update this case")

    # Prepare update data, ignoring None values
    update_data = {k: v for k, v in case_update.dict(exclude_unset=True).items() if v is not None}
    if not update_data:
        return convert_mongo_doc_to_json(existing_case)  # No updates to apply

    # Add updated timestamp
    update_data["updated_at"] = datetime.utcnow()

    # Log changes to audit trail
    audit_entries = []
    for field, new_value in update_data.items():
        if field == "updated_at":
            continue
        old_value = existing_case.get(field)
        if old_value != new_value:
            audit_entries.append(
                {
                    "action": f"{field}_changed",
                    "user_id": current_user["id"],
                    "username": current_user.get("username", "Unknown"),
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "field": field,
                        "old_value": str(old_value) if old_value else None,
                        "new_value": str(new_value) if new_value else None,
                    },
                }
            )

    # Update the case
    update_operations = {"$set": update_data}
    if audit_entries:
        update_operations["$push"] = {"audit_log": {"$each": audit_entries}}

    await db.cases.update_one({"id": case_id}, update_operations)

    # Return the updated case
    updated_case = await db.cases.find_one({"id": case_id})
    return convert_mongo_doc_to_json(updated_case)


# Add documents to a case
@router.post(
    "/{case_id}/documents", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def add_documents_to_case(
    request: Request,
    case_id: str,
    document_ids: list = Body(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Add documents to a case."""
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check if user has permission to update this case
    user_role = current_user.get("role")
    if (
        user_role not in ["owner", "admin", "manager"]
        and current_user["id"] not in case.get("assigned_user_ids", [])
        and current_user["id"] != case.get("created_by")
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to update this case")

    # Validate document IDs
    for doc_id in document_ids:
        doc = await db.documents.find_one({"id": doc_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # Add documents to case
    existing_doc_ids = set(case.get("document_ids", []))
    new_doc_ids = list(
        set(document_ids) - existing_doc_ids
    )  # Only add documents that aren't already in the case

    if new_doc_ids:
        await db.cases.update_one(
            {"id": case_id}, {"$addToSet": {"document_ids": {"$each": new_doc_ids}}}
        )

    # Get updated case
    updated_case = await db.cases.find_one({"id": case_id})
    return convert_mongo_doc_to_json(updated_case)


# Remove documents from a case
@router.delete(
    "/{case_id}/documents", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def remove_documents_from_case(
    request: Request,
    case_id: str,
    document_ids: list = Body(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Remove documents from a case."""
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check if user has permission to update this case
    user_role = current_user.get("role")
    if (
        user_role not in ["owner", "admin", "manager"]
        and current_user["id"] not in case.get("assigned_user_ids", [])
        and current_user["id"] != case.get("created_by")
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to update this case")

    # Remove documents from case
    await db.cases.update_one({"id": case_id}, {"$pullAll": {"document_ids": document_ids}})

    # Get updated case
    updated_case = await db.cases.find_one({"id": case_id})
    return convert_mongo_doc_to_json(updated_case)


# Get documents in a case
@router.get(
    "/{case_id}/documents",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def get_case_documents(
    request: Request, case_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """
    Get all documents associated with a case.
    Returns documents that are attached to the case
    (but remain in the database for audit).
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check if user has permission
    user_role = current_user.get("role")
    if (
        user_role not in ["owner", "admin", "analyst"]
        and current_user["id"] not in case.get("assigned_user_ids", [])
        and current_user["id"] != case.get("created_by")
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to view this case")

    # Get documents
    document_ids = case.get("document_ids", [])
    if not document_ids:
        return {"documents": []}

    # Exclude binary content fields
    cursor = db.documents.find({"id": {"$in": document_ids}}, {"content": 0, "original_content": 0})
    docs = await cursor.to_list(length=100)

    # Group emails by thread so we only return the latest email per thread.
    emails_by_thread: dict = {}
    non_email_docs: list[dict] = []

    for doc in docs:
        mime_type = doc.get("mime_type")

        # Only apply thread-collapsing logic to email documents
        if mime_type in ["message/rfc822", "application/vnd.ms-outlook"]:
            thread_meta = doc.get("thread_metadata") or {}
            normalized_subject = (thread_meta.get("normalized_subject") or "").lower()
            from_addr = (thread_meta.get("from") or "").lower()
            to_addr = (thread_meta.get("to") or "").lower()

            # Fallback: if we have no thread metadata, treat this email as its own thread
            if not normalized_subject:
                thread_key = (doc.get("id"), "", "")
            else:
                thread_key = (normalized_subject, from_addr, to_addr)

            existing = emails_by_thread.get(thread_key)
            if not existing:
                emails_by_thread[thread_key] = doc
            else:
                # Prefer the email with the latest upload_date
                existing_date = existing.get("upload_date")
                current_date = doc.get("upload_date")
                if existing_date and current_date:
                    if current_date > existing_date:
                        emails_by_thread[thread_key] = doc
                elif current_date and not existing_date:
                    emails_by_thread[thread_key] = doc
                # If both dates are missing, keep the first one seen
        else:
            non_email_docs.append(doc)

    # Combine non-email docs with the canonical emails for each thread
    visible_docs = non_email_docs + list(emails_by_thread.values())

    return {"documents": [convert_mongo_doc_to_json(doc) for doc in visible_docs]}


# ASSIGNMENT ENDPOINTS


@router.put("/{case_id}/assign", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def assign_case(
    request: Request,
    case_id: str,
    assignee: str | None = Body(None),
    team: str | None = Body(None),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Assign a case to a user or team."""
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    update_data = {"updated_at": datetime.utcnow()}
    audit_details = {}

    if assignee is not None:
        update_data["assignee"] = assignee
        audit_details["assignee"] = assignee

        # Add to assigned_user_ids if not already there
        if assignee and assignee not in case.get("assigned_user_ids", []):
            await db.cases.update_one(
                {"id": case_id}, {"$addToSet": {"assigned_user_ids": assignee}}
            )

        # Add/update assignee as analyst in case_team
        if assignee:
            # Remove any existing analyst from the team
            await db.cases.update_one(
                {"id": case_id}, {"$pull": {"case_team": {"role": "analyst"}}}
            )

            # Add the new assignee as analyst
            from .permissions import get_permissions_for_role

            new_analyst = {
                "user_id": assignee,
                "role": "analyst",
                "department": None,
                "permissions": get_permissions_for_role("analyst"),
                "added_at": datetime.utcnow(),
                "added_by": current_user["id"],
                "status": "active",
                "notes": "Assigned as case analyst",
            }
            await db.cases.update_one({"id": case_id}, {"$push": {"case_team": new_analyst}})
        elif assignee == "":
            # If unassigning, remove analyst from team
            await db.cases.update_one(
                {"id": case_id}, {"$pull": {"case_team": {"role": "analyst"}}}
            )

    if team is not None:
        update_data["team"] = team
        audit_details["team"] = team

    # Add audit log entry
    audit_entry = {
        "action": "case_assigned",
        "user_id": current_user["id"],
        "username": current_user.get(
            "username", current_user.get("email", current_user.get("role", "Unknown User"))
        ),
        "timestamp": datetime.utcnow(),
        "details": audit_details,
    }

    await db.cases.update_one(
        {"id": case_id}, {"$set": update_data, "$push": {"audit_log": audit_entry}}
    )

    updated_case = await db.cases.find_one({"id": case_id})
    return convert_mongo_doc_to_json(updated_case)


@router.delete("/{case_id}", dependencies=[Depends(check_role(["owner", "admin"]))])
async def delete_case(
    request: Request, case_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Delete a case (admin only)."""
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Delete associated documents from database
    document_ids = case.get("document_ids", [])
    if document_ids:
        await db.documents.delete_many({"id": {"$in": document_ids}})

    # Delete the case
    result = await db.cases.delete_one({"id": case_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Case not found")

    return {
        "message": "Case deleted successfully",
        "case_id": case_id,
        "deleted_documents": len(document_ids),
    }


@router.put("/{case_id}/status", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def update_case_status(
    request: Request,
    case_id: str,
    status: CaseStatus = Body(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Update case status."""

    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role = current_user.get("role")
    if user_role not in ["owner", "admin", "manager"] and current_user["id"] not in case.get(
        "assigned_user_ids", []
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to update this case")

    old_status = case.get("status")

    # Add audit log entry
    audit_entry = {
        "action": "status_changed",
        "user_id": current_user["id"],
        "username": current_user.get(
            "username", current_user.get("email", current_user.get("role", "Unknown User"))
        ),
        "timestamp": datetime.utcnow(),
        "details": {"old_status": old_status, "new_status": status.value},
    }

    await db.cases.update_one(
        {"id": case_id},
        {
            "$set": {"status": status.value, "updated_at": datetime.utcnow()},
            "$push": {"audit_log": audit_entry},
        },
    )

    updated_case = await db.cases.find_one({"id": case_id})
    return convert_mongo_doc_to_json(updated_case)


@router.put("/{case_id}/priority", dependencies=[Depends(check_role(["owner", "admin"]))])
async def update_case_priority(
    request: Request,
    case_id: str,
    priority: CasePriority = Body(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Update case priority."""

    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    old_priority = case.get("priority")

    # Add audit log entry
    audit_entry = {
        "action": "priority_changed",
        "user_id": current_user["id"],
        "username": current_user.get(
            "username", current_user.get("email", current_user.get("role", "Unknown User"))
        ),
        "timestamp": datetime.utcnow(),
        "details": {"old_priority": old_priority, "new_priority": priority.value},
    }

    await db.cases.update_one(
        {"id": case_id},
        {
            "$set": {"priority": priority.value, "updated_at": datetime.utcnow()},
            "$push": {"audit_log": audit_entry},
        },
    )

    updated_case = await db.cases.find_one({"id": case_id})
    return convert_mongo_doc_to_json(updated_case)


# COMMENTS ENDPOINTS


@router.post(
    "/{case_id}/comments", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def add_comment(
    request: Request,
    case_id: str,
    comment_data: CommentCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Add a comment to a case."""

    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role = current_user.get("role")
    if user_role not in ["owner", "admin", "manager"] and current_user["id"] not in case.get(
        "assigned_user_ids", []
    ):
        raise HTTPException(
            status_code=403, detail="You don't have permission to comment on this case"
        )

    # Create comment
    comment = {
        "id": str(uuid.uuid4()),
        "author_id": current_user["id"],
        "author_name": current_user.get(
            "name", current_user.get("email", current_user.get("role", "Unknown User"))
        ),
        "text": comment_data.text,
        "type": comment_data.type.value,
        "created_at": datetime.utcnow(),
    }

    # Add audit log entry
    audit_entry = {
        "action": "comment_added",
        "user_id": current_user["id"],
        "username": current_user.get(
            "username", current_user.get("email", current_user.get("role", "Unknown User"))
        ),
        "timestamp": datetime.utcnow(),
        "details": {"comment_type": comment_data.type.value},
    }

    await db.cases.update_one(
        {"id": case_id},
        {
            "$push": {"comments": comment, "audit_log": audit_entry},
            "$set": {"updated_at": datetime.utcnow()},
        },
    )

    return {"success": True, "comment": comment}


@router.get(
    "/{case_id}/comments", dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))]
)
async def get_comments(
    request: Request,
    case_id: str,
    include_internal: bool = True,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Get comments for a case."""

    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check permission
    user_role = current_user.get("role")
    if (
        user_role not in ["owner", "admin", "manager"]
        and current_user["id"] not in case.get("assigned_user_ids", [])
        and current_user["id"] != case.get("created_by")
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to view this case")

    comments = case.get("comments", [])

    # Filter internal comments if user doesn't have permission
    if not include_internal or user_role == "reviewer":
        comments = [c for c in comments if c.get("type") == CommentType.PUBLIC.value]

    return {"comments": comments}


# RESPONSE LETTER GENERATION


@router.post("/{case_id}/generate-letter", dependencies=[Depends(check_role(["admin", "analyst"]))])
async def generate_letter(case_id: str):
    """501 stub. Response-letter generation is on the roadmap; see README."""
    raise HTTPException(
        status_code=501,
        detail="Response letter generation is not yet implemented.",
    )


# Sub-routers are mounted at the top of this file (after `router = APIRouter(...)`)
# so their routes register before the /{case_id} catch-all defined here. See the
# B12 fix note up top.
