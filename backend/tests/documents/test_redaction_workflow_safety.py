"""Redaction workflow safety on the write side: every stored box is valid
(DOC-02/07), approved redactions are protected from plain case-team members
(DOC-16), redactions are addressed by stable id (DOC-23), failed conversions
cannot be approved (DOC-19 follow-up), and downloads carry safe headers
(DOC-21)."""

from __future__ import annotations

from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from tests.factories import make_case, make_document

LETTER = [[612.0, 792.0, 0]]
BOX = {"page": 1, "x": 72.0, "y": 90.0, "width": 120.0, "height": 16.0}


@pytest.fixture
def patch_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    import src.database as db_mod
    import src.dependencies as deps_mod
    from src.documents import contest_routes, document_status_routes, redaction_routes
    from src.documents import routes as documents_routes

    async def _override_get_db():
        return db

    deps = [redaction_routes.get_db, documents_routes.get_db, document_status_routes.get_db]
    for dep in deps:
        app.dependency_overrides[dep] = _override_get_db
    monkeypatch.setattr(contest_routes, "db", db)
    monkeypatch.setattr(contest_routes, "redaction_contests", db["redaction_contests"])
    monkeypatch.setattr(deps_mod, "users", db.users)
    monkeypatch.setattr(db_mod, "users", db.users)
    yield db
    for dep in deps:
        app.dependency_overrides.pop(dep, None)


async def _user(db, authed_client_factory, role: str, email: str):
    client = await authed_client_factory(role=role, email=email)
    me = await db.users.find_one({"email": email})
    return client, me["id"]


async def _case(db, *team: tuple[str, str]) -> str:
    case = make_case(
        case_team=[
            {"user_id": uid, "role": role, "status": "active", "added_at": "2026-01-01"}
            for uid, role in team
        ]
    )
    await db.cases.insert_one(case)
    return case["id"]


async def _doc(db, case_id: str, **extra: Any) -> str:
    fields: dict[str, Any] = {"case_id": case_id, "page_dims": LETTER}
    fields.update(extra)
    doc = make_document(**fields)
    await db.documents.insert_one(doc)
    return doc["id"]


def _approved(rid: str, created_by: str = "someone-else", **extra: Any) -> dict:
    return (
        {"id": rid, "status": "approved", "type": "professional", "created_by": created_by}
        | BOX
        | extra
    )


# ---------------------------------------------------------------------------
# DOC-02 / DOC-07: validation on every write path
# ---------------------------------------------------------------------------


class TestWriteValidation:
    @pytest.mark.parametrize(
        "bad",
        [
            {},
            {"page": 1},
            BOX | {"width": 0},
            BOX | {"height": -5},
            BOX | {"page": 0},
            BOX | {"page": 2},
            BOX | {"x": 600.0},
        ],
    )
    async def test_add_rejects_invalid_box_with_422(
        self, db, authed_client_factory, patch_db, bad: dict
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "analyst", "a1@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "analyst")))
        r = await client.post(f"/api/v1/documents/{doc_id}/redactions", json=bad)
        assert r.status_code == 422, r.text
        assert (await db.documents.find_one({"id": doc_id}))["redactions"] == []

    async def test_add_nan_width_rejected(self, db, authed_client_factory, patch_db) -> None:
        client, uid = await _user(db, authed_client_factory, "analyst", "a2@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "analyst")))
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions",
            content=b'{"page": 1, "x": 1, "y": 1, "width": NaN, "height": 5}',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422, r.text

    async def test_add_page_bounds_come_from_the_real_pdf(
        self, db, authed_client_factory, patch_db
    ) -> None:
        """Without a cached size the PDF itself is read (and cached)."""
        import fitz

        pdf_doc = fitz.open()
        pdf_doc.new_page(width=300, height=300)
        client, uid = await _user(db, authed_client_factory, "analyst", "a3@example.com")
        doc_id = await _doc(
            db, await _case(db, (uid, "analyst")), page_dims=None, content=pdf_doc.tobytes()
        )
        r = await client.post(f"/api/v1/documents/{doc_id}/redactions", json=BOX | {"y": 290})
        assert r.status_code == 422, r.text
        r = await client.post(f"/api/v1/documents/{doc_id}/redactions", json=BOX)
        assert r.status_code == 200, r.text
        assert (await db.documents.find_one({"id": doc_id}))["page_dims"] == [[300.0, 300.0, 0]]

    async def test_add_on_document_without_content_is_409(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "analyst", "a4@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "analyst")), page_dims=None)
        r = await client.post(f"/api/v1/documents/{doc_id}/redactions", json=BOX)
        assert r.status_code == 409, r.text

    async def test_staff_add_is_approved_with_id(self, db, authed_client_factory, patch_db) -> None:
        client, uid = await _user(db, authed_client_factory, "analyst", "a5@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "analyst")))
        r = await client.post(f"/api/v1/documents/{doc_id}/redactions", json=BOX)
        assert r.status_code == 200, r.text
        (stored,) = (await db.documents.find_one({"id": doc_id}))["redactions"]
        assert stored["id"] == r.json()["id"]
        assert stored["status"] == "approved" and r.json()["status"] == "approved"

    async def test_plain_member_add_is_only_a_proposal(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "u1@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "reviewer")))
        r = await client.post(f"/api/v1/documents/{doc_id}/redactions", json=BOX)
        assert r.status_code == 200, r.text
        (stored,) = (await db.documents.find_one({"id": doc_id}))["redactions"]
        assert stored["status"] == "proposed" and stored["type"] == "proposed"

    async def test_edit_cannot_move_box_off_page(self, db, authed_client_factory, patch_db) -> None:
        client, uid = await _user(db, authed_client_factory, "analyst", "a6@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "analyst")), redactions=[_approved("r1")])
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/r1/edit", json={"x": 700, "width": 50}
        )
        assert r.status_code == 422, r.text
        r = await client.put(f"/api/v1/documents/{doc_id}/redactions/r1/edit", json={"width": 0})
        assert r.status_code == 422, r.text
        stored = (await db.documents.find_one({"id": doc_id}))["redactions"][0]
        assert stored["x"] == BOX["x"] and stored["width"] == BOX["width"]

    async def test_propose_validates_and_assigns_id(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "u2@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "legal")))
        body = BOX | {"category": "S22", "reason": "r"}
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/propose", json=body | {"page": 3}
        )
        assert r.status_code == 422, r.text
        r = await client.post(f"/api/v1/documents/{doc_id}/redactions/propose", json=body)
        assert r.status_code == 200, r.text
        (stored,) = (await db.documents.find_one({"id": doc_id}))["redactions"]
        assert stored["id"] and stored["status"] == "proposed"


# ---------------------------------------------------------------------------
# DOC-16: approved redactions are protected
# ---------------------------------------------------------------------------


class TestApprovedRedactionIntegrity:
    async def test_plain_member_cannot_delete_or_move_approved(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "tp@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "third_party")), redactions=[_approved("r1")])
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/r1")
        assert r.status_code == 403, r.text
        r = await client.put(f"/api/v1/documents/{doc_id}/redactions/r1/edit", json={"width": 1})
        assert r.status_code == 403, r.text
        assert len((await db.documents.find_one({"id": doc_id}))["redactions"]) == 1

    async def test_plain_member_cannot_touch_even_own_redaction_once_approved(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "own@example.com")
        doc_id = await _doc(
            db, await _case(db, (uid, "reviewer")), redactions=[_approved("r1", created_by=uid)]
        )
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/r1")
        assert r.status_code == 403, r.text

    async def test_creator_can_delete_own_proposal(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "prop@example.com")
        proposal = BOX | {"id": "p1", "status": "proposed", "type": "proposed", "created_by": uid}
        doc_id = await _doc(db, await _case(db, (uid, "reviewer")), redactions=[proposal])
        r = await client.put(f"/api/v1/documents/{doc_id}/redactions/p1/edit", json={"x": 80})
        assert r.status_code == 200, r.text
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/p1")
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("system_role, case_role", [("analyst", None), ("user", "analyst")])
    async def test_analyst_can_delete_approved(
        self, db, authed_client_factory, patch_db, system_role: str, case_role: str | None
    ) -> None:
        email = f"del-{system_role}@example.com"
        client, uid = await _user(db, authed_client_factory, system_role, email)
        team = [(uid, case_role)] if case_role else []
        doc_id = await _doc(db, await _case(db, *team), redactions=[_approved("r1")])
        r = await client.delete(f"/api/v1/documents/{doc_id}/redactions/r1")
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# DOC-23: stable ids for approve and contest
# ---------------------------------------------------------------------------


class TestStableRedactionIds:
    def _proposal(self, rid: str | None) -> dict:
        rec = BOX | {"status": "proposed", "type": "proposed", "created_by": "x"}
        if rid:
            rec["id"] = rid
        return rec

    async def test_approve_by_id(self, db, authed_client_factory, patch_db) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "ap1@example.com")
        doc_id = await _doc(
            db,
            await _case(db, (uid, "analyst")),
            redactions=[_approved("keep"), self._proposal("p1")],
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/p1/approve", json={"action": "approve"}
        )
        assert r.status_code == 200, r.text
        reds = (await db.documents.find_one({"id": doc_id}))["redactions"]
        assert [(x["id"], x["status"]) for x in reds] == [("keep", "approved"), ("p1", "approved")]

    async def test_legacy_index_fallback_assigns_id(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "ap2@example.com")
        doc_id = await _doc(
            db, await _case(db, (uid, "analyst")), redactions=[self._proposal(None)]
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve", json={"action": "reject"}
        )
        assert r.status_code == 200, r.text
        (red,) = (await db.documents.find_one({"id": doc_id}))["redactions"]
        assert red["status"] == "rejected" and red["id"]

    async def test_index_of_record_with_id_is_not_accepted(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "ap3@example.com")
        doc_id = await _doc(
            db, await _case(db, (uid, "analyst")), redactions=[self._proposal("p1")]
        )
        r = await client.put(
            f"/api/v1/documents/{doc_id}/redactions/0/approve", json={"action": "approve"}
        )
        assert r.status_code == 404, r.text

    async def test_contest_resolution_follows_the_redaction_not_the_index(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "ct1@example.com")
        doc_id = await _doc(
            db,
            await _case(db, (uid, "analyst")),
            redactions=[
                _approved("first"),
                _approved("target"),
                {"id": "rej", "status": "rejected"} | BOX,
            ],
        )
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/target/contest", json={"reason": "why"}
        )
        assert r.status_code == 200, r.text
        contest_id = r.json()["contest_id"]
        contest = await db.redaction_contests.find_one({"id": contest_id})
        assert contest["redaction_id"] == "target"

        # An earlier redaction disappears; indexes shift.
        await db.documents.update_one({"id": doc_id}, {"$pull": {"redactions": {"id": "first"}}})

        r = await client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve", json={"resolution": "kept"}
        )
        assert r.status_code == 200, r.text
        reds = {x["id"]: x for x in (await db.documents.find_one({"id": doc_id}))["redactions"]}
        assert reds["target"]["status"] == "approved"
        assert reds["target"]["is_contested"] is False
        assert reds["rej"]["status"] == "rejected"  # untouched

    async def test_contest_removed_pulls_by_id(self, db, authed_client_factory, patch_db) -> None:
        client, uid = await _user(db, authed_client_factory, "user", "ct2@example.com")
        doc_id = await _doc(db, await _case(db, (uid, "analyst")), redactions=[_approved("t")])
        r = await client.post(
            f"/api/v1/documents/{doc_id}/redactions/t/contest", json={"reason": "x"}
        )
        contest_id = r.json()["contest_id"]
        r = await client.put(
            f"/api/v1/documents/contests/{contest_id}/resolve", json={"resolution": "removed"}
        )
        assert r.status_code == 200, r.text
        assert (await db.documents.find_one({"id": doc_id}))["redactions"] == []


# ---------------------------------------------------------------------------
# Ingest follow-up: failed conversions cannot be approved
# ---------------------------------------------------------------------------


class TestConversionFailedCannotBeApproved:
    async def test_bulk_status_approve_is_409_and_changes_nothing(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, _ = await _user(db, authed_client_factory, "analyst", "st1@example.com")
        case_id = await _case(db)
        ok_id = await _doc(db, case_id, status="new")
        bad_id = await _doc(db, case_id, status="conversion_failed", conversion_failed=True)
        r = await client.put(
            "/api/v1/documents/bulk/status",
            json={"document_ids": [ok_id, bad_id], "status": "approved"},
        )
        assert r.status_code == 409, r.text
        assert bad_id in r.text
        assert (await db.documents.find_one({"id": ok_id}))["status"] == "new"
        assert (await db.documents.find_one({"id": bad_id}))["status"] == "conversion_failed"

    @pytest.mark.parametrize("status", ["approved", "released"])
    async def test_single_status_approve_is_409(
        self, db, authed_client_factory, patch_db, status: str
    ) -> None:
        client, _ = await _user(db, authed_client_factory, "analyst", f"st-{status}@example.com")
        bad_id = await _doc(db, await _case(db), status="conversion_failed", conversion_failed=True)
        r = await client.put(f"/api/v1/documents/{bad_id}/status", json={"status": status})
        assert r.status_code == 409, r.text

    async def test_withholding_a_failed_conversion_is_allowed(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, _ = await _user(db, authed_client_factory, "analyst", "st3@example.com")
        bad_id = await _doc(db, await _case(db), status="conversion_failed", conversion_failed=True)
        r = await client.put(f"/api/v1/documents/{bad_id}/status", json={"status": "withheld"})
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# DOC-21: download headers
# ---------------------------------------------------------------------------


class TestDownloadHeaders:
    async def test_unicode_and_quote_filename_is_safe(
        self, db, authed_client_factory, patch_db
    ) -> None:
        client, _ = await _user(db, authed_client_factory, "analyst", "dl1@example.com")
        doc_id = await _doc(
            db, await _case(db), filename='文件 "x"\r\nSet-Cookie: a=b.pdf', content=b"%PDF-1.4"
        )
        r = await client.get(f"/api/v1/documents/{doc_id}/download")
        assert r.status_code == 200, r.text
        cd = r.headers["content-disposition"]
        assert cd.startswith('attachment; filename="')
        assert "filename*=UTF-8''" in cd
        assert "\r" not in cd and "\n" not in cd and '"x"' not in cd
        assert "set-cookie" not in {
            k.lower() for k in r.headers if k.lower() != "content-disposition"
        }
        assert "no-store" in r.headers["cache-control"]

    async def test_viewer_pdf_is_not_cacheable(self, db, authed_client_factory, patch_db) -> None:
        client, _ = await _user(db, authed_client_factory, "analyst", "dl2@example.com")
        doc_id = await _doc(db, await _case(db), content=b"%PDF-1.4")
        r = await client.get(f"/api/v1/documents/{doc_id}")
        assert r.status_code == 200, r.text
        assert "no-store" in r.headers["cache-control"]
        assert r.headers["x-content-type-options"] == "nosniff"
