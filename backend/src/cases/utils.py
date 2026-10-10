"""Utility functions for case management"""

import secrets
from datetime import datetime, timedelta

from src.packs.loader import get_pack_terminology, get_pack_timelines

# The suffix is the only unguessable part of a tracking number, which is the
# sole credential for the anonymous /cases/public/track lookup (AUTH-05).
# 32 symbols (no 0/O/1/I) x 8 characters = 40 bits from a CSPRNG.
TRACKING_SUFFIX_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TRACKING_SUFFIX_LENGTH = 8


def generate_tracking_number(year: int = None, sequence: int = None) -> str:
    """
    Generate a tracking number using format from active pack
    Format: {prefix}-YYYY-###-XXXXXXXX where the suffix is random (secrets)
    """
    # Get terminology from pack
    terminology = get_pack_terminology()
    prefix = terminology.get("tracking_number_prefix", "FOI")

    suffix = "".join(
        secrets.choice(TRACKING_SUFFIX_ALPHABET) for _ in range(TRACKING_SUFFIX_LENGTH)
    )

    return f"{prefix}-{year}-{sequence:03d}-{suffix}"


def calculate_due_date(received_date: datetime, days: int = None) -> datetime:
    """
    Calculate due date based on received date.
    Uses default_response_days from active pack if days not specified.
    """
    if days is None:
        # Get default from pack
        timelines = get_pack_timelines()
        days = timelines.get("default_response_days", 30)

    return received_date + timedelta(days=days)


def get_days_until_due(due_date: datetime) -> int:
    """Calculate days until due date (negative if overdue)"""
    delta = due_date - datetime.utcnow()
    return delta.days


def is_overdue(due_date: datetime) -> bool:
    """Check if case is overdue"""
    return datetime.utcnow() > due_date


def get_sla_status(due_date: datetime) -> str:
    """
    Get SLA status based on due date.
    Returns: "overdue", "due_soon" (< 7 days), or "on_track"
    """
    days_until_due = get_days_until_due(due_date)

    if days_until_due < 0:
        return "overdue"
    elif days_until_due <= 7:
        return "due_soon"
    else:
        return "on_track"
