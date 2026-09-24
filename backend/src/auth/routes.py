"""
Authentication routes
"""

import logging
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator

from src.auth import security
from src.auth.audit import record_auth_event
from src.auth.auth_service import AuthService
from src.auth.roles import STAFF_ROLES, SYSTEM_ROLES
from src.core.dependencies import get_current_user_id, require_role
from src.core.rate_limit import LOGIN_LIMIT, limiter
from src.database import db
from src.users.repository import UsersRepository
from src.users.serializers import SAFE_USER_PROJECTION
from src.utils.log_utils import hash_email_for_logs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _validate_role_value(v: str | None) -> str | None:
    """Normalise and validate a system role string (AUTH-25)."""
    if v is None:
        return v
    role = v.strip().lower()
    if role not in SYSTEM_ROLES:
        raise ValueError(f"Invalid role; must be one of: {', '.join(SYSTEM_ROLES)}")
    return role


def _validate_new_password(v: str | None) -> str | None:
    if v is None:
        return v
    problem = security.password_policy_error(v)
    if problem:
        raise ValueError(problem)
    return v


class LoginRequest(BaseModel):
    """Login request model"""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate email format, allowing .local for development"""
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$|^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.local$"
        if not re.match(email_pattern, v.lower()):
            raise ValueError("Invalid email format")
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, v: str) -> str:
        # bcrypt ignores everything past 72 bytes; refuse rather than
        # silently truncate (AUTH-27).
        if security.password_too_long(v):
            raise ValueError(f"Password must be at most {security.BCRYPT_MAX_PASSWORD_BYTES} bytes")
        return v


class LoginResponse(BaseModel):
    """Login response model"""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    roles: list[str]  # kept for frontend compatibility


@router.post("/login", response_model=LoginResponse)
@limiter.limit(LOGIN_LIMIT)
async def login(request: Request, login_data: LoginRequest):
    """
    Authenticate user with email and password
    Returns JWT token
    """
    users_repo = UsersRepository(db)
    auth_service = AuthService(users_repo)

    # Authenticate user
    user = await auth_service.authenticate_local(login_data.email, login_data.password)

    if not user:
        await record_auth_event(
            db,
            "login_failed",
            request=request,
            success=False,
            details={"email_hash": hash_email_for_logs(login_data.email)},
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Issue token
    token = await auth_service.issue_token(user)
    await record_auth_event(db, "login_succeeded", request=request, actor_id=user.id)

    return LoginResponse(access_token=token, user_id=user.id, role=user.role, roles=[user.role])


@router.post("/logout")
async def logout(request: Request, user_id: str = Depends(get_current_user_id)):
    """
    Logout endpoint

    Revokes every token issued to the caller so far by bumping their
    `token_version` (AUTH-14). The client should also discard its token.
    """
    await db.users.update_one({"id": user_id}, {"$inc": {"token_version": 1}})
    await record_auth_event(db, "logout", request=request, actor_id=user_id)
    return {"message": "Logged out successfully"}


@router.get("/me")
async def get_current_user(request: Request):
    """
    Get current user information
    Supports both internal users and public users (RFC-007)
    """
    # Try to get token from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header.split(" ")[1]
    payload = AuthService.validate_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Handle public users (RFC-007)
    if payload.realm == "public":
        try:
            claims = security.decode_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"id": payload.sub, "email": claims.get("email"), "user_type": "public"}

    # Handle internal users: the DB, not the token, is the source of truth.
    user = await db.users.find_one({"id": payload.sub}, SAFE_USER_PROJECTION)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.get("status", "active") != "active":
        raise HTTPException(status_code=401, detail="Account is not active")
    if int(user.get("token_version") or 0) != payload.tv:
        raise HTTPException(status_code=401, detail="Session has been revoked")

    role = user.get("role") or "user"
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "name": user.get("name"),
        "status": user.get("status", "active"),
        "roles": [role],
        "user_type": "internal",
    }


@router.get("/roles")
async def get_roles():
    """Get available roles"""
    return {
        "roles": [
            {"id": "admin", "name": "Administrator", "description": "Full administrative access"},
            {"id": "analyst", "name": "Analyst", "description": "Can manage cases and documents"},
            {"id": "user", "name": "User", "description": "Regular user, can be assigned to cases"},
            {"id": "guest", "name": "Guest", "description": "Limited access for external parties"},
        ]
    }


@router.get("/users", dependencies=[Depends(require_role(["owner", "admin"]))])
async def get_users(request: Request, user_id: str = Depends(get_current_user_id)):
    """Get all users"""
    # Get all users
    all_users = await db.users.find({}, SAFE_USER_PROJECTION).to_list(length=1000)

    users_list = []
    for user_doc in all_users:
        users_list.append(
            {
                "id": user_doc.get("id"),
                "email": user_doc.get("email"),
                "username": user_doc.get("email", "").split("@")[0],
                "full_name": user_doc.get("name", ""),
                "role": user_doc.get("role", "user"),
                "created_at": (
                    user_doc.get("created_at").isoformat() if user_doc.get("created_at") else None
                ),
                "disabled": user_doc.get("status") != "active",
            }
        )

    return users_list


class UserCreate(BaseModel):
    """User creation model - password optional for magic link invitations"""

    email: str
    username: str | None = None
    full_name: str
    password: str | None = None
    role: str

    @field_validator("role")
    @classmethod
    def check_role_value(cls, v: str | None) -> str | None:
        return _validate_role_value(v)

    @field_validator("password")
    @classmethod
    def check_password_policy(cls, v: str | None) -> str | None:
        return _validate_new_password(v)


async def _caller_role(user_id: str) -> str:
    caller = await db.users.find_one({"id": user_id}, {"_id": 0, "role": 1})
    return (caller or {}).get("role", "")


async def _ensure_may_assign(role: str | None, caller_id: str) -> None:
    """Only an owner may hand out the owner role."""
    if role == "owner" and await _caller_role(caller_id) != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can assign the owner role")


@router.post("/users", dependencies=[Depends(require_role(["owner", "admin"]))])
async def create_user(
    request: Request, user_data: UserCreate, user_id: str = Depends(get_current_user_id)
):
    """Create a new user with optional magic link invitation"""
    users_repo = UsersRepository(db)
    await _ensure_may_assign(user_data.role, user_id)

    # Check if user already exists
    existing_user = await users_repo.get_by_email(user_data.email)

    if existing_user:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    # Create new user
    from src.users.models import UserCreate as UserCreateModel
    from src.users.models import UserStatus
    from src.utils.welcome_email_service import WelcomeEmailService

    welcome_service = WelcomeEmailService(None)

    # Generate activation token
    activation_token = welcome_service.generate_activation_token()
    token_hash = welcome_service.hash_token(activation_token)
    token_expires = datetime.utcnow() + timedelta(hours=48)

    # If password provided, hash it; otherwise user will set via activation
    password_hash = None
    user_status = UserStatus.PENDING_ACTIVATION
    if user_data.password:
        password_hash = AuthService.hash_password(user_data.password)
        user_status = UserStatus.ACTIVE

    new_user = UserCreateModel(
        email=user_data.email,
        name=user_data.full_name,
        password=user_data.password or "placeholder",
        status=user_status,
    )
    user = await users_repo.create(new_user, password_hash)

    # Set role on user record
    await db.users.update_one({"id": user.id}, {"$set": {"role": user_data.role}})

    # Store activation token if no password provided
    if not user_data.password:
        await db.users.update_one(
            {"id": user.id},
            {
                "$set": {
                    "activation_token": token_hash,
                    "activation_token_expires_at": token_expires,
                    "status": "pending_activation",
                }
            },
        )

        # Send invitation email
        try:
            # Get org name from system config
            config = await db.system_config.find_one({})
            org_name = config.get("org_name", "BlackBar") if config else "BlackBar"

            welcome_service.send_owner_welcome(
                owner_email=user_data.email,
                owner_name=user_data.full_name,
                org_name=org_name,
                activation_token=activation_token,
            )
            logger.info(f"Invitation email sent to user {user.id}")
        except Exception as e:
            logger.error(f"Failed to send invitation email: {e}")

    await record_auth_event(
        db,
        "user_created",
        request=request,
        actor_id=user_id,
        target_id=user.id,
        details={"role": user_data.role, "invited": not user_data.password},
    )

    return {
        "id": user.id,
        "email": user.email,
        "username": user.email.split("@")[0],
        "full_name": user.name or "",
        "role": user_data.role,
        "created_at": (
            user.created_at.isoformat() if hasattr(user, "created_at") and user.created_at else None
        ),
        "disabled": user.status != "active",
        "invitation_sent": not user_data.password,
    }


class UserUpdate(BaseModel):
    """User update model"""

    email: str | None = None
    username: str | None = None
    full_name: str | None = None
    password: str | None = None
    role: str | None = None
    disabled: bool | None = None

    @field_validator("role")
    @classmethod
    def check_role_value(cls, v: str | None) -> str | None:
        return _validate_role_value(v)

    @field_validator("password")
    @classmethod
    def check_password_policy(cls, v: str | None) -> str | None:
        return _validate_new_password(v)


@router.put("/users/{target_user_id}", dependencies=[Depends(require_role(["owner", "admin"]))])
async def update_user(
    request: Request,
    target_user_id: str,
    user_data: UserUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Update a user"""
    users_repo = UsersRepository(db)

    # Get user
    user = await users_repo.get_by_id(target_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await _ensure_may_assign(user_data.role, user_id)
    if user.role == "owner" and await _caller_role(user_id) != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can modify an owner account")

    # Prepare update data
    password_hash = None
    if user_data.password:
        password_hash = AuthService.hash_password(user_data.password)

    # Build UserUpdate object with only provided fields
    update_fields = {}
    if user_data.email:
        # Check if new email is already in use by another user
        existing_user = await users_repo.get_by_email(user_data.email)
        if existing_user and existing_user.id != target_user_id:
            raise HTTPException(status_code=400, detail="Email already in use by another user")
        update_fields["email"] = user_data.email
    if user_data.full_name:
        update_fields["name"] = user_data.full_name
    if user_data.disabled is not None:
        update_fields["status"] = "disabled" if user_data.disabled else "active"

    # Create UserUpdate model
    from src.users.models import UserUpdate as UserUpdateModel

    user_update = UserUpdateModel(**update_fields)

    await users_repo.update(target_user_id, user_update, password_hash)

    # Update role if provided
    role_changed = bool(user_data.role) and user_data.role != user.role
    if user_data.role:
        await db.users.update_one({"id": target_user_id}, {"$set": {"role": user_data.role}})

    # Revoke the target's existing sessions when their credentials or
    # privileges change (AUTH-14).
    if password_hash or user_data.disabled or role_changed:
        await db.users.update_one({"id": target_user_id}, {"$inc": {"token_version": 1}})

    await record_auth_event(
        db,
        "user_updated",
        request=request,
        actor_id=user_id,
        target_id=target_user_id,
        details={
            "fields": sorted(k for k, v in user_data.model_dump().items() if v is not None),
            "role_before": user.role,
            "role_after": user_data.role or user.role,
            "password_changed": bool(password_hash),
            "disabled": user_data.disabled,
        },
    )

    return {
        "id": user.id,
        "email": user.email,
        "username": user.email.split("@")[0],
        "full_name": user.name or "",
        "role": user_data.role or user.role,
        "disabled": user.status != "active",
    }


@router.delete("/users/{target_user_id}", dependencies=[Depends(require_role(["owner", "admin"]))])
async def delete_user(
    request: Request, target_user_id: str, user_id: str = Depends(get_current_user_id)
):
    """Delete a user"""
    target = await db.users.find_one({"id": target_user_id}, {"_id": 0, "role": 1})
    if target and target.get("role") == "owner" and await _caller_role(user_id) != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can delete an owner account")

    # Delete user record
    result = await db.users.delete_one({"id": target_user_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    await record_auth_event(
        db,
        "user_deleted",
        request=request,
        actor_id=user_id,
        target_id=target_user_id,
        details={"role": (target or {}).get("role")},
    )
    return {"message": "User deleted"}


@router.get("/users/assignable", dependencies=[Depends(require_role(STAFF_ROLES))])
async def list_assignable_users(request: Request, user_id: str = Depends(get_current_user_id)):
    """List users who can be assigned to cases"""
    assignable_roles = ["admin", "analyst", "owner"]
    users_cursor = db.users.find(
        {"role": {"$in": assignable_roles}, "status": "active"}, SAFE_USER_PROJECTION
    )
    users_list = await users_cursor.to_list(length=1000)

    return [
        {
            "id": u.get("id"),
            "name": u.get("name"),
            "email": u.get("email"),
            "role": u.get("role", "user"),
        }
        for u in users_list
    ]


@router.get("/users/guests", dependencies=[Depends(require_role(STAFF_ROLES))])
async def list_guest_users(request: Request, user_id: str = Depends(get_current_user_id)):
    """List guest users (for document sharing)"""
    guests_cursor = db.users.find({"role": "guest", "status": "active"}, SAFE_USER_PROJECTION)
    guests_list = await guests_cursor.to_list(length=1000)

    return [
        {"id": u.get("id"), "name": u.get("name"), "email": u.get("email"), "role": "guest"}
        for u in guests_list
    ]


@router.get("/users/search", dependencies=[Depends(require_role(STAFF_ROLES))])
async def search_users_for_team(
    request: Request,
    user_id: str = Depends(get_current_user_id),
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
):
    """
    Search users for team assignment.
    Returns users matching query by email or name.
    """
    # Build query
    query: dict = {"status": "active"}

    if q and len(q) >= 2:
        q_escaped = re.escape(q.lower())
        query["$or"] = [
            {"name": {"$regex": q_escaped, "$options": "i"}},
            {"email": {"$regex": q_escaped, "$options": "i"}},
        ]

    users_cursor = db.users.find(query, SAFE_USER_PROJECTION).limit(limit)
    users_list = await users_cursor.to_list(length=limit)

    return {
        "users": [
            {
                "id": u.get("id"),
                "name": u.get("name"),
                "email": u.get("email"),
                "role": u.get("role", "user"),
            }
            for u in users_list
        ]
    }
