import os
import warnings

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Suppress PyMuPDF font warnings
warnings.filterwarnings("ignore", message=".*Cannot load system font.*")

# Initialize structured logging first (before any other imports that might log)
from src.core.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
from src.admin.config_routes import router as config_router
from src.admin.llm_routes import router as llm_admin_router
from src.admin.routes import router as admin_router
from src.auth.activation_routes import router as activation_router
from src.auth.magic_link_routes import demo_router as public_demo_router
from src.auth.magic_link_routes import router as magic_link_router
from src.auth.routes import router as auth_router
from src.cases.public_routes import router as public_case_router
from src.cases.routes import router as case_router
from src.cases.status_routes import router as status_router
from src.categories.routes import router as category_router
from src.documents.routes import router as document_router
from src.documents.share_routes import router as document_share_router
from src.packs.routes import router as packs_router
from src.teams.routes import router as teams_router
from src.templates.routes import router as templates_router

# Workflow routes
from src.workflow.routes import router as workflow_router

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

_is_production = os.getenv("ENVIRONMENT", "development") == "production"
app = FastAPI(
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add standard error handlers
from fastapi import HTTPException

from src.utils.error_handler import (
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


# Initialize telemetry on startup
@app.on_event("startup")
async def startup_event():
    """Initialize telemetry, database indexes, and default templates"""
    # Initialize telemetry (OpenTelemetry, Sentry, metrics)
    from src.core.telemetry import init_telemetry

    init_telemetry(app)
    logger.info("Application starting up", startup_phase="init")

    from src.core.database import create_indexes
    from src.database import db, templates
    from src.users.repository import UsersRepository

    # Create indexes for all collections in single database
    users_repo = UsersRepository(db)
    await users_repo.create_indexes()
    await create_indexes(db)

    # Seed default templates
    from src.utils.seed_templates import seed_default_templates

    await seed_default_templates(templates)

    logger.info("Application startup complete", startup_phase="complete")


from src.config import ALLOWED_ORIGINS

# Middleware setup
# NOTE: Middleware executes in REVERSE order of addition
from src.core.auth_middleware import AuthMiddleware
from src.core.correlation import CorrelationMiddleware

# Add in reverse order of execution:
app.add_middleware(AuthMiddleware)  # Executes 3rd (innermost, closest to routes)
app.add_middleware(CorrelationMiddleware)  # Executes 2nd (adds correlation ID and metrics)
app.add_middleware(
    CORSMiddleware,  # Executes 1st (outermost)
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID", "X-Request-ID"],
)

# Create API router with /api/v1 prefix (versioned API)
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

# Include all routers under /api
# Authentication routes
api_router.include_router(auth_router, tags=["Authentication"])
# Magic link auth routes (RFC-007)
api_router.include_router(magic_link_router, tags=["Magic Link Authentication"])
# Demo login (env-gated by BLACKBAR_DEMO_MODE; returns 404 in production)
api_router.include_router(public_demo_router, tags=["Demo Login (env-gated)"])
# Account activation routes (WP-001)
api_router.include_router(activation_router, tags=["Account Activation"])
# Public FOI request routes (RFC-007)
api_router.include_router(public_case_router, tags=["Public FOI Requests"])
api_router.include_router(case_router)
# Register share router BEFORE main document router to avoid /{document_id} catching /shared-with-me
api_router.include_router(document_share_router, prefix="/documents", tags=["Document Sharing"])
api_router.include_router(document_router, prefix="/documents", tags=["Documents"])
api_router.include_router(category_router, prefix="/categories")
api_router.include_router(status_router, prefix="/config", tags=["Configuration"])
api_router.include_router(teams_router)
api_router.include_router(llm_admin_router)
# Legacy admin routes
api_router.include_router(admin_router)
api_router.include_router(config_router)
api_router.include_router(packs_router)
api_router.include_router(templates_router)
# Workflow routes (clock, contributors, queue, transfers, records confirmation)
api_router.include_router(workflow_router)

# Mount the API router
app.include_router(api_router)

# Mount metrics endpoint at root level (not under /api/v1)
from src.core.metrics_routes import router as metrics_router

app.include_router(metrics_router)


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


@app.get("/")
async def root():
    return {"message": "FOI Document API"}


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint for monitoring"""
    import os
    from datetime import datetime

    correlation_id = getattr(request.state, "correlation_id", None)

    try:
        # Check database connection
        from src.database import db

        await db.command("ping")

        return {
            "status": "healthy",
            "service": "blackbar-backend",
            "version": os.getenv("SERVICE_VERSION", "1.0.0"),
            "environment": os.getenv("ENVIRONMENT", "development"),
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat(),
            "correlation_id": correlation_id,
        }
    except Exception as e:
        logger.error("Health check failed", error=str(e), correlation_id=correlation_id)
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "blackbar-backend",
                "database": "disconnected",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
                "correlation_id": correlation_id,
            },
        )
