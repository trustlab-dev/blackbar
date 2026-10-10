"""
Redaction records: one validated shape and one release rule.

Every code path that creates or moves a redaction goes through
``parse_redaction_geometry`` + ``check_geometry_on_page`` (DOC-02, DOC-07), so
a stored box always has a real page and a finite, positive-area rectangle
inside that page. The same checks run again when the PDF is burned
(``src.utils.pdf_redaction``), so a bad record fails the release instead of
silently redacting nothing.

Coordinate space (C1): every coordinate the API accepts or returns
(redaction boxes, AI suggestion ``coordinates``, ``text_data`` word, line and
block boxes) is in PDF points in the page's *displayed* space: origin at the
top-left of the page as a viewer shows it, after ``/Rotate`` is applied.
That is what pdf.js renders and what ``page.rect`` describes in PyMuPDF.
Records created from this release on carry ``coord_space: "displayed"`` and
the ``page_rotation`` (0/90/180/270) of their page when they were placed;
the burn step converts them to unrotated page space and refuses a record
whose page rotation no longer matches.

Legacy records (no ``coord_space``) were written by builds that mixed the
two spaces: boxes drawn in the viewer were displayed-space, boxes taken from
AI suggestions or native text were unrotated. On a page with rotation 0 the
two spaces are identical, so such records are used as they are. On a
rotated page the space is unknown, so the record is unresolved
(``legacy_rotated_coordinates``) and blocks export/release until a reviewer
looks at it in the viewer and approves it (which confirms the displayed
position and stamps the marker) or deletes and re-adds it. See
``src.migrations.tag_redaction_coordinate_space``.

Release rule (DOC-13): only redactions whose effective status is
``approved`` are burned into exported or released PDFs. ``rejected`` ones
are ignored. Anything else (``proposed``, ``contested``, ``pending``, missing
status, no usable geometry, legacy boxes on rotated pages) is unresolved and
blocks export/release of that document until a reviewer decides it.
``review_state`` gives the reason for each unresolved record.
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

# Coordinate-space marker stamped on every new redaction and suggestion.
DISPLAYED_SPACE = "displayed"

# Why an unresolved redaction blocks export/release: (message, approvable).
# "approvable" means the approve/reject route can resolve it.
UNRESOLVED_REASONS: dict[str, tuple[str, bool]] = {
    "proposed": ("Proposed redaction awaiting approval.", True),
    "contested": ("Redaction has an open contest; resolve the contest first.", False),
    "legacy_pending": (
        "Created as 'pending' by an older version of BlackBar and never approved; "
        "approve or reject it.",
        True,
    ),
    "legacy_no_role": (
        "Created by an older version of BlackBar without a recorded creator role; "
        "approve or reject it.",
        True,
    ),
    "legacy_rotated_coordinates": (
        "Created by an older version of BlackBar on a rotated page, so its position is "
        "ambiguous. Check where it appears in the viewer, then approve it to confirm that "
        "position, or delete it and add it again.",
        True,
    ),
    "unknown_status": ("Redaction has no recognised review status; approve or reject it.", True),
    "no_geometry": (
        "Redaction has no usable position on the page and cannot be approved. Delete it "
        "and add it again (re-run bulk apply for bulk or AI redactions).",
        False,
    ),
}


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


def normalise_rotation(value: Any) -> int:
    """A page rotation as 0, 90, 180 or 270."""
    try:
        return int(value) % 360
    except (TypeError, ValueError):
        return 0


def coordinate_space_fields(page_rotation: Any) -> dict[str, Any]:
    """The marker fields for a box in displayed space on a page rotated by
    ``page_rotation`` degrees."""
    return {"coord_space": DISPLAYED_SPACE, "page_rotation": normalise_rotation(page_rotation)}


def has_legacy_coordinates(redaction: dict[str, Any]) -> bool:
    """True for records written before the coordinate-space marker."""
    return not redaction.get("coord_space")


def page_rotation_of(page_sizes: Sequence[Sequence[float]], page: int) -> int:
    """Rotation of 1-based ``page`` from ``[[w, h, rotation], ...]`` (0 when
    the entry carries no rotation)."""
    if 1 <= page <= len(page_sizes):
        entry = page_sizes[page - 1]
        if len(entry) >= 3:
            return normalise_rotation(entry[2])
    return 0


def new_redaction_record(
    geometry: RedactionGeometry,
    *,
    status: str,
    created_by: str | None,
    source: str,
    page_rotation: int,
    created_by_role: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build a stored redaction record with a fresh stable id.

    ``geometry`` is in displayed space on a page rotated by ``page_rotation``.
    """
    record: dict[str, Any] = dict(fields)
    record.update(geometry.as_fields())
    record.update(coordinate_space_fields(page_rotation))
    record["id"] = str(uuid.uuid4())
    record["status"] = status
    record["source"] = source
    record["created_by"] = created_by
    if created_by_role is not None:
        record["created_by_role"] = created_by_role
    record["created_at"] = datetime.now(UTC).replace(tzinfo=None)
    return record


def review_state(
    redaction: dict[str, Any], page_rotations: Sequence[int] | None = None
) -> tuple[str, str | None]:
    """Classify a stored redaction as ``(state, reason)``.

    ``state`` is APPROVED, REJECTED or UNRESOLVED; ``reason`` is a key of
    ``UNRESOLVED_REASONS`` for unresolved records, else None.

    - ``rejected`` is rejected (whatever its geometry).
    - A record without usable geometry is unresolved (``no_geometry``).
    - ``approved`` and the legacy synonym ``accepted`` are approved, and so
      are legacy ``pending`` records drawn by staff (owner/admin/analyst)
      before the approval rule existed: they were always applied.
    - ``proposed``, ``contested``, other ``pending`` and missing statuses are
      unresolved.
    - With ``page_rotations`` (one entry per page), an approved legacy
      record on a rotated page is unresolved (``legacy_rotated_coordinates``).
    """
    status = str(redaction.get("status") or "").strip().lower()
    if status == REJECTED:
        return REJECTED, None
    try:
        geometry = parse_redaction_geometry(redaction)
    except RedactionValidationError:
        return UNRESOLVED, "no_geometry"

    if status in (APPROVED, "accepted"):
        state, reason = APPROVED, None
    elif status == "proposed" or (redaction.get("type") == "proposed" and status == "pending"):
        state, reason = UNRESOLVED, "proposed"
    elif status == "contested":
        state, reason = UNRESOLVED, "contested"
    elif status == "pending":
        role = redaction.get("created_by_role")
        if (
            role in _STAFF_ROLES
            and not redaction.get("bulk_operation")
            and not redaction.get("needs_coordinates")
        ):
            state, reason = APPROVED, None
        elif not role:
            state, reason = UNRESOLVED, "legacy_no_role"
        else:
            state, reason = UNRESOLVED, "legacy_pending"
    else:
        state, reason = UNRESOLVED, "unknown_status"

    if (
        state == APPROVED
        and page_rotations is not None
        and has_legacy_coordinates(redaction)
        and 1 <= geometry.page <= len(page_rotations)
        and normalise_rotation(page_rotations[geometry.page - 1]) != 0
    ):
        return UNRESOLVED, "legacy_rotated_coordinates"
    return state, reason


def effective_status(redaction: dict[str, Any]) -> str:
    """APPROVED, REJECTED or UNRESOLVED for one record (see ``review_state``)."""
    return review_state(redaction)[0]


def partition_redactions(
    redactions: Iterable[dict[str, Any]],
    page_rotations: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split redactions into (to_apply, unresolved). Rejected ones are dropped.

    This is the single release rule used by export, the release package and
    its manifest/cover letter. Pass ``page_rotations`` whenever the PDF is
    known so legacy boxes on rotated pages are held back.
    """
    to_apply: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for redaction in redactions or []:
        state, _ = review_state(redaction, page_rotations)
        if state == APPROVED:
            to_apply.append(redaction)
        elif state == UNRESOLVED:
            unresolved.append(redaction)
    return to_apply, unresolved


def describe_unresolved(
    redaction: dict[str, Any], page_rotations: Sequence[int] | None = None
) -> dict[str, Any] | None:
    """Why ``redaction`` blocks export/release, or None if it does not.

    ``{"id", "page", "status", "reason", "message", "approvable"}``.
    """
    state, reason = review_state(redaction, page_rotations)
    if state != UNRESOLVED or reason is None:
        return None
    message, approvable = UNRESOLVED_REASONS[reason]
    return {
        "id": redaction.get("id"),
        "page": redaction.get("page"),
        "status": redaction.get("status"),
        "reason": reason,
        "message": message,
        "approvable": approvable,
    }


def unresolved_summary(
    redactions: Iterable[dict[str, Any]], page_rotations: Sequence[int] | None = None
) -> list[dict[str, Any]]:
    """``describe_unresolved`` for every blocking record, in order."""
    out = []
    for redaction in redactions or []:
        described = describe_unresolved(redaction, page_rotations)
        if described is not None:
            out.append(described)
    return out


def unresolved_message(details: list[dict[str, Any]], action: str) -> str:
    """One-line human summary of ``unresolved_summary`` output."""
    parts = [
        f"{d.get('id') or '?'} (page {d.get('page') if d.get('page') is not None else '?'}): "
        f"{d['reason']}"
        for d in details
    ]
    return (
        f"{len(details)} redaction(s) are awaiting review and block {action}: "
        + "; ".join(parts)
        + ". Approve or reject proposals, resolve contests, and delete and re-add "
        "redactions that have no usable position."
    )


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
