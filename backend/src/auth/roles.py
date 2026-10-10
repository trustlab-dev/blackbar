"""
Role definitions and management for the application.
Centralized role configuration to ensure consistency across the system.

System Roles (4-tier):
- admin: Full system access
- analyst: FOI staff - create cases, view all cases
- user: Limited staff - view only assigned cases
- guest: External - view only invited cases
"""

# Available system roles
AVAILABLE_ROLES = [
    {
        "id": "admin",
        "name": "Admin",
        "description": "Full system access - manage users, teams, and all cases",
    },
    {
        "id": "analyst",
        "name": "Analyst",
        "description": "FOI staff - create and manage cases, view all cases",
    },
    {
        "id": "user",
        "name": "User",
        "description": "Limited staff - view only assigned cases (legal, privacy, reviewers)",
    },
    {
        "id": "guest",
        "name": "Guest",
        "description": "External collaborators - view only invited cases (third-parties)",
    },
]

# Role hierarchy (for permission checks)
ROLE_HIERARCHY = {"owner": 5, "admin": 4, "analyst": 3, "user": 2, "guest": 1}

# Every system role a user record may hold. `owner` is not offered in the
# role picker (AVAILABLE_ROLES) but is honoured by the authz layer, so it is
# assignable only by another owner (AUTH-25).
SYSTEM_ROLES = ("owner", "admin", "analyst", "user", "guest")

# Internal staff: everyone except external guests.
STAFF_ROLES = ["owner", "admin", "analyst", "user"]


def get_available_roles():
    """Get list of available roles"""
    return AVAILABLE_ROLES


def get_role_ids():
    """Get list of role IDs"""
    return [role["id"] for role in AVAILABLE_ROLES]


def is_valid_role(role: str) -> bool:
    """Check if a role is a known system role (including `owner`)."""
    return role in SYSTEM_ROLES


def get_role_level(role: str) -> int:
    """Get the hierarchy level of a role"""
    return ROLE_HIERARCHY.get(role, 0)


def has_permission(user_role: str, required_role: str) -> bool:
    """Check if user_role has at least the level of required_role"""
    return get_role_level(user_role) >= get_role_level(required_role)
