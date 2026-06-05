"""
Repository for user data access
"""

import re
import uuid
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from .models import User, UserCreate, UserUpdate


class UsersRepository:
    """Repository for user CRUD operations"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.users

    async def create(self, user_data: UserCreate, password_hash: str) -> User:
        """Create a new user with hashed password"""
        user_dict = user_data.model_dump(exclude={"password"})
        user_dict["id"] = str(uuid.uuid4())
        user_dict["password_hash"] = password_hash
        user_dict["external_id"] = None
        user_dict["created_at"] = datetime.utcnow()
        user_dict["updated_at"] = datetime.utcnow()

        await self.collection.insert_one(user_dict)
        return User(**user_dict)

    async def get_by_id(self, user_id: str) -> User | None:
        """Get user by ID"""
        doc = await self.collection.find_one({"id": user_id})
        if doc:
            doc.pop("_id", None)
            return User(**doc)
        return None

    async def get_by_email(self, email: str) -> User | None:
        """Get user by email (case-insensitive)"""
        escaped_email = re.escape(email)
        doc = await self.collection.find_one(
            {"email": {"$regex": f"^{escaped_email}$", "$options": "i"}}
        )
        if doc:
            doc.pop("_id", None)
            return User(**doc)
        return None

    async def get_by_external_id(self, external_id: str) -> User | None:
        """Get user by external IdP ID"""
        doc = await self.collection.find_one({"external_id": external_id})
        if doc:
            doc.pop("_id", None)
            return User(**doc)
        return None

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[User]:
        """List all users with pagination"""
        cursor = self.collection.find().skip(skip).limit(limit)
        users = []
        async for doc in cursor:
            doc.pop("_id", None)
            users.append(User(**doc))
        return users

    async def update(
        self, user_id: str, update_data: UserUpdate, password_hash: str | None = None
    ) -> User | None:
        """Update a user"""
        update_dict = {
            k: v for k, v in update_data.model_dump(exclude={"password"}).items() if v is not None
        }
        if password_hash:
            update_dict["password_hash"] = password_hash

        if not update_dict:
            return await self.get_by_id(user_id)

        update_dict["updated_at"] = datetime.utcnow()

        result = await self.collection.update_one({"id": user_id}, {"$set": update_dict})

        if result.modified_count > 0:
            return await self.get_by_id(user_id)
        return None

    async def delete(self, user_id: str) -> bool:
        """Delete a user"""
        result = await self.collection.delete_one({"id": user_id})
        return result.deleted_count > 0

    async def create_indexes(self):
        """Create necessary indexes"""
        await self.collection.create_index("id", unique=True)
        await self.collection.create_index("email", unique=True)
        await self.collection.create_index("external_id", sparse=True)
        await self.collection.create_index("status")
