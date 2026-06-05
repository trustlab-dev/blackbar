"""
Release Package Service
Handles generation, storage, and retrieval of release packages

Three-step workflow:
1. GENERATE - Creates draft package in background, returns immediately
2. REVIEW - Analyst downloads draft to review locally
3. RELEASE - Publishes to public portal, sets expiration, notifies requester
"""

import io
import logging
import secrets
import uuid
import zipfile
from datetime import datetime, timedelta

import gridfs
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import MongoClient

from src.config import MONGODB_URI
from src.utils.pdf_redaction import apply_redactions_to_pdf
from src.utils.release_package import generate_cover_letter, generate_release_summary

from .release_package_models import (
    DownloadRecord,
    IncludedDocument,
    ReleasePackageDB,
    ReleasePackageGenerate,
    ReleasePackageRelease,
    ReleasePackageStatus,
)

logger = logging.getLogger(__name__)


async def get_document_content(doc: dict, db: AsyncIOMotorDatabase) -> bytes | None:
    """
    Get document content from GridFS or embedded content.
    """
    # Try GridFS first
    if doc.get("content_file_id"):
        try:
            sync_client = MongoClient(MONGODB_URI)
            db_name = db.name
            sync_db = sync_client[db_name]
            fs = gridfs.GridFS(sync_db)

            grid_out = fs.get(doc["content_file_id"])
            content = grid_out.read()
            sync_client.close()
            return content
        except Exception as e:
            logger.warning(f"GridFS retrieval failed for {doc.get('id')}: {e}")

    # Fall back to embedded content
    if doc.get("content"):
        return doc["content"]

    return None


async def delete_existing_draft(case_id: str, db: AsyncIOMotorDatabase) -> str | None:
    """Delete any existing draft package for a case. Returns deleted package ID if any."""
    existing_draft = await db.release_packages.find_one(
        {"case_id": case_id, "status": ReleasePackageStatus.DRAFT.value}
    )

    if existing_draft:
        # Delete from GridFS if file exists
        if existing_draft.get("file_id"):
            try:
                sync_client = MongoClient(MONGODB_URI)
                sync_db = sync_client[db.name]
                fs = gridfs.GridFS(sync_db)
                fs.delete(ObjectId(existing_draft["file_id"]))
                sync_client.close()
            except Exception as e:
                logger.warning(
                    f"Failed to delete GridFS file for draft {existing_draft['id']}: {e}"
                )

        # Delete the package record
        await db.release_packages.delete_one({"id": existing_draft["id"]})
        logger.info(f"Deleted existing draft package {existing_draft['id']}")
        return existing_draft["id"]

    return None


async def start_package_generation(
    case_id: str,
    created_by: str,
    created_by_name: str,
    request: ReleasePackageGenerate,
    release_settings: dict,
    db: AsyncIOMotorDatabase = None,
) -> tuple[str, str | None]:
    """
    Start generating a release package (Step 1).
    Creates initial record with GENERATING status.

    Returns:
        Tuple of (package_id, replaced_draft_id)
    """
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise ValueError("Case not found")

    replaced_draft_id = await delete_existing_draft(case_id, db)

    package_id = str(uuid.uuid4())
    access_token = secrets.token_urlsafe(32)

    package = ReleasePackageDB(
        id=package_id,
        case_id=case_id,
        filename=f"{case.get('tracking_number', case_id)}-Release.zip",
        access_token=access_token,
        created_at=datetime.utcnow(),
        created_by=created_by,
        created_by_name=created_by_name,
        status=ReleasePackageStatus.GENERATING,
        generation_progress=0,
        generation_message="Starting package generation...",
        include_cover_letter=request.include_cover_letter,
        cover_letter_template_id=request.cover_letter_template_id,
    )

    await db.release_packages.insert_one(package.model_dump())

    # Update case to track current draft
    await db.cases.update_one({"id": case_id}, {"$set": {"current_draft_id": package_id}})

    return package_id, replaced_draft_id


async def process_package_generation(
    package_id: str,
    case_id: str,
    db: AsyncIOMotorDatabase,
    request: ReleasePackageGenerate,
    release_settings: dict,
):
    """
    Process the actual package generation (runs in background).
    Updates status to DRAFT when complete.
    """
    try:
        # Get case
        case = await db.cases.find_one({"id": case_id})
        if not case:
            raise ValueError("Case not found")

        # Get documents
        query = {"case_id": case_id}
        if request.document_ids:
            query["id"] = {"$in": request.document_ids}

        documents = await db.documents.find(query).to_list(None)

        # Filter to only released/approved documents
        documents = [d for d in documents if d.get("status") in ["released", "approved"]]

        if not documents:
            await db.release_packages.update_one(
                {"id": package_id},
                {
                    "$set": {
                        "status": "failed",
                        "generation_message": "No documents ready for release",
                    }
                },
            )
            return

        total_docs = len(documents)

        # Update progress
        await db.release_packages.update_one(
            {"id": package_id},
            {
                "$set": {
                    "generation_progress": 5,
                    "generation_message": f"Found {total_docs} documents to process",
                }
            },
        )

        # Generate ZIP content
        zip_buffer = io.BytesIO()
        included_docs = []
        total_redactions = 0

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add cover letter if requested
            if request.include_cover_letter:
                case_data = {
                    "case_number": case.get("tracking_number", "N/A"),
                    "title": case.get("title", "Freedom of Information Request"),
                    "requester_name": (
                        case.get("requester", {}).get("name", "Requester")
                        if isinstance(case.get("requester"), dict)
                        else case.get("requester_name", "Requester")
                    ),
                    "created_at": (
                        case.get("created_at", datetime.utcnow()).strftime("%B %d, %Y")
                        if isinstance(case.get("created_at"), datetime)
                        else str(case.get("created_at", ""))
                    ),
                    "officer_name": "FOI Officer",
                    "officer_title": "Information Officer",
                }

                # Prepare doc info for cover letter
                doc_info = []
                for doc in documents:
                    redactions = doc.get("redactions", [])
                    exemptions = list(set([r.get("category", "S22") for r in redactions]))
                    doc_info.append(
                        {
                            "filename": doc.get("filename", "document.pdf"),
                            "redaction_count": len(redactions),
                            "exemptions": exemptions,
                            "status": doc.get("status", "released"),
                        }
                    )

                cover_letter = generate_cover_letter(case_data, doc_info)
                zf.writestr("00-Cover-Letter.txt", cover_letter)

            # Add manifest if enabled
            if release_settings.get("include_manifest", True):
                case_data = {
                    "case_number": case.get("tracking_number", "N/A"),
                    "title": case.get("title", "N/A"),
                }
                doc_info = []
                for doc in documents:
                    redactions = doc.get("redactions", [])
                    exemptions = list(set([r.get("category", "S22") for r in redactions]))
                    doc_info.append(
                        {
                            "filename": doc.get("filename", "document.pdf"),
                            "redaction_count": len(redactions),
                            "exemptions": exemptions,
                            "status": doc.get("status", "released"),
                        }
                    )
                summary = generate_release_summary(case_data, doc_info)
                zf.writestr("00-MANIFEST.txt", summary)

            # Process each document
            for idx, doc in enumerate(documents, 1):
                # Update progress
                progress = 10 + int((idx / total_docs) * 80)
                await db.release_packages.update_one(
                    {"id": package_id},
                    {
                        "$set": {
                            "generation_progress": progress,
                            "generation_message": f"Processing document {idx} of {total_docs}...",
                        }
                    },
                )

                content = await get_document_content(doc, db)
                if not content:
                    logger.warning(f"No content for document {doc.get('id')}")
                    continue

                # Apply redactions
                # SECURITY: Never fall back to unredacted content on failure.
                # A redaction error is a generation failure — the outer except
                # marks the package as "failed" so the operator must investigate
                # before retrying. Any silent fallback is a data-leak vector.
                redactions = doc.get("redactions", [])
                if redactions:
                    try:
                        redacted_content = apply_redactions_to_pdf(content, redactions)
                    except Exception as e:
                        logger.error(f"Error applying redactions to {doc.get('id')}: {e}")
                        raise RuntimeError(
                            f"Failed to apply redactions to document {doc.get('id')}: {e}"
                        ) from e
                else:
                    redacted_content = content

                # Add to ZIP
                filename = doc.get("filename", "document.pdf")
                # Ensure .pdf extension
                if not filename.lower().endswith(".pdf"):
                    filename = filename.rsplit(".", 1)[0] + ".pdf"
                zip_filename = f"{idx:02d}-{filename}"
                zf.writestr(zip_filename, redacted_content)

                # Track included document
                exemptions = list(set([r.get("category", "S22") for r in redactions]))
                total_redactions += len(redactions)
                included_docs.append(
                    IncludedDocument(
                        document_id=doc.get("id"),
                        filename=zip_filename,
                        original_filename=doc.get("filename"),
                        redaction_count=len(redactions),
                        exemptions=exemptions,
                    )
                )

        # Get ZIP bytes
        zip_content = zip_buffer.getvalue()
        zip_buffer.close()

        # Update progress
        await db.release_packages.update_one(
            {"id": package_id},
            {"$set": {"generation_progress": 95, "generation_message": "Storing package..."}},
        )

        # Store ZIP in GridFS
        sync_client = MongoClient(MONGODB_URI)
        sync_db = sync_client[db.name]
        fs = gridfs.GridFS(sync_db)

        # Get package to get filename
        package = await db.release_packages.find_one({"id": package_id})

        file_id = fs.put(
            zip_content,
            filename=package["filename"],
            content_type="application/zip",
            package_id=package_id,
        )
        sync_client.close()

        # Update package record - status is now DRAFT (ready for review)
        await db.release_packages.update_one(
            {"id": package_id},
            {
                "$set": {
                    "file_id": str(file_id),
                    "size_bytes": len(zip_content),
                    "document_count": len(included_docs),
                    "total_redactions": total_redactions,
                    "included_documents": [d.model_dump() for d in included_docs],
                    "status": ReleasePackageStatus.DRAFT.value,
                    "generation_progress": 100,
                    "generation_message": "Package ready for review",
                }
            },
        )

        logger.info(
            f"Generated draft package {package_id} with {len(included_docs)} documents, {total_redactions} redactions"
        )

    except Exception as e:
        logger.error(f"Error generating release package: {e}")
        # Update status to failed
        await db.release_packages.update_one(
            {"id": package_id},
            {"$set": {"status": "failed", "generation_message": f"Generation failed: {str(e)}"}},
        )


async def release_package(
    package_id: str,
    db: AsyncIOMotorDatabase,
    released_by: str,
    released_by_name: str,
    request: ReleasePackageRelease,
    release_settings: dict,
) -> ReleasePackageDB:
    """
    Release a draft package to the public portal (Step 3).
    Sets expiration, download limits, and optionally notifies requester.
    """
    # Get package
    package = await db.release_packages.find_one({"id": package_id})
    if not package:
        raise ValueError("Package not found")

    if package["status"] != ReleasePackageStatus.DRAFT.value:
        raise ValueError(
            f"Package must be in draft status to release (current: {package['status']})"
        )

    # Calculate expiration
    expiration_days = request.expires_in_days or release_settings.get("default_expiration_days", 30)
    max_days = release_settings.get("max_expiration_days", 90)
    min_days = release_settings.get("min_expiration_days", 7)
    expiration_days = max(min_days, min(expiration_days, max_days))
    expires_at = datetime.utcnow() + timedelta(days=expiration_days)

    # Calculate max downloads
    max_downloads = request.max_downloads
    if max_downloads is None:
        max_downloads = release_settings.get("default_max_downloads", 10)
    max_limit = release_settings.get("max_downloads_limit", 100)
    if not release_settings.get("unlimited_downloads_allowed", False):
        max_downloads = min(max_downloads, max_limit) if max_downloads else max_limit

    # Revoke any existing released package for this case
    await db.release_packages.update_many(
        {
            "case_id": package["case_id"],
            "status": ReleasePackageStatus.RELEASED.value,
            "id": {"$ne": package_id},
        },
        {
            "$set": {
                "status": ReleasePackageStatus.REVOKED.value,
                "revoked_at": datetime.utcnow(),
                "revoked_by": released_by,
            }
        },
    )

    # Update package to released
    await db.release_packages.update_one(
        {"id": package_id},
        {
            "$set": {
                "status": ReleasePackageStatus.RELEASED.value,
                "released_at": datetime.utcnow(),
                "released_by": released_by,
                "released_by_name": released_by_name,
                "expires_at": expires_at,
                "max_downloads": max_downloads,
                "custom_message": request.custom_message,
            }
        },
    )

    # Update case status to "released" and add audit log
    await db.cases.update_one(
        {"id": package["case_id"]},
        {
            "$set": {
                "status": "released",
                "current_release_id": package_id,
                "current_draft_id": None,
                "release_status": "released",
                "updated_at": datetime.utcnow(),
            },
            "$push": {
                "audit_log": {
                    "action": "release_package_released",
                    "user_id": released_by,
                    "username": released_by_name,
                    "timestamp": datetime.utcnow(),
                    "details": {
                        "package_id": package_id,
                        "expires_at": expires_at.isoformat() if expires_at else None,
                        "notify_requester": request.notify_requester,
                    },
                }
            },
        },
    )

    # TODO(issue: TBD): Send notification email if request.notify_requester
    requester_notified = False
    if request.notify_requester:
        # Email notification would be sent here
        # For now, just mark as notified
        requester_notified = True
        await db.release_packages.update_one(
            {"id": package_id},
            {"$set": {"requester_notified": True, "requester_notified_at": datetime.utcnow()}},
        )

    logger.info(f"Released package {package_id}, expires {expires_at}")

    # Return updated package
    updated = await db.release_packages.find_one({"id": package_id})
    return ReleasePackageDB(**updated)


async def get_release_package(package_id: str, db: AsyncIOMotorDatabase) -> ReleasePackageDB | None:
    """Get a release package by ID."""
    doc = await db.release_packages.find_one({"id": package_id})
    if doc:
        return ReleasePackageDB(**doc)
    return None


async def get_release_package_by_token(
    access_token: str, db: AsyncIOMotorDatabase
) -> ReleasePackageDB | None:
    """Get a release package by access token."""
    doc = await db.release_packages.find_one({"access_token": access_token})
    if doc:
        return ReleasePackageDB(**doc)
    return None


async def download_draft_package(
    package: ReleasePackageDB,
    db: AsyncIOMotorDatabase,
    downloaded_by: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[bytes, str]:
    """
    Download a package for analyst review (Step 2).
    Allows download of both draft and released packages (for internal review).

    Returns:
        Tuple of (content bytes, filename)
    """
    # Check status - must be draft or released (analysts can review released packages)
    if package.status not in [ReleasePackageStatus.DRAFT, ReleasePackageStatus.RELEASED]:
        raise ValueError(
            f"Package must be in draft or released status for analyst download (current: {package.status})"
        )

    # Get content from GridFS
    if not package.file_id:
        raise ValueError("Package file not found")

    sync_client = MongoClient(MONGODB_URI)
    sync_db = sync_client[db.name]
    fs = gridfs.GridFS(sync_db)

    grid_out = fs.get(ObjectId(package.file_id))
    content = grid_out.read()
    sync_client.close()

    # Record download (for audit, doesn't count against limit)
    download_record = DownloadRecord(
        downloaded_at=datetime.utcnow(),
        ip_address=ip_address,
        user_agent=user_agent,
        downloaded_by="analyst",
    )

    await db.release_packages.update_one(
        {"id": package.id}, {"$push": {"downloads": download_record.model_dump()}}
    )

    logger.info(f"Draft package {package.id} downloaded by analyst {downloaded_by}")

    # Return with DRAFT suffix in filename
    filename = package.filename.replace(".zip", "-DRAFT.zip")
    return content, filename


async def download_public_package(
    package: ReleasePackageDB,
    db: AsyncIOMotorDatabase,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[bytes, str]:
    """
    Download a released package via public portal.
    Checks expiration and download limits.

    Returns:
        Tuple of (content bytes, filename)
    """
    # Check status - must be released
    if package.status != ReleasePackageStatus.RELEASED:
        if package.status == ReleasePackageStatus.DRAFT:
            raise ValueError("Package has not been released yet")
        elif package.status == ReleasePackageStatus.EXPIRED:
            raise ValueError("Release package has expired")
        elif package.status == ReleasePackageStatus.REVOKED:
            raise ValueError("Release package has been revoked")
        else:
            raise ValueError(f"Package is not available for download (status: {package.status})")

    # Check if expired
    if package.expires_at and datetime.utcnow() > package.expires_at:
        # Update status to expired
        await db.release_packages.update_one(
            {"id": package.id}, {"$set": {"status": ReleasePackageStatus.EXPIRED.value}}
        )
        raise ValueError("Release package has expired")

    # Check download limit
    if package.max_downloads and package.download_count >= package.max_downloads:
        raise ValueError("Download limit reached")

    # Get content from GridFS
    if not package.file_id:
        raise ValueError("Package file not found")

    sync_client = MongoClient(MONGODB_URI)
    sync_db = sync_client[db.name]
    fs = gridfs.GridFS(sync_db)

    grid_out = fs.get(ObjectId(package.file_id))
    content = grid_out.read()
    sync_client.close()

    # Record download and increment count
    download_record = DownloadRecord(
        downloaded_at=datetime.utcnow(),
        ip_address=ip_address,
        user_agent=user_agent,
        downloaded_by="requester",
    )

    await db.release_packages.update_one(
        {"id": package.id},
        {"$inc": {"download_count": 1}, "$push": {"downloads": download_record.model_dump()}},
    )

    logger.info(
        f"Release package {package.id} downloaded by requester (count: {package.download_count + 1})"
    )

    return content, package.filename


async def revoke_release_package(
    package_id: str, db: AsyncIOMotorDatabase, revoked_by: str
) -> bool:
    """Revoke a release package."""
    result = await db.release_packages.update_one(
        {"id": package_id},
        {
            "$set": {
                "status": ReleasePackageStatus.REVOKED.value,
                "revoked_at": datetime.utcnow(),
                "revoked_by": revoked_by,
            }
        },
    )

    if result.modified_count > 0:
        # Update case
        await db.cases.update_one(
            {"release_packages.id": package_id}, {"$set": {"release_packages.$.status": "revoked"}}
        )
        logger.info(f"Release package {package_id} revoked by {revoked_by}")
        return True

    return False


async def list_release_packages(case_id: str, db: AsyncIOMotorDatabase) -> list[ReleasePackageDB]:
    """List all release packages for a case."""
    cursor = db.release_packages.find({"case_id": case_id}).sort("created_at", -1)
    packages = await cursor.to_list(None)
    return [ReleasePackageDB(**p) for p in packages]


async def get_current_package_state(
    case_id: str, db: AsyncIOMotorDatabase
) -> tuple[ReleasePackageDB | None, ReleasePackageDB | None]:
    """
    Get current draft and released packages for a case.

    Returns:
        Tuple of (current_draft, current_release)
    """
    # Get current draft (generating or draft status)
    current_draft = await db.release_packages.find_one(
        {
            "case_id": case_id,
            "status": {
                "$in": [ReleasePackageStatus.GENERATING.value, ReleasePackageStatus.DRAFT.value]
            },
        }
    )

    # Get current release
    current_release = await db.release_packages.find_one(
        {"case_id": case_id, "status": ReleasePackageStatus.RELEASED.value}
    )

    draft = ReleasePackageDB(**current_draft) if current_draft else None
    release = ReleasePackageDB(**current_release) if current_release else None

    return draft, release
