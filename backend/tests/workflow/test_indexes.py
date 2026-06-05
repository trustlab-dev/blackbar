"""Tests for `src.workflow.indexes.create_workflow_indexes`.

Phase 2.5.A. Verifies that the helper creates the expected indexes on
the testcontainer Mongo and is idempotent (safe to run twice).

The function unconditionally calls `create_index(...)` against each
collection. Mongo's `create_index` is idempotent for identical specs
(same name + same key + same options), so re-running is a no-op.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.workflow.indexes import create_workflow_indexes


async def _index_keys(db: AsyncIOMotorDatabase, coll: str) -> set[str]:
    """Return the set of index names for a collection."""
    info = await db[coll].index_information()
    return set(info.keys())


class TestCreateWorkflowIndexes:
    async def test_creates_clock_events_indexes(self, db: AsyncIOMotorDatabase) -> None:
        await create_workflow_indexes(db)
        info = await db.clock_events.index_information()
        # All keys mentioned in indexes.py for clock_events
        names = list(info.keys())
        # id unique index, case_id index, compound (case_id, event_date)
        assert any("id" in n for n in names)
        assert any("case_id" in n for n in names)
        assert any("event_date" in n for n in names)

    async def test_id_index_is_unique(self, db: AsyncIOMotorDatabase) -> None:
        await create_workflow_indexes(db)
        for coll in [
            "clock_events",
            "case_messages",
            "case_contributors",
            "case_reminders",
            "case_transfers",
        ]:
            info = await db[coll].index_information()
            # Find the index keyed on `id`
            id_idx = [v for v in info.values() if v["key"] == [("id", 1)]]
            assert id_idx, f"`id` index missing on {coll}"
            assert id_idx[0].get("unique") is True, f"`id` index not unique on {coll}"

    async def test_creates_case_messages_indexes(self, db: AsyncIOMotorDatabase) -> None:
        await create_workflow_indexes(db)
        info = await db.case_messages.index_information()
        # Should have an index on `mentions` for @mention queries
        assert any(v["key"] == [("mentions", 1)] for v in info.values())
        # And on author_id
        assert any(v["key"] == [("author_id", 1)] for v in info.values())

    async def test_creates_case_contributors_indexes(self, db: AsyncIOMotorDatabase) -> None:
        await create_workflow_indexes(db)
        info = await db.case_contributors.index_information()
        assert any(v["key"] == [("email", 1)] for v in info.values())
        assert any(v["key"] == [("status", 1)] for v in info.values())
        # Compound (case_id, status)
        assert any(v["key"] == [("case_id", 1), ("status", 1)] for v in info.values())

    async def test_creates_case_reminders_indexes(self, db: AsyncIOMotorDatabase) -> None:
        await create_workflow_indexes(db)
        info = await db.case_reminders.index_information()
        # Compound (status, trigger_date) used by pending-reminder queries
        assert any(v["key"] == [("status", 1), ("trigger_date", 1)] for v in info.values())
        # recipient_ids multikey index
        assert any(v["key"] == [("recipient_ids", 1)] for v in info.values())

    async def test_creates_cases_rfc010_indexes(self, db: AsyncIOMotorDatabase) -> None:
        await create_workflow_indexes(db)
        info = await db.cases.index_information()
        # clock_status, workflow_stage, all_records_uploaded
        assert any(v["key"] == [("clock_status", 1)] for v in info.values())
        assert any(v["key"] == [("workflow_stage", 1)] for v in info.values())
        assert any(v["key"] == [("all_records_uploaded", 1)] for v in info.values())
        # Compound (workflow_stage, due_date)
        assert any(v["key"] == [("workflow_stage", 1), ("due_date", 1)] for v in info.values())

    async def test_creates_case_transfers_indexes(self, db: AsyncIOMotorDatabase) -> None:
        await create_workflow_indexes(db)
        info = await db.case_transfers.index_information()
        assert any(v["key"] == [("recipient_email", 1)] for v in info.values())
        # Compound (case_id, transferred_at desc)
        assert any(v["key"] == [("case_id", 1), ("transferred_at", -1)] for v in info.values())

    async def test_idempotent_second_run(self, db: AsyncIOMotorDatabase) -> None:
        """Same spec twice is a no-op (Mongo deduplicates by name + key)."""
        await create_workflow_indexes(db)
        before = await _index_keys(db, "clock_events")
        # Run again — must not raise
        await create_workflow_indexes(db)
        after = await _index_keys(db, "clock_events")
        assert before == after
