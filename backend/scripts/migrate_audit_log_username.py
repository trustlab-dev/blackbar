#!/usr/bin/env python3
"""
Migrate audit_log entries from 'user_name' to 'username' field.
This fixes validation errors caused by field name mismatch.
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def migrate_audit_logs():
    # Connect to MongoDB
    client = AsyncIOMotorClient("mongodb://mongodb:27017")
    db = client["blackbar"]
    cases = db.cases
    
    # Find all cases with audit logs
    cursor = cases.find({"audit_log": {"$exists": True, "$ne": []}})
    cases_list = await cursor.to_list(None)
    
    print(f"Found {len(cases_list)} cases with audit logs")
    
    migrated_cases = 0
    migrated_entries = 0
    
    for case in cases_list:
        audit_log = case.get("audit_log", [])
        updated = False
        
        for entry in audit_log:
            # If entry has 'user_name' but not 'username', rename it
            if "user_name" in entry and "username" not in entry:
                entry["username"] = entry.pop("user_name")
                updated = True
                migrated_entries += 1
        
        # Update the case if any entries were modified
        if updated:
            await cases.update_one(
                {"_id": case["_id"]},
                {"$set": {"audit_log": audit_log}}
            )
            migrated_cases += 1
            print(f"Migrated case {case.get('tracking_number', case.get('id', 'unknown'))}: {len([e for e in audit_log if 'username' in e])} entries")
    
    print(f"\nMigration complete!")
    print(f"Cases updated: {migrated_cases}")
    print(f"Audit log entries migrated: {migrated_entries}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(migrate_audit_logs())
