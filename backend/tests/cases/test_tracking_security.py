"""AUTH-05: public tracking-number lookup hardening.

- the suffix comes from `secrets` and is long enough that guessing is
  impractical (>= 40 bits);
- the anonymous lookup is rate limited per client IP;
- internal (non-portal) cases are not trackable, and every miss is the same
  404, so the endpoint is not an existence oracle.
"""

from __future__ import annotations

import re
from datetime import datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.cases.utils import (
    TRACKING_SUFFIX_ALPHABET,
    TRACKING_SUFFIX_LENGTH,
    generate_tracking_number,
)
from tests.factories import make_case


@pytest.fixture
def patch_public_routes_db(monkeypatch: pytest.MonkeyPatch, db: AsyncIOMotorDatabase, app):
    from src.cases import public_routes

    async def _override(request=None):
        return db

    monkeypatch.setattr(public_routes, "get_database_from_request", _override)
    yield db


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


class TestTrackingNumberGeneration:
    def test_format_and_suffix_length(self) -> None:
        tn = generate_tracking_number(2026, 7)
        pattern = rf"[A-Z]+-2026-007-[A-Z0-9]{{{TRACKING_SUFFIX_LENGTH}}}"
        assert re.fullmatch(pattern, tn), tn

    def test_suffix_space_is_at_least_40_bits(self) -> None:
        import math

        bits = TRACKING_SUFFIX_LENGTH * math.log2(len(set(TRACKING_SUFFIX_ALPHABET)))
        assert bits >= 40

    def test_suffix_uses_secrets_not_random(self) -> None:
        with patch("src.cases.utils.secrets.choice", return_value="Z") as choice:
            tn = generate_tracking_number(2026, 1)
        assert choice.call_count == TRACKING_SUFFIX_LENGTH
        assert tn.endswith("-" + "Z" * TRACKING_SUFFIX_LENGTH)

    def test_suffixes_are_not_repeated(self) -> None:
        suffixes = {generate_tracking_number(2026, 1).rsplit("-", 1)[1] for _ in range(200)}
        assert len(suffixes) == 200


class TestTrackLookup:
    async def test_portal_case_is_trackable(
        self, app, db: AsyncIOMotorDatabase, patch_public_routes_db
    ) -> None:
        await db.cases.insert_one(
            make_case(
                tracking_number="FOI-2026-001-PORTAL01",
                source="public_portal",
                created_by="system",
                received_date=datetime.utcnow(),
            )
        )
        async with _client(app) as c:
            r = await c.get("/api/v1/cases/public/track/FOI-2026-001-PORTAL01")
        assert r.status_code == 200, r.text

    async def test_internal_case_is_indistinguishable_from_unknown(
        self, app, db: AsyncIOMotorDatabase, patch_public_routes_db
    ) -> None:
        # Internal cases have no received_date; this used to 500 (existence oracle).
        await db.cases.insert_one(
            make_case(tracking_number="FOI-2026-002-INTERNAL", created_by="staff-user-1")
        )
        async with _client(app) as c:
            internal = await c.get("/api/v1/cases/public/track/FOI-2026-002-INTERNAL")
            unknown = await c.get("/api/v1/cases/public/track/FOI-2026-002-NOSUCHCA")
        assert internal.status_code == 404
        assert unknown.status_code == 404
        bodies = [internal.json(), unknown.json()]
        for body in bodies:
            body["error"].pop("correlation_id", None)
        assert bodies[0] == bodies[1]

    async def test_lookup_is_rate_limited(self, app, patch_public_routes_db) -> None:
        async with _client(app) as c:
            codes = [
                (await c.get(f"/api/v1/cases/public/track/FOI-2026-001-GUESS{i:03d}")).status_code
                for i in range(15)
            ]
        assert codes[:10] == [404] * 10
        assert 429 in codes[10:]

    async def test_submitted_case_is_marked_as_portal_case(
        self, app, db: AsyncIOMotorDatabase, patch_public_routes_db
    ) -> None:
        async with _client(app) as c:
            r = await c.post(
                "/api/v1/cases/public/submit",
                json={
                    "title": "Records about X",
                    "description": "Please provide records.",
                    "requester": {"name": "R", "email": "r@example.org"},
                },
            )
            assert r.status_code == 200, r.text
            tn = r.json()["tracking_number"]
            tracked = await c.get(f"/api/v1/cases/public/track/{tn}")
        assert tracked.status_code == 200, tracked.text
        case = await db.cases.find_one({"tracking_number": tn})
        assert case["source"] == "public_portal"
