"""Integration tests for `src.documents.share_routes`.

Phase 2.3.C (4/5). Target >=80% line coverage on
`src.documents.share_routes` — analyst-side share management plus the
guest-side "shared-with-me" listing.

Endpoints under test (mounted at `/api/v1/documents/...` via
`document_share_router` in `src/main.py`, prefix `/documents`):

    POST   /{document_id}/share         (analyst+ shares with guest)
    DELETE /{document_id}/share/{user_id}
    GET    /{document_id}/shares
    GET    /shared-with-me              (guest-only)

**Module-level db symbol capture:** the source imports `from
..database import db, users` at the top. All four endpoints reach
for these module-level symbols (NOT via Depends(get_db)). Tests must
monkeypatch `src.documents.share_routes.db` AND
`src.documents.share_routes.users`. Same class as B30.

**Auth:**
- Sharing/unsharing/listing-shares: `check_role(["owner","admin","analyst"])`.
- shared-with-me: `check_role(["guest"])` — owner/admin cannot access.

**Route order pin:** `GET /shared-with-me` is defined AFTER `GET
/{document_id}/shares`. The latter matches `document_id="shared-with-me"`
under any method — but since `/shares` is the path suffix it doesn't
actually collide. Just confirmed for sanity.
"""

from __future__ import annotations

from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_document, make_user

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Rebind the module-level `db` and `users` symbols on share_routes
    to the per-test motor db. The endpoints don't use Depends(get_db)."""
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import share_routes

    monkeypatch.setattr(share_routes, "db", db)
    monkeypatch.setattr(share_routes, "users", db.users)
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)
    yield db


async def _seed_doc(db: AsyncIOMotorDatabase, **overrides: Any) -> str:
    doc = make_document(**overrides)
    await db.documents.insert_one(doc)
    return doc["id"]


async def _seed_guest_user(
    db: AsyncIOMotorDatabase, email: str = "guest-target@example.com"
) -> dict:
    u = make_user(role="guest", email=email, username="GuestTarget")
    await db.users.insert_one(u)
    return u


# ---------------------------------------------------------------------------
# POST /{document_id}/share
# ---------------------------------------------------------------------------


class TestShareDocument:
    async def test_admin_shares_with_guest(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        guest = await _seed_guest_user(db)
        doc_id = await _seed_doc(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/share",
            json={"user_id": guest["id"], "notes": "for your review"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "share" in body
        share = body["share"]
        assert share["user_id"] == guest["id"]
        assert share["notes"] == "for your review"
        assert share["shared_by"]

        # Persisted in document
        doc = await db.documents.find_one({"id": doc_id})
        assert len(doc["shared_with"]) == 1
        assert doc["shared_with"][0]["user_id"] == guest["id"]

    async def test_share_doc_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        guest = await _seed_guest_user(db)
        r = await client.post(
            "/api/v1/documents/ghost/share",
            json={"user_id": guest["id"]},
        )
        assert r.status_code == 404
        assert "Document not found" in r.text

    async def test_share_target_user_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_doc(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/share",
            json={"user_id": "ghost-user"},
        )
        assert r.status_code == 404
        assert "User not found" in r.text

    async def test_share_target_must_be_guest_role(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Sharing with a non-guest user -> 400 "Can only share with
        guest users". Pinned guard."""
        client = await authed_client_factory(role="admin")
        non_guest = make_user(role="analyst", email="not-a-guest@example.com")
        await db.users.insert_one(non_guest)
        doc_id = await _seed_doc(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/share",
            json={"user_id": non_guest["id"]},
        )
        assert r.status_code == 400
        assert "Can only share with guest users" in r.text

    async def test_share_duplicate_returns_400(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        guest = await _seed_guest_user(db)
        doc_id = await _seed_doc(db, shared_with=[{"user_id": guest["id"]}])
        r = await client.post(
            f"/api/v1/documents/{doc_id}/share",
            json={"user_id": guest["id"]},
        )
        assert r.status_code == 400
        assert "already shared" in r.text

    @pytest.mark.parametrize("role", ["user", "guest"])
    async def test_share_role_decorator_forbids(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        role: str,
    ) -> None:
        client = await authed_client_factory(role=role, email=f"share-forbid-{role}@example.com")
        guest = await _seed_guest_user(db, email=f"target-{role}@example.com")
        doc_id = await _seed_doc(db)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/share",
            json={"user_id": guest["id"]},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /{document_id}/share/{user_id}
# ---------------------------------------------------------------------------


class TestUnshareDocument:
    async def test_admin_can_unshare(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        guest = await _seed_guest_user(db)
        doc_id = await _seed_doc(db, shared_with=[{"user_id": guest["id"], "notes": "x"}])
        r = await client.delete(f"/api/v1/documents/{doc_id}/share/{guest['id']}")
        assert r.status_code == 200
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["shared_with"] == []

    async def test_unshare_doc_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.delete("/api/v1/documents/ghost/share/u1")
        assert r.status_code == 404
        assert "Document not found" in r.text

    async def test_unshare_share_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Doc exists but user isn't in shared_with -> modified_count
        is 0 -> 404 "Share not found"."""
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_doc(db, shared_with=[])
        r = await client.delete(f"/api/v1/documents/{doc_id}/share/u1")
        assert r.status_code == 404
        assert "Share not found" in r.text

    @pytest.mark.parametrize("role", ["user", "guest"])
    async def test_unshare_role_decorator_forbids(
        self,
        authed_client_factory,
        patch_routes_db,
        role: str,
    ) -> None:
        client = await authed_client_factory(role=role, email=f"unshare-forbid-{role}@example.com")
        r = await client.delete("/api/v1/documents/x/share/u1")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{document_id}/shares
# ---------------------------------------------------------------------------


class TestListDocumentShares:
    async def test_admin_lists_shares(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_doc(
            db,
            shared_with=[
                {"user_id": "u1", "user_name": "Alice"},
                {"user_id": "u2", "user_name": "Bob"},
            ],
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/shares")
        assert r.status_code == 200
        body = r.json()
        assert {s["user_id"] for s in body["shares"]} == {"u1", "u2"}

    async def test_list_shares_empty(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_doc(db)
        r = await client.get(f"/api/v1/documents/{doc_id}/shares")
        assert r.status_code == 200
        assert r.json() == {"shares": []}

    async def test_list_shares_doc_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/shares")
        assert r.status_code == 404

    @pytest.mark.parametrize("role", ["user", "guest"])
    async def test_list_shares_role_decorator_forbids(
        self,
        authed_client_factory,
        patch_routes_db,
        role: str,
    ) -> None:
        client = await authed_client_factory(
            role=role, email=f"list-shares-forbid-{role}@example.com"
        )
        r = await client.get("/api/v1/documents/x/shares")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /shared-with-me
# ---------------------------------------------------------------------------


class TestListSharedWithMe:
    async def test_guest_lists_documents_shared_with_them(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest", email="swm@example.com")
        me = await db.users.find_one({"email": "swm@example.com"})
        # Two docs shared with this guest, one with someone else.
        await _seed_doc(
            db,
            filename="for-me-1.pdf",
            mime_type="application/pdf",
            shared_with=[
                {
                    "user_id": me["id"],
                    "shared_by_name": "Analyst Alice",
                    "shared_at": "2026-05-01T00:00:00",
                    "notes": "first",
                }
            ],
        )
        await _seed_doc(
            db,
            filename="for-me-2.pdf",
            shared_with=[{"user_id": me["id"], "notes": "second"}],
        )
        await _seed_doc(
            db,
            filename="not-for-me.pdf",
            shared_with=[{"user_id": "someone-else"}],
        )
        r = await client.get("/api/v1/documents/shared-with-me")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        filenames = {d["filename"] for d in body["documents"]}
        assert filenames == {"for-me-1.pdf", "for-me-2.pdf"}
        # Pinned response shape: shared_by/shared_at/notes pulled from
        # the matching share_entry
        f1 = next(d for d in body["documents"] if d["filename"] == "for-me-1.pdf")
        assert f1["shared_by"] == "Analyst Alice"
        assert f1["shared_at"] == "2026-05-01T00:00:00"
        assert f1["notes"] == "first"

    async def test_shared_with_me_empty_for_new_guest(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="guest", email="empty-swm@example.com")
        r = await client.get("/api/v1/documents/shared-with-me")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["documents"] == []

    @pytest.mark.parametrize("role", ["admin", "analyst", "user"])
    async def test_shared_with_me_role_decorator_forbids_non_guest(
        self,
        authed_client_factory,
        patch_routes_db,
        role: str,
    ) -> None:
        """Endpoint is guest-only; admin/analyst/user are 403."""
        client = await authed_client_factory(role=role, email=f"swm-forbid-{role}@example.com")
        r = await client.get("/api/v1/documents/shared-with-me")
        assert r.status_code == 403
