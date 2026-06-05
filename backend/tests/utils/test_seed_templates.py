"""Tests for ``src.utils.seed_templates``.

Seeds default templates into the templates collection. Most of the
module is template-data constants (MESSAGE_TEMPLATES, STATUS_UPDATE_TEMPLATES,
FOI_RESPONSE_TEMPLATES); the testable surface is:
- ``generate_template_id`` (UUID4)
- ``get_all_default_templates`` (fresh IDs + timestamps every call)
- ``seed_default_templates`` async (insert if missing, skip if exists,
   error-count surface)
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.utils.seed_templates import (
    FOI_RESPONSE_TEMPLATES,
    MESSAGE_TEMPLATES,
    STATUS_UPDATE_TEMPLATES,
    generate_template_id,
    get_all_default_templates,
    seed_default_templates,
)

# ---------------------------------------------------------------------------
# generate_template_id
# ---------------------------------------------------------------------------


class TestGenerateTemplateId:
    def test_returns_uuid_string(self) -> None:
        tid = generate_template_id()
        assert isinstance(tid, str)
        # UUID4 has 4 hyphens
        assert tid.count("-") == 4
        # 36 chars: 32 hex + 4 hyphens
        assert len(tid) == 36

    def test_unique_per_call(self) -> None:
        ids = {generate_template_id() for _ in range(10)}
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# get_all_default_templates
# ---------------------------------------------------------------------------


class TestGetAllDefaultTemplates:
    def test_returns_combined_count(self) -> None:
        templates = get_all_default_templates()
        expected = (
            len(MESSAGE_TEMPLATES) + len(STATUS_UPDATE_TEMPLATES) + len(FOI_RESPONSE_TEMPLATES)
        )
        assert len(templates) == expected

    def test_every_template_has_id_and_timestamps(self) -> None:
        for t in get_all_default_templates():
            assert "id" in t
            assert isinstance(t["created_at"], datetime)
            assert isinstance(t["updated_at"], datetime)

    def test_ids_fresh_per_call(self) -> None:
        first = {t["id"] for t in get_all_default_templates()}
        second = {t["id"] for t in get_all_default_templates()}
        # No overlap — fresh UUIDs each call
        assert first.isdisjoint(second)

    def test_message_templates_categorized_correctly(self) -> None:
        all_templates = get_all_default_templates()
        message_count = sum(1 for t in all_templates if t.get("category") == "message")
        assert message_count == len(MESSAGE_TEMPLATES)

    def test_templates_carry_required_fields(self) -> None:
        for t in get_all_default_templates():
            # All seed templates must have name, content, type
            assert "name" in t
            assert "content" in t
            assert "type" in t


class TestMessageTemplateData:
    """Pin shape of MESSAGE_TEMPLATES constants — these are part of the
    onboarding flow per Phase 1 setup.sh expectations."""

    def test_all_active_by_default(self) -> None:
        for t in MESSAGE_TEMPLATES:
            assert t["is_active"] is True

    def test_all_marked_as_default(self) -> None:
        for t in MESSAGE_TEMPLATES:
            assert t["is_default"] is True

    def test_all_created_by_system(self) -> None:
        for t in MESSAGE_TEMPLATES:
            assert t["created_by"] == "system"


# ---------------------------------------------------------------------------
# seed_default_templates (async)
# ---------------------------------------------------------------------------


class TestSeedDefaultTemplates:
    @pytest.mark.asyncio
    async def test_inserts_every_template_when_empty(self, capsys) -> None:
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)
        coll.insert_one = AsyncMock()

        result = await seed_default_templates(coll)

        expected_total = (
            len(MESSAGE_TEMPLATES) + len(STATUS_UPDATE_TEMPLATES) + len(FOI_RESPONSE_TEMPLATES)
        )
        assert result["total"] == expected_total
        assert result["inserted"] == expected_total
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert coll.insert_one.await_count == expected_total

    @pytest.mark.asyncio
    async def test_skips_templates_that_already_exist(self) -> None:
        coll = MagicMock()
        # Always return an existing template
        coll.find_one = AsyncMock(return_value={"name": "existing"})
        coll.insert_one = AsyncMock()

        result = await seed_default_templates(coll)

        expected = (
            len(MESSAGE_TEMPLATES) + len(STATUS_UPDATE_TEMPLATES) + len(FOI_RESPONSE_TEMPLATES)
        )
        assert result["skipped"] == expected
        assert result["inserted"] == 0
        coll.insert_one.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_records_errors_when_insert_raises(self) -> None:
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)
        coll.insert_one = AsyncMock(side_effect=RuntimeError("db down"))

        result = await seed_default_templates(coll)
        expected_total = (
            len(MESSAGE_TEMPLATES) + len(STATUS_UPDATE_TEMPLATES) + len(FOI_RESPONSE_TEMPLATES)
        )
        assert result["errors"] == expected_total
        assert result["inserted"] == 0

    @pytest.mark.asyncio
    async def test_mixed_results_counted_correctly(self) -> None:
        """Half the templates exist, the rest get inserted."""
        coll = MagicMock()
        # Alternate: return None then {} then None...
        call_count = {"n": 0}

        async def fake_find_one(query):  # type: ignore[no-untyped-def]
            call_count["n"] += 1
            if call_count["n"] % 2 == 0:
                return {"name": "exists"}
            return None

        coll.find_one = AsyncMock(side_effect=fake_find_one)
        coll.insert_one = AsyncMock()

        result = await seed_default_templates(coll)
        total = len(MESSAGE_TEMPLATES) + len(STATUS_UPDATE_TEMPLATES) + len(FOI_RESPONSE_TEMPLATES)
        # Half inserted, half skipped (rounding depends on parity)
        assert result["inserted"] + result["skipped"] == total
        assert result["errors"] == 0
