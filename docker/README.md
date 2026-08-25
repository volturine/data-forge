# Docker model

Data-Forge has one Docker runtime model:

```text
Postgres + RustFS + API + Scheduler + Worker
```

The API container serves the backend API and built frontend. Scheduler and worker are separate Python role containers built from the same source tree.

See [Deployment](../docs/DEPLOYMENT.md) for production prerequisites, TLS,
health checks, upgrades, backup, restore, and secret rotation.

## Files

| File | Purpose |
| --- | --- |
| `compose.yaml` | Base runtime stack. |
| `compose.dev.yaml` | Development override with source mounts and Vite. |
| `env/prod.env` | Production image tags, ports, credentials, auth, and sizing. |
| `env/dev.env` | Local Docker development config. |
| `Dockerfile` | Builds app role images. |

## Development stack

```bash
just docker-dev
```

Stop it:

```bash
just docker-dev-down
```

Logs:

```bash
just docker-dev-logs
```

The dev stack uses the same host ports as `just dev` (API 8000, Vite 3000) and
the same engine network name is unique to its `-p dataforge-dev` project, so the
two dev modes are mutually exclusive by design: run either one, not both.

## Production compose

Use the base compose file directly with `docker/env/prod.env`:

```bash
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/compose.yaml pull
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/compose.yaml up -d
```

All four `DF_*_IMAGE` values must refer to the same Data-Forge release. The
worker starts the engine image dynamically, so pull it explicitly before startup:

```bash
docker pull "$(grep '^DF_ENGINE_IMAGE=' docker/env/prod.env | cut -d= -f2-)"
```

Set `DF_DOCKER_SOCKET_PATH` and `DF_DOCKER_GID` for the host Docker socket. This
socket is mounted only into the worker; Docker socket access is administrative
host access. Replace
the example passwords, internal token, encryption key, and object-store
credentials before starting the stack.

Inspect the deployment:

```bash
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/compose.yaml ps
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/compose.yaml logs -f
```

Stop the deployment while preserving volumes:

```bash
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/compose.yaml down
```

Do not pass `-v` for production unless permanent deletion of all three durable
volumes is intentional and verified.

## Maintainer local production smoke test

`just docker-prod` builds local `api` / `scheduler` / `worker` / `engine` images and starts
the same production compose file and env file, overriding the four
`DF_*_IMAGE` tags and binding the API to host port 8300 so the smoke stack
never collides with the dev stacks or the central deployment stacks:

```bash
just docker-prod
just docker-prod-logs
just docker-prod-down
```

Optional: set `DF_LOCAL_TAG` to control the local image tag (default `local`)
and `DF_SMOKE_API_PORT` to override the smoke host port (default `8300`).
Replace every `replace-with-...` value in `docker/env/prod.env` (or export
overrides) before a successful smoke start.

## Naming and port registry

Every fixed Docker resource has a unique name so prod, dev, tests, e2e, and the
central deployments workspace can coexist on one host:

| Consumer | Compose project | Engine network | Host ports |
| --- | --- | --- | --- |
| Source dev (`just dev`) / `docker-dev` | `dataforge-dev` (compose) | `dataforge-dev-engine-runtime` | 8000 API, 3000 Vite |
| Production smoke (`docker-prod`) | `dataforge-prod` | `dataforge-prod-engine-runtime` | 8300 |
| Central deployment prod | `dataforge-app` | `dataforge-app-engine-runtime` | 3300 |
| Central deployment dev / PR preview | `dataforge-app-dev` | `dataforge-app-dev-engine-runtime` | 3400 |
| Unit/integration tests | — | `dataforge-integration-engine-<uuid>` | random free ports |
| E2E suite | — | `dataforge-e2e-engine-<run-id>` | random free ports |

When adding a new fixed resource, pick the next free name/port and update this
table. See [Deployment](../docs/DEPLOYMENT.md) for the full standard.
