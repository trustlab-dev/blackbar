"""
Public FOI Request Routes (RFC-007)
Endpoints for authenticated public users to manage their FOI requests.

Also hosts the truly-anonymous public-portal endpoints (submit, track)
that were originally in cases/routes.py; consolidated here in Phase 1.5
(2026-05-11) since they share the /cases/public URL prefix.
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from src.auth.dependencies import get_current_user_public
from src.core.database import get_database_from_request, get_shared_database
from src.utils.log_utils import hash_email_for_logs

from . import release_package_service
from .models import (
    CasePriority,
    CaseStatus,
    CommentType,
    PublicRequestCreate,
)
from .release_package_models import ReleasePackageStatus
from .utils import calculate_due_date, generate_tracking_number, get_sla_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases/public", tags=["Public FOI Requests"])


def _iso(value):
    """Return a value as an ISO-8601 string regardless of whether it's a
    datetime, a date, or already a string. Cases/release packages mix the
    two depending on whether they were inserted by the API (which
    serialises some fields) or written directly (which leaves datetimes
    in place); both are seen in practice."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


# ANONYMOUS PUBLIC PORTAL ENDPOINTS (no auth — submit + track by tracking number)


@router.post("/submit")
async def submit_public_request(http_request: Request, request: PublicRequestCreate):
    """
    Public endpoint for FOI request submission.
    No authentication required.
    Returns tracking number for status checking.
    """
    # Get database from request context
    db = await get_db(http_request)

    case_id = str(uuid.uuid4())

    # Get current year's case count for tracking number
    current_year = datetime.utcnow().year
    year_cases = await db.cases.count_documents(
        {
            "created_at": {
                "$gte": datetime(current_year, 1, 1),
                "$lt": datetime(current_year + 1, 1, 1),
            }
        }
    )
    sequence = year_cases + 1

    # Generate tracking number
    tracking_number = generate_tracking_number(current_year, sequence)

    # Calculate due date (from pack configuration)
    received_date = datetime.utcnow()
    due_date = calculate_due_date(received_date)

    # Create case document
    case_data = {
        "id": case_id,
        "tracking_number": tracking_number,
        "title": request.title,
        "description": request.description,
        "category": request.category,
        "requester": request.requester.dict(),
        "status": CaseStatus.NEW.value,
        "priority": CasePriority.MEDIUM.value,
        "received_date": received_date,
        "created_at": received_date,
        "due_date": due_date,
        "extended_due_date": None,
        "assignee": None,
        "team": None,
        "assigned_user_ids": [],
        "privacy_officer_id": None,
        "tags": [],
        "comments": [],
        "audit_log": [
            {
                "action": "case_created",
                "user_id": "system",
                "username": "Public Portal",
                "timestamp": received_date,
                "details": {"source": "public_portal"},
            }
        ],
        "document_ids": [],
        "metadata": {},
        "workflow_stage": "intake",
        "estimated_completion": None,
        "updated_at": received_date,
        "created_by": "system",
    }

    # Insert into database
    await db.cases.insert_one(case_data)

    # Send confirmation email to requester
    try:
        from src.utils.email_service import EmailService
        from src.utils.welcome_email_service import WelcomeEmailService

        email_service = EmailService()
        welcome_service = WelcomeEmailService(email_service)

        # Get org name from system config
        org_name = "FOI Office"

        # Get contact email from system config
        sys_config = await db.system_config.find_one({"type": "system"})
        contact_email = sys_config.get("contact_email") if sys_config else None

        welcome_service.send_public_request_confirmation(
            requester_email=request.requester.email,
            requester_name=request.requester.name,
            tracking_number=tracking_number,
            request_title=request.title,
            org_name=org_name,
            contact_email=contact_email,
        )
        logger.info(f"Confirmation email sent for {tracking_number}")
    except Exception as e:
        # Don't fail case creation if email fails
        logger.error(f"Failed to send confirmation email for {tracking_number}: {e}")

    return {
        "success": True,
        "tracking_number": tracking_number,
        "case_id": case_id,
        "message": f"Your FOI request has been received. Use tracking number {tracking_number} to check status.",
        "due_date": due_date.isoformat(),
    }


@router.get("/track/{tracking_number}")
async def track_public_request(http_request: Request, tracking_number: str):
    """
    Public endpoint to track FOI request status.
    No authentication required.
    Returns public information only (no internal comments).
    """
    db = await get_db(http_request)
    case = await db.cases.find_one({"tracking_number": tracking_number})

    if not case:
        raise HTTPException(status_code=404, detail="Tracking number not found")

    # Filter to public comments only
    public_comments = [
        comment
        for comment in case.get("comments", [])
        if comment.get("type") == CommentType.PUBLIC.value
    ]

    # Calculate SLA status
    sla_status = get_sla_status(case["due_date"]) if case.get("due_date") else "unknown"

    return {
        "tracking_number": tracking_number,
        "title": case["title"],
        "status": case["status"],
        "received_date": case["received_date"],
        "due_date": case.get("due_date"),
        "sla_status": sla_status,
        "comments": public_comments,
        "last_updated": case["updated_at"],
    }


# AUTHENTICATED PUBLIC USER ENDPOINTS (magic-link JWT required)


@router.get("/my-requests")
async def get_my_requests(
    request: Request,
    current_user: dict = Depends(get_current_user_public),
    db=Depends(get_database_from_request),
):
    """
    Get all FOI requests for the authenticated public user

    Returns list of requests with status, tracking number, and basic info
    Requires: JWT token from magic link authentication
    """
    try:
        user_email = current_user["email"]

        # Filter by requester email
        cases_cursor = db.cases.find({"requester.email": user_email}).sort(
            "created_at", -1
        )  # Most recent first

        cases = await cases_cursor.to_list(length=100)  # Limit to 100 requests

        # Format response. Use the app-level UUID (case["id"]) rather
        # than the Mongo ObjectId — the detail endpoint and frontend
        # routes expect the UUID, and exposing _id leaks implementation
        # detail without buying anything.
        formatted_cases = []
        for case in cases:
            formatted_cases.append(
                {
                    "id": case.get("id"),
                    "tracking_number": case.get("tracking_number"),
                    "title": case.get("title"),
                    "description": case.get("description"),
                    "status": case.get("status"),
                    "created_at": _iso(case.get("created_at")),
                    "updated_at": _iso(case.get("updated_at")),
                    "requester": {
                        "name": case.get("requester", {}).get("name"),
                        "email": case.get("requester", {}).get("email"),
                    },
                }
            )

        email_hash = hash_email_for_logs(user_email)
        logger.info(f"Retrieved {len(formatted_cases)} requests for {email_hash}")

        return {"requests": formatted_cases, "total": len(formatted_cases)}

    except Exception as e:
        logger.error(f"Failed to get user requests: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve requests")


@router.get("/health")
async def health_check():
    """Health check for public FOI endpoints.

    Declared BEFORE /{request_id} (B18 fix, 2026-05-12). FastAPI matches
    routes in registration order; if /{request_id} were registered
    first, requests to /health would be caught by the catch-all and
    require auth — making the health endpoint unreachable.
    """
    return {"status": "healthy", "service": "public_foi_requests"}


@router.get("/{request_id}")
async def get_request_details(
    request_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_public),
    db=Depends(get_database_from_request),
):
    """
    Get detailed information about a specific FOI request

    Includes:
    - Full request details
    - Status timeline
    - Documents (if any)
    - Messages/comments

    Requires: JWT token and user must own the request
    """
    try:
        user_email = current_user["email"]

        # Lookup by the app-level UUID stored in `id` (not the Mongo
        # ObjectId). Matches the rest of the codebase and what the
        # frontend routes pass through.
        # SECURITY: filter by case id AND requester email so a public
        # user can't see another requester's case even with a valid id.
        case = await db.cases.find_one({"id": request_id, "requester.email": user_email})

        if not case:
            raise HTTPException(
                status_code=404, detail="Request not found or you don't have access"
            )

        case_id = case.get("id")

        # Get documents for this case
        documents_cursor = db.documents.find({"case_id": case_id})
        documents = await documents_cursor.to_list(length=None)

        # Get audit log from case document (stored inline)
        # Filter to only show status changes and key events - not internal activity
        audit_logs = case.get("audit_log", [])

        # Events that are appropriate for public view
        public_events = {
            "case_created",
            "status_changed",
            "case_completed",
            "case_closed",
            "extension_requested",
            "extension_granted",
            "release_package_released",
        }

        # Build timeline from audit log - filtered for public view
        timeline = []
        for log in audit_logs:
            action = log.get("action")
            if action in public_events:
                timeline.append(
                    {
                        "event": action,
                        "timestamp": _iso(log.get("timestamp")),
                        "details": log.get("details"),
                    }
                )

        # Get released packages for this case
        release_packages = []
        packages_cursor = db.release_packages.find({"case_id": case_id, "status": "released"})
        async for pkg in packages_cursor:
            # Only include if not expired. `expires_at` may be a datetime
            # OR an ISO string depending on how the package was written;
            # parse the string form for the comparison.
            expires_at = pkg.get("expires_at")
            expires_at_dt = expires_at
            if isinstance(expires_at, str):
                try:
                    expires_at_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                except ValueError:
                    expires_at_dt = None
            if expires_at_dt and expires_at_dt < datetime.utcnow():
                continue
            # Check download limit
            if pkg.get("max_downloads") and pkg.get("download_count", 0) >= pkg.get(
                "max_downloads"
            ):
                continue
            release_packages.append(
                {
                    "id": pkg.get("id"),
                    "filename": pkg.get("filename"),
                    "size_bytes": pkg.get("size_bytes"),
                    "document_count": pkg.get("document_count"),
                    "download_count": pkg.get("download_count", 0),
                    "max_downloads": pkg.get("max_downloads"),
                    "expires_at": _iso(expires_at),
                    "access_token": pkg.get("access_token"),
                    "released_at": _iso(pkg.get("released_at")),
                }
            )

        # Format response. Use the app-level UUID, not the Mongo _id.
        response = {
            "id": case.get("id"),
            "tracking_number": case.get("tracking_number"),
            "title": case.get("title"),
            "description": case.get("description"),
            "status": case.get("status"),
            "category": case.get("category"),
            "created_at": _iso(case.get("created_at")),
            "updated_at": _iso(case.get("updated_at")),
            "due_date": _iso(case.get("due_date")),
            "requester": {
                "name": case.get("requester", {}).get("name"),
                "email": case.get("requester", {}).get("email"),
                "phone": case.get("requester", {}).get("phone"),
                "organization": case.get("requester", {}).get("organization"),
            },
            "timeline": timeline,
            "documents": [
                {
                    "id": doc.get("id"),
                    "filename": doc.get("filename"),
                    "file_type": doc.get("file_type"),
                    "file_size": doc.get("file_size"),
                    "uploaded_at": _iso(doc.get("created_at") or doc.get("upload_date")),
                    "status": doc.get("status"),
                }
                for doc in documents
            ],
            "document_count": len(documents),
            "release_packages": release_packages,
            "release_status": "available" if release_packages else None,
        }

        email_hash = hash_email_for_logs(user_email)
        logger.info(f"Retrieved request details for {request_id} by {email_hash}")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get request details: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve request details")


@router.get("/stats/summary")
async def get_request_summary(
    request: Request,
    current_user: dict = Depends(get_current_user_public),
    db=Depends(get_database_from_request),
):
    """
    Get summary statistics for user's requests

    Returns counts by status: open, in_progress, completed, closed
    """
    try:
        user_email = current_user["email"]

        # Filter by requester email
        pipeline = [
            {"$match": {"requester.email": user_email}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]

        results = await db.cases.aggregate(pipeline).to_list(length=None)

        # Format response
        summary = {"open": 0, "in_progress": 0, "completed": 0, "closed": 0, "total": 0}

        for result in results:
            status = result["_id"]
            count = result["count"]
            if status in summary:
                summary[status] = count
            summary["total"] += count

        email_hash = hash_email_for_logs(user_email)
        logger.info(f"Retrieved summary for {email_hash}")

        return summary

    except Exception as e:
        logger.error(f"Failed to get request summary: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve summary")


# /health is declared above /{request_id} (B18 fix). See note up there.


# PUBLIC RELEASE PACKAGE DOWNLOAD (Token-based, no auth required)


@router.get("/release/{access_token}")
async def download_release_package(access_token: str, request: Request):
    """
    Download a release package using secure access token.

    This endpoint uses token-based authentication (no login required).
    The token is:
    - Cryptographically secure (32+ bytes)
    - Time-limited (configurable expiration)
    - Download-limited (configurable max downloads)
    - Only shared with requester via email
    """
    # Find the package by token in the database
    db = get_shared_database()
    package = await release_package_service.get_release_package_by_token(access_token, db)

    if not package:
        raise HTTPException(status_code=404, detail="Release package not found")

    # Check status
    if package.status == ReleasePackageStatus.REVOKED:
        raise HTTPException(status_code=410, detail="This release package has been revoked")

    if package.status == ReleasePackageStatus.EXPIRED:
        raise HTTPException(status_code=410, detail="This release package has expired")

    if package.status != ReleasePackageStatus.RELEASED:
        raise HTTPException(status_code=400, detail="Release package is not available for download")

    # Check expiration
    if package.expires_at and datetime.utcnow() > package.expires_at:
        # Update status to expired
        await db.release_packages.update_one(
            {"id": package.id}, {"$set": {"status": ReleasePackageStatus.EXPIRED.value}}
        )
        raise HTTPException(status_code=410, detail="This release package has expired")

    # Check download limit
    if package.max_downloads and package.download_count >= package.max_downloads:
        raise HTTPException(
            status_code=410, detail="Download limit reached for this release package"
        )

    try:
        # Get client info for audit
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # Download and record (uses public download which checks released status)
        content, filename = await release_package_service.download_public_package(
            package, db, ip_address=ip_address, user_agent=user_agent
        )

        logger.info(f"Release package {package.id} downloaded via public endpoint")

        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(content)),
            },
        )

    except ValueError as e:
        raise HTTPException(status_code=410, detail=str(e))
    except Exception as e:
        logger.error(f"Error downloading release package: {e}")
        raise HTTPException(status_code=500, detail="Failed to download release package")
