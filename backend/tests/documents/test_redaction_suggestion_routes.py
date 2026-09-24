"""Integration tests for `src.documents.redaction_suggestion_routes`.

Phase 2.3.B (2/2). Target >=80% line coverage on
`src.documents.redaction_suggestion_routes` — the AI-driven redaction
suggestion endpoints (distinct from the manual workflow in
`redaction_routes.py`).

Endpoints under test (all mounted at `/api/v1/documents/...` via
`redaction_suggestion_router` included from `documents/routes.py`):

    GET    /{document_id}/redaction-suggestions       (cached / quick / AI full)
    POST   /bulk/preview-redaction
    POST   /bulk/apply-redaction
    POST   /bulk/create-template
    POST   /{document_id}/ai-feedback
    POST   /bulk/apply-ai-suggestions
    DELETE /{document_id}/redaction-suggestions/cache

**LLM mocking strategy:** all paths that would invoke the real LLM go
through `src.utils.ai_redaction.get_redaction_suggestions` →
`src.utils.llm_client.get_llm_client`. When `get_llm_client()` returns
None (the default test config — no LLM provider configured in db),
the helper returns an empty-suggestions dict with an error message.
We exercise both branches:
- The default "LLM not configured" branch (no mock needed; helper
  short-circuits and returns empty suggestions).
- A mocked happy path that monkeypatches `get_redaction_suggestions`
  directly in the route module to return a canned suggestions dict.

We DO NOT make real HTTP calls to OpenAI / Anthropic / Cohere.

**Module-level `db` capture:** the source has
`from ..database import db` at module top (line 16) AND a `Depends(get_db)`
parameter on some endpoints. The endpoints that bypass `Depends(get_db)`
(preview-redaction, apply-redaction, ai-feedback, clear-cache) read from
the module-level `db` directly. Tests must monkeypatch
`src.documents.redaction_suggestion_routes.db` so those endpoints hit
the per-test motor database instead of the production-default
`client["blackbar"]` instance.

Source-API findings pinned (audit Section 11 candidates):
- The `db` import is captured at module load time, so we must
  monkeypatch the attribute on the route module itself.
- `apply_bulk_redaction_endpoint` and `preview_bulk_redaction_endpoint`
  do NOT inject `db` via `Depends` — they reach for the module-level
  symbol. Inconsistent with the other endpoints; would be cleaner if
  all used `Depends(get_db)`.
- `record_ai_feedback` writes to `db["ai_feedback"]` (collection
  accessed via __getitem__ rather than attribute). Tests verify the
  collection accumulates feedback records.
- `apply_ai_suggestions_bulk_endpoint` line 489 uses module-level
  `db` for the audit-log write (`case = await db.cases.find_one(...)`)
  even though the same function has `db = Depends(get_db)` overriding
  the symbol in scope. The `Depends`-bound name shadows the
  module-level for `db.documents` reads, but the final
  `db.cases.find_one(...)` near the bottom uses the same shadowed
  name. Confirmed by tests passing with module-level patch only when
  bulk endpoints need it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case, make_document

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    """Rebind ALL routes' db touchpoints to the per-test motor db.

    Three patch surfaces:
    1. `app.dependency_overrides[redaction_suggestion_routes.get_db]` and
       `documents.routes.get_db` for endpoints that use Depends(get_db).
    2. `src.documents.redaction_suggestion_routes.db` — the module-level
       `db` capture used by preview/apply/ai-feedback/clear-cache
       endpoints (the ones that DON'T take db via Depends).
    3. `src.dependencies.users` so `get_current_user` lookups bind
       to the test db.
    """
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import redaction_suggestion_routes
    from src.documents import routes as documents_routes

    async def _override_get_db():
        return db

    app.dependency_overrides[redaction_suggestion_routes.get_db] = _override_get_db
    app.dependency_overrides[documents_routes.get_db] = _override_get_db
    monkeypatch.setattr(redaction_suggestion_routes, "db", db)
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)

    yield db

    app.dependency_overrides.pop(redaction_suggestion_routes.get_db, None)
    app.dependency_overrides.pop(documents_routes.get_db, None)


async def _seed_case(db: AsyncIOMotorDatabase, **overrides: Any) -> str:
    case = make_case(**overrides)
    await db.cases.insert_one(case)
    return case["id"]


COORDS = {"x": 72.0, "y": 90.0, "width": 40.0, "height": 14.0}


def _text_pdf(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 100), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


async def _seed_document(db: AsyncIOMotorDatabase, **overrides: Any) -> str:
    doc = make_document(**overrides)
    await db.documents.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# GET /{document_id}/redaction-suggestions
# ---------------------------------------------------------------------------


class TestGetRedactionSuggestions:
    async def test_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/redaction-suggestions")
        assert r.status_code == 404

    async def test_no_extracted_text_returns_no_text_status(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Document without `extracted_text` or `text_data.full_text`
        returns a no_text response (not a 404)."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, extracted_text=None)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "no_text"
        assert body["suggestions"] == []

    async def test_extracted_text_via_text_data_full_text(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When `extracted_text` is missing but `text_data.full_text`
        is present, the route should use it (covering the fallback
        branch)."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            text_data={"full_text": "fallback text here"},
        )
        # Quick mode skips the LLM call but exercises the text_data
        # fallback.
        from src.documents import redaction_suggestion_routes

        def _fake_quick(text: str):
            return [
                {
                    "text": "fallback",
                    "category": "personal_info",
                    "reason": "test",
                    "confidence": "high",
                }
            ]

        monkeypatch.setattr(redaction_suggestion_routes, "get_quick_pii_suggestions", _fake_quick)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?quick=true")
        assert r.status_code == 200
        body = r.json()
        assert body["method"] == "pattern_matching"
        assert body["status"] == "quick"

    async def test_quick_mode_pattern_matching(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """quick=True uses get_quick_pii_suggestions and skips LLM."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, extracted_text="John Doe lives at 123 Main")

        from src.documents import redaction_suggestion_routes

        def _fake_quick(text: str):
            return [{"text": "John", "category": "personal_info", "reason": "name"}]

        monkeypatch.setattr(redaction_suggestion_routes, "get_quick_pii_suggestions", _fake_quick)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?quick=true")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "quick"
        assert body["method"] == "pattern_matching"
        assert len(body["suggestions"]) == 1

    async def test_full_ai_path_with_mocked_helper(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Mock `get_redaction_suggestions` (the LLM-calling helper) to
        return a canned response. Verifies the full AI path including
        cache write and case-context lookup."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db, title="Test Case")
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            extracted_text="Some document text",
        )

        from src.documents import redaction_suggestion_routes

        async def _fake_ai(text, context=None):
            # LLM-17: the case title is not sent unless LLM_SEND_CASE_CONTEXT
            assert context is None
            return {
                "suggestions": [{"text": "Some", "category": "personal_info", "reason": "x"}],
                "summary": "synthetic summary",
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "analysis_truncated": True,
                "analysed_chars": 10,
                "total_chars": 20,
            }

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _fake_ai)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?generate=true")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ai_complete"
        assert body["method"] == "llm"
        assert body["analysis_truncated"] is True
        assert body["summary"] == "synthetic summary"

        # Verify cache was written, with provenance (LLM-16)
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["ai_suggestions"]["summary"] == "synthetic summary"
        assert doc["ai_suggestions"]["provider"] == "anthropic"
        assert doc["ai_suggestions"]["model"] == "claude-sonnet-5"
        assert doc["ai_suggestions"]["analysed_chars"] == 10

        # The cached response surfaces the truncation flag too.
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        assert r.json()["status"] == "cached"
        assert r.json()["analysis_truncated"] is True

    async def test_cached_suggestions_returned(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """When `ai_suggestions` is already populated, the cached
        version is returned without re-calling the LLM."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            ai_suggestions={
                "suggestions": [{"text": "cached", "category": "personal_info", "reason": "x"}],
                "summary": "from cache",
                "method": "openai_gpt4",
                "generated_at": datetime.utcnow().isoformat(),
            },
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "cached"
        assert body["summary"] == "from cache"

    async def test_cached_marks_rejected_suggestions(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Cached suggestions whose `text` appears in
        `rejected_ai_suggestions` should be flagged `rejected: True`."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            ai_suggestions={
                "suggestions": [
                    {"text": "john", "category": "personal_info"},
                    {"text": "jane", "category": "personal_info"},
                ],
                "summary": "x",
            },
            rejected_ai_suggestions=[{"text": "john"}],
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        body = r.json()
        flagged = {s["text"]: s.get("rejected", False) for s in body["suggestions"]}
        assert flagged["john"] is True
        assert flagged["jane"] is False

    async def test_force_regenerate_bypasses_cache(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`force_regenerate=true` should bypass cache and re-call the
        LLM helper."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            ai_suggestions={
                "suggestions": [{"text": "old", "category": "x", "reason": "y"}],
                "summary": "OLD",
            },
        )

        from src.documents import redaction_suggestion_routes

        async def _fake_ai(text, context=None):
            return {
                "suggestions": [{"text": "new", "category": "x", "reason": "y"}],
                "summary": "NEW",
            }

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _fake_ai)
        r = await client.get(
            f"/api/v1/documents/{doc_id}/redaction-suggestions" "?force_regenerate=true"
        )
        body = r.json()
        assert body["summary"] == "NEW"

    async def test_empty_cache_is_not_regenerated_on_view(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LLM-04: a cached zero-result analysis is returned as-is; viewing
        the document again does not re-send it to the LLM."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            ai_suggestions={"suggestions": [], "summary": "empty"},
        )

        from src.documents import redaction_suggestion_routes

        async def _explode(text, context=None):
            raise AssertionError("LLM must not be called for a cached empty result")

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _explode)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        body = r.json()
        assert body["status"] == "cached"
        assert body["suggestions"] == []
        assert body["summary"] == "empty"

    # -- Demo mode (BLACKBAR_DEMO_MODE=true) -----------------------------------
    # In demo mode there is no live LLM configured. The route must NEVER call
    # the LLM and must NEVER overwrite the curated `ai_suggestions` snapshot —
    # otherwise a visitor clicking "Regenerate" would wipe the demo for
    # everyone until the next nightly reset.

    async def test_demo_mode_ignores_force_regenerate_and_serves_snapshot(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With BLACKBAR_DEMO_MODE=true, force_regenerate is ignored: the
        seeded snapshot is returned and the LLM is never called nor the
        cache overwritten."""
        monkeypatch.setenv("BLACKBAR_DEMO_MODE", "true")
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            ai_suggestions={
                "suggestions": [{"text": "keep", "category": "personal_info", "reason": "x"}],
                "summary": "SNAPSHOT",
                "method": "openai_gpt4",
            },
        )

        from src.documents import redaction_suggestion_routes

        async def _explode(text, context=None):
            raise AssertionError("LLM must not be called in demo mode")

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _explode)
        r = await client.get(
            f"/api/v1/documents/{doc_id}/redaction-suggestions?force_regenerate=true"
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "cached"
        assert body["summary"] == "SNAPSHOT"

        # Snapshot must be untouched in the DB.
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["ai_suggestions"]["summary"] == "SNAPSHOT"

    async def test_demo_mode_no_cache_does_not_call_llm_or_write(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Demo mode + a document with no `ai_suggestions`: return empty
        without calling the LLM and without persisting an empty cache."""
        monkeypatch.setenv("BLACKBAR_DEMO_MODE", "true")
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, extracted_text="text")

        from src.documents import redaction_suggestion_routes

        async def _explode(text, context=None):
            raise AssertionError("LLM must not be called in demo mode")

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _explode)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "demo_no_suggestions"
        assert body["suggestions"] == []

        # No empty cache should have been written.
        doc = await db.documents.find_one({"id": doc_id})
        assert doc.get("ai_suggestions") is None

    async def test_demo_mode_empty_cache_does_not_regenerate(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Demo mode must NOT trigger the empty-cache auto-regenerate path
        (which would call the LLM and overwrite the snapshot)."""
        monkeypatch.setenv("BLACKBAR_DEMO_MODE", "true")
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            ai_suggestions={"suggestions": [], "summary": "empty"},
        )

        from src.documents import redaction_suggestion_routes

        async def _explode(text, context=None):
            raise AssertionError("LLM must not be called in demo mode")

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _explode)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "demo_no_suggestions"
        assert body["suggestions"] == []

        # Cache stays empty — not regenerated.
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["ai_suggestions"]["suggestions"] == []

    async def test_helper_exception_returns_500(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A raised exception inside the AI helper is converted to a 500."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, extracted_text="text")

        from src.documents import redaction_suggestion_routes

        async def _boom(text, context=None):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _boom)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?generate=true")
        assert r.status_code == 500
        # Generic message with a reference, never the raw exception text
        assert "LLM exploded" not in r.text
        assert "reference" in r.text

    async def test_full_ai_no_case_id(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Document with no `case_id` skips the case-context lookup
        and passes context=None to the LLM helper. Covers the
        `if doc.get('case_id')` False branch."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, extracted_text="text")  # No case_id
        # Remove case_id explicitly
        await db.documents.update_one({"id": doc_id}, {"$unset": {"case_id": ""}})

        from src.documents import redaction_suggestion_routes

        captured = {}

        async def _fake_ai(text, context=None):
            captured["context"] = context
            return {"suggestions": [], "summary": "ok"}

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _fake_ai)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?generate=true")
        assert r.status_code == 200
        assert captured["context"] is None

    async def test_full_ai_case_id_present_but_case_missing(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`case_id` set but case row missing: covers the `if case`
        False branch — context stays None."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, case_id="ghost-case", extracted_text="text")

        from src.documents import redaction_suggestion_routes

        captured = {}

        async def _fake_ai(text, context=None):
            captured["context"] = context
            return {"suggestions": [], "summary": "ok"}

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _fake_ai)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?generate=true")
        assert r.status_code == 200
        assert captured["context"] is None

    async def test_full_ai_enriches_when_pdf_content_present(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Document with `content` (raw PDF bytes) triggers the
        coordinate-enrichment call. Covers lines 146-147."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            content=b"%PDF-1.4 fake pdf",
        )

        from src.documents import redaction_suggestion_routes

        async def _fake_ai(text, context=None):
            return {"suggestions": [{"text": "x", "category": "y", "reason": "z"}], "summary": "ok"}

        enriched_calls = []

        def _fake_enrich(suggestions, pdf_content, text_data=None):
            enriched_calls.append(True)
            # Stamp enrichment so the assertion can see it
            for s in suggestions:
                s["enriched"] = True
            return suggestions

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _fake_ai)
        monkeypatch.setattr(
            redaction_suggestion_routes,
            "enrich_suggestions_with_coordinates",
            _fake_enrich,
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?generate=true")
        assert r.status_code == 200, r.text
        assert enriched_calls  # Was called

    async def test_quick_enrichment_when_pdf_content_present(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """quick=true + `content` triggers coordinate enrichment in the
        quick branch. Covers line 122."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db, extracted_text="text", content=b"%PDF-1.4 fake")

        from src.documents import redaction_suggestion_routes

        monkeypatch.setattr(
            redaction_suggestion_routes,
            "get_quick_pii_suggestions",
            lambda t: [{"text": "x"}],
        )

        called = []

        def _fake_enrich(suggestions, pdf_content, text_data=None):
            called.append(True)
            return suggestions

        monkeypatch.setattr(
            redaction_suggestion_routes,
            "enrich_suggestions_with_coordinates",
            _fake_enrich,
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?quick=true")
        assert r.status_code == 200
        assert called

    async def test_cached_skip_enrichment_when_coordinates_present(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cached path with `content` AND suggestions already carrying
        `coordinates`: needs_enrichment evaluates False, so enrich is
        NOT called. Only server-located suggestions (`has_coordinates`)
        count as located (LLM-06)."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            content=b"%PDF-1.4 fake",
            ai_suggestions={
                "suggestions": [
                    {
                        "text": "has-coords",
                        "category": "x",
                        "coordinates": {"x": 1, "y": 2},
                        "has_coordinates": True,
                    }
                ],
                "summary": "cached",
            },
        )

        from src.documents import redaction_suggestion_routes

        called = []

        def _fake_enrich(*args, **kwargs):
            called.append(True)
            return args[0]

        monkeypatch.setattr(
            redaction_suggestion_routes,
            "enrich_suggestions_with_coordinates",
            _fake_enrich,
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        assert r.status_code == 200
        assert not called  # Enrichment was skipped because coords present

    async def test_cached_enrichment_when_pdf_content_present(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cached path: when `content` is present and cached suggestions
        lack `coordinates`/`bbox`, the route enriches them. Covers
        lines 93-96."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            extracted_text="text",
            content=b"%PDF-1.4 fake",
            ai_suggestions={
                "suggestions": [{"text": "needs-coords", "category": "x"}],
                "summary": "cached",
            },
        )

        from src.documents import redaction_suggestion_routes

        called = []

        def _fake_enrich(suggestions, pdf_content, text_data=None):
            called.append(True)
            for s in suggestions:
                s["coordinates"] = {"x": 1, "y": 2}
            return suggestions

        monkeypatch.setattr(
            redaction_suggestion_routes,
            "enrich_suggestions_with_coordinates",
            _fake_enrich,
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "cached"
        assert called

    @pytest.mark.parametrize(
        "role,expected_status",
        [
            ("admin", 200),
            ("analyst", 200),
            ("user", 403),
            ("guest", 403),
        ],
    )
    async def test_role_gate(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        role: str,
        expected_status: int,
    ) -> None:
        """`check_role(['owner','admin','analyst'])` is the decorator
        gate. Test the four user roles against it."""
        client = await authed_client_factory(role=role)
        doc_id = await _seed_document(db, extracted_text="x")
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?quick=true")
        assert r.status_code == expected_status


# ---------------------------------------------------------------------------
# POST /bulk/preview-redaction
# ---------------------------------------------------------------------------


class TestPreviewBulkRedaction:
    async def test_preview_happy_path(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        await _seed_document(db, case_id=case_id, extracted_text="alice and bob")
        await _seed_document(db, case_id=case_id, extracted_text="alice was here")
        r = await client.post(
            "/api/v1/documents/bulk/preview-redaction",
            json={
                "case_id": case_id,
                "search_text": "alice",
                "category": "S22",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["documents_affected"] == 2
        assert body["total_occurrences"] == 2

    async def test_preview_short_search_text_400(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/bulk/preview-redaction",
            json={"case_id": "x", "search_text": "a", "category": "S22"},
        )
        assert r.status_code == 400

    async def test_preview_no_documents_in_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/bulk/preview-redaction",
            json={
                "case_id": "no-docs",
                "search_text": "alpha",
                "category": "S22",
            },
        )
        assert r.status_code == 404

    async def test_preview_user_role_forbidden(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/documents/bulk/preview-redaction",
            json={
                "case_id": "x",
                "search_text": "alpha",
                "category": "S22",
            },
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /bulk/apply-redaction
# ---------------------------------------------------------------------------


class TestApplyBulkRedaction:
    async def test_apply_happy_path_creates_redactions(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        doc_id = await _seed_document(
            db,
            case_id=case_id,
            extracted_text="bob met alice and alice",
            content=_text_pdf("bob met alice and alice"),
        )
        r = await client.post(
            "/api/v1/documents/bulk/apply-redaction",
            json={
                "case_id": case_id,
                "search_text": "alice",
                "category": "S22",
                "reason": "personal",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["documents_affected"] == 1
        assert body["redactions_created"] == 2  # "alice" appears twice
        # Each occurrence is located on the page and stored as a real box
        # (DOC-02: previously these were coordinate-less "needs_coordinates"
        # records that released nothing).
        doc = await db.documents.find_one({"id": doc_id})
        assert len(doc["redactions"]) == 2
        for red in doc["redactions"]:
            assert red["status"] == "approved" and red["source"] == "bulk_text"
            assert red["page"] == 1 and red["width"] > 0 and red["height"] > 0
            assert red["id"] and "needs_coordinates" not in red
        # Case audit log
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "bulk_redaction_applied" for e in case["audit_log"])

    async def test_apply_no_matches_returns_zero_summary(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        await _seed_document(db, case_id=case_id, extracted_text="alpha beta")
        r = await client.post(
            "/api/v1/documents/bulk/apply-redaction",
            json={
                "case_id": case_id,
                "search_text": "ZZZZZZ",
                "category": "S22",
                "reason": "x",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["redactions_created"] == 0
        assert body["documents_affected"] == 0

    async def test_apply_short_text_400(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/bulk/apply-redaction",
            json={
                "case_id": "x",
                "search_text": "a",
                "category": "S22",
                "reason": "x",
            },
        )
        assert r.status_code == 400

    async def test_apply_no_documents_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/bulk/apply-redaction",
            json={
                "case_id": "empty",
                "search_text": "abc",
                "category": "S22",
                "reason": "x",
            },
        )
        assert r.status_code == 404

    async def test_apply_audit_log_skipped_when_case_missing(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Documents exist for case_id but case row is missing -> the
        `if case:` audit-log block is skipped (branch 283->302)."""
        client = await authed_client_factory(role="admin")
        case_id = "ghost-case-bulk"
        await _seed_document(
            db, case_id=case_id, extracted_text="alice", content=_text_pdf("alice")
        )
        r = await client.post(
            "/api/v1/documents/bulk/apply-redaction",
            json={
                "case_id": case_id,
                "search_text": "alice",
                "category": "S22",
                "reason": "x",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["redactions_created"] == 1


# ---------------------------------------------------------------------------
# POST /bulk/create-template
# ---------------------------------------------------------------------------


class TestCreateRedactionTemplate:
    async def test_create_template_returns_template(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/bulk/create-template",
            json={
                "name": "SSN",
                "pattern": r"\d{3}-\d{2}-\d{4}",
                "category": "S22",
                "reason": "SSN",
                "description": "US SSN pattern",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["template"]["name"] == "SSN"
        assert "id" in body["template"]
        assert "created_by" in body["template"]

    async def test_create_template_without_optional_description(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/bulk/create-template",
            json={
                "name": "Phone",
                "pattern": r"\d{3}-\d{4}",
                "category": "S22",
                "reason": "Phone",
            },
        )
        assert r.status_code == 200
        body = r.json()
        # Description auto-generated
        assert "Redact all instances" in body["template"]["description"]

    async def test_create_template_user_role_forbidden(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/documents/bulk/create-template",
            json={
                "name": "x",
                "pattern": "y",
                "category": "S22",
                "reason": "z",
            },
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /{document_id}/ai-feedback
# ---------------------------------------------------------------------------


class TestRecordAIFeedback:
    async def test_feedback_accepted_records_in_collection(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/ai-feedback",
            json={
                "suggestion_text": "John Doe",
                "suggestion_category": "personal_info",
                "suggestion_reason": "name",
                "feedback": "accepted",
            },
        )
        assert r.status_code == 200, r.text
        # ai_feedback collection has the entry
        feedback_docs = await db["ai_feedback"].find({}).to_list(None)
        assert len(feedback_docs) == 1
        assert feedback_docs[0]["feedback"] == "accepted"
        # When accepted, document has NO rejected_ai_suggestions update
        doc = await db.documents.find_one({"id": doc_id})
        assert "rejected_ai_suggestions" not in doc or not doc.get("rejected_ai_suggestions")

    async def test_feedback_rejected_persists_in_document(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Rejected feedback should also update
        `document.rejected_ai_suggestions` via $addToSet so future
        cache reads can flag the suggestion as rejected."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/ai-feedback",
            json={
                "suggestion_text": "Jane",
                "suggestion_category": "personal_info",
                "suggestion_reason": "name",
                "feedback": "rejected",
                "context": "user_rejected_suggestion",
            },
        )
        assert r.status_code == 200
        doc = await db.documents.find_one({"id": doc_id})
        assert len(doc["rejected_ai_suggestions"]) == 1
        assert doc["rejected_ai_suggestions"][0]["text"] == "Jane"
        # Also persisted in ai_feedback collection
        feedback_docs = await db["ai_feedback"].find({}).to_list(None)
        assert len(feedback_docs) == 1
        assert feedback_docs[0]["feedback"] == "rejected"

    async def test_feedback_user_role_allowed_by_decorator(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """`check_role(['owner','admin','analyst','user'])` accepts a user who
        is on the document's case team (LLM-12)."""
        client = await authed_client_factory(role="user", email="team@example.test")
        user_doc = await db.users.find_one({"email": "team@example.test"})
        case_id = await _seed_case(
            db, case_team=[{"user_id": user_doc["id"], "role": "analyst", "status": "active"}]
        )
        doc_id = await _seed_document(db, case_id=case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/ai-feedback",
            json={
                "suggestion_text": "xy",
                "suggestion_category": "y",
                "suggestion_reason": "z",
                "feedback": "accepted",
            },
        )
        assert r.status_code == 200

    async def test_feedback_guest_role_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest")
        doc_id = await _seed_document(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/ai-feedback",
            json={
                "suggestion_text": "x",
                "suggestion_category": "y",
                "suggestion_reason": "z",
                "feedback": "accepted",
            },
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /bulk/apply-ai-suggestions
# ---------------------------------------------------------------------------


class TestApplyAISuggestionsBulk:
    async def test_apply_happy_path_filters_and_creates(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        # Seed 2 docs: one with valid AI suggestions, one without
        doc_id_1 = await _seed_document(
            db,
            case_id=case_id,
            content=_text_pdf("alice bob charlie x y"),
            ai_suggestions={
                "suggestions": [
                    {
                        "text": "alice",
                        "category": "personal_info",
                        "confidence": "high",
                        "has_coordinates": True,
                        "page": 1,
                        # The stored (enriched) shape: geometry is nested.
                        "coordinates": COORDS,
                        "reason": "name",
                    },
                    {
                        # Filtered out by confidence < medium
                        "text": "bob",
                        "category": "personal_info",
                        "confidence": "low",
                        "has_coordinates": True,
                        "page": 1,
                        "coordinates": COORDS,
                    },
                    {
                        # Filtered out by missing coordinates
                        "text": "charlie",
                        "category": "personal_info",
                        "confidence": "high",
                        "has_coordinates": False,
                        "page": 1,
                    },
                ]
            },
        )
        doc_id_2 = await _seed_document(
            db,
            case_id=case_id,
            ai_suggestions={"suggestions": []},  # skip path
        )
        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions",
            json={"case_id": case_id, "confidence_threshold": "medium"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["documents_processed"] == 1
        assert body["suggestions_applied"] == 1
        # Verify redaction added to doc_id_1
        doc = await db.documents.find_one({"id": doc_id_1})
        assert len(doc["redactions"]) == 1
        red = doc["redactions"][0]
        assert red["source"] == "ai_bulk_apply" and red["status"] == "approved"
        assert (red["x"], red["y"], red["width"], red["height"]) == (72.0, 90.0, 40.0, 14.0)
        assert red["id"]
        # The suggestion without coordinates is reported, not silently dropped.
        assert body["skipped_without_coordinates"] == 1

    async def test_apply_category_filter(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """`category_filter` skips suggestions where category doesn't match."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        await _seed_document(
            db,
            case_id=case_id,
            content=_text_pdf("alice bob charlie x y"),
            ai_suggestions={
                "suggestions": [
                    {
                        "text": "x",
                        "category": "personal_info",
                        "confidence": "high",
                        "has_coordinates": True,
                        "page": 1,
                        "coordinates": COORDS,
                    },
                    {
                        "text": "y",
                        "category": "other",
                        "confidence": "high",
                        "has_coordinates": True,
                        "page": 1,
                        "coordinates": COORDS,
                    },
                ]
            },
        )
        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions",
            json={"case_id": case_id, "category_filter": "personal_info"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["suggestions_applied"] == 1

    async def test_apply_unknown_confidence_threshold_defaults_to_medium(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """`confidence_threshold='nonsense'` falls back to medium (1)
        via the `.get(..., 1)` default."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        await _seed_document(
            db,
            case_id=case_id,
            content=_text_pdf("alice bob charlie x y"),
            ai_suggestions={
                "suggestions": [
                    {
                        "text": "x",
                        "category": "personal_info",
                        "confidence": "medium",
                        "has_coordinates": True,
                        "page": 1,
                        "coordinates": COORDS,
                    }
                ]
            },
        )
        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions",
            json={"case_id": case_id, "confidence_threshold": "nonsense"},
        )
        assert r.status_code == 200
        body = r.json()
        # `medium` suggestion at `medium` threshold passes (>=1)
        assert body["suggestions_applied"] == 1

    async def test_apply_no_documents_in_case_404(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions",
            json={"case_id": "empty-case"},
        )
        assert r.status_code == 404

    async def test_apply_role_gate(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions",
            json={"case_id": "x"},
        )
        assert r.status_code == 403

    async def test_apply_all_suggestions_filtered_out(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc with suggestions that all get filtered out (no coords).
        Pins branch 462->437: enter loop, `filtered_suggestions` empty,
        continue to next iteration without incrementing
        documents_processed."""
        client = await authed_client_factory(role="admin")
        case_id = await _seed_case(db)
        await _seed_document(
            db,
            case_id=case_id,
            ai_suggestions={
                "suggestions": [
                    {
                        "text": "x",
                        "category": "personal_info",
                        "confidence": "high",
                        "has_coordinates": False,  # filtered
                        "page": 1,
                    }
                ]
            },
        )
        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions",
            json={"case_id": case_id},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["documents_processed"] == 0
        assert body["suggestions_applied"] == 0

    async def test_apply_audit_log_skipped_when_case_missing(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Documents exist for case_id but the case row itself is
        missing: audit-log block is skipped (branch 490->509)."""
        client = await authed_client_factory(role="admin")
        # Don't seed a case row; seed only documents
        case_id = "ghost-case-id"
        await _seed_document(
            db,
            case_id=case_id,
            ai_suggestions={
                "suggestions": [
                    {
                        "text": "x",
                        "category": "personal_info",
                        "confidence": "high",
                        "has_coordinates": True,
                        "page": 1,
                    }
                ]
            },
        )
        r = await client.post(
            "/api/v1/documents/bulk/apply-ai-suggestions",
            json={"case_id": case_id},
        )
        assert r.status_code == 200
        # No audit log to verify; just confirmed no crash


# ---------------------------------------------------------------------------
# DELETE /{document_id}/redaction-suggestions/cache
# ---------------------------------------------------------------------------


class TestClearAISuggestionsCache:
    async def test_clear_cache_unsets_ai_suggestions(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(
            db,
            ai_suggestions={"suggestions": [{"text": "x"}], "summary": "x"},
        )
        r = await client.delete(f"/api/v1/documents/{doc_id}/redaction-suggestions/cache")
        assert r.status_code == 200, r.text
        doc = await db.documents.find_one({"id": doc_id})
        assert "ai_suggestions" not in doc

    async def test_clear_cache_no_cache_returns_404(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """No ai_suggestions to unset -> modified_count==0 -> 404."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db)  # No ai_suggestions
        r = await client.delete(f"/api/v1/documents/{doc_id}/redaction-suggestions/cache")
        assert r.status_code == 404

    async def test_clear_cache_role_gate(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user")
        r = await client.delete("/api/v1/documents/ghost/redaction-suggestions/cache")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Direct unit tests for helpers (cover module-level helpers not reachable
# via deps-override)
# ---------------------------------------------------------------------------


async def test_get_db_helper_returns_shared_database(mongo_uri: str) -> None:
    """The module-level `get_db` helper. Direct call to cover line."""
    from src.documents.redaction_suggestion_routes import get_db

    fake_request = MagicMock()
    result = await get_db(fake_request)
    assert result.name == "blackbar"


# ---------------------------------------------------------------------------
# Security-review 2026-09: LLM-02, LLM-04, LLM-12, LLM-14
# ---------------------------------------------------------------------------

GOOGLE_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/test-gemini-model:generateContent"
)
GOOGLE_KEY = "AIzaSyDOCVIEWLEAKDOCVIEWLEAK0001"


async def _seed_default_llm(
    db: AsyncIOMotorDatabase,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    request_format: str = "google",
    endpoint: str = GOOGLE_ENDPOINT,
    api_key: str = GOOGLE_KEY,
) -> None:
    """A real default LLM config in the test db, reached through the real
    get_llm_client() (no helper mocks)."""
    import src.utils.llm_client as llm_client_mod
    from src.llm.encryption import encrypt_api_key

    monkeypatch.setattr(llm_client_mod, "db", db)
    await db.llm_configs.insert_one(
        {
            "id": "llm-default",
            "name": "Gemini",
            "enabled": enabled,
            "api_endpoint": endpoint,
            "model_name": "test-gemini-model",
            "request_format": request_format,
            "default_settings": {"temperature": 0.3, "max_tokens": 2000, "top_p": 1.0},
            "headers": None,
            "notes": None,
            "api_key_encrypted": encrypt_api_key(api_key),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "seed",
        }
    )
    await db.system_config.insert_one({"id": "global_llm_config", "default_llm_id": "llm-default"})


async def _set_auto_generate(db: AsyncIOMotorDatabase, value: bool) -> None:
    await db.system_config.update_one(
        {"id": "system_configuration"},
        {"$set": {"auto_generate_ai_suggestions": value}},
        upsert=True,
    )


class TestViewDoesNotEgress:
    async def test_view_without_auto_generate_does_not_call_llm(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = await authed_client_factory(role="analyst")
        doc_id = await _seed_document(db, extracted_text="Alice Smith lives here")

        from src.documents import redaction_suggestion_routes

        async def _explode(text, context=None):
            raise AssertionError("viewing must not send the document to the LLM")

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _explode)
        r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?quick=false")
        assert r.status_code == 200
        assert r.json()["status"] == "not_generated"
        doc = await db.documents.find_one({"id": doc_id})
        assert "ai_suggestions" not in doc

    async def test_view_with_auto_generate_calls_llm_once_then_caches_empty(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _set_auto_generate(db, True)
        client = await authed_client_factory(role="analyst")
        doc_id = await _seed_document(db, extracted_text="Nothing sensitive here")

        from src.documents import redaction_suggestion_routes

        calls = []

        async def _fake_ai(text, context=None):
            calls.append(text)
            return {"suggestions": [], "summary": "AI identified 0 potential redactions"}

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _fake_ai)
        for _ in range(3):
            r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
            assert r.status_code == 200
        assert len(calls) == 1
        assert r.json()["status"] == "cached"

    async def test_disabled_llm_config_sends_nothing_and_caches_nothing(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import respx

        await _seed_default_llm(db, monkeypatch, enabled=False)
        client = await authed_client_factory(role="analyst")
        doc_id = await _seed_document(db, extracted_text="Alice Smith")
        with respx.mock(assert_all_mocked=True) as router:
            r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?generate=true")
            assert len(router.calls) == 0
        body = r.json()
        assert body["status"] == "ai_unavailable"
        assert body["error_code"] == "ai_disabled"
        assert "disabled" in body["summary"].lower()
        doc = await db.documents.find_one({"id": doc_id})
        assert "ai_suggestions" not in doc


class TestProviderErrorDoesNotLeakKey:
    async def test_google_401_key_absent_from_response_cache_and_logs(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        import httpx
        import respx

        await _seed_default_llm(db, monkeypatch)
        client = await authed_client_factory(role="analyst")
        doc_id = await _seed_document(db, extracted_text="Alice Smith")
        caplog.set_level(logging.DEBUG)
        with respx.mock(assert_all_mocked=True) as router:
            route = router.post(GOOGLE_ENDPOINT).mock(
                return_value=httpx.Response(
                    401,
                    json={"error": {"message": f"API key not valid: {GOOGLE_KEY}"}},
                )
            )
            r = await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions?generate=true")
            sent = route.calls.last.request
        assert GOOGLE_KEY not in str(sent.url)
        assert sent.headers["x-goog-api-key"] == GOOGLE_KEY

        assert r.status_code == 200
        body = r.json()
        assert GOOGLE_KEY not in r.text
        assert body["status"] == "ai_error"
        assert body["error_code"] == "provider_error"
        assert body["reference"] in body["summary"]

        doc = await db.documents.find_one({"id": doc_id})
        assert GOOGLE_KEY not in str(doc["ai_suggestions"])
        assert doc["ai_suggestions"]["provider"] == "google"
        assert GOOGLE_KEY not in caplog.text


class TestLLMRateLimits:
    async def test_per_document_cooldown(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LLM_REGENERATE_COOLDOWN_SECONDS", "60")
        client = await authed_client_factory(role="analyst")
        doc_id = await _seed_document(db, extracted_text="text")

        from src.documents import redaction_suggestion_routes

        async def _fake_ai(text, context=None):
            return {"suggestions": [], "summary": "ok"}

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _fake_ai)
        url = f"/api/v1/documents/{doc_id}/redaction-suggestions?force_regenerate=true"
        assert (await client.get(url)).status_code == 200
        r = await client.get(url)
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) > 0

    async def test_per_user_rate_limit(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LLM_REGENERATE_COOLDOWN_SECONDS", "0")
        monkeypatch.setenv("RATE_LIMIT_LLM", "2/minute")
        client = await authed_client_factory(role="analyst")
        doc_id = await _seed_document(db, extracted_text="text")

        from src.documents import redaction_suggestion_routes

        async def _fake_ai(text, context=None):
            return {"suggestions": [], "summary": "ok"}

        monkeypatch.setattr(redaction_suggestion_routes, "get_redaction_suggestions", _fake_ai)
        url = f"/api/v1/documents/{doc_id}/redaction-suggestions?force_regenerate=true"
        assert (await client.get(url)).status_code == 200
        assert (await client.get(url)).status_code == 200
        r = await client.get(url)
        assert r.status_code == 429
        # Cached reads are never limited.
        assert (
            await client.get(f"/api/v1/documents/{doc_id}/redaction-suggestions")
        ).status_code == 200


class TestFeedbackAccessAndRetention:
    async def test_user_outside_case_team_gets_403(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user")
        case_id = await _seed_case(db, case_team=[])
        doc_id = await _seed_document(db, case_id=case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/ai-feedback",
            json={
                "suggestion_text": "Alice Smith",
                "suggestion_category": "S22",
                "suggestion_reason": "name",
                "feedback": "rejected",
            },
        )
        assert r.status_code == 403
        doc = await db.documents.find_one({"id": doc_id})
        assert not doc.get("rejected_ai_suggestions")
        assert await db["ai_feedback"].count_documents({}) == 0

    async def test_missing_document_404(self, authed_client_factory, patch_routes_db) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/ghost/ai-feedback",
            json={
                "suggestion_text": "Alice",
                "suggestion_category": "S22",
                "feedback": "accepted",
            },
        )
        assert r.status_code == 404

    async def test_invalid_feedback_value_422(
        self, db: AsyncIOMotorDatabase, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/ai-feedback",
            json={
                "suggestion_text": "Alice",
                "suggestion_category": "S22",
                "feedback": "maybe",
            },
        )
        assert r.status_code == 422

    async def test_feedback_stores_hash_with_ttl_not_text(
        self, db: AsyncIOMotorDatabase, authed_client_factory, patch_routes_db
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_document(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/ai-feedback",
            json={
                "suggestion_text": "Alice Smith SIN 123-456-789",
                "suggestion_category": "S22",
                "suggestion_reason": "Alice Smith is named",
                "feedback": "accepted",
            },
        )
        assert r.status_code == 200
        record = await db["ai_feedback"].find_one({})
        assert "Alice" not in str(record)
        assert len(record["suggestion_hash"]) == 64
        assert record["expires_at"] > record["timestamp"]
        indexes = await db["ai_feedback"].index_information()
        assert any(
            spec.get("expireAfterSeconds") == 0 and spec["key"] == [("expires_at", 1)]
            for spec in indexes.values()
        )
