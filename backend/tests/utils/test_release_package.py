"""Tests for ``src.utils.release_package`` — CRITICAL PATH (audit 5j).

Final-PDF redaction generation. Bugs here leak data through the ZIP
package handed to FOI requesters, so the audit requires 100% line + branch
coverage on this module.

The module is pure Python (no I/O, no external services) — it builds an
in-memory ZIP from a list of document dicts and a Jinja2 template, so
every branch is reachable from a synthetic input.

Audit Section 11 finding (B49, surfaced 2026-05-13 during Sub-phase 2.9):
``generate_cover_letter`` and the embedded Jinja2 ``COVER_LETTER_TEMPLATE``
read ``doc.redaction_count`` and ``doc.exemptions`` with attribute access
inside an ``{% if doc.redaction_count > 0 %}`` block. When a released
document's dict lacks either key, Jinja's ``UndefinedError`` propagates
into ``create_release_package``'s except clause and the entire release
pipeline crashes with a generic "Failed to create release package" error.
Every caller MUST pre-populate ``redaction_count: 0`` and
``exemptions: []`` on documents missing them. Mitigation tracked in
Section 11; behavior pinned by ``test_missing_redaction_count_field_crashes_release``.
"""

from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pytest

from src.utils.release_package import (
    COVER_LETTER_TEMPLATE,
    create_release_package,
    generate_cover_letter,
    generate_release_summary,
    get_exemption_description,
)

# ---------------------------------------------------------------------------
# get_exemption_description
# ---------------------------------------------------------------------------


class TestGetExemptionDescription:
    @pytest.mark.parametrize(
        "code,fragment",
        [
            ("S13", "Policy advice"),
            ("S14", "Solicitor-client"),
            ("S15", "law enforcement"),
            ("S16", "intergovernmental"),
            ("S17", "financial or economic"),
            ("S18", "conservation"),
            ("S19", "public safety"),
            ("S20", "security of property"),
            ("S21", "business interests"),
            ("S22", "Personal information"),
            ("S23", "local government"),
        ],
    )
    def test_known_codes_return_descriptions(self, code: str, fragment: str) -> None:
        desc = get_exemption_description(code)
        assert fragment.lower() in desc.lower()

    def test_unknown_code_returns_generic_default(self) -> None:
        assert get_exemption_description("S99") == "Exemption applied"

    def test_empty_string_returns_default(self) -> None:
        assert get_exemption_description("") == "Exemption applied"


# ---------------------------------------------------------------------------
# generate_cover_letter
# ---------------------------------------------------------------------------


class TestGenerateCoverLetter:
    def test_renders_basic_template(self) -> None:
        case_data = {
            "case_number": "FOI-2026-0001",
            "title": "Records about X",
            "requester_name": "Alice",
            "created_at": "2026-01-15",
            "officer_name": "Officer Smith",
            "officer_title": "Senior FOI Officer",
        }
        documents = [
            {
                "filename": "doc1.pdf",
                "status": "released",
                "exemptions": [],
                "redaction_count": 0,
            }
        ]
        letter = generate_cover_letter(case_data, documents)

        assert "FOI-2026-0001" in letter
        assert "Records about X" in letter
        assert "Alice" in letter
        assert "Officer Smith" in letter
        assert "Senior FOI Officer" in letter
        assert "doc1.pdf" in letter
        # Released in full (no redactions / no exemptions)
        assert "Released in full" in letter
        # No documents withheld → withheld section absent
        assert "DOCUMENTS WITHHELD" not in letter

    def test_treats_approved_status_as_released(self) -> None:
        """The implementation treats both 'released' and 'approved' as
        releasable. Pin that behavior."""
        case_data = {"case_number": "C1", "requester_name": "Alice"}
        documents = [
            {
                "filename": "approved.pdf",
                "status": "approved",
                "exemptions": [],
                "redaction_count": 0,
            }
        ]
        letter = generate_cover_letter(case_data, documents)
        assert "approved.pdf" in letter
        assert "releasing 1 document" in letter

    def test_renders_with_redactions_and_exemptions(self) -> None:
        case_data = {"case_number": "C1", "requester_name": "Alice"}
        documents = [
            {
                "filename": "doc.pdf",
                "status": "released",
                "exemptions": ["S22", "S14"],
                "redaction_count": 5,
            }
        ]
        letter = generate_cover_letter(case_data, documents)
        # Exemption codes joined with commas
        assert "Redacted under: S22, S14" in letter
        # Per-code descriptions in the EXEMPTIONS APPLIED section
        assert "S22:" in letter
        assert "S14:" in letter
        assert "Personal information" in letter
        assert "Solicitor-client" in letter
        # Released-in-full marker should NOT appear
        assert "Released in full" not in letter

    def test_renders_withheld_documents_section(self) -> None:
        case_data = {"case_number": "C1", "requester_name": "Alice"}
        documents = [
            {
                "filename": "withheld.pdf",
                "status": "withheld",
                "exemptions": ["S14"],
                "reason": "Subject to solicitor-client privilege.",
            }
        ]
        letter = generate_cover_letter(case_data, documents)
        assert "DOCUMENTS WITHHELD" in letter
        assert "withheld.pdf" in letter
        assert "S14" in letter
        assert "Subject to solicitor-client privilege" in letter
        # No documents released → released count is 0, no released-count line
        assert "releasing 0" not in letter  # the {% if released_count > 0 %} branch hides it
        # No "DOCUMENTS RELEASED" entries listed
        # (the section heading is always rendered but the list is empty)

    def test_renders_mixed_released_and_withheld(self) -> None:
        case_data = {"case_number": "C1", "requester_name": "Alice"}
        documents = [
            {
                "filename": "released.pdf",
                "status": "released",
                "exemptions": [],
                "redaction_count": 0,
            },
            {
                "filename": "withheld.pdf",
                "status": "withheld",
                "exemptions": ["S14"],
                "reason": "Privileged.",
            },
        ]
        letter = generate_cover_letter(case_data, documents)
        assert "releasing 1 document" in letter
        assert "withholding 1 document" in letter
        assert "released.pdf" in letter
        assert "withheld.pdf" in letter

    def test_uses_defaults_when_case_data_missing(self) -> None:
        """Each ``case_data.get(...)`` has a default fallback. Pin them."""
        letter = generate_cover_letter({}, [])
        assert "Case Number: N/A" in letter
        assert "FOI Officer" in letter
        assert "Information Officer" in letter
        assert "Requester" in letter  # default name

    def test_exemption_descriptions_only_collected_once(self) -> None:
        """Duplicate exemption codes across documents appear once in the
        EXEMPTIONS APPLIED section."""
        documents = [
            {
                "filename": "a.pdf",
                "status": "released",
                "exemptions": ["S22"],
                "redaction_count": 1,
            },
            {
                "filename": "b.pdf",
                "status": "released",
                "exemptions": ["S22"],
                "redaction_count": 1,
            },
        ]
        letter = generate_cover_letter({"case_number": "C1"}, documents)
        # S22 should appear exactly once in the EXEMPTIONS APPLIED section.
        # (It still appears in the per-doc lists.)
        exemptions_section_start = letter.index("EXEMPTIONS APPLIED")
        right_to_review_start = letter.index("RIGHT TO REVIEW")
        exemptions_block = letter[exemptions_section_start:right_to_review_start]
        # The exemption code line is "S22: Personal information"
        assert exemptions_block.count("S22:") == 1


# ---------------------------------------------------------------------------
# generate_release_summary
# ---------------------------------------------------------------------------


class TestGenerateReleaseSummary:
    def test_basic_summary(self) -> None:
        case_data = {"case_number": "FOI-2026-0001", "title": "Records about X"}
        documents = [
            {"filename": "a.pdf", "status": "released", "redaction_count": 0},
        ]
        summary = generate_release_summary(case_data, documents)
        assert "FOI-2026-0001" in summary
        assert "Records about X" in summary
        assert "Total Documents: 1" in summary
        assert "Released: 1" in summary
        assert "Withheld: 0" in summary
        assert "a.pdf" in summary

    def test_documents_with_redactions_show_count_and_exemptions(self) -> None:
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "doc.pdf",
                "status": "released",
                "redaction_count": 3,
                "exemptions": ["S22", "S14"],
            }
        ]
        summary = generate_release_summary(case_data, documents)
        assert "Redactions: 3" in summary
        assert "Exemptions: S22, S14" in summary

    def test_withheld_documents_appear_with_reason(self) -> None:
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "withheld.pdf",
                "status": "withheld",
                "reason": "Privileged document",
            }
        ]
        summary = generate_release_summary(case_data, documents)
        assert "WITHHELD DOCUMENTS" in summary
        assert "withheld.pdf" in summary
        assert "Reason: Privileged document" in summary

    def test_withheld_section_omitted_when_no_withheld(self) -> None:
        case_data = {"case_number": "C1"}
        documents = [{"filename": "a.pdf", "status": "released"}]
        summary = generate_release_summary(case_data, documents)
        assert "WITHHELD DOCUMENTS" not in summary

    def test_defaults_when_case_data_missing(self) -> None:
        summary = generate_release_summary({}, [])
        assert "Case Number: N/A" in summary
        assert "Case Title: N/A" in summary


# ---------------------------------------------------------------------------
# create_release_package
# ---------------------------------------------------------------------------


class TestCreateReleasePackage:
    def test_creates_zip_with_cover_letter_and_summary(self) -> None:
        case_data = {"case_number": "FOI-2026-0001", "requester_name": "Alice"}
        documents = [
            {
                "filename": "doc.pdf",
                "status": "released",
                "content": b"%PDF-1.4\nfake pdf bytes",
                "exemptions": [],
                "redaction_count": 0,
            }
        ]
        zip_bytes = create_release_package(case_data, documents)
        assert isinstance(zip_bytes, bytes)
        assert len(zip_bytes) > 0

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            assert "00_COVER_LETTER.txt" in names
            assert "00_RELEASE_SUMMARY.txt" in names
            assert "01_doc.pdf" in names
            # Verify the document content round-trips
            assert zf.read("01_doc.pdf") == b"%PDF-1.4\nfake pdf bytes"
            # Cover letter contains the case number
            letter = zf.read("00_COVER_LETTER.txt").decode("utf-8")
            assert "FOI-2026-0001" in letter

    def test_skips_cover_letter_when_disabled(self) -> None:
        case_data = {"case_number": "C1"}
        documents = [{"filename": "d.pdf", "status": "released", "content": b"data"}]
        zip_bytes = create_release_package(case_data, documents, include_cover_letter=False)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            assert "00_COVER_LETTER.txt" not in names
            assert "00_RELEASE_SUMMARY.txt" in names

    def test_prefers_redacted_content_over_original(self) -> None:
        """CRITICAL: when a document has ``redacted_content``, that MUST
        be what lands in the ZIP — falling back to ``content`` would leak
        unredacted data.

        Audit Section 11 (B49 pinned below): the cover-letter Jinja
        template requires ``redaction_count`` to be set on every released
        document — the field is read with attribute access. Test docs
        therefore set ``redaction_count`` explicitly.
        """
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "secret.pdf",
                "status": "released",
                "content": b"UNREDACTED-SHOULD-NOT-APPEAR",
                "redacted_content": b"REDACTED-OK",
                "redaction_count": 0,
                "exemptions": [],
            }
        ]
        zip_bytes = create_release_package(case_data, documents)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            content = zf.read("01_secret.pdf")
        assert content == b"REDACTED-OK"
        assert b"UNREDACTED-SHOULD-NOT-APPEAR" not in content

    def test_falls_back_to_content_when_no_redacted_content(self) -> None:
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "doc.pdf",
                "status": "released",
                "content": b"original-bytes",
                "redaction_count": 0,
                "exemptions": [],
            }
        ]
        zip_bytes = create_release_package(case_data, documents)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert zf.read("01_doc.pdf") == b"original-bytes"

    def test_falls_back_when_redacted_content_is_falsy(self) -> None:
        """If ``redacted_content`` is empty/None, the ``or`` operator
        falls through to ``content``."""
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "d.pdf",
                "status": "released",
                "redacted_content": b"",  # falsy
                "content": b"fallback-content",
                "redaction_count": 0,
                "exemptions": [],
            }
        ]
        zip_bytes = create_release_package(case_data, documents)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert zf.read("01_d.pdf") == b"fallback-content"

    def test_uses_approved_status_too(self) -> None:
        """Both 'released' and 'approved' are included in the ZIP."""
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "ok.pdf",
                "status": "approved",
                "content": b"approved-content",
                "redaction_count": 0,
                "exemptions": [],
            }
        ]
        zip_bytes = create_release_package(case_data, documents)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert "01_ok.pdf" in zf.namelist()

    def test_skips_withheld_documents(self) -> None:
        """CRITICAL: withheld documents must NOT be included in the ZIP."""
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "secret.pdf",
                "status": "withheld",
                "content": b"WITHHELD-SHOULD-NOT-LEAK",
            }
        ]
        zip_bytes = create_release_package(case_data, documents)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            # Only cover letter + summary, no document bytes
            assert "01_secret.pdf" not in names
            assert all("secret" not in n for n in names if not n.endswith(".txt"))

    def test_warns_and_skips_document_with_no_content(self) -> None:
        """Documents with neither content nor redacted_content are
        skipped with a warning (and the ZIP doesn't crash)."""
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "empty.pdf",
                "status": "released",
                # No content, no redacted_content
                "redaction_count": 0,
                "exemptions": [],
            },
            {
                "filename": "good.pdf",
                "status": "released",
                "content": b"good",
                "redaction_count": 0,
                "exemptions": [],
            },
        ]
        zip_bytes = create_release_package(case_data, documents)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            # empty.pdf is skipped silently
            assert "01_empty.pdf" not in names
            # good.pdf is at index 2 (per the enumerate(documents, 1))
            assert "02_good.pdf" in names

    def test_filename_default_when_missing(self) -> None:
        """``doc.get('filename', 'document.pdf')`` fallback."""
        case_data = {"case_number": "C1"}
        documents = [
            {
                "status": "released",
                "content": b"data",
                "redaction_count": 0,
                "exemptions": [],
            },  # no filename
        ]
        zip_bytes = create_release_package(case_data, documents)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert "01_document.pdf" in zf.namelist()

    def test_numbers_documents_with_zero_padding(self) -> None:
        """Pin the ``f"{i:02d}_..."`` filename pattern."""
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": f"d{i}.pdf",
                "status": "released",
                "content": b"x",
                "redaction_count": 0,
                "exemptions": [],
            }
            for i in range(1, 12)
        ]
        zip_bytes = create_release_package(case_data, documents)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            assert "01_d1.pdf" in names
            assert "10_d10.pdf" in names
            assert "11_d11.pdf" in names

    def test_missing_redaction_count_field_crashes_release(self) -> None:
        """Audit Section 11 / B49: a released document dict that omits
        ``redaction_count`` causes the entire release_package pipeline
        to fail. Pin this defect-by-design until B49 is fixed."""
        case_data = {"case_number": "C1"}
        documents = [
            {
                "filename": "doc.pdf",
                "status": "released",
                "content": b"x",
                # NB: deliberately no redaction_count, no exemptions
            }
        ]
        with pytest.raises(Exception) as exc:
            create_release_package(case_data, documents)
        assert "Failed to create release package" in str(exc.value)
        assert "redaction_count" in str(exc.value)

    def test_exception_during_zip_build_reraises(self) -> None:
        """The except clause wraps the inner exception in a new
        ``Exception(...)`` — pin that this surfaces, not crashes."""
        case_data = {"case_number": "C1"}
        documents = [{"filename": "d.pdf", "status": "released", "content": b"x"}]

        with patch(
            "src.utils.release_package.zipfile.ZipFile",
            side_effect=RuntimeError("disk full"),
        ):
            with pytest.raises(Exception) as exc_info:
                create_release_package(case_data, documents)
            assert "Failed to create release package" in str(exc_info.value)
            assert "disk full" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Sanity check that the cover-letter template is well-formed
# ---------------------------------------------------------------------------


class TestCoverLetterTemplateConstant:
    def test_template_is_non_empty_string(self) -> None:
        assert isinstance(COVER_LETTER_TEMPLATE, str)
        assert len(COVER_LETTER_TEMPLATE) > 100
        # The four key sections
        assert "DECISION" in COVER_LETTER_TEMPLATE
        assert "DOCUMENTS RELEASED" in COVER_LETTER_TEMPLATE
        assert "EXEMPTIONS APPLIED" in COVER_LETTER_TEMPLATE
        assert "RIGHT TO REVIEW" in COVER_LETTER_TEMPLATE
