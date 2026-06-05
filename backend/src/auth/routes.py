"""
Authentication routes
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.auth.auth_service import AuthService
from src.core.dependencies import get_current_user_id, require_role
from src.database import db
from src.users.repository import UsersRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])
limiter = Limiter(key_func=get_remote_address)


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


class LoginResponse(BaseModel):
    """Login response model"""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    roles: list[str]  # kept for frontend compatibility


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
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
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Issue token
    token = await auth_service.issue_token(user)

    return LoginResponse(access_token=token, user_id=user.id, role=user.role, roles=[user.role])


@router.post("/logout")
async def logout():
    """
    Logout endpoint
    Since we use JWT, actual logout happens client-side by discarding the token
    """
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

    # Decode token to check user type
    import jwt

    from src.config import ALGORITHM, JWT_SECRET

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_type = payload.get("user_type")

        # Handle public users (RFC-007)
        if user_type == "public":
            return {"id": payload.get("sub"), "email": payload.get("email"), "user_type": "public"}

        # Handle internal users
        user_id = payload.get("sub")
        users_repo = UsersRepository(db)

        user = await users_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get role from user record
        role = payload.get("role") or user.role
        # Support legacy tokens with roles list
        if not role and "roles" in payload:
            roles_list = payload.get("roles", [])
            role = roles_list[0] if roles_list else "user"

        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "status": user.status,
            "roles": [role],
            "user_type": "internal",
        }
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


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
    users_repo = UsersRepository(db)

    # Get all users
    all_users = await db.users.find({}).to_list(length=1000)

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


@router.post("/users", dependencies=[Depends(require_role(["owner", "admin"]))])
async def create_user(
    request: Request, user_data: UserCreate, user_id: str = Depends(get_current_user_id)
):
    """Create a new user with optional magic link invitation"""
    users_repo = UsersRepository(db)
    auth_service = AuthService(users_repo)

    # Check if user already exists
    existing_user = await users_repo.get_by_email(user_data.email)

    if existing_user:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    # Create new user
    from datetime import datetime, timedelta

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
    await db.users.update_one({"id": user.id}, {"$set": {"role": user_data.role.lower()}})

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
    if user_data.role:
        await db.users.update_one(
            {"id": target_user_id}, {"$set": {"role": user_data.role.lower()}}
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
    # Delete user record
    result = await db.users.delete_one({"id": target_user_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User deleted"}


@router.get("/users/assignable")
async def list_assignable_users(request: Request, user_id: str = Depends(get_current_user_id)):
    """List users who can be assigned to cases"""
    assignable_roles = ["admin", "analyst", "owner"]
    users_cursor = db.users.find({"role": {"$in": assignable_roles}, "status": "active"})
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


@router.get("/users/guests")
async def list_guest_users(request: Request, user_id: str = Depends(get_current_user_id)):
    """List guest users (for document sharing)"""
    guests_cursor = db.users.find({"role": "guest", "status": "active"})
    guests_list = await guests_cursor.to_list(length=1000)

    return [
        {"id": u.get("id"), "name": u.get("name"), "email": u.get("email"), "role": "guest"}
        for u in guests_list
    ]


@router.get("/users/search")
async def search_users_for_team(
    request: Request, user_id: str = Depends(get_current_user_id), q: str = None, limit: int = 50
):
    """
    Search users for team assignment.
    Returns users matching query by email or name.
    """
    # Build query
    query = {"status": "active"}

    if q and len(q) >= 2:
        q_escaped = re.escape(q.lower())
        query["$or"] = [
            {"name": {"$regex": q_escaped, "$options": "i"}},
            {"email": {"$regex": q_escaped, "$options": "i"}},
        ]

    users_cursor = db.users.find(query).limit(limit)
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
