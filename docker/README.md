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
| `docker-compose.yml` | Base runtime stack. |
| `docker-compose.dev.yml` | Development override with source mounts and Vite. |
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

## Production compose

Use the base compose file directly with `docker/env/prod.env`:

```bash
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/docker-compose.yml pull
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/docker-compose.yml up -d
```

All three `DF_*_IMAGE` values must refer to the same Data-Forge release. Replace
the example passwords, internal token, encryption key, and object-store
credentials before starting the stack.

Inspect the deployment:

```bash
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/docker-compose.yml ps
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/docker-compose.yml logs -f
```

Stop the deployment while preserving volumes:

```bash
docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/docker-compose.yml down
```

Do not pass `-v` for production unless permanent deletion of all three durable
volumes is intentional and verified.
