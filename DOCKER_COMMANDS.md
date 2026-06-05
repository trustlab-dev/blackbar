# Docker Compose Commands Reference

All commands use the modern Compose v2 invocation (`docker compose`, no hyphen). The legacy `docker-compose` form may still work if you have it installed, but is not the supported invocation.

BlackBar's compose stack defines three services — `backend`, `frontend`, `mongodb` — on a single `blackbar-network`, with one named volume (`mongodb_data`). The production overlay (`docker-compose.prod.yml`) adds a `grafana` service and replaces the named volumes with bind mounts under `${BLACKBAR_DATA_DIR:-./data}`.

## Setup & Start

```bash
# Run full setup (recommended first time — generates secrets, creates admin, seeds templates)
bash setup.sh

# Or, after secrets are already in .env, start the stack manually
docker compose up -d
```

## Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f mongodb

# Last 100 lines
docker compose logs --tail=100 backend
```

## Managing Services

```bash
# Start / stop / restart everything
docker compose up -d
docker compose down
docker compose restart

# Single service
docker compose restart backend
docker compose stop backend
docker compose start backend
```

## Building

```bash
# Build everything
docker compose build

# Build a single service
docker compose build backend

# Build without cache (force fresh layers)
docker compose build --no-cache backend

# Build and start in one shot
docker compose up -d --build
```

## Viewing Status

```bash
# List running containers in the project
docker compose ps

# Live resource usage (CPU / memory / I/O)
docker compose stats

# Effective merged compose configuration
docker compose config
```

## Executing Commands

```bash
# Run an arbitrary command in the backend container
docker compose exec backend python scripts/<some_script>.py

# Interactive shells
docker compose exec backend bash
docker compose exec frontend sh

# MongoDB shell (authenticated automatically inside the network)
docker compose exec mongodb mongosh blackbar
```

## Database Operations

```bash
# Open mongosh against the blackbar database
docker compose exec mongodb mongosh blackbar

# Quick query
docker compose exec mongodb mongosh blackbar --eval 'db.users.find().pretty()'

# Backup the blackbar database to the container's /data/backup
docker compose exec mongodb mongodump --db blackbar --out /data/backup

# Copy the backup out to the host
docker cp "$(docker compose ps -q mongodb):/data/backup" ./backup

# Restore from /data/backup/blackbar
docker compose exec mongodb mongorestore --db blackbar /data/backup/blackbar
```

## Cleanup

```bash
# Stop and remove containers (volumes preserved)
docker compose down

# Stop, remove containers AND the mongodb_data volume (DESTROYS DATA)
docker compose down -v

# System-wide prune of dangling images, networks, build cache
docker system prune -a

# Remove the named MongoDB volume explicitly (after `down`)
docker volume rm blackbar_mongodb_data
```

## Development Workflow

```bash
# Tail backend logs while iterating
docker compose logs -f backend

# After backend code changes (src is bind-mounted; uvicorn reloads automatically
# in development — usually no rebuild is needed for pure src/ edits)
docker compose restart backend

# After backend dependency changes (pyproject.toml / requirements.txt)
docker compose build backend
docker compose up -d backend

# Frontend hot reload is provided by Vite via the bind-mounted src/.
# If you change package.json or vite.config.ts:
docker compose build frontend
docker compose up -d frontend

# Quick service-only restart, no rebuild
docker compose restart backend frontend
```

## Troubleshooting

```bash
# Service status overview
docker compose ps

# Targeted log dive
docker compose logs backend | tail -50

# Identify host-port conflicts (Linux / macOS)
lsof -i :3000
lsof -i :8000
lsof -i :27017

# Force recreate containers (picks up changes to env / config)
docker compose up -d --force-recreate

# Full reset
docker compose down -v
bash setup.sh
```

## Production Deployment

```bash
# Bring up the production overlay (merges docker-compose.yml + docker-compose.prod.yml)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Tail prod logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=100

# Pull pre-built images, if a registry is in use
docker compose pull
```

> The production overlay parameterises persistent paths via `BLACKBAR_DATA_DIR` (defaults to `./data`). Bind-mounted directories must exist and be writable by the container UID before `up`. See `SETUP_GUIDE.md` for the full production checklist.

## Environment Variables

```bash
# Use a non-default env file
docker compose --env-file .env.production up -d

# One-off override at the shell
JWT_SECRET=different-secret docker compose up -d
```

## Networking

```bash
# List Docker networks
docker network ls

# Inspect the BlackBar network
docker network inspect blackbar-network
```

## Volumes

```bash
# List volumes
docker volume ls

# Inspect the MongoDB volume
docker volume inspect blackbar_mongodb_data

# Backup the named volume to a tarball on the host
docker run --rm -v blackbar_mongodb_data:/data -v "$(pwd)":/backup alpine \
    tar czf /backup/mongodb-backup.tar.gz /data

# Restore (mind the path — this overwrites the volume contents)
docker run --rm -v blackbar_mongodb_data:/data -v "$(pwd)":/backup alpine \
    tar xzf /backup/mongodb-backup.tar.gz -C /
```

## Quick Reference

| Task | Command |
|------|---------|
| Start all | `docker compose up -d` |
| Stop all | `docker compose down` |
| View logs | `docker compose logs -f` |
| Restart service | `docker compose restart backend` |
| Rebuild service | `docker compose build backend` |
| Shell access | `docker compose exec backend bash` |
| MongoDB shell | `docker compose exec mongodb mongosh blackbar` |
| Full reset (destroys data) | `docker compose down -v` |

## Common Workflows

### After backend code changes
```bash
# src/ is bind-mounted; uvicorn reload usually picks the change up.
# If not, restart:
docker compose restart backend
```

### After backend dependency changes (pyproject.toml / requirements.txt)
```bash
docker compose build backend
docker compose up -d backend
```

### After frontend code changes
```bash
# Vite HMR via the bind-mounted src/. If hot reload misbehaves:
docker compose restart frontend
```

### After .env changes
```bash
docker compose down
docker compose up -d
```

### Fresh start (DESTROYS DATA)
```bash
docker compose down -v
bash setup.sh
```

### Quick health check
```bash
docker compose ps
curl http://localhost:8000/health   # backend health endpoint
curl -I http://localhost:3000/       # frontend (Nginx serves the SPA)
```
