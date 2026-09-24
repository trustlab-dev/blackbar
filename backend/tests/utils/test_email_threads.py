"""Tests for ``src.utils.email_threads``.

Email thread detection + supersede-chain consolidation. Pure-function
helpers are tested directly; the two async functions
(``find_thread_emails`` and ``consolidate_email_thread``) are tested
through a stub `db` object that mimics the motor collection interface
the production code uses.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
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

    @pytest.mark.parametrize(
        "subject",
        [
            "Budget",
            "Re: Budget",
            "Re: Fwd: Budget",
            "RE: RE: Budget",
            "Fw: Budget",
            "FW:Budget",
            "Re:  Budget ",
            "  Re: Budget",
            "AW: Budget",
            "WG: Budget",
            "SV: Budget",
            "VS: Budget",
            "Antw: Budget",
            "TR: Budget",
            "RV: Budget",
            "Re[2]: Budget",
            "Re [3]: Budget",
            "[External] Budget",
            "[External] Re: Budget",
            "Re: [External] Budget",
            "Re: [EXT] Fwd: RE: Budget",
        ],
    )
    def test_strips_stacked_localised_and_tag_prefixes(self, subject: str) -> None:
        """#74: every leading reply/forward marker and bracketed tag goes."""
        assert normalize_subject(subject) == "budget"

    def test_prefix_words_inside_subject_are_kept(self) -> None:
        assert normalize_subject("Re: Review of RE: tax") == "review of re: tax"
        assert normalize_subject("Revenue report") == "revenue report"


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

    def test_results_are_always_utc_aware(self) -> None:
        """#71: naive and aware dates must be comparable."""
        aware = parse_email_date("Mon, 1 Jan 2024 12:00:00 +0200")
        naive = parse_email_date("Tue, 2 Jan 2024 12:00:00")
        iso = parse_email_date("2024-01-15 09:30:00")
        for dt in (aware, naive, iso):
            assert dt is not None and dt.utcoffset() == timedelta(0)
        assert aware == datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        assert aware < naive  # no TypeError

    def test_rfc_2822_with_comment_and_msg_style(self) -> None:
        assert parse_email_date("Mon, 1 Jan 2024 12:00:00 +0000 (UTC)") == datetime(
            2024, 1, 1, 12, 0, tzinfo=UTC
        )
        # extract_msg dates are stringified datetimes.
        assert parse_email_date("2024-01-01 12:00:00+00:00") == datetime(
            2024, 1, 1, 12, 0, tzinfo=UTC
        )

    def test_unknown_placeholder_returns_none(self) -> None:
        assert parse_email_date("Unknown") is None


# ---------------------------------------------------------------------------
# find_thread_emails (async)
# ---------------------------------------------------------------------------


class _FakeFindCursor:
    """Mimics a Motor cursor: ``to_list(length)`` truncates like the real
    driver, and the cursor can be iterated with ``async for``."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None) -> list[dict]:
        return list(self._docs if length is None else self._docs[:length])

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for doc in self._docs:
            yield doc


class _FakeCollection:
    """Returns every stored doc for any query; the Python-side filter in
    ``find_thread_emails`` is what these unit tests exercise. The Mongo
    query itself is covered against a real database below."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.update_one = AsyncMock()
        self.last_find_query: dict | None = None
        self.last_projection: dict | None = None

    def find(self, query: dict, projection: dict | None = None) -> _FakeFindCursor:
        self.last_find_query = query
        self.last_projection = projection
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
    async def test_groups_by_message_id_headers_not_subject(self) -> None:
        """#73. Replaces ``test_returns_all_with_matching_normalized_subject``,
        which pinned the unconditional subject-only fallback as intended.
        Header-linked emails are grouped; an email that only shares the
        subject (and no participants) is not."""
        docs = [
            {
                "id": "doc-1",
                "message_id": "<m1@x>",
                "thread_metadata": {
                    "normalized_subject": "hello",
                    "in_reply_to": None,
                    "references": [],
                },
            },
            {
                "id": "doc-2",
                "message_id": "<m2@x>",
                "thread_metadata": {
                    "normalized_subject": "hello",
                    "in_reply_to": "<m1@x>",
                    "references": ["<m1@x>"],
                },
            },
            {
                "id": "unrelated",
                "message_id": "<other@y>",
                "thread_metadata": {
                    "normalized_subject": "hello",
                    "from": "carol@y",
                    "to": "dave@y",
                    "date": "Mon, 1 Jan 2024 09:00:00 +0000",
                    "in_reply_to": None,
                    "references": [],
                },
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
                "from": "alice@x",
                "to": "bob@x",
                "date": "Tue, 2 Jan 2024 09:00:00 +0000",
            },
            "case-1",
        )
        assert {d["id"] for d in result} == {"doc-1", "doc-2"}
        assert db.documents.last_find_query["case_id"] == "case-1"

    @pytest.mark.asyncio
    async def test_unrelated_same_subject_not_grouped(self) -> None:
        """#73 repro: two unrelated "Meeting" emails, different
        Message-IDs, no references, no shared participants."""
        a = {
            "id": "a",
            "message_id": "<a@x>",
            "thread_metadata": {
                "normalized_subject": "meeting",
                "from": "alice@x",
                "to": "bob@x",
                "date": "2024-01-01 09:00:00",
                "in_reply_to": None,
                "references": [],
            },
        }
        db = _FakeDB([a])
        ids = {
            "normalized_subject": "meeting",
            "message_id": "<b@y>",
            "in_reply_to": None,
            "references": [],
            "from": "carol@y",
            "to": "dave@y",
            "date": "2024-01-05 09:00:00",
        }
        assert await find_thread_emails(db, ids, "case-1") == []

    @pytest.mark.asyncio
    async def test_reply_found_from_parent_side(self) -> None:
        """An existing reply whose In-Reply-To points at the new email."""
        reply = {
            "id": "reply",
            "message_id": "<r@x>",
            "thread_metadata": {"in_reply_to": "<new@x>", "references": ["<new@x>"]},
        }
        db = _FakeDB([reply])
        ids = {"normalized_subject": "s", "message_id": "<new@x>", "references": []}
        assert [d["id"] for d in await find_thread_emails(db, ids, "c")] == ["reply"]

    @pytest.mark.asyncio
    async def test_siblings_sharing_a_reference_are_grouped(self) -> None:
        sibling = {
            "id": "sib",
            "message_id": "<s@x>",
            "thread_metadata": {"in_reply_to": "<root@x>", "references": ["<root@x>"]},
        }
        db = _FakeDB([sibling])
        ids = {
            "normalized_subject": "s",
            "message_id": "<new@x>",
            "in_reply_to": "<root@x>",
            "references": ["<root@x>"],
        }
        assert [d["id"] for d in await find_thread_emails(db, ids, "c")] == ["sib"]

    @pytest.mark.parametrize(
        "existing_from,existing_to,existing_date,expected",
        [
            # Same participants (reversed), 3 days apart -> heuristic match.
            ("Bob <bob@x>", "alice@x", "Thu, 4 Jan 2024 09:00:00 +0000", True),
            # One shared participant is enough overlap.
            ("carol@x", "Alice <ALICE@x>, erin@x", "Thu, 4 Jan 2024 09:00:00 +0000", True),
            # Same participants but 45 days apart -> no match.
            ("bob@x", "alice@x", "Fri, 16 Feb 2024 09:00:00 +0000", False),
            # Within 30 days but no shared participant -> no match.
            ("carol@y", "dave@y", "Thu, 4 Jan 2024 09:00:00 +0000", False),
            # Undated existing email -> heuristic cannot apply.
            ("bob@x", "alice@x", "Unknown", False),
        ],
    )
    @pytest.mark.asyncio
    async def test_subject_heuristic_scoped_by_participants_and_time(
        self, existing_from: str, existing_to: str, existing_date: str, expected: bool
    ) -> None:
        existing = {
            "id": "e",
            "message_id": "<e@x>",
            "thread_metadata": {
                "normalized_subject": "budget",
                "from": existing_from,
                "to": existing_to,
                "date": existing_date,
                "in_reply_to": None,
                "references": [],
            },
        }
        db = _FakeDB([existing])
        ids = {
            "normalized_subject": "budget",
            "message_id": "<n@x>",
            "in_reply_to": None,
            "references": [],
            "from": "Alice <alice@x>",
            "to": "bob@x",
            "date": "Mon, 1 Jan 2024 09:00:00 +0000",
        }
        result = await find_thread_emails(db, ids, "case-1")
        assert (result == [existing]) is expected

    @pytest.mark.asyncio
    async def test_requires_case_id(self) -> None:
        """#73. Replaces ``test_works_without_case_id``, which pinned a
        case-less query that matched emails across every case."""
        db = _FakeDB([{"id": "x", "message_id": "<m@x>", "thread_metadata": {}}])
        result = await find_thread_emails(
            db,
            {"normalized_subject": "hi", "message_id": "<m@x>", "references": []},
            None,
        )
        assert result == []
        assert db.documents.last_find_query is None

    @pytest.mark.asyncio
    async def test_excludes_the_new_email_itself(self) -> None:
        own = {"id": "new", "message_id": "<m@x>", "thread_metadata": {}}
        db = _FakeDB([own])
        result = await find_thread_emails(
            db,
            {"normalized_subject": "s", "message_id": "<m@x>", "references": []},
            "c",
            exclude_id="new",
        )
        assert result == []
        assert db.documents.last_find_query["id"] == {"$ne": "new"}

    @pytest.mark.asyncio
    async def test_evaluates_more_than_100_candidates(self) -> None:
        """#72: every candidate is evaluated, not just the first 100, and
        only the fields the thread logic needs are fetched."""
        docs = [
            {
                "id": f"e{i}",
                "message_id": f"<m{i}@x>",
                "thread_metadata": {"normalized_subject": "budget", "references": ["<root@x>"]},
            }
            for i in range(150)
        ]
        db = _FakeDB(docs)
        ids = {
            "normalized_subject": "budget",
            "message_id": "<new@x>",
            "in_reply_to": "<root@x>",
            "references": ["<root@x>"],
        }
        result = await find_thread_emails(db, ids, "c")
        assert len(result) == 150
        assert {"e0", "e100", "e149"} <= {d["id"] for d in result}
        projection = db.documents.last_projection
        assert projection is not None
        assert "content" not in projection and "text_data" not in projection
        assert projection.get("thread_metadata") == 1


class TestFindThreadEmailsAgainstMongo:
    """The same rules through the real Mongo query (not the fake)."""

    @pytest.mark.asyncio
    async def test_real_query_scopes_to_case_and_links(self, db) -> None:
        def email(doc_id: str, case_id: str, msg_id: str, **tm) -> dict:
            return {
                "id": doc_id,
                "case_id": case_id,
                "mime_type": "message/rfc822",
                "message_id": msg_id,
                "upload_date": datetime(2024, 1, 1),
                "content": b"not projected",
                "thread_metadata": {
                    "normalized_subject": "budget",
                    "in_reply_to": None,
                    "references": [],
                    **tm,
                },
            }

        await db.documents.insert_many(
            [
                email("parent", "c1", "<p@x>"),
                email("child", "c1", "<c@x>", in_reply_to="<new@x>", references=["<new@x>"]),
                email("other-case", "c2", "<o@x>", in_reply_to="<p@x>", references=["<p@x>"]),
                email(
                    "same-subject-stranger",
                    "c1",
                    "<s@y>",
                    **{"from": "zed@y", "to": "yan@y", "date": "Mon, 1 Jan 2024 09:00:00"},
                ),
                email("self", "c1", "<new@x>"),
            ]
        )
        # 120 more linked emails so the old 100-document cap would show.
        await db.documents.insert_many(
            [email(f"bulk{i}", "c1", f"<b{i}@x>", references=["<p@x>"]) for i in range(120)]
        )
        ids = {
            "normalized_subject": "budget",
            "message_id": "<new@x>",
            "in_reply_to": "<p@x>",
            "references": ["<p@x>"],
            "from": "alice@x",
            "to": "bob@x",
            "date": "Mon, 1 Jan 2024 10:00:00 +0000",
        }
        result = await find_thread_emails(db, ids, "c1", exclude_id="self")
        found = {d["id"] for d in result}
        assert {"parent", "child"} <= found
        assert len([f for f in found if f.startswith("bulk")]) == 120
        assert "other-case" not in found
        assert "same-subject-stranger" not in found
        assert "self" not in found
        assert all("content" not in d for d in result)


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
    async def test_mixed_aware_and_naive_dates_do_not_raise(self) -> None:
        """#71: a +0000 header, a zone-less header and a naive upload_date."""
        new_doc = {
            "id": "new",
            "filename": "new.eml",
            "thread_metadata": {"date": "Tue, 2 Jan 2024 12:00:00"},
            "upload_date": datetime.utcnow(),
        }
        old = {
            "id": "old",
            "filename": "old.eml",
            "thread_metadata": {"date": "Mon, 1 Jan 2024 12:00:00 +0000"},
            "upload_date": datetime(2024, 1, 1),
        }
        undated = {"id": "u", "filename": "u.eml", "upload_date": datetime(2023, 1, 1)}
        db = _FakeDB([])
        result = await consolidate_email_thread(db, new_doc, [old, undated])
        assert result["canonical_id"] == "new"
        assert set(result["superseded_ids"]) == {"old", "u"}

    @pytest.mark.asyncio
    async def test_header_date_beats_upload_date(self) -> None:
        """#75 repro 5d: an email dated 2020 uploaded today must not
        supersede an existing email dated 2025."""
        new_doc = {
            "id": "n",
            "filename": "n.eml",
            "thread_metadata": {"date": "Wed, 1 Jan 2020 00:00:00 +0000"},
            "upload_date": datetime(2026, 9, 23),
        }
        existing = {
            "id": "x",
            "filename": "x.eml",
            "thread_metadata": {"date": "Sun, 1 Jun 2025 00:00:00 +0000"},
            "upload_date": datetime(2025, 6, 1),
        }
        db = _FakeDB([])
        result = await consolidate_email_thread(db, new_doc, [existing])
        assert result["action"] == "mark_new_as_superseded"
        assert result["canonical_id"] == "x"
        assert result["superseded_ids"] == ["n"]

    @pytest.mark.asyncio
    async def test_own_record_in_thread_list_is_ignored(self) -> None:
        """#75: the new email's own DB row must never supersede it (or be
        superseded by it)."""
        new_doc = {
            "id": "n",
            "filename": "n.eml",
            "thread_metadata": {"date": "Wed, 1 Jan 2020 00:00:00 +0000"},
            "upload_date": datetime(2026, 9, 23),
        }
        self_row = {**new_doc, "thread_metadata": {"date": "Wed, 1 Jan 2020 00:00:00 +0000"}}
        db = _FakeDB([])
        result = await consolidate_email_thread(db, new_doc, [self_row])
        assert result["action"] == "none"
        assert result["canonical_id"] == "n"
        assert result["superseded_ids"] == []
        db.documents.update_one.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_undated_new_email_does_not_beat_dated_existing(self) -> None:
        """#75 repro 5b: undated emails sort below dated ones, even when
        their upload date is later."""
        new_doc = {
            "id": "n",
            "filename": "n.eml",
            "thread_metadata": {"date": "Unknown"},
            "upload_date": datetime(2026, 9, 23),
        }
        existing = {
            "id": "x",
            "filename": "x.eml",
            "thread_metadata": {"date": "2024-01-01 00:00:00"},
            "upload_date": datetime(2024, 1, 1),
        }
        db = _FakeDB([])
        result = await consolidate_email_thread(db, new_doc, [existing])
        assert result["action"] == "mark_new_as_superseded"
        assert result["canonical_id"] == "x"

    @pytest.mark.asyncio
    async def test_dated_new_email_beats_undated_existing(self) -> None:
        """#75 repro 5c, now deliberate: an existing email with an
        unparseable Date sorts below any dated email."""
        new_doc = {
            "id": "n",
            "filename": "n.eml",
            "thread_metadata": {"date": "2020-01-01 00:00:00"},
            "upload_date": datetime(2026, 9, 23),
        }
        undated = {
            "id": "u",
            "filename": "u.eml",
            "thread_metadata": {"date": "Unknown"},
            "upload_date": datetime(2099, 1, 1),
        }
        db = _FakeDB([])
        result = await consolidate_email_thread(db, new_doc, [undated])
        assert result["canonical_id"] == "n"
        assert result["superseded_ids"] == ["u"]

    @pytest.mark.asyncio
    async def test_new_email_with_unparseable_date_falls_back_to_upload_date(
        self,
    ) -> None:
        """Both dates unparseable: both sort in the undated tier and the
        upload date breaks the tie (the fallback now applies only when
        parsing returns None)."""
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
