"""Tests for ``src.utils.redaction_records``: the single validated redaction
shape and the single release rule (DOC-02, DOC-07, DOC-13, DOC-23)."""

from __future__ import annotations

import pytest

from src.utils.redaction_records import (
    APPROVED,
    REJECTED,
    UNRESOLVED,
    RedactionValidationError,
    effective_status,
    ensure_redaction_ids,
    find_redaction,
    new_redaction_record,
    partition_redactions,
    validate_redaction,
)

LETTER = [(612.0, 792.0)]


class TestValidateRedaction:
    def test_valid_box(self) -> None:
        geom = validate_redaction({"page": 1, "x": 10, "y": 20, "width": 30, "height": 40}, LETTER)
        assert geom.as_fields() == {"page": 1, "x": 10.0, "y": 20.0, "width": 30.0, "height": 40.0}

    def test_small_edge_overshoot_is_tolerated(self) -> None:
        validate_redaction({"page": 1, "x": -0.5, "y": 0, "width": 613, "height": 10}, LETTER)

    @pytest.mark.parametrize(
        "data, match",
        [
            ({"page": 1, "x": 1, "y": 1, "width": 0, "height": 5}, "width"),
            ({"page": 1, "x": 1, "y": 1, "width": 5, "height": -1}, "height"),
            ({"page": 1, "x": float("nan"), "y": 1, "width": 5, "height": 5}, "x"),
            ({"page": 0, "x": 1, "y": 1, "width": 5, "height": 5}, "page"),
            ({"page": True, "x": 1, "y": 1, "width": 5, "height": 5}, "page"),
            ({"page": 2, "x": 1, "y": 1, "width": 5, "height": 5}, "does not exist"),
            ({"page": 1, "x": 1, "y": 790, "width": 5, "height": 5}, "outside page"),
            ({"page": 1, "coordinates": {"x": 1, "y": 1, "width": 5, "height": 5}}, "x"),
        ],
    )
    def test_invalid_boxes_raise(self, data: dict, match: str) -> None:
        with pytest.raises(RedactionValidationError, match=match):
            validate_redaction(data, LETTER)


class TestNewRedactionRecord:
    def test_record_has_stable_id_and_flat_geometry(self) -> None:
        geom = validate_redaction({"page": 1, "x": 1, "y": 2, "width": 3, "height": 4}, LETTER)
        rec = new_redaction_record(
            geom, status="approved", created_by="u1", source="manual", category="S22"
        )
        assert rec["id"] and rec["status"] == "approved" and rec["source"] == "manual"
        assert (rec["page"], rec["x"], rec["width"]) == (1, 1.0, 3.0)
        assert rec["category"] == "S22"
        other = new_redaction_record(geom, status="approved", created_by="u1", source="manual")
        assert other["id"] != rec["id"]


class TestReleaseRule:
    @pytest.mark.parametrize(
        "record, expected",
        [
            ({"status": "approved"}, APPROVED),
            ({"status": "accepted"}, APPROVED),
            ({"status": "rejected"}, REJECTED),
            ({"status": "proposed", "type": "proposed"}, UNRESOLVED),
            ({"status": "contested"}, UNRESOLVED),
            ({}, UNRESOLVED),
            # legacy: staff-drawn "pending" boxes were always applied
            ({"status": "pending", "created_by_role": "analyst"}, APPROVED),
            ({"status": "pending", "created_by_role": "user"}, UNRESOLVED),
            (
                {"status": "pending", "created_by_role": "analyst", "needs_coordinates": True},
                UNRESOLVED,
            ),
            ({"status": "pending", "bulk_operation": True}, UNRESOLVED),
        ],
    )
    def test_effective_status(self, record: dict, expected: str) -> None:
        assert effective_status(record) == expected

    def test_partition_drops_rejected_and_splits_unresolved(self) -> None:
        a = {"id": "a", "status": "approved"}
        r = {"id": "r", "status": "rejected"}
        p = {"id": "p", "status": "proposed"}
        to_apply, unresolved = partition_redactions([a, r, p])
        assert to_apply == [a]
        assert unresolved == [p]


class TestFindRedaction:
    def test_by_id(self) -> None:
        reds = [{"id": "x"}, {"id": "y"}]
        assert find_redaction(reds, "y") == (1, {"id": "y"})

    def test_index_fallback_only_for_legacy_records_without_id(self) -> None:
        reds = [{"id": "x"}, {"page": 1}]
        assert find_redaction(reds, "1") == (1, {"page": 1})
        # Record 0 has an id, so its index is not an accepted reference.
        assert find_redaction(reds, "0") is None
        assert find_redaction(reds, "7") is None
        assert find_redaction(reds, "-1") is None

    def test_ensure_ids(self) -> None:
        reds = [{"id": "x"}, {"page": 1}]
        assert ensure_redaction_ids(reds) is True
        assert all(r.get("id") for r in reds)
        assert ensure_redaction_ids(reds) is False
