# PRD: Docker Release All-in-One
 
## Overview
 
Provide a single Docker image and `docker-compose.yml` that bundles the complete Data-Forge stack — frontend, backend, and optional PostgreSQL — so users can deploy the platform with a single `docker compose up` command. Publish versioned images to a container registry on each release.
 
## Problem Statement
 
The current Docker setup (`Dockerfile` + `docker-compose.yml`) builds and runs the application but has gaps for a production-ready release:
 
- No published Docker images — users must build from source.
- No PostgreSQL service in `docker-compose.yml` — users wanting PostgreSQL must configure it separately.
- No multi-architecture images (linux/amd64, linux/arm64).
- No image tagging strategy tied to release versions.
- The healthcheck is commented out.
- No documentation for common deployment scenarios (standalone, with PostgreSQL, with S3).
 
### Current State
 
| Concern | Status |
|---------|--------|
| Multi-stage Dockerfile | ✅ Frontend build + backend runtime |
| docker-compose.yml | ✅ Single service, local volumes |
| Published images | ❌ Must build from source |
| PostgreSQL service | ❌ Not included |
| Multi-arch builds | ❌ Only build platform |
| Healthcheck | ⚠️ Commented out |
| Image tagging | ❌ No strategy |
 
## Goals
 
| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | One-command deployment | `docker compose up` starts full stack with zero additional setup |
| G-2 | Published versioned images | Images available on GHCR/Docker Hub with `latest` and semver tags |
| G-3 | Multi-arch support | Images built for linux/amd64 and linux/arm64 |
| G-4 | Optional PostgreSQL sidecar | `docker-compose.yml` includes a PostgreSQL service with sensible defaults |
| G-5 | Production-ready defaults | Healthcheck enabled, resource limits set, restart policies configured |
 
## Non-Goals
 
- Kubernetes Helm chart (future)
- Managed database provisioning (users bring their own or use the included PostgreSQL)
- Automatic TLS/SSL termination (use a reverse proxy)
- Horizontal auto-scaling configuration
 
## User Stories
 
### US-1: Deploy with Docker Compose
 
> As a user, I want to run `docker compose up -d` and have a working Data-Forge instance.
 
**Acceptance Criteria:**
 
1. `docker-compose.yml` defines two profiles:
   - **default**: App only (SQLite, self-contained).
   - **postgres**: App + PostgreSQL service.
2. Running `docker compose up -d` starts the default profile with SQLite.
3. Running `docker compose --profile postgres up -d` starts the app with PostgreSQL.
4. Data persists across restarts via named volumes.
5. The app is accessible on `http://localhost:8000` after startup.
6. Healthcheck passes within 30 seconds of container start.
 
### US-2: Use Published Docker Image
 
> As a user, I want to pull a pre-built image instead of building from source.
 
**Acceptance Criteria:**
 
1. Images published to `ghcr.io/volturine/data-forge` (or configured registry).
2. Tags: `latest`, `v1.2.3`, `v1.2`, `v1`.
3. `docker-compose.yml` references the published image with a `build:` fallback.
4. Users can override the image tag via `.env`: `IMAGE_TAG=v1.2.3`.
 
### US-3: Deploy with PostgreSQL
 
> As a user, I want to use PostgreSQL for metadata storage alongside the Data-Forge app.
 
**Acceptance Criteria:**
 
1. PostgreSQL service uses `postgres:16-alpine` image.
2. Database, user, and password configurable via `.env`.
3. App `DATABASE_URL` automatically references the PostgreSQL service.
4. PostgreSQL data persists in a named volume.
5. App waits for PostgreSQL readiness before starting (healthcheck dependency).
6. `.env.example` includes commented PostgreSQL configuration block.
 
## Technical Design
 
### docker-compose.yml Structure
 
```yaml
services:
  app:
    image: ghcr.io/volturine/data-forge:${IMAGE_TAG:-latest}
    build: .
    ports:
      - "${PORT:-8000}:8000"
    environment:
      - DATABASE_URL=${DATABASE_URL:-sqlite:///data/app.db}
      - DATA_DIR=/data
    volumes:
      - app-data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: "${CPU_LIMIT:-4.0}"
          memory: "${MEMORY_LIMIT:-8g}"
 
  postgres:
    image: postgres:16-alpine
    profiles: ["postgres"]
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-dataforge}
      POSTGRES_USER: ${POSTGRES_USER:-dataforge}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    volumes:
      - pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-dataforge}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
 
volumes:
  app-data:
  pg-data:
```
 
### CI/CD Image Publishing
 
Add a GitHub Actions workflow (`.github/workflows/docker-publish.yml`):
 
1. Triggered on: push to `master` with version tags (`v*`), manual dispatch.
2. Build multi-arch images using `docker/build-push-action` with QEMU.
3. Push to GHCR with tags derived from git ref.
4. Cache layers across builds for speed.
 
### Dockerfile Improvements
 
- Uncomment and configure healthcheck.
- Add `LABEL` metadata (version, description, source URL).
- Ensure `curl` is available in final image for healthcheck.
- Pin base image digests for reproducibility.
 
### Environment File
 
Provide `docker.env.example` with all deployment-relevant variables:
 
```env
# Image
IMAGE_TAG=latest
 
# App
PORT=8000
DATA_DIR=/data
DEBUG=false
 
# Database (default: SQLite)
DATABASE_URL=sqlite:///data/app.db
 
# Uncomment for PostgreSQL (use with --profile postgres)
# DATABASE_URL=postgresql+psycopg://dataforge:changeme@postgres:5432/dataforge
# POSTGRES_DB=dataforge
# POSTGRES_USER=dataforge
# POSTGRES_PASSWORD=changeme
 
# Resources
CPU_LIMIT=4.0
MEMORY_LIMIT=8g
```
 
## Acceptance Criteria
 
- [ ] `docker compose up -d` starts the app with SQLite, accessible on port 8000
- [ ] `docker compose --profile postgres up -d` starts app + PostgreSQL, app uses PostgreSQL
- [ ] Healthcheck passes within 30 seconds
- [ ] Published multi-arch image pullable from GHCR
- [ ] Version tags (`v1.0.0`) produce correctly tagged images
- [ ] Data persists across `docker compose down && docker compose up`
- [ ] `docker.env.example` documents all configurable variables
- [ ] README updated with deployment instructions