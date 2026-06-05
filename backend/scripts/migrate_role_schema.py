#!/usr/bin/env python3
"""
Database Migration Script: Tenant Role Schema Simplification
WP-004: Migrate existing users from old tenant roles to new simplified schema

Migration Mapping:
- reviewer → user
- approver → user
- manager → admin
- owner → owner (unchanged)
- admin → admin (unchanged)
- analyst → analyst (unchanged)
- user → user (unchanged)
- guest → guest (unchanged)

Usage:
    # Dry run (preview changes):
    python scripts/migrate_role_schema.py --dry-run
    
    # Execute migration:
    python scripts/migrate_role_schema.py
    
    # Or run from docker:
    docker compose exec backend python scripts/migrate_role_schema.py --dry-run
"""
import asyncio
import argparse
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import os
import sys

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")

# Role migration mapping
ROLE_MIGRATION = {
    "reviewer": "user",
    "approver": "user",
    "manager": "admin",
    # Unchanged roles
    "owner": "owner",
    "admin": "admin",
    "analyst": "analyst",
    "user": "user",
    "guest": "guest"
}


async def migrate_role_schema(dry_run: bool = True):
    """
    Migrate user-tenant memberships from old role schema to new simplified schema.
    
    Args:
        dry_run: If True, only preview changes without applying them
    """
    client = AsyncIOMotorClient(MONGO_URI)
    global_db = client["blackbar"]
    
    print("=" * 80)
    print("WP-004: Tenant Role Schema Migration")
    print("=" * 80)
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else 'LIVE MIGRATION'}")
    print()
    
    # Get all memberships
    memberships = await global_db.user_tenant_memberships.find({}).to_list(length=None)
    
    print(f"Found {len(memberships)} total memberships")
    print()
    
    # Analyze what needs to be migrated
    changes_needed = {}
    unchanged = {}
    
    for membership in memberships:
        current_role = membership.get("role")
        new_role = ROLE_MIGRATION.get(current_role, current_role)
        
        if current_role != new_role:
            if new_role not in changes_needed:
                changes_needed[new_role] = []
            changes_needed[new_role].append({
                "membership_id": membership["id"],
                "user_id": membership["user_id"],
                "tenant_id": membership["tenant_id"],
                "old_role": current_role,
                "new_role": new_role
            })
        else:
            if current_role not in unchanged:
                unchanged[current_role] = 0
            unchanged[current_role] += 1
    
    # Display summary
    print("📊 Migration Summary:")
    print("-" * 80)
    
    if changes_needed:
        print("\n✏️  Changes Required:")
        for new_role, changes in changes_needed.items():
            old_roles = {}
            for change in changes:
                old_role = change["old_role"]
                if old_role not in old_roles:
                    old_roles[old_role] = 0
                old_roles[old_role] += 1
            
            for old_role, count in old_roles.items():
                print(f"   {old_role:12} → {new_role:12} ({count:3} memberships)")
    else:
        print("\n✅ No changes needed - all roles already using new schema")
    
    if unchanged:
        print("\n✓  Unchanged Roles:")
        for role, count in unchanged.items():
            print(f"   {role:12} : {count:3} memberships")
    
    print()
    print(f"Total changes: {sum(len(changes) for changes in changes_needed.values())}")
    print(f"Total unchanged: {sum(unchanged.values())}")
    print()
    
    # If dry run, stop here
    if dry_run:
        print("=" * 80)
        print("DRY RUN COMPLETE - No changes were made")
        print("Run without --dry-run flag to apply these changes")
        print("=" * 80)
        client.close()
        return
    
    # Confirm before proceeding
    print("⚠️  WARNING: This will modify the database!")
    print("=" * 80)
    response = input("Type 'MIGRATE' to proceed with migration: ")
    
    if response != "MIGRATE":
        print("Migration cancelled")
        client.close()
        return
    
    print()
    print("Starting migration...")
    print()
    
    # Perform migration
    migrated_count = 0
    error_count = 0
    
    for new_role, changes in changes_needed.items():
        for change in changes:
            try:
                result = await global_db.user_tenant_memberships.update_one(
                    {"id": change["membership_id"]},
                    {
                        "$set": {
                            "role": change["new_role"],
                            "updated_at": datetime.utcnow(),
                            "migration_note": f"WP-004: Migrated from {change['old_role']} to {change['new_role']}"
                        }
                    }
                )
                
                if result.modified_count > 0:
                    migrated_count += 1
                    print(f"✅ Migrated membership {change['membership_id']}: {change['old_role']} → {change['new_role']}")
                else:
                    print(f"⚠️  No change for membership {change['membership_id']}")
                    
            except Exception as e:
                error_count += 1
                print(f"❌ Error migrating membership {change['membership_id']}: {str(e)}")
    
    print()
    print("=" * 80)
    print("Migration Complete")
    print("=" * 80)
    print(f"✅ Successfully migrated: {migrated_count}")
    if error_count > 0:
        print(f"❌ Errors: {error_count}")
    print()
    
    # Verify migration
    print("Verifying migration...")
    remaining_old_roles = await global_db.user_tenant_memberships.count_documents({
        "role": {"$in": ["reviewer", "approver", "manager"]}
    })
    
    if remaining_old_roles > 0:
        print(f"⚠️  WARNING: {remaining_old_roles} memberships still have old roles!")
    else:
        print("✅ Verification passed - no old roles remaining")
    
    print()
    
    # Show final role distribution
    print("Final Role Distribution:")
    print("-" * 80)
    for role in ["owner", "admin", "analyst", "user", "guest"]:
        count = await global_db.user_tenant_memberships.count_documents({"role": role})
        print(f"   {role:12} : {count:3} memberships")
    
    client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate tenant role schema from old to new simplified schema"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them"
    )
    
    args = parser.parse_args()
    
    try:
        asyncio.run(migrate_role_schema(dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("\n\nMigration cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Migration failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
