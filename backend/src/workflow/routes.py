"""
Workflow routes — advanced workflow and queue management.

API endpoints for:
- Clock management (pause/resume statutory clock)
- Internal messaging
- Contributors (named record providers)
- Reminders
- Priority queue
"""

import logging
from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)

from src.core.database import get_database_from_request
from src.dependencies import get_current_user
from src.utils.email_service import EmailService

from .models import (
    BulkContributorCreate,
    # Contributors
    CaseContributor,
    # Queue
    CasePriorityScore,
    # Transfer
    CaseTransfer,
    # Clock
    ClockEvent,
    ClockEventCreate,
    ClockEventType,
    ClockStatus,
    ContributorCreate,
    ContributorUpdate,
    ContributorUploadInfo,
    QueueFilter,
    # Records confirmation
    RecordsConfirmation,
    RecordsConfirmationCreate,
    TransferCreate,
)
from .repository import (
    ClockEventsRepository,
    ContributorsRepository,
    QueueRepository,
    TransfersRepository,
)

# Initialize email service
email_service = EmailService()

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Workflow"])


# =============================================================================
# Helper: Get database
# =============================================================================


async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


# =============================================================================
# Clock Management Routes
# =============================================================================


@router.post("/cases/{case_id}/clock/pause", response_model=ClockEvent)
async def pause_clock(
    case_id: str,
    event_data: ClockEventCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Pause the statutory clock for a case.

    Reasons include:
    - fee_pending: Waiting for fee payment
    - scope_narrowing: Negotiating scope with requester
    - third_party_consultation: Consulting with third parties
    - privacy_commission_review: Under review by privacy commissioner
    - applicant_request: Requester asked for extension
    - manual: Other reason (specify in notes)
    """

    # Verify case exists
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check if already paused
    if case.get("clock_status") == "paused":
        raise HTTPException(status_code=400, detail="Clock is already paused")

    # Force event type to PAUSE
    event_data.event_type = ClockEventType.PAUSE

    if not event_data.reason:
        raise HTTPException(status_code=400, detail="Reason is required when pausing clock")

    repo = ClockEventsRepository(db)
    event = await repo.create(
        case_id=case_id,
        event_data=event_data,
        user_id=current_user["id"],
        user_name=current_user.get("name", current_user.get("email", "Unknown")),
    )

    # Add to case audit log
    audit_entry = {
        "action": "clock_paused",
        "user_id": current_user["id"],
        "username": current_user.get("name", current_user.get("email", "Unknown")),
        "timestamp": datetime.utcnow(),
        "details": {
            "reason": event_data.reason.value if event_data.reason else "manual",
            "notes": event_data.notes,
        },
    }
    await db.cases.update_one({"id": case_id}, {"$push": {"audit_log": audit_entry}})

    logger.info(
        f"Clock paused for case {case_id} by {current_user['id']}: {event_data.reason}",
        extra={"case_id": case_id, "user_id": current_user["id"]},
    )

    return event


@router.post("/cases/{case_id}/clock/resume", response_model=ClockEvent)
async def resume_clock(
    case_id: str,
    request: Request,
    notes: str | None = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Resume the statutory clock for a case.

    This will:
    - Calculate total paused days
    - Adjust the due date accordingly
    - Record the resume event
    """

    # Verify case exists
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Check if actually paused
    if case.get("clock_status") != "paused":
        raise HTTPException(status_code=400, detail="Clock is not paused")

    event_data = ClockEventCreate(event_type=ClockEventType.RESUME, notes=notes)

    repo = ClockEventsRepository(db)
    event = await repo.create(
        case_id=case_id,
        event_data=event_data,
        user_id=current_user["id"],
        user_name=current_user.get("name", current_user.get("email", "Unknown")),
    )

    # Add to case audit log
    audit_entry = {
        "action": "clock_resumed",
        "user_id": current_user["id"],
        "username": current_user.get("name", current_user.get("email", "Unknown")),
        "timestamp": datetime.utcnow(),
        "details": {"notes": notes, "total_paused_days": case.get("total_paused_days", 0)},
    }
    await db.cases.update_one({"id": case_id}, {"$push": {"audit_log": audit_entry}})

    logger.info(
        f"Clock resumed for case {case_id} by {current_user['id']}",
        extra={"case_id": case_id, "user_id": current_user["id"]},
    )

    return event


@router.get("/cases/{case_id}/clock/history", response_model=ClockStatus)
async def get_clock_history(
    case_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Get the clock status and event history for a case.

    Returns:
    - Current status (running/paused)
    - Original and adjusted due dates
    - Total paused days
    - Full event history
    """

    # Verify case exists
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    repo = ClockEventsRepository(db)
    return await repo.get_clock_status(case_id)


# =============================================================================
# Contributors Routes
# =============================================================================


@router.post("/cases/{case_id}/contributors", response_model=dict)
async def invite_contributor(
    case_id: str,
    contributor_data: ContributorCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Invite a named contributor to upload records for a case.

    Returns the contributor info and a magic link for uploading.
    The link expires after the specified number of days (default 14).
    """

    # Verify case exists
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    repo = ContributorsRepository(db)
    contributor, raw_token = await repo.create(
        case_id=case_id,
        contributor_data=contributor_data,
        user_id=current_user["id"],
        user_name=current_user.get("name", current_user.get("email", "Unknown")),
    )

    # Build upload URL
    upload_url = f"/contribute/{contributor.id}?token={raw_token}"

    logger.info(
        f"Contributor {contributor.email} invited to case {case_id}",
        extra={"case_id": case_id, "contributor_id": contributor.id},
    )

    # Send invitation email
    config = await db.system_config.find_one({})
    org_name = config.get("org_name", "BlackBar") if config else "BlackBar"
    base_url = str(request.base_url).rstrip("/")
    full_upload_url = f"{base_url}{upload_url}"

    email_service.send_contributor_invitation(
        to_email=contributor.email,
        contributor_name=contributor.name,
        upload_url=full_upload_url,
        case_tracking_number=case.get("tracking_number", case_id),
        org_name=org_name,
        expires_days=contributor_data.token_expiration_days or 14,
    )

    return {
        "contributor": contributor,
        "upload_url": upload_url,
        "expires_at": contributor.token_expires_at,
    }


@router.post("/cases/{case_id}/contributors/bulk", response_model=dict)
async def bulk_invite_contributors(
    case_id: str,
    bulk_data: BulkContributorCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Bulk invite multiple contributors to upload records for a case.

    Returns list of contributors with their magic links.
    """
    # Verify case exists
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    repo = ContributorsRepository(db)
    results = await repo.bulk_create(
        case_id=case_id,
        contributors_data=bulk_data.contributors,
        user_id=current_user["id"],
        user_name=current_user.get("name", current_user.get("email", "Unknown")),
    )

    # Send emails for each contributor
    config = await db.system_config.find_one({})
    org_name = config.get("org_name", "BlackBar") if config else "BlackBar"
    base_url = str(request.base_url).rstrip("/")
    tracking_number = case.get("tracking_number", case_id)

    invitations = []
    for contributor, raw_token in results:
        upload_url = f"/contribute/{contributor.id}?token={raw_token}"
        full_upload_url = f"{base_url}{upload_url}"

        # Send invitation email
        email_service.send_contributor_invitation(
            to_email=contributor.email,
            contributor_name=contributor.name,
            upload_url=full_upload_url,
            case_tracking_number=tracking_number,
            org_name=org_name,
            expires_days=14,
        )

        invitations.append(
            {
                "contributor": contributor,
                "upload_url": upload_url,
                "expires_at": contributor.token_expires_at,
            }
        )

    logger.info(
        f"Bulk invited {len(results)} contributors to case {case_id}",
        extra={"case_id": case_id, "count": len(results)},
    )

    return {"invitations": invitations, "count": len(invitations)}


@router.get("/cases/{case_id}/contributors", response_model=list[CaseContributor])
async def list_contributors(
    case_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    List all contributors invited to a case.
    """

    # Verify case exists
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    repo = ContributorsRepository(db)
    return await repo.get_by_case(case_id)


@router.put("/cases/{case_id}/contributors/{contributor_id}", response_model=CaseContributor)
async def update_contributor(
    case_id: str,
    contributor_id: str,
    update_data: ContributorUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Update a contributor's details or status.
    """

    repo = ContributorsRepository(db)
    contributor = await repo.update(contributor_id, update_data)

    if not contributor:
        raise HTTPException(status_code=404, detail="Contributor not found")

    return contributor


@router.post("/cases/{case_id}/contributors/{contributor_id}/remind")
async def remind_contributor(
    case_id: str,
    contributor_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Send a reminder to a contributor to upload their records.
    Generates a new token since we can't recover the original raw token from the hash.
    """
    import secrets

    from .repository import hash_token

    repo = ContributorsRepository(db)
    contributor = await repo.get_by_id(contributor_id)

    if not contributor:
        raise HTTPException(status_code=404, detail="Contributor not found")

    if contributor.status.value == "completed":
        raise HTTPException(
            status_code=400, detail="Contributor has already completed their upload"
        )

    if contributor.status.value == "expired":
        raise HTTPException(status_code=400, detail="Contributor invitation has expired")

    # Get case for tracking number
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Generate a new token for the reminder (we can't recover the
    # original raw token). Phase 4 Batch 4.4 (audit B44): the token
    # hash is only persisted AFTER the email send succeeds. The prior
    # implementation rotated the token and committed the new hash
    # BEFORE sending — if SendGrid was unreachable the contributor's
    # old link stopped working while no new email arrived.
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)

    # Build upload URL with the new raw token
    base_url = str(request.base_url).rstrip("/")
    upload_url = f"{base_url}/contribute/{contributor_id}?token={raw_token}"

    # Get org name from system config
    config = await db.system_config.find_one({})
    org_name = config.get("org_name", "BlackBar") if config else "BlackBar"

    # Calculate days until expiry
    expires_days = 30
    if contributor.token_expires_at:
        from datetime import datetime

        days_remaining = (contributor.token_expires_at - datetime.utcnow()).days
        expires_days = max(1, days_remaining)

    # Send reminder email
    email_sent = email_service.send_contributor_reminder(
        to_email=contributor.email,
        contributor_name=contributor.name,
        upload_url=upload_url,
        case_tracking_number=case.get("tracking_number", case_id),
        org_name=org_name,
        expires_days=expires_days,
    )

    if email_sent:
        # Only commit the token rotation after the email succeeds. If
        # the write itself fails the contributor keeps the old link
        # working — which is the more conservative failure mode.
        await db.case_contributors.update_one(
            {"id": contributor_id}, {"$set": {"upload_token": token_hash}}
        )
        logger.info(
            f"Reminder email sent to contributor {contributor.email} for case {case_id}",
            extra={"case_id": case_id, "contributor_id": contributor_id},
        )
        return {"success": True, "message": f"Reminder sent to {contributor.email}"}
    else:
        logger.warning(
            f"Failed to send reminder email to contributor {contributor.email} for case {case_id} "
            "— token NOT rotated; existing upload link remains valid",
            extra={"case_id": case_id, "contributor_id": contributor_id},
        )
        return {
            "success": False,
            "message": "Failed to send reminder email. Check email configuration.",
        }


@router.delete("/cases/{case_id}/contributors/{contributor_id}")
async def delete_contributor(
    case_id: str,
    contributor_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Delete a contributor invitation.
    """

    repo = ContributorsRepository(db)
    deleted = await repo.delete(contributor_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Contributor not found")

    return {"success": True, "message": "Contributor invitation deleted"}


# =============================================================================
# Public Contributor Portal Routes (No Auth Required - Token Based)
# =============================================================================


@router.get("/contribute/{contributor_id}", response_model=ContributorUploadInfo)
async def get_contributor_portal(contributor_id: str, token: str, request: Request):
    """
    Public endpoint for contributors to access their upload portal.

    Validates the token and returns contributor info with their uploaded documents.
    No authentication required - access is via secure token.
    """
    from src.core.database import get_database_from_request

    db = await get_database_from_request(request)

    repo = ContributorsRepository(db)
    contributor = await repo.verify_token(contributor_id, token)

    if not contributor:
        raise HTTPException(status_code=401, detail="Invalid or expired contribution link")

    # Update last access time
    await repo.update_last_access(contributor_id)

    # Get case info
    case = await db.cases.find_one({"id": contributor.case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Get documents uploaded by this contributor
    docs_cursor = db.documents.find(
        {"case_id": contributor.case_id, "uploaded_by_contributor": contributor_id}
    )
    uploaded_docs = []
    async for doc in docs_cursor:
        uploaded_docs.append(
            {
                "id": doc.get("id"),
                "filename": doc.get("original_filename") or doc.get("filename") or "Unknown",
                "uploaded_at": doc.get("uploaded_at")
                or doc.get("created_at")
                or doc.get("upload_date"),
                "status": doc.get("status"),
            }
        )

    # Get org name from system config
    config = await db.system_config.find_one({})
    org_name = config.get("org_name", "BlackBar") if config else "BlackBar"

    return ContributorUploadInfo(
        contributor_id=contributor.id,
        contributor_name=contributor.name,
        case_tracking_number=case.get("tracking_number", ""),
        case_title=case.get("title", ""),
        org_name=org_name,
        documents_uploaded=contributor.documents_uploaded,
        uploaded_documents=uploaded_docs,
        is_expired=False,
        expires_at=contributor.token_expires_at,
        records_confirmed=contributor.records_confirmed,
    )


@router.post("/contribute/{contributor_id}/upload")
async def contributor_upload_document(
    contributor_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    token: str = Form(...),
):
    """
    Public endpoint for contributors to upload documents.

    No authentication required - access is via secure token.
    Uses shared DocumentProcessingService for consistent handling.
    """
    from src.core.database import get_database_from_request
    from src.documents.processing_service import (
        DocumentProcessingService,
        ProcessingStatus,
        UploadContext,
    )

    db = await get_database_from_request(request)

    repo = ContributorsRepository(db)
    contributor = await repo.verify_token(contributor_id, token)

    if not contributor:
        raise HTTPException(status_code=401, detail="Invalid or expired contribution link")

    if contributor.records_confirmed:
        raise HTTPException(
            status_code=400,
            detail="You have already confirmed your records are complete. Contact the FOI coordinator to reopen.",
        )

    # Read file content
    content = await file.read()

    # Use shared processing service
    service = DocumentProcessingService(db)
    context = UploadContext(
        case_id=contributor.case_id,
        uploaded_by="contributor",
        uploaded_by_name=contributor.name,
        contributor_id=contributor_id,
        contributor_name=contributor.name,
        process_attachments=True,
        consolidate_email_threads=True,
    )

    result = await service.process_upload(
        file_content=content,
        filename=file.filename,
        content_type=file.content_type,
        context=context,
        background_tasks=background_tasks,
    )

    # Update contributor document count on successful upload
    if result.status == ProcessingStatus.SUCCESS:
        await repo.record_upload(contributor_id)
        logger.info(
            f"Contributor {contributor.email} uploaded document {file.filename}",
            extra={"contributor_id": contributor_id, "document_id": result.document_id},
        )

    # Return appropriate response
    if result.status == ProcessingStatus.DUPLICATE:
        return {
            "success": False,
            "message": result.message,
            "is_duplicate": True,
            "duplicate_of_id": result.duplicate_of_id,
            "duplicate_of_filename": result.duplicate_of_filename,
        }
    elif result.status in [ProcessingStatus.VALIDATION_FAILED, ProcessingStatus.ERROR]:
        raise HTTPException(status_code=400, detail=result.message)

    return {
        "success": True,
        "document_id": result.document_id,
        "filename": result.filename,
        "has_ocr": result.has_ocr,
        "has_ai_summary": result.has_ai_summary,
        "attachment_count": result.attachment_count,
    }


@router.post("/contribute/{contributor_id}/confirm-complete")
async def confirm_records_complete(contributor_id: str, token: str, request: Request):
    """
    Public endpoint for contributors to confirm they have submitted all records.

    No authentication required - access is via secure token.
    """
    db = await get_database_from_request(request)

    repo = ContributorsRepository(db)
    contributor = await repo.verify_token(contributor_id, token)

    if not contributor:
        raise HTTPException(status_code=401, detail="Invalid or expired contribution link")

    if contributor.records_confirmed:
        return {"success": True, "message": "Records already confirmed as complete"}

    updated = await repo.confirm_records_complete(contributor_id)

    logger.info(
        f"Contributor {contributor.email} confirmed records complete",
        extra={"contributor_id": contributor_id, "case_id": contributor.case_id},
    )

    return {
        "success": True,
        "message": "Thank you! Your records have been marked as complete.",
        "confirmed_at": updated.records_confirmed_at,
    }


# =============================================================================
# Priority Queue Routes
# =============================================================================


@router.get("/queue/prioritized", response_model=list[CasePriorityScore])
async def get_prioritized_queue(
    request: Request,
    analyst_id: str | None = None,
    workflow_stage: str | None = None,
    clock_status: str | None = None,
    include_closed: bool = False,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Get cases ordered by priority score.

    Priority is calculated based on:
    1. Due date (most important - overdue cases highest priority)
    2. Case age (older cases get slight boost)
    3. Document count (larger cases flagged for early start)

    Filter by analyst, workflow stage, or clock status.
    """

    filters = QueueFilter(
        analyst_id=analyst_id,
        workflow_stages=[workflow_stage] if workflow_stage else None,
        clock_status=clock_status,
        include_closed=include_closed,
        limit=min(limit, 200),
        offset=offset,
    )

    repo = QueueRepository(db)
    return await repo.get_prioritized_queue(filters)


@router.get("/queue/workload/{analyst_id}", response_model=list[CasePriorityScore])
async def get_analyst_workload(
    analyst_id: str,
    request: Request,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Get recommended workload for a specific analyst.

    Returns their assigned cases ordered by priority.
    """

    filters = QueueFilter(analyst_id=analyst_id, include_closed=False, limit=limit)

    repo = QueueRepository(db)
    return await repo.get_prioritized_queue(filters)


# NOTE: PUT /cases/{case_id}/priority is handled by cases/routes.py (not duplicated here)

# =============================================================================
# All Records Uploaded Confirmation
# =============================================================================


@router.post("/cases/{case_id}/records-confirmation", response_model=RecordsConfirmation)
async def confirm_all_records_uploaded(
    case_id: str,
    confirmation_data: RecordsConfirmationCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Confirm that all responsive records have been uploaded for a case.

    This notifies assigned analysts that the case is ready for review.
    """

    # Verify case exists
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    now = datetime.utcnow()
    user_name = current_user.get("name", current_user.get("email", "Unknown"))

    # Update case
    await db.cases.update_one(
        {"id": case_id},
        {
            "$set": {
                "all_records_uploaded": True,
                "all_records_confirmed_by": current_user["id"],
                "all_records_confirmed_by_name": user_name,
                "all_records_confirmed_at": now,
                "all_records_confirmation_notes": confirmation_data.notes,
                "updated_at": now,
            }
        },
    )

    # TODO(issue: TBD): Send notification to assigned analysts

    logger.info(
        f"All records confirmed for case {case_id} by {current_user['id']}",
        extra={"case_id": case_id, "user_id": current_user["id"]},
    )

    return RecordsConfirmation(
        confirmed=True,
        confirmed_by=current_user["id"],
        confirmed_by_name=user_name,
        confirmed_at=now,
        notes=confirmation_data.notes,
    )


@router.get("/cases/{case_id}/records-confirmation", response_model=RecordsConfirmation)
async def get_records_confirmation(
    case_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Get the records upload confirmation status for a case.
    """

    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    return RecordsConfirmation(
        confirmed=case.get("all_records_uploaded", False),
        confirmed_by=case.get("all_records_confirmed_by"),
        confirmed_by_name=case.get("all_records_confirmed_by_name"),
        confirmed_at=case.get("all_records_confirmed_at"),
        notes=case.get("all_records_confirmation_notes"),
    )


@router.delete("/cases/{case_id}/records-confirmation")
async def revoke_records_confirmation(
    case_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Revoke the records upload confirmation (e.g., if more records are found).
    """

    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    await db.cases.update_one(
        {"id": case_id},
        {
            "$set": {
                "all_records_uploaded": False,
                "all_records_confirmed_by": None,
                "all_records_confirmed_by_name": None,
                "all_records_confirmed_at": None,
                "all_records_confirmation_notes": None,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    logger.info(
        f"Records confirmation revoked for case {case_id} by {current_user['id']}",
        extra={"case_id": case_id, "user_id": current_user["id"]},
    )

    return {"success": True, "message": "Records confirmation revoked"}


# =============================================================================
# Request Transfer Routes
# =============================================================================


@router.post("/cases/{case_id}/transfer", response_model=dict)
async def transfer_case(
    case_id: str,
    transfer_data: TransferCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Transfer a request to another public body.

    Generates a secure link that the recipient can use to access:
    - Original request text and requester info
    - Optionally, all uploaded documents

    The link expires after 30 days.
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    repo = TransfersRepository(db)
    transfer, raw_token = await repo.create(
        case_id=case_id,
        tracking_number=case.get("tracking_number", ""),
        transfer_data=transfer_data,
        user_id=current_user["id"],
        user_name=current_user.get("name", current_user.get("email", "Unknown")),
    )

    # Build transfer URL
    transfer_url = f"/transfer/{transfer.id}?token={raw_token}"

    # Update case status to indicate transfer
    await db.cases.update_one(
        {"id": case_id},
        {
            "$set": {
                "workflow_stage": "transferred",
                "transferred_to": transfer_data.recipient_organization,
                "transferred_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        },
    )

    logger.info(f"Case {case_id} transferred to {transfer_data.recipient_organization}")

    # Send email to recipient with transfer link
    config = await db.system_config.find_one({})
    org_name = config.get("org_name", "BlackBar") if config else "BlackBar"
    base_url = str(request.base_url).rstrip("/")
    full_transfer_url = f"{base_url}{transfer_url}"

    email_service.send_transfer_notification(
        to_email=transfer_data.recipient_email,
        recipient_name=transfer_data.recipient_name,
        recipient_organization=transfer_data.recipient_organization,
        transfer_url=full_transfer_url,
        case_tracking_number=case.get("tracking_number", case_id),
        transfer_reason=transfer_data.transfer_reason,
        sender_organization=org_name,
        expires_days=30,
    )

    return {
        "transfer": transfer,
        "transfer_url": transfer_url,
        "expires_at": transfer.token_expires_at,
    }


@router.get("/cases/{case_id}/transfers", response_model=list[CaseTransfer])
async def list_transfers(
    case_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """List all transfers for a case."""
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    repo = TransfersRepository(db)
    return await repo.get_by_case(case_id)
