"""
Repository for public users and magic link tokens
Handles all database operations for public user management
"""

import uuid
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from .models import MagicLinkToken, PublicUser, PublicUserCreate, PublicUserUpdate


class PublicUsersRepository:
    """Repository for public user CRUD operations"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.public_users

    async def create(self, user_create: PublicUserCreate) -> PublicUser:
        """Create a new public user"""
        user_dict = {
            "_id": str(uuid.uuid4()),
            **user_create.model_dump(),
            "email_verified": True,  # Verified via magic link
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_login_at": None,
            "request_ids": [],
        }

        await self.collection.insert_one(user_dict)

        return PublicUser(
            id=user_dict["_id"],
            **user_create.model_dump(),
            email_verified=True,
            status="active",
            created_at=user_dict["created_at"],
            updated_at=user_dict["updated_at"],
            last_login_at=None,
            request_ids=[],
        )

    async def get_by_id(self, user_id: str) -> PublicUser | None:
        """Get user by ID"""
        user_dict = await self.collection.find_one({"_id": user_id})

        if not user_dict:
            return None

        return PublicUser(
            id=user_dict["_id"],
            email=user_dict["email"],
            name=user_dict.get("name"),
            email_verified=user_dict.get("email_verified", True),
            status=user_dict.get("status", "active"),
            created_at=user_dict["created_at"],
            updated_at=user_dict["updated_at"],
            last_login_at=user_dict.get("last_login_at"),
            request_ids=user_dict.get("request_ids", []),
        )

    async def get_by_email(self, email: str) -> PublicUser | None:
        """Get user by email"""
        user_dict = await self.collection.find_one({"email": email.lower()})

        if not user_dict:
            return None

        return PublicUser(
            id=user_dict["_id"],
            email=user_dict["email"],
            name=user_dict.get("name"),
            email_verified=user_dict.get("email_verified", True),
            status=user_dict.get("status", "active"),
            created_at=user_dict["created_at"],
            updated_at=user_dict["updated_at"],
            last_login_at=user_dict.get("last_login_at"),
            request_ids=user_dict.get("request_ids", []),
        )

    async def update_last_login(self, user_id: str) -> bool:
        """Update user's last login timestamp"""
        result = await self.collection.update_one(
            {"_id": user_id},
            {"$set": {"last_login_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
        )
        return result.modified_count > 0

    async def update(self, user_id: str, user_update: PublicUserUpdate = None) -> bool:
        """Update user information"""
        update_data = {k: v for k, v in user_update.model_dump().items() if v is not None}
        if not update_data:
            return False

        update_data["updated_at"] = datetime.utcnow()

        result = await self.collection.update_one({"_id": user_id}, {"$set": update_data})
        return result.modified_count > 0


class MagicLinkTokensRepository:
    """Repository for magic link token operations"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.magic_link_tokens

    async def create_token(
        self,
        email: str,
        token_hash: str,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> MagicLinkToken:
        """Create a new magic link token"""
        token_dict = {
            "_id": str(uuid.uuid4()),
            "email": email.lower(),
            "token_hash": token_hash,
            "expires_at": expires_at,
            "used": False,
            "created_at": datetime.utcnow(),
            "ip_address": ip_address,
            "user_agent": user_agent,
        }

        await self.collection.insert_one(token_dict)

        return MagicLinkToken(
            id=token_dict["_id"],
            email=token_dict["email"],
            token_hash=token_dict["token_hash"],
            expires_at=token_dict["expires_at"],
            used=False,
            created_at=token_dict["created_at"],
            ip_address=token_dict.get("ip_address"),
            user_agent=token_dict.get("user_agent"),
        )

    async def get_by_email(self, email: str) -> MagicLinkToken | None:
        """Get most recent unused, unexpired token for email"""
        query = {"email": email.lower(), "used": False, "expires_at": {"$gt": datetime.utcnow()}}
        token_dict = await self.collection.find_one(query, sort=[("created_at", -1)])

        if not token_dict:
            return None

        return MagicLinkToken(
            id=token_dict["_id"],
            email=token_dict["email"],
            token_hash=token_dict["token_hash"],
            expires_at=token_dict["expires_at"],
            used=token_dict["used"],
            created_at=token_dict["created_at"],
            ip_address=token_dict.get("ip_address"),
            user_agent=token_dict.get("user_agent"),
        )

    async def mark_as_used(self, token_id: str) -> bool:
        """Mark token as used"""
        result = await self.collection.update_one({"_id": token_id}, {"$set": {"used": True}})
        return result.modified_count > 0

    async def count_recent_requests(
        self,
        email: str,
        since: datetime,
    ) -> int:
        """Count token requests since a given time (for rate limiting)"""
        query = {"email": email.lower(), "created_at": {"$gte": since}}
        count = await self.collection.count_documents(query)
        return count

    async def cleanup_expired(self) -> int:
        """Delete expired tokens (called by background task)"""
        result = await self.collection.delete_many({"expires_at": {"$lt": datetime.utcnow()}})
        return result.deleted_count
