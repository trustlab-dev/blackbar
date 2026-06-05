"""
Migration: Fix audit log entries with 'user_name' to 'username'
Updates all existing audit log entries to use the correct field name
"""

import asyncio

from motor.motor_asyncio import AsyncIOMotorClient


async def fix_audit_log_usernames():
    """Fix audit log entries with user_name to username"""
    client = AsyncIOMotorClient("mongodb://mongodb:27017")
    db = client["blackbar"]
    cases = db["cases"]

    print("Starting audit log username migration...")

    # Find all cases
    cursor = cases.find({})
    total_cases = await cases.count_documents({})
    print(f"Found {total_cases} cases to check")

    updated_count = 0
    fixed_entries = 0

    async for case in cursor:
        audit_log = case.get("audit_log", [])
        needs_update = False

        # Check each audit log entry
        for i, entry in enumerate(audit_log):
            if "user_name" in entry and "username" not in entry:
                # Move user_name to username
                audit_log[i]["username"] = entry["user_name"]
                del audit_log[i]["user_name"]
                needs_update = True
                fixed_entries += 1

        # Update the case if needed
        if needs_update:
            await cases.update_one({"_id": case["_id"]}, {"$set": {"audit_log": audit_log}})
            updated_count += 1

    print("\n✅ Migration complete!")
    print(f"   Cases updated: {updated_count}")
    print(f"   Audit entries fixed: {fixed_entries}")

    client.close()


if __name__ == "__main__":
    asyncio.run(fix_audit_log_usernames())
