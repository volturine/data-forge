# Environment Variables

This project uses environment variables for two layers:

1. **Backend runtime** — loaded by `packages/backend/backend_core/config.py` from process env and the git-ignored `.env` at the repository root (path overridable with `ENV_FILE`)
2. **Frontend dev server (Vite)** — read from the process environment; `just dev` sources `docker/env/dev.env` so local dev variables come from the same file

There is no separate `packages/frontend/.env` file. All local dev configuration — including Vite
dev-server settings (`FRONTEND_PORT`, `BACKEND_HOST`) — lives in `docker/env/dev.env`.

## Deployment topologies

Understanding the two topologies helps you know which variables matter and
which are irrelevant for your context.

For end-to-end production setup, TLS, health checks, backup, restore, and
upgrades, see [Deployment](DEPLOYMENT.md).

### Production — single port

```
Browser  ──►  FastAPI (PORT 8000)
                  │
                  ├── /api/*     →  API handlers
                  └── /*         →  Serves packages/frontend/build static files
```

- `PROD_MODE_ENABLED=true` tells FastAPI to serve static files from
  `packages/frontend/build/`. Build the frontend first: `cd packages/frontend && bun run build`.
- Browser and API share the **same origin**, so cross-origin CORS is not needed
  for regular browser traffic. `CORS_ORIGINS` only needs a value when you have
  out-of-band clients (native apps, separate domains).
- The frontend Vite dev server is **not running**. `FRONTEND_PORT`,
  `BACKEND_HOST`, and `BACKEND_PORT` have no effect.
- `AUTH_FRONTEND_URL` should be the same URL as the backend (e.g.
  `http://your-server:8000`).

**Templates for this topology:**

- Docker: use `docker/compose.yaml` with `docker/env/prod.env`.
- Bare-metal (`just prod`): edit `docker/env/prod.env`

### Development — local runtime

```
Browser  ──►  Vite dev server (FRONTEND_PORT 3000)
                   │
                   └── /api/* proxy ──►  FastAPI (BACKEND_PORT 8000)

Repo-level local runtime:
  - backend/main.py API process
  - backend/runtime_coordinator.py fenced coordinator process
  - scheduler/main.py scheduler process
  - worker/main.py Docker-owning worker manager
  - dynamically assigned isolated compute containers
```

- `PROD_MODE_ENABLED=false` (default) — FastAPI does not serve static files; the
  Vite dev server handles all browser requests and proxies `/api` to FastAPI.
- `just dev` starts the four application roles from the repo root. The
  worker manager then assigns compute containers on demand.
- Because the browser origin (`:3000`) differs from the API origin (`:8000`),
  FastAPI's `CORS_ORIGINS` **must** include the dev-server origin.
- `FRONTEND_PORT`, `BACKEND_HOST`, and `BACKEND_PORT` wire the Vite
  proxy to the correct backend address. WebSocket connections go through the
  Vite proxy — no backend host/port is exposed to browser code.
- `AUTH_FRONTEND_URL` should be the Vite dev-server URL (e.g.
  `http://localhost:5173` or `http://localhost:3000`).

**Templates for this topology:**

- Edit `docker/env/dev.env` (covers both backend and Vite dev-server settings)

---

## What to configure first

If you only want the high-value knobs, start with these:

- `DATA_DIR` — where app data, uploads, exports, and logs live
- `PORT` — backend port
- `CORS_ORIGINS` — allowed browser origins (only needed in dev or multi-origin setups)
- `AUTH_REQUIRED` — turn login on/off
- `SETTINGS_ENCRYPTION_KEY` — strongly recommended when auth is enabled
- `COMPUTE_WORKERS` — the active compute capacity for the current single worker-manager topology
- `COMPUTE_WARM_WORKERS` — additional ready workers reserved before assignment; they are the same worker type, not a second execution pool
- `POLARS_CORES_AVAILABLE`, `POLARS_MAX_MEMORY_MB` — per-compute-worker resource limits
- **Dev-only:** `BACKEND_HOST`, `BACKEND_PORT`, `FRONTEND_PORT` — Vite proxy wiring (Bun/Vite only, not exposed to browser)

## How configuration is loaded

### Backend

- `Settings()` reads process environment first, then an env file.
- The default env file is the git-ignored `.env` at the repository root. It is the one place for local secrets and overrides (backend settings, auth keys, e.g. `E2E_OPENROUTER_API_KEY`). A legacy `packages/backend/.env` is no longer read — move any such file to the root.
- Process environment values win over `.env`. `ENV_FILE` chooses a different env file path; set it to an empty value only if you want to rely on process env alone. Application containers set `ENV_FILE` to empty so they only ever use compose-provided values.
- `DATABASE_URL` is the backend database URL and must be a full PostgreSQL connection string.
- Some values such as SMTP and provider defaults are **seeded into the database once**. After the UI saves a value, the database value wins until it is cleared.

### Frontend dev server

- `just dev` sources `docker/env/dev.env` into the shell before starting Vite, so `FRONTEND_PORT` and `BACKEND_HOST` are inherited from the same file as the backend.
- No `packages/frontend/.env` file is needed or used.
- No variables are exposed to browser code — the `VITE_` prefix convention is not used.

## Setup examples

### Production — Docker / compose

```bash
# From the repository root, after editing docker/env/prod.env
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml pull
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml up -d
```

`docker/compose.yaml` is the single production compose file and
`docker/env/prod.env` is its production env template. GHCR-published images are
for production releases only.
`docker/compose.yaml` uses published fixed-role images and does not build application images during `up`.
The compose topology uses separate `api`, `runtime`, `scheduler`, and `worker` containers from the same codebase release.
The checked-in Docker topology still includes `postgres` because the supported Docker runtime path is Postgres-backed. `DF_DATABASE_URL` in the Docker env files points at that service.

The checked-in Docker production env defaults to `DF_WORKERS=1`, the API
process count within the API container. API processes serve HTTP,
WebSocket/SSE, and durable enqueue-and-wait paths; they do not own compute
dispatch, Telegram polling, or compute-worker lifecycle. One active fenced `runtime`
coordinator owns gRPC/dispatch, durable chat processing, Telegram polling, and
independent durable email/Telegram delivery lanes. The single `worker` service
owns Docker and isolated compute containers. In this topology,
`COMPUTE_WORKERS` bounds concurrent jobs/assigned workers and
`COMPUTE_WARM_WORKERS` bounds ready-but-unassigned reserve; an assigned worker
is bound to one exact analysis or datasource RID. Identical full commands share
durable results and distinct commands for one RID are serialized. API caches,
projections, and waiters are process-local and disposable; PostgreSQL remains
authoritative for durable work. Work remains durable while waiting. These are
not cluster-wide leases across multiple manager containers; horizontal
worker-service scaling is unsupported until
distributed identity ownership and capacity grants are implemented and
load-tested in the
[capacity-first runtime plan](prd/active/elastic-runtime-scale-out.md).
Active and warm starts are bounded by their configured budgets; there is no
host-CPU-derived startup cap.

Synchronous SQLAlchemy work runs as a complete, short unit that opens and closes
its own session inside bounded threads. Async compute waits carry no unused
session or database dependency. Blocking Docker, storage/catalog, and SMTP work
also stays off async event loops; native async network I/O and waits stay on their
owning loop. Parsing and Polars-heavy execution happen in compute containers.
API/coordinator PostgreSQL receivers use dedicated `psycopg.AsyncConnection`
listeners and continuous `notifies()` generators with explicit durable recovery
callbacks. This is receive-only; publication remains synchronous DB/thread
work. Recovery targets active projections, reads build/lock projections in
batches of at most 128, and wakes durable chat/settings consumers.
Worker/scheduler health probes require PID1 registration and fresh progress on
every dispatch lane; the API health endpoint
checks API dependencies. Durable external delivery metadata is stored in the
outbox, and network delivery runs outside database transactions. Private storage
cleanup reuses that outbox and an independent worker I/O lane; published snapshot
retention uses the existing policy, with no new service or public tunables.

### Production — bare-metal (`just prod`)

```bash
# Provision PostgreSQL and S3-compatible storage, then edit
# docker/env/prod.env with endpoints, secrets, and resource limits.
just prod
```

`just prod` generates protocol bindings, builds the frontend, and runs the API,
runtime coordinator, scheduler, and worker as separate processes. The checked-in
`docker/env/prod.env` defaults to `WORKERS=1`. This controls API processes in
the API container; it does not add runtime coordinator or worker-manager
capacity. For the current supported topology and the future scale-out target,
see [Deployment](DEPLOYMENT.md) and [Capacity-First Runtime Optimization](prd/active/elastic-runtime-scale-out.md).

### Local development

```bash
# Edit docker/env/dev.env with your settings — covers both backend and Vite dev-server
just dev
```

## Backend variables

### Application and files

| Variable                               | Default                                                                                   | Notes                                                                                                                                                                                                                                                            |
| -------------------------------------- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ENV_FILE`                             | `<repo root>/.env`                                                                        | Path to the backend env file. Default is the git-ignored root `.env`; set to empty on all application containers.                                                                                                                                                |
| `APP_NAME`                             | `Data-Forge Analysis Platform`                                                            | Application name for UI/logging metadata.                                                                                                                                                                                                                        |
| `APP_VERSION`                          | `1.0.0`                                                                                   | Application version string.                                                                                                                                                                                                                                      |
| `DEBUG`                                | `false`                                                                                   | Enables verbose/debug behavior.                                                                                                                                                                                                                                  |
| `PROD_MODE_ENABLED`                    | `false`                                                                                   | Must be `true` in production. Enables static-file serving from `packages/frontend/build/`. In dev, leave `false` so FastAPI does not try to serve the frontend.                                                                                                  |
| `PORT`                                 | `8000`                                                                                    | Backend HTTP port.                                                                                                                                                                                                                                               |
| `DATA_DIR`                             | system temp dir + `/data-forge`                                                           | Writable scratch directory for the process. No authoritative state lives there; product data is in object storage and PostgreSQL, so API replicas need not share it.                                                                                               |
| `DATABASE_URL`                         | none                                                                                      | Full backend PostgreSQL database URL. Required.                                                                                                                                                                                                                  |
| `DF_API_IMAGE`                         | `ghcr.io/volturine/data-forge-api:1.0.0`                                                  | Docker compose production image tag for the `api` service. Pull this image before `docker compose up`.                                                                                                                                                           |
| `DF_SCHEDULER_IMAGE`                   | `ghcr.io/volturine/data-forge-scheduler:1.0.0`                                            | Docker compose production image tag for the `scheduler` service.                                                                                                                                                                                                 |
| `DF_WORKER_IMAGE`                      | `ghcr.io/volturine/data-forge-worker:1.0.0`                                               | Docker compose production image tag for the `worker` service.                                                                                                                                                                                                    |
| `DF_COMPUTE_WORKER_IMAGE`              | `ghcr.io/volturine/data-forge-compute-worker:1.0.0`                                      | Image used for dynamically-created compute-worker containers. A `repository@sha256:<digest>` reference keeps every launch byte-identical; tags remain supported for custom images.                                                                                |
| `DF_COMPUTE_WORKER_DOCKER_HOST`         | `unix:///var/run/docker.sock`                                                             | Docker API endpoint used only by the worker manager service.                                                                                                                                                                                                      |
| `DF_COMPUTE_WORKER_DOCKER_NETWORK`      | `dataforge-prod-compute-worker-runtime`                                                   | Dedicated network joining the worker manager, RustFS, and compute-worker containers.                                                                                                                                                                               |
| `DF_COMPUTE_WORKER_DOCKER_HOSTS`        | empty                                                                                     | Optional JSON list of Docker daemons for compute-worker placement. Empty uses the single `DF_COMPUTE_WORKER_DOCKER_HOST`. See [Compute hosts](COMPUTE_HOSTS.md).                                                                                                   |
| `DF_COMPUTE_WORKER_DOCKER_HOST_HEALTH_INTERVAL_SECONDS` | `15`                                                                     | Seconds between background health probes of each configured Docker host.                                                                                                                                                                                         |
| `DF_COMPUTE_WORKER_CONNECT_HOST`        | empty                                                                                     | Optional address the worker manager dials for published compute-worker RPC ports. Empty uses Docker DNS on the configured network.                                                                                                                                 |
| `DF_COMPUTE_WORKER_RPC_PORT`            | `50053`                                                                                   | Compute-worker gRPC port.                                                                                                                                                                                                                                         |
| `DF_COMPUTE_WORKER_START_TIMEOUT_SECONDS` | `30`                                                                                     | Maximum time to wait for a new compute worker to become ready.                                                                                                                                                                                                     |
| `DF_COMPUTE_WORKER_SHUTDOWN_GRACE_SECONDS` | `10`                                                                                    | Grace period for compute-worker shutdown before Docker force-stops its container.                                                                                                                                                                                   |
| `DF_COMPUTE_WORKER_HEARTBEAT_INTERVAL_SECONDS` | `5`                                                                                 | Worker-manager heartbeat interval for each assigned compute worker.                                                                                                                                                                                               |
| `DF_API_REPLICAS`                      | `2`                                                                                       | Number of API containers started by `docker/compose.replicas.yaml`. The base stack ignores it.                                                                                                                                                                  |
| `DF_API_REPLICA_TRUSTED_PROXY_HOPS`    | `1`                                                                                       | `TRUSTED_PROXY_HOPS` applied to the API replicas behind the bundled nginx ingress: the ingress itself plus any TLS terminator in front of it.                                                                                                                      |
| `DF_NODE_ADDRESS`                      | `10.0.0.1`                                                                                | `docker/compose.multi-host.yaml` only: this machine's private address, on which the runtime coordinator port 50051 is published for the other machines. The one value that differs per machine. See [High availability](HIGH_AVAILABILITY.md).                 |
| `DF_RUNTIME_COORDINATOR_TARGETS`       | `ipv4:10.0.0.1:50051,10.0.0.2:50051`                                                      | `docker/compose.multi-host.yaml` only: every machine's coordinator address as one gRPC `ipv4:` list, used as `INTERNAL_GRPC_TARGET` by workers and schedulers so they reach whichever coordinator is active.                                                     |
| `DF_COMPUTE_HOST_CERTS_DIR`            | `./certs`                                                                                 | `docker/compose.multi-host.yaml` only: directory (relative to `docker/`) mounted read-only at `/certs` in the worker, holding the TLS client certificates referenced by `tls_cert_path` in `DF_COMPUTE_WORKER_DOCKER_HOSTS`.                                             |
| `DF_DOCKER_SOCKET_PATH`                | `/var/run/docker.sock`                                                                    | Host Docker socket bind-mounted into the worker. Docker daemon access is administrative host access.                                                                                                                                                             |
| `DF_DOCKER_GID`                        | `0`                                                                                       | Group ID permitted to access the mounted Docker socket; set this to the socket's host group ID.                                                                                                                                                                  |
| `DISTRIBUTED_RUNTIME_ENABLED`          | `false`                                                                                   | Enables supported distributed runtime behavior when `DATABASE_URL` is Postgres.                                                                                                                                                                                  |
| `DEFAULT_NAMESPACE`                    | `default`                                                                                 | Namespace used when no namespace is selected.                                                                                                                                                                                                                    |
| `CORS_ORIGINS`                         | `http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed browser origins. Required in dev (Vite server is cross-origin). In prod (single port) same-origin applies and this can be left unset.                                                                                                    |
| `UPLOAD_MAX_FILE_SIZE_BYTES`           | `2147483648`                                                                              | Configurable upload size limit in bytes, from `0` to `2147483648` (2 GiB). Values above 2 GiB are rejected because the worker data-plane transport has a hard 2 GiB ceiling. `0` disables the configurable soft cap but does not disable that transport ceiling. |

### One-release compute-worker environment aliases

The worker service accepts the old names in this table for one release. The
new name wins when both are set; reading a deprecated name emits a warning that
identifies the old key. Remove old keys from deployment files after that
release.

| Current name | Deprecated one-release alias |
| --- | --- |
| `DF_COMPUTE_WORKER_IMAGE` | `DF_ENGINE_IMAGE`, `ENGINE_IMAGE` |
| `DF_COMPUTE_WORKER_DOCKER_HOST` | `DF_ENGINE_DOCKER_HOST`, `ENGINE_DOCKER_HOST` |
| `DF_COMPUTE_WORKER_DOCKER_HOSTS` | `DF_ENGINE_DOCKER_HOSTS`, `ENGINE_DOCKER_HOSTS` |
| `DF_COMPUTE_WORKER_DOCKER_HOST_HEALTH_INTERVAL_SECONDS` | `DF_ENGINE_DOCKER_HOST_HEALTH_INTERVAL_SECONDS`, `ENGINE_DOCKER_HOST_HEALTH_INTERVAL_SECONDS` |
| `DF_COMPUTE_WORKER_DOCKER_NETWORK` | `DF_ENGINE_DOCKER_NETWORK`, `ENGINE_DOCKER_NETWORK` |
| `DF_COMPUTE_WORKER_CONNECT_HOST` | `DF_ENGINE_CONNECT_HOST`, `ENGINE_CONNECT_HOST` |
| `DF_COMPUTE_WORKER_RPC_PORT` | `DF_ENGINE_RPC_PORT`, `ENGINE_RPC_PORT` |
| `DF_COMPUTE_WORKER_START_TIMEOUT_SECONDS` | `DF_ENGINE_START_TIMEOUT_SECONDS`, `ENGINE_START_TIMEOUT_SECONDS` |
| `DF_COMPUTE_WORKER_SHUTDOWN_GRACE_SECONDS` | `DF_ENGINE_SHUTDOWN_GRACE_SECONDS`, `ENGINE_SHUTDOWN_GRACE_SECONDS` |
| `DF_COMPUTE_WORKER_HEARTBEAT_INTERVAL_SECONDS` | `DF_ENGINE_HEARTBEAT_INTERVAL_SECONDS`, `ENGINE_HEARTBEAT_INTERVAL_SECONDS` |
| `COMPUTE_WORKER_OBJECT_STORE_ENDPOINT` | `DF_ENGINE_OBJECT_STORE_ENDPOINT`, `ENGINE_OBJECT_STORE_ENDPOINT` |
| `COMPUTE_WORKER_IDLE_TTL_SECONDS` | `ENGINE_IDLE_TTL_SECONDS` |
| `COMPUTE_WORKER_IDLE_REAP_INTERVAL_SECONDS` | `ENGINE_IDLE_REAP_INTERVAL_SECONDS` |

### Object storage

S3-compatible store for uploads, Iceberg tables, exports, and compute artifacts.

**The namespace is the bucket.** Name `analytics` means bucket `analytics`.
Nothing is rewritten. Keys sit directly in the bucket:

```text
s3://{namespace}/uploads/...
s3://{namespace}/clean/...
s3://{namespace}/exports/...
s3://{namespace}/runtime-staging/...
```

Namespace names must be valid bucket names (3–63 chars; lowercase letters,
digits, hyphens, underscores; start and end alphanumeric). Invalid names are
rejected; nothing is rewritten.

`DATA_DIR` remains a local directory for process scratch only.

| Variable                            | Default                 | Notes                                                                                                                                                                                                                                                                         |
| ----------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OBJECT_STORE_ENDPOINT`             | `http://127.0.0.1:9000` | S3-compatible HTTP(S) endpoint. Use the internal service URL from every application role.                                                                                                                                                                                     |
| `OBJECT_STORE_REGION`               | `us-east-1`             | S3 signing region. Must match the provider configuration.                                                                                                                                                                                                                     |
| `OBJECT_STORE_ACCESS_KEY`           | `rustfsadmin`           | Access key with read, write, list, delete, and bucket-creation permissions for namespace buckets. Replace the development default in production.                                                                                                                              |
| `OBJECT_STORE_SECRET_KEY`           | `rustfsadmin`           | Secret key paired with `OBJECT_STORE_ACCESS_KEY`. Replace the development default in production.                                                                                                                                                                              |
| `COMPUTE_WORKER_OBJECT_STORE_ENDPOINT` | empty                | Optional compute-worker endpoint for the same object store. Set this when the worker manager uses a host-published URL but compute workers should use private Docker DNS.                                                                                                    |
| `COMPUTE_WORKER_HEARTBEAT_INTERVAL_SECONDS` | `5`             | Worker-manager heartbeat interval for assigned compute workers. Compute workers stop themselves after three missed intervals.                                                                                                                                              |
| `COMPUTE_WARM_WORKERS`              | `0`                     | Additional ready, unassigned compute workers. A claimed worker is bound to one resource identity and immediately replaced. Checked-in dev/prod environments set this to `2`; E2E sets it to `4` for the 30-analysis probe. These workers are outside active compute capacity. |

All object-store settings are process-start configuration. Change them for the
API, scheduler, and worker together, then restart the complete runtime.

### Internal runtime (gRPC)

These variables configure the internal gRPC control plane between the runtime coordinator, scheduler, and worker. Scheduler and worker clients connect to `runtime`. The API also connects to the worker data-plane for object-store operations such as file upload.

Same-host processes can keep the loopback defaults. Split Docker roles must bind the coordinator/data-plane servers on `0.0.0.0` and point clients at Compose DNS (`runtime:50051`, `worker:50052`). With coordinators on several machines, give clients every address as one gRPC `ipv4:` target (`ipv4:10.0.0.1:50051,10.0.0.2:50051`): gRPC tries them in order and skips a standby, which does not listen.

| Variable                        | Default           | Notes                                                                                                                                                                                                                               |
| ------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INTERNAL_API_TOKEN`            | empty             | Shared secret used to authenticate internal gRPC calls between scheduler, worker, and API. Required when distributed runtime is enabled.                                                                                            |
| `INTERNAL_GRPC_HOST`            | `127.0.0.1`       | Host the dedicated runtime coordinator gRPC server binds to.                                                                                                                                                                        |
| `INTERNAL_GRPC_PORT`            | `50051`           | Port the dedicated runtime coordinator gRPC server listens on.                                                                                                                                                                      |
| `INTERNAL_GRPC_TARGET`          | `127.0.0.1:50051` | gRPC target that scheduler and worker clients connect to: `host:port`, or an `ipv4:addr:port,addr:port` list naming every machine that may host the active coordinator.                                                             |
| `RUNTIME_COORDINATOR_TARGET`    | empty             | Deployment target for the dedicated coordinator; required when API `WORKERS > 1`. API processes do not own runtime gRPC, dispatch, Telegram polling, or compute-worker lifecycle. Several coordinator containers may run, but only the lease holder is active.         |
| `WORKER_DATA_PLANE_GRPC_HOST`   | `127.0.0.1`       | Host the worker data-plane gRPC server binds to.                                                                                                                                                                                    |
| `WORKER_DATA_PLANE_GRPC_PORT`   | `50052`           | Port the worker data-plane gRPC server listens on.                                                                                                                                                                                  |
| `WORKER_DATA_PLANE_GRPC_TARGET` | `127.0.0.1:50052` | Full `host:port` target string that the API uses to reach the worker data-plane.                                                                                                                                                    |

### Compute-worker, scheduling, and resource limits

| Variable                          | Default | Notes                                                                                                                                                                                                                                                                                                                                                            |
| --------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SCHEDULER_CHECK_INTERVAL`        | `60`    | Seconds between scheduler polls.                                                                                                                                                                                                                                                                                                                                 |
| `LOCK_TTL_SECONDS`                | `30`    | Lock lease duration.                                                                                                                                                                                                                                                                                                                                             |
| `LOCK_HEARTBEAT_INTERVAL_SECONDS` | `10`    | Must stay lower than `LOCK_TTL_SECONDS`.                                                                                                                                                                                                                                                                                                                         |
| `POLARS_CORES_AVAILABLE`          | `0`     | Total cores available to compute workers; `0` = all host logical CPUs. Not Polars' native `POLARS_MAX_THREADS`.                                                                                                                                                                                                                                                   |
| `POLARS_MAX_MEMORY_MB`            | `0`     | `0` means unlimited.                                                                                                                                                                                                                                                                                                                                             |
| `POLARS_STREAMING_CHUNK_SIZE`     | `0`     | `0` means automatic chunk sizing.                                                                                                                                                                                                                                                                                                                                |
| `COMPUTE_WORKER_IDLE_TTL_SECONDS` | `300`   | Seconds an assigned compute worker may stay idle before the worker manager reaps its container.                                                                                                                                                                                                        |
| `COMPUTE_WORKER_IDLE_REAP_INTERVAL_SECONDS` | `30` | Seconds between idle compute-worker sweeps.                                                                                                                                                                                                                                                                |
| `COMPUTE_WORKERS`                 | `14`    | Current single-manager active capacity (`1`–`100` in this implementation): concurrent compute jobs and assigned workers. Builds, previews, and datasource operations share it; excess work remains durable and waits. Each assigned worker is bound to one exact analysis/datasource identity. Cluster-wide grants across multiple managers are not implemented. |
| `WORKERS`                         | `1`     | Valid range: `0` to `32`; `0` means auto in deployment scripts. Values above `1` require the dedicated runtime coordinator service and scale API processes only, not compute capacity.                                                                                                                                                                           |
| `WORKER_CONNECTIONS`              | `4096`  | Coarse maximum concurrent HTTP/WebSocket connections per Uvicorn process. Thread counts and blocking-work queue bounds are derived independently from database capacity; saturation returns overload responses instead of growing those queues with this connection limit.                                                                                                                                                                                                  |
| `DATABASE_POOL_SIZE`              | `8`     | SQLAlchemy pool size per process and per engine. The runtime coordinator inherits this bounded value; it is independent of `COMPUTE_WORKERS`. The API requires `DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW >= 3` for its general, synchronous-handler, and protected bootstrap lanes. |
| `DATABASE_MAX_OVERFLOW`           | `4`     | Extra Postgres connections allowed above each process's pool size. API processes and the runtime coordinator use this same bound; it must not scale with `COMPUTE_WORKERS`.                                                                                  |
| `DATABASE_POOL_TIMEOUT`           | `30`    | Seconds to wait for a Postgres pooled connection.                                                                                                                                                                                                                                                                                                                |

The runtime coordinator's pending RPC queue is bounded from `COMPUTE_WORKERS`
(`max(8, 2 × COMPUTE_WORKERS)` per RPC lane). Active RPC threads are still
bounded by its database pool; the queue bound allows compute bursts to wait
without making a database pool the admission limit. Work beyond the queue is
rejected explicitly while accepted compute requests remain durable.

### Logging and time handling

| Variable                       | Default | Notes                                                                                                                                        |
| ------------------------------ | ------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `LOG_LEVEL`                    | `info`  | One of `debug`, `info`, `warning`, `error`, `critical`.                                                                                      |
| `UVICORN_ACCESS_LOG`           | `true`  | Enables uvicorn access logs.                                                                                                                 |
| `UVICORN_TIMEOUT_KEEP_ALIVE`   | `5`     | Seconds before Uvicorn closes an idle keep-alive connection. E2E raises this above the suite budget so pooled API clients are not reset.    |
| `TIMEZONE`                     | `UTC`   | Must be a valid IANA timezone.                                                                                                               |
| `NORMALIZE_TZ`                 | `false` | Normalizes datetime values to `TIMEZONE`.                                                                                                    |
| `LOG_CLIENT_BATCH_SIZE`        | `20`    | Client audit batch size.                                                                                                                     |
| `LOG_CLIENT_FLUSH_INTERVAL_MS` | `5000`  | Client audit flush interval.                                                                                                                 |
| `LOG_CLIENT_DEDUPE_WINDOW_MS`  | `500`   | Dedupe window for repeated client events.                                                                                                    |
| `LOG_CLIENT_FLUSH_COOLDOWN_MS` | `3000`  | Cooldown before repeating client flush-failure logs.                                                                                         |
| `LOG_FLUSH_INTERVAL_SECONDS`   | `5`     | Flush interval for database-backed server logs.                                                                                              |
| `LOG_QUEUE_MAX_SIZE`           | `2000`  | Max queued log batches.                                                                                                                      |
| `LOG_QUEUE_OVERFLOW`           | `drop`  | One of `block` or `drop`.                                                                                                                    |
| `LOG_MAX_BODY_SIZE`            | `65536` | Max explicitly sized request/response body bytes to log. `0` disables body logging; unknown-size request bodies are never buffered for logs. |
| `PUBLIC_IDB_DEBUG`             | `false` | Enables IndexedDB debug panels in the frontend. Seeded via the backend config API endpoint — not a Vite/browser env var.                     |

### AI and provider settings

| Variable                    | Default                  | Notes                                             |
| --------------------------- | ------------------------ | ------------------------------------------------- |
| `OLLAMA_BASE_URL`           | `http://localhost:11434`     | Base URL for Ollama.                              |
| `OLLAMA_DEFAULT_MODEL`      | `llama3.2`                   | Default Ollama chat model.                        |
| `OPENROUTER_BASE_URL`       | `https://openrouter.ai/api/v1` | OpenRouter API base. Not a profile setting.     |
| `OPENROUTER_API_KEY`        | empty                        | Copied into settings when the saved key is empty. A key saved in the profile replaces it. |
| `OPENROUTER_DEFAULT_MODEL`  | empty                        | Seeded into DB on first run if DB field is empty. |
| `OLLAMA_ENDPOINT_URL_DB`    | empty                        | DB-seeded Ollama endpoint override.               |
| `OLLAMA_DEFAULT_MODEL_DB`   | empty                    | DB-seeded Ollama model override.                  |

### Notifications and encrypted settings

| Variable                  | Default | Notes                                                                                             |
| ------------------------- | ------- | ------------------------------------------------------------------------------------------------- |
| `SETTINGS_ENCRYPTION_KEY` | empty   | Strongly recommended in production when `AUTH_REQUIRED=true`; secrets stay unencrypted otherwise. |
| `SMTP_HOST`               | empty   | DB-seeded SMTP host.                                                                              |
| `SMTP_PORT`               | `587`   | DB-seeded SMTP port.                                                                              |
| `SMTP_USER`               | empty   | DB-seeded SMTP username.                                                                          |
| `SMTP_PASSWORD`           | empty   | DB-seeded SMTP password.                                                                          |
| `TELEGRAM_BOT_TOKEN`      | empty   | DB-seeded Telegram token.                                                                         |
| `TELEGRAM_BOT_ENABLED`    | `false` | DB-seeded Telegram enable flag.                                                                   |

### Authentication and OAuth

| Variable                | Default                                             | Notes                                                                                                                                                                                                                     |
| ----------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AUTH_REQUIRED`         | `false`                                             | Enables authenticated routes.                                                                                                                                                                                             |
| `VERIFY_EMAIL_ADDRESS`  | `true`                                              | Require email verification before password login. Set explicitly for production according to the deployment's mail flow.                                                                                                  |
| `DEFAULT_USER_EMAIL`    | `default@example.com`                               | Default env-managed account email.                                                                                                                                                                                        |
| `DEFAULT_USER_PASSWORD` | `ChangeMe123`                                       | Must contain upper, lower, and digit, and be at least 8 chars.                                                                                                                                                            |
| `DEFAULT_USER_NAME`     | `Default User`                                      | Default env-managed account name.                                                                                                                                                                                         |
| `AUTH_FRONTEND_URL`     | `http://localhost:5173`                             | Frontend base URL used in verification and password-reset email links. In prod set the public app origin. In dev set the Vite dev-server URL — must match `FRONTEND_PORT` (default `http://localhost:3000`). |
| `SESSION_MAX_AGE_DAYS`  | `30`                                                | Session lifetime in days.                                                                                                                                                                                                 |
| `TRUSTED_PROXY_HOPS`    | `0`                                                 | Number of trusted reverse proxies in front of the app. `0` ignores forwarded client IP and scheme headers.                                                                                                               |
| `GITHUB_CLIENT_ID`      | empty                                               | GitHub OAuth client id.                                                                                                                                                                                                   |
| `GITHUB_CLIENT_SECRET`  | empty                                               | GitHub OAuth client secret.                                                                                                                                                                                               |

GitHub OAuth derives its callback URL and post-login frontend URL from the
incoming request host. Behind a reverse proxy, set `TRUSTED_PROXY_HOPS` to the
proxy count so the callback uses the forwarded public scheme. Register the
deployment's `/api/v1/auth/github/callback` URL in the GitHub OAuth app.

## Frontend dev-server variables

> **Development only.** These configure the Vite dev server and its proxy.
> They live in `docker/env/dev.env` alongside the backend variables. `just dev`
> sources that file so both processes share the same configuration.
> In production the Vite dev server is not running, so none of these have any
> effect on the deployed application.

| Variable        | Default     | Notes                                                                                 |
| --------------- | ----------- | ------------------------------------------------------------------------------------- |
| `FRONTEND_PORT` | `3000`      | Local Vite dev-server port. Must match `AUTH_FRONTEND_URL`.                           |
| `BACKEND_HOST`  | `127.0.0.1` | Backend hostname used by the Vite proxy (Bun/Vite only, not exposed to browser code). |
| `BACKEND_PORT`  | `PORT`      | Backend port used by the Vite proxy. Defaults to `PORT` when unset.                   |

## Test and tooling variables

| Variable         | Default | Notes                                                                                                                                                                                                              |
| ---------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `PW_E2E_WORKERS` | `5`     | Playwright workers per E2E shard (3×5 validated). The checked-in E2E topology uses four API processes, one active runtime coordinator, one worker manager, a 32-worker compute budget, and four prewarmed workers. |
| `E2E_OPENROUTER_API_KEY` | empty  | OpenRouter key passed to the E2E runner and the chat model stack; the `runtime-architecture` chat tests fail fast without it. Lives in the git-ignored root `.env` together with the other local overrides. |
| `TEST_MEMORY_MB` | derived | Optional total memory budget in MiB per test recipe invocation. When unset, Python/Vitest uses 75% and E2E uses 90% of memory available to Docker. Explicit values must be at least `1024` MiB and no greater than Docker's available memory. E2E allocates 512 MiB to its controller and the remainder to its isolated DinD daemon, which runs all browser containers. |
| `TEST_CPUS`      | unset   | Optional total CPU budget per test recipe invocation; when set, it must be at least `0.1`. Without it, the invocation uses the Docker-reported CPU capacity. E2E allocates at least 0.5 CPUs or 20% of the total to its controller, whichever is greater, and gives the remainder to DinD; its total must leave CPU for both. Concurrent invocations each get their own cap. |
| `STRICT_TEST_TEARDOWN` | derived | Whether a test recipe fails when its Compose enclave teardown fails or exceeds its 90 s bound after the tests themselves passed. Defaults to `1` locally, where leftovers accumulate, and `0` when `CI` is set, where runners are ephemeral or cleaned by a runner-level post-step; a non-strict failure still writes `compose-down.log` and emits a GitHub Actions warning. Set `0` or `1` to override. |

Every public per-suite recipe creates a fresh daemon, network, and volumes in
its own private Compose enclave. `just test` runs the per-suite recipes
sequentially, while independent recipe invocations such as CI matrix jobs may
run concurrently. `TEST_MEMORY_MB` and `TEST_CPUS` are per invocation, not a
global host budget: concurrent caps add together and the host's CPU and memory
remain finite and shared. Budgets do not change service counts or test
concurrency. Recipes require Docker with privileged-container
support and `just` on the host. See [Docker test setup](../docker/README.md#containerized-tests)
for enclave lifecycle and security limits. Test logs and diagnostics are
exported to `.test-artifacts/<run-id>`.

## Recommended additions to consider later

These are **not implemented yet**, but they are reasonable future env-driven enhancements if you want more operational control:

- Rate limiting (`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_BURST`)
- Retention / cleanup (`DATA_RETENTION_DAYS`, `AUTO_CLEANUP_ENABLED`)
- Response caching (`CACHE_TTL_SECONDS`, `CACHE_MAX_SIZE_MB`)
- Alerting (`ERROR_ALERT_EMAIL`, `ENABLE_ERROR_NOTIFICATIONS`)
- Feature flags for experimental UI modules
