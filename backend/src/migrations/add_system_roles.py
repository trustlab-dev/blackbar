"""
Migration: Add system roles to existing users
Adds 'role' field to users who don't have it (defaults to 'analyst')
"""

import asyncio

from motor.motor_asyncio import AsyncIOMotorClient


async def migrate_user_roles():
    """Add system role to existing users"""
    client = AsyncIOMotorClient("mongodb://mongodb:27017")
    db = client["blackbar"]
    users = db["users"]

    print("Starting user role migration...")

    # Find users without 'role' field or with old 'reviewer' role
    users_without_role = await users.count_documents({"role": {"$exists": False}})
    users_with_reviewer = await users.count_documents({"role": "reviewer"})

    print(f"Found {users_without_role} users without role field")
    print(f"Found {users_with_reviewer} users with 'reviewer' role")

    # Update users without role to 'analyst' (safe default for existing users)
    if users_without_role > 0:
        result = await users.update_many(
            {"role": {"$exists": False}}, {"$set": {"role": "analyst"}}
        )
        print(f"✅ Updated {result.modified_count} users to 'analyst' role")

    # Update old 'reviewer' role to 'user' (limited staff)
    if users_with_reviewer > 0:
        result = await users.update_many({"role": "reviewer"}, {"$set": {"role": "user"}})
        print(f"✅ Migrated {result.modified_count} 'reviewer' users to 'user' role")

    # Ensure all users have 'id' field
    users_without_id = await users.count_documents({"id": {"$exists": False}})
    if users_without_id > 0:
        print(f"Found {users_without_id} users without 'id' field")
        cursor = users.find({"id": {"$exists": False}})
        async for user in cursor:
            user_id = str(user["_id"])
            await users.update_one({"_id": user["_id"]}, {"$set": {"id": user_id}})
        print(f"✅ Added 'id' field to {users_without_id} users")

    # Ensure all users have 'is_active' field
    result = await users.update_many(
        {"is_active": {"$exists": False}}, {"$set": {"is_active": True}}
    )
    if result.modified_count > 0:
        print(f"✅ Added 'is_active' field to {result.modified_count} users")

    # Print summary
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)

    total_users = await users.count_documents({})
    admin_count = await users.count_documents({"role": "admin"})
    analyst_count = await users.count_documents({"role": "analyst"})
    user_count = await users.count_documents({"role": "user"})
    guest_count = await users.count_documents({"role": "guest"})

    print(f"\nTotal users: {total_users}")
    print(f"  - admin: {admin_count}")
    print(f"  - analyst: {analyst_count}")
    print(f"  - user: {user_count}")
    print(f"  - guest: {guest_count}")
    print("\n✅ All users now have system roles!")

    client.close()


if __name__ == "__main__":
    asyncio.run(migrate_user_roles())
