"""
Collection-link routes — generate per-case upload links and accept
contributor uploads via shareable tokens.

Split from cases/routes.py in Phase 1.5 (2026-05-11). Mounted via
include_router in cases/routes.py.
"""

import uuid
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

from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user
from .collection_link_service import (
    CollectionLinkCreate,
    generate_collection_token,
    is_link_valid,
)

router = APIRouter()


# Helper to get database from request
async def get_db(request: Request):
    """Get database from request"""
    return await get_database_from_request(request)


# DOCUMENT COLLECTION LINKS


@router.post(
    "/{case_id}/collection-links", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def create_collection_link(
    request: Request,
    case_id: str,
    link_data: CollectionLinkCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Create a document collection link for a case"""

    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Generate secure token
    token = generate_collection_token()
    link_id = str(uuid.uuid4())

    # Create link document
    link = {
        "id": link_id,
        "case_id": case_id,
        "token": token,
        "created_by": current_user["id"],
        "created_at": datetime.utcnow(),
        "expires_at": link_data.expires_at,
        "max_uploads": link_data.max_uploads,
        "upload_count": 0,
        "is_active": True,
        "notes": link_data.notes,
    }

    # Store in case document
    await db.cases.update_one({"id": case_id}, {"$push": {"collection_links": link}})

    # Return link with full URL
    return {**link, "url": f"/collect/{token}"}


@router.get(
    "/{case_id}/collection-links", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))]
)
async def get_collection_links(
    request: Request, case_id: str, current_user=Depends(get_current_user), db=Depends(get_db)
):
    """Get all collection links for a case"""

    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    links = case.get("collection_links", [])

    # Add full URLs
    for link in links:
        link["url"] = f"/collect/{link['token']}"

    return {"links": links}


@router.delete(
    "/{case_id}/collection-links/{link_id}",
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def deactivate_collection_link(
    request: Request,
    case_id: str,
    link_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Deactivate a collection link"""
    result = await db.cases.update_one(
        {"id": case_id, "collection_links.id": link_id},
        {"$set": {"collection_links.$.is_active": False}},
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Collection link not found")

    return {"success": True, "message": "Collection link deactivated"}


# PUBLIC COLLECTION ENDPOINT


@router.get("/collect/{token}")
async def get_collection_info(http_request: Request, token: str):
    """Get information about a collection link (public, no auth)"""
    db = await get_db(http_request)
    # Find case with this token
    case = await db.cases.find_one({"collection_links.token": token})
    if not case:
        raise HTTPException(status_code=404, detail="Collection link not found")

    # Find the specific link
    link = next((l for l in case.get("collection_links", []) if l["token"] == token), None)
    if not link:
        raise HTTPException(status_code=404, detail="Collection link not found")

    # Check if link is valid
    is_valid, error_msg = is_link_valid(link)
    if not is_valid:
        raise HTTPException(status_code=403, detail=error_msg)

    # Return safe information
    return {
        "case_title": case.get("title"),
        "case_tracking_number": case.get("tracking_number"),
        "upload_count": link.get("upload_count", 0),
        "max_uploads": link.get("max_uploads"),
        "expires_at": link.get("expires_at"),
    }


@router.post("/collect/{token}/upload")
async def upload_to_collection(
    http_request: Request,
    token: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    submitter_name: str = Form(...),
    submitter_email: str = Form(...),
    notes: str | None = Form(None),
):
    """
    Upload a document via collection link (public, no auth).

    Uses shared DocumentProcessingService for consistent handling.
    """
    from src.documents.processing_service import (
        DocumentProcessingService,
        ProcessingStatus,
        UploadContext,
    )

    db = await get_db(http_request)

    # Find case with this token
    case = await db.cases.find_one({"collection_links.token": token})
    if not case:
        raise HTTPException(status_code=404, detail="Collection link not found")

    # Find the specific link
    link_index = next(
        (i for i, l in enumerate(case.get("collection_links", [])) if l["token"] == token), None
    )
    if link_index is None:
        raise HTTPException(status_code=404, detail="Collection link not found")

    link = case["collection_links"][link_index]

    # Check if link is valid
    is_valid, error_msg = is_link_valid(link)
    if not is_valid:
        raise HTTPException(status_code=403, detail=error_msg)

    # Read file content
    content = await file.read()

    # Use shared processing service
    service = DocumentProcessingService(db)
    context = UploadContext(
        case_id=case["id"],
        uploaded_by="collection_link",
        uploaded_by_name=f"{submitter_name} ({submitter_email})",
        collection_link_id=link["id"],
        submitter_name=submitter_name,
        submitter_email=submitter_email,
        submitter_notes=notes,
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

    # Handle result
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

    # Increment upload count on success
    await db.cases.update_one(
        {"id": case["id"]}, {"$inc": {f"collection_links.{link_index}.upload_count": 1}}
    )

    # Add audit log
    audit_entry = {
        "action": "document_uploaded_via_collection_link",
        "user_id": "public",
        "username": f"{submitter_name} ({submitter_email})",
        "timestamp": datetime.utcnow(),
        "details": {
            "document_id": result.document_id,
            "filename": file.filename,
            "size": len(content),
            "collection_link_id": link["id"],
            "conversion_status": result.conversion_status,
            "has_ai_summary": result.has_ai_summary,
            "has_ocr_data": result.has_ocr,
            "attachment_count": result.attachment_count,
        },
    }

    await db.cases.update_one({"id": case["id"]}, {"$push": {"audit_log": audit_entry}})

    return {
        "success": True,
        "document_id": result.document_id,
        "filename": result.filename,
        "message": "Document uploaded successfully",
        "has_ocr": result.has_ocr,
        "has_ai_summary": result.has_ai_summary,
        "attachment_count": result.attachment_count,
    }
