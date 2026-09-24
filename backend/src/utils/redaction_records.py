"""
Redaction records: one validated shape and one release rule.

Every code path that creates or moves a redaction goes through
``parse_redaction_geometry`` + ``check_geometry_on_page`` (DOC-02, DOC-07), so
a stored box always has a real page and a finite, positive-area rectangle
inside that page. The same checks run again when the PDF is burned
(``src.utils.pdf_redaction``), so a bad record fails the release instead of
silently redacting nothing.

Coordinates are PDF points in the page's *displayed* space: origin at the
top-left of the page as a viewer shows it, after ``/Rotate`` is applied. That
is what pdf.js renders and what ``page.rect`` describes in PyMuPDF.

Release rule (DOC-13): only redactions whose effective status is
``approved`` are burned into exported or released PDFs. ``rejected`` ones
are ignored. Anything else (``proposed``, ``contested``, ``pending``, missing
status) is unresolved and blocks export/release of that document until a
reviewer decides it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# How far (in points) a box may extend past the page edge before it is
# rejected. Covers float noise from zoom conversion in the viewer; the part
# outside the page is clipped when the redaction is applied.
PAGE_EDGE_TOLERANCE = 1.0

APPROVED = "approved"
REJECTED = "rejected"
UNRESOLVED = "unresolved"

# System roles whose manually drawn redactions were stored as "pending" by
# older builds but always applied at release. They count as approved.
_STAFF_ROLES = frozenset({"owner", "admin", "analyst"})

GEOMETRY_FIELDS = ("page", "x", "y", "width", "height")


class RedactionValidationError(ValueError):
    """A redaction record is malformed or does not fit the document."""


class RedactionGeometry(BaseModel):
    """Page and rectangle of one redaction, in displayed-page points."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    page: int = Field(ge=1)
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)

    @field_validator("page", mode="before")
    @classmethod
    def _page_must_be_integral(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("page must be an integer")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("page must be an integer")
        return value

    @field_validator("x", "y", "width", "height", mode="before")
    @classmethod
    def _reject_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("must be a number")
        return value

    def as_fields(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "x": float(self.x),
            "y": float(self.y),
            "width": float(self.width),
            "height": float(self.height),
        }


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "redaction"
        parts.append(f"{loc}: {err.get('msg')}")
    return "; ".join(parts)


def parse_redaction_geometry(data: dict[str, Any]) -> RedactionGeometry:
    """Validate the geometry fields of ``data``.

    Raises RedactionValidationError when a field is missing, non-numeric,
    NaN/infinite, the page is below 1, or the box has no area.
    """
    if not isinstance(data, dict):
        raise RedactionValidationError("redaction must be an object")
    try:
        return RedactionGeometry.model_validate({k: data.get(k) for k in GEOMETRY_FIELDS})
    except ValidationError as exc:
        raise RedactionValidationError(_format_validation_error(exc)) from exc


def check_geometry_on_page(
    geometry: RedactionGeometry, page_sizes: Sequence[Sequence[float]]
) -> None:
    """Raise RedactionValidationError unless the box lies on an existing page.

    ``page_sizes`` holds ``(width, height)`` of every page in displayed space
    (PyMuPDF ``page.rect``), in page order.
    """
    page_count = len(page_sizes)
    if geometry.page > page_count:
        raise RedactionValidationError(
            f"page {geometry.page} does not exist (document has {page_count} pages)"
        )
    width, height = (float(v) for v in page_sizes[geometry.page - 1][:2])
    tol = PAGE_EDGE_TOLERANCE
    if (
        geometry.x < -tol
        or geometry.y < -tol
        or geometry.x + geometry.width > width + tol
        or geometry.y + geometry.height > height + tol
    ):
        raise RedactionValidationError(
            f"box ({geometry.x:.1f}, {geometry.y:.1f}, {geometry.width:.1f} x "
            f"{geometry.height:.1f}) is outside page {geometry.page} "
            f"({width:.1f} x {height:.1f})"
        )


def validate_redaction(
    data: dict[str, Any], page_sizes: Sequence[Sequence[float]]
) -> RedactionGeometry:
    """Parse and bounds-check one redaction. See the two helpers above."""
    geometry = parse_redaction_geometry(data)
    check_geometry_on_page(geometry, page_sizes)
    return geometry


def new_redaction_record(
    geometry: RedactionGeometry,
    *,
    status: str,
    created_by: str | None,
    source: str,
    created_by_role: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build a stored redaction record with a fresh stable id."""
    record: dict[str, Any] = dict(fields)
    record.update(geometry.as_fields())
    record["id"] = str(uuid.uuid4())
    record["status"] = status
    record["source"] = source
    record["created_by"] = created_by
    if created_by_role is not None:
        record["created_by_role"] = created_by_role
    record["created_at"] = datetime.now(UTC).replace(tzinfo=None)
    return record


def effective_status(redaction: dict[str, Any]) -> str:
    """Normalise a stored status to APPROVED, REJECTED or UNRESOLVED.

    - ``approved`` and the legacy synonym ``accepted`` are approved.
    - Legacy ``pending`` records drawn by staff (owner/admin/analyst) before
      the approval rule existed are approved: they were always applied.
    - ``rejected`` is rejected.
    - Everything else (``proposed``, ``contested``, other ``pending``,
      missing) is unresolved.
    """
    status = str(redaction.get("status") or "").strip().lower()
    if status in (APPROVED, "accepted"):
        return APPROVED
    if status == REJECTED:
        return REJECTED
    if (
        status == "pending"
        and redaction.get("type") != "proposed"
        and not redaction.get("bulk_operation")
        and not redaction.get("needs_coordinates")
        and redaction.get("created_by_role") in _STAFF_ROLES
    ):
        return APPROVED
    return UNRESOLVED


def partition_redactions(
    redactions: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split redactions into (to_apply, unresolved). Rejected ones are dropped.

    This is the single release rule used by export, the release package and
    its manifest/cover letter.
    """
    to_apply: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for redaction in redactions or []:
        state = effective_status(redaction)
        if state == APPROVED:
            to_apply.append(redaction)
        elif state == UNRESOLVED:
            unresolved.append(redaction)
    return to_apply, unresolved


def ensure_redaction_ids(redactions: list[dict[str, Any]]) -> bool:
    """Give every redaction without one a stable uuid. Returns True if any changed."""
    changed = False
    for redaction in redactions:
        if not redaction.get("id"):
            redaction["id"] = str(uuid.uuid4())
            changed = True
    return changed


def find_redaction(redactions: list[dict[str, Any]], ref: str) -> tuple[int, dict[str, Any]] | None:
    """Find a redaction by stable id.

    Legacy fallback (DOC-23): when ``ref`` is a non-negative integer and the
    record at that index has no id, it is returned. A record that already has
    an id can only be addressed by that id.
    """
    for index, redaction in enumerate(redactions):
        if redaction.get("id") == ref:
            return index, redaction
    if ref.isdigit():
        index = int(ref)
        if index < len(redactions) and not redactions[index].get("id"):
            return index, redactions[index]
    return None
