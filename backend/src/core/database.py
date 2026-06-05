"""
Database Management
Provides database connections for the BlackBar instance
"""

import logging

from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from src.config import MONGODB_URI

logger = logging.getLogger(__name__)

# Global MongoDB client
_client: AsyncIOMotorClient | None = None


def get_mongodb_client() -> AsyncIOMotorClient:
    """Get or create the global MongoDB client"""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            MONGODB_URI,
            maxPoolSize=50,
            minPoolSize=10,
            maxIdleTimeMS=45000,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            socketTimeoutMS=45000,
        )
        logger.info("MongoDB client initialized")
    return _client


def get_shared_database() -> AsyncIOMotorDatabase:
    """Get the blackbar database"""
    client = get_mongodb_client()
    return client["blackbar"]


def get_database() -> AsyncIOMotorDatabase:
    """Get the blackbar database"""
    return get_shared_database()


async def get_database_from_request(request: Request) -> AsyncIOMotorDatabase:
    """
    Get database from request context.
    Returns the single blackbar database.

    Usage:
        @router.get("/cases")
        async def list_cases(db = Depends(get_database_from_request)):
            cases = await db.cases.find({}).to_list(100)
    """
    return get_shared_database()


async def create_indexes(db: AsyncIOMotorDatabase = None):
    """Create indexes for all database collections"""
    if db is None:
        db = get_shared_database()

    # Cases indexes
    await db.cases.create_index("id", unique=True)
    await db.cases.create_index("tracking_number", unique=True)
    await db.cases.create_index("status")
    await db.cases.create_index("created_at")
    await db.cases.create_index([("status", 1), ("created_at", -1)])

    # Documents indexes
    await db.documents.create_index("id", unique=True)
    await db.documents.create_index("case_id")
    await db.documents.create_index("created_at")
    await db.documents.create_index("file_hash")
    await db.documents.create_index("is_duplicate")
    await db.documents.create_index([("case_id", 1), ("is_duplicate", 1)])
    await db.documents.create_index([("case_id", 1), ("file_hash", 1)])

    # Templates indexes
    await db.templates.create_index("id", unique=True)
    await db.templates.create_index("category")
    await db.templates.create_index("is_active")

    # Workflow indexes
    from src.workflow.indexes import create_workflow_indexes

    await create_workflow_indexes(db)

    logger.info("Created indexes for database")
