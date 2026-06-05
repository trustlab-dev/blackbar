"""
Case team role-based permissions
Defines what each role can do on a case
"""

# Role definitions with their permissions
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "manager": [
        "view",
        "edit",
        "redact",
        "upload",
        "comment",
        "manage_team",
        "propose_redactions",
        "contest_redactions",
        "reject_documents",
        "approve_release",
    ],
    "analyst": [
        "view",
        "edit",
        "redact",
        "upload",
        "comment",
        "manage_team",
        "propose_redactions",
        "contest_redactions",
        "approve_proposed_redactions",
    ],
    "legal": ["view", "comment", "propose_redactions", "contest_redactions"],
    "sme": ["view", "comment", "upload"],
    "reviewer": ["view", "comment", "propose_redactions", "contest_redactions", "reject_documents"],
    "approver": ["view", "comment", "propose_redactions", "approve_release", "reject_documents"],
    "third_party": ["view", "comment", "propose_redactions", "contest_redactions"],
}


def get_permissions_for_role(role: str) -> list[str]:
    """
    Get the list of permissions for a given role.

    Args:
        role: Role name (analyst, legal, sme, reviewer, approver, third_party, manager)

    Returns:
        List of permission strings
    """
    return ROLE_PERMISSIONS.get(role.lower(), [])


def can_user_perform_action(role: str, action: str) -> bool:
    """
    Check if a user with given role can perform an action.

    Args:
        role: User's role on the case team
        action: Action to check (e.g., "redact", "propose_redactions")

    Returns:
        True if user can perform action, False otherwise
    """
    permissions = get_permissions_for_role(role)
    return action in permissions


def can_manage_team(role: str) -> bool:
    """Check if role can add/remove team members"""
    return role.lower() in ["manager", "analyst"]


def can_create_redactions(role: str) -> bool:
    """Check if role can create professional (black) redactions"""
    return role.lower() in ["manager", "analyst"]


def can_propose_redactions(role: str) -> bool:
    """Check if role can propose (blue) redactions"""
    return role.lower() in ["manager", "analyst", "legal", "reviewer", "approver", "third_party"]


def can_approve_proposed_redactions(role: str) -> bool:
    """Check if role can approve/reject proposed redactions"""
    return role.lower() in ["manager", "analyst"]


def can_contest_redactions(role: str) -> bool:
    """Check if role can contest existing redactions"""
    return role.lower() in ["manager", "analyst", "legal", "reviewer", "third_party"]


def can_reject_documents(role: str) -> bool:
    """Check if role can reject documents"""
    return role.lower() in ["manager", "analyst", "reviewer", "approver"]


def can_approve_release(role: str) -> bool:
    """Check if role can approve final release"""
    return role.lower() in ["manager", "approver"]


def is_case_team_member(case_team: list[dict], user_id: str) -> bool:
    """
    Check if user is a member of the case team.

    Args:
        case_team: List of case team members
        user_id: User ID to check

    Returns:
        True if user is active member, False otherwise
    """
    for member in case_team:
        if member.get("user_id") == user_id and member.get("status") == "active":
            return True
    return False


def get_user_role_on_case(case_team: list[dict], user_id: str) -> str | None:
    """
    Get user's role on the case team.

    Args:
        case_team: List of case team members
        user_id: User ID to check

    Returns:
        Role string if user is active member, None otherwise
    """
    for member in case_team:
        if member.get("user_id") == user_id and member.get("status") == "active":
            return member.get("role")
    return None
