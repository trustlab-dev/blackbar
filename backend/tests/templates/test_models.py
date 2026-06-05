"""Unit tests for `src.templates.models` Pydantic models.

Phase 2.8 Batch B. Target >=80% line coverage on `src/templates/models.py`.

Surface covered:
- `TemplateCreate`: `name` and `content` required; `description` optional;
  `category` defaults to "general"; `is_active` defaults to True.
- `TemplateUpdate`: all fields Optional.
- `TemplateResponse`: full response shape requires id, name, content,
  category, is_active, created_at, updated_at, created_by; description
  is Optional. Has `from_attributes = True` for ORM-friendly conversion.

Reality pins:
- Pydantic V2 ValidationError raised on missing required fields.
- `TemplateCreate(name=..., content=...)` is the minimal valid instance.
- `is_active=False` is preserved (no truthy coercion).
- `model_dump()` shape matches the field declarations.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.templates.models import (
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
)

# ---------------------------------------------------------------------------
# TemplateCreate
# ---------------------------------------------------------------------------


class TestTemplateCreate:
    def test_minimal_valid_instance(self) -> None:
        t = TemplateCreate(name="Ack", content="Hello")
        assert t.name == "Ack"
        assert t.content == "Hello"
        assert t.description is None
        assert t.category == "general"
        assert t.is_active is True

    def test_all_fields(self) -> None:
        t = TemplateCreate(
            name="X",
            description="desc",
            content="body",
            category="response_letter",
            is_active=False,
        )
        assert t.description == "desc"
        assert t.category == "response_letter"
        assert t.is_active is False

    def test_name_required(self) -> None:
        with pytest.raises(ValidationError) as exc:
            TemplateCreate(content="x")
        assert "name" in str(exc.value)

    def test_content_required(self) -> None:
        with pytest.raises(ValidationError) as exc:
            TemplateCreate(name="x")
        assert "content" in str(exc.value)

    def test_dict_export(self) -> None:
        t = TemplateCreate(name="X", content="Y")
        d = t.model_dump()
        assert d == {
            "name": "X",
            "description": None,
            "content": "Y",
            "category": "general",
            "is_active": True,
        }


# ---------------------------------------------------------------------------
# TemplateUpdate
# ---------------------------------------------------------------------------


class TestTemplateUpdate:
    def test_empty_update_valid(self) -> None:
        # All fields Optional — empty payload validates
        u = TemplateUpdate()
        assert u.name is None
        assert u.content is None
        assert u.is_active is None

    def test_partial_update(self) -> None:
        u = TemplateUpdate(name="new")
        d = u.model_dump(exclude_unset=True)
        assert d == {"name": "new"}

    def test_explicit_false_preserved(self) -> None:
        u = TemplateUpdate(is_active=False)
        # is_active is set explicitly to False — not None
        d = u.model_dump(exclude_unset=True)
        assert d == {"is_active": False}


# ---------------------------------------------------------------------------
# TemplateResponse
# ---------------------------------------------------------------------------


class TestTemplateResponse:
    def _make_kwargs(self, **overrides) -> dict:
        base = {
            "id": "t-1",
            "name": "Ack",
            "description": None,
            "content": "Hi",
            "category": "general",
            "is_active": True,
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 2),
            "created_by": "user-1",
        }
        base.update(overrides)
        return base

    def test_full_instance(self) -> None:
        r = TemplateResponse(**self._make_kwargs())
        assert r.id == "t-1"
        assert r.is_active is True
        assert r.created_by == "user-1"

    def test_description_optional(self) -> None:
        # description is typed Optional[str] — None is allowed
        r = TemplateResponse(**self._make_kwargs(description=None))
        assert r.description is None

    @pytest.mark.parametrize(
        "missing",
        [
            "id",
            "name",
            "content",
            "category",
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
        ],
    )
    def test_required_fields(self, missing: str) -> None:
        kwargs = self._make_kwargs()
        kwargs.pop(missing)
        with pytest.raises(ValidationError) as exc:
            TemplateResponse(**kwargs)
        assert missing in str(exc.value)

    def test_from_attributes_config(self) -> None:
        """`from_attributes = True` lets the model accept ORM-style objects."""

        class Stub:
            id = "t-1"
            name = "X"
            description = None
            content = "Y"
            category = "general"
            is_active = True
            created_at = datetime(2026, 1, 1)
            updated_at = datetime(2026, 1, 2)
            created_by = "user-1"

        r = TemplateResponse.model_validate(Stub())
        assert r.id == "t-1"
        assert r.name == "X"
