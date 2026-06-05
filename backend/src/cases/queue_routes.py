"""
Case queue, search, dashboard, and deadline routes.

Split from cases/routes.py in Phase 1.5 (2026-05-11) to keep individual
route modules tractable. Mounted via include_router in cases/routes.py.
"""

import re as re_module
from datetime import datetime
from typing import Any

from bson.objectid import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user
from ..utils.deadline_tracker import (
    DeadlineStatus,
    SLAType,
    calculate_sla_deadline,
    generate_deadline_summary,
    request_extension,
)
from ..utils.search_engine import (
    format_search_results,
    rank_results,
    search_cases,
    search_documents,
)
from .models import CasePriority, CaseStatus
from .utils import get_sla_status

router = APIRouter()


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


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


@router.get(
    "/deadline-dashboard", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def get_deadline_dashboard(
    request: Request, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """
    Get dashboard view of all case deadlines.
    Accessible to owners, admins, and analysts.

    Returns:
        Summary statistics and list of cases requiring attention
    """
    all_cases = await db.cases.find({"status": {"$nin": ["closed", "cancelled"]}}).to_list(None)

    # Calculate deadline info for each case
    cases_with_deadlines = []

    for case in all_cases:
        created_at = case.get("created_at", datetime.utcnow())
        if not isinstance(created_at, datetime):
            created_at = datetime.utcnow()

        sla_type = case.get("sla_type", SLAType.STANDARD.value)
        extensions = case.get("extensions", [])

        deadline_info = calculate_sla_deadline(
            request_date=created_at,
            sla_type=SLAType(sla_type),
            extensions=[ext.get("days", 0) for ext in extensions],
        )

        cases_with_deadlines.append(
            {
                "id": case.get("id"),
                "case_number": case.get("case_number"),
                "title": case.get("title"),
                "status": case.get("status"),
                "deadline_info": deadline_info,
            }
        )

    # Generate summary
    summary = generate_deadline_summary(cases_with_deadlines)

    # Get cases requiring attention
    attention_cases = [
        c for c in cases_with_deadlines if c["deadline_info"].get("requires_attention", False)
    ]

    # Sort by urgency
    attention_cases.sort(
        key=lambda x: (
            x["deadline_info"]["status"] == DeadlineStatus.OVERDUE.value,
            x["deadline_info"]["status"] == DeadlineStatus.URGENT.value,
            x["deadline_info"]["days_remaining"],
        ),
        reverse=True,
    )

    return {
        "summary": summary,
        "attention_required": attention_cases,
        "all_cases": cases_with_deadlines,
    }


# SEARCH (must come before /{case_id} route)
@router.get("/search", dependencies=[Depends(check_role(["admin", "analyst", "user"]))])
async def search_all(
    q: str,
    search_type: str = "all",  # all, documents, cases
    limit: int = 50,
    current_user=Depends(get_current_user),
):
    """
    Search across documents and db.cases.

    Args:
        q: Search query
        search_type: Type of search (all, documents, cases)
        limit: Maximum results per type
    """
    results = {}

    # Search documents
    if search_type in ["all", "documents"]:
        doc_results = search_documents(q, limit=limit)
        results["documents"] = doc_results.get("results", [])
        results["documents_total"] = doc_results.get("total", 0)

    # Search cases
    if search_type in ["all", "cases"]:
        case_results = search_cases(q, limit=limit)
        results["cases"] = case_results.get("results", [])
        results["cases_total"] = case_results.get("total", 0)

    return results


@router.get(
    "/queue/my-cases", dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))]
)
async def get_my_cases(
    request: Request,
    skip: int = 0,
    limit: int = 50,
    status: CaseStatus | None = None,
    priority: CasePriority | None = None,
    sort_by: str = "due_date",
    sort_order: str = "asc",
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Get cases assigned to current user (cases where user is on case_team)."""
    query = {
        "$or": [
            {"assignee": current_user["id"]},
            {"assigned_user_ids": current_user["id"]},
            {"case_team.user_id": current_user["id"]},
        ]
    }

    if status:
        query["status"] = status.value
    if priority:
        query["priority"] = priority.value

    # Build sort direction (1 for asc, -1 for desc)
    sort_direction = 1 if sort_order == "asc" else -1

    cursor = db.cases.find(query).skip(skip).limit(limit).sort(sort_by, sort_direction)
    result = await cursor.to_list(length=limit)
    total = await db.cases.count_documents(query)

    # Populate assignee names
    from ..database import users

    for case in result:
        if case.get("assignee"):
            user = await users.find_one({"id": case["assignee"]})
            if user:
                case["assignee"] = (
                    user.get("full_name") or user.get("username") or user.get("email")
                )

    return {
        "cases": [convert_mongo_doc_to_json(doc) for doc in result],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/queue/all", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def get_all_cases_queue(
    request: Request,
    skip: int = 0,
    limit: int = 50,
    status: CaseStatus | None = None,
    priority: CasePriority | None = None,
    assignee: str | None = None,
    team: str | None = None,
    tags: str | None = None,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Get all cases with advanced filtering (owner/admin/analyst)."""
    query = {}

    if status:
        query["status"] = status.value
    if priority:
        query["priority"] = priority.value
    if assignee:
        query["assignee"] = assignee
    if team:
        query["team"] = team
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        query["tags"] = {"$in": tag_list}
    if search:
        escaped_search = re_module.escape(search)
        query["$or"] = [
            {"title": {"$regex": escaped_search, "$options": "i"}},
            {"description": {"$regex": escaped_search, "$options": "i"}},
            {"tracking_number": {"$regex": escaped_search, "$options": "i"}},
        ]

    # Build sort direction (1 for asc, -1 for desc)
    sort_direction = 1 if sort_order == "asc" else -1

    cursor = db.cases.find(query).skip(skip).limit(limit).sort(sort_by, sort_direction)
    result = await cursor.to_list(length=limit)
    total = await db.cases.count_documents(query)

    # Populate assignee names and add SLA status
    from ..database import users

    cases_with_sla = []
    for case in result:
        # Populate assignee name
        if case.get("assignee"):
            user = await users.find_one({"id": case["assignee"]})
            if user:
                case["assignee"] = (
                    user.get("full_name") or user.get("username") or user.get("email")
                )

        case_dict = convert_mongo_doc_to_json(case)
        if case.get("due_date"):
            case_dict["sla_status"] = get_sla_status(case["due_date"])
        cases_with_sla.append(case_dict)

    return {"cases": cases_with_sla, "total": total, "skip": skip, "limit": limit}


@router.get("/stats/dashboard", dependencies=[Depends(check_role(["owner", "admin"]))])
async def get_dashboard_stats(
    request: Request, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Get dashboard statistics."""
    total_cases = await db.cases.count_documents({})

    # Count by status
    status_counts = {}
    for status in CaseStatus:
        count = await db.cases.count_documents({"status": status.value})
        status_counts[status.value] = count

    # Count by priority
    priority_counts = {}
    for priority in CasePriority:
        count = await db.cases.count_documents({"priority": priority.value})
        priority_counts[priority.value] = count

    # Count overdue cases
    overdue_count = await db.cases.count_documents(
        {
            "due_date": {"$lt": datetime.utcnow()},
            "status": {"$nin": [CaseStatus.COMPLETED.value, CaseStatus.CLOSED.value]},
        }
    )

    # Count unassigned cases
    unassigned_count = await db.cases.count_documents(
        {"assignee": None, "status": {"$ne": CaseStatus.CLOSED.value}}
    )

    return {
        "total_cases": total_cases,
        "status_counts": status_counts,
        "priority_counts": priority_counts,
        "overdue_count": overdue_count,
        "unassigned_count": unassigned_count,
    }


@router.get(
    "/{case_id}/deadline-info",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def get_case_deadline_info(
    request: Request, case_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """
    Get detailed deadline information for a case.

    Returns:
        Deadline status, days remaining, SLA compliance info
    """
    # Find case
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Get or calculate deadline info
    created_at = case.get("created_at", datetime.utcnow())
    if not isinstance(created_at, datetime):
        created_at = datetime.utcnow()

    sla_type = case.get("sla_type", SLAType.STANDARD.value)
    extensions = case.get("extensions", [])

    deadline_info = calculate_sla_deadline(
        request_date=created_at,
        sla_type=SLAType(sla_type),
        extensions=[ext.get("days", 0) for ext in extensions],
    )

    # Update case with latest deadline info
    await db.cases.update_one({"id": case_id}, {"$set": {"deadline_info": deadline_info}})

    return deadline_info


@router.post(
    "/{case_id}/request-extension",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def request_deadline_extension(
    request: Request,
    case_id: str,
    extension_days: int = Body(...),
    reason: str = Body(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Request an extension to a case deadline.

    Args:
        extension_days: Number of business days to extend
        reason: Reason for extension request
    """
    # Find case
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Get current deadline
    deadline_info = case.get("deadline_info", {})
    current_deadline = deadline_info.get("deadline")

    if not current_deadline:
        # Calculate if not exists
        created_at = case.get("created_at", datetime.utcnow())
        sla_type = case.get("sla_type", SLAType.STANDARD.value)
        deadline_info = calculate_sla_deadline(created_at, SLAType(sla_type))
        current_deadline = deadline_info["deadline"]

    # Create extension request
    extension = request_extension(
        current_deadline=(
            current_deadline if isinstance(current_deadline, datetime) else datetime.utcnow()
        ),
        extension_days=extension_days,
        reason=reason,
    )

    extension["requested_by"] = current_user.get("username", "unknown")
    extension["status"] = "approved"  # Auto-approve for now

    # Add to case extensions
    await db.cases.update_one(
        {"id": case_id},
        {"$push": {"extensions": extension}, "$set": {"sla_type": SLAType.EXTENDED.value}},
    )

    # Recalculate deadline
    created_at = case.get("created_at", datetime.utcnow())
    extensions = case.get("extensions", []) + [extension]

    new_deadline_info = calculate_sla_deadline(
        request_date=created_at if isinstance(created_at, datetime) else datetime.utcnow(),
        sla_type=SLAType.EXTENDED,
        extensions=[ext.get("extension_days", 0) for ext in extensions],
    )

    await db.cases.update_one({"id": case_id}, {"$set": {"deadline_info": new_deadline_info}})

    # Log in audit trail
    audit_entry = {
        "action": "extension_requested",
        "user_id": current_user.get("id", "unknown"),
        "username": current_user.get("username", "unknown"),
        "timestamp": datetime.utcnow(),
        "details": {
            "extension_days": extension_days,
            "reason": reason,
            "new_deadline": new_deadline_info["deadline"],
        },
    }

    await db.cases.update_one({"id": case_id}, {"$push": {"audit_log": audit_entry}})

    return {"success": True, "extension": extension, "new_deadline_info": new_deadline_info}


@router.get(
    "/{case_id}/search-documents",
    dependencies=[Depends(check_role(["owner", "admin", "analyst", "user"]))],
)
async def search_case_documents(
    request: Request,
    case_id: str,
    q: str,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Search documents within a specific case.

    Args:
        q: Search query
        limit: Maximum results
    """
    if not q or len(q) < 2:
        raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")

    # Verify case exists
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Search documents in this case
    doc_query = search_documents(q, {"case_id": case_id}, limit)
    doc_results = await db.documents.find(doc_query["query"]).limit(limit).to_list(None)

    # Rank and format results
    doc_results = rank_results(doc_results, q)
    formatted_results = format_search_results(doc_results, q, include_highlights=True)

    return {
        "query": q,
        "case_id": case_id,
        "case_number": case.get("case_number"),
        "results": formatted_results,
        "total_results": len(formatted_results),
    }


@router.get("/search/advanced", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def advanced_search(
    request: Request,
    q: str,
    document_status: str | None = None,
    case_status: str | None = None,
    submitter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Advanced search with filters.

    Args:
        q: Search query
        document_status: Filter by document status
        case_status: Filter by case status
        submitter: Filter by submitter name/email
        date_from: Start date (YYYY-MM-DD)
        date_to: End date (YYYY-MM-DD)
        limit: Maximum results
    """
    if not q or len(q) < 2:
        raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")

    # Build filters
    doc_filters = {}
    case_filters = {}

    if document_status:
        doc_filters["status"] = document_status

    if case_status:
        case_filters["status"] = case_status

    if submitter:
        escaped_submitter = re_module.escape(submitter)
        doc_filters["$or"] = [
            {"submitter_name": {"$regex": escaped_submitter, "$options": "i"}},
            {"submitter_email": {"$regex": escaped_submitter, "$options": "i"}},
        ]

    if date_from or date_to:
        date_filter = {}
        if date_from:
            date_filter["$gte"] = datetime.fromisoformat(date_from)
        if date_to:
            date_filter["$lte"] = datetime.fromisoformat(date_to)
        doc_filters["uploaded_at"] = date_filter
        case_filters["created_at"] = date_filter

    # Search documents
    doc_query = search_documents(q, doc_filters, limit)
    doc_results = await db.documents.find(doc_query["query"]).limit(limit).to_list(None)
    doc_results = rank_results(doc_results, q)

    # Search cases
    case_query = search_cases(q, case_filters, limit)
    case_results = await db.cases.find(case_query["query"]).limit(limit).to_list(None)
    case_results = rank_results(case_results, q)

    return {
        "query": q,
        "filters": {
            "document_status": document_status,
            "case_status": case_status,
            "submitter": submitter,
            "date_from": date_from,
            "date_to": date_to,
        },
        "documents": format_search_results(doc_results, q, include_highlights=True),
        "cases": format_search_results(case_results, q, include_highlights=False),
        "total_results": len(doc_results) + len(case_results),
    }
