# Roles in BlackBar

**Status:** Active standard
**Last Updated:** 2026-05-14
**Audience:** Anyone touching authentication, authorisation, route
decorators, or case-team logic in BlackBar.

---

## TL;DR

BlackBar has **two independent role taxonomies** that share a namespace
but mean different things. Pick the right one for the job:

| Taxonomy | Where it lives | Scope | Set on |
| --- | --- | --- | --- |
| **User roles** (4 tiers) | `backend/src/auth/roles.py` | System-wide | `users.role` |
| **Case-team roles** (7 peers) | `backend/src/cases/permissions.py` | Per-case | `cases.case_team[*].role` |

The string `"analyst"` exists in **both** taxonomies. They are NOT
equivalent. A user whose **system role** is `analyst` does NOT
automatically have **case-team role** `analyst` on any case — case-team
roles are assigned explicitly when a user is added to a case team.

If you only read one section: jump to [Permission-check patterns](#permission-check-patterns).

---

## User roles (system-level, 4-tier)

Defined in `backend/src/auth/roles.py`. The canonical list:

```python
AVAILABLE_ROLES = [
    {"id": "admin",   "name": "Admin",   "description": "Full system access - manage users, teams, and all cases"},
    {"id": "analyst", "name": "Analyst", "description": "FOI staff - create and manage cases, view all cases"},
    {"id": "user",    "name": "User",    "description": "Limited staff - view only assigned cases"},
    {"id": "guest",   "name": "Guest",   "description": "External collaborators - view only invited cases"},
]
```

Each user document has exactly one `role` field (string, lowercase) that
takes one of these four values.

### Hierarchy

`auth/roles.py` defines a numeric hierarchy used by `has_permission`:

```python
ROLE_HIERARCHY = {"admin": 4, "analyst": 3, "user": 2, "guest": 1}
```

The hierarchy is consulted by `get_role_level(role)` and
`has_permission(user_role, required_role)`. The latter returns
`get_role_level(user_role) >= get_role_level(required_role)`.

**Quirk worth knowing:** `get_role_level` returns `0` for any unknown
role string. That means
`has_permission("nonsense_role", "another_nonsense_role")` returns
`True` (0 >= 0). In practice this is harmless — every code path that
calls `has_permission` first hardcodes a real `required_role` and passes
a `user_role` pulled from a validated JWT — but it is the literal
behaviour. Tracked in audit Section 11 (B4 cluster).

### Helpers

| Function | Returns |
| --- | --- |
| `get_available_roles()` | Full role-metadata list. |
| `get_role_ids()` | `["admin", "analyst", "user", "guest"]`. |
| `is_valid_role(role)` | `True` if `role` is one of the four. |
| `get_role_level(role)` | Numeric tier; `0` for unknown roles. |
| `has_permission(user, required)` | Tier-based `>=` comparison. |

---

## Case-team roles (per-case, 7-peer)

Defined in `backend/src/cases/permissions.py`. The canonical map:

```python
ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "manager":     [...],  # full case management + manage_team + approve_release
    "analyst":     [...],  # full case management + approve_proposed_redactions
    "legal":       ["view", "comment", "propose_redactions", "contest_redactions"],
    "sme":         ["view", "comment", "upload"],
    "reviewer":    [...],  # propose / contest / reject_documents
    "approver":    [...],  # propose_redactions, approve_release, reject_documents
    "third_party": ["view", "comment", "propose_redactions", "contest_redactions"],
}
```

These are **peers**, not a hierarchy. Each is a different role on a case
team with a different set of allowed actions.

Case-team roles are stored per-user per-case in the case document:

```json
{
  "id": "case-123",
  "case_team": [
    {"user_id": "u1", "role": "manager",  "status": "active"},
    {"user_id": "u2", "role": "legal",    "status": "active"},
    {"user_id": "u3", "role": "reviewer", "status": "active"}
  ]
}
```

> Note: `backend/src/cases/team_routes.py::ALLOWED_CASE_ROLES` still
> spells subject-matter expert as `"subject_matter_expert"` for the
> assignment-validation map (and still references the vestigial
> `"owner"` system role as an assignment-source key). The
> case-team role string actually persisted on the case is `"sme"`. A
> mechanical sweep to unify on `"sme"` is on the post-0.1.0 list.

### Resolution

To find a user's role on a specific case:

```python
from src.cases.permissions import get_user_role_on_case

role = get_user_role_on_case(case["case_team"], user_id)
# Returns the role string if user is an active team member,
# or None if they are not on the team (or are marked inactive).
```

### Permission predicates

`cases/permissions.py` exposes a set of `can_*` helpers built on the
`ROLE_PERMISSIONS` map. Prefer these to inline string lists at call
sites:

| Predicate | True for case-team roles |
| --- | --- |
| `can_manage_team(role)` | `manager`, `analyst` |
| `can_create_redactions(role)` | `manager`, `analyst` |
| `can_propose_redactions(role)` | `manager`, `analyst`, `legal`, `reviewer`, `approver`, `third_party` |
| `can_approve_proposed_redactions(role)` | `manager`, `analyst` |
| `can_contest_redactions(role)` | `manager`, `analyst`, `legal`, `reviewer`, `third_party` |
| `can_reject_documents(role)` | `manager`, `analyst`, `reviewer`, `approver` |
| `can_approve_release(role)` | `manager`, `approver` |

> Note: `can_propose_redactions` deliberately excludes `sme`. Audit
> Section 11 (B59) flags this — verify with product intent before
> changing.

### Membership helpers

| Function | Returns |
| --- | --- |
| `is_case_team_member(case_team, user_id)` | `True` if user is in `case_team` with `status == "active"`. |
| `get_user_role_on_case(case_team, user_id)` | Role string for an active member, else `None`. |

---

## The `"analyst"` namespace collision

The string `"analyst"` appears in **both** taxonomies:

- In **user roles**, `analyst` is the second-highest system role
  (FOI staff who can create and view all cases).
- In **case-team roles**, `analyst` is one of seven peer roles
  (full case management + can approve proposed redactions on the
  case).

These are **not** the same thing. Concretely:

- A user with system role `analyst` can read the case queue and create
  cases (because the route decorator allows the `analyst` system role).
- That same user has no case-team role on any specific case until they
  are explicitly added to that case's `case_team` array with a
  case-team role assignment.
- Conversely, a user with system role `user` can be added to a case
  team with the case-team role `analyst` and will have full case
  management on **that** case — but they still cannot access endpoints
  gated on the `analyst` system role.

When writing or reading permission logic, **always disambiguate** which
taxonomy you mean. The conventions in this codebase:

- Route-decorator string lists are **system roles**.
- `case_team[*].role` is a **case-team role**.
- `get_user_role_on_case(...)` returns a **case-team role**.
- `current_user["role"]` (extracted from the JWT) is a **system role**.

---

## Permission-check patterns

### System-level: route decorator

The canonical pattern for "is the caller allowed to hit this endpoint
at all?":

```python
from fastapi import Depends
from src.dependencies import check_role

@router.get(
    "/cases/queue/all",
    dependencies=[Depends(check_role(["admin", "analyst"]))],
)
async def get_all_cases_queue(...):
    ...
```

`check_role` is a dependency factory in `backend/src/dependencies.py`.
It pulls `current_user["role"]` from the JWT-validated user and returns
403 if the role is not in the supplied list. It uses Python `in`
membership, so unknown strings in the list are silently ignored — see
[Vestigial `"owner"` literal](#vestigial-owner-literal).

### Case-scoped: load + resolve + predicate

The canonical pattern for "is the caller allowed to do X on **this**
case?":

```python
from src.cases.permissions import get_user_role_on_case, can_approve_release

case = await db.cases.find_one({"id": case_id})
if not case:
    raise HTTPException(404, "Case not found")

team_role = get_user_role_on_case(case.get("case_team", []), current_user["id"])
if not team_role or not can_approve_release(team_role):
    raise HTTPException(403, "You don't have permission to approve releases on this case")
```

Always:
1. Load the case (so 404 wins over 403 when the case doesn't exist).
2. Resolve the case-team role via `get_user_role_on_case`.
3. Run the relevant `can_*` predicate.

### Mixed (rare): system OR case-team

A handful of endpoints accept either a high-tier system role OR a
specific case-team role. Example from `backend/src/cases/routes.py`
(`update_case`):

```python
@router.put("/{case_id}", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
async def update_case(...):
    user_role = current_user.get("role")
    if user_role not in ["owner", "admin", "manager"] and \
       current_user["id"] not in existing_case.get("assigned_user_ids", []) and \
       current_user["id"] != existing_case.get("created_by") and \
       current_user["id"] != existing_case.get("privacy_officer_id"):
        raise HTTPException(403, "...")
```

The list `["owner", "admin", "manager"]` mixes the two taxonomies:
`admin` is a system role, `manager` is a case-team role, and `"owner"`
is recognised by neither (see below). Behaviour happens to be correct
because the membership check is permissive — but the mixed list
obscures intent. New code should prefer the [case-scoped pattern](#case-scoped-load--resolve--predicate)
above. Tracked in audit Section 11 (B20).

---

## Vestigial `"owner"` literal

Many existing route decorators list `"owner"` in their `check_role`
list:

```python
@router.get("/...", dependencies=[Depends(check_role(["owner", "admin", "analyst"]))])
```

The string `"owner"` is recognised by **neither** taxonomy. It is a
remnant of a removed multi-tenant role tier. `check_role`'s membership
semantics make every `"owner"` literal a no-op — silently ignored,
because no token will ever decode to a `role` of `"owner"`.

Removing the stale `"owner"` literals from existing decorators is a
welcome contribution. New code MUST NOT add new `"owner"` literals.

---

## Lowercase, always

All role values — system and case-team — are stored, compared, and
listed as **lowercase** strings. The legacy `UserRole` enum (formerly
in `backend/src/auth/models.py`) followed Python's `UPPERCASE_NAME =
"lowercase_value"` convention; current code uses lowercase string
literals directly against the `AVAILABLE_ROLES` list in
`auth/roles.py`. MongoDB stores the lowercase values verbatim.

```python
# OK
if user_role in ["admin", "analyst"]: ...

# NOT OK — never compare uppercase
if user_role in ["ADMIN", "Analyst"]: ...
```

---

## Related docs

- [`docs/architecture/SECURITY_ARCHITECTURE.md`](../architecture/SECURITY_ARCHITECTURE.md)
  — the JWT-realm story (`public` / `org` / `admin` realms) and how
  role enforcement composes with realm enforcement.
