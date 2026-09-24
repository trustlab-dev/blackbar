"""DOC-11: streamed size limit and content sniffing for uploads.

Unit tests for the shared helper in ``src.documents.processing_service``.
The three upload entry points (documents, collection link, contributor)
are covered in their own route test modules.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.documents import processing_service as ps
from src.documents.processing_service import content_matches_extension, read_verified_upload

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
ZIP = b"PK\x03\x04" + b"\x00" * 32
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
EML = b"Received: from mx\r\nFrom: a@x\r\nTo: b@x\r\nSubject: hi\r\n\r\nbody\r\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


class _FakeUpload:
    """Minimal UploadFile stand-in that records how much was read."""

    def __init__(self, data: bytes, filename: str, size: int | None = None) -> None:
        self._data = data
        self._pos = 0
        self.filename = filename
        self.size = size
        self.bytes_read = 0

    async def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = len(self._data) - self._pos
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        self.bytes_read += len(chunk)
        return chunk


@pytest.mark.parametrize(
    "filename,content",
    [
        ("a.pdf", PDF),
        ("a.PDF", b"\n\n" + PDF),  # header may follow a little junk
        ("a.docx", ZIP),
        ("a.xlsx", ZIP),
        ("a.pptx", ZIP),
        ("a.doc", OLE),
        ("a.xls", OLE),
        ("a.ppt", OLE),
        ("a.msg", OLE),
        ("a.eml", EML),
        ("a.eml", b"From: a@x\nSubject: s\n\nbody"),
        ("a.eml", b"MIME-Version: 1.0\nContent-Type: text/plain\n\nx"),
        ("a.eml", b"From sender@example.test Mon Jan  1 00:00:00 2024\nFrom: a@x\n\nx"),
        ("a.jpg", JPG),
        ("a.jpeg", JPG),
        ("a.png", PNG),
        ("a.gif", b"GIF89a" + b"\x00" * 8),
        ("a.gif", b"GIF87a" + b"\x00" * 8),
        ("a.bmp", b"BM" + b"\x00" * 16),
        ("a.tif", b"II*\x00" + b"\x00" * 8),
        ("a.tiff", b"MM\x00*" + b"\x00" * 8),
        ("a.webp", b"RIFF\x10\x00\x00\x00WEBPVP8 "),
    ],
)
def test_matching_content_accepted(filename: str, content: bytes) -> None:
    assert content_matches_extension(filename, content) is True


@pytest.mark.parametrize(
    "filename,content",
    [
        ("a.pdf", b"<html><body>not a pdf</body></html>"),
        ("a.pdf", ZIP),
        ("a.pdf", EML),
        ("a.docx", PDF),
        ("a.docx", OLE),
        ("a.doc", ZIP),
        ("a.msg", ZIP),
        ("a.msg", EML),
        ("a.eml", PDF),
        ("a.eml", OLE),
        ("a.eml", b"\x00\x01\x02 binary junk"),
        ("a.eml", b"just some plain text without headers"),
        ("a.png", JPG),
        ("a.jpg", PNG),
        ("a.gif", PNG),
        ("a.webp", b"RIFF\x10\x00\x00\x00WAVEfmt "),
        ("a.pdf", b""),
    ],
)
def test_mismatched_content_rejected(filename: str, content: bytes) -> None:
    assert content_matches_extension(filename, content) is False


def test_unknown_extension_left_to_service_validation() -> None:
    """Extensions outside the allow-list are rejected by the service's own
    validation (400), not by the sniffer."""
    assert content_matches_extension("a.txt", b"hello") is None
    assert content_matches_extension("noext", b"hello") is None


async def test_read_verified_upload_returns_bytes() -> None:
    upload = _FakeUpload(PDF, "ok.pdf")
    assert await read_verified_upload(upload) == PDF


async def test_mismatch_raises_415() -> None:
    upload = _FakeUpload(b"<html>", "x.pdf")
    with pytest.raises(HTTPException) as exc:
        await read_verified_upload(upload)
    assert exc.value.status_code == 415


async def test_oversize_stops_reading_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The body is read in chunks and rejected as soon as the running
    total passes the limit, not after buffering all of it."""
    monkeypatch.setattr(ps, "MAX_FILE_SIZE", 1024)
    monkeypatch.setattr(ps, "UPLOAD_READ_CHUNK", 256)
    upload = _FakeUpload(PDF + b"x" * 100_000, "big.pdf")
    with pytest.raises(HTTPException) as exc:
        await read_verified_upload(upload)
    assert exc.value.status_code == 413
    assert upload.bytes_read <= 1024 + 256


async def test_declared_size_over_limit_rejected_without_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ps, "MAX_FILE_SIZE", 1024)
    upload = _FakeUpload(PDF, "big.pdf", size=10_000)
    with pytest.raises(HTTPException) as exc:
        await read_verified_upload(upload)
    assert exc.value.status_code == 413
    assert upload.bytes_read == 0


async def test_exactly_at_limit_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    body = PDF + b"x" * (1024 - len(PDF))
    monkeypatch.setattr(ps, "MAX_FILE_SIZE", 1024)
    monkeypatch.setattr(ps, "UPLOAD_READ_CHUNK", 100)
    assert await read_verified_upload(_FakeUpload(body, "ok.pdf")) == body
