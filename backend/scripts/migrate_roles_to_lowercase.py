#!/usr/bin/env python3
"""
Migration script to convert all role values from uppercase to lowercase
in the memberships collection.

This script updates:
- OWNER -> owner
- ADMIN -> admin
- ANALYST -> analyst
- REVIEWER -> reviewer
- APPROVER -> approver
- MANAGER -> manager
- USER -> user
- GUEST -> guest
"""
import asyncio
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

# Add parent directory to path to import config
sys.path.insert(0, '/app/src')
from config import MONGODB_URI

# Role mapping (uppercase -> lowercase)
ROLE_MAPPING = {
    "OWNER": "owner",
    "ADMIN": "admin",
    "ANALYST": "analyst",
    "REVIEWER": "reviewer",
    "APPROVER": "approver",
    "MANAGER": "manager",
    "USER": "user",
    "GUEST": "guest"
}


async def migrate_roles():
    """Migrate all uppercase role values to lowercase"""
    print("=" * 60)
    print("Role Migration Script")
    print("Converting uppercase roles to lowercase")
    print("=" * 60)
    
    # Connect to MongoDB
    print(f"\nConnecting to MongoDB...")
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client["blackbar"]  # Shared database
    memberships_collection = db["user_tenant_memberships"]
    
    # Count total memberships
    total_count = await memberships_collection.count_documents({})
    print(f"Total memberships: {total_count}")
    
    # Find all memberships with uppercase roles
    uppercase_roles = list(ROLE_MAPPING.keys())
    uppercase_count = await memberships_collection.count_documents({
        "role": {"$in": uppercase_roles}
    })
    print(f"Memberships with uppercase roles: {uppercase_count}")
    
    if uppercase_count == 0:
        print("\n✅ No uppercase roles found. Database is already up to date!")
        client.close()
        return
    
    # Migrate each uppercase role
    total_updated = 0
    for old_role, new_role in ROLE_MAPPING.items():
        # Count documents with this role
        count = await memberships_collection.count_documents({"role": old_role})
        
        if count > 0:
            print(f"\nMigrating {count} memberships from '{old_role}' to '{new_role}'...")
            
            # Update all documents with this role
            result = await memberships_collection.update_many(
                {"role": old_role},
                {
                    "$set": {
                        "role": new_role,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            print(f"  ✅ Updated {result.modified_count} documents")
            total_updated += result.modified_count
    
    # Verify migration
    print("\n" + "=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print(f"Total memberships updated: {total_updated}")
    
    # Show final counts by role
    print("\nFinal role distribution:")
    for role in ["owner", "admin", "analyst", "reviewer", "approver", "manager", "user", "guest"]:
        count = await memberships_collection.count_documents({"role": role})
        if count > 0:
            print(f"  {role}: {count}")
    
    # Check for any remaining uppercase roles
    remaining_uppercase = await memberships_collection.count_documents({
        "role": {"$in": uppercase_roles}
    })
    
    if remaining_uppercase > 0:
        print(f"\n⚠️  WARNING: {remaining_uppercase} memberships still have uppercase roles!")
    else:
        print("\n✅ All roles successfully converted to lowercase!")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(migrate_roles())
