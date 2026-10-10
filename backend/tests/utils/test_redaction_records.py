"""Tests for ``src.utils.redaction_records``: the single validated redaction
shape and the single release rule (DOC-02, DOC-07, DOC-13, DOC-23)."""

from __future__ import annotations

import pytest

from src.utils.redaction_records import (
    APPROVED,
    REJECTED,
    UNRESOLVED,
    RedactionValidationError,
    describe_unresolved,
    effective_status,
    ensure_redaction_ids,
    find_redaction,
    new_redaction_record,
    partition_redactions,
    review_state,
    unresolved_message,
    unresolved_summary,
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
            geom,
            status="approved",
            created_by="u1",
            source="manual",
            page_rotation=0,
            category="S22",
        )
        assert rec["id"] and rec["status"] == "approved" and rec["source"] == "manual"
        assert (rec["page"], rec["x"], rec["width"]) == (1, 1.0, 3.0)
        assert rec["category"] == "S22"
        other = new_redaction_record(
            geom, status="approved", created_by="u1", source="manual", page_rotation=0
        )
        assert other["id"] != rec["id"]

    @pytest.mark.parametrize("rotation, stored", [(0, 0), (90, 90), (-90, 270), (450, 90)])
    def test_record_carries_coordinate_space(self, rotation: int, stored: int) -> None:
        geom = validate_redaction({"page": 1, "x": 1, "y": 2, "width": 3, "height": 4}, LETTER)
        rec = new_redaction_record(
            geom, status="approved", created_by="u1", source="manual", page_rotation=rotation
        )
        assert rec["coord_space"] == "displayed"
        assert rec["page_rotation"] == stored


BOX = {"page": 1, "x": 10, "y": 10, "width": 20, "height": 10}


class TestReleaseRule:
    @pytest.mark.parametrize(
        "record, expected, reason",
        [
            ({"status": "approved"}, APPROVED, None),
            ({"status": "accepted"}, APPROVED, None),
            ({"status": "rejected"}, REJECTED, None),
            ({"status": "proposed", "type": "proposed"}, UNRESOLVED, "proposed"),
            ({"status": "pending", "type": "proposed"}, UNRESOLVED, "proposed"),
            ({"status": "contested"}, UNRESOLVED, "contested"),
            ({}, UNRESOLVED, "unknown_status"),
            # legacy: staff-drawn "pending" boxes were always applied
            ({"status": "pending", "created_by_role": "analyst"}, APPROVED, None),
            ({"status": "pending", "created_by_role": "user"}, UNRESOLVED, "legacy_pending"),
            ({"status": "pending"}, UNRESOLVED, "legacy_no_role"),
            (
                {"status": "pending", "created_by_role": "analyst", "needs_coordinates": True},
                UNRESOLVED,
                "legacy_pending",
            ),
            (
                {"status": "pending", "bulk_operation": True, "created_by_role": "admin"},
                UNRESOLVED,
                "legacy_pending",
            ),
        ],
    )
    def test_review_state(self, record: dict, expected: str, reason: str | None) -> None:
        record = {**BOX, **record}
        assert effective_status(record) == expected
        assert review_state(record) == (expected, reason)

    @pytest.mark.parametrize(
        "record",
        [
            {"status": "approved", "page": 1},
            {"status": "pending", "bulk_operation": True, "needs_coordinates": True, "page": 1},
            {"status": "approved", **BOX, "width": 0},
        ],
    )
    def test_record_without_geometry_is_unresolved_whatever_its_status(self, record: dict) -> None:
        assert review_state(record) == (UNRESOLVED, "no_geometry")
        described = describe_unresolved(record)
        assert described["reason"] == "no_geometry"
        assert described["approvable"] is False
        assert "delete" in described["message"].lower()

    def test_rejected_record_without_geometry_is_just_dropped(self) -> None:
        assert review_state({"status": "rejected"}) == (REJECTED, None)

    def test_partition_drops_rejected_and_splits_unresolved(self) -> None:
        a = {"id": "a", "status": "approved", **BOX}
        r = {"id": "r", "status": "rejected", **BOX}
        p = {"id": "p", "status": "proposed", **BOX}
        to_apply, unresolved = partition_redactions([a, r, p])
        assert to_apply == [a]
        assert unresolved == [p]


class TestLegacyCoordinateRule:
    """C1: records without a coordinate-space marker are only trusted on
    unrotated pages, where displayed and unrotated space coincide."""

    legacy = {"id": "l", "status": "approved", **BOX}
    marked = {"id": "m", "status": "approved", **BOX, "coord_space": "displayed"}

    def test_legacy_record_on_unrotated_page_is_applied(self) -> None:
        assert partition_redactions([self.legacy], [0]) == ([self.legacy], [])

    @pytest.mark.parametrize("rotation", [90, 180, 270])
    def test_legacy_record_on_rotated_page_is_held_back(self, rotation: int) -> None:
        to_apply, unresolved = partition_redactions([self.legacy, self.marked], [rotation])
        assert to_apply == [self.marked]
        assert unresolved == [self.legacy]
        (described,) = unresolved_summary(unresolved, [rotation])
        assert described["reason"] == "legacy_rotated_coordinates"
        assert described["approvable"] is True

    def test_without_rotations_the_rule_cannot_tell(self) -> None:
        assert partition_redactions([self.legacy]) == ([self.legacy], [])

    def test_unresolved_message_lists_ids_and_reasons(self) -> None:
        details = unresolved_summary([self.legacy, {"id": "p", "status": "proposed", **BOX}], [90])
        message = unresolved_message(details, "release")
        assert "2 redaction(s)" in message
        assert "l (page 1): legacy_rotated_coordinates" in message
        assert "p (page 1): proposed" in message


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
