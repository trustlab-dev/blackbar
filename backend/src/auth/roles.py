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
ROLE_HIERARCHY = {"admin": 4, "analyst": 3, "user": 2, "guest": 1}


def get_available_roles():
    """Get list of available roles"""
    return AVAILABLE_ROLES


def get_role_ids():
    """Get list of role IDs"""
    return [role["id"] for role in AVAILABLE_ROLES]


def is_valid_role(role: str) -> bool:
    """Check if a role is valid"""
    return role in get_role_ids()


def get_role_level(role: str) -> int:
    """Get the hierarchy level of a role"""
    return ROLE_HIERARCHY.get(role, 0)


def has_permission(user_role: str, required_role: str) -> bool:
    """Check if user_role has at least the level of required_role"""
    return get_role_level(user_role) >= get_role_level(required_role)
