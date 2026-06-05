"""Tests for ``src.utils.ai_processing``.

Document-summary + AI-suggestion + attachment-processing pipeline.
Each function calls ``get_llm_client()`` first, then uses the client's
``chat_completion``. Tests stub both.

``process_attachment_async`` reaches into ``src.database.documents``
(the module global) so we patch that at the import site.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.ai_processing import (
    generate_ai_suggestions,
    generate_document_summary,
    process_attachment,
    process_attachment_async,
)

# ---------------------------------------------------------------------------
# generate_document_summary
# ---------------------------------------------------------------------------


class TestGenerateDocumentSummary:
    @pytest.mark.asyncio
    async def test_returns_default_when_llm_unconfigured(self) -> None:
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=None),
        ):
            result = await generate_document_summary(b"x", "f.pdf", "application/pdf")
        # Copy was tightened in 6ef0929 to point operators at the actual
        # fix (set a default in Admin -> LLM Configuration).
        assert "no default llm" in result.lower()

    @pytest.mark.asyncio
    async def test_pdf_uses_extract_text_from_pdf(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(return_value="Single sentence.")
        with (
            patch(
                "src.utils.ai_processing.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.utils.ai_processing.extract_text_from_pdf",
                return_value="A long enough text to pass the 20-char check",
            ),
        ):
            result = await generate_document_summary(b"%PDF", "f.pdf", "application/pdf")
        assert result == "Single sentence."

    @pytest.mark.asyncio
    async def test_non_pdf_decodes_content_directly(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(return_value="Summary text.")
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await generate_document_summary(
                b"some text content here that is long enough",
                "f.txt",
                "text/plain",
            )
        assert result == "Summary text."

    @pytest.mark.asyncio
    async def test_short_or_error_text_returns_meaningful_default(self) -> None:
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await generate_document_summary(b"x", "f.txt", "text/plain")
        assert "meaningful text" in result.lower()

    @pytest.mark.asyncio
    async def test_error_extracting_text_branch(self) -> None:
        client = MagicMock()
        with (
            patch(
                "src.utils.ai_processing.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "src.utils.ai_processing.extract_text_from_pdf",
                return_value="Error extracting text: corrupt PDF",
            ),
        ):
            result = await generate_document_summary(b"%PDF", "f.pdf", "application/pdf")
        assert "meaningful text" in result.lower()

    @pytest.mark.asyncio
    async def test_truncates_long_content(self) -> None:
        """Content > 8000 chars is truncated. We can't easily inspect
        the truncated text without seeing the prompt; verify the call
        succeeds without raising on a huge input."""
        client = MagicMock()
        client.chat_completion = AsyncMock(return_value="OK.")
        long_text = "A" * 20000
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await generate_document_summary(long_text.encode(), "f.txt", "text/plain")
        assert result == "OK."

    @pytest.mark.asyncio
    async def test_more_than_two_sentences_trimmed_to_two(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(return_value="First. Second. Third. Fourth.")
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await generate_document_summary(
                b"content here that is at least 20 chars long",
                "f.txt",
                "text/plain",
            )
        assert result == "First. Second."

    @pytest.mark.asyncio
    async def test_exception_returns_error_string(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await generate_document_summary(
                b"content here that is at least 20 chars long",
                "f.txt",
                "text/plain",
            )
        assert "Error generating summary" in result
        assert "boom" in result


# ---------------------------------------------------------------------------
# generate_ai_suggestions
# ---------------------------------------------------------------------------


class TestGenerateAiSuggestions:
    @pytest.mark.asyncio
    async def test_returns_error_when_llm_unconfigured(self) -> None:
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=None),
        ):
            result = await generate_ai_suggestions(b"x", "f", "text/plain")
        assert result[0]["type"] == "error"

    @pytest.mark.asyncio
    async def test_parses_valid_json_array(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(
            return_value='Here are findings: [{"type":"personal","description":"name","confidence":"High"}]'
        )
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await generate_ai_suggestions(b"text", "f", "text/plain")
        assert len(result) == 1
        assert result[0]["type"] == "personal"

    @pytest.mark.asyncio
    async def test_returns_error_when_no_brackets_in_response(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(return_value="Just a paragraph, no JSON.")
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await generate_ai_suggestions(b"text", "f", "text/plain")
        assert result[0]["type"] == "error"
        assert "Could not parse" in result[0]["description"]

    @pytest.mark.asyncio
    async def test_returns_error_on_invalid_json(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(return_value="[malformed json content here {not really]")
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await generate_ai_suggestions(b"text", "f", "text/plain")
        assert result[0]["type"] == "error"
        assert "Failed to parse" in result[0]["description"]

    @pytest.mark.asyncio
    async def test_exception_returns_error_response(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(side_effect=RuntimeError("oops"))
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await generate_ai_suggestions(b"text", "f", "text/plain")
        assert result[0]["type"] == "error"
        assert "oops" in result[0]["description"]


# ---------------------------------------------------------------------------
# process_attachment
# ---------------------------------------------------------------------------


class TestProcessAttachment:
    @pytest.mark.asyncio
    async def test_processes_attachment_returns_summary_and_suggestions(self) -> None:
        client = MagicMock()
        client.chat_completion = AsyncMock(
            side_effect=[
                "A summary.",
                '[{"type":"personal","description":"name","confidence":"High"}]',
            ]
        )
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=client),
        ):
            result = await process_attachment(
                {
                    "content": b"some content here long enough for processing",
                    "filename": "f.txt",
                    "mime_type": "text/plain",
                }
            )
        assert result["summary"] == "A summary."
        assert len(result["ai_suggestions"]) == 1
        assert result["processed"] is True
        assert result["processing_error"] is None

    @pytest.mark.asyncio
    async def test_attachment_processing_exception_caught(self) -> None:
        """Outer exception (e.g., something raising before asyncio.gather)
        is caught and returned in processing_error."""
        # Force an exception by passing a non-dict (the function calls
        # .get on it which will fail)
        with patch(
            "src.utils.ai_processing.get_llm_client",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await process_attachment(None)  # type: ignore[arg-type]
        assert result["processed"] is True
        assert result["processing_error"] is not None
        assert result["summary"] is None


# ---------------------------------------------------------------------------
# process_attachment_async
# ---------------------------------------------------------------------------


class TestProcessAttachmentAsync:
    @pytest.mark.asyncio
    async def test_logs_when_attachment_not_found(self) -> None:
        documents_mock = MagicMock()
        documents_mock.find_one = AsyncMock(return_value=None)

        with patch("src.utils.ai_processing.documents", documents_mock):
            # Should not raise
            await process_attachment_async("missing-id", "doc-1")
        documents_mock.find_one.assert_awaited_once_with({"id": "missing-id"})

    @pytest.mark.asyncio
    async def test_happy_path_updates_attachment_and_parent_counter(self) -> None:
        documents_mock = MagicMock()
        documents_mock.find_one = AsyncMock(
            return_value={
                "id": "att-1",
                "content": b"x" * 100,
                "filename": "f.pdf",
                "mime_type": "application/pdf",
            }
        )
        documents_mock.update_one = AsyncMock()

        client = MagicMock()
        client.chat_completion = AsyncMock(side_effect=["Summary.", "[]"])

        with (
            patch("src.utils.ai_processing.documents", documents_mock),
            patch(
                "src.utils.ai_processing.get_llm_client",
                new=AsyncMock(return_value=client),
            ),
        ):
            await process_attachment_async("att-1", "doc-parent")

        # First update sets summary/suggestions, second increments counter
        assert documents_mock.update_one.await_count == 2

    @pytest.mark.asyncio
    async def test_processing_failure_still_increments_counter(self) -> None:
        """When generate_* raises, the outer except clause runs the
        fallback updates so processed is True and counter still ticks."""
        documents_mock = MagicMock()
        documents_mock.find_one = AsyncMock(
            return_value={"id": "att-1", "content": b"x", "filename": "f.pdf"}
        )
        documents_mock.update_one = AsyncMock()

        with (
            patch("src.utils.ai_processing.documents", documents_mock),
            patch(
                "src.utils.ai_processing.get_llm_client",
                side_effect=RuntimeError("broken"),
            ),
        ):
            await process_attachment_async("att-1", "doc-parent")

        assert documents_mock.update_one.await_count >= 2

    @pytest.mark.asyncio
    async def test_fallback_update_failure_is_logged_not_raised(self) -> None:
        """Even the fallback update can fail (e.g. db down); that nested
        exception is logged and does NOT escape."""
        documents_mock = MagicMock()
        documents_mock.find_one = AsyncMock(
            return_value={"id": "att-1", "content": b"x", "filename": "f.pdf"}
        )
        documents_mock.update_one = AsyncMock(side_effect=RuntimeError("db down"))

        with (
            patch("src.utils.ai_processing.documents", documents_mock),
            patch(
                "src.utils.ai_processing.get_llm_client",
                side_effect=RuntimeError("broken"),
            ),
        ):
            # Must not raise
            await process_attachment_async("att-1", "doc-parent")
