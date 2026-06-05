"""Integration tests for `src.documents.contest_routes`.

Phase 2.3.C (5/5). Target >=80% line coverage on
`src.documents.contest_routes` — the contest-redactions and
reject-document state machines.

Endpoints under test (mounted at `/api/v1/documents/...` via
`contest_router` included from `documents/routes.py`):

    POST   /{document_id}/redactions/{redaction_index}/contest
    GET    /{document_id}/contests
    PUT    /contests/{contest_id}/resolve
    POST   /{document_id}/reject
    GET    /{document_id}/rejections
    PUT    /rejections/{rejection_id}/address

**Module-level db captures:** the source imports
`from ..database import db` and binds two collection symbols at module
load time:
    redaction_contests = db["redaction_contests"]
    document_rejections = db["document_rejections"]
These are bound BEFORE tests monkeypatch the module's `db` attribute.
Both collection symbols still reference the production "blackbar" db
unless we monkeypatch them too. Tests do.

**State machines:**
- Contest lifecycle: file (status="open") -> resolve (status="resolved",
  resolution in {"kept", "removed", "modified"})
- Rejection lifecycle: reject (status="open", doc.status="rejected")
  -> address (status="addressed", doc.status="under_review")

**Auth (case-team roles):**
- contest_redaction: any role that returns True from
  `can_contest_redactions` (manager/analyst/legal/reviewer/third_party).
  SME + approver cannot contest.
- resolve_contest: user_role in {"analyst", "manager"} only.
- reject_document: any role that returns True from
  `can_reject_documents` (manager/analyst/reviewer/approver).
- address_rejection: user_role in {"analyst", "manager"} only.
- get_document_contests / get_document_rejections: any case-team member.

**Pinned source findings (audit Section 11 candidates):**
- `resolve_contest` allows resolving an already-resolved contest
  (no state-machine guard on `contest.status`). Pinned.
- `address_rejection` allows addressing an already-addressed
  rejection. Pinned.
- Resolving a contest with `resolution == "removed"` uses a
  `$pull: {"redactions": {"$eq": contest["redaction"]}}` filter that
  matches the full stored redaction dict. If anything mutated the
  redaction between contest-time and resolve-time, the pull is a
  no-op and no error surfaces (silent failure).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case, make_document

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase):
    """Rebind contest_routes' module-level captures to the per-test
    motor db: both `db` and the two collection symbols
    (redaction_contests, document_rejections)."""
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import contest_routes

    monkeypatch.setattr(contest_routes, "db", db)
    monkeypatch.setattr(contest_routes, "redaction_contests", db["redaction_contests"])
    monkeypatch.setattr(contest_routes, "document_rejections", db["document_rejections"])
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)
    yield db


async def _seed_case_with_team(
    db: AsyncIOMotorDatabase,
    *team: tuple[str, str],  # (user_id, role) tuples
    **overrides: Any,
) -> str:
    case_team = [
        {
            "user_id": uid,
            "role": role,
            "status": "active",
            "added_at": datetime.utcnow().isoformat(),
        }
        for uid, role in team
    ]
    case = make_case(case_team=case_team, **overrides)
    await db.cases.insert_one(case)
    return case["id"]


async def _seed_doc(db: AsyncIOMotorDatabase, case_id: str, **overrides: Any) -> str:
    doc = make_document(case_id=case_id, **overrides)
    await db.documents.insert_one(doc)
    return doc["id"]


# ---------------------------------------------------------------------------
# POST /{document_id}/redactions/{redaction_index}/contest
# ---------------------------------------------------------------------------


class TestContestRedaction:
    async def test_legal_contests_redaction(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="legal@example.com")
        me = await db.users.find_one({"email": "legal@example.com"})
        case_id = await _seed_case_with_team(db, (me["id"], "legal"))
        doc_id = await _seed_doc(
            db,
            case_id,
            redactions=[
                {
                    "id": "r1",
                    "page": 1,
                    "type": "professional",
                    "status": "approved",
                }
            ],
        )
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/0/contest",
            json={"redaction_index": 0, "reason": "Public interest"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["contest_id"]

        # Persisted in redaction_contests collection
        contest = await db["redaction_contests"].find_one({"id": body["contest_id"]})
        assert contest["status"] == "open"
        assert contest["reason"] == "Public interest"
        assert contest["contested_by"] == me["id"]
        assert contest["contested_by_role"] == "legal"
        assert contest["document_id"] == doc_id

        # Redaction flipped to contested
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["redactions"][0]["status"] == "contested"
        assert doc["redactions"][0]["is_contested"] is True
        assert doc["redactions"][0]["active_contests"] == 1

        # Audit log entry
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "redaction_contested" for e in case.get("audit_log", []))

    async def test_contest_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/ghost/redactions/0/contest",
            json={"redaction_index": 0, "reason": "x"},
        )
        assert r.status_code == 404
        assert "Document not found" in r.text

    async def test_contest_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_doc(db, case_id="ghost-case", redactions=[{"id": "r1"}])
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/0/contest",
            json={"redaction_index": 0, "reason": "x"},
        )
        assert r.status_code == 404
        assert "Case not found" in r.text

    @pytest.mark.parametrize("case_role", ["sme", "approver"])
    async def test_contest_forbidden_for_non_contesting_roles(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        case_role: str,
    ) -> None:
        """SME and approver case-team roles cannot contest. Pins
        can_contest_redactions False branches."""
        client = await authed_client_factory(
            role="user", email=f"contest-no-{case_role}@example.com"
        )
        me = await db.users.find_one({"email": f"contest-no-{case_role}@example.com"})
        case_id = await _seed_case_with_team(db, (me["id"], case_role))
        doc_id = await _seed_doc(db, case_id, redactions=[{"id": "r1"}])
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/0/contest",
            json={"redaction_index": 0, "reason": "x"},
        )
        assert r.status_code == 403
        assert "permission to contest" in r.text

    async def test_contest_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """User not on case team -> get_user_role_on_case returns None ->
        403 short-circuit."""
        client = await authed_client_factory(role="user", email="off-contest@example.com")
        case_id = await _seed_case_with_team(db, ("someone-else", "analyst"))
        doc_id = await _seed_doc(db, case_id, redactions=[{"id": "r1"}])
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/0/contest",
            json={"redaction_index": 0, "reason": "x"},
        )
        assert r.status_code == 403

    async def test_contest_index_out_of_range(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="oob@example.com")
        me = await db.users.find_one({"email": "oob@example.com"})
        case_id = await _seed_case_with_team(db, (me["id"], "legal"))
        doc_id = await _seed_doc(db, case_id, redactions=[])
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/99/contest",
            json={"redaction_index": 99, "reason": "x"},
        )
        assert r.status_code == 404
        assert "Redaction not found" in r.text


# ---------------------------------------------------------------------------
# GET /{document_id}/contests
# ---------------------------------------------------------------------------


class TestGetDocumentContests:
    async def test_team_member_lists_contests(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="gc@example.com")
        me = await db.users.find_one({"email": "gc@example.com"})
        case_id = await _seed_case_with_team(db, (me["id"], "analyst"))
        doc_id = await _seed_doc(db, case_id, redactions=[{"id": "r1"}])
        # Seed two contests
        await db["redaction_contests"].insert_many(
            [
                {
                    "id": "c1",
                    "document_id": doc_id,
                    "case_id": case_id,
                    "status": "open",
                },
                {
                    "id": "c2",
                    "document_id": doc_id,
                    "case_id": case_id,
                    "status": "resolved",
                },
            ]
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/contests")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert {c["id"] for c in body["contests"]} == {"c1", "c2"}
        # Mongo _id should be stripped from the response
        assert all("_id" not in c for c in body["contests"])

    async def test_get_contests_doc_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        # Even admin can't bypass the doc-existence check.
        r = await client.get("/api/v1/documents/ghost/contests")
        assert r.status_code == 404

    async def test_get_contests_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_doc(db, case_id="ghost-case")
        r = await client.get(f"/api/v1/documents/{doc_id}/contests")
        assert r.status_code == 404
        assert "Case not found" in r.text

    async def test_get_contests_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="off-gc@example.com")
        case_id = await _seed_case_with_team(db, ("someone", "analyst"))
        doc_id = await _seed_doc(db, case_id)
        r = await client.get(f"/api/v1/documents/{doc_id}/contests")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# PUT /contests/{contest_id}/resolve
# ---------------------------------------------------------------------------


class TestResolveContest:
    async def _seed_open_contest(
        self,
        db: AsyncIOMotorDatabase,
        user_id: str,
        *,
        resolver_role: str = "analyst",
        redaction: dict | None = None,
    ) -> tuple[str, str, str]:
        """Returns (case_id, doc_id, contest_id) and a redaction with
        active_contests=1 already in place."""
        case_id = await _seed_case_with_team(db, (user_id, resolver_role))
        redaction = redaction or {
            "id": "r1",
            "page": 1,
            "type": "professional",
            "status": "contested",
            "is_contested": True,
            "active_contests": 1,
        }
        doc_id = await _seed_doc(db, case_id, redactions=[redaction])
        contest = {
            "id": "contest-1",
            "case_id": case_id,
            "document_id": doc_id,
            "redaction_index": 0,
            "redaction": redaction,
            "status": "open",
            "contested_by": "someone-else",
        }
        await db["redaction_contests"].insert_one(contest)
        return case_id, doc_id, "contest-1"

    @pytest.mark.parametrize("resolution", ["kept", "modified"])
    async def test_resolve_kept_or_modified_decrements_contests(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        resolution: str,
    ) -> None:
        client = await authed_client_factory(role="user", email=f"res-{resolution}@example.com")
        me = await db.users.find_one({"email": f"res-{resolution}@example.com"})
        case_id, doc_id, contest_id = await self._seed_open_contest(db, me["id"])
        r = await client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve",
            json={"resolution": resolution, "resolution_notes": "ok"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert resolution in body["message"]

        # Contest marked resolved
        contest = await db["redaction_contests"].find_one({"id": contest_id})
        assert contest["status"] == "resolved"
        assert contest["resolution"] == resolution
        assert contest["resolved_by"] == me["id"]

        # Redaction status flipped back to "approved" when active_contests=0
        doc = await db.documents.find_one({"id": doc_id})
        red = doc["redactions"][0]
        assert red["active_contests"] == 0
        assert red["is_contested"] is False
        assert red["status"] == "approved"

        # Audit log
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "contest_resolved" for e in case.get("audit_log", []))

    async def test_resolve_removed_pulls_redaction(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="rm@example.com")
        me = await db.users.find_one({"email": "rm@example.com"})
        case_id, doc_id, contest_id = await self._seed_open_contest(db, me["id"])
        r = await client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve",
            json={"resolution": "removed"},
        )
        assert r.status_code == 200
        # Redaction was $pulled out
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["redactions"] == []

    async def test_resolve_kept_with_multiple_contests_stays_contested(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """active_contests was 2 -> after resolve becomes 1 -> still
        contested (is_contested True, status='contested')."""
        client = await authed_client_factory(role="user", email="multi@example.com")
        me = await db.users.find_one({"email": "multi@example.com"})
        redaction = {
            "id": "r1",
            "page": 1,
            "status": "contested",
            "is_contested": True,
            "active_contests": 2,
        }
        case_id, doc_id, contest_id = await self._seed_open_contest(
            db, me["id"], redaction=redaction
        )
        r = await client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve",
            json={"resolution": "kept"},
        )
        assert r.status_code == 200
        doc = await db.documents.find_one({"id": doc_id})
        red = doc["redactions"][0]
        assert red["active_contests"] == 1
        assert red["is_contested"] is True
        assert red["status"] == "contested"

    async def test_resolve_contest_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/documents/contests/ghost/resolve",
            json={"resolution": "kept"},
        )
        assert r.status_code == 404
        assert "Contest not found" in r.text

    async def test_resolve_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        await db["redaction_contests"].insert_one(
            {
                "id": "orphan",
                "case_id": "ghost-case",
                "document_id": "doesnt-matter",
                "redaction_index": 0,
                "redaction": {},
            }
        )
        r = await client.put(
            "/api/v1/documents/contests/orphan/resolve",
            json={"resolution": "kept"},
        )
        assert r.status_code == 404
        assert "Case not found" in r.text

    @pytest.mark.parametrize("case_role", ["legal", "sme", "reviewer", "third_party"])
    async def test_resolve_forbidden_for_non_resolver_roles(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        case_role: str,
    ) -> None:
        """Only analyst/manager can resolve. Pins the role guard."""
        client = await authed_client_factory(
            role="user", email=f"noresolve-{case_role}@example.com"
        )
        me = await db.users.find_one({"email": f"noresolve-{case_role}@example.com"})
        case_id, doc_id, contest_id = await self._seed_open_contest(
            db, me["id"], resolver_role=case_role
        )
        r = await client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve",
            json={"resolution": "kept"},
        )
        assert r.status_code == 403
        assert "analysts and managers" in r.text

    async def test_resolve_already_resolved_contest_silently_succeeds(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin reality: no state-machine guard on contest.status.
        Re-resolving an already-resolved contest succeeds; the second
        resolution overwrites the first."""
        client = await authed_client_factory(role="user", email="re@example.com")
        me = await db.users.find_one({"email": "re@example.com"})
        case_id, doc_id, contest_id = await self._seed_open_contest(db, me["id"])
        # Resolve once
        r1 = await client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve",
            json={"resolution": "kept"},
        )
        assert r1.status_code == 200
        # Resolve again with different resolution
        r2 = await client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve",
            json={"resolution": "modified", "resolution_notes": "redo"},
        )
        assert r2.status_code == 200
        contest = await db["redaction_contests"].find_one({"id": contest_id})
        assert contest["resolution"] == "modified"


# ---------------------------------------------------------------------------
# POST /{document_id}/reject
# ---------------------------------------------------------------------------


class TestRejectDocument:
    async def test_reviewer_rejects_document(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="rev@example.com")
        me = await db.users.find_one({"email": "rev@example.com"})
        case_id = await _seed_case_with_team(db, (me["id"], "reviewer"))
        doc_id = await _seed_doc(db, case_id, status="under_review")
        r = await client.post(
            f"/api/v1/documents/{doc_id}/reject",
            json={"reason": "Missing exemption", "details": "S.22 not applied"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        rej_id = body["rejection_id"]

        # Rejection persisted with status="open"
        rej = await db["document_rejections"].find_one({"id": rej_id})
        assert rej["status"] == "open"
        assert rej["reason"] == "Missing exemption"
        assert rej["rejected_by_role"] == "reviewer"

        # Document status flipped to "rejected"
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["status"] == "rejected"

        # Audit log entry
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "document_rejected" for e in case.get("audit_log", []))

    async def test_reject_document_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.post(
            "/api/v1/documents/ghost/reject",
            json={"reason": "x"},
        )
        assert r.status_code == 404

    async def test_reject_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_doc(db, case_id="ghost-case")
        r = await client.post(
            f"/api/v1/documents/{doc_id}/reject",
            json={"reason": "x"},
        )
        assert r.status_code == 404
        assert "Case not found" in r.text

    @pytest.mark.parametrize("case_role", ["legal", "sme", "third_party"])
    async def test_reject_forbidden_for_non_rejecter_roles(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        case_role: str,
    ) -> None:
        """legal/sme/third_party cannot reject. Pins can_reject_documents
        False branches."""
        client = await authed_client_factory(role="user", email=f"norej-{case_role}@example.com")
        me = await db.users.find_one({"email": f"norej-{case_role}@example.com"})
        case_id = await _seed_case_with_team(db, (me["id"], case_role))
        doc_id = await _seed_doc(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/reject",
            json={"reason": "x"},
        )
        assert r.status_code == 403
        assert "reviewers and approvers" in r.text

    async def test_reject_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="off-rej@example.com")
        case_id = await _seed_case_with_team(db, ("someone", "reviewer"))
        doc_id = await _seed_doc(db, case_id)
        r = await client.post(
            f"/api/v1/documents/{doc_id}/reject",
            json={"reason": "x"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /{document_id}/rejections
# ---------------------------------------------------------------------------


class TestGetDocumentRejections:
    async def test_team_member_lists_rejections(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="grl@example.com")
        me = await db.users.find_one({"email": "grl@example.com"})
        case_id = await _seed_case_with_team(db, (me["id"], "analyst"))
        doc_id = await _seed_doc(db, case_id)
        await db["document_rejections"].insert_many(
            [
                {
                    "id": "rj1",
                    "document_id": doc_id,
                    "case_id": case_id,
                    "status": "open",
                },
                {
                    "id": "rj2",
                    "document_id": doc_id,
                    "case_id": case_id,
                    "status": "addressed",
                },
            ]
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/rejections")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert {rj["id"] for rj in body["rejections"]} == {"rj1", "rj2"}

    async def test_get_rejections_doc_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.get("/api/v1/documents/ghost/rejections")
        assert r.status_code == 404

    async def test_get_rejections_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        doc_id = await _seed_doc(db, case_id="ghost")
        r = await client.get(f"/api/v1/documents/{doc_id}/rejections")
        assert r.status_code == 404

    async def test_get_rejections_non_team_member_forbidden(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="off-grj@example.com")
        case_id = await _seed_case_with_team(db, ("someone", "analyst"))
        doc_id = await _seed_doc(db, case_id)
        r = await client.get(f"/api/v1/documents/{doc_id}/rejections")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# PUT /rejections/{rejection_id}/address
# ---------------------------------------------------------------------------


class TestAddressRejection:
    async def _seed_open_rejection(
        self,
        db: AsyncIOMotorDatabase,
        user_id: str,
        *,
        resolver_role: str = "analyst",
    ) -> tuple[str, str, str]:
        case_id = await _seed_case_with_team(db, (user_id, resolver_role))
        doc_id = await _seed_doc(db, case_id, status="rejected")
        rejection = {
            "id": "rej-1",
            "case_id": case_id,
            "document_id": doc_id,
            "status": "open",
            "rejected_by": "someone-else",
            "rejected_by_role": "reviewer",
        }
        await db["document_rejections"].insert_one(rejection)
        return case_id, doc_id, "rej-1"

    async def test_analyst_addresses_rejection(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="user", email="addr@example.com")
        me = await db.users.find_one({"email": "addr@example.com"})
        case_id, doc_id, rej_id = await self._seed_open_rejection(db, me["id"])
        r = await client.put(
            f"/api/v1/documents/rejections/{rej_id}/address",
            json={"resolution_notes": "Added the missing exemption."},
        )
        assert r.status_code == 200, r.text
        # Rejection flipped to addressed
        rj = await db["document_rejections"].find_one({"id": rej_id})
        assert rj["status"] == "addressed"
        assert rj["addressed_by"] == me["id"]
        # Document status reverted to under_review
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["status"] == "under_review"
        # Audit log
        case = await db.cases.find_one({"id": case_id})
        assert any(e.get("action") == "rejection_addressed" for e in case.get("audit_log", []))

    async def test_address_rejection_not_found(
        self,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        r = await client.put(
            "/api/v1/documents/rejections/ghost/address",
            json={"resolution_notes": "x"},
        )
        assert r.status_code == 404
        assert "Rejection not found" in r.text

    async def test_address_case_not_found(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        client = await authed_client_factory(role="admin")
        await db["document_rejections"].insert_one(
            {
                "id": "orphan-rej",
                "case_id": "ghost",
                "document_id": "x",
                "status": "open",
            }
        )
        r = await client.put(
            "/api/v1/documents/rejections/orphan-rej/address",
            json={"resolution_notes": "x"},
        )
        assert r.status_code == 404
        assert "Case not found" in r.text

    @pytest.mark.parametrize("case_role", ["legal", "sme", "reviewer", "approver"])
    async def test_address_forbidden_for_non_resolver_roles(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
        case_role: str,
    ) -> None:
        """Only analyst/manager can address. Pins role guard."""
        client = await authed_client_factory(role="user", email=f"noaddr-{case_role}@example.com")
        me = await db.users.find_one({"email": f"noaddr-{case_role}@example.com"})
        case_id, doc_id, rej_id = await self._seed_open_rejection(
            db, me["id"], resolver_role=case_role
        )
        r = await client.put(
            f"/api/v1/documents/rejections/{rej_id}/address",
            json={"resolution_notes": "x"},
        )
        assert r.status_code == 403
        assert "analysts and managers" in r.text

    async def test_address_already_addressed_silently_succeeds(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Pin reality: no state-machine guard on rejection.status. Can
        re-address an already-addressed rejection; second write wins."""
        client = await authed_client_factory(role="user", email="readdr@example.com")
        me = await db.users.find_one({"email": "readdr@example.com"})
        case_id, doc_id, rej_id = await self._seed_open_rejection(db, me["id"])
        r1 = await client.put(
            f"/api/v1/documents/rejections/{rej_id}/address",
            json={"resolution_notes": "first"},
        )
        assert r1.status_code == 200
        r2 = await client.put(
            f"/api/v1/documents/rejections/{rej_id}/address",
            json={"resolution_notes": "second"},
        )
        assert r2.status_code == 200
        rj = await db["document_rejections"].find_one({"id": rej_id})
        assert rj["resolution_notes"] == "second"


# ---------------------------------------------------------------------------
# End-to-end state machine tests
# ---------------------------------------------------------------------------


class TestContestLifecycle:
    async def test_full_contest_lifecycle_file_then_resolve_kept(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """File contest as legal, resolve as analyst. Two different users
        on the same case team."""
        legal_client = await authed_client_factory(role="user", email="lc@example.com")
        analyst_client = await authed_client_factory(role="user", email="ac@example.com")
        legal = await db.users.find_one({"email": "lc@example.com"})
        analyst = await db.users.find_one({"email": "ac@example.com"})
        case_id = await _seed_case_with_team(db, (legal["id"], "legal"), (analyst["id"], "analyst"))
        doc_id = await _seed_doc(
            db,
            case_id,
            redactions=[
                {
                    "id": "r1",
                    "page": 1,
                    "type": "professional",
                    "status": "approved",
                }
            ],
        )
        # 1. File contest
        r1 = await legal_client.post(
            f"/api/v1/documents/{doc_id}/redactions/0/contest",
            json={"redaction_index": 0, "reason": "Public interest"},
        )
        assert r1.status_code == 200
        contest_id = r1.json()["contest_id"]
        # 2. Verify redaction is contested
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["redactions"][0]["status"] == "contested"
        # 3. Resolve as kept
        r2 = await analyst_client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve",
            json={"resolution": "kept", "resolution_notes": "Exemption valid"},
        )
        assert r2.status_code == 200
        # 4. Redaction back to approved
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["redactions"][0]["status"] == "approved"
        assert doc["redactions"][0]["is_contested"] is False


class TestRejectionLifecycle:
    async def test_full_rejection_lifecycle(
        self,
        db: AsyncIOMotorDatabase,
        authed_client_factory,
        patch_routes_db,
    ) -> None:
        """Reject as reviewer, address as analyst."""
        reviewer_client = await authed_client_factory(role="user", email="revc@example.com")
        analyst_client = await authed_client_factory(role="user", email="ana@example.com")
        reviewer = await db.users.find_one({"email": "revc@example.com"})
        analyst = await db.users.find_one({"email": "ana@example.com"})
        case_id = await _seed_case_with_team(
            db, (reviewer["id"], "reviewer"), (analyst["id"], "analyst")
        )
        doc_id = await _seed_doc(db, case_id, status="under_review")
        # 1. Reject
        r1 = await reviewer_client.post(
            f"/api/v1/documents/{doc_id}/reject",
            json={"reason": "Missing exemption"},
        )
        assert r1.status_code == 200
        rej_id = r1.json()["rejection_id"]
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["status"] == "rejected"
        # 2. Address
        r2 = await analyst_client.put(
            f"/api/v1/documents/rejections/{rej_id}/address",
            json={"resolution_notes": "Applied S.22"},
        )
        assert r2.status_code == 200
        doc = await db.documents.find_one({"id": doc_id})
        assert doc["status"] == "under_review"
        rj = await db["document_rejections"].find_one({"id": rej_id})
        assert rj["status"] == "addressed"
