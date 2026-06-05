"""
Magic Link Authentication Routes (RFC-007)
API endpoints for passwordless email authentication
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, validator

from src.auth.magic_link_service import MagicLinkService
from src.core.database import get_shared_database
from src.public_users.repository import MagicLinkTokensRepository, PublicUsersRepository
from src.utils.email_service import EmailService

logger = logging.getLogger(__name__)

# Initialize email service
email_service = EmailService()

router = APIRouter(prefix="/auth/public/magic-link", tags=["Magic Link Authentication"])


# Dependency to get magic link service
async def get_magic_link_service() -> MagicLinkService:
    """Dependency to create MagicLinkService"""
    db = get_shared_database()
    users_repo = PublicUsersRepository(db)
    tokens_repo = MagicLinkTokensRepository(db)

    return MagicLinkService(
        users_repo=users_repo, tokens_repo=tokens_repo, token_expiration_minutes=15
    )


# Request/Response Models
class MagicLinkRequest(BaseModel):
    """Request model for magic link"""

    email: EmailStr
    name: str | None = None

    @validator("email")
    def normalize_email(cls, v):
        """Normalize email to lowercase to prevent rate limit bypass"""
        return v.lower().strip() if v else v


class MagicLinkResponse(BaseModel):
    """Response after requesting magic link"""

    message: str
    expires_in: int  # seconds


class VerifyRequest(BaseModel):
    """Request model for verifying magic link"""

    token: str
    email: EmailStr

    @validator("email")
    def normalize_email(cls, v):
        """Normalize email to lowercase for consistent comparison"""
        return v.lower().strip() if v else v


class AuthResponse(BaseModel):
    """Authentication response with JWT"""

    access_token: str
    token_type: str = "bearer"
    user: dict


# Endpoints
@router.post("/request", response_model=MagicLinkResponse)
async def request_magic_link(
    request_data: MagicLinkRequest,
    request: Request,
    service: MagicLinkService = Depends(get_magic_link_service),
):
    """
    Request a magic link to be sent to email

    Rate limit: 3 requests per hour per email
    Token expires: 15 minutes
    """
    try:
        # Get client info for audit
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # Generate and store token
        token, expires_at = await service.request_magic_link(
            email=request_data.email,
            name=request_data.name,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Build magic link URL from configurable base URL
        base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000")
        magic_link_url = f"{base_url}/public/verify/{token}"

        # Send email
        org_name = os.getenv("ORG_NAME", "BlackBar")
        email_sent = email_service.send_magic_link(
            to_email=request_data.email,
            magic_link_url=magic_link_url,
            org_name=org_name,
            expires_minutes=15,
        )

        if not email_sent:
            logger.warning(f"Failed to send email to {request_data.email}, but token was created")
            # Continue anyway - in dev mode, token is logged

        return MagicLinkResponse(
            message=f"Magic link sent to {request_data.email}",
            expires_in=900,  # 15 minutes in seconds
        )

    except ValueError as e:
        if str(e) == "RATE_LIMIT_EXCEEDED":
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": "Too many requests. Please wait before requesting another link.",
                    "retry_after": 3600,  # 1 hour
                },
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to request magic link: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send magic link. Please try again.")


@router.post("/verify", response_model=AuthResponse)
async def verify_magic_link(
    verify_data: VerifyRequest,
    request: Request,
    service: MagicLinkService = Depends(get_magic_link_service),
):
    """
    Verify magic link token and issue JWT

    Token is single-use and expires after 15 minutes
    """
    try:
        # Verify token
        user = await service.verify_magic_link(token=verify_data.token, email=verify_data.email)

        if not user:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_token",
                    "message": "Magic link is invalid or has expired. Please request a new one.",
                },
            )

        # Issue JWT
        access_token = service.issue_token(user)

        return AuthResponse(
            access_token=access_token,
            user={
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "email_verified": user.email_verified,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify magic link: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to verify magic link. Please try again."
        )


@router.get("/health")
async def health_check():
    """Health check for magic link endpoints"""
    return {"status": "healthy", "service": "magic_link_auth"}


# ---------------------------------------------------------------------------
# Demo login — env-gated convenience for testing the public-side UX without
# going through the magic-link email flow. Returns 404 unless
# BLACKBAR_DEMO_MODE=true. Never enable in production.
# ---------------------------------------------------------------------------


# Use a separate router with a different prefix so the path is
# /api/v1/auth/public/demo-login (still under the /auth/public/ public
# allowlist) but doesn't collide with the magic-link namespace.
demo_router = APIRouter(prefix="/auth/public", tags=["Demo Login (env-gated)"])


# Single fixed demo persona. Matches the TrustLab demo case's requester
# so logging in here gives access to FOI-2026-007-DJH in the dashboard.
DEMO_PERSONA = {
    "email": "jordan.park@example.org",
    "name": "Jordan Park",
}


@demo_router.post("/demo-login", response_model=AuthResponse)
async def demo_login(
    request: Request,
    service: MagicLinkService = Depends(get_magic_link_service),
):
    """Mint a JWT for the demo persona without requiring a magic link.

    Gated by the BLACKBAR_DEMO_MODE env var. When the env var is absent
    or not equal to "true", the route returns 404 so the existence of
    the endpoint isn't even advertised in non-demo deployments.

    Idempotent: upserts the demo public_user, marks email_verified=true,
    and issues a fresh JWT in the public realm valid for the configured
    JWT_EXPIRATION window.
    """
    if os.getenv("BLACKBAR_DEMO_MODE", "").lower() != "true":
        # Same 404 the FastAPI router would return for an unknown path,
        # so we don't disclose that the endpoint exists.
        raise HTTPException(status_code=404, detail="Not Found")

    from src.public_users.models import PublicUserCreate

    # Upsert the demo user. Calling create_or_update via the repo would be
    # nicer but get_by_email + create + update_last_login matches the
    # existing magic-link verify flow.
    user = await service.users_repo.get_by_email(DEMO_PERSONA["email"])
    if not user:
        user_create = PublicUserCreate(email=DEMO_PERSONA["email"], name=DEMO_PERSONA["name"])
        user = await service.users_repo.create(user_create)
        logger.info(f"Created demo public user {DEMO_PERSONA['email']}")

    # Mark email_verified so the rest of the public-side surface treats
    # the demo session like a real verified one.
    if not getattr(user, "email_verified", False):
        await service.users_repo.collection.update_one(
            {"id": user.id},
            {"$set": {"email_verified": True}},
        )
        user.email_verified = True

    await service.users_repo.update_last_login(user.id)
    access_token = service.issue_token(user)

    logger.info(f"Issued demo public JWT to {DEMO_PERSONA['email']}")
    return AuthResponse(
        access_token=access_token,
        user={
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "email_verified": True,
        },
    )
