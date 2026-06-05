"""
Database indexes for RFC-010 workflow collections.

Run this on database creation or startup.
"""

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


async def create_workflow_indexes(db: AsyncIOMotorDatabase):
    """
    Create indexes for workflow collections.

    Collections:
    - clock_events: Statutory clock events
    - case_messages: Internal staff messaging
    - case_contributors: Named record contributors
    - case_reminders: Milestone notifications
    """

    # Clock events indexes
    await db.clock_events.create_index("id", unique=True)
    await db.clock_events.create_index("case_id")
    await db.clock_events.create_index([("case_id", 1), ("event_date", 1)])
    logger.info("Created indexes for clock_events collection")

    # Case messages indexes
    await db.case_messages.create_index("id", unique=True)
    await db.case_messages.create_index("case_id")
    await db.case_messages.create_index([("case_id", 1), ("created_at", 1)])
    await db.case_messages.create_index("author_id")
    await db.case_messages.create_index("mentions")  # For @mention queries
    logger.info("Created indexes for case_messages collection")

    # Case contributors indexes
    await db.case_contributors.create_index("id", unique=True)
    await db.case_contributors.create_index("case_id")
    await db.case_contributors.create_index("email")
    await db.case_contributors.create_index("status")
    await db.case_contributors.create_index([("case_id", 1), ("status", 1)])
    logger.info("Created indexes for case_contributors collection")

    # Case reminders indexes
    await db.case_reminders.create_index("id", unique=True)
    await db.case_reminders.create_index("case_id")
    await db.case_reminders.create_index("status")
    await db.case_reminders.create_index("trigger_date")
    await db.case_reminders.create_index(
        [("status", 1), ("trigger_date", 1)]
    )  # For pending reminder queries
    await db.case_reminders.create_index("recipient_ids")
    logger.info("Created indexes for case_reminders collection")

    # Cases collection - add indexes for new RFC-010 fields
    await db.cases.create_index("clock_status")
    await db.cases.create_index("workflow_stage")
    await db.cases.create_index("all_records_uploaded")
    await db.cases.create_index([("clock_status", 1), ("due_date", 1)])  # For queue queries
    await db.cases.create_index([("workflow_stage", 1), ("due_date", 1)])
    await db.cases.create_index("priority_override")
    logger.info("Created RFC-010 indexes for cases collection")

    # Case transfers indexes
    await db.case_transfers.create_index("id", unique=True)
    await db.case_transfers.create_index("case_id")
    await db.case_transfers.create_index("status")
    await db.case_transfers.create_index("recipient_email")
    await db.case_transfers.create_index([("case_id", 1), ("transferred_at", -1)])
    logger.info("Created indexes for case_transfers collection")

    logger.info("All RFC-010 workflow indexes created successfully")
