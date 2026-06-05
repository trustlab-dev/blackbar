# Developer Quick Start

This guide covers the essentials for developing on BlackBar, a single-tenant
open-source application built with FastAPI (backend) and React (frontend),
backed by MongoDB.

---

## 1. Quick Setup

```bash
# One-time bootstrap: prompts for admin email/password, creates the
# admin user, and writes INITIAL_CREDS.txt with the database password.
bash setup.sh

# Start all services (backend, frontend, MongoDB)
docker compose up

# Frontend:  http://localhost:3000
# Backend:   http://localhost:8000
# API docs:  http://localhost:8000/docs
```

The admin email and password are whatever you entered during
`setup.sh`. There are no hardcoded default credentials.

---

## 2. Project Structure

```
backend/
  src/
    admin/           # Admin configuration routes
    auth/            # Authentication (login, registration, tokens)
    cases/           # Case management routes and models
    categories/      # Category management
    config.py        # App configuration (env vars, secrets)
    core/            # Core utilities (database, auth middleware, logging)
    database.py      # Database handle and collection references
    dependencies.py  # Auth dependencies (get_current_user, check_role)
    documents/       # Document management routes
    llm/             # LLM provider abstraction
    main.py          # FastAPI app entrypoint
    migrations/      # Database migrations
    packs/           # Redaction packs
    public_users/    # Public-facing user endpoints
    scripts/         # Utility scripts
    teams/           # Team management
    templates/       # Document templates
    users/           # User management
    utils/           # Shared utilities (PDF, OCR, search, etc.)
    workflow/        # Workflow engine (clock events, messages, reminders)

frontend/
  src/
    api/             # API client (client.ts)
    components/      # Reusable UI components
    contexts/        # React contexts (AuthContext, UserContext)
    layouts/         # Page layouts
    pages/           # Route-level page components
    services/        # Service-layer abstractions
    themes/          # MUI theme configuration
    types/           # TypeScript type definitions
    utils/           # Frontend utility functions
```

---

## 3. Adding a New Route

All routes follow the same pattern: import dependencies from `src.dependencies`,
get the database via a local `get_db` helper that wraps
`get_database_from_request`, and protect endpoints with `check_role`.

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from src.dependencies import get_current_user, check_role
from src.core.database import get_database_from_request

router = APIRouter(prefix="/my-feature", tags=["My Feature"])


async def get_db(request: Request):
    return await get_database_from_request(request)


@router.get("/items")
async def list_items(
    request: Request,
    db = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all items for the authenticated user."""
    items = await db.items.find({}).to_list(100)
    return items


@router.post("/items")
async def create_item(
    request: Request,
    item_data: dict,
    db = Depends(get_db),
    user: dict = Depends(check_role(["admin"])),
):
    """Create an item. Restricted to the admin system role."""
    item_data["id"] = str(uuid.uuid4())
    item_data["created_by"] = user["id"]
    item_data["created_at"] = datetime.utcnow()
    await db.items.insert_one(item_data)
    return item_data
```

Register the router in `main.py`:

```python
from src.my_feature.routes import router as my_feature_router

app.include_router(my_feature_router, prefix="/api/v1")
```

---

## 4. Database Access

BlackBar uses a single MongoDB database named `blackbar`. There are two ways to
access it.

### Direct import (for services, scripts, and startup logic)

```python
from src.database import db, cases, documents, users

# db is the AsyncIOMotorDatabase handle
# cases, documents, users, etc. are collection references
result = await cases.find_one({"id": case_id})
```

### Dependency injection (for route handlers)

```python
from fastapi import Request, Depends
from src.core.database import get_database_from_request

async def get_db(request: Request):
    return await get_database_from_request(request)

@router.get("/cases")
async def list_cases(
    request: Request,
    db = Depends(get_db),
):
    return await db.cases.find({}).to_list(100)
```

Each route module defines its own local `get_db` wrapper. This keeps the
database handle explicit in the function signature and makes it easy to
override in tests.

---

## 5. Frontend: Auth Context

The `useAuth` hook provides authentication state and actions throughout the
React application.

```typescript
import { useAuth } from '../contexts/AuthContext';

const MyComponent: React.FC = () => {
  const { user, roles, isAuthenticated, isLoading, login, logout } = useAuth();

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (!isAuthenticated) {
    return <LoginForm />;
  }

  return (
    <div>
      <p>Welcome, {user?.name}</p>
      <p>Role: {roles.join(', ')}</p>
      {roles.includes('admin') && <AdminPanel />}
      <button onClick={logout}>Sign out</button>
    </div>
  );
};
```

The `AuthProvider` wraps the application in `App.tsx`. On mount, it checks
`localStorage` for a stored token and calls `/api/v1/auth/me` to hydrate the
user object.

---

## 6. Frontend: API Calls

Use the shared `apiClient` from `../api/client`. It automatically attaches the
Bearer token from `localStorage` and handles 401 responses by redirecting to
the login page.

```typescript
import { apiClient } from '../api/client';

// GET
const response = await apiClient.get('/cases');
const cases = response.data;

// POST
const newCase = await apiClient.post('/cases', {
  title: 'New Case',
  priority: 'high',
});

// PUT
await apiClient.put(`/cases/${caseId}`, updatedData);

// DELETE
await apiClient.delete(`/cases/${caseId}`);
```

No tenant headers are required. The token is the only credential sent with each
request.

---

## 7. Role Checks

BlackBar has **two role taxonomies** — system-level user roles and per-case
case-team roles. See [`docs/standards/ROLES.md`](../standards/ROLES.md) for the
full breakdown. The short version:

System roles (stored on `user.role`):

| Role     | Description                              |
|----------|------------------------------------------|
| admin    | Full system access, user management      |
| analyst  | Case and document analysis, FOI staff    |
| user     | Standard access (assigned cases only)    |
| guest    | External collaborators (invited cases)   |

> Many existing route decorators still list a vestigial `"owner"` literal in
> their `check_role([...])` list. It is recognised by neither taxonomy and is
> silently ignored. Do not add new `"owner"` literals — a sweep to remove
> them from the existing decorators is welcome.

### Backend: dependency injection

Use `check_role` to restrict an endpoint to specific roles. It returns the
authenticated user dict on success or raises a 403 if the role does not match.

```python
from src.dependencies import check_role

@router.post("/admin-action")
async def admin_action(
    user: dict = Depends(check_role(["admin"])),
):
    # Only admin can reach this code
    return {"message": "Action performed", "by": user["id"]}
```

### Backend: authentication without role restriction

Use `get_current_user` when any authenticated user should have access.

```python
from src.dependencies import get_current_user

@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    return {"email": user["email"], "role": user["role"]}
```

---

## 8. Common Dependencies

| Dependency                          | Import                                                        | Purpose                                      |
|-------------------------------------|---------------------------------------------------------------|----------------------------------------------|
| `get_current_user`                  | `from src.dependencies import get_current_user`               | Returns authenticated user dict              |
| `check_role(["admin"])`             | `from src.dependencies import check_role`                     | Restricts access to listed system roles      |
| `get_database_from_request`         | `from src.core.database import get_database_from_request`     | Returns the `blackbar` database handle       |
| `db` / collection references        | `from src.database import db, cases, users`                   | Direct database and collection access        |

---

## 9. Logging

Use the standard `logging` module. Always include `correlation_id` when
available, and never log personally identifiable information (PII).

```python
import logging

logger = logging.getLogger(__name__)

# Good: includes correlation_id for request tracing
logger.info(
    "Case created",
    extra={
        "correlation_id": getattr(request.state, "correlation_id", None),
        "case_id": case_id,
        "user_id": user["id"],
    }
)

# Bad: logs PII
logger.warning("Failed login", extra={"email": email})        # Do not do this

# Good: logs user identifier without PII
logger.warning("Failed login", extra={"user_id": user_id})    # Do this instead
```

---

## 10. Error Handling

Use `HTTPException` for standard error responses. For structured errors that
include a correlation ID, return a `JSONResponse` directly.

```python
from fastapi import HTTPException
from starlette.responses import JSONResponse

# Simple error
raise HTTPException(status_code=404, detail="Case not found")

# Structured error with correlation ID
return JSONResponse(
    status_code=400,
    content={
        "error": {
            "code": "INVALID_STATUS_TRANSITION",
            "message": "Cannot move case from 'closed' to 'open'",
            "correlation_id": getattr(request.state, "correlation_id", None),
        }
    }
)
```

On the frontend, the `apiClient` response interceptor logs the correlation ID
from the `x-correlation-id` response header automatically when a request fails.

---

## 11. Checklist for New Features

- [ ] Route handler uses `get_current_user` or `check_role` for authentication
- [ ] Database access uses `get_database_from_request` via a local `get_db` dependency (routes) or `from src.database import db` (services)
- [ ] Role checks are implemented for any restricted operations
- [ ] Database indexes are created for new collections (see `src/core/database.py` `create_indexes`)
- [ ] Logging includes `correlation_id` where a request context is available
- [ ] No PII appears in log output
- [ ] Error responses use `HTTPException` or the structured `JSONResponse` format
- [ ] Frontend uses `apiClient` from `../api/client` for all API calls
- [ ] New routes are registered in `main.py` with the `/api/v1` prefix
- [ ] TypeScript types are defined in `frontend/src/types/` for new response shapes

---

## Reference

- Coding standards: [`docs/AGENTS.md`](../AGENTS.md)
- Roles (dual taxonomy + permission patterns): [`docs/standards/ROLES.md`](../standards/ROLES.md)
- API documentation: `http://localhost:8000/docs` (Swagger UI, available when backend is running)
- Existing route modules under `backend/src/` serve as working examples
