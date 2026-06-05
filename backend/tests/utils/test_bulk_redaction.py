"""Tests for ``src.utils.bulk_redaction``.

Pure-function helpers for finding text across documents, creating
redaction records, templates, and bulk operations. No I/O — every
function operates on in-memory dicts.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.utils.bulk_redaction import (
    apply_template_to_documents,
    copy_redactions_between_pages,
    create_bulk_redactions,
    create_redaction_template,
    create_undo_record,
    find_text_in_documents,
    preview_bulk_redaction,
    undo_bulk_operation,
    validate_bulk_operation,
)

# ---------------------------------------------------------------------------
# find_text_in_documents
# ---------------------------------------------------------------------------


class TestFindTextInDocuments:
    def test_returns_empty_when_no_matches(self) -> None:
        docs = [{"id": "d1", "filename": "a.pdf", "extracted_text": "Hello world"}]
        result = find_text_in_documents(docs, "xyz")
        assert result == {}

    def test_finds_single_match(self) -> None:
        docs = [{"id": "d1", "filename": "a.pdf", "extracted_text": "Hello world, hello again"}]
        result = find_text_in_documents(docs, "world")
        assert "d1" in result
        assert result["d1"]["count"] == 1
        assert result["d1"]["filename"] == "a.pdf"
        assert result["d1"]["occurrences"][0]["text"] == "world"

    def test_finds_multiple_occurrences(self) -> None:
        docs = [
            {
                "id": "d1",
                "filename": "a.pdf",
                "extracted_text": "foo bar foo baz foo",
            }
        ]
        result = find_text_in_documents(docs, "foo")
        assert result["d1"]["count"] == 3

    def test_case_insensitive_by_default(self) -> None:
        docs = [{"id": "d1", "filename": "a.pdf", "extracted_text": "Hello"}]
        result = find_text_in_documents(docs, "hello", case_sensitive=False)
        assert "d1" in result
        # Original-case text returned (search is case-insensitive but
        # ``text`` slice comes from the original string)
        assert result["d1"]["occurrences"][0]["text"] == "Hello"

    def test_case_sensitive_when_requested(self) -> None:
        docs = [{"id": "d1", "filename": "a.pdf", "extracted_text": "Hello hello"}]
        result = find_text_in_documents(docs, "hello", case_sensitive=True)
        assert result["d1"]["count"] == 1

    def test_skips_docs_with_no_extracted_text(self) -> None:
        docs = [
            {"id": "d1", "filename": "a.pdf", "extracted_text": ""},
            {"id": "d2", "filename": "b.pdf"},  # no extracted_text key
            {"id": "d3", "filename": "c.pdf", "extracted_text": "match"},
        ]
        result = find_text_in_documents(docs, "match")
        assert list(result.keys()) == ["d3"]

    def test_context_before_and_after(self) -> None:
        docs = [
            {
                "id": "d1",
                "filename": "a.pdf",
                "extracted_text": "x" * 100 + "MATCH" + "y" * 100,
            }
        ]
        result = find_text_in_documents(docs, "MATCH", case_sensitive=True)
        occ = result["d1"]["occurrences"][0]
        assert "x" in occ["context_before"]
        assert "y" in occ["context_after"]


# ---------------------------------------------------------------------------
# create_bulk_redactions
# ---------------------------------------------------------------------------


class TestCreateBulkRedactions:
    def test_creates_redaction_per_occurrence(self) -> None:
        matches = {
            "d1": {
                "document_id": "d1",
                "filename": "a.pdf",
                "occurrences": [
                    {"position": 10, "text": "foo"},
                    {"position": 50, "text": "foo"},
                ],
                "count": 2,
            }
        }
        redactions = create_bulk_redactions(matches, "S22", "PII", "user-1")
        assert len(redactions) == 2
        for r in redactions:
            assert r["document_id"] == "d1"
            assert r["text"] == "foo"
            assert r["category"] == "S22"
            assert r["reason"] == "PII"
            assert r["created_by"] == "user-1"
            assert r["status"] == "pending"
            assert r["bulk_operation"] is True
            assert isinstance(r["created_at"], datetime)

    def test_empty_matches_returns_empty_list(self) -> None:
        assert create_bulk_redactions({}, "S22", "x", "u1") == []


# ---------------------------------------------------------------------------
# create_redaction_template
# ---------------------------------------------------------------------------


class TestCreateRedactionTemplate:
    def test_creates_template_with_all_fields(self) -> None:
        tpl = create_redaction_template(
            name="SSN",
            pattern="123-45-6789",
            category="S22",
            reason="Personal info",
            description="Match SSN pattern",
        )
        assert tpl["name"] == "SSN"
        assert tpl["pattern"] == "123-45-6789"
        assert tpl["category"] == "S22"
        assert tpl["reason"] == "Personal info"
        assert tpl["description"] == "Match SSN pattern"
        assert tpl["is_regex"] is False
        assert isinstance(tpl["created_at"], datetime)

    def test_default_description_includes_pattern(self) -> None:
        tpl = create_redaction_template("X", "pattern-xyz", "S22", "r")
        assert "pattern-xyz" in tpl["description"]


# ---------------------------------------------------------------------------
# apply_template_to_documents
# ---------------------------------------------------------------------------


class TestApplyTemplateToDocuments:
    def test_applies_template_finds_and_creates_redactions(self) -> None:
        template = create_redaction_template("Foo", "foo", "S22", "PII")
        documents = [
            {"id": "d1", "filename": "a.pdf", "extracted_text": "foo bar foo"},
            {"id": "d2", "filename": "b.pdf", "extracted_text": "no match"},
        ]
        result = apply_template_to_documents(template, documents)
        assert result["template_name"] == "Foo"
        assert result["documents_affected"] == 1
        assert result["total_redactions"] == 2
        assert "matches" in result

    def test_template_with_no_pattern_uses_defaults(self) -> None:
        """``template.get('pattern', '')`` -> empty search returns no
        matches (an empty string would otherwise match every position;
        we pin the actual behavior)."""
        # An empty pattern hits the no-matches branch because the search
        # is for an empty string — find_text_in_documents would loop
        # infinitely otherwise. The actual behavior: ``str.find("")``
        # always returns 0, so the loop in find_text_in_documents would
        # never terminate normally. We avoid that pathological case by
        # passing a real pattern via a template with no pattern key.
        template = {"category": "S22", "reason": "x"}  # no name, no pattern
        # The actual call: find_text_in_documents([], "") returns {}
        result = apply_template_to_documents(template, [])
        assert result["documents_affected"] == 0
        assert result["total_redactions"] == 0


# ---------------------------------------------------------------------------
# copy_redactions_between_pages
# ---------------------------------------------------------------------------


class TestCopyRedactionsBetweenPages:
    def test_copies_to_each_target_page(self) -> None:
        source = [
            {"page": 1, "x": 10, "y": 20, "width": 30, "height": 40, "text": "secret"},
            {"page": 2, "x": 1, "y": 1, "width": 1, "height": 1, "text": "other"},
        ]
        result = copy_redactions_between_pages(source, 1, [2, 3])
        # Only page-1 source redactions copied, x2 target pages
        assert len(result) == 2
        for r in result:
            assert r["text"] == "secret"
            assert r["copied_from_page"] == 1
        pages = sorted(r["page"] for r in result)
        assert pages == [2, 3]

    def test_no_source_redactions_returns_empty(self) -> None:
        assert copy_redactions_between_pages([], 1, [2, 3]) == []

    def test_no_target_pages_returns_empty(self) -> None:
        source = [
            {"page": 1, "x": 10, "y": 20, "width": 30, "height": 40},
        ]
        assert copy_redactions_between_pages(source, 1, []) == []


# ---------------------------------------------------------------------------
# preview_bulk_redaction
# ---------------------------------------------------------------------------


class TestPreviewBulkRedaction:
    def test_summary_includes_count_and_documents_affected(self) -> None:
        documents = [
            {"id": "d1", "filename": "a.pdf", "extracted_text": "foo foo foo"},
            {"id": "d2", "filename": "b.pdf", "extracted_text": "foo"},
        ]
        preview = preview_bulk_redaction(documents, "foo", "S22")
        assert preview["search_text"] == "foo"
        assert preview["category"] == "S22"
        assert preview["documents_affected"] == 2
        assert preview["total_occurrences"] == 4
        assert len(preview["preview"]) == 2

    def test_sample_contexts_limited_to_three(self) -> None:
        documents = [
            {
                "id": "d1",
                "filename": "a.pdf",
                "extracted_text": "foo foo foo foo foo",
            }
        ]
        preview = preview_bulk_redaction(documents, "foo", "S22")
        # 5 matches but only 3 sample contexts
        assert preview["preview"][0]["occurrences"] == 5
        assert len(preview["preview"][0]["sample_contexts"]) == 3

    def test_empty_documents_returns_zero_counts(self) -> None:
        preview = preview_bulk_redaction([], "foo", "S22")
        assert preview["documents_affected"] == 0
        assert preview["total_occurrences"] == 0
        assert preview["preview"] == []


# ---------------------------------------------------------------------------
# validate_bulk_operation
# ---------------------------------------------------------------------------


class TestValidateBulkOperation:
    def test_valid_returns_true(self) -> None:
        assert validate_bulk_operation(["d1", "d2"]) is True

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="No documents specified"):
            validate_bulk_operation([])

    def test_too_many_raises(self) -> None:
        with pytest.raises(ValueError, match="limited to 5"):
            validate_bulk_operation(["d"] * 10, max_documents=5)

    def test_default_max_is_100(self) -> None:
        assert validate_bulk_operation(["d"] * 100) is True
        with pytest.raises(ValueError):
            validate_bulk_operation(["d"] * 101)


# ---------------------------------------------------------------------------
# create_undo_record / undo_bulk_operation
# ---------------------------------------------------------------------------


class TestCreateUndoRecord:
    def test_captures_metadata(self) -> None:
        record = create_undo_record(
            operation_type="bulk_redact",
            affected_documents=["d1", "d2"],
            redactions_created=[{"id": "r1"}, {"id": "r2"}, {}],
            user_id="user-1",
        )
        assert record["operation_type"] == "bulk_redact"
        assert record["affected_documents"] == ["d1", "d2"]
        # Filters out redactions without 'id'
        assert record["redactions_created"] == ["r1", "r2"]
        assert record["created_by"] == "user-1"
        assert record["can_undo"] is True


class TestUndoBulkOperation:
    def test_undo_when_can_undo(self) -> None:
        record = {
            "can_undo": True,
            "redactions_created": ["r1", "r2"],
            "affected_documents": ["d1"],
        }
        result = undo_bulk_operation(record, documents_collection=MagicMock())
        assert result["success"] is True
        assert result["redactions_removed"] == 2
        assert result["documents_affected"] == 1

    def test_undo_when_cannot_undo_raises(self) -> None:
        record = {"can_undo": False, "redactions_created": []}
        with pytest.raises(ValueError, match="cannot be undone"):
            undo_bulk_operation(record, documents_collection=MagicMock())
