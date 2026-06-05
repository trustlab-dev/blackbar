"""
Deadline and SLA Tracking System
Monitors case deadlines and SLA compliance
"""

import logging
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class DeadlineStatus(str, Enum):
    """Deadline status categories"""

    ON_TRACK = "on_track"
    WARNING = "warning"  # Within 7 days
    URGENT = "urgent"  # Within 3 days
    OVERDUE = "overdue"


class SLAType(str, Enum):
    """SLA types for FOI requests"""

    STANDARD = "standard"  # 30 business days
    EXTENDED = "extended"  # With approved extension
    EXPEDITED = "expedited"  # Rush request


# SLA configurations (in business days)
SLA_CONFIGS = {SLAType.STANDARD: 30, SLAType.EXTENDED: 60, SLAType.EXPEDITED: 10}


def calculate_business_days(start_date: datetime, num_days: int) -> datetime:
    """
    Calculate a date that is num_days business days from start_date.
    Excludes weekends (Saturday and Sunday).

    Args:
        start_date: Starting date
        num_days: Number of business days to add

    Returns:
        End date (business days later)
    """
    current_date = start_date
    days_added = 0

    while days_added < num_days:
        current_date += timedelta(days=1)
        # Skip weekends (5 = Saturday, 6 = Sunday)
        if current_date.weekday() < 5:
            days_added += 1

    return current_date


def get_deadline_status(due_date: datetime, current_date: datetime = None) -> DeadlineStatus:
    """
    Determine the status of a deadline.

    Args:
        due_date: The deadline date
        current_date: Current date (defaults to now)

    Returns:
        DeadlineStatus enum
    """
    if current_date is None:
        current_date = datetime.utcnow()

    # Calculate days remaining
    days_remaining = (due_date - current_date).days

    if days_remaining < 0:
        return DeadlineStatus.OVERDUE
    elif days_remaining <= 3:
        return DeadlineStatus.URGENT
    elif days_remaining <= 7:
        return DeadlineStatus.WARNING
    else:
        return DeadlineStatus.ON_TRACK


def calculate_sla_deadline(
    request_date: datetime, sla_type: SLAType = SLAType.STANDARD, extensions: list[int] = None
) -> dict:
    """
    Calculate SLA deadline for a case.

    Args:
        request_date: Date request was received
        sla_type: Type of SLA to apply
        extensions: List of extension days granted

    Returns:
        Dict with deadline info
    """
    # Base SLA days
    base_days = SLA_CONFIGS[sla_type]

    # Add extensions
    extension_days = sum(extensions) if extensions else 0
    total_days = base_days + extension_days

    # Calculate deadline (business days)
    deadline = calculate_business_days(request_date, total_days)

    # Get current status
    status = get_deadline_status(deadline)

    # Calculate days remaining
    current_date = datetime.utcnow()
    days_remaining = (deadline - current_date).days

    # Calculate business days remaining
    business_days_remaining = calculate_business_days_between(current_date, deadline)

    return {
        "deadline": deadline,
        "status": status.value,
        "days_remaining": days_remaining,
        "business_days_remaining": business_days_remaining,
        "sla_type": sla_type.value,
        "base_days": base_days,
        "extension_days": extension_days,
        "total_days": total_days,
        "is_overdue": status == DeadlineStatus.OVERDUE,
        "requires_attention": status in [DeadlineStatus.URGENT, DeadlineStatus.OVERDUE],
    }


def calculate_business_days_between(start_date: datetime, end_date: datetime) -> int:
    """
    Calculate number of business days between two dates.

    Args:
        start_date: Start date
        end_date: End date

    Returns:
        Number of business days
    """
    if start_date > end_date:
        return 0

    current_date = start_date
    business_days = 0

    while current_date < end_date:
        if current_date.weekday() < 5:  # Monday = 0, Friday = 4
            business_days += 1
        current_date += timedelta(days=1)

    return business_days


def get_deadline_color(status: DeadlineStatus) -> str:
    """Get color code for deadline status."""
    colors = {
        DeadlineStatus.ON_TRACK: "#28a745",  # Green
        DeadlineStatus.WARNING: "#ffc107",  # Yellow
        DeadlineStatus.URGENT: "#fd7e14",  # Orange
        DeadlineStatus.OVERDUE: "#dc3545",  # Red
    }
    return colors.get(status, "#6c757d")


def should_send_notification(deadline_info: dict, last_notification: datetime = None) -> bool:
    """
    Determine if a notification should be sent.

    Args:
        deadline_info: Deadline information dict
        last_notification: When last notification was sent

    Returns:
        True if notification should be sent
    """
    status = deadline_info["status"]

    # Always notify if overdue
    if status == DeadlineStatus.OVERDUE.value:
        # Send daily if overdue
        if last_notification is None:
            return True
        days_since_notification = (datetime.utcnow() - last_notification).days
        return days_since_notification >= 1

    # Notify if urgent and no notification in last 2 days
    if status == DeadlineStatus.URGENT.value:
        if last_notification is None:
            return True
        days_since_notification = (datetime.utcnow() - last_notification).days
        return days_since_notification >= 2

    # Notify if warning and no notification in last week
    if status == DeadlineStatus.WARNING.value:
        if last_notification is None:
            return True
        days_since_notification = (datetime.utcnow() - last_notification).days
        return days_since_notification >= 7

    return False


def generate_deadline_summary(cases: list[dict]) -> dict:
    """
    Generate summary of deadline statuses across cases.

    Args:
        cases: List of cases with deadline info

    Returns:
        Summary statistics
    """
    summary = {
        "total_cases": len(cases),
        "on_track": 0,
        "warning": 0,
        "urgent": 0,
        "overdue": 0,
        "requires_attention": 0,
    }

    for case in cases:
        deadline_info = case.get("deadline_info", {})
        status = deadline_info.get("status", DeadlineStatus.ON_TRACK.value)

        if status == DeadlineStatus.ON_TRACK.value:
            summary["on_track"] += 1
        elif status == DeadlineStatus.WARNING.value:
            summary["warning"] += 1
            summary["requires_attention"] += 1
        elif status == DeadlineStatus.URGENT.value:
            summary["urgent"] += 1
            summary["requires_attention"] += 1
        elif status == DeadlineStatus.OVERDUE.value:
            summary["overdue"] += 1
            summary["requires_attention"] += 1

    # Calculate percentages
    if summary["total_cases"] > 0:
        summary["compliance_rate"] = (summary["on_track"] / summary["total_cases"]) * 100
        summary["at_risk_rate"] = (summary["requires_attention"] / summary["total_cases"]) * 100
    else:
        summary["compliance_rate"] = 100.0
        summary["at_risk_rate"] = 0.0

    return summary


def request_extension(current_deadline: datetime, extension_days: int, reason: str) -> dict:
    """
    Request an extension to a deadline.

    Args:
        current_deadline: Current deadline date
        extension_days: Number of days to extend
        reason: Reason for extension

    Returns:
        Extension information
    """
    new_deadline = calculate_business_days(current_deadline, extension_days)

    return {
        "original_deadline": current_deadline,
        "new_deadline": new_deadline,
        "extension_days": extension_days,
        "reason": reason,
        "requested_at": datetime.utcnow(),
        "status": "pending",  # Would need approval workflow
    }
