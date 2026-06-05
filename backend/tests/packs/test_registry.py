"""Unit tests for `src.packs.registry` (pack catalog / search helpers).

Phase 2.8 Batch A. Target >=80% line coverage on `src/packs/registry.py`.

Surface covered:
- `PackRegistry.list_packs()` enumerates everything `PackLoader.get_all_packs()`
  returns and shapes each entry into a summary dict (name, version,
  description, jurisdiction sub-fields, author, timestamps, counts, feature
  flags). Returns sorted by name.
- `PackRegistry.get_pack_summary(pack_id)` returns a rich summary (full
  jurisdiction, terminology, timelines, features, counts, branding) or
  None when load fails.
- `PackRegistry.search_packs(query)` filters list_packs() by case-insensitive
  substring against name, description, country, region, legislation_short.
- `PackRegistry.get_packs_by_country(country_code)` filters by uppercased
  country code.
- Module-level `list_available_packs()` is a thin alias for `list_packs()`.

Reality pins:
- list_packs() reads from `PackLoader.get_all_packs()` which is filesystem-
  backed; tests stub that method to keep the unit tests pure.
- Defaults: missing `name` -> "Unknown", missing version -> "0.0.0",
  missing author -> "Unknown".
- list_packs sort key is `x['name']` — case-sensitive (so "alpha" sorts
  before "Zed" alphabetically when case differs).
- search_packs() reads `pack['description']` via `.get(...)` defaulting to
  empty string, but reads `pack['name']` and `pack['jurisdiction']` as
  required keys (built-in to the list_packs shape, never missing).
- get_packs_by_country uppercases the input AND the stored country before
  comparing.
"""

from __future__ import annotations

from typing import Any

import pytest

import src.packs.registry as registry_mod
from src.packs.registry import PackRegistry, list_available_packs

# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------


def _make_pack(pack_id: str, **overrides: Any) -> dict:
    base = {
        "pack_id": pack_id,
        "name": f"Pack {pack_id}",
        "version": "1.0.0",
        "description": "A test pack",
        "jurisdiction": {
            "country": "CA",
            "region": "BC",
            "legislation": "FIPPA",
            "legislation_short": "FIPPA",
        },
        "author": "Tests",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "redaction_categories": [{"id": "c1"}, {"id": "c2"}],
        "statuses": [{"value": "open"}],
        "priorities": [{"value": "normal"}],
        "templates": {"ack": "Hi"},
        "ai_prompts": {"summarize": "Sum"},
        "terminology": {"requester": "applicant"},
        "timelines": {"default_response_days": 30},
        "features": {"public_portal": True},
        "branding": {"primary_color": "#000"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def stub_loader(monkeypatch: pytest.MonkeyPatch):
    """Stub PackLoader.get_all_packs / load_pack to operate on an in-memory
    dict — keeps registry tests independent of filesystem state."""
    store: dict[str, dict] = {}

    def _get_all_packs() -> dict[str, dict]:
        return store

    def _load_pack(pack_id: str) -> dict | None:
        return store.get(pack_id)

    monkeypatch.setattr(registry_mod.PackLoader, "get_all_packs", staticmethod(_get_all_packs))
    monkeypatch.setattr(registry_mod.PackLoader, "load_pack", staticmethod(_load_pack))
    return store


# ---------------------------------------------------------------------------
# PackRegistry.list_packs
# ---------------------------------------------------------------------------


class TestListPacks:
    def test_empty_when_no_packs(self, stub_loader) -> None:
        assert PackRegistry.list_packs() == []

    def test_single_pack_shape(self, stub_loader) -> None:
        stub_loader["alpha"] = _make_pack("alpha")
        result = PackRegistry.list_packs()
        assert len(result) == 1
        item = result[0]
        assert item["pack_id"] == "alpha"
        assert item["name"] == "Pack alpha"
        assert item["version"] == "1.0.0"
        assert item["jurisdiction"]["country"] == "CA"
        assert item["jurisdiction"]["region"] == "BC"
        assert item["jurisdiction"]["legislation_short"] == "FIPPA"
        assert item["category_count"] == 2
        assert item["status_count"] == 1
        assert item["has_templates"] is True
        assert item["has_ai_prompts"] is True

    def test_uses_defaults_for_missing_optional_fields(self, stub_loader) -> None:
        stub_loader["bare"] = {
            "pack_id": "bare",
            "jurisdiction": {},
            # everything else missing
        }
        result = PackRegistry.list_packs()
        assert len(result) == 1
        item = result[0]
        assert item["name"] == "Unknown"
        assert item["version"] == "0.0.0"
        assert item["author"] == "Unknown"
        assert item["category_count"] == 0
        assert item["status_count"] == 0
        assert item["has_templates"] is False
        assert item["has_ai_prompts"] is False

    def test_sorted_by_name(self, stub_loader) -> None:
        stub_loader["a"] = _make_pack("a", name="Zebra")
        stub_loader["b"] = _make_pack("b", name="Alpha")
        stub_loader["c"] = _make_pack("c", name="Mango")
        names = [p["name"] for p in PackRegistry.list_packs()]
        assert names == ["Alpha", "Mango", "Zebra"]


# ---------------------------------------------------------------------------
# PackRegistry.get_pack_summary
# ---------------------------------------------------------------------------


class TestGetPackSummary:
    def test_returns_none_when_not_found(self, stub_loader) -> None:
        assert PackRegistry.get_pack_summary("missing") is None

    def test_full_summary_shape(self, stub_loader) -> None:
        stub_loader["alpha"] = _make_pack("alpha")
        summary = PackRegistry.get_pack_summary("alpha")
        assert summary is not None
        assert summary["pack_id"] == "alpha"
        assert summary["name"] == "Pack alpha"
        assert summary["jurisdiction"]["country"] == "CA"
        assert summary["terminology"]["requester"] == "applicant"
        assert summary["timelines"]["default_response_days"] == 30
        assert summary["features"]["public_portal"] is True
        assert summary["category_count"] == 2
        assert summary["status_count"] == 1
        assert summary["priority_count"] == 1
        assert summary["template_count"] == 1
        assert summary["has_ai_prompts"] is True
        assert summary["branding"]["primary_color"] == "#000"

    def test_defaults_when_optional_fields_missing(self, stub_loader) -> None:
        stub_loader["min"] = {"pack_id": "min"}
        summary = PackRegistry.get_pack_summary("min")
        assert summary is not None
        assert summary["name"] == "Unknown"
        assert summary["version"] == "0.0.0"
        assert summary["author"] == "Unknown"
        assert summary["terminology"] == {}
        assert summary["timelines"] == {}
        assert summary["features"] == {}
        assert summary["category_count"] == 0
        assert summary["has_ai_prompts"] is False
        assert summary["branding"] == {}


# ---------------------------------------------------------------------------
# PackRegistry.search_packs
# ---------------------------------------------------------------------------


class TestSearchPacks:
    @pytest.fixture(autouse=True)
    def _populate(self, stub_loader) -> None:
        stub_loader["bc"] = _make_pack(
            "bc",
            name="BC FIPPA",
            description="Privacy regs",
            jurisdiction={
                "country": "CA",
                "region": "BC",
                "legislation_short": "FIPPA",
            },
        )
        stub_loader["ny"] = _make_pack(
            "ny",
            name="NY FOIL",
            description="New York records",
            jurisdiction={
                "country": "US",
                "region": "NY",
                "legislation_short": "FOIL",
            },
        )

    def test_search_matches_name_case_insensitive(self) -> None:
        results = PackRegistry.search_packs("fippa")
        assert len(results) == 1
        assert results[0]["pack_id"] == "bc"

    def test_search_matches_description(self) -> None:
        results = PackRegistry.search_packs("New York")
        assert len(results) == 1
        assert results[0]["pack_id"] == "ny"

    def test_search_matches_country(self) -> None:
        results = PackRegistry.search_packs("us")
        assert len(results) == 1
        assert results[0]["pack_id"] == "ny"

    def test_search_matches_region(self) -> None:
        results = PackRegistry.search_packs("bc")
        # pack_id "bc" matches via region; "ny" doesn't
        assert any(p["pack_id"] == "bc" for p in results)

    def test_search_matches_legislation_short(self) -> None:
        results = PackRegistry.search_packs("FOIL")
        assert len(results) == 1
        assert results[0]["pack_id"] == "ny"

    def test_search_no_matches(self) -> None:
        results = PackRegistry.search_packs("zzz-nope")
        assert results == []


# ---------------------------------------------------------------------------
# PackRegistry.get_packs_by_country
# ---------------------------------------------------------------------------


class TestGetPacksByCountry:
    @pytest.fixture(autouse=True)
    def _populate(self, stub_loader) -> None:
        stub_loader["ca1"] = _make_pack("ca1", jurisdiction={"country": "ca"})
        stub_loader["ca2"] = _make_pack("ca2", jurisdiction={"country": "CA"})
        stub_loader["us1"] = _make_pack("us1", jurisdiction={"country": "US"})

    def test_uppercase_match(self) -> None:
        results = PackRegistry.get_packs_by_country("CA")
        ids = {p["pack_id"] for p in results}
        assert ids == {"ca1", "ca2"}

    def test_lowercase_input_upcased(self) -> None:
        # Input is lowercased; stored country is also upcased before compare
        results = PackRegistry.get_packs_by_country("us")
        assert len(results) == 1
        assert results[0]["pack_id"] == "us1"

    def test_no_match(self) -> None:
        assert PackRegistry.get_packs_by_country("ZZ") == []


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


class TestListAvailablePacks:
    def test_delegates_to_list_packs(self, stub_loader) -> None:
        stub_loader["x"] = _make_pack("x", name="X")
        assert [p["pack_id"] for p in list_available_packs()] == ["x"]
