"""Ingest-safety tests for ``src.utils.conversion`` (security review 2026-09).

- DOC-01: attachment filenames from EML/MSG must never be used as paths.
- DOC-18: same-name attachments, forwarded ``message/rfc822`` parts and
  MSG embedded messages must not be lost or break conversion.
- DOC-06: the email renderer must keep every line on the page (wrap to
  the page width, paginate at the bottom margin).
- Thread headers (#73): In-Reply-To / References reach the extracted text
  so ``extract_thread_identifiers`` can populate them.
"""

from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from src.utils.conversion import convert_eml_to_pdf, convert_msg_to_pdf, convert_to_pdf

HOSTILE_NAMES = [
    pytest.param("../../x", "x", id="dotdot"),
    pytest.param("ABSOLUTE", "abs.pdf", id="absolute"),
    pytest.param("..\\..\\x.pdf", "x.pdf", id="windows-dotdot"),
]


def _resolve_hostile(name: str, tmp_path: Path) -> str:
    """Absolute-path case points at a real location outside the output dir."""
    if name == "ABSOLUTE":
        return str(tmp_path / "outside" / "abs.pdf")
    return name


def _eml_with_attachment(filename: str, payload: bytes = b"%PDF-1.4 hostile") -> bytes:
    msg = EmailMessage()
    msg["From"] = "a@example.test"
    msg["To"] = "b@example.test"
    msg["Subject"] = "hostile"
    msg.set_content("body")
    msg.add_attachment(payload, maintype="application", subtype="pdf", filename=filename)
    return bytes(msg)


def _assert_contained(path: str, output_dir: Path) -> None:
    real_out = os.path.realpath(output_dir)
    assert os.path.commonpath([real_out, os.path.realpath(path)]) == real_out


def _fake_msg(**overrides):
    fake = MagicMock()
    fake.sender = "a@example.test"
    fake.to = "b@example.test"
    fake.subject = "S"
    fake.date = None
    fake.messageId = "<m@example.test>"
    fake.inReplyTo = None
    fake.header = None
    fake.body = "body"
    fake.htmlBody = None
    fake.rtfBody = None
    fake.attachments = []
    for k, v in overrides.items():
        setattr(fake, k, v)
    module = MagicMock()
    module.Message.return_value = fake
    return module


def _fake_msg_attachment(name: str | None, data, mime: str = "application/pdf"):
    att = MagicMock()
    att.longFilename = name
    att.shortFilename = None
    att.data = data
    att.mimeType = mime
    return att


# ---------------------------------------------------------------------------
# DOC-01: path traversal via attachment filename
# ---------------------------------------------------------------------------


class TestAttachmentPathTraversal:
    @pytest.mark.parametrize("raw_name,display", HOSTILE_NAMES)
    def test_eml_attachment_written_inside_output_dir(
        self, tmp_path: Path, raw_name: str, display: str
    ) -> None:
        name = _resolve_hostile(raw_name, tmp_path)
        work = tmp_path / "a" / "b" / "work"
        work.mkdir(parents=True)
        in_file = work / "in.eml"
        in_file.write_bytes(_eml_with_attachment(name))

        _, attachments, text, _ = convert_eml_to_pdf(str(in_file), str(work / "out.pdf"))

        assert len(attachments) == 1
        att = attachments[0]
        _assert_contained(att["path"], work)
        assert Path(att["path"]).read_bytes() == b"%PDF-1.4 hostile"
        # Stored under a generated name, never the sender-controlled one.
        assert os.path.basename(att["path"]) != os.path.basename(name)
        assert att["filename"] == display
        assert f"[ATTACHMENT: {display}]" in text
        # Nothing escaped the work directory.
        assert not (tmp_path / "a" / "x").exists()
        assert not (tmp_path / "x").exists()
        assert not (tmp_path / "outside").exists()

    @pytest.mark.parametrize("raw_name,display", HOSTILE_NAMES)
    def test_msg_attachment_written_inside_output_dir(
        self, tmp_path: Path, raw_name: str, display: str
    ) -> None:
        name = _resolve_hostile(raw_name, tmp_path)
        work = tmp_path / "a" / "b" / "work"
        work.mkdir(parents=True)
        in_file = work / "in.msg"
        in_file.write_bytes(b"x")
        module = _fake_msg(attachments=[_fake_msg_attachment(name, b"%PDF-1.4 hostile")])

        with patch.dict("sys.modules", {"extract_msg": module}):
            _, attachments, text, _ = convert_msg_to_pdf(str(in_file), str(work / "out.pdf"))

        assert len(attachments) == 1
        att = attachments[0]
        _assert_contained(att["path"], work)
        assert Path(att["path"]).read_bytes() == b"%PDF-1.4 hostile"
        assert att["filename"] == display
        assert f"[ATTACHMENT: {display}]" in text
        assert not (tmp_path / "a" / "x").exists()
        assert not (tmp_path / "x").exists()
        assert not (tmp_path / "outside").exists()

    def test_display_name_strips_control_chars_and_is_capped(self, tmp_path: Path) -> None:
        # RFC 2231 encoding lets the sender smuggle NUL/CR/LF into the name.
        encoded = "evil%00%0D%0Aname" + ("y" * 400) + ".pdf"
        raw = (
            "MIME-Version: 1.0\nFrom: a@x\nTo: b@x\nSubject: S\n"
            'Content-Type: multipart/mixed; boundary="b"\n\n'
            "--b\nContent-Type: text/plain\n\nbody\n"
            "--b\nContent-Type: application/pdf\n"
            f"Content-Disposition: attachment; filename*=utf-8''{encoded}\n\n"
            "%PDF-1.4\n--b--\n"
        )
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(raw.encode())
        _, attachments, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        display = attachments[0]["filename"]
        assert not any(ord(c) < 32 for c in display)
        assert len(display) <= 255
        assert display.endswith(".pdf")

    def test_supported_extension_kept_on_disk(self, tmp_path: Path) -> None:
        """The on-disk name keeps an allow-listed extension so the attachment
        can still be converted; anything else gets a neutral one."""
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(_eml_with_attachment("report.PDF"))
        _, attachments, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        assert attachments[0]["path"].endswith(".pdf")

        in_file.write_bytes(_eml_with_attachment("run.sh"))
        _, attachments, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        assert not attachments[0]["path"].endswith(".sh")


# ---------------------------------------------------------------------------
# DOC-18: records dropped during ingest
# ---------------------------------------------------------------------------


class TestAttachmentsNotDropped:
    def test_same_name_eml_attachments_both_kept(self, tmp_path: Path) -> None:
        msg = EmailMessage()
        msg["Subject"] = "dup"
        msg.set_content("two files")
        msg.add_attachment(b"FIRST", maintype="application", subtype="pdf", filename="a.pdf")
        msg.add_attachment(b"SECOND", maintype="application", subtype="pdf", filename="a.pdf")
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(bytes(msg))

        _, attachments, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))

        assert [a["filename"] for a in attachments] == ["a.pdf", "a.pdf"]
        assert [Path(a["path"]).read_bytes() for a in attachments] == [b"FIRST", b"SECOND"]

    def test_same_name_msg_attachments_both_kept(self, tmp_path: Path) -> None:
        in_file = tmp_path / "in.msg"
        in_file.write_bytes(b"x")
        module = _fake_msg(
            attachments=[
                _fake_msg_attachment("a.pdf", b"FIRST"),
                _fake_msg_attachment("a.pdf", b"SECOND"),
            ]
        )
        with patch.dict("sys.modules", {"extract_msg": module}):
            _, attachments, _, _ = convert_msg_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        assert [a["filename"] for a in attachments] == ["a.pdf", "a.pdf"]
        assert [Path(a["path"]).read_bytes() for a in attachments] == [b"FIRST", b"SECOND"]

    def test_forwarded_rfc822_part_becomes_eml_attachment(self, tmp_path: Path) -> None:
        inner = EmailMessage()
        inner["Subject"] = "inner"
        inner.set_content("inner body SECRET-INNER")
        outer = EmailMessage()
        outer["Subject"] = "fwd"
        outer.set_content("see attached")
        outer.add_attachment(inner)
        in_file = tmp_path / "o.eml"
        in_file.write_bytes(bytes(outer))

        result = convert_to_pdf(str(in_file), str(tmp_path))

        assert result["success"], result["error"]
        assert len(result["attachments"]) == 1
        att = result["attachments"][0]
        assert att["filename"].endswith(".eml")
        assert att["path"].endswith(".eml")
        assert b"SECRET-INNER" in Path(att["path"]).read_bytes()
        # The forwarded body is not spliced into the outer email's text.
        assert "SECRET-INNER" not in result["extracted_text"]
        # And the saved part is itself convertible.
        inner_result = convert_to_pdf(att["path"], str(tmp_path))
        assert inner_result["success"], inner_result["error"]
        assert "SECRET-INNER" in inner_result["extracted_text"]

    def test_msg_embedded_message_extracted_as_msg_attachment(self, tmp_path: Path) -> None:
        embedded = MagicMock(spec=["exportBytes", "subject"])
        embedded.exportBytes.return_value = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1embedded"
        embedded.subject = "Inner subject"
        att = _fake_msg_attachment(None, embedded, mime=None)
        in_file = tmp_path / "in.msg"
        in_file.write_bytes(b"x")
        module = _fake_msg(attachments=[att])

        with patch.dict("sys.modules", {"extract_msg": module}):
            _, attachments, text, _ = convert_msg_to_pdf(str(in_file), str(tmp_path / "out.pdf"))

        assert len(attachments) == 1
        assert attachments[0]["path"].endswith(".msg")
        assert attachments[0]["filename"].endswith(".msg")
        assert Path(attachments[0]["path"]).read_bytes().startswith(b"\xd0\xcf\x11\xe0")

    def test_msg_attachment_without_data_is_logged_and_marked(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        in_file = tmp_path / "in.msg"
        in_file.write_bytes(b"x")
        module = _fake_msg(attachments=[_fake_msg_attachment("link.url", None)])
        with caplog.at_level(logging.WARNING, logger="src.utils.conversion"):
            with patch.dict("sys.modules", {"extract_msg": module}):
                _, attachments, text, _ = convert_msg_to_pdf(
                    str(in_file), str(tmp_path / "out.pdf")
                )
        assert attachments == []
        assert "link.url" in text and "NOT EXTRACTED" in text
        assert any("link.url" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# DOC-06: rendered text must stay on the page
# ---------------------------------------------------------------------------


def _all_text_and_blocks(pdf_path: str) -> tuple[str, list[tuple[fitz.Rect, fitz.Rect]]]:
    doc = fitz.open(pdf_path)
    try:
        text = ""
        blocks = []
        for page in doc:
            text += page.get_text("text", clip=fitz.INFINITE_RECT())
            for block in page.get_text("dict", clip=fitz.INFINITE_RECT())["blocks"]:
                blocks.append((fitz.Rect(block["bbox"]), fitz.Rect(page.rect)))
        return text, blocks
    finally:
        doc.close()


def _assert_on_page(blocks) -> None:
    assert blocks
    for bbox, page_rect in blocks:
        assert bbox.x0 >= page_rect.x0 - 0.5, bbox
        assert bbox.y0 >= page_rect.y0 - 0.5, bbox
        assert bbox.x1 <= page_rect.x1 + 0.5, bbox
        assert bbox.y1 <= page_rect.y1 + 0.5, bbox


LONG_LINE = ("WWMM" * 70) + "SIN123456789"  # 292 wide chars, no spaces
BODY_LINES = [f"line {i:03d} of the body END{i:03d}" for i in range(200)]


def _squash(s: str) -> str:
    return "".join(s.split())


class TestRendererStaysOnPage:
    def test_eml_long_unbroken_line(self, tmp_path: Path) -> None:
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(f"From: a@x\nTo: b@x\nSubject: Long\n\n{LONG_LINE}\n".encode())
        pdf, _, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        text, blocks = _all_text_and_blocks(pdf)
        assert LONG_LINE in _squash(text)
        _assert_on_page(blocks)

    def test_eml_long_header_wraps(self, tmp_path: Path) -> None:
        to = ", ".join(f"person{i}@example.test" for i in range(30))
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(f"From: a@x\nTo: {to}\nSubject: S\n\nbody\n".encode())
        pdf, _, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        text, blocks = _all_text_and_blocks(pdf)
        assert "person29@example.test" in text
        _assert_on_page(blocks)

    def test_eml_200_line_body_paginates(self, tmp_path: Path) -> None:
        body = "\n".join(BODY_LINES)
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(f"From: a@x\nTo: b@x\nSubject: Many\n\n{body}\n".encode())
        pdf, _, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        text, blocks = _all_text_and_blocks(pdf)
        for line in BODY_LINES:
            assert line in text
        _assert_on_page(blocks)
        with fitz.open(pdf) as doc:
            assert doc.page_count > 1

    def test_eml_long_paragraph_near_page_bottom(self, tmp_path: Path) -> None:
        """A long paragraph that starts near the bottom must break onto the
        next page instead of running past the bottom edge."""
        para = " ".join(f"word{i:04d}" for i in range(400))
        for n_filler in (30, 36, 38, 40, 46):
            filler = "\n".join(f"filler {i}" for i in range(n_filler))
            in_file = tmp_path / f"in{n_filler}.eml"
            in_file.write_bytes(f"From: a@x\nTo: b@x\nSubject: P\n\n{filler}\n{para}\n".encode())
            pdf, _, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / f"o{n_filler}.pdf"))
            text, blocks = _all_text_and_blocks(pdf)
            assert "word0399" in text
            _assert_on_page(blocks)

    def test_eml_html_with_inline_image_long_line(self, tmp_path: Path) -> None:
        import base64

        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
            b"\x08\x99c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        b64 = base64.b64encode(png_1x1).decode()
        html = (
            f"<html><body><p>{LONG_LINE}</p>"
            f'<img src="data:image/png;base64,{b64}" />'
            f"<p>{'<br>'.join(BODY_LINES)}</p></body></html>"
        )
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(
            b"MIME-Version: 1.0\nFrom: a@x\nTo: b@x\nSubject: H\n"
            b"Content-Type: text/html\n\n" + html.encode()
        )
        with patch("src.utils.conversion.pytesseract.image_to_string", return_value=""):
            pdf, _, _, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        text, blocks = _all_text_and_blocks(pdf)
        assert LONG_LINE in _squash(text)
        assert "END199" in text
        _assert_on_page(blocks)

    def test_msg_long_unbroken_line_and_200_lines(self, tmp_path: Path) -> None:
        in_file = tmp_path / "in.msg"
        in_file.write_bytes(b"x")
        module = _fake_msg(body=LONG_LINE + "\n" + "\n".join(BODY_LINES))
        with patch.dict("sys.modules", {"extract_msg": module}):
            pdf, _, _, _ = convert_msg_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        text, blocks = _all_text_and_blocks(pdf)
        assert LONG_LINE in _squash(text)
        for line in BODY_LINES:
            assert line in text
        _assert_on_page(blocks)

    def test_msg_long_subject_not_truncated_off_page(self, tmp_path: Path) -> None:
        subject = "Subject " + ("W" * 250) + " TAIL"
        in_file = tmp_path / "in.msg"
        in_file.write_bytes(b"x")
        module = _fake_msg(subject=subject)
        with patch.dict("sys.modules", {"extract_msg": module}):
            pdf, _, _, _ = convert_msg_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        text, blocks = _all_text_and_blocks(pdf)
        assert "TAIL" in text
        _assert_on_page(blocks)


# ---------------------------------------------------------------------------
# #73: In-Reply-To / References reach the extracted text
# ---------------------------------------------------------------------------


class TestThreadHeadersExtracted:
    def test_eml_in_reply_to_and_references(self, tmp_path: Path) -> None:
        from src.utils.email_threads import extract_thread_identifiers

        # References is folded over two lines, as real mail clients do.
        raw = (
            b"From: a@example.test\nTo: b@example.test\nSubject: Re: Budget\n"
            b"Message-ID: <c@example.test>\nIn-Reply-To: <b@example.test>\n"
            b"References: <a@example.test>\n <b@example.test>\n\nreply body\n"
        )
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(raw)

        _, _, text, message_id = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        ids = extract_thread_identifiers(text, message_id)
        assert ids["in_reply_to"] == "<b@example.test>"
        assert ids["references"] == ["<a@example.test>", "<b@example.test>"]

    def test_msg_in_reply_to_and_references(self, tmp_path: Path) -> None:
        from email.message import Message

        from src.utils.email_threads import extract_thread_identifiers

        header = Message()
        header["References"] = "<a@example.test> <b@example.test>"
        module = _fake_msg(inReplyTo="<b@example.test>", header=header)
        in_file = tmp_path / "in.msg"
        in_file.write_bytes(b"x")
        with patch.dict("sys.modules", {"extract_msg": module}):
            _, _, text, message_id = convert_msg_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        ids = extract_thread_identifiers(text, message_id)
        assert ids["in_reply_to"] == "<b@example.test>"
        assert ids["references"] == ["<a@example.test>", "<b@example.test>"]

    def test_absent_headers_add_no_lines(self, tmp_path: Path) -> None:
        in_file = tmp_path / "in.eml"
        in_file.write_bytes(b"From: a@x\nTo: b@x\nSubject: S\n\nbody\n")
        _, _, text, _ = convert_eml_to_pdf(str(in_file), str(tmp_path / "out.pdf"))
        assert "In-Reply-To:" not in text
        assert "References:" not in text


class TestReadThreadHeaders:
    """I7: conversion returns threading headers parsed from the message."""

    def test_eml_headers_are_structured_and_decoded(self, tmp_path) -> None:
        from src.utils.conversion import read_thread_headers

        path = tmp_path / "m.eml"
        path.write_bytes(
            b"From: =?utf-8?q?Ren=C3=A9e?= <renee@example.org>\r\n"
            b"To: a@example.org,\r\n b@example.org\r\n"
            b"Subject: =?utf-8?q?Caf=C3=A9_budget?=\r\n"
            b"Date: Sun, 1 Jun 2025 09:00:00 +0000\r\n"
            b"Message-ID: <m@example.org>\r\n"
            b"In-Reply-To: <p@example.org>\r\n"
            b"References: <r@example.org> <p@example.org>\r\n"
            b"\r\nbody\r\n"
        )
        headers = read_thread_headers(str(path))
        assert headers == {
            "message_id": "<m@example.org>",
            "in_reply_to": "<p@example.org>",
            "references": ["<r@example.org>", "<p@example.org>"],
            "date": "Sun, 1 Jun 2025 09:00:00 +0000",
            "subject": "Café budget",
            "from": "Renée <renee@example.org>",
            "to": "a@example.org, b@example.org",
        }

    def test_convert_to_pdf_returns_thread_headers(self, tmp_path) -> None:
        from src.utils.conversion import convert_to_pdf

        path = tmp_path / "m.eml"
        path.write_bytes(b"From: a@x\nSubject: S\nMessage-ID: <m@x>\n\nbody\n")
        result = convert_to_pdf(str(path), str(tmp_path))
        assert result["success"]
        assert result["thread_headers"]["subject"] == "S"
        assert result["thread_headers"]["message_id"] == "<m@x>"

    def test_unreadable_file_gives_empty_headers(self, tmp_path) -> None:
        from src.utils.conversion import read_thread_headers

        assert read_thread_headers(str(tmp_path / "missing.eml")) == {}
