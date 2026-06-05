"""Tests for ``src.utils.deadline_tracker``.

SLA deadline + business-day calculator. Uses ``freezegun`` to pin
``datetime.utcnow()`` (the implementation uses the deprecated
``datetime.utcnow()`` everywhere — see pyproject filterwarning for that
DeprecationWarning suppression).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from freezegun import freeze_time

from src.utils.deadline_tracker import (
    DeadlineStatus,
    SLAType,
    calculate_business_days,
    calculate_business_days_between,
    calculate_sla_deadline,
    generate_deadline_summary,
    get_deadline_color,
    get_deadline_status,
    request_extension,
    should_send_notification,
)

# ---------------------------------------------------------------------------
# calculate_business_days
# ---------------------------------------------------------------------------


class TestCalculateBusinessDays:
    def test_five_business_days_from_monday(self) -> None:
        # Monday 2024-01-01 (actually Monday)
        start = datetime(2024, 1, 1)  # Monday
        result = calculate_business_days(start, 5)
        # +5 business days = Mon→Mon (skip weekend) -> 2024-01-08 (Monday)
        assert result == datetime(2024, 1, 8)

    def test_one_business_day_skips_weekend(self) -> None:
        # Friday 2024-01-05 + 1 business day = Monday 2024-01-08
        friday = datetime(2024, 1, 5)
        result = calculate_business_days(friday, 1)
        assert result == datetime(2024, 1, 8)

    def test_zero_days_returns_start_date(self) -> None:
        start = datetime(2024, 1, 1)
        result = calculate_business_days(start, 0)
        assert result == start

    def test_starting_on_weekend(self) -> None:
        # Saturday 2024-01-06 + 1 business day
        saturday = datetime(2024, 1, 6)
        result = calculate_business_days(saturday, 1)
        # Saturday + 1 = Sunday (skip) → Monday is +1 business day
        assert result == datetime(2024, 1, 8)


class TestCalculateBusinessDaysBetween:
    def test_one_week_apart(self) -> None:
        start = datetime(2024, 1, 1)  # Monday
        end = datetime(2024, 1, 8)  # Monday a week later
        # Mon, Tue, Wed, Thu, Fri = 5 business days
        assert calculate_business_days_between(start, end) == 5

    def test_same_day_returns_zero(self) -> None:
        d = datetime(2024, 1, 1)
        assert calculate_business_days_between(d, d) == 0

    def test_end_before_start_returns_zero(self) -> None:
        assert calculate_business_days_between(datetime(2024, 1, 10), datetime(2024, 1, 1)) == 0


# ---------------------------------------------------------------------------
# get_deadline_status (uses datetime.utcnow internally)
# ---------------------------------------------------------------------------


class TestGetDeadlineStatus:
    def test_overdue(self) -> None:
        now = datetime(2024, 6, 1)
        past = datetime(2024, 5, 1)
        assert get_deadline_status(past, now) == DeadlineStatus.OVERDUE

    def test_urgent_within_3_days(self) -> None:
        now = datetime(2024, 6, 1)
        due_in_2 = datetime(2024, 6, 3)
        assert get_deadline_status(due_in_2, now) == DeadlineStatus.URGENT

    def test_warning_within_7_days(self) -> None:
        now = datetime(2024, 6, 1)
        due_in_5 = datetime(2024, 6, 6)
        assert get_deadline_status(due_in_5, now) == DeadlineStatus.WARNING

    def test_on_track_more_than_7_days(self) -> None:
        now = datetime(2024, 6, 1)
        due_in_30 = datetime(2024, 7, 1)
        assert get_deadline_status(due_in_30, now) == DeadlineStatus.ON_TRACK

    @freeze_time("2024-06-01 12:00:00")
    def test_uses_utcnow_when_current_date_omitted(self) -> None:
        # 2024-06-01 frozen → due 2024-05-01 is OVERDUE
        past = datetime(2024, 5, 1)
        assert get_deadline_status(past) == DeadlineStatus.OVERDUE


# ---------------------------------------------------------------------------
# calculate_sla_deadline
# ---------------------------------------------------------------------------


class TestCalculateSlaDeadline:
    @freeze_time("2024-06-01")
    def test_standard_sla_30_business_days(self) -> None:
        request_date = datetime(2024, 6, 1)  # Saturday
        info = calculate_sla_deadline(request_date)
        assert info["sla_type"] == "standard"
        assert info["base_days"] == 30
        assert info["extension_days"] == 0
        assert info["total_days"] == 30
        assert info["status"] in {"on_track", "warning", "urgent"}

    @freeze_time("2024-06-01")
    def test_expedited_sla_10_days(self) -> None:
        request_date = datetime(2024, 6, 1)
        info = calculate_sla_deadline(request_date, sla_type=SLAType.EXPEDITED)
        assert info["base_days"] == 10

    @freeze_time("2024-06-01")
    def test_with_extensions(self) -> None:
        request_date = datetime(2024, 6, 1)
        info = calculate_sla_deadline(request_date, sla_type=SLAType.STANDARD, extensions=[15, 5])
        assert info["extension_days"] == 20
        assert info["total_days"] == 50

    @freeze_time("2024-06-01")
    def test_extended_sla_60_days(self) -> None:
        info = calculate_sla_deadline(datetime(2024, 6, 1), sla_type=SLAType.EXTENDED)
        assert info["base_days"] == 60

    @freeze_time("2025-01-01")
    def test_overdue_flags_when_request_far_in_past(self) -> None:
        info = calculate_sla_deadline(datetime(2023, 6, 1))
        assert info["is_overdue"] is True
        assert info["requires_attention"] is True
        assert info["status"] == "overdue"


# ---------------------------------------------------------------------------
# get_deadline_color
# ---------------------------------------------------------------------------


class TestGetDeadlineColor:
    @pytest.mark.parametrize(
        "status,color",
        [
            (DeadlineStatus.ON_TRACK, "#28a745"),
            (DeadlineStatus.WARNING, "#ffc107"),
            (DeadlineStatus.URGENT, "#fd7e14"),
            (DeadlineStatus.OVERDUE, "#dc3545"),
        ],
    )
    def test_known_status_returns_expected_color(self, status: DeadlineStatus, color: str) -> None:
        assert get_deadline_color(status) == color

    def test_unknown_status_returns_gray(self) -> None:
        # "unknown" not in the dict -> fallback
        assert get_deadline_color("not-a-status") == "#6c757d"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# should_send_notification
# ---------------------------------------------------------------------------


class TestShouldSendNotification:
    @freeze_time("2024-06-01 12:00:00")
    def test_overdue_sends_when_no_prior_notification(self) -> None:
        assert should_send_notification({"status": DeadlineStatus.OVERDUE.value}) is True

    @freeze_time("2024-06-01 12:00:00")
    def test_overdue_skips_if_notified_within_1_day(self) -> None:
        recent = datetime(2024, 6, 1, 0, 0, 0)
        assert (
            should_send_notification(
                {"status": DeadlineStatus.OVERDUE.value},
                last_notification=recent,
            )
            is False
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_overdue_sends_if_notified_2_days_ago(self) -> None:
        two_days_ago = datetime(2024, 5, 30, 12, 0)
        assert (
            should_send_notification(
                {"status": DeadlineStatus.OVERDUE.value},
                last_notification=two_days_ago,
            )
            is True
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_urgent_skips_within_2_days(self) -> None:
        last = datetime(2024, 5, 31, 12, 0)  # 1 day ago
        assert (
            should_send_notification(
                {"status": DeadlineStatus.URGENT.value}, last_notification=last
            )
            is False
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_urgent_sends_after_2_days(self) -> None:
        last = datetime(2024, 5, 28, 12, 0)  # 4 days ago
        assert (
            should_send_notification(
                {"status": DeadlineStatus.URGENT.value}, last_notification=last
            )
            is True
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_urgent_sends_when_no_prior_notification(self) -> None:
        assert should_send_notification({"status": DeadlineStatus.URGENT.value}) is True

    @freeze_time("2024-06-01 12:00:00")
    def test_warning_skips_within_7_days(self) -> None:
        last = datetime(2024, 5, 28, 12, 0)  # 4 days ago
        assert (
            should_send_notification(
                {"status": DeadlineStatus.WARNING.value}, last_notification=last
            )
            is False
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_warning_sends_after_7_days(self) -> None:
        last = datetime(2024, 5, 20, 12, 0)  # 12 days ago
        assert (
            should_send_notification(
                {"status": DeadlineStatus.WARNING.value}, last_notification=last
            )
            is True
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_warning_sends_when_no_prior_notification(self) -> None:
        assert should_send_notification({"status": DeadlineStatus.WARNING.value}) is True

    def test_on_track_never_notifies(self) -> None:
        assert should_send_notification({"status": DeadlineStatus.ON_TRACK.value}) is False


# ---------------------------------------------------------------------------
# generate_deadline_summary
# ---------------------------------------------------------------------------


class TestGenerateDeadlineSummary:
    def test_empty_list_has_100_percent_compliance(self) -> None:
        summary = generate_deadline_summary([])
        assert summary["total_cases"] == 0
        assert summary["compliance_rate"] == 100.0
        assert summary["at_risk_rate"] == 0.0

    def test_mixed_statuses(self) -> None:
        cases = [
            {"deadline_info": {"status": "on_track"}},
            {"deadline_info": {"status": "on_track"}},
            {"deadline_info": {"status": "warning"}},
            {"deadline_info": {"status": "urgent"}},
            {"deadline_info": {"status": "overdue"}},
        ]
        s = generate_deadline_summary(cases)
        assert s["total_cases"] == 5
        assert s["on_track"] == 2
        assert s["warning"] == 1
        assert s["urgent"] == 1
        assert s["overdue"] == 1
        assert s["requires_attention"] == 3
        assert s["compliance_rate"] == 40.0
        assert s["at_risk_rate"] == 60.0

    def test_missing_deadline_info_defaults_to_on_track(self) -> None:
        cases = [{}, {"deadline_info": {}}]
        s = generate_deadline_summary(cases)
        assert s["on_track"] == 2


# ---------------------------------------------------------------------------
# request_extension
# ---------------------------------------------------------------------------


class TestRequestExtension:
    @freeze_time("2024-06-01 12:00:00")
    def test_creates_extension_record_with_new_deadline(self) -> None:
        current = datetime(2024, 7, 1)  # Monday
        result = request_extension(current, extension_days=5, reason="Need more time")
        assert result["original_deadline"] == current
        # +5 business days from Monday Jul 1 = Mon Jul 8
        assert result["new_deadline"] == datetime(2024, 7, 8)
        assert result["extension_days"] == 5
        assert result["reason"] == "Need more time"
        assert result["status"] == "pending"
