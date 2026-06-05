"""Tests for `src.workflow.repository`.

Phase 2.5.A. Target >=80% line coverage on src.workflow.repository.

Covers all five repository classes:
    - ClockEventsRepository
    - ContributorsRepository
    - RemindersRepository
    - QueueRepository
    - TransfersRepository

Plus the module-level `hash_token` / `verify_token` helpers.

Tests use the per-test `db` fixture (testcontainer Mongo) so the
clock-status side-effects on the `cases` collection round-trip
through real Mongo writes — pinning the real state-machine behavior
(pause -> resume calculates `total_paused_days` from `clock_paused_at`).

Reality pins surfaced while writing these tests:
- `record_upload` only increments `documents_uploaded` and stamps
  `last_upload_at`; it does NOT change `status`. The contributor's
  status only flips to ACTIVE on first `verify_token` call (see
  `verify_token` body).
- `update` with `status=COMPLETED` triggers a `completed_at` stamp
  side effect.
- `_calculate_priority_score`'s due_date branches:
    * overdue:           score >= 1000 + abs(days) * 10
    * 0..3 days:         score >= 500
    * 4..7 days:         score >= 200
    * 8..14 days:        score >= 100
    * >14 days:          score == max(0, 100 - days_until_due)
  Document-count tiers: >50 +30, >20 +15, >10 +5, else 0.
- `set_priority_override` returns False if no document modified
  (matched_count = 0 OR matched but no change).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.workflow.models import (
    ClockEventCreate,
    ClockEventType,
    ClockPauseReason,
    ContributorCreate,
    ContributorStatus,
    ContributorUpdate,
    QueueFilter,
    ReminderCreate,
    ReminderStatus,
    ReminderType,
    TransferCreate,
)
from src.workflow.repository import (
    ClockEventsRepository,
    ContributorsRepository,
    QueueRepository,
    RemindersRepository,
    TransfersRepository,
    hash_token,
    verify_token,
)
from tests.factories import make_case

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestTokenHelpers:
    def test_hash_token_returns_64_char_hex(self) -> None:
        h = hash_token("secret")
        assert isinstance(h, str)
        assert len(h) == 64  # sha256 hex
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_token_deterministic(self) -> None:
        assert hash_token("foo") == hash_token("foo")
        assert hash_token("foo") != hash_token("bar")

    def test_verify_token_matches(self) -> None:
        token = "raw-token"
        assert verify_token(token, hash_token(token)) is True

    def test_verify_token_rejects_wrong(self) -> None:
        assert verify_token("other", hash_token("raw")) is False


# ---------------------------------------------------------------------------
# ClockEventsRepository
# ---------------------------------------------------------------------------


class TestClockEventsRepository:
    async def _seed_case(self, db: AsyncIOMotorDatabase, **overrides: Any) -> str:
        case = make_case(**overrides)
        await db.cases.insert_one(case)
        return case["id"]

    async def test_create_pause_event_sets_clock_status(self, db: AsyncIOMotorDatabase) -> None:
        case_id = await self._seed_case(db)
        repo = ClockEventsRepository(db)

        event = await repo.create(
            case_id=case_id,
            event_data=ClockEventCreate(
                event_type=ClockEventType.PAUSE,
                reason=ClockPauseReason.FEE_PENDING,
                notes="awaiting payment",
            ),
            user_id="u1",
            user_name="User One",
        )

        assert event.event_type == ClockEventType.PAUSE
        assert event.reason == ClockPauseReason.FEE_PENDING
        assert event.created_by == "u1"
        assert event.created_by_name == "User One"
        # Case row updated
        case = await db.cases.find_one({"id": case_id})
        assert case["clock_status"] == "paused"
        assert case["clock_paused_at"] is not None
        assert case["clock_pause_reason"] == "fee_pending"
        # FEE_PENDING also flips workflow_stage
        assert case["workflow_stage"] == "pending_fee_payment"

    async def test_create_pause_with_privacy_commission_reason_sets_workflow_stage(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        case_id = await self._seed_case(db)
        repo = ClockEventsRepository(db)

        await repo.create(
            case_id=case_id,
            event_data=ClockEventCreate(
                event_type=ClockEventType.PAUSE,
                reason=ClockPauseReason.PRIVACY_COMMISSION_REVIEW,
            ),
            user_id="u1",
            user_name="User One",
        )

        case = await db.cases.find_one({"id": case_id})
        assert case["workflow_stage"] == "privacy_commission_review"

    async def test_create_resume_event_recalculates_adjusted_due_date(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        # Seed a paused case with a known clock_paused_at 5 days ago
        five_days_ago = datetime.utcnow() - timedelta(days=5)
        original_due = datetime.utcnow() + timedelta(days=10)
        case_id = await self._seed_case(
            db,
            clock_status="paused",
            clock_paused_at=five_days_ago,
            due_date=original_due,
            total_paused_days=0,
        )

        repo = ClockEventsRepository(db)
        event = await repo.create(
            case_id=case_id,
            event_data=ClockEventCreate(event_type=ClockEventType.RESUME),
            user_id="u2",
            user_name="Resumer",
        )

        assert event.event_type == ClockEventType.RESUME
        case = await db.cases.find_one({"id": case_id})
        assert case["clock_status"] == "running"
        assert case["clock_paused_at"] is None
        assert case["total_paused_days"] >= 5
        # Adjusted due date shifted forward
        assert case["adjusted_due_date"] > original_due

    async def test_create_start_event_resets_clock_state(self, db: AsyncIOMotorDatabase) -> None:
        case_id = await self._seed_case(db, clock_status="paused", total_paused_days=7)
        repo = ClockEventsRepository(db)
        await repo.create(
            case_id=case_id,
            event_data=ClockEventCreate(event_type=ClockEventType.START),
            user_id="u",
            user_name="N",
        )
        case = await db.cases.find_one({"id": case_id})
        assert case["clock_status"] == "running"
        assert case["clock_paused_at"] is None
        assert case["total_paused_days"] == 0

    async def test_get_by_case_returns_events_sorted_ascending(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        case_id = await self._seed_case(db)
        repo = ClockEventsRepository(db)

        for reason in [ClockPauseReason.MANUAL, ClockPauseReason.SCOPE_NARROWING]:
            await repo.create(
                case_id=case_id,
                event_data=ClockEventCreate(event_type=ClockEventType.PAUSE, reason=reason),
                user_id="u",
                user_name="N",
            )

        events = await repo.get_by_case(case_id)
        assert len(events) == 2
        assert events[0].event_date <= events[1].event_date

    async def test_get_clock_status_assembles_summary(self, db: AsyncIOMotorDatabase) -> None:
        due = datetime.utcnow() + timedelta(days=7)
        case_id = await self._seed_case(db, due_date=due)
        repo = ClockEventsRepository(db)
        # Pause then check status
        await repo.create(
            case_id=case_id,
            event_data=ClockEventCreate(
                event_type=ClockEventType.PAUSE,
                reason=ClockPauseReason.MANUAL,
            ),
            user_id="u",
            user_name="N",
        )
        status = await repo.get_clock_status(case_id)
        assert status.case_id == case_id
        assert status.status == "paused"
        assert status.current_pause_reason == ClockPauseReason.MANUAL
        assert len(status.events) == 1

    async def test_create_string_received_date_with_z_suffix_succeeds(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        """Phase 4 Batch 4.4 (audit B43): `Z`-suffixed ISO strings in
        Mongo no longer crash the clock-events repository. The new
        `_parse_iso_naive` helper coerces the parsed datetime back to
        naive (matching `datetime.utcnow()`), so the arithmetic site
        succeeds. Same defect class as the already-fixed B11.

        Regression test flipped from `pytest.raises(TypeError)` to
        assert the happy-path event creation."""
        received_iso = (datetime.utcnow() - timedelta(days=3)).isoformat() + "Z"
        case_id = await self._seed_case(db, received_date=received_iso)
        repo = ClockEventsRepository(db)
        event = await repo.create(
            case_id=case_id,
            event_data=ClockEventCreate(
                event_type=ClockEventType.PAUSE,
                reason=ClockPauseReason.MANUAL,
            ),
            user_id="u",
            user_name="N",
        )
        assert event.days_elapsed_at_event is not None
        assert event.days_elapsed_at_event >= 2

    async def test_create_string_received_date_no_z_works(self, db: AsyncIOMotorDatabase) -> None:
        """A naive-ISO string (no `Z`) is parsed naive, so subtraction works."""
        received_iso = (datetime.utcnow() - timedelta(days=3)).isoformat()
        case_id = await self._seed_case(db, received_date=received_iso)
        repo = ClockEventsRepository(db)
        event = await repo.create(
            case_id=case_id,
            event_data=ClockEventCreate(
                event_type=ClockEventType.PAUSE,
                reason=ClockPauseReason.MANUAL,
            ),
            user_id="u",
            user_name="N",
        )
        assert event.days_elapsed_at_event is not None
        assert event.days_elapsed_at_event >= 2

    async def test_resume_with_string_clock_paused_at_naive(self, db: AsyncIOMotorDatabase) -> None:
        """clock_paused_at stored as naive-ISO string still resolves on resume.
        (Z-suffixed string would trip the B43 bug above.)"""
        paused_iso = (datetime.utcnow() - timedelta(days=4)).isoformat()
        due_iso = (datetime.utcnow() + timedelta(days=10)).isoformat()
        case_id = await self._seed_case(
            db,
            clock_status="paused",
            clock_paused_at=paused_iso,
            due_date=due_iso,
        )
        repo = ClockEventsRepository(db)
        await repo.create(
            case_id=case_id,
            event_data=ClockEventCreate(event_type=ClockEventType.RESUME),
            user_id="u",
            user_name="N",
        )
        case = await db.cases.find_one({"id": case_id})
        assert case["clock_status"] == "running"
        assert case["total_paused_days"] >= 3


# ---------------------------------------------------------------------------
# ContributorsRepository
# ---------------------------------------------------------------------------


class TestContributorsRepository:
    async def test_create_returns_contributor_and_raw_token(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, raw_token = await repo.create(
            case_id="case-1",
            contributor_data=ContributorCreate(
                name="Alice",
                email="alice@example.com",
                department="Records",
                notes="test",
                token_expiration_days=7,
            ),
            user_id="u",
            user_name="Inviter",
        )
        assert contributor.name == "Alice"
        assert contributor.email == "alice@example.com"
        assert contributor.status == ContributorStatus.INVITED
        # Raw token is high-entropy random
        assert isinstance(raw_token, str)
        assert len(raw_token) >= 32
        # The stored hash should validate against the raw token
        stored = await db.case_contributors.find_one({"id": contributor.id})
        assert verify_token(raw_token, stored["upload_token"])

    async def test_get_by_case_sorted_newest_first(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        await repo.create(
            "case-x",
            ContributorCreate(name="First", email="f@example.com"),
            "u",
            "N",
        )
        await repo.create(
            "case-x",
            ContributorCreate(name="Second", email="s@example.com"),
            "u",
            "N",
        )
        contributors = await repo.get_by_case("case-x")
        assert len(contributors) == 2
        # Newest first
        assert contributors[0].created_at >= contributors[1].created_at

    async def test_get_by_id_returns_none_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        assert await repo.get_by_id("nope") is None

    async def test_verify_token_happy_path_flips_to_active(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, raw = await repo.create(
            "case-1",
            ContributorCreate(name="Bob", email="bob@example.com"),
            "u",
            "N",
        )
        verified = await repo.verify_token(contributor.id, raw)
        assert verified is not None
        assert verified.status == ContributorStatus.ACTIVE
        assert verified.first_access_at is not None

    async def test_verify_token_wrong_token_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, _ = await repo.create(
            "case-1",
            ContributorCreate(name="C", email="c@example.com"),
            "u",
            "N",
        )
        assert await repo.verify_token(contributor.id, "wrong-token") is None

    async def test_verify_token_missing_contributor_returns_none(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        repo = ContributorsRepository(db)
        assert await repo.verify_token("ghost", "anything") is None

    async def test_verify_token_expired_marks_status_and_returns_none(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        """Expiration handling: status flipped to EXPIRED, returns None."""
        repo = ContributorsRepository(db)
        contributor, raw = await repo.create(
            "case-1",
            ContributorCreate(name="D", email="d@example.com"),
            "u",
            "N",
        )
        # Force expiration in the past
        await db.case_contributors.update_one(
            {"id": contributor.id},
            {"$set": {"token_expires_at": datetime.utcnow() - timedelta(days=1)}},
        )
        assert await repo.verify_token(contributor.id, raw) is None
        stored = await db.case_contributors.find_one({"id": contributor.id})
        assert stored["status"] == ContributorStatus.EXPIRED.value

    async def test_record_upload_increments_counter(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, _ = await repo.create(
            "case-1",
            ContributorCreate(name="E", email="e@example.com"),
            "u",
            "N",
        )
        updated = await repo.record_upload(contributor.id)
        assert updated.documents_uploaded == 1
        assert updated.last_upload_at is not None
        await repo.record_upload(contributor.id)
        again = await repo.get_by_id(contributor.id)
        assert again.documents_uploaded == 2

    async def test_update_none_fields_is_noop_return(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, _ = await repo.create(
            "case-1",
            ContributorCreate(name="F", email="f@example.com"),
            "u",
            "N",
        )
        # Empty update returns the existing record unchanged
        updated = await repo.update(contributor.id, ContributorUpdate())
        assert updated.id == contributor.id
        assert updated.name == "F"

    async def test_update_to_completed_stamps_completed_at(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, _ = await repo.create(
            "case-1",
            ContributorCreate(name="G", email="g@example.com"),
            "u",
            "N",
        )
        updated = await repo.update(
            contributor.id,
            ContributorUpdate(status=ContributorStatus.COMPLETED),
        )
        assert updated.status == ContributorStatus.COMPLETED
        assert updated.completed_at is not None

    async def test_update_field_persists(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, _ = await repo.create(
            "case-1",
            ContributorCreate(name="Old", email="x@example.com"),
            "u",
            "N",
        )
        updated = await repo.update(contributor.id, ContributorUpdate(name="New"))
        assert updated.name == "New"

    async def test_delete_returns_true_when_found(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, _ = await repo.create(
            "case-1",
            ContributorCreate(name="H", email="h@example.com"),
            "u",
            "N",
        )
        assert await repo.delete(contributor.id) is True
        assert await repo.get_by_id(contributor.id) is None

    async def test_delete_returns_false_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        assert await repo.delete("ghost") is False

    async def test_bulk_create_creates_all(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        results = await repo.bulk_create(
            "case-1",
            [
                ContributorCreate(name="A", email="a@example.com"),
                ContributorCreate(name="B", email="b@example.com"),
            ],
            "u",
            "N",
        )
        assert len(results) == 2
        for contrib, token in results:
            assert isinstance(token, str)
            stored = await db.case_contributors.find_one({"id": contrib.id})
            assert stored is not None

    async def test_confirm_records_complete_flips_status_and_stamps(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        repo = ContributorsRepository(db)
        contributor, _ = await repo.create(
            "case-1",
            ContributorCreate(name="I", email="i@example.com"),
            "u",
            "N",
        )
        confirmed = await repo.confirm_records_complete(contributor.id)
        assert confirmed.records_confirmed is True
        assert confirmed.records_confirmed_at is not None
        assert confirmed.status == ContributorStatus.COMPLETED
        assert confirmed.completed_at is not None

    async def test_update_last_access_sets_timestamp(self, db: AsyncIOMotorDatabase) -> None:
        repo = ContributorsRepository(db)
        contributor, _ = await repo.create(
            "case-1",
            ContributorCreate(name="J", email="j@example.com"),
            "u",
            "N",
        )
        await repo.update_last_access(contributor.id)
        stored = await repo.get_by_id(contributor.id)
        assert stored.last_access_at is not None


# ---------------------------------------------------------------------------
# RemindersRepository
# ---------------------------------------------------------------------------


class TestRemindersRepository:
    async def test_create_reminder_persists_with_defaults(self, db: AsyncIOMotorDatabase) -> None:
        repo = RemindersRepository(db)
        reminder = await repo.create(
            "case-1",
            ReminderCreate(
                reminder_type=ReminderType.CUSTOM,
                trigger_date=datetime.utcnow() + timedelta(days=2),
                recipient_ids=["u1"],
                message="ping",
            ),
        )
        assert reminder.status == ReminderStatus.PENDING
        assert reminder.created_by == "system"  # default
        assert reminder.recipient_ids == ["u1"]

    async def test_get_by_case_filters_to_pending_by_default(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        repo = RemindersRepository(db)
        pending = await repo.create(
            "case-1",
            ReminderCreate(
                trigger_date=datetime.utcnow() + timedelta(days=1),
                recipient_ids=["u"],
                message="m1",
            ),
        )
        sent = await repo.create(
            "case-1",
            ReminderCreate(
                trigger_date=datetime.utcnow() + timedelta(days=1),
                recipient_ids=["u"],
                message="m2",
            ),
        )
        await repo.mark_sent(sent.id, ["email"])

        defaults = await repo.get_by_case("case-1")
        assert len(defaults) == 1
        assert defaults[0].id == pending.id

        with_sent = await repo.get_by_case("case-1", include_sent=True)
        assert len(with_sent) == 2

    async def test_get_pending_reminders_filters_by_before_date(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        repo = RemindersRepository(db)
        now = datetime.utcnow()
        past = await repo.create(
            "c",
            ReminderCreate(
                trigger_date=now - timedelta(hours=1),
                recipient_ids=["u"],
                message="due",
            ),
        )
        future = await repo.create(
            "c",
            ReminderCreate(
                trigger_date=now + timedelta(hours=1),
                recipient_ids=["u"],
                message="later",
            ),
        )
        pending = await repo.get_pending_reminders()  # defaults to <= now
        ids = {r.id for r in pending}
        assert past.id in ids
        assert future.id not in ids

    async def test_get_pending_reminders_explicit_before_date(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        repo = RemindersRepository(db)
        now = datetime.utcnow()
        r1 = await repo.create(
            "c",
            ReminderCreate(
                trigger_date=now + timedelta(days=1),
                recipient_ids=["u"],
                message="m",
            ),
        )
        result = await repo.get_pending_reminders(before_date=now + timedelta(days=2))
        assert any(r.id == r1.id for r in result)

    async def test_mark_sent_returns_updated(self, db: AsyncIOMotorDatabase) -> None:
        repo = RemindersRepository(db)
        r = await repo.create(
            "c",
            ReminderCreate(
                trigger_date=datetime.utcnow(),
                recipient_ids=["u"],
                message="m",
            ),
        )
        updated = await repo.mark_sent(r.id, ["email", "in_app"])
        assert updated.status == ReminderStatus.SENT
        assert updated.sent_via == ["email", "in_app"]
        assert updated.sent_at is not None

    async def test_mark_sent_returns_none_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = RemindersRepository(db)
        assert await repo.mark_sent("ghost", ["email"]) is None

    async def test_dismiss_records_user_and_timestamp(self, db: AsyncIOMotorDatabase) -> None:
        repo = RemindersRepository(db)
        r = await repo.create(
            "c",
            ReminderCreate(
                trigger_date=datetime.utcnow(),
                recipient_ids=["u"],
                message="m",
            ),
        )
        dismissed = await repo.dismiss(r.id, "boss")
        assert dismissed.status == ReminderStatus.DISMISSED
        assert dismissed.dismissed_by == "boss"
        assert dismissed.dismissed_at is not None

    async def test_dismiss_returns_none_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = RemindersRepository(db)
        assert await repo.dismiss("ghost", "u") is None

    async def test_delete_returns_true_when_found(self, db: AsyncIOMotorDatabase) -> None:
        repo = RemindersRepository(db)
        r = await repo.create(
            "c",
            ReminderCreate(
                trigger_date=datetime.utcnow(),
                recipient_ids=["u"],
                message="m",
            ),
        )
        assert await repo.delete(r.id) is True

    async def test_delete_returns_false_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = RemindersRepository(db)
        assert await repo.delete("ghost") is False


# ---------------------------------------------------------------------------
# QueueRepository
# ---------------------------------------------------------------------------


class TestQueueRepository:
    async def _seed_case(self, db: AsyncIOMotorDatabase, **overrides: Any) -> str:
        c = make_case(**overrides)
        await db.cases.insert_one(c)
        return c["id"]

    async def test_get_prioritized_queue_excludes_closed_by_default(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        await self._seed_case(db, status="new")
        await self._seed_case(db, status="closed")
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter())
        assert len(results) == 1

    async def test_get_prioritized_queue_includes_closed_when_flag(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        await self._seed_case(db, status="new")
        await self._seed_case(db, status="closed")
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter(include_closed=True))
        assert len(results) == 2

    async def test_get_prioritized_queue_filters_by_analyst(self, db: AsyncIOMotorDatabase) -> None:
        await self._seed_case(db, assignee="alice")
        await self._seed_case(db, assigned_user_ids=["alice"])
        await self._seed_case(db, assignee="bob")
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter(analyst_id="alice"))
        assert len(results) == 2

    async def test_get_prioritized_queue_filters_by_workflow_stage(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        await self._seed_case(db, workflow_stage="review")
        await self._seed_case(db, workflow_stage="intake")
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter(workflow_stages=["review"]))
        assert len(results) == 1
        assert results[0].workflow_stage == "review"

    async def test_get_prioritized_queue_filters_by_clock_status(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        await self._seed_case(db, clock_status="paused")
        await self._seed_case(db, clock_status="running")
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter(clock_status="paused"))
        assert len(results) == 1
        assert results[0].clock_status == "paused"

    async def test_priority_score_overdue_highest(self, db: AsyncIOMotorDatabase) -> None:
        # Overdue by 10 days
        await self._seed_case(db, due_date=datetime.utcnow() - timedelta(days=10), title="overdue")
        # Comfortable
        await self._seed_case(db, due_date=datetime.utcnow() + timedelta(days=20), title="comfy")
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter())
        assert results[0].title == "overdue"
        assert results[0].priority_score > results[1].priority_score
        assert results[0].priority_score >= 1000

    async def test_priority_override_sorts_first(self, db: AsyncIOMotorDatabase) -> None:
        await self._seed_case(
            db,
            due_date=datetime.utcnow() + timedelta(days=20),
            title="manual-high",
            priority_override=999,
        )
        await self._seed_case(
            db,
            due_date=datetime.utcnow() - timedelta(days=10),
            title="overdue-default",
        )
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter())
        assert results[0].title == "manual-high"

    async def test_priority_score_doc_count_bonus(self, db: AsyncIOMotorDatabase) -> None:
        await self._seed_case(
            db,
            document_ids=[str(uuid.uuid4()) for _ in range(60)],
            title="big",
        )
        await self._seed_case(
            db,
            document_ids=[str(uuid.uuid4()) for _ in range(2)],
            title="small",
        )
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter())
        big = next(r for r in results if r.title == "big")
        small = next(r for r in results if r.title == "small")
        assert big.document_count == 60
        assert small.document_count == 2

    async def test_priority_score_handles_string_due_date_naive(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        """Naive-ISO string due_date is parsed and used for scoring.
        (Z-suffixed string would trip the same B43 tz-mismatch bug as in
        ClockEventsRepository — pinned in that test class.)"""
        await self._seed_case(
            db,
            due_date=(datetime.utcnow() + timedelta(days=5)).isoformat(),
        )
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter())
        assert len(results) == 1
        assert results[0].days_until_due is not None

    async def test_priority_score_no_due_date(self, db: AsyncIOMotorDatabase) -> None:
        await self._seed_case(db, due_date=None)
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter())
        assert len(results) == 1
        assert results[0].days_until_due is None

    async def test_priority_score_uses_adjusted_due_date_when_set(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        adjusted = datetime.utcnow() + timedelta(days=2)
        await self._seed_case(
            db,
            due_date=datetime.utcnow() + timedelta(days=30),
            adjusted_due_date=adjusted,
        )
        repo = QueueRepository(db)
        results = await repo.get_prioritized_queue(QueueFilter())
        # days_until_due should reflect the adjusted date (2 days), not 30
        assert results[0].days_until_due is not None
        assert results[0].days_until_due <= 3

    async def test_set_priority_override_returns_true_on_modify(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        case_id = await self._seed_case(db, priority_override=None)
        repo = QueueRepository(db)
        assert await repo.set_priority_override(case_id, 5) is True
        case = await db.cases.find_one({"id": case_id})
        assert case["priority_override"] == 5

    async def test_set_priority_override_returns_false_when_missing_case(
        self, db: AsyncIOMotorDatabase
    ) -> None:
        repo = QueueRepository(db)
        assert await repo.set_priority_override("ghost", 5) is False


# ---------------------------------------------------------------------------
# TransfersRepository
# ---------------------------------------------------------------------------


class TestTransfersRepository:
    async def test_create_persists_and_returns_raw_token(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        transfer, raw = await repo.create(
            case_id="c1",
            tracking_number="FOI-2026-0001",
            transfer_data=TransferCreate(
                recipient_organization="OtherOrg",
                recipient_email="rcv@example.com",
                recipient_name="Receiver",
                transfer_reason="wrong jurisdiction",
                include_documents=False,
            ),
            user_id="u",
            user_name="N",
        )
        assert transfer.recipient_organization == "OtherOrg"
        assert transfer.status == "pending"
        assert isinstance(raw, str)
        stored = await db.case_transfers.find_one({"id": transfer.id})
        assert verify_token(raw, stored["access_token"])

    async def test_create_respects_custom_expiration(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        transfer, _ = await repo.create(
            case_id="c1",
            tracking_number="FOI-2026-0001",
            transfer_data=TransferCreate(
                recipient_organization="O",
                recipient_email="r@example.com",
                transfer_reason="reason",
            ),
            user_id="u",
            user_name="N",
            token_expiration_days=5,
        )
        delta = transfer.token_expires_at - datetime.utcnow()
        # ~5 days, allow microsecond-level skew between `now` captures
        assert delta.total_seconds() > 4.99 * 86400
        assert delta.total_seconds() <= 5 * 86400

    async def test_get_by_id_returns_none_when_missing(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        assert await repo.get_by_id("ghost") is None

    async def test_get_by_case_orders_newest_first(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        t1, _ = await repo.create(
            "c1",
            "T1",
            TransferCreate(
                recipient_organization="A",
                recipient_email="a@a.com",
                transfer_reason="r",
            ),
            "u",
            "N",
        )
        t2, _ = await repo.create(
            "c1",
            "T1",
            TransferCreate(
                recipient_organization="B",
                recipient_email="b@b.com",
                transfer_reason="r",
            ),
            "u",
            "N",
        )
        transfers = await repo.get_by_case("c1")
        assert len(transfers) == 2
        assert transfers[0].transferred_at >= transfers[1].transferred_at

    async def test_verify_token_happy_path_marks_accessed(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        transfer, raw = await repo.create(
            "c1",
            "T",
            TransferCreate(
                recipient_organization="O",
                recipient_email="o@o.com",
                transfer_reason="r",
            ),
            "u",
            "N",
        )
        verified = await repo.verify_token(transfer.id, raw)
        assert verified is not None
        assert verified.status == "accessed"
        assert verified.accessed_at is not None

    async def test_verify_token_wrong_token_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        transfer, _ = await repo.create(
            "c1",
            "T",
            TransferCreate(
                recipient_organization="O",
                recipient_email="o@o.com",
                transfer_reason="r",
            ),
            "u",
            "N",
        )
        assert await repo.verify_token(transfer.id, "bogus") is None

    async def test_verify_token_missing_returns_none(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        assert await repo.verify_token("ghost", "x") is None

    async def test_verify_token_expired_marks_status(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        transfer, raw = await repo.create(
            "c1",
            "T",
            TransferCreate(
                recipient_organization="O",
                recipient_email="o@o.com",
                transfer_reason="r",
            ),
            "u",
            "N",
        )
        await db.case_transfers.update_one(
            {"id": transfer.id},
            {"$set": {"token_expires_at": datetime.utcnow() - timedelta(days=1)}},
        )
        assert await repo.verify_token(transfer.id, raw) is None
        stored = await db.case_transfers.find_one({"id": transfer.id})
        assert stored["status"] == "expired"

    async def test_mark_downloaded_updates_status(self, db: AsyncIOMotorDatabase) -> None:
        repo = TransfersRepository(db)
        transfer, _ = await repo.create(
            "c1",
            "T",
            TransferCreate(
                recipient_organization="O",
                recipient_email="o@o.com",
                transfer_reason="r",
            ),
            "u",
            "N",
        )
        downloaded = await repo.mark_downloaded(transfer.id)
        assert downloaded.status == "downloaded"
        assert downloaded.downloaded_at is not None
