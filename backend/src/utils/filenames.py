"""
Safe filenames for HTTP headers and archive entries (DOC-21).

Uploaded filenames are user-controlled. They must never be able to break out
of a ``Content-Disposition`` header, crash Starlette's Latin-1 header
encoding, or escape an extraction directory as a ZIP entry name.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

_MAX_NAME_LENGTH = 180
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_basename(name: str | None, default: str = "document.pdf") -> str:
    """Last path component of ``name`` with control characters, quotes and
    parent-directory markers removed. Never empty, never ``.``/``..``."""
    text = unicodedata.normalize("NFC", str(name or ""))
    text = _CONTROL_CHARS.sub("", text)
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = text.replace('"', "").replace("..", "").strip().strip(".")
    text = text.strip()
    if not text:
        return default
    if len(text) > _MAX_NAME_LENGTH:
        stem, dot, ext = text.rpartition(".")
        if dot and len(ext) <= 10:
            text = stem[: _MAX_NAME_LENGTH - len(ext) - 1] + "." + ext
        else:
            text = text[:_MAX_NAME_LENGTH]
    return text


def _ascii_fallback(name: str) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").strip()
    )
    ascii_name = re.sub(r"[^A-Za-z0-9._ ()\-]", "_", ascii_name)
    return ascii_name or "download"


def content_disposition(filename: str | None, disposition: str = "attachment") -> str:
    """RFC 6266 header value: ASCII ``filename`` fallback plus UTF-8
    ``filename*``. Safe to pass to Starlette for any input."""
    name = safe_basename(filename, default="download")
    fallback = _ascii_fallback(name)
    encoded = quote(name, safe="")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


# Headers for responses that carry unredacted or original document content.
NO_STORE_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}
