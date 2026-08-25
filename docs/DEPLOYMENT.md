# Deployment

Data-Forge has one production architecture: PostgreSQL and S3-compatible object
storage support three fixed application roles—API, scheduler, and worker. Docker
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

Keep the API, scheduler, and worker on the same release. They share database and
gRPC contracts and must be upgraded together.

## Docker Compose (recommended)

The checked-in stack runs five services:

```text
PostgreSQL ─┐
RustFS ─────┼── API (HTTP + internal gRPC) ◄── Scheduler
            │         │                    ◄── Worker
            │         └── worker data-plane gRPC
Browser ────┘
```

The API serves the built frontend and HTTP API on port 8000. The scheduler and
worker reach the API gRPC endpoint only through the Compose network. The API
reaches the worker data-plane gRPC the same way for object-store operations
such as file upload.

### Image channels

CI publishes every role image to GHCR on three channels:

| Channel | Trigger | Tags | Platforms |
| --- | --- | --- | --- |
| Dev / PR preview | pull request, push to `master` | `dev-pr-<number>`, `dev-master` | `linux/amd64` |
| Release | tag `v*` | `<version>`, semver aliases, `latest` | `linux/amd64`, `linux/arm64` |

Dev-channel images feed PR-preview deployments; release images are pinned in
production. Keep all four `DF_*_IMAGE` values on the same channel and commit.

### Naming, ports, and collision rules

All fixed Docker resources are unique per purpose so prod, dev, tests, e2e,
and centrally managed deployment stacks can coexist on one host:

- Compose projects: repo smoke uses `-p dataforge-prod`, containerized dev uses
  `-p dataforge-dev`; centrally deployed stacks use their own names
  (`dataforge-app`, `dataforge-app-dev`) with separate volumes.
- Engine networks follow the compose project (`dataforge-prod-engine-runtime`,
  `dataforge-dev-engine-runtime`) and never overlap test networks — tests and
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
2. Set the four image variables to tags published from the same release. `DF_ENGINE_IMAGE` must be available to the local Docker daemon before the worker starts.
3. Set `DF_AUTH_FRONTEND_URL`, OAuth callback URLs, and `DF_CORS_ORIGINS` to the
   public HTTPS origin.
4. Set `DF_DOCKER_SOCKET_PATH` and `DF_DOCKER_GID` for the deployment host. The worker is the only service with Docker access; this permission is equivalent to administrative host access.
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

Back up all three durable stores first. Then change all application image tags in
`docker/env/prod.env` to one release and run:

```bash
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml pull
docker compose --env-file docker/env/prod.env \
  -p dataforge-prod -f docker/compose.yaml up -d
```

Watch the logs and wait for `/health/ready` before returning traffic to the
deployment. Roll back by restoring the coordinated backups and the previous set
of image tags; application images and persisted data should not be rolled back
independently.

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
  Each product namespace is an S3 bucket (name == bucket);
- provision separate namespace reader and builder object-store identities and
  set `ENGINE_OBJECT_STORE_CREDENTIALS_JSON`; production rejects the platform
  object-store credentials for engine containers;
- replace `INTERNAL_API_TOKEN` and `SETTINGS_ENCRYPTION_KEY`;
- set `DATA_DIR` to a writable, durable local directory for process scratch;
- set the public auth and OAuth URLs;
- keep `DISTRIBUTED_RUNTIME_ENABLED=true` and `PROD_MODE_ENABLED=true`.

Start the complete application runtime:

```bash
just prod
```

The recipe generates protocol bindings, builds the static frontend, loads
`docker/env/prod.env`, and runs the API, scheduler, and worker in the foreground.
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
available. For either proxy, set `AUTH_FRONTEND_URL` and OAuth callback URLs to
`https://dataforge.example.com`.

## Health checks

Use the unauthenticated root health endpoints:

| Endpoint | Purpose | Healthy response |
| --- | --- | --- |
| `/health` | Liveness: the API process can answer HTTP | `200` |
| `/health/ready` | Readiness: PostgreSQL and required local directories are available | `200`; otherwise `503` |
| `/health/startup` | Startup: application settings initialized | `200` |

Example:

```bash
curl --fail --silent https://dataforge.example.com/health/ready
```

The Compose health check uses `/health/ready`. Also monitor PostgreSQL and object
store capacity, application-role restarts, error logs, and backup age; the API
readiness endpoint is not a complete infrastructure monitor.

## Backup and restore

A recoverable deployment needs a point-in-time-consistent set containing:

1. PostgreSQL metadata;
2. the entire configured object-store bucket/prefix;
3. the local `DATA_DIR` volume, which contains local runtime files and logs.

Pause writes or stop API, scheduler, and worker while taking coordinated backups.
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
