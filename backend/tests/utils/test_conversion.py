"""Tests for ``src.utils.conversion``.

The conversion module wraps LibreOffice (subprocess), PyMuPDF, Pillow,
and extract_msg for file-format conversion. Tests mock subprocess to
avoid requiring LibreOffice in CI; real-tool integration tests are
marked ``@pytest.mark.slow`` and skipped when the relevant binary is
absent.

Phase 4 Batch 4.4 (audit B51): ``convert_image_to_pdf`` now opens the
input image inside a ``with`` block so Pillow releases the file handle
eagerly. The previous per-class ``filterwarnings`` suppressors that
absorbed the resulting ``ResourceWarning`` are no longer required and
have been removed.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz  # PyMuPDF
import pytest
from PIL import Image

from src.utils.conversion import (
    calculate_file_hash,
    configure_tesseract,
    convert_docx_to_pdf,
    convert_eml_to_pdf,
    convert_image_to_pdf,
    convert_msg_to_pdf,
    convert_office_to_pdf,
    convert_to_pdf,
    extract_text_from_pdf,
)

# ---------------------------------------------------------------------------
# configure_tesseract — env-driven
# ---------------------------------------------------------------------------


class TestConfigureTesseract:
    def test_uses_env_var_when_path_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_tesseract = tmp_path / "tesseract-bin"
        fake_tesseract.write_text("")
        monkeypatch.setenv("TESSERACT_PATH", str(fake_tesseract))
        configure_tesseract()
        import pytesseract

        assert pytesseract.pytesseract.tesseract_cmd == str(fake_tesseract)

    def test_no_env_var_skips_configuration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When env not set and Windows paths don't exist (Linux test
        env), the function is a no-op — does not raise."""
        monkeypatch.delenv("TESSERACT_PATH", raising=False)
        # Should not raise on Linux
        configure_tesseract()


# ---------------------------------------------------------------------------
# convert_office_to_pdf (mocked subprocess)
# ---------------------------------------------------------------------------


class TestConvertOfficeToPdf:
    def test_invokes_libreoffice_and_returns_output_path(self, tmp_path: Path) -> None:
        in_file = tmp_path / "doc.docx"
        in_file.write_bytes(b"fake docx")
        out_dir = tmp_path
        expected_pdf = out_dir / "doc.pdf"

        def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            assert cmd[0] == "libreoffice"
            # Simulate LibreOffice creating the PDF
            expected_pdf.write_bytes(b"%PDF-1.4 fake")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("src.utils.conversion.subprocess.run", side_effect=_fake_run):
            result = convert_office_to_pdf(str(in_file), str(out_dir))
        assert result == str(expected_pdf)

    def test_missing_output_file_raises(self, tmp_path: Path) -> None:
        in_file = tmp_path / "doc.docx"
        in_file.write_bytes(b"x")

        def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            # Don't create the expected output file
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="boom")

        with patch("src.utils.conversion.subprocess.run", side_effect=_fake_run):
            with pytest.raises(Exception, match="Office to PDF conversion failed"):
                convert_office_to_pdf(str(in_file), str(tmp_path))

    def test_subprocess_timeout_raises(self, tmp_path: Path) -> None:
        in_file = tmp_path / "doc.docx"
        in_file.write_bytes(b"x")

        with patch(
            "src.utils.conversion.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="libreoffice", timeout=60),
        ):
            with pytest.raises(Exception, match="timed out"):
                convert_office_to_pdf(str(in_file), str(tmp_path))

    def test_docx_wrapper_calls_office(self, tmp_path: Path) -> None:
        """``convert_docx_to_pdf`` is the legacy alias for
        convert_office_to_pdf."""
        in_file = tmp_path / "doc.docx"
        in_file.write_bytes(b"x")
        expected = tmp_path / "doc.pdf"

        def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            expected.write_bytes(b"%PDF")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("src.utils.conversion.subprocess.run", side_effect=_fake_run):
            r = convert_docx_to_pdf(str(in_file), str(tmp_path))
        assert r == str(expected)


# ---------------------------------------------------------------------------
# convert_image_to_pdf
# ---------------------------------------------------------------------------


def _write_png(path: Path, size: tuple[int, int] = (100, 100)) -> None:
    img = Image.new("RGB", size, color=(255, 255, 255))
    img.save(path, "PNG")


class TestConvertImageToPdf:
    def test_creates_pdf_from_png(self, tmp_path: Path) -> None:
        in_file = tmp_path / "img.png"
        _write_png(in_file)
        pdf_path = convert_image_to_pdf(str(in_file), str(tmp_path))
        assert Path(pdf_path).exists()
        # Valid PDF
        doc = fitz.open(pdf_path)
        assert len(doc) == 1
        doc.close()

    def test_handles_rgba_png(self, tmp_path: Path) -> None:
        """RGBA image is converted to RGB before drawing."""
        in_file = tmp_path / "rgba.png"
        Image.new("RGBA", (50, 50), color=(255, 0, 0, 128)).save(in_file, "PNG")
        pdf = convert_image_to_pdf(str(in_file), str(tmp_path))
        assert Path(pdf).exists()

    def test_bad_input_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "not-an-image.png"
        bad.write_bytes(b"not a real image")
        with pytest.raises(Exception):
            convert_image_to_pdf(str(bad), str(tmp_path))


# ---------------------------------------------------------------------------
# convert_eml_to_pdf
# ---------------------------------------------------------------------------


SIMPLE_EML = b"""From: alice@example.test
To: bob@example.test
Subject: Test Subject
Date: Mon, 1 Jan 2024 12:00:00 +0000
Message-ID: <abc@example.test>
Content-Type: text/plain

Hello, this is the body.
"""

MULTIPART_EML = b"""MIME-Version: 1.0
From: alice@example.test
To: bob@example.test
Subject: With Attachment
Date: Mon, 1 Jan 2024 12:00:00 +0000
Message-ID: <multipart@example.test>
Content-Type: multipart/mixed; boundary="bnd"

--bnd
Content-Type: text/plain

Body text here
--bnd
Content-Type: application/pdf; name="attachment.pdf"
Content-Disposition: attachment; filename="attachment.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQK
--bnd--
"""

HTML_EML = b"""MIME-Version: 1.0
From: alice@example.test
To: bob@example.test
Subject: HTML email
Date: Mon, 1 Jan 2024 12:00:00 +0000
Content-Type: text/html

<html><body><p>Hello <b>HTML</b> world.</p></body></html>
"""


class TestConvertEmlToPdf:
    def test_simple_plain_text_eml(self, tmp_path: Path) -> None:
        in_file = tmp_path / "msg.eml"
        in_file.write_bytes(SIMPLE_EML)
        out_pdf = tmp_path / "msg.pdf"

        pdf_path, attachments, text, message_id = convert_eml_to_pdf(str(in_file), str(out_pdf))
        assert Path(pdf_path).exists()
        assert attachments == []
        assert "Test Subject" in text
        assert "alice@example.test" in text
        assert message_id == "<abc@example.test>"

    def test_multipart_eml_extracts_attachment(self, tmp_path: Path) -> None:
        in_file = tmp_path / "msg.eml"
        in_file.write_bytes(MULTIPART_EML)
        out_pdf = tmp_path / "msg.pdf"

        pdf_path, attachments, text, message_id = convert_eml_to_pdf(str(in_file), str(out_pdf))
        assert Path(pdf_path).exists()
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "attachment.pdf"
        assert attachments[0]["mime_type"] == "application/pdf"
        assert "[ATTACHMENT: attachment.pdf]" in text

    def test_html_only_eml(self, tmp_path: Path) -> None:
        """HTML-only emails should have tags stripped."""
        in_file = tmp_path / "msg.eml"
        in_file.write_bytes(HTML_EML)
        out_pdf = tmp_path / "msg.pdf"

        pdf_path, _, text, _ = convert_eml_to_pdf(str(in_file), str(out_pdf))
        # Tags stripped — only text content remains
        assert "Hello" in text
        # The <b>HTML</b> markup should be gone
        assert "<b>" not in text
        assert "</b>" not in text

    def test_eml_with_long_lines_wraps(self, tmp_path: Path) -> None:
        """Lines >90 chars get wrapped — exercises the wrapping branch."""
        long_line = "x" * 200
        eml_bytes = f"From: a@x\nTo: b@x\nSubject: Long\n\n{long_line}\n".encode()
        in_file = tmp_path / "msg.eml"
        in_file.write_bytes(eml_bytes)
        out = tmp_path / "msg.pdf"
        pdf_path, _, text, _ = convert_eml_to_pdf(str(in_file), str(out))
        assert long_line in text

    def test_eml_with_inline_base64_image(self, tmp_path: Path) -> None:
        """HTML email with an inline data:image/png;base64 src triggers
        the inline-image branch."""
        import base64

        # Tiny valid 1x1 PNG
        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
            b"\x08\x99c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        b64 = base64.b64encode(png_1x1).decode()

        html_body = (
            f"<html><body><p>Look:</p>"
            f'<img src="data:image/png;base64,{b64}" />'
            f"<p>End</p></body></html>"
        )
        eml = (
            b"MIME-Version: 1.0\nFrom: a@x\nTo: b@x\nSubject: Inline\n"
            b"Content-Type: text/html\n\n" + html_body.encode()
        )
        in_file = tmp_path / "msg.eml"
        in_file.write_bytes(eml)
        out = tmp_path / "msg.pdf"

        with patch(
            "src.utils.conversion.pytesseract.image_to_string",
            return_value="",
        ):
            pdf_path, _, _, _ = convert_eml_to_pdf(str(in_file), str(out))
        assert Path(pdf_path).exists()

    def test_eml_with_inline_image_cid_and_multipart_related(self, tmp_path: Path) -> None:
        """Multipart/related EML with an inline image referenced by
        Content-ID hits the cid handling branch."""
        import base64

        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
            b"\x08\x99c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        b64 = base64.b64encode(png_1x1).decode()
        eml = (
            b"MIME-Version: 1.0\nFrom: a@x\nTo: b@x\nSubject: cid-test\n"
            b'Content-Type: multipart/related; boundary="b"\n\n'
            b"--b\nContent-Type: text/html\n\n"
            b'<html><body><img src="cid:image1@x"/></body></html>\n'
            b"--b\nContent-Type: image/png\nContent-ID: <image1@x>\n"
            b"Content-Transfer-Encoding: base64\n\n" + b64.encode() + b"\n" + b"--b--\n"
        )
        in_file = tmp_path / "msg.eml"
        in_file.write_bytes(eml)
        out = tmp_path / "msg.pdf"

        with patch(
            "src.utils.conversion.pytesseract.image_to_string",
            return_value="",
        ):
            pdf_path, _, _, _ = convert_eml_to_pdf(str(in_file), str(out))
        assert Path(pdf_path).exists()

    def test_eml_with_unnamed_attachment_falls_back_to_uuid_name(self, tmp_path: Path) -> None:
        """An attachment without a filename gets a uuid-based one."""
        eml = (
            b"MIME-Version: 1.0\nFrom: a@x\nTo: b@x\nSubject: S\n"
            b'Content-Type: multipart/mixed; boundary="b"\n\n'
            b"--b\nContent-Type: text/plain\n\nbody\n"
            b"--b\nContent-Type: application/octet-stream\n"
            b"Content-Disposition: attachment\n\n"
            b"binary-content-here\n"
            b"--b--\n"
        )
        in_file = tmp_path / "msg.eml"
        in_file.write_bytes(eml)
        out = tmp_path / "msg.pdf"
        _, attachments, _, _ = convert_eml_to_pdf(str(in_file), str(out))
        assert len(attachments) == 1
        assert attachments[0]["filename"].startswith("unknown_attachment_")


# ---------------------------------------------------------------------------
# extract_text_from_pdf
# ---------------------------------------------------------------------------


def _build_text_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 100), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


class TestExtractTextFromPdf:
    def test_returns_native_text(self) -> None:
        pdf = _build_text_pdf("Quick brown fox jumps over the lazy dog " * 20)
        result = extract_text_from_pdf(pdf)
        assert "Quick brown fox" in result
        assert "--- Page 1 ---" in result

    def test_invalid_pdf_returns_error_message(self) -> None:
        result = extract_text_from_pdf(b"not a pdf")
        assert "Error" in result

    def test_empty_pdf_falls_back_to_ocr_message(self) -> None:
        """A PDF with NO text triggers the OCR fallback. We stub
        pytesseract to return a fixed string to verify the branch
        without depending on Tesseract behavior."""
        # Build a PDF with just a rectangle (no text)
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(10, 10, 100, 100), fill=(0.5, 0.5, 0.5))
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()

        with patch(
            "src.utils.conversion.pytesseract.image_to_string",
            return_value="OCR'd content here",
        ):
            result = extract_text_from_pdf(buf.getvalue())
        assert "OCR'd content here" in result


# ---------------------------------------------------------------------------
# calculate_file_hash
# ---------------------------------------------------------------------------


class TestCalculateFileHash:
    def test_returns_sha256_hex(self) -> None:
        h = calculate_file_hash(b"hello world")
        assert len(h) == 64
        # Pre-computed sha256 of "hello world"
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_deterministic(self) -> None:
        assert calculate_file_hash(b"abc") == calculate_file_hash(b"abc")


# ---------------------------------------------------------------------------
# convert_to_pdf (dispatcher)
# ---------------------------------------------------------------------------


class TestConvertToPdf:
    def test_pdf_input_passes_through(self, tmp_path: Path) -> None:
        pdf_file = tmp_path / "in.pdf"
        pdf_file.write_bytes(_build_text_pdf("text"))
        result = convert_to_pdf(str(pdf_file), str(tmp_path))
        assert result["success"] is True
        assert result["pdf_path"] == str(pdf_file)
        assert "extracted_text" in result
        assert result["original_format"] == "pdf"

    def test_unsupported_format_sets_error(self, tmp_path: Path) -> None:
        unknown = tmp_path / "file.xyz"
        unknown.write_bytes(b"x")
        result = convert_to_pdf(str(unknown), str(tmp_path))
        assert result["success"] is False
        assert "Unsupported file format" in result["error"]

    def test_image_input_converts_via_image_pipeline(self, tmp_path: Path) -> None:
        img = tmp_path / "pic.png"
        _write_png(img)
        with patch(
            "src.utils.conversion.extract_text_from_pdf",
            return_value="extracted text",
        ):
            result = convert_to_pdf(str(img), str(tmp_path))
        assert result["success"] is True
        assert result["original_format"] == "png"

    def test_eml_input_uses_eml_pipeline(self, tmp_path: Path) -> None:
        eml = tmp_path / "in.eml"
        eml.write_bytes(SIMPLE_EML)
        result = convert_to_pdf(str(eml), str(tmp_path))
        assert result["success"] is True
        assert result["original_format"] == "eml"
        assert result["message_id"] == "<abc@example.test>"

    def test_msg_input_uses_msg_pipeline(self, tmp_path: Path) -> None:
        msg = tmp_path / "in.msg"
        msg.write_bytes(b"x")

        fake_msg = MagicMock()
        fake_msg.sender = "a@x"
        fake_msg.to = "b@x"
        fake_msg.subject = "S"
        fake_msg.date = None
        fake_msg.body = "body"
        fake_msg.attachments = []
        fake_msg.messageId = "<m@x>"

        fake_module = MagicMock()
        fake_module.Message.return_value = fake_msg

        with patch.dict("sys.modules", {"extract_msg": fake_module}):
            result = convert_to_pdf(str(msg), str(tmp_path))
        assert result["success"] is True
        assert result["original_format"] == "msg"
        assert result["message_id"] == "<m@x>"

    def test_office_input_uses_office_pipeline(self, tmp_path: Path) -> None:
        docx = tmp_path / "file.docx"
        docx.write_bytes(b"x")
        expected_pdf = tmp_path / "file.pdf"

        def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            expected_pdf.write_bytes(_build_text_pdf("DOCX content"))
            return subprocess.CompletedProcess(cmd, 0)

        with patch("src.utils.conversion.subprocess.run", side_effect=_fake_run):
            result = convert_to_pdf(str(docx), str(tmp_path))
        assert result["success"] is True
        assert result["original_format"] == "docx"

    def test_no_output_dir_uses_temp(self) -> None:
        """When output_dir is None, a temp dir is created."""
        # Use a PDF that already exists to avoid any external tool calls
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(_build_text_pdf("x"))
            tmp_pdf = f.name
        try:
            result = convert_to_pdf(tmp_pdf)
            assert result["success"] is True
        finally:
            os.unlink(tmp_pdf)

    def test_conversion_exception_caught(self, tmp_path: Path) -> None:
        """When the underlying conversion raises, result.error is set
        but the function does not re-raise."""
        eml = tmp_path / "in.eml"
        eml.write_bytes(SIMPLE_EML)

        with patch(
            "src.utils.conversion.convert_eml_to_pdf",
            side_effect=RuntimeError("boom"),
        ):
            result = convert_to_pdf(str(eml), str(tmp_path))
        assert result["success"] is False
        assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# convert_msg_to_pdf (mocked extract_msg)
# ---------------------------------------------------------------------------


class TestConvertMsgToPdf:
    def test_extract_msg_unavailable_raises(self, tmp_path: Path) -> None:
        """If extract_msg can't be imported, the function raises."""
        in_file = tmp_path / "msg.msg"
        in_file.write_bytes(b"x")
        out = tmp_path / "msg.pdf"

        # Force the local import to fail
        with patch.dict("sys.modules", {"extract_msg": None}):
            with pytest.raises(Exception, match="extract-msg library not installed"):
                convert_msg_to_pdf(str(in_file), str(out))

    def test_happy_path_with_mocked_msg(self, tmp_path: Path) -> None:
        """Simulate an extract_msg.Message and verify a PDF is built."""
        in_file = tmp_path / "msg.msg"
        in_file.write_bytes(b"x")
        out = tmp_path / "msg.pdf"

        fake_msg = MagicMock()
        fake_msg.sender = "alice@example.test"
        fake_msg.to = "bob@example.test"
        fake_msg.subject = "Hello from MSG"
        fake_msg.date = "2024-01-01"
        fake_msg.messageId = "<msg-id@example.test>"
        fake_msg.body = "This is the body text."
        fake_msg.attachments = []

        fake_module = MagicMock()
        fake_module.Message.return_value = fake_msg

        with patch.dict("sys.modules", {"extract_msg": fake_module}):
            pdf_path, attachments, text, message_id = convert_msg_to_pdf(str(in_file), str(out))
        assert Path(pdf_path).exists()
        assert attachments == []
        assert "Hello from MSG" in text
        assert message_id == "<msg-id@example.test>"

    def test_msg_with_attachment(self, tmp_path: Path) -> None:
        in_file = tmp_path / "msg.msg"
        in_file.write_bytes(b"x")
        out = tmp_path / "msg.pdf"

        fake_attachment = MagicMock()
        fake_attachment.longFilename = "report.pdf"
        fake_attachment.shortFilename = None
        fake_attachment.data = b"%PDF-fake-attachment"
        fake_attachment.mimeType = "application/pdf"

        fake_msg = MagicMock()
        fake_msg.sender = "a@x"
        fake_msg.to = "b@x"
        fake_msg.subject = "S"
        fake_msg.date = None
        fake_msg.body = "body"
        fake_msg.attachments = [fake_attachment]
        fake_msg.messageId = "<m@x>"

        fake_module = MagicMock()
        fake_module.Message.return_value = fake_msg

        with patch.dict("sys.modules", {"extract_msg": fake_module}):
            _, attachments, text, _ = convert_msg_to_pdf(str(in_file), str(out))
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "report.pdf"
        assert "[ATTACHMENT: report.pdf]" in text

    def test_msg_with_long_body_wraps_and_paginates(self, tmp_path: Path) -> None:
        """Exercise the long-line wrapping + showPage branches inside
        convert_msg_to_pdf's body loop."""
        long_line = "x" * 200
        in_file = tmp_path / "msg.msg"
        in_file.write_bytes(b"x")
        out = tmp_path / "msg.pdf"

        fake_msg = MagicMock()
        fake_msg.sender = "a@x"
        fake_msg.to = "b@x"
        fake_msg.subject = "S"
        fake_msg.date = "2024-01-01"
        # Many lines to force showPage. Empty lines too.
        fake_msg.body = "\n".join([long_line] * 100) + "\n\n\n" + "trailing\n"
        fake_msg.attachments = []
        fake_msg.messageId = "<m@x>"

        fake_module = MagicMock()
        fake_module.Message.return_value = fake_msg

        with patch.dict("sys.modules", {"extract_msg": fake_module}):
            pdf_path, _, _, _ = convert_msg_to_pdf(str(in_file), str(out))
        assert Path(pdf_path).exists()

    def test_msg_attachment_summary_paginates(self, tmp_path: Path) -> None:
        """Many attachments fill the attachment summary page and trigger
        the showPage branch in that loop."""
        in_file = tmp_path / "msg.msg"
        in_file.write_bytes(b"x")
        out = tmp_path / "msg.pdf"

        attachments = []
        for i in range(60):  # 60 attachments × 15 px line ≈ 900 px, triggers showPage
            att = MagicMock()
            att.longFilename = f"file_{i}.pdf"
            att.shortFilename = None
            att.data = b"%PDF"
            att.mimeType = "application/pdf"
            attachments.append(att)

        fake_msg = MagicMock()
        fake_msg.sender = "a@x"
        fake_msg.to = "b@x"
        fake_msg.subject = "S"
        fake_msg.date = "2024-01-01"
        fake_msg.body = "body"
        fake_msg.attachments = attachments
        fake_msg.messageId = None

        fake_module = MagicMock()
        fake_module.Message.return_value = fake_msg

        with patch.dict("sys.modules", {"extract_msg": fake_module}):
            _, atts, _, _ = convert_msg_to_pdf(str(in_file), str(out))
        assert len(atts) == 60

    def test_msg_attachment_extraction_error_is_logged_and_skipped(self, tmp_path: Path) -> None:
        """An attachment whose data raises during write is caught and
        the next attachment processed."""
        in_file = tmp_path / "msg.msg"
        in_file.write_bytes(b"x")
        out = tmp_path / "msg.pdf"

        # First attachment raises when ``data`` is accessed
        bad_att = MagicMock()
        bad_att.longFilename = "broken.pdf"
        type(bad_att).data = property(lambda self: (_ for _ in ()).throw(RuntimeError("io error")))
        good_att = MagicMock()
        good_att.longFilename = "good.pdf"
        good_att.shortFilename = None
        good_att.data = b"good-bytes"
        good_att.mimeType = "application/pdf"

        fake_msg = MagicMock()
        fake_msg.sender = "a@x"
        fake_msg.to = "b@x"
        fake_msg.subject = "S"
        fake_msg.date = None
        fake_msg.body = "body"
        fake_msg.attachments = [bad_att, good_att]
        fake_msg.messageId = None

        fake_module = MagicMock()
        fake_module.Message.return_value = fake_msg

        with patch.dict("sys.modules", {"extract_msg": fake_module}):
            _, atts, _, _ = convert_msg_to_pdf(str(in_file), str(out))
        # Only the good attachment survived
        assert len(atts) == 1
        assert atts[0]["filename"] == "good.pdf"

    def test_msg_with_rtf_only_body(self, tmp_path: Path) -> None:
        """When the only body is RTF, the function returns a placeholder
        string."""
        in_file = tmp_path / "msg.msg"
        in_file.write_bytes(b"x")
        out = tmp_path / "msg.pdf"

        fake_msg = MagicMock()
        fake_msg.sender = "a@x"
        fake_msg.to = "b@x"
        fake_msg.subject = "S"
        fake_msg.date = None
        fake_msg.body = None
        fake_msg.htmlBody = None
        fake_msg.rtfBody = b"{\\rtf1...}"
        fake_msg.attachments = []
        fake_msg.messageId = None

        fake_module = MagicMock()
        fake_module.Message.return_value = fake_msg

        with patch.dict("sys.modules", {"extract_msg": fake_module}):
            _, _, text, _ = convert_msg_to_pdf(str(in_file), str(out))
        assert "RTF formatted email" in text

    def test_msg_with_html_body_falls_back(self, tmp_path: Path) -> None:
        in_file = tmp_path / "msg.msg"
        in_file.write_bytes(b"x")
        out = tmp_path / "msg.pdf"

        fake_msg = MagicMock()
        fake_msg.sender = "a@x"
        fake_msg.to = "b@x"
        fake_msg.subject = "S"
        fake_msg.date = None
        fake_msg.body = None
        fake_msg.htmlBody = b"<p>Hello <b>HTML</b></p>"
        fake_msg.rtfBody = None
        fake_msg.attachments = []
        fake_msg.messageId = None

        fake_module = MagicMock()
        fake_module.Message.return_value = fake_msg

        with patch.dict("sys.modules", {"extract_msg": fake_module}):
            pdf_path, _, text, _ = convert_msg_to_pdf(str(in_file), str(out))
        assert "Hello" in text
        assert "<b>" not in text


# ---------------------------------------------------------------------------
# Slow integration tests (skip if tooling absent)
# ---------------------------------------------------------------------------


_HAS_LIBREOFFICE = shutil.which("libreoffice") is not None


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="libreoffice not installed")
def test_real_libreoffice_docx_roundtrip(tmp_path: Path, fixtures_dir: Path) -> None:
    """End-to-end: convert the sample FOIPPA docx through LibreOffice."""
    sample = fixtures_dir / "FOIPPA_Test_Document.docx"
    if not sample.exists():
        pytest.skip("FOIPPA_Test_Document.docx fixture not available")
    pdf = convert_office_to_pdf(str(sample), str(tmp_path))
    assert Path(pdf).exists()
