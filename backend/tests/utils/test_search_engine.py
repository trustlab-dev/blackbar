"""Tests for ``src.utils.search_engine``.

Pure-function helpers — text highlighting, MongoDB query builders,
relevance ranking, keyword extraction, and result formatting. No I/O.
"""

from __future__ import annotations

from src.utils.search_engine import (
    build_search_query,
    create_search_index_config,
    extract_keywords,
    format_search_results,
    highlight_text,
    rank_results,
    search_cases,
    search_documents,
)

# ---------------------------------------------------------------------------
# highlight_text
# ---------------------------------------------------------------------------


class TestHighlightText:
    def test_finds_single_match_with_context(self) -> None:
        text = "Lorem ipsum dolor sit amet."
        matches = highlight_text(text, "dolor")
        assert len(matches) == 1
        m = matches[0]
        assert m["match"] == "dolor"
        assert "ipsum" in m["before"]
        assert "sit" in m["after"]

    def test_finds_multiple_matches(self) -> None:
        text = "foo bar foo baz foo"
        matches = highlight_text(text, "foo")
        assert len(matches) == 3

    def test_case_insensitive(self) -> None:
        matches = highlight_text("Hello World", "hello")
        assert len(matches) == 1
        # The slice preserves original case
        assert matches[0]["match"] == "Hello"

    def test_empty_text_returns_empty(self) -> None:
        assert highlight_text("", "x") == []

    def test_empty_query_returns_empty(self) -> None:
        assert highlight_text("text", "") == []

    def test_no_match_returns_empty(self) -> None:
        assert highlight_text("hello world", "xyz") == []

    def test_ellipsis_added_when_context_truncated(self) -> None:
        text = "x" * 200 + "MATCH" + "y" * 200
        matches = highlight_text(text, "MATCH", context_chars=50)
        m = matches[0]
        assert m["before"].startswith("...")
        assert m["after"].endswith("...")

    def test_no_ellipsis_when_match_at_boundary(self) -> None:
        text = "MATCH" + "y" * 50
        matches = highlight_text(text, "MATCH", context_chars=100)
        m = matches[0]
        # before starts at position 0, no leading ellipsis
        assert not m["before"].startswith("...")


# ---------------------------------------------------------------------------
# build_search_query
# ---------------------------------------------------------------------------


class TestBuildSearchQuery:
    def test_empty_query_returns_empty(self) -> None:
        assert build_search_query("") == {}

    def test_regex_query_with_fields(self) -> None:
        q = build_search_query("hello world", fields=["name", "title"])
        assert "$or" in q
        assert len(q["$or"]) == 2
        # Special regex chars are escaped
        q2 = build_search_query("a.b", fields=["name"])
        assert "a\\.b" in q2["$or"][0]["name"]["$regex"]
        # case-insensitive option present
        assert q["$or"][0]["name"]["$options"] == "i"

    def test_text_query_without_fields(self) -> None:
        q = build_search_query("hello", fields=None)
        assert q == {"$text": {"$search": "hello"}}


# ---------------------------------------------------------------------------
# search_documents / search_cases
# ---------------------------------------------------------------------------


class TestSearchDocuments:
    def test_builds_or_query_over_doc_fields(self) -> None:
        cfg = search_documents("alice")
        assert "$or" in cfg["query"]
        # filename / extracted_text / submitter_name / submitter_email
        fields = [list(c.keys())[0] for c in cfg["query"]["$or"]]
        assert set(fields) == {
            "filename",
            "extracted_text",
            "submitter_name",
            "submitter_email",
        }
        assert cfg["limit"] == 50
        assert cfg["sort"] == [("uploaded_at", -1)]

    def test_filters_are_merged(self) -> None:
        cfg = search_documents("x", filters={"case_id": "c1"})
        assert cfg["query"]["case_id"] == "c1"

    def test_custom_limit(self) -> None:
        assert search_documents("x", limit=10)["limit"] == 10


class TestSearchCases:
    def test_builds_or_query_over_case_fields(self) -> None:
        cfg = search_cases("alice")
        fields = [list(c.keys())[0] for c in cfg["query"]["$or"]]
        assert set(fields) == {
            "case_number",
            "title",
            "description",
            "requester_name",
            "requester_email",
        }
        assert cfg["sort"] == [("created_at", -1)]

    def test_filters_applied(self) -> None:
        cfg = search_cases("x", filters={"status": "open"})
        assert cfg["query"]["status"] == "open"


# ---------------------------------------------------------------------------
# rank_results
# ---------------------------------------------------------------------------


class TestRankResults:
    def test_filename_match_boosts_score(self) -> None:
        results = [
            {"filename": "no-match.pdf", "extracted_text": ""},
            {"filename": "alice-report.pdf", "extracted_text": ""},
        ]
        ranked = rank_results(results, "alice")
        # alice-report.pdf should rank first (filename hit = +10)
        assert ranked[0]["filename"] == "alice-report.pdf"
        assert ranked[0]["relevance_score"] == 10
        assert ranked[1]["relevance_score"] == 0

    def test_multiple_text_occurrences_increase_score(self) -> None:
        results = [
            {"filename": "x.pdf", "extracted_text": "alice alice alice"},
            {"filename": "y.pdf", "extracted_text": "alice"},
        ]
        ranked = rank_results(results, "alice")
        assert ranked[0]["filename"] == "x.pdf"
        # 5 (text match) + 3 (occurrences) = 8 vs 5 + 1 = 6
        assert ranked[0]["relevance_score"] == 8
        assert ranked[1]["relevance_score"] == 6

    def test_submitter_match(self) -> None:
        results = [
            {"filename": "a.pdf", "submitter_name": "Alice Smith"},
        ]
        ranked = rank_results(results, "alice")
        assert ranked[0]["relevance_score"] == 8


# ---------------------------------------------------------------------------
# create_search_index_config
# ---------------------------------------------------------------------------


class TestCreateSearchIndexConfig:
    def test_returns_both_collections(self) -> None:
        cfg = create_search_index_config()
        assert "documents" in cfg
        assert "cases" in cfg
        assert cfg["documents"]["weights"]["filename"] == 10
        assert cfg["cases"]["weights"]["case_number"] == 10


# ---------------------------------------------------------------------------
# extract_keywords
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    def test_removes_stop_words(self) -> None:
        keywords = extract_keywords("the quick brown fox jumps over the lazy dog")
        # Pin the actual stop-word list: 'the' is filtered; 'over' is NOT
        # in this implementation's stop_words set (the list is small).
        assert "the" not in keywords
        assert "quick" in keywords
        assert "fox" in keywords
        # "over" stays because it's not in the stop_words set
        assert "over" in keywords

    def test_drops_short_words(self) -> None:
        keywords = extract_keywords("a b cat dog")
        assert "cat" in keywords
        assert "dog" in keywords
        # Single-char words filtered (len > 2 requirement)
        assert "a" not in keywords
        assert "b" not in keywords

    def test_lowercases_output(self) -> None:
        keywords = extract_keywords("ALICE BOB")
        assert "alice" in keywords
        assert "bob" in keywords

    def test_handles_punctuation(self) -> None:
        keywords = extract_keywords("alice, bob; charlie.")
        assert set(keywords) == {"alice", "bob", "charlie"}


# ---------------------------------------------------------------------------
# format_search_results
# ---------------------------------------------------------------------------


class TestFormatSearchResults:
    def test_formats_document_result(self) -> None:
        results = [
            {
                "id": "d1",
                "filename": "doc.pdf",
                "extracted_text": "alice was here",
                "case_id": "c1",
                "uploaded_at": "2024-01-01",
                "submitter_name": "Alice",
                "relevance_score": 10,
            }
        ]
        formatted = format_search_results(results, "alice")
        f = formatted[0]
        assert f["type"] == "document"
        assert f["title"] == "doc.pdf"
        assert f["relevance_score"] == 10
        assert f["metadata"]["filename"] == "doc.pdf"
        assert "highlights" in f
        assert f["match_count"] == 1

    def test_formats_case_result(self) -> None:
        results = [
            {
                "id": "c1",
                "case_number": "FOI-001",
                "title": "Alice's request",
                "status": "open",
                "created_at": "2024-01-01",
            }
        ]
        formatted = format_search_results(results, "alice")
        f = formatted[0]
        assert f["type"] == "case"
        assert f["title"] == "Alice's request"
        assert f["metadata"]["case_number"] == "FOI-001"

    def test_caps_highlights_at_three(self) -> None:
        results = [
            {
                "id": "d1",
                "filename": "x.pdf",
                "extracted_text": "alice " * 10,
            }
        ]
        formatted = format_search_results(results, "alice")
        # 10 matches but only top 3 highlights retained
        assert len(formatted[0]["highlights"]) == 3
        assert formatted[0]["match_count"] == 10

    def test_skip_highlights_when_disabled(self) -> None:
        results = [
            {
                "id": "d1",
                "filename": "x.pdf",
                "extracted_text": "alice",
            }
        ]
        formatted = format_search_results(results, "alice", include_highlights=False)
        assert "highlights" not in formatted[0]
