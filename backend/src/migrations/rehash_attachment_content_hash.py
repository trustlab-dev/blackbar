"""
Migration: re-hash email attachment documents on their original bytes (issue #70)

Before the fix, `DocumentProcessingService._process_attachments` stored
`content_hash = sha256(converted PDF)` for attachments, while direct uploads
stored `sha256(original bytes)`, so duplicate detection never matched the
two. This recomputes `content_hash` for attachment documents from the
original file kept in GridFS (`original_file_id`).

Attachments with no `original_file_id` are left alone: that covers PDF
attachments (never converted, so the stored hash already is the original's)
and records whose GridFS write failed at upload time (no original to hash).

Idempotent: records whose hash already matches are not rewritten.
"""

import asyncio
import hashlib

from gridfs.errors import NoFile
from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorDatabase,
    AsyncIOMotorGridFSBucket,
)

from src.config import MONGODB_URI


async def rehash_attachment_content_hashes(db: AsyncIOMotorDatabase) -> dict[str, int]:
    """Recompute attachment `content_hash` values from GridFS originals."""
    bucket = AsyncIOMotorGridFSBucket(db)
    stats = {"checked": 0, "updated": 0, "missing_original": 0}

    cursor = db.documents.find(
        {"is_attachment": True, "original_file_id": {"$ne": None}},
        {"_id": 1, "content_hash": 1, "original_file_id": 1},
    )
    async for doc in cursor:
        stats["checked"] += 1
        try:
            stream = await bucket.open_download_stream(doc["original_file_id"])
        except NoFile:
            stats["missing_original"] += 1
            continue
        original_hash = hashlib.sha256(await stream.read()).hexdigest()
        if doc.get("content_hash") != original_hash:
            await db.documents.update_one(
                {"_id": doc["_id"]}, {"$set": {"content_hash": original_hash}}
            )
            stats["updated"] += 1

    return stats


async def main() -> None:
    client: AsyncIOMotorClient = AsyncIOMotorClient(MONGODB_URI)
    try:
        print("Re-hashing attachment documents on original bytes...")
        stats = await rehash_attachment_content_hashes(client["blackbar"])
        print(f"   Attachments checked: {stats['checked']}")
        print(f"   Hashes updated: {stats['updated']}")
        print(f"   Missing GridFS original: {stats['missing_original']}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
