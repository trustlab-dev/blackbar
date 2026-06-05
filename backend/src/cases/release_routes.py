"""
Release-package routes — generate, list, retrieve, download, release,
and delete per-case release packages.

Split from cases/routes.py in Phase 1.5 (2026-05-11). Mounted via
include_router in cases/routes.py.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response

from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user
from . import release_package_service
from .release_package_models import (
    CurrentPackageState,
    GenerateResponse,
    ReleasePackageGenerate,
    ReleasePackageRelease,
    ReleasePackageResponse,
    ReleasePackageStatus,
    ReleaseResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


def _build_package_response(package, case_id: str) -> ReleasePackageResponse:
    """Build a ReleasePackageResponse from a package."""
    # Only include public URLs if released
    download_url = None
    public_url = None
    if package.status == ReleasePackageStatus.RELEASED:
        download_url = f"/api/v1/cases/public/release/{package.access_token}"
        public_url = download_url  # Relative URL — frontend constructs full URL

    return ReleasePackageResponse(
        id=package.id,
        case_id=case_id,
        status=package.status,
        filename=package.filename,
        size_bytes=package.size_bytes,
        document_count=package.document_count,
        total_redactions=package.total_redactions,
        included_documents=package.included_documents,
        generation_progress=package.generation_progress,
        generation_message=package.generation_message,
        download_url=download_url,
        public_url=public_url,
        expires_at=package.expires_at,
        download_count=package.download_count,
        max_downloads=package.max_downloads,
        created_at=package.created_at,
        created_by_name=package.created_by_name,
        released_at=package.released_at,
        released_by_name=package.released_by_name,
    )


@router.post(
    "/{case_id}/release-package/generate",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def generate_release_package_endpoint(
    request: Request,
    case_id: str,
    background_tasks: BackgroundTasks,
    package_request: ReleasePackageGenerate = None,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Step 1: Start generating a release package in the background.

    Creates a draft package with redacted documents. The package will be
    available for review once generation completes (status changes to 'draft').

    Poll GET /release-packages to check generation progress.
    """
    # Default request if not provided
    if package_request is None:
        package_request = ReleasePackageGenerate(include_cover_letter=True)

    try:
        # Start generation - creates record with GENERATING status
        package_id, replaced_draft_id = await release_package_service.start_package_generation(
            case_id=case_id,
            created_by=current_user.get("id", "unknown"),
            created_by_name=current_user.get("username", current_user.get("email", "Unknown")),
            request=package_request,
            release_settings={},
            db=db,
        )

        # Run actual generation in background
        background_tasks.add_task(
            release_package_service.process_package_generation,
            package_id,
            case_id,
            db,
            package_request,
            {},
        )

        # Log in audit trail
        audit_entry = {
            "action": "release_package_generation_started",
            "user_id": current_user.get("id", "unknown"),
            "username": current_user.get("username", "unknown"),
            "timestamp": datetime.utcnow(),
            "details": {"package_id": package_id, "replaced_draft_id": replaced_draft_id},
        }

        await db.cases.update_one({"id": case_id}, {"$push": {"audit_log": audit_entry}})

        return GenerateResponse(
            package_id=package_id,
            status=ReleasePackageStatus.GENERATING,
            message="Release package generation started",
            replaced_draft_id=replaced_draft_id,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting release package generation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start package generation: {str(e)}")


@router.get(
    "/{case_id}/release-packages", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def get_release_packages_state(
    request: Request, case_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """
    Get current release package state for a case.

    Returns the current draft (if any) and current release (if any).
    Use this to poll for generation progress.
    """
    current_draft, current_release = await release_package_service.get_current_package_state(
        case_id, db
    )

    return CurrentPackageState(
        current_draft=_build_package_response(current_draft, case_id) if current_draft else None,
        current_release=(
            _build_package_response(current_release, case_id) if current_release else None
        ),
    )


@router.get(
    "/{case_id}/release-package/{package_id}",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def get_release_package_endpoint(
    request: Request,
    case_id: str,
    package_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Get details of a specific release package."""
    package = await release_package_service.get_release_package(package_id, db)

    if not package or package.case_id != case_id:
        raise HTTPException(status_code=404, detail="Release package not found")

    return _build_package_response(package, case_id)


@router.get(
    "/{case_id}/release-package/{package_id}/download",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def download_draft_package_endpoint(
    request: Request,
    case_id: str,
    package_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Step 2: Download draft package for analyst review.

    Downloads the generated ZIP file so the analyst can review
    the redacted documents before releasing to the requester.
    """
    package = await release_package_service.get_release_package(package_id, db)

    if not package or package.case_id != case_id:
        raise HTTPException(status_code=404, detail="Release package not found")

    if package.status == ReleasePackageStatus.GENERATING:
        raise HTTPException(status_code=400, detail="Package is still generating")
    elif package.status not in [ReleasePackageStatus.DRAFT, ReleasePackageStatus.RELEASED]:
        raise HTTPException(
            status_code=400, detail=f"Package cannot be downloaded (status: {package.status})"
        )

    try:
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # Download package (works for both draft and released - analyst review)
        content, filename = await release_package_service.download_draft_package(
            package,
            db,
            downloaded_by=current_user.get("id", "unknown"),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(content)),
            },
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error downloading draft package: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to download package")


@router.post(
    "/{case_id}/release-package/{package_id}/release",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def release_package_endpoint(
    request: Request,
    case_id: str,
    package_id: str,
    release_request: ReleasePackageRelease = None,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Step 3: Release package to public portal.

    Publishes the draft package, making it available for the requester
    to download via the public portal. Optionally sends notification email.
    """
    package = await release_package_service.get_release_package(package_id, db)

    if not package or package.case_id != case_id:
        raise HTTPException(status_code=404, detail="Release package not found")

    # Default request if not provided
    if release_request is None:
        release_request = ReleasePackageRelease(notify_requester=True)

    try:
        released_package = await release_package_service.release_package(
            package_id=package_id,
            db=db,
            released_by=current_user.get("id", "unknown"),
            released_by_name=current_user.get("username", current_user.get("email", "Unknown")),
            request=release_request,
            release_settings={},
        )

        # Log in audit trail
        audit_entry = {
            "action": "release_package_released",
            "user_id": current_user.get("id", "unknown"),
            "username": current_user.get("username", "unknown"),
            "timestamp": datetime.utcnow(),
            "details": {
                "package_id": package_id,
                "expires_at": (
                    released_package.expires_at.isoformat() if released_package.expires_at else None
                ),
                "max_downloads": released_package.max_downloads,
                "requester_notified": released_package.requester_notified,
            },
        }

        await db.cases.update_one({"id": case_id}, {"$push": {"audit_log": audit_entry}})

        public_url = f"/api/v1/cases/public/release/{released_package.access_token}"

        return ReleaseResponse(
            id=released_package.id,
            status=released_package.status,
            public_url=public_url,
            expires_at=released_package.expires_at,
            requester_notified=released_package.requester_notified,
            message="Package released to public portal"
            + (" and requester notified" if released_package.requester_notified else ""),
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error releasing package: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to release package: {str(e)}")


@router.delete(
    "/{case_id}/release-package/{package_id}",
    dependencies=[Depends(check_role(["owner", "admin"]))],
)
async def revoke_release_package_endpoint(
    request: Request,
    case_id: str,
    package_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Revoke a release package, preventing further downloads."""
    package = await release_package_service.get_release_package(package_id, db)

    if not package or package.case_id != case_id:
        raise HTTPException(status_code=404, detail="Release package not found")

    success = await release_package_service.revoke_release_package(
        package_id, db, current_user.get("id", "unknown")
    )

    if success:
        # Log in audit trail
        audit_entry = {
            "action": "release_package_revoked",
            "user_id": current_user.get("id", "unknown"),
            "username": current_user.get("username", "unknown"),
            "timestamp": datetime.utcnow(),
            "details": {"package_id": package_id},
        }

        await db.cases.update_one({"id": case_id}, {"$push": {"audit_log": audit_entry}})

        return {"message": "Release package revoked", "status": "revoked"}

    raise HTTPException(status_code=500, detail="Failed to revoke release package")
