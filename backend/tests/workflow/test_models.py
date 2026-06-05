"""Tests for `src.workflow.models` Pydantic V2 schemas.

Phase 2.5.A. Pins validation behavior, enum membership, and the
Phase-1.9c rename `ContributorUploadInfo.tenant_name` -> `org_name`.

Models covered:
    - WorkflowStage / ClockEventType / ClockPauseReason / ContributorStatus
    - ReminderType / ReminderStatus
    - ClockEventCreate, ClockEvent, ClockStatus
    - MessageCreate, MessageUpdate, CaseMessage
    - ContributorCreate, ContributorUpdate, CaseContributor,
      BulkContributorCreate, ContributorUploadInfo
    - ReminderCreate, CaseReminder
    - RecordsConfirmation, RecordsConfirmationCreate
    - CasePriorityScore, QueueFilter
    - TransferCreate, CaseTransfer, TransferPackageInfo

Reality pins:
- `ContributorUploadInfo` field name is `org_name` (Phase 1.9c rename).
- `ContributorCreate.token_expiration_days` is bounded `ge=1, le=90`.
- `MessageCreate.content` requires `min_length=1, max_length=10000`.
- `QueueFilter.limit` is `le=200`.
- `TransferCreate.transfer_reason` is `min_length=1, max_length=2000`.
- `ContributorCreate.email` must validate as RFC-5321 email (EmailStr).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.workflow.models import (
    BulkContributorCreate,
    CaseContributor,
    CaseMessage,
    CasePriorityScore,
    CaseReminder,
    CaseTransfer,
    ClockEvent,
    ClockEventCreate,
    ClockEventType,
    ClockPauseReason,
    ClockStatus,
    ContributorCreate,
    ContributorStatus,
    ContributorUpdate,
    ContributorUploadInfo,
    MessageCreate,
    MessageUpdate,
    QueueFilter,
    RecordsConfirmation,
    RecordsConfirmationCreate,
    ReminderCreate,
    ReminderStatus,
    ReminderType,
    TransferCreate,
    TransferPackageInfo,
    WorkflowStage,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_workflow_stage_membership(self) -> None:
        assert WorkflowStage.INTAKE.value == "intake"
        assert WorkflowStage.CLOSED.value == "closed"
        assert "pending_fee_payment" in {s.value for s in WorkflowStage}

    def test_clock_event_type_membership(self) -> None:
        values = {e.value for e in ClockEventType}
        assert values == {"start", "pause", "resume", "extend"}

    def test_clock_pause_reason_membership(self) -> None:
        values = {r.value for r in ClockPauseReason}
        assert "fee_pending" in values
        assert "manual" in values

    def test_contributor_status_membership(self) -> None:
        values = {s.value for s in ContributorStatus}
        assert values == {"invited", "active", "completed", "expired"}

    def test_reminder_type_and_status_membership(self) -> None:
        assert "due_date" in {r.value for r in ReminderType}
        assert "pending" in {s.value for s in ReminderStatus}


# ---------------------------------------------------------------------------
# Clock models
# ---------------------------------------------------------------------------


class TestClockEventModels:
    def test_clock_event_create_minimal(self) -> None:
        evt = ClockEventCreate(event_type=ClockEventType.START)
        assert evt.event_type == ClockEventType.START
        assert evt.reason is None

    def test_clock_event_create_invalid_event_type(self) -> None:
        with pytest.raises(ValidationError):
            ClockEventCreate(event_type="not-a-thing")

    def test_clock_event_requires_id_and_user(self) -> None:
        with pytest.raises(ValidationError):
            ClockEvent(case_id="c", event_type=ClockEventType.PAUSE)  # missing id/created_by

    def test_clock_event_full_payload_roundtrips(self) -> None:
        now = datetime.utcnow()
        evt = ClockEvent(
            id="e1",
            case_id="c1",
            event_type=ClockEventType.PAUSE,
            reason=ClockPauseReason.FEE_PENDING,
            event_date=now,
            created_by="u",
            created_by_name="N",
            notes="notes",
            days_elapsed_at_event=3,
        )
        assert evt.id == "e1"
        assert evt.reason == ClockPauseReason.FEE_PENDING
        assert evt.days_elapsed_at_event == 3

    def test_clock_status_defaults(self) -> None:
        s = ClockStatus(case_id="c", status="running")
        assert s.total_paused_days == 0
        assert s.events == []


# ---------------------------------------------------------------------------
# Message models
# ---------------------------------------------------------------------------


class TestMessageModels:
    def test_message_create_empty_content_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MessageCreate(content="")

    def test_message_create_oversize_content_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MessageCreate(content="x" * 10001)

    def test_message_update_at_capacity_ok(self) -> None:
        m = MessageUpdate(content="x" * 10000)
        assert len(m.content) == 10000

    def test_case_message_requires_author(self) -> None:
        with pytest.raises(ValidationError):
            CaseMessage(id="m", case_id="c", content="hi")  # missing author_id/author_name


# ---------------------------------------------------------------------------
# Contributor models
# ---------------------------------------------------------------------------


class TestContributorModels:
    def test_contributor_create_default_expiration_days(self) -> None:
        c = ContributorCreate(name="A", email="a@example.com")
        assert c.token_expiration_days == 14

    def test_contributor_create_invalid_email(self) -> None:
        with pytest.raises(ValidationError):
            ContributorCreate(name="A", email="not-an-email")

    @pytest.mark.parametrize("days", [0, 91, -1])
    def test_contributor_create_expiration_bounds(self, days: int) -> None:
        with pytest.raises(ValidationError):
            ContributorCreate(name="A", email="a@example.com", token_expiration_days=days)

    def test_contributor_create_expiration_at_lower_bound(self) -> None:
        c = ContributorCreate(name="A", email="a@example.com", token_expiration_days=1)
        assert c.token_expiration_days == 1

    def test_contributor_update_all_optional(self) -> None:
        u = ContributorUpdate()
        assert u.model_dump(exclude_none=True) == {}

    def test_case_contributor_defaults(self) -> None:
        cc = CaseContributor(
            id="c1",
            case_id="case",
            name="A",
            email="a@example.com",
            upload_token="hash",
            token_expires_at=datetime.utcnow() + timedelta(days=1),
            invited_by="u",
        )
        assert cc.status == ContributorStatus.INVITED
        assert cc.documents_uploaded == 0
        assert cc.records_confirmed is False

    def test_bulk_contributor_create_requires_list(self) -> None:
        b = BulkContributorCreate(
            contributors=[
                ContributorCreate(name="A", email="a@example.com"),
                ContributorCreate(name="B", email="b@example.com"),
            ]
        )
        assert len(b.contributors) == 2

    def test_contributor_upload_info_has_org_name_field_phase_19c(self) -> None:
        """Phase 1.9c rename pin: `tenant_name` -> `org_name`."""
        info = ContributorUploadInfo(
            contributor_id="c",
            contributor_name="A",
            case_tracking_number="FOI-2026-0001",
            case_title="T",
            org_name="MyOrg",
            documents_uploaded=0,
            is_expired=False,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        assert info.org_name == "MyOrg"
        assert "org_name" in info.model_dump()
        # The old name should NOT be a field
        assert "tenant_name" not in ContributorUploadInfo.model_fields

    def test_contributor_upload_info_requires_org_name(self) -> None:
        with pytest.raises(ValidationError):
            ContributorUploadInfo(
                contributor_id="c",
                contributor_name="A",
                case_tracking_number="T",
                case_title="T",
                # org_name missing
                documents_uploaded=0,
                is_expired=False,
                expires_at=datetime.utcnow(),
            )


# ---------------------------------------------------------------------------
# Reminder models
# ---------------------------------------------------------------------------


class TestReminderModels:
    def test_reminder_create_message_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ReminderCreate(
                trigger_date=datetime.utcnow(),
                recipient_ids=["u"],
                message="",
            )
        with pytest.raises(ValidationError):
            ReminderCreate(
                trigger_date=datetime.utcnow(),
                recipient_ids=["u"],
                message="x" * 1001,
            )

    def test_reminder_create_defaults_type_to_custom(self) -> None:
        r = ReminderCreate(
            trigger_date=datetime.utcnow(),
            recipient_ids=["u"],
            message="ping",
        )
        assert r.reminder_type == ReminderType.CUSTOM

    def test_case_reminder_default_status_pending(self) -> None:
        cr = CaseReminder(
            id="r",
            case_id="c",
            reminder_type=ReminderType.DUE_DATE,
            trigger_date=datetime.utcnow(),
            recipient_ids=["u"],
            message="m",
        )
        assert cr.status == ReminderStatus.PENDING


# ---------------------------------------------------------------------------
# Records confirmation
# ---------------------------------------------------------------------------


class TestRecordsConfirmation:
    def test_records_confirmation_create_default_notes(self) -> None:
        c = RecordsConfirmationCreate()
        assert c.notes is None

    def test_records_confirmation_unconfirmed_minimal(self) -> None:
        rc = RecordsConfirmation(confirmed=False)
        assert rc.confirmed is False
        assert rc.confirmed_by is None


# ---------------------------------------------------------------------------
# Queue models
# ---------------------------------------------------------------------------


class TestQueueModels:
    def test_priority_score_defaults(self) -> None:
        s = CasePriorityScore(
            case_id="c",
            tracking_number="T",
            title="X",
            status="new",
        )
        assert s.priority_score == 0.0
        assert s.clock_status == "running"
        assert s.analyst_ids == []

    def test_queue_filter_defaults(self) -> None:
        f = QueueFilter()
        assert f.include_closed is False
        assert f.limit == 50
        assert f.offset == 0

    def test_queue_filter_limit_max(self) -> None:
        with pytest.raises(ValidationError):
            QueueFilter(limit=201)

    def test_queue_filter_at_max_ok(self) -> None:
        f = QueueFilter(limit=200)
        assert f.limit == 200


# ---------------------------------------------------------------------------
# Transfer models
# ---------------------------------------------------------------------------


class TestTransferModels:
    def test_transfer_create_minimal(self) -> None:
        t = TransferCreate(
            recipient_organization="O",
            recipient_email="o@example.com",
            transfer_reason="r",
        )
        assert t.include_documents is False
        assert t.included_document_ids is None

    def test_transfer_create_invalid_email(self) -> None:
        with pytest.raises(ValidationError):
            TransferCreate(
                recipient_organization="O",
                recipient_email="not-an-email",
                transfer_reason="r",
            )

    def test_transfer_create_reason_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TransferCreate(
                recipient_organization="O",
                recipient_email="o@example.com",
                transfer_reason="",
            )
        with pytest.raises(ValidationError):
            TransferCreate(
                recipient_organization="O",
                recipient_email="o@example.com",
                transfer_reason="x" * 2001,
            )

    def test_transfer_create_organization_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TransferCreate(
                recipient_organization="",
                recipient_email="o@example.com",
                transfer_reason="r",
            )
        with pytest.raises(ValidationError):
            TransferCreate(
                recipient_organization="x" * 501,
                recipient_email="o@example.com",
                transfer_reason="r",
            )

    def test_case_transfer_defaults(self) -> None:
        t = CaseTransfer(
            id="t",
            case_id="c",
            tracking_number="T",
            recipient_organization="O",
            recipient_email="o@example.com",
            transfer_reason="r",
            access_token="h",
            token_expires_at=datetime.utcnow() + timedelta(days=1),
            transferred_by="u",
        )
        assert t.status == "pending"
        assert t.included_document_ids == []
        assert t.include_documents is False

    def test_transfer_package_info_full(self) -> None:
        info = TransferPackageInfo(
            transfer_id="t",
            case_tracking_number="T",
            case_title="X",
            requester_name="R",
            requester_email="r@example.com",
            transfer_reason="r",
            transferred_from="OrgA",
            transferred_at=datetime.utcnow(),
            includes_documents=True,
            document_count=3,
            is_expired=False,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        assert info.document_count == 3
        assert info.requester_organization is None
