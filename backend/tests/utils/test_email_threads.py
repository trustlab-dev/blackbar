"""Tests for ``src.utils.email_threads``.

Email thread detection + supersede-chain consolidation. Pure-function
helpers are tested directly; the two async functions
(``find_thread_emails`` and ``consolidate_email_thread``) are tested
through a stub `db` object that mimics the motor collection interface
the production code uses.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.utils.email_threads import (
    calculate_thread_hash,
    consolidate_email_thread,
    extract_thread_identifiers,
    find_thread_emails,
    normalize_subject,
    parse_email_date,
)

# ---------------------------------------------------------------------------
# normalize_subject
# ---------------------------------------------------------------------------


class TestNormalizeSubject:
    def test_empty_returns_empty(self) -> None:
        assert normalize_subject("") == ""

    def test_none_returns_empty(self) -> None:
        assert normalize_subject(None) == ""  # type: ignore[arg-type]

    def test_strips_re_prefix(self) -> None:
        assert normalize_subject("Re: Hello") == "hello"

    def test_strips_re_upper_prefix(self) -> None:
        assert normalize_subject("RE: Hello") == "hello"

    def test_strips_fwd_prefix(self) -> None:
        assert normalize_subject("Fwd: Hello") == "hello"

    def test_strips_fw_prefix(self) -> None:
        assert normalize_subject("FW: Hello") == "hello"

    def test_collapses_whitespace(self) -> None:
        assert normalize_subject("Hello  \t  world") == "hello world"

    def test_no_prefix_just_lowercases(self) -> None:
        assert normalize_subject("Plain Subject") == "plain subject"

    def test_lowercases_result(self) -> None:
        assert normalize_subject("Re: MIXED Case") == "mixed case"


# ---------------------------------------------------------------------------
# extract_thread_identifiers
# ---------------------------------------------------------------------------


class TestExtractThreadIdentifiers:
    def test_extracts_full_set_of_headers(self) -> None:
        text = "\n".join(
            [
                "Subject: Re: Hello World",
                "From: alice@example.test",
                "To: bob@example.test",
                "Date: Mon, 1 Jan 2024 12:00:00 +0000",
                "In-Reply-To: <abc@example.test>",
                "References: <abc@example.test> <def@example.test>",
                "",
                "Body...",
            ]
        )
        ids = extract_thread_identifiers(text, "<xyz@example.test>")
        assert ids["subject"] == "Re: Hello World"
        assert ids["normalized_subject"] == "hello world"
        assert ids["from"] == "alice@example.test"
        assert ids["to"] == "bob@example.test"
        assert ids["date"] == "Mon, 1 Jan 2024 12:00:00 +0000"
        assert ids["in_reply_to"] == "<abc@example.test>"
        assert ids["references"] == ["<abc@example.test>", "<def@example.test>"]
        assert ids["message_id"] == "<xyz@example.test>"

    def test_missing_headers_return_none_or_empty(self) -> None:
        ids = extract_thread_identifiers("no headers at all\n", None)
        assert ids["subject"] is None
        assert ids["from"] is None
        assert ids["in_reply_to"] is None
        assert ids["references"] == []
        assert ids["message_id"] is None

    def test_only_first_20_lines_scanned(self) -> None:
        """A header on line 21 is ignored."""
        text = ("noise\n" * 20) + "Subject: Late Header\n"
        ids = extract_thread_identifiers(text, None)
        assert ids["subject"] is None


# ---------------------------------------------------------------------------
# calculate_thread_hash
# ---------------------------------------------------------------------------


class TestCalculateThreadHash:
    def test_is_deterministic(self) -> None:
        a = calculate_thread_hash("hello", ["alice@x", "bob@x"])
        b = calculate_thread_hash("hello", ["alice@x", "bob@x"])
        assert a == b

    def test_participant_order_does_not_matter(self) -> None:
        a = calculate_thread_hash("hello", ["alice@x", "bob@x"])
        b = calculate_thread_hash("hello", ["bob@x", "alice@x"])
        assert a == b

    def test_participant_case_does_not_matter(self) -> None:
        a = calculate_thread_hash("hello", ["Alice@X", "BOB@X"])
        b = calculate_thread_hash("hello", ["alice@x", "bob@x"])
        assert a == b

    def test_different_subjects_produce_different_hashes(self) -> None:
        a = calculate_thread_hash("hello", ["alice@x"])
        b = calculate_thread_hash("world", ["alice@x"])
        assert a != b

    def test_empty_participants_filtered(self) -> None:
        """Falsy entries are dropped before sorting."""
        a = calculate_thread_hash("hello", ["alice@x", "", None])  # type: ignore[list-item]
        b = calculate_thread_hash("hello", ["alice@x"])
        assert a == b

    def test_returns_sha256_hex(self) -> None:
        h = calculate_thread_hash("hi", ["a@x"])
        # SHA-256 hex = 64 chars
        assert len(h) == 64
        # Should match manual computation
        expected = hashlib.sha256(b"hi|a@x").hexdigest()
        assert h == expected


# ---------------------------------------------------------------------------
# parse_email_date
# ---------------------------------------------------------------------------


class TestParseEmailDate:
    def test_rfc_2822_format(self) -> None:
        dt = parse_email_date("Mon, 1 Jan 2024 12:00:00 +0000")
        assert dt is not None
        assert dt.year == 2024 and dt.month == 1 and dt.day == 1

    def test_format_without_timezone(self) -> None:
        dt = parse_email_date("1 Jan 2024 12:00:00")
        assert dt is not None

    def test_iso_format(self) -> None:
        dt = parse_email_date("2024-01-15 09:30:00")
        assert dt is not None
        assert dt.year == 2024 and dt.month == 1 and dt.day == 15

    def test_empty_string_returns_none(self) -> None:
        assert parse_email_date("") is None

    def test_none_returns_none(self) -> None:
        assert parse_email_date(None) is None  # type: ignore[arg-type]

    def test_unparseable_returns_none(self) -> None:
        assert parse_email_date("not a date at all") is None


# ---------------------------------------------------------------------------
# find_thread_emails (async)
# ---------------------------------------------------------------------------


class _FakeFindCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int) -> list[dict]:
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.update_one = AsyncMock()
        self.last_find_query: dict | None = None

    def find(self, query: dict) -> _FakeFindCursor:  # pragma: no cover - trivial
        self.last_find_query = query
        return _FakeFindCursor(self._docs)


class _FakeDB:
    def __init__(self, docs: list[dict]) -> None:
        self.documents = _FakeCollection(docs)


class TestFindThreadEmails:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_normalized_subject(self) -> None:
        db = _FakeDB([])
        result = await find_thread_emails(
            db,
            {"normalized_subject": "", "message_id": None, "in_reply_to": None, "references": []},
            "case-1",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_with_matching_normalized_subject(self) -> None:
        """The fallback ``is_same_thread = True`` after the message-id
        checks means every subject-match in the case is treated as
        belonging to the thread. Pin that intentional behavior."""
        docs = [
            {
                "id": "doc-1",
                "message_id": "<m1@x>",
                "thread_metadata": {"in_reply_to": None, "references": []},
            },
            {
                "id": "doc-2",
                "message_id": "<m2@x>",
                "thread_metadata": {"in_reply_to": "<m1@x>", "references": ["<m1@x>"]},
            },
        ]
        db = _FakeDB(docs)
        result = await find_thread_emails(
            db,
            {
                "normalized_subject": "hello",
                "message_id": "<m3@x>",
                "in_reply_to": "<m2@x>",
                "references": ["<m1@x>", "<m2@x>"],
            },
            "case-1",
        )
        assert {d["id"] for d in result} == {"doc-1", "doc-2"}
        # The query restricts to the normalized subject and case_id
        assert db.documents.last_find_query["thread_metadata.normalized_subject"] == "hello"
        assert db.documents.last_find_query["case_id"] == "case-1"

    @pytest.mark.asyncio
    async def test_works_without_case_id(self) -> None:
        db = _FakeDB([])
        result = await find_thread_emails(
            db,
            {"normalized_subject": "hi", "message_id": None, "in_reply_to": None, "references": []},
            None,
        )
        assert result == []
        assert "case_id" not in db.documents.last_find_query


# ---------------------------------------------------------------------------
# consolidate_email_thread (async)
# ---------------------------------------------------------------------------


class TestConsolidateEmailThread:
    @pytest.mark.asyncio
    async def test_no_thread_returns_none_action(self) -> None:
        db = _FakeDB([])
        result = await consolidate_email_thread(
            db,
            {"id": "doc-new", "filename": "new.eml"},
            [],
        )
        assert result["action"] == "none"
        assert result["canonical_id"] == "doc-new"
        assert result["superseded_ids"] == []

    @pytest.mark.asyncio
    async def test_new_is_older_marks_new_superseded(self) -> None:
        """When an existing email is newer, the new email is the
        superseded one."""
        existing_date = datetime(2024, 6, 1, 12, 0, 0)
        new_date = datetime(2024, 1, 1, 12, 0, 0)

        existing = {
            "id": "doc-old-in-db",  # actually newer in time
            "filename": "newer.eml",
            "thread_metadata": {"date": existing_date.strftime("%Y-%m-%d %H:%M:%S")},
            "upload_date": existing_date,
        }
        new_doc = {
            "id": "doc-new",
            "filename": "older-uploaded-later.eml",
            "thread_metadata": {"date": new_date.strftime("%Y-%m-%d %H:%M:%S")},
            "upload_date": new_date,
        }
        db = _FakeDB([])
        result = await consolidate_email_thread(db, new_doc, [existing])
        assert result["action"] == "mark_new_as_superseded"
        assert result["superseded_by"] == "doc-old-in-db"
        assert result["canonical_id"] == "doc-old-in-db"
        assert result["superseded_ids"] == ["doc-new"]
        db.documents.update_one.assert_awaited()  # was called

    @pytest.mark.asyncio
    async def test_new_is_latest_marks_older_superseded(self) -> None:
        old_date = datetime(2024, 1, 1, 12, 0, 0)
        new_date = datetime(2024, 6, 1, 12, 0, 0)

        existing = {
            "id": "doc-old",
            "filename": "old.eml",
            "thread_metadata": {"date": old_date.strftime("%Y-%m-%d %H:%M:%S")},
            "upload_date": old_date,
        }
        new_doc = {
            "id": "doc-new",
            "filename": "new.eml",
            "thread_metadata": {"date": new_date.strftime("%Y-%m-%d %H:%M:%S")},
            "upload_date": new_date,
        }
        db = _FakeDB([])
        result = await consolidate_email_thread(db, new_doc, [existing])
        assert result["action"] == "mark_older_as_superseded"
        assert result["superseded_count"] == 1
        assert result["canonical_id"] == "doc-new"
        assert result["superseded_ids"] == ["doc-old"]
        # update_one called at least twice (mark old + mark new as active)
        assert db.documents.update_one.await_count >= 2

    @pytest.mark.asyncio
    async def test_new_email_with_unparseable_date_falls_back_to_upload_date(
        self,
    ) -> None:
        new_doc = {
            "id": "doc-new",
            "filename": "new.eml",
            "thread_metadata": {"date": "not a date"},
            "upload_date": datetime(2024, 6, 1),
        }
        existing = {
            "id": "doc-old",
            "filename": "old.eml",
            "thread_metadata": {"date": "also unparseable"},
            "upload_date": datetime(2024, 1, 1),
        }
        db = _FakeDB([])
        result = await consolidate_email_thread(db, new_doc, [existing])
        # new (Jun) > existing (Jan) -> mark older
        assert result["action"] == "mark_older_as_superseded"
