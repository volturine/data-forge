# Deployment

The current production architecture uses PostgreSQL and S3-compatible object
storage with four application roles—API, runtime coordinator, scheduler, and
the worker manager service. Docker
Compose is the recommended deployment method. Running the same roles from source
is supported when the infrastructure is managed separately.

Standalone binaries from the v0.2-era single-process architecture are not a
supported deployment method. The current distributed runtime is not packaged as
one executable; do not use old binary artifacts for a current installation.

## Before you deploy

Production requires:

- PostgreSQL 18 or later;
- an S3-compatible object store such as RustFS;
- durable storage for PostgreSQL, the object store, and `DATA_DIR`;
- unique values for database, internal-runtime, authentication, OAuth, and
  encryption secrets;
- a reverse proxy with TLS for any host exposed outside a trusted network.

Keep the API, runtime coordinator, scheduler, worker-manager, and compute-worker
images on the same release. They share protocol contracts and must be upgraded
together. The worker service owns Docker; compute workers are the isolated
containers it starts for analyses and datasources.

## Docker Compose (recommended)

The checked-in stack runs six services:

```text
PostgreSQL ─┐
RustFS ─────┼── API (HTTP) ◄── Runtime coordinator (internal gRPC)
            │       │                         ▲
            │       └── worker data-plane     ├── Scheduler
            │                                 └── Worker manager (Docker owner)
            │         └── worker data-plane gRPC
Browser ────┘
```

The API processes serve the built frontend and HTTP API on port 8000, including
WebSocket/SSE delivery and durable enqueue-and-wait request paths. They retain
disposable process-local caches, projections, and waiters; these are not
authoritative durable runtime state. They do not own compute dispatch, Telegram
polling, or compute-worker lifecycle. One active fenced runtime
coordinator owns internal gRPC/dispatch, durable chat processing, Telegram
polling, and independent durable email/Telegram delivery lanes. One worker
manager owns Docker and isolated compute-worker containers; each assigned compute worker is
bound to one exact analysis or datasource RID. Identical full commands share
durable results, while distinct commands for one RID are serialized. Increasing
`WORKERS` scales API processes inside that container only. The Compose API
service publishes one fixed host port, so adding API containers also requires
an ingress/load-balancer topology. See [Capacity-First Runtime Optimization](prd/active/elastic-runtime-scale-out.md)
for the 1×1 baseline and evidence-gated scale path.

External notification delivery claims durable outbox metadata before making
email or Telegram network calls; those calls run outside the database
transaction. Compute parsing and Polars-heavy work run in isolated compute
workers managed by the worker service.

Compute-worker cancellation targets the exact job ID, remembers requests made before
the job starts, and waits for the actual execution thread to settle before
releasing its admission. SMTP tests admit one thread; a deadline while sending
can return before that thread settles, so the provider may already have accepted
the email. Admission remains occupied until the thread finishes; a deadline is
not proof that no email was sent.

The API reaches the worker data-plane gRPC for object-store operations such as
file upload.

### Image channels

CI publishes every role image to GHCR on three channels:

| Channel          | Trigger                        | Tags                                  | Platforms                    |
| ---------------- | ------------------------------ | ------------------------------------- | ---------------------------- |
| Dev / PR preview | pull request, push to `master` | `dev-pr-<number>`, `dev-master`       | `linux/amd64`                |
| Release          | tag `v*`                       | `<version>`, semver aliases, `latest` | `linux/amd64`, `linux/arm64` |

Dev-channel images feed PR-preview deployments; release images are pinned in
production. Keep all five `DF_*_IMAGE` values on the same channel and commit.
The old `data-forge-polars-engine` image name is published as a compatibility
alias for one release; new manifests use `data-forge-compute-worker`.

### Naming, ports, and collision rules

All fixed Docker resources are unique per purpose so prod, dev, tests, e2e,
and centrally managed deployment stacks can coexist on one host:

- Compose projects: repo smoke uses `-p dataforge-prod`, containerized dev uses
  `-p dataforge-dev`; centrally deployed stacks use their own names
  (`dataforge-app`, `dataforge-app-dev`) with separate volumes.
- Compute-worker networks follow the compose project (`dataforge-prod-compute-worker-runtime`,
  `dataforge-dev-compute-worker-runtime`) and never overlap test networks — tests and
  e2e always create per-run networks with UUID/run-id suffixes on random free
  ports.
- Host ports: dev 8000/3000 (`just dev` and `docker-dev` are mutually
  exclusive), production smoke 8300, central deployment prod 3300, dev 3400.

The central deployments workspace (one directory per project with
`compose.prod.yaml`, `compose.dev.yaml`, a Tailscale Serve overlay, and real
`.env.*` files) is the standard way these images get run on servers; its
compose files mirror this directory's topology and follow the same registry.

### Configure and start

1. Review `docker/env/prod.env` and replace every `replace-with-...` value.
2. Set the five image variables to tags published from the same release. `DF_COMPUTE_WORKER_IMAGE` must be available to the local Docker daemon before the worker manager starts. Pin it to a `repository@sha256:<digest>` reference when compute workers must stay byte-identical across launches; tags remain accepted for custom compute-worker images with extra libraries.
3. Set `DF_AUTH_FRONTEND_URL` and `DF_CORS_ORIGINS` to the public HTTPS origin.
   GitHub OAuth derives its callback from the incoming request host, so register
   `https://<your-host>/api/v1/auth/github/callback` in the GitHub OAuth app.
   Set `DF_TRUSTED_PROXY_HOPS` to the number of proxies that provide the
   forwarded public scheme.
4. Set `DF_DOCKER_SOCKET_PATH` and `DF_DOCKER_GID` for the deployment host. The worker manager is the only service with Docker access; this permission is equivalent to administrative host access. To run compute workers on more than one machine, list the daemons in `DF_COMPUTE_WORKER_DOCKER_HOSTS` as described in [Compute hosts](COMPUTE_HOSTS.md).
5. Start the stack:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod \
  -f docker/compose.yaml \
  pull
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod \
  -f docker/compose.yaml \
  up -d
```

The old `DF_ENGINE_*` and `ENGINE_*` environment names are accepted for one
release. The worker manager logs a deprecation warning when it reads one; new
names take precedence. Remove old keys from deployment files during this
release. `data-forge-polars-engine` is also published as a compatibility image
alias for this release only.

Inspect status and logs:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml ps
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml logs -f
```

Stop containers without deleting durable volumes:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml down
```

Do not add `-v` to the production `down` command: it deletes the PostgreSQL,
RustFS, and application-data volumes.

### Update

Keep ingress traffic drained until migrations and health checks are complete.
Back up all three durable stores, stop the API, runtime coordinator, scheduler,
and worker manager, then set the five image tags and new compute-worker
variables in `docker/env/prod.env`. Pull the release images without starting the
services:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml pull
```

Run the new API image once to apply its migrations to the public schema and all
registered tenant schemas before starting the application roles:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml \
  run --rm --no-deps api python3 -c \
  'import asyncio; from backend_core.database import init_db; asyncio.run(init_db())'
```

The revision order is part of the rollout: apply #244's table/column revisions
first (public `0025`, tenant `0026`), then #246's constraints (public `0027`,
tenant `0028`), all before restoring traffic. The current public head also
includes #247's Docker-host revision `0029`. After the migration job succeeds,
start the coordinated release:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml up -d
```

Watch the API and worker-manager logs, confirm `/health/ready`, and restore
traffic only after the new release is healthy.

For a rollback of the #246 constraint layer, downgrade public `0027` to `0025`
and tenant `0028` to `0026`. The current public `0029` revision follows `0027`,
so first unwind it to `0027`; reaching `0025` also removes the Docker-host
column introduced by #247. Keep traffic drained and use application images
compatible with that schema. For a full rollback of #244, continue to public
`0020` and tenant `0024` before deploying the previous images. Restore the
coordinated backups if the database and object-store data must return to their
pre-upgrade state; do not roll back application images and persisted data
independently.

### Scale out

API containers are stateless: sessions, locks, namespaces, jobs, projections
and runtime notifications live in PostgreSQL, every API process has a unique
identity, and WebSocket/SSE fan-out goes through Postgres `LISTEN/NOTIFY`, so
any replica can serve any request. `docker/compose.replicas.yaml` removes the
fixed host port from the API service, runs `DF_API_REPLICAS` copies of it
(default 2) and publishes `DF_API_PORT` through an nginx ingress that balances
HTTP and WebSocket traffic across them:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod \
  -f docker/compose.yaml -f docker/compose.replicas.yaml \
  up -d
```

The ingress is one proxy hop; the override replaces `DF_TRUSTED_PROXY_HOPS`
with `DF_API_REPLICA_TRUSTED_PROXY_HOPS` (default `1`) for the API replicas,
so set it to the ingress plus every proxy in front of it, for example `2` with
a TLS terminator ahead of the ingress. Replicas share the `data` volume only for
scratch files. The runtime coordinator and the worker manager are single active
instances chosen by PostgreSQL leases; extra copies of them are standbys, not
replicas.

Compute capacity scales across machines: the active worker manager can place
compute workers on several Docker daemons. See
[Compute hosts](COMPUTE_HOSTS.md) for how to add a host.

To survive the loss of a whole machine, run the same stack on two or three
machines with `docker/compose.multi-host.yaml`: API replicas on every machine,
coordinator and manager active on one and standby on the others, schedulers
everywhere, compute workers on every daemon, and PostgreSQL and the object
store shared outside the stacks. See [High availability](HIGH_AVAILABILITY.md).

## From source

Install Python 3.14+, `uv`, Bun, `just`, and Git. Provision PostgreSQL and an
S3-compatible object store before starting Data-Forge; `just prod` does not start
or supervise infrastructure.

```bash
git clone https://github.com/volturine/data-forge.git
cd data-forge
just install
```

Edit `docker/env/prod.env`:

- set `DATABASE_URL` to PostgreSQL;
- set the four `OBJECT_STORE_*` values (endpoint, region, access key, secret).
  Each product namespace is an S3 bucket (name == bucket). The backend
  provisions namespace-scoped reader/builder compute-worker identities and serves them
  to workers over the authenticated internal gRPC API — no per-namespace
  object-store configuration is required;
- replace `INTERNAL_API_TOKEN` and `SETTINGS_ENCRYPTION_KEY`;
- set `DATA_DIR` to a writable, durable local directory for process scratch;
- set the public auth and OAuth URLs;
- keep `DISTRIBUTED_RUNTIME_ENABLED=true` and `PROD_MODE_ENABLED=true`.

Start the complete application runtime:

```bash
just prod
```

The recipe generates protocol bindings, builds the static frontend, loads
`docker/env/prod.env`, and runs the API, runtime coordinator, scheduler, and
worker in the foreground.
If one role exits, the recipe stops the others and exits unsuccessfully. Run it
under a process supervisor that restarts the whole group and forwards `SIGTERM`;
do not start only the API.

## Reverse proxy and TLS

Terminate TLS at the reverse proxy and forward both normal HTTP and WebSocket
upgrades to the API. Set `TRUSTED_PROXY_HOPS=1` only when exactly one trusted
proxy is in front of Data-Forge; otherwise use the actual trusted hop count.

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name dataforge.example.com;

    ssl_certificate /etc/letsencrypt/live/dataforge.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dataforge.example.com/privkey.pem;

    client_max_body_size 2g;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

Redirect port 80 to HTTPS in a separate server block. Certificate provisioning
and renewal remain the operator's responsibility.

### Caddy

```caddyfile
dataforge.example.com {
    request_body {
        max_size 2GB
    }
    reverse_proxy 127.0.0.1:8000
}
```

Caddy obtains and renews public certificates when DNS and ports 80/443 are
available. For either proxy, set `AUTH_FRONTEND_URL` to
`https://dataforge.example.com` and register
`https://dataforge.example.com/api/v1/auth/github/callback` in the GitHub OAuth
app. Set `TRUSTED_PROXY_HOPS=1` when a single proxy terminates TLS.

## Health checks

Use the unauthenticated root health endpoints:

| Endpoint          | Purpose                                                                               | Healthy response       |
| ----------------- | ------------------------------------------------------------------------------------- | ---------------------- |
| `/health`         | Liveness: the API process can answer HTTP                                             | `200`                  |
| `/health/ready`   | Readiness: PostgreSQL and the object-store probe succeed                              | `200`; otherwise `503` |
| `/health/startup` | Startup: application settings initialized                                             | `200`                  |

Example:

```bash
curl --fail --silent https://dataforge.example.com/health/ready
```

The API Compose health check uses `/health/ready` to verify API dependencies.
Worker and scheduler Docker probes query PID1's private Unix socket through
`python3 -m runtime.dispatcher_health` and `python3 -m scheduler_grpc.health`,
respectively. They require that process's actual registration and fresh progress
on every configured dispatch lane; a worker waiting in standby for the manager
lease reports healthy without a registration. The runtime coordinator probe,
`python3 -m backend_core.coordinator_health`, accepts a standby waiting for the
coordinator lease and, for the active owner, still requires its gRPC endpoint to
answer with the active generation. Worker lanes cover compute execution and
shutdown, builds, datasource deletion, and outbox cleanup. A database registry
row or independent heartbeat cannot mask a stalled lane. API readiness does not establish
coordinator dispatch progress. Also monitor PostgreSQL and object-store capacity,
application-role restarts, error logs, and backup age.

## Private storage cleanup

Storage GC uses the existing durable outbox and an independent worker I/O lane.
It records durable source intents before staging and retirement, then
cleans exact managed objects/prefixes and associated catalog IDs idempotently.
Busy RIDs defer cleanup. Referenced targets become `PUBLISHED` and retain their
data; abandoned targets require fenced `AUTHORIZED` grants before deletion.
Published snapshots keep their existing retention policy. Cleanup uses durable
intents and indexed source references rather than blob discovery; it introduces
no additional service or public configuration. See the
[private GC contract](prd/active/elastic-runtime-scale-out.md#private-storage-gc)
for authorization, ownership transfer, and acknowledgement rules.

## Backup and restore

A recoverable deployment needs a point-in-time-consistent set containing:

1. PostgreSQL metadata;
2. the entire configured object-store bucket/prefix;
3. the local `DATA_DIR` volume, which contains local runtime files and logs.

Pause writes or stop API, runtime coordinator, scheduler, and worker while taking coordinated backups.
Use provider-native snapshots/versioning for managed PostgreSQL and S3 whenever
available, and test restores regularly.

### Docker PostgreSQL

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml \
  exec -T postgres pg_dump -U dataforge -d dataforge -Fc > dataforge-postgres.dump
```

Restore into an empty or disposable database after stopping application roles:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml \
  exec -T postgres pg_restore -U dataforge -d dataforge \
  --clean --if-exists --no-owner < dataforge-postgres.dump
```

If you changed `DF_POSTGRES_USER` or `DF_POSTGRES_DB`, use those configured names.

### Docker volumes

With the documented project name, back up the RustFS and local data volumes:

```bash
docker run --rm -v dataforge-prod_rustfs-data:/source:ro \
  -v "$PWD":/backup alpine \
  tar -czf /backup/dataforge-rustfs.tgz -C /source .
docker run --rm -v dataforge-prod_data:/source:ro \
  -v "$PWD":/backup alpine \
  tar -czf /backup/dataforge-data-dir.tgz -C /source .
```

Confirm actual volume names with `docker volume ls` if a different Compose
project name was used. Restore only while every service using the target volume
is stopped, into an empty volume, and together with the matching PostgreSQL
backup. For an external S3 service, back up the configured bucket and prefix with
that provider's versioning, replication, or snapshot tooling.

## Secret rotation

- Rotate database and object-store credentials in the services first, update all
  Data-Forge roles together, then restart the complete runtime.
- Rotate `INTERNAL_API_TOKEN` simultaneously for API, scheduler, and worker; mixed
  values prevent role registration and job processing.
- Treat `SETTINGS_ENCRYPTION_KEY` as data-encryption material, not an ordinary
  password. Follow an application-supported re-encryption procedure before
  replacing it; changing it blindly makes stored encrypted settings unreadable.
- Rotate OAuth, SMTP, Telegram, and AI-provider credentials at their providers,
  update Data-Forge, restart if the value comes from the environment, and revoke
  the previous credential after verification.
- Never commit production secrets or reuse the checked-in example values.

See [Environment Variables](ENV_VARIABLES.md) for the complete configuration
contract and [Docker model](../docker/README.md) for Compose-specific commands.
