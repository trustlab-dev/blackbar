"""Integration tests for `src.admin.llm_routes` endpoints.

Phase 2.7. Target >=80% line coverage on `src/admin/llm_routes.py`.

Endpoint surface (8 endpoints; all admin-gated via `require_role(['admin'])`,
all mounted at /api/v1/llm/...):
    POST   /llm/configs                  -> create
    GET    /llm/configs                  -> list (with ?enabled_only=)
    GET    /llm/configs/{id}             -> read one
    PUT    /llm/configs/{id}             -> update
    DELETE /llm/configs/{id}             -> delete (with default-protection)
    GET    /llm/default                  -> read global default
    PUT    /llm/default/{id}             -> set global default
    POST   /llm/test                     -> test connection (real HTTP, mocked)

Reality pins:
- `LLMRepository(db)` is constructed inside Depends() helpers at request
  time, so patching `src.admin.llm_routes.db` is sufficient for full
  isolation — no module-level collection capture (unlike admin/routes.py).
- `require_role(['admin'])` uses `request.state.roles` (set by
  AuthMiddleware), NOT `get_current_user`. JWT realm-based gate.
- DELETE protection: deleting the configured global default returns 400
  with explicit message; other deletes return success {"message": ...}.
- LLM /test endpoint exercises the FULL provider HTTP path via
  `LLMService.make_llm_call`, mocked through respx. We test all 4
  provider formats (openai, anthropic, google, cohere).
- Test result includes `latency_seconds` rounded to 2 decimals and a
  human-friendly success/failure message.
- A disabled config returns `{"success": False, "message": "...
  disabled"}` without calling the LLM (early return).
- Error paths in /test return success=False with the failure message
  baked into the response (no 500 surfacing).
"""

from __future__ import annotations

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.llm.encryption import encrypt_api_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Point `src.admin.llm_routes.db` at the per-test motor database.

    The two Depends factories (`get_llm_service`, `get_llm_repository`)
    construct `LLMService(db)` and `LLMRepository(db)` against this
    module-level symbol, so rebinding the symbol is sufficient for the
    LLM-config CRUD.

    Endpoints that ALSO depend on `Depends(get_current_user)` (POST
    /configs and PUT /default/{id}) reach through `src.dependencies.users`
    — captured at module load from `src.database`. We rebind that too so
    the user lookup hits the per-test db rather than the closed global
    motor client.
    """
    import src.admin.llm_routes as _routes_mod
    import src.dependencies as deps_mod

    monkeypatch.setattr(_routes_mod, "db", db)
    monkeypatch.setattr(deps_mod, "users", db.users)
    return db


def _anon_client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _seed_config(
    db: AsyncIOMotorDatabase,
    *,
    config_id: str = "cfg-1",
    name: str = "OpenAI Prod",
    enabled: bool = True,
    request_format: str = "openai",
    api_endpoint: str = "https://api.openai.com/v1/chat/completions",
    model_name: str = "gpt-4o-mini",
    api_key_plaintext: str = "sk-fake-key-1234",
) -> str:
    """Insert an LLMConfig doc directly. Returns the id."""
    from datetime import datetime

    await db.llm_configs.insert_one(
        {
            "id": config_id,
            "name": name,
            "enabled": enabled,
            "api_endpoint": api_endpoint,
            "model_name": model_name,
            "request_format": request_format,
            "default_settings": {
                "temperature": 0.7,
                "max_tokens": 4000,
                "top_p": 1.0,
            },
            "headers": None,
            "notes": None,
            "api_key_encrypted": encrypt_api_key(api_key_plaintext),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "seed",
        }
    )
    return config_id


def _create_payload(**overrides) -> dict:
    """Build a valid LLMConfigCreate JSON body for POST /configs."""
    base = {
        "name": "OpenAI Prod",
        "enabled": True,
        "api_endpoint": "https://api.openai.com/v1/chat/completions",
        "model_name": "gpt-4o-mini",
        "request_format": "openai",
        "api_key": "sk-fake-1234",
        "default_settings": {
            "temperature": 0.7,
            "max_tokens": 4000,
            "top_p": 1.0,
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# POST /llm/configs (create)
# ---------------------------------------------------------------------------


class TestCreateLLMConfig:
    async def test_admin_can_create(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/configs", json=_create_payload(name="MyLLM"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "MyLLM"
        # Response shape pin: no encrypted_key field on the public response
        assert "api_key" not in body
        assert "api_key_encrypted" not in body

    async def test_create_persists_encrypted_key(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Audit guarantee: plaintext api_key is NEVER stored."""
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/llm/configs",
            json=_create_payload(api_key="plaintext-secret"),
        )
        assert r.status_code == 200
        config_id = r.json()["id"]
        doc = await db.llm_configs.find_one({"id": config_id})
        assert doc is not None
        assert "api_key" not in doc
        assert "api_key_encrypted" in doc
        assert doc["api_key_encrypted"] != "plaintext-secret"

    async def test_non_admin_forbidden(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.post("/api/v1/llm/configs", json=_create_payload())
        assert r.status_code == 403

    async def test_user_forbidden(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="user")
        r = await client.post("/api/v1/llm/configs", json=_create_payload())
        assert r.status_code == 403

    async def test_unauthenticated_rejected(self, app) -> None:
        async with _anon_client(app) as c:
            r = await c.post("/api/v1/llm/configs", json=_create_payload())
        assert r.status_code == 401

    async def test_first_enabled_config_auto_promoted_to_default(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """FE-F11: creating an enabled config when no default exists yet
        auto-marks it default so AI features work without an extra
        click."""
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/configs", json=_create_payload(name="First"))
        assert r.status_code == 200, r.text
        config_id = r.json()["id"]

        global_cfg = await db.system_config.find_one({"id": "global_llm_config"})
        assert global_cfg is not None
        assert global_cfg["default_llm_id"] == config_id

    async def test_subsequent_create_does_not_steal_default(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Once a default is set, creating another config must NOT
        re-point the default — operators stay in control."""
        await _seed_config(db, config_id="existing-default")
        await db.system_config.update_one(
            {"id": "global_llm_config"},
            {"$set": {"default_llm_id": "existing-default"}},
            upsert=True,
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/configs", json=_create_payload(name="Second"))
        assert r.status_code == 200

        global_cfg = await db.system_config.find_one({"id": "global_llm_config"})
        assert global_cfg["default_llm_id"] == "existing-default"

    async def test_disabled_first_config_not_auto_promoted(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """A disabled config should NOT be auto-promoted — it would
        immediately fail any LLM call."""
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/llm/configs", json=_create_payload(name="Disabled", enabled=False)
        )
        assert r.status_code == 200

        global_cfg = await db.system_config.find_one({"id": "global_llm_config"})
        assert global_cfg is None or global_cfg.get("default_llm_id") is None


# ---------------------------------------------------------------------------
# GET /llm/configs (list)
# ---------------------------------------------------------------------------


class TestListLLMConfigs:
    async def test_admin_lists_all(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(db, config_id="a", name="A", enabled=True)
        await _seed_config(db, config_id="b", name="B", enabled=False)
        await _seed_config(db, config_id="c", name="C", enabled=True)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/llm/configs")
        assert r.status_code == 200
        body = r.json()
        assert {c["name"] for c in body} == {"A", "B", "C"}

    async def test_enabled_only_filter(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(db, config_id="on", name="ON", enabled=True)
        await _seed_config(db, config_id="off", name="OFF", enabled=False)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/llm/configs?enabled_only=true")
        names = {c["name"] for c in r.json()}
        assert names == {"ON"}

    async def test_non_admin_forbidden(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.get("/api/v1/llm/configs")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /llm/configs/{id}
# ---------------------------------------------------------------------------


class TestGetLLMConfig:
    async def test_admin_gets_existing(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(db, config_id="ce-1", name="Specific")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/llm/configs/ce-1")
        assert r.status_code == 200
        assert r.json()["name"] == "Specific"

    async def test_404_for_missing(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/llm/configs/nonexistent")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /llm/configs/{id}
# ---------------------------------------------------------------------------


class TestUpdateLLMConfig:
    async def test_admin_can_update_name(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(db, config_id="upd-1", name="Old")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/llm/configs/upd-1", json={"name": "New", "enabled": False})
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "New"
        assert body["enabled"] is False

    async def test_404_for_missing(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/llm/configs/missing", json={"name": "Whatever"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /llm/configs/{id}
# ---------------------------------------------------------------------------


class TestDeleteLLMConfig:
    async def test_admin_can_delete(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(db, config_id="del-1")

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/llm/configs/del-1")
        assert r.status_code == 200
        assert "deleted successfully" in r.json()["message"]
        # Persistence
        assert await db.llm_configs.find_one({"id": "del-1"}) is None

    async def test_cannot_delete_global_default(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Reality pin: if the config is the global default, DELETE
        returns 400 with a guidance message — even before the actual
        delete is attempted."""
        await _seed_config(db, config_id="default-1")
        # Mark as global default
        await db.system_config.update_one(
            {"id": "global_llm_config"},
            {"$set": {"default_llm_id": "default-1"}},
            upsert=True,
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/llm/configs/default-1")
        assert r.status_code == 400
        body = r.json()
        msg = body.get("error", {}).get("message", "") or body.get("detail", "")
        assert "default" in msg.lower()
        # Confirm the doc still exists
        assert await db.llm_configs.find_one({"id": "default-1"}) is not None

    async def test_delete_404_for_missing(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/llm/configs/nonexistent")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /llm/default
# ---------------------------------------------------------------------------


class TestGetDefaultLLM:
    async def test_404_when_no_default_set(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/llm/default")
        assert r.status_code == 404

    async def test_returns_default_when_set(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(db, config_id="d-1", name="DefaultLLM")
        await db.system_config.update_one(
            {"id": "global_llm_config"},
            {"$set": {"default_llm_id": "d-1"}},
            upsert=True,
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/llm/default")
        assert r.status_code == 200
        assert r.json()["name"] == "DefaultLLM"


# ---------------------------------------------------------------------------
# PUT /llm/default/{id}
# ---------------------------------------------------------------------------


class TestSetDefaultLLM:
    async def test_admin_can_set_default(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(db, config_id="d-set-1", enabled=True)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/llm/default/d-set-1")
        assert r.status_code == 200
        body = r.json()
        assert body["config_id"] == "d-set-1"
        # Persistence
        gc = await db.system_config.find_one({"id": "global_llm_config"})
        assert gc["default_llm_id"] == "d-set-1"

    async def test_cannot_set_disabled_as_default(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Reality pin: `set_default_llm` checks `config.enabled` and
        returns False for disabled configs — handler converts to 404
        'not found or not enabled'."""
        await _seed_config(db, config_id="dis-1", enabled=False)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/llm/default/dis-1")
        assert r.status_code == 404

    async def test_404_for_missing_config(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.put("/api/v1/llm/default/nope")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /llm/test  (connection test, mocked HTTP)
# ---------------------------------------------------------------------------


class TestLLMTestConnection:
    @respx.mock
    async def test_disabled_config_returns_success_false_no_http(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Reality pin: disabled config short-circuits before any HTTP
        call. respx.mock asserts no provider URL was hit (`assert_all_called`
        defaults False in respx.mock decorator — we add an explicit
        respx.calls assertion)."""
        await _seed_config(db, config_id="off-1", enabled=False)

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/test", json={"config_id": "off-1"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert "disabled" in body["message"].lower()
        assert body["response"] is None
        # No HTTP calls made (no respx routes were ever set up either)
        assert len(respx.calls) == 0

    @respx.mock
    async def test_openai_success_extracts_choice_text(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(
            db,
            config_id="ok-openai",
            request_format="openai",
            api_endpoint="https://api.openai.com/v1/chat/completions",
        )
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "I am working."}}]},
            )
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/test", json={"config_id": "ok-openai"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["response"] == "I am working."
        assert body["model"] == "gpt-4o-mini"
        assert "latency_seconds" in body

    @respx.mock
    async def test_anthropic_success_extracts_content_text(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(
            db,
            config_id="ok-anthropic",
            request_format="anthropic",
            api_endpoint="https://api.anthropic.com/v1/messages",
            model_name="claude-3-5-sonnet-20241022",
        )
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=Response(
                200,
                json={
                    "content": [{"type": "text", "text": "Anthropic OK"}],
                    "model": "claude-3-5-sonnet-20241022",
                },
            )
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/test", json={"config_id": "ok-anthropic"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["response"] == "Anthropic OK"

    @respx.mock
    async def test_google_success_extracts_candidates_text(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(
            db,
            config_id="ok-google",
            request_format="google",
            api_endpoint="https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent",
            model_name="gemini-pro",
        )
        # Google appends ?key=<api_key> to the URL; respx.post pattern
        # matches the base URL regardless of query string by default
        respx.post(
            url__startswith="https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent"
        ).mock(
            return_value=Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": "Gemini OK"}],
                                "role": "model",
                            }
                        }
                    ]
                },
            )
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/test", json={"config_id": "ok-google"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["response"] == "Gemini OK"

    @respx.mock
    async def test_cohere_success_extracts_text_field(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(
            db,
            config_id="ok-cohere",
            request_format="cohere",
            api_endpoint="https://api.cohere.com/v1/chat",
            model_name="command-r",
        )
        respx.post("https://api.cohere.com/v1/chat").mock(
            return_value=Response(200, json={"text": "Cohere OK"})
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/test", json={"config_id": "ok-cohere"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["response"] == "Cohere OK"

    @respx.mock
    async def test_provider_5xx_returns_success_false_with_message(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Reality pin: handler catches the provider exception inside the
        `make_llm_call` await and returns `{"success": False,
        "message": "Connection failed (...): ...", "response": None,
        "latency_seconds": <float>}`. The HTTP status of the route stays
        200 — the caller gets a structured failure shape."""
        await _seed_config(
            db,
            config_id="fail-1",
            request_format="openai",
            api_endpoint="https://api.openai.com/v1/chat/completions",
        )
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=Response(500, json={"error": "internal"})
        )

        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/test", json={"config_id": "fail-1"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert "failed" in body["message"].lower()
        assert body["response"] is None
        assert "latency_seconds" in body

    async def test_404_for_missing_config(self, authed_client_factory, patch_routes_db) -> None:
        client: AsyncClient = await authed_client_factory(role="admin")
        r = await client.post("/api/v1/llm/test", json={"config_id": "missing"})
        assert r.status_code == 404

    async def test_non_admin_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        await _seed_config(db, config_id="rbac-1")
        client: AsyncClient = await authed_client_factory(role="analyst")
        r = await client.post("/api/v1/llm/test", json={"config_id": "rbac-1"})
        assert r.status_code == 403
