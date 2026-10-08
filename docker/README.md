# Docker model

Data-Forge has one Docker runtime model:

```text
Postgres + RustFS + API + Scheduler + Worker
```

The API container serves the backend API and built frontend. Scheduler and worker are separate Python role containers built from the same source tree.

See [Deployment](../docs/DEPLOYMENT.md) for production prerequisites, TLS,
health checks, upgrades, backup, restore, and secret rotation.

## Containerized tests

Each invocation of a public per-suite recipe (`just test-backend-unit`,
`just test-backend-integration`, `just test-worker`, `just test-scheduler`,
`just test-frontend`, or `just test-e2e`) launches a private Compose enclave
through `scripts/test_container.sh`. Every enclave has a seeded Linux runner
image, a named volume mounted at `/app` for the workspace, and a
`docker:29.7.2-dind` service with its own Docker daemon and socket. Each gets
its own Compose network and volumes. It does not mount the host Docker socket
or publish ports on the host. Test services are started inside that
invocation's enclave, and collected logs and diagnostics are copied to
`.test-artifacts/<run-id>` with the invoking user's local ownership, including
when a suite fails or the runner is OOM-killed.

`just test` orchestrates those public per-suite recipes sequentially on the
host. Each suite therefore runs in a new enclave and daemon, and its artifacts
have a separate run ID. CI's Python matrix and frontend job invoke the public
suite recipes independently and may run concurrently.

The host needs Docker and `just`. Its Docker daemon must allow the privileged
DinD service: Docker documents that privileged mode is needed for common
Docker-in-Docker setups and warns that privileged containers are not securely
sandboxed ([Docker run reference](https://docs.docker.com/reference/cli/docker/container/run/)).
The enclave gives each invocation a separate daemon lifecycle and socket, but
it is not a security boundary for malicious code. No test services run outside
the enclave. The host still shares its CPU and memory with test processes and
other workloads.

`TEST_MEMORY_MB` optionally sets one total memory budget per test recipe
invocation for its runner and DinD daemon. If unset, Python and Vitest
invocations use 75% of memory available to Docker; E2E uses 90%. In E2E, the
controller receives 512 MiB and at least 0.5 CPUs or 20% of the total CPU
budget, whichever is greater. The daemon receives the remaining budget and
runs all browser containers inside the enclave. `TEST_CPUS` optionally sets
one total CPU budget per invocation. Concurrent invocations each receive
their own caps, so their combined use can exceed host capacity. Limits cap
container resources but do not reserve host resources: the machine's CPU and
memory remain finite and shared with other workloads. These budgets do not
change service counts or test concurrency. Artifacts are uploaded by CI for
every suite, whether it succeeds or fails.

## Files

| File | Purpose |
| --- | --- |
| `compose.yaml` | Base runtime stack. |
| `compose.dev.yaml` | Development override with source mounts and Vite. |
| `compose.replicas.yaml` | Production override: N stateless API replicas behind an nginx ingress. |
| `ingress/nginx.conf` | Ingress config used by `compose.replicas.yaml`. |
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
