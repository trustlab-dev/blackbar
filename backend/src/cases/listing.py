"""Field filtering for case list responses (AUTH-12).

List routes return raw case documents. Team-scoped (non-global) callers must
not receive live capability tokens or internal workflow records, and guests
(external third parties) must not see the internal audit trail or internal
comments.
"""

from __future__ import annotations

from typing import Any

from ..core.authz import has_global_access
from .models import CommentType

# Case fields never returned to team-scoped (non-global) callers in list
# views: live capability tokens and internal workflow records (AUTH-12).
_TEAM_SCOPED_HIDDEN_FIELDS = ("collection_links", "release_packages", "extensions")
# Guests (external third parties) additionally never see the internal audit
# trail; their comments are filtered to public ones.
_GUEST_HIDDEN_FIELDS = ("audit_log",)


def redact_case_for_listing(doc: dict[str, Any], current_user: dict) -> dict[str, Any]:
    """Strip fields a non-global caller must not receive from a raw case doc."""
    if has_global_access(current_user):
        return doc
    hidden = set(_TEAM_SCOPED_HIDDEN_FIELDS)
    if current_user.get("role") == "guest":
        hidden.update(_GUEST_HIDDEN_FIELDS)
    out = {k: v for k, v in doc.items() if k not in hidden}
    if current_user.get("role") == "guest" and "comments" in out:
        out["comments"] = [
            c for c in out.get("comments") or [] if c.get("type") == CommentType.PUBLIC.value
        ]
    return out
