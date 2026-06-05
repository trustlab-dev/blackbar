"""Unit tests for `src.packs.loader` (jurisdiction pack loading + caching).

Phase 2.8 Batch A. Target >=80% line coverage on `src/packs/loader.py`.

Surface covered:
- `PackLoader.get_packs_directory()` returns the configured directory.
- `PackLoader.load_pack(pack_id)` reads `<dir>/<pack_id>.json`, falls back to
  `<dir>/custom/<pack_id>.json`, returns `None` for unknown packs, missing
  `pack_id` field, or invalid JSON.
- Cache: a second `load_pack` call serves from the module-level `_pack_cache`.
- `PackLoader.load_pack_by_filename` mirrors `load_pack` but keys on filename.
- `PackLoader.get_all_packs()` scans the main directory AND `custom/`,
  populates the cache, ignores files without `pack_id`, ignores malformed
  JSON.
- `PackLoader.clear_cache()` resets the module-level cache.
- Module-level conveniences: `get_active_pack`, `set_active_pack`,
  `reload_packs`, and the six `get_pack_*` helpers (categories, statuses,
  priorities, timelines, templates, terminology, ai_prompts) — each returns
  the relevant slice from the active pack, or an empty list/dict when no
  pack is active.

Reality pins:
- The module captures `_packs_directory = Path(__file__).parent.parent.parent
  / "packs"` at import time. To isolate tests from the real on-disk packs,
  each test that touches the filesystem monkeypatches `_packs_directory`
  AND `_pack_cache` / `_active_pack` to a temp dir / empty state.
- `load_pack` swallows `json.JSONDecodeError` and bare `Exception`. Tests
  pin both branches.
- `get_active_pack()` lazy-loads `bc-fippa-v1` on first call if no active
  pack is set. The fallback `if not _active_pack:` branch immediately after
  is unreachable: the prior line already assigns the same result. Pinned
  with a coverage note.
- `set_active_pack` returns False when the pack can't be loaded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.packs.loader as loader_mod
from src.packs.loader import (
    PackLoader,
    get_active_pack,
    get_pack_ai_prompts,
    get_pack_categories,
    get_pack_priorities,
    get_pack_statuses,
    get_pack_templates,
    get_pack_terminology,
    get_pack_timelines,
    reload_packs,
    set_active_pack,
)

# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------


def _make_pack(pack_id: str = "test-pack-v1", **overrides) -> dict:
    """Minimal valid-ish pack dict."""
    base = {
        "pack_id": pack_id,
        "name": f"Test pack {pack_id}",
        "version": "1.0.0",
        "jurisdiction": {
            "country": "CA",
            "region": "BC",
            "legislation": "FIPPA",
        },
        "redaction_categories": [
            {"id": "s22", "code": "S.22", "name": "Privacy", "description": "x", "color": "#ff0000"}
        ],
        "statuses": [{"value": "open", "label": "Open", "color": "#00ff00"}],
        "priorities": [{"value": "normal", "label": "Normal"}],
        "timelines": {"default_response_days": 30},
        "templates": {"ack": "Hello"},
        "terminology": {"requester": "applicant"},
        "ai_prompts": {"summarize": "Summarize"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def fresh_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect `_packs_directory` to a tmp dir and zero the module caches.

    Each test gets a pristine packs directory and an empty cache/active-pack
    state. The fixture yields the tmp dir so tests can drop JSON files in.
    """
    monkeypatch.setattr(loader_mod, "_packs_directory", tmp_path)
    monkeypatch.setattr(loader_mod, "_pack_cache", {})
    monkeypatch.setattr(loader_mod, "_active_pack", None)
    return tmp_path


def _write_pack(directory: Path, filename: str, data: dict | str) -> Path:
    """Write a pack JSON (or raw string) into `directory`."""
    path = directory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# PackLoader.get_packs_directory
# ---------------------------------------------------------------------------


class TestGetPacksDirectory:
    def test_returns_module_level_path(self, fresh_loader: Path) -> None:
        assert PackLoader.get_packs_directory() == fresh_loader

    def test_default_directory_is_under_backend(self) -> None:
        """Sanity: the un-patched module path points inside the repo."""
        # We don't assert exact path because cwd-dependent, but it should be a
        # `Path` and end with `packs`.
        default = loader_mod._packs_directory
        assert isinstance(default, Path)
        assert default.name == "packs"


# ---------------------------------------------------------------------------
# PackLoader.load_pack
# ---------------------------------------------------------------------------


class TestLoadPack:
    def test_loads_from_main_directory(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "alpha.json", _make_pack(pack_id="alpha"))
        result = PackLoader.load_pack("alpha")
        assert result is not None
        assert result["pack_id"] == "alpha"

    def test_falls_back_to_custom_directory(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader / "custom", "beta.json", _make_pack(pack_id="beta"))
        result = PackLoader.load_pack("beta")
        assert result is not None
        assert result["pack_id"] == "beta"

    def test_returns_none_when_pack_not_found(self, fresh_loader: Path) -> None:
        assert PackLoader.load_pack("missing") is None

    def test_returns_none_when_pack_id_missing(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "noid.json", {"name": "no id here"})
        assert PackLoader.load_pack("noid") is None

    def test_returns_none_on_invalid_json(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "broken.json", "{not valid json")
        assert PackLoader.load_pack("broken") is None

    def test_returns_none_on_unexpected_exception(
        self, fresh_loader: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare `except Exception:` branch — make `open` raise OSError."""
        _write_pack(fresh_loader, "x.json", _make_pack(pack_id="x"))
        real_open = open

        def raising_open(path, *args, **kwargs):
            if str(path).endswith("x.json"):
                raise OSError("disk on fire")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", raising_open)
        assert PackLoader.load_pack("x") is None

    def test_caches_pack_after_first_load(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "cacheme.json", _make_pack(pack_id="cacheme"))
        first = PackLoader.load_pack("cacheme")
        # Delete the file on disk; second call should still succeed via cache.
        (fresh_loader / "cacheme.json").unlink()
        second = PackLoader.load_pack("cacheme")
        assert first == second
        assert second is not None

    def test_main_dir_takes_precedence_over_custom(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "dual.json", _make_pack(pack_id="dual", name="main"))
        _write_pack(fresh_loader / "custom", "dual.json", _make_pack(pack_id="dual", name="custom"))
        result = PackLoader.load_pack("dual")
        assert result is not None
        assert result["name"] == "main"


# ---------------------------------------------------------------------------
# PackLoader.load_pack_by_filename
# ---------------------------------------------------------------------------


class TestLoadPackByFilename:
    def test_loads_by_filename_from_main_dir(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "foo.json", _make_pack(pack_id="foo"))
        result = PackLoader.load_pack_by_filename("foo.json")
        assert result is not None
        assert result["pack_id"] == "foo"
        # Side-effect: caches by pack_id
        assert "foo" in loader_mod._pack_cache

    def test_loads_by_filename_from_custom_dir(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader / "custom", "bar.json", _make_pack(pack_id="bar"))
        result = PackLoader.load_pack_by_filename("bar.json")
        assert result is not None
        assert result["pack_id"] == "bar"

    def test_returns_none_when_filename_not_found(self, fresh_loader: Path) -> None:
        assert PackLoader.load_pack_by_filename("nope.json") is None

    def test_returns_none_on_exception(
        self, fresh_loader: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_pack(fresh_loader, "boom.json", _make_pack(pack_id="boom"))
        real_open = open

        def raising_open(path, *args, **kwargs):
            if str(path).endswith("boom.json"):
                raise OSError("nope")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", raising_open)
        assert PackLoader.load_pack_by_filename("boom.json") is None

    def test_pack_without_pack_id_field_is_not_cached(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "anon.json", {"name": "anonymous"})
        result = PackLoader.load_pack_by_filename("anon.json")
        # Returns the raw data but skips cache write
        assert result == {"name": "anonymous"}


# ---------------------------------------------------------------------------
# PackLoader.get_all_packs
# ---------------------------------------------------------------------------


class TestGetAllPacks:
    def test_returns_empty_when_directory_missing(
        self, fresh_loader: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point at a non-existent path
        monkeypatch.setattr(loader_mod, "_packs_directory", fresh_loader / "ghost")
        assert PackLoader.get_all_packs() == {}

    def test_loads_all_packs_from_main_dir(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "a.json", _make_pack(pack_id="a"))
        _write_pack(fresh_loader, "b.json", _make_pack(pack_id="b"))
        packs = PackLoader.get_all_packs()
        assert set(packs.keys()) == {"a", "b"}

    def test_loads_packs_from_both_main_and_custom(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "main.json", _make_pack(pack_id="main"))
        _write_pack(fresh_loader / "custom", "custom.json", _make_pack(pack_id="custom"))
        packs = PackLoader.get_all_packs()
        assert set(packs.keys()) == {"main", "custom"}

    def test_skips_pack_missing_pack_id(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "ok.json", _make_pack(pack_id="ok"))
        _write_pack(fresh_loader, "skip.json", {"name": "no id"})
        packs = PackLoader.get_all_packs()
        assert "ok" in packs
        assert "skip" not in packs

    def test_skips_invalid_json_in_main_dir(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "ok.json", _make_pack(pack_id="ok"))
        _write_pack(fresh_loader, "bad.json", "{not json")
        packs = PackLoader.get_all_packs()
        assert "ok" in packs
        assert len(packs) == 1

    def test_skips_invalid_json_in_custom_dir(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader / "custom", "bad.json", "{not json")
        _write_pack(fresh_loader / "custom", "ok.json", _make_pack(pack_id="ok"))
        packs = PackLoader.get_all_packs()
        assert "ok" in packs

    def test_populates_cache(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "p.json", _make_pack(pack_id="p"))
        PackLoader.get_all_packs()
        assert "p" in loader_mod._pack_cache


# ---------------------------------------------------------------------------
# PackLoader.clear_cache
# ---------------------------------------------------------------------------


class TestClearCache:
    def test_clears_cache(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "p.json", _make_pack(pack_id="p"))
        PackLoader.load_pack("p")
        assert loader_mod._pack_cache  # not empty
        PackLoader.clear_cache()
        assert loader_mod._pack_cache == {}


# ---------------------------------------------------------------------------
# Module-level: get_active_pack / set_active_pack / reload_packs
# ---------------------------------------------------------------------------


class TestActivePack:
    def test_get_active_pack_returns_set_pack(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "alpha.json", _make_pack(pack_id="alpha"))
        assert set_active_pack("alpha") is True
        pack = get_active_pack()
        assert pack is not None
        assert pack["pack_id"] == "alpha"

    def test_get_active_pack_lazy_loads_bc_fippa_when_none_set(self, fresh_loader: Path) -> None:
        """When `_active_pack` is None, get_active_pack tries to load
        `bc-fippa-v1` as the implicit default."""
        _write_pack(fresh_loader, "bc-fippa-v1.json", _make_pack(pack_id="bc-fippa-v1"))
        pack = get_active_pack()
        assert pack is not None
        assert pack["pack_id"] == "bc-fippa-v1"

    def test_get_active_pack_returns_none_when_default_missing(self, fresh_loader: Path) -> None:
        # No pack files on disk and _active_pack is None
        assert get_active_pack() is None

    def test_set_active_pack_returns_false_for_unknown(self, fresh_loader: Path) -> None:
        assert set_active_pack("does-not-exist") is False
        assert loader_mod._active_pack is None

    def test_set_active_pack_overwrites_previous(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "a.json", _make_pack(pack_id="a"))
        _write_pack(fresh_loader, "b.json", _make_pack(pack_id="b"))
        assert set_active_pack("a")
        assert set_active_pack("b")
        active = get_active_pack()
        assert active is not None
        assert active["pack_id"] == "b"


class TestReloadPacks:
    def test_reload_clears_cache_and_repopulates(self, fresh_loader: Path) -> None:
        _write_pack(fresh_loader, "p.json", _make_pack(pack_id="p"))
        PackLoader.load_pack("p")
        assert "p" in loader_mod._pack_cache
        # Add a new pack on disk, reload
        _write_pack(fresh_loader, "q.json", _make_pack(pack_id="q"))
        reload_packs()
        assert "p" in loader_mod._pack_cache
        assert "q" in loader_mod._pack_cache


# ---------------------------------------------------------------------------
# get_pack_* helpers (active-pack slices)
# ---------------------------------------------------------------------------


class TestPackHelpersWithActive:
    @pytest.fixture(autouse=True)
    def _seed(self, fresh_loader: Path) -> None:
        _write_pack(
            fresh_loader,
            "rich.json",
            _make_pack(pack_id="rich"),
        )
        set_active_pack("rich")

    def test_get_pack_categories(self) -> None:
        cats = get_pack_categories()
        assert isinstance(cats, list)
        assert cats[0]["code"] == "S.22"

    def test_get_pack_statuses(self) -> None:
        statuses = get_pack_statuses()
        assert statuses[0]["value"] == "open"

    def test_get_pack_priorities(self) -> None:
        priorities = get_pack_priorities()
        assert priorities[0]["value"] == "normal"

    def test_get_pack_timelines(self) -> None:
        timelines = get_pack_timelines()
        assert timelines["default_response_days"] == 30

    def test_get_pack_templates(self) -> None:
        templates = get_pack_templates()
        assert templates == {"ack": "Hello"}

    def test_get_pack_terminology(self) -> None:
        term = get_pack_terminology()
        assert term["requester"] == "applicant"

    def test_get_pack_ai_prompts(self) -> None:
        prompts = get_pack_ai_prompts()
        assert prompts == {"summarize": "Summarize"}


class TestPackHelpersNoActive:
    """When no active pack is set AND no default `bc-fippa-v1` on disk,
    every helper falls back to an empty container."""

    def test_get_pack_categories_returns_empty_list(self, fresh_loader: Path) -> None:
        assert get_pack_categories() == []

    def test_get_pack_statuses_returns_empty_list(self, fresh_loader: Path) -> None:
        assert get_pack_statuses() == []

    def test_get_pack_priorities_returns_empty_list(self, fresh_loader: Path) -> None:
        assert get_pack_priorities() == []

    def test_get_pack_timelines_returns_empty_dict(self, fresh_loader: Path) -> None:
        assert get_pack_timelines() == {}

    def test_get_pack_templates_returns_empty_dict(self, fresh_loader: Path) -> None:
        assert get_pack_templates() == {}

    def test_get_pack_terminology_returns_empty_dict(self, fresh_loader: Path) -> None:
        assert get_pack_terminology() == {}

    def test_get_pack_ai_prompts_returns_empty_dict(self, fresh_loader: Path) -> None:
        assert get_pack_ai_prompts() == {}
