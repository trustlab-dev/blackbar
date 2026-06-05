# BlackBar Documentation Index

Quick map of the project's docs. Everything else is read-as-you-need.

---

## Repo root

- **[README.md](README.md)** — what BlackBar is, feature list, quick start
- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** — end-to-end installation and operations
- **[DOCKER_COMMANDS.md](DOCKER_COMMANDS.md)** — Docker Compose cheatsheet
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — dev setup, conventions, DCO sign-off
- **[SECURITY.md](SECURITY.md)** — vulnerability disclosure
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — Contributor Covenant 2.1
- **[CHANGELOG.md](CHANGELOG.md)** — release notes
- **[LICENSE](LICENSE)** — Apache License, Version 2.0

## Architecture (`docs/architecture/`)

- **[ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)** — system overview, single-tenant runtime, router decomposition
- **[SYSTEM_OVERVIEW_DIAGRAM.md](docs/architecture/SYSTEM_OVERVIEW_DIAGRAM.md)** — end-to-end component and process diagrams
- **[DATA_MODELS.md](docs/architecture/DATA_MODELS.md)** — Pydantic models and MongoDB collections
- **[DOCUMENT_PROCESSING.md](docs/architecture/DOCUMENT_PROCESSING.md)** — upload → OCR → conversion pipeline
- **[SECURITY_ARCHITECTURE.md](docs/architecture/SECURITY_ARCHITECTURE.md)** — JWT realms, AuthMiddleware, RBAC, the dual role taxonomy
- **[AGENTIC_REDACTION_PIPELINE.md](docs/architecture/AGENTIC_REDACTION_PIPELINE.md)** — forward-looking design proposal (NOT implemented)

## API (`docs/api/`)

- **[ENDPOINTS.md](docs/api/ENDPOINTS.md)** — REST API reference
- **[AI_PROMPT_SYSTEM.md](docs/api/AI_PROMPT_SYSTEM.md)** — LLM prompt construction details

## Guides (`docs/guides/`)

- **[DEVELOPER_QUICK_START.md](docs/guides/DEVELOPER_QUICK_START.md)** — local dev setup for contributors
- **[SUGGESTION_OVERLAY_GUIDE.md](docs/guides/SUGGESTION_OVERLAY_GUIDE.md)** — user-facing AI-suggestion overlay guide

## Standards (`docs/standards/`, `docs/`)

- **[docs/standards/ROLES.md](docs/standards/ROLES.md)** — canonical 4-tier system / 7-tier case-team taxonomy
- **[docs/STYLEGUIDE.md](docs/STYLEGUIDE.md)** — UI/UX design guidelines
- **[docs/AGENTS.md](docs/AGENTS.md)** — repo-level rules for AI coding agents

## Testing (`docs/testing/`)

- **[END-TO-END.md](docs/testing/END-TO-END.md)** — end-to-end test plan and conventions

---

## Quick navigation

| I want to… | Go to |
|---|---|
| Set up local dev | [docs/guides/DEVELOPER_QUICK_START.md](docs/guides/DEVELOPER_QUICK_START.md) |
| Deploy BlackBar | [SETUP_GUIDE.md](SETUP_GUIDE.md) |
| Understand the architecture | [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) |
| Understand auth + security | [docs/architecture/SECURITY_ARCHITECTURE.md](docs/architecture/SECURITY_ARCHITECTURE.md) |
| Contribute code | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Report a vulnerability | [SECURITY.md](SECURITY.md) |
| Use the API | [docs/api/ENDPOINTS.md](docs/api/ENDPOINTS.md) |
