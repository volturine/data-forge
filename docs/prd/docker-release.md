# PRD: Docker Release

## Overview

Provide a production-grade Docker release for Data-Forge built around one production compose file, one production env file, and published fixed-role images. Customers should install the product without building from source. Maintainers should keep using the same production compose topology for local smoke tests, with only image tags overridden to local builds.

The release artifacts are:

- `docker/docker-compose.yml`
- `docker/env/prod.env`
- published images in GitHub Container Registry

The runtime topology is:

- `postgres`
- `api`
- `scheduler`
- `worker`

## Problem Statement

The original Docker direction mixed several concerns:

- single-container supervised runtime versus split runtime roles
- customer-facing install files versus maintainer-local smoke-test files
- source-build workflows versus published-image workflows

That created product confusion.

For this release, Docker should be opinionated and simple:

1. There is exactly one production compose file.
2. There is exactly one production env file.
3. Customers install from published images, not from source.
4. GitHub Container Registry is used only for real production release artifacts.
5. Maintainer-local smoke tests may override image names, but must keep the same production compose topology.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Single production compose | `docker/docker-compose.yml` is the only production compose file used by both customers and maintainers |
| G-2 | Single production env | `docker/env/prod.env` is the only production env file |
| G-3 | No source build for customers | Customer install is `docker compose pull && docker compose up -d` |
| G-4 | Fixed-role runtime release | Published images exist for `api`, `scheduler`, and `worker` |
| G-5 | Release-grade security defaults | Production env template requires users to replace secrets and admin credentials |
| G-6 | Multi-arch publish | Release images are published for `linux/amd64` and `linux/arm64` |

## Non-Goals

- Kubernetes manifests or Helm charts
- separate production compose variants
- separate production env variants
- GHCR usage for local-only test images
- a single all-in-one production container

## User Stories

### US-1: Customer Installs Without Source

> As a customer, I want to deploy Data-Forge without cloning the repository or building images myself.

**Acceptance Criteria:**

1. Customer copies `docker/docker-compose.yml` and `docker/env/prod.env`.
2. Customer renames `docker/env/prod.env` to `.env` or passes it as the compose env file.
3. Customer edits only env values such as passwords, secrets, and image tags.
4. Customer runs:

   ```bash
   docker compose pull
   docker compose up -d
   ```

5. The app becomes reachable on port `8000`.
6. No customer step requires `docker build`, `uv`, `bun`, or a source checkout.

### US-2: Maintainer Smokes Local Production Topology

> As a maintainer, I want to test the real production topology locally before release.

**Acceptance Criteria:**

1. `just docker-prod` builds local role images.
2. `just docker-prod` still runs `docker/docker-compose.yml`.
3. `just docker-prod` still reads `docker/env/prod.env`.
4. `just docker-prod` overrides only image names/tags at runtime to point to locally built images.
5. No extra production compose file or production env file is introduced for local smoke testing.

### US-3: Publish Production Images

> As a maintainer, I want GitHub releases to publish the production Docker artifacts automatically.

**Acceptance Criteria:**

1. Tag push `vX.Y.Z` publishes:
   - `ghcr.io/volturine/data-forge-api:X.Y.Z`
   - `ghcr.io/volturine/data-forge-scheduler:X.Y.Z`
   - `ghcr.io/volturine/data-forge-worker:X.Y.Z`
2. Images are multi-arch.
3. GHCR is used only for production release artifacts.
4. Local maintainer smoke tests do not require publishing temporary images to GHCR.

## Technical Design

### Runtime Shape

The Docker production topology is fixed-role, not supervised single-container:

```text
Browser
  |
  v
api
  |
  v
Postgres
  ^
  |
scheduler
worker
```

Notes:

- `api` serves HTTP and websockets.
- `scheduler` claims due schedules and enqueues jobs.
- `worker` owns build execution and dynamic worker subprocesses.
- `postgres` is required for the supported Docker production path.

### Compose Contract

`docker/docker-compose.yml` is the only production compose file.

Requirements:

1. It must reference only image names, never `build:`.
2. It must define the four services above.
3. It must be suitable for both customer installs and maintainer-local smoke tests.
4. Maintainer-local smoke tests may override image tags through shell env, but may not swap to another compose file.

### Env Contract

`docker/env/prod.env` is the only production env file.

Requirements:

1. It must contain published-image defaults.
2. It must be customer-facing.
3. It must use placeholder secrets that force explicit replacement.
4. It must document the fixed-role image names:
   - `DF_API_IMAGE`
   - `DF_SCHEDULER_IMAGE`
   - `DF_WORKER_IMAGE`

### Dockerfile Contract

`docker/Dockerfile` builds three final targets from one codebase:

- `api`
- `scheduler`
- `worker`

Requirements:

1. Shared layers should be reused across the three targets.
2. Base/toolchain versions should be pinned.
3. OCI labels should be present.
4. Healthchecks should remain enabled for the API image.

### Registry Publishing

GitHub Actions publishes fixed-role images to GHCR on production release tags.

Rules:

1. Publish only on release tags or explicit release workflow triggers.
2. Do not publish local smoke-test images.
3. Use immutable version tags.
4. Support multi-arch builds.

## Environment Example

`docker/env/prod.env` should look like this shape:

```env
DF_API_IMAGE=ghcr.io/volturine/data-forge-api:1.0.0
DF_SCHEDULER_IMAGE=ghcr.io/volturine/data-forge-scheduler:1.0.0
DF_WORKER_IMAGE=ghcr.io/volturine/data-forge-worker:1.0.0

DF_POSTGRES_PASSWORD=replace-with-strong-password
DF_DATABASE_URL=postgresql+psycopg://dataforge:replace-with-strong-password@postgres:5432/dataforge

DF_AUTH_REQUIRED=true
DF_DEFAULT_USER_PASSWORD=replace-with-strong-password
DF_SETTINGS_ENCRYPTION_KEY=replace-with-long-random-secret
```

## Acceptance Criteria

- [ ] `docker/docker-compose.yml` is the only production compose file in the repository
- [ ] `docker/env/prod.env` is the only production env file in the repository
- [ ] Customer install requires only `docker compose pull` and `docker compose up -d`
- [ ] Customer install does not require source build
- [ ] `just docker-prod` uses the same production compose file and same production env file
- [ ] `just docker-prod` overrides only image tags to local builds
- [ ] Production runtime is split into `api`, `scheduler`, and `worker`
- [ ] GHCR publishes only production release images
- [ ] Published images are multi-arch
- [ ] Production env template uses placeholder secrets and credentials that must be replaced
