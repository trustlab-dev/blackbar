"""
Database Purge Script
Clears all data from the database for a fresh start
"""

import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient


async def purge_database():
    """Purge all collections in the database"""

    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://mongodb:27017")
    client = AsyncIOMotorClient(mongodb_uri)
    db = client["blackbar"]

    print("\n" + "=" * 70)
    print("⚠️  DATABASE PURGE")
    print("=" * 70)
    print("This will DELETE ALL DATA from the following collections:")
    print("  - users")
    print("  - cases")
    print("  - documents")
    print("  - teams")
    print("  - categories")
    print("  - audit_logs")
    print("=" * 70)

    confirm = input("\nType 'PURGE' to confirm: ")
    if confirm != "PURGE":
        print("❌ Purge cancelled")
        return

    print("\n🗑️  Purging database...")

    # Drop collections
    collections = ["users", "cases", "documents", "teams", "categories", "audit_logs"]

    for collection_name in collections:
        collection = db[collection_name]
        count = await collection.count_documents({})
        if count > 0:
            await collection.delete_many({})
            print(f"   ✓ Deleted {count} documents from {collection_name}")
        else:
            print(f"   - {collection_name} was already empty")

    print("\n✅ Database purged successfully!")
    print("   Run the application to create a fresh admin account")
    print("=" * 70 + "\n")

    client.close()


if __name__ == "__main__":
    asyncio.run(purge_database())
