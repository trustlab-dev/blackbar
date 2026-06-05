# Blackbar Coding Standards (Compact, for Coding Agent)

These rules apply to all changes, including those made by automated agents.

---

## 1. Mandatory Workflow (No Freehanding)

For every task:

1. **Read context**
   - Read relevant routes, services, repositories, components, schemas, tests, and docs.
   - Read and obey `STYLEGUIDE.md`
   - read all architecture documentation, including overall architecture, data_models, etc
   - read all standards guides

2. **Reuse before creating**
   - Search for existing endpoints, services, components, hooks, and utilities.
   - Extend or refactor instead of duplicating.
   - Only create new endpoints/services/components if reuse is clearly not appropriate.

3. **Plan before coding**
   - Write a short plan:
     - Files to change
     - New or modified functions / endpoints / components
     - Any schema or contract changes
     - Tests you will add or update
     - Docs and diagrams you will update
   - Then implement the plan.

4. **Align with existing patterns**
   - Keep folder structure, naming, error handling, and patterns consistent.
   - Do not introduce new architectural patterns without clear reason.

5. **Tests after every change (required)**
   - Add or update tests for every behavioral change.
   - Run the relevant test suites after changes (backend + frontend where applicable).
   - No change is considered complete without tests being run.

6. **Update documentation and diagrams**
   - Document new/updated test cases inline (docstrings, README in the
     relevant module's `tests/` folder) so contributors can find and run them.
   - Update relevant docs in `docs/` (API docs, feature docs, etc.) to match behavior.
   - Update architecture diagrams (Mermaid files, e.g. `docs/architecture/*.md` or `*.mmd`) if flows, boundaries, or dependencies change.

7. **Self-review and summary**
   - Check for:
     - Duplicate logic
     - Inconsistent naming
     - Schema drift between frontend and backend
     - Security or privacy issues
   - Output a concise summary:
     - What changed
     - Why it changed
     - Tests added/updated and their results
     - Docs/diagrams updated

8. ** Git Commit **
- Commit changes once complete to git, with a descriptive comment.

---

## 2. Standards & Patterns

### Required Reading

Before implementing backend changes, review these standards:

- **[Roles](standards/ROLES.md)** - Dual role taxonomy (user roles vs case-team roles), permission-check patterns, and naming conventions
- **[Style Guide](STYLEGUIDE.md)** - UI/UX and frontend patterns
- **[Known Issues](KNOWN_ISSUES.md)** - Deferred audit findings; check before re-reporting

### Key Patterns

**Database Access** (Backend):

BlackBar is single-tenant. Routes obtain a database handle via the
`get_database_from_request` helper in `src/core/database.py`, wrapped in
a local `get_db` dependency:

```python
from fastapi import APIRouter, Depends, Request
from ..core.database import get_database_from_request

async def get_db(request: Request):
    return await get_database_from_request(request)

@router.get("/resource")
async def endpoint(request: Request, db = Depends(get_db)):
    resource = await db.resources.find_one({"id": id})
```

See `backend/src/cases/routes.py` for a canonical example.

---

## 3. Architecture Rules

### Backend (Python / FastAPI)

Flow: **routes → services → repositories → DB**

- Routes:
  - Handle HTTP, auth, and serialization only.
  - Never access the DB directly - use the `get_db` dependency.
- Services:
  - Contain business logic.
- Repositories:
  - Contain all DB access.

### Frontend (React / TypeScript)

Flow: **components → hooks → api**

- Components:
  - Presentational and simple orchestration.
  - No direct `fetch` calls.
- Hooks:
  - Contain derived state and view logic.
- API modules:
  - Handle HTTP, endpoints, and error mapping.

---

## 4. API and Schema Rules

- All JSON fields use `snake_case`.
- All URLs use kebab-case, versioned under `/api/v1/` (for example `/api/v1/documents`).
- Standard success response:
  ```json
  { "data": { }, "correlation_id": "<uuid>" }
- Standard error response:
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "details": {},
    "correlation_id": "<uuid>"
  }
}
Frontend and backend schemas must match exactly.

Changing schemas requires:

Backend schema update

Frontend types/hooks/components update

Tests update

Documentation and diagrams update

## 5. Security and Privacy

Never log passwords, tokens, emails, or PII.

Always use existing hashing and verification utilities for passwords.

Validate all inputs (Pydantic on backend, types/Zod on frontend if used).

Do not invent crypto or token logic without a documented design decision.

Prefer the most secure pattern already present in the codebase.

5. Frontend Standards (React + MUI)

Functional components only, using hooks.

All styling uses MUI sx.

Icons must come from @mui/icons-material, neutral color and 18–22px size.

No style={} inline CSS.

Data fetching is done only via src/api/ modules, not directly inside components.

6. Code Style
TypeScript

strict: true

Prefer const

Avoid any unless explicitly justified

Use arrow functions and destructuring

Python

PEP 8 compliant

Type hints everywhere

Use async/await for I/O

Use docstrings for public functions

7. Project Structure (High Level)
Frontend
src/
  features/
    documents/
      components/
      hooks/
      api/
    cases/
  components/
  api/
  utils/
  types/

Backend
src/
  documents/
    routes.py
    service.py
    repository.py
    models.py
  cases/
  packs/
  auth/
  utils/
  core/
    db.py
    config.py
    exceptions.py

** Perform security evaluation after each major piece of work and report on and propose remediation of security issues **


8. Git and Documentation

Use Conventional Commits (for example: feat:, fix:, refactor:, test:).

Keep README.md per major module up to date.

Use ADRs (Architecture Decision Records) for major decisions.

Prefer self-documenting code; comment only non-obvious logic.

** UPDATE RELEVANT DOCUMENTATION, ARCHITECTURE, MODELS, etc with changes **

---

# ❌ Violations Checklist (Agent Must Run Before Submitting)

```md
# Blackbar Coding Agent Violations Checklist

Before submitting code, confirm **all** of the following.  
If any item is false, stop and fix it.

## A. Workflow

- [ ] I read all relevant routes, services, repositories, components, schemas, tests, and docs.
- [ ] I followed `STYLEGUIDE.md` and `standards/ROLES.md`.
- [ ] I produced a clear plan before editing.
- [ ] I reused existing endpoints/services/components where possible instead of duplicating.
- [ ] I did not freehand or guess about unseen code.

## B. Architecture

- [ ] Backend: routes only call services; services call repositories; repositories call the DB.
- [ ] Frontend: components use hooks and api modules; components do not call `fetch` directly.
- [ ] I did not introduce new architectural patterns or folder structures without necessity.

## C. API & Schema

- [ ] All request and response JSON uses `snake_case`.
- [ ] All routes are versioned under `/api/v1/` and use kebab-case paths.
- [ ] Success and error responses follow the standard envelopes.
- [ ] Frontend and backend schemas are fully aligned.
- [ ] Any schema changes are reflected in:
  - [ ] Backend schemas/models
  - [ ] Frontend types/hooks/components
  - [ ] Tests
  - [ ] Documentation and diagrams

## D. Security & Privacy

- [ ] I did not log passwords, tokens, emails, or PII.
- [ ] I used existing password hashing/verification and token utilities.
- [ ] All inputs are validated.
- [ ] I did not invent new crypto or insecure patterns.

## E. Frontend (React + MUI)

- [ ] All styling uses MUI `sx`; no inline `style={}`.
- [ ] All icons come from `@mui/icons-material` and follow the style guide.
- [ ] Components do not call `fetch`; all HTTP calls go through `src/api/`.
- [ ] I did not use emoji or decorative icons.

## F. Testing (Must Be Done After Every Change)

- [ ] I added or updated tests for every behavioral change.
- [ ] I ran the relevant test suites (backend and/or frontend).
- [ ] All tests are passing.
- [ ] New/updated test cases are documented inline (docstring or module README)
      with the command needed to run them and the expected outcome.

## G. Documentation & Architecture Diagrams

- [ ] I updated relevant docs in `docs/` to reflect the new or changed behavior.
- [ ] I updated architecture Mermaid diagrams if flows, dependencies, or boundaries changed.
- [ ] I ensured diagrams and docs are consistent with the new code.

## H. Final Self-Review

- [ ] There is no duplicate logic that could reasonably be shared.
- [ ] Naming is consistent with existing code and conventions.
- [ ] There is no schema drift or hidden breaking change.
- [ ] The summary of changes clearly states:
  - What changed
  - Why it changed
  - What tests were run and their results
  - What docs/diagrams were updated