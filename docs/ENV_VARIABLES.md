# Environment Variables

This project uses environment variables for two layers:

1. **Backend runtime** — loaded by `packages/shared/core/config.py` from process env and the env file selected by `ENV_FILE`
2. **Frontend dev server (Vite)** — read from the process environment; `just dev` sources `packages/shared/dev.env` so local dev variables come from the same file

There is no separate `packages/frontend/.env` file. All local dev configuration — including Vite
dev-server settings (`FRONTEND_PORT`, `BACKEND_HOST`) — lives in `packages/shared/dev.env`.

## Deployment topologies

Understanding the two topologies helps you know which variables matter and
which are irrelevant for your context.

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

- Customer install: copy `docker/docker-compose.yml` to `compose.yml` plus `docker/env/prod.env` to `.env`, then run `docker compose pull && docker compose up -d`
- Maintainer local smoke test: `just docker-prod` uses the same `docker/env/prod.env` but overrides image tags to local builds at runtime
- Bare-metal (`just prod`): edit `packages/shared/prod.env`

### Development — local runtime

```
Browser  ──►  Vite dev server (FRONTEND_PORT 3000)
                   │
                   └── /api/* proxy ──►  FastAPI (BACKEND_PORT 8000)

Repo-level local runtime:
  - backend/main.py API process
  - scheduler/main.py scheduler process
  - worker-manager/main.py worker-manager process
  - dynamically spawned build-worker subprocesses
```

- `PROD_MODE_ENABLED=false` (default) — FastAPI does not serve static files; the
  Vite dev server handles all browser requests and proxies `/api` to FastAPI.
- `just dev` starts the three package entrypoints from the repo root. The
  worker manager then spawns build workers on demand.
- Because the browser origin (`:3000`) differs from the API origin (`:8000`),
  FastAPI's `CORS_ORIGINS` **must** include the dev-server origin.
- `FRONTEND_PORT`, `BACKEND_HOST`, and `BACKEND_PORT` wire the Vite
  proxy to the correct backend address. WebSocket connections go through the
  Vite proxy — no backend host/port is exposed to browser code.
- `AUTH_FRONTEND_URL` should be the Vite dev-server URL (e.g.
  `http://localhost:5173` or `http://localhost:3000`).

**Templates for this topology:**

- Edit `packages/shared/dev.env` (covers both backend and Vite dev-server settings)

---

## What to configure first

If you only want the high-value knobs, start with these:

- `DATA_DIR` — where app data, uploads, exports, and logs live
- `PORT` — backend port
- `CORS_ORIGINS` — allowed browser origins (only needed in dev or multi-origin setups)
- `AUTH_REQUIRED` — turn login on/off
- `SETTINGS_ENCRYPTION_KEY` — strongly recommended when auth is enabled
- `POLARS_MAX_THREADS`, `POLARS_MAX_MEMORY_MB`, `MAX_CONCURRENT_ENGINES` — performance limits
- **Dev-only:** `BACKEND_HOST`, `BACKEND_PORT`, `FRONTEND_PORT` — Vite proxy wiring (Bun/Vite only, not exposed to browser)

## How configuration is loaded

### Backend

- `Settings()` reads process environment first, then an env file.
- `ENV_FILE` chooses the env file path. Default: `.env`.
- Set `ENV_FILE` to an empty value only if you want to rely on process env alone.
- `DATABASE_URL` is the backend database URL and must be a full PostgreSQL connection string.
- Some values such as SMTP and provider defaults are **seeded into the database once**. After the UI saves a value, the database value wins until it is cleared.

### Frontend dev server

- `just dev` sources `packages/shared/dev.env` into the shell before starting Vite, so `FRONTEND_PORT` and `BACKEND_HOST` are inherited from the same file as the backend.
- No `packages/frontend/.env` file is needed or used.
- No variables are exposed to browser code — the `VITE_` prefix convention is not used.

## Setup examples

### Production — Docker / compose

```bash
# From the repository root
# Customer install bundle
cp docker/env/prod.env .env
# Edit .env with your host, secrets, and release tags
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml up -d
```

`docker/docker-compose.yml` is the single production compose file. `docker/env/prod.env` is the single production env template. `just docker-prod` uses that same env file but overrides image tags to local builds at runtime. GHCR-published images are for production releases only.
`docker/docker-compose.yml` uses published fixed-role images and does not build application images during `up`.
The compose topology uses separate `api`, `scheduler`, and `worker` containers from the same codebase release.
The checked-in Docker topology still includes `postgres` because the supported Docker runtime path is Postgres-backed. `DF_DATABASE_URL` in the Docker env files points at that service.

The checked-in Docker production env defaults to `DF_WORKERS=4` for the API process pool in the `api` service, `DF_BUILD_WORKER_MIN_PROCESSES=0`, and dynamic build-worker spawn up to `DF_BUILD_WORKER_MAX_PROCESSES` in the `worker` service.

### Production — bare-metal (`just prod`)

```bash
# Build the frontend first
cd packages/frontend && bun run build && cd ../..
# Configure the backend
# Edit packages/shared/prod.env with your host, secrets, resource limits
just prod
```

The checked-in `packages/shared/prod.env` now defaults to `WORKERS=4` and dynamic build-worker scaling with zero warm workers.

### Local development

```bash
# Edit packages/shared/dev.env with your settings — covers both backend and Vite dev-server
just dev
```

## Backend variables

### Application and files

| Variable                     | Default                                                                                   | Notes                                                                                                                                                         |
| ---------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ENV_FILE`                   | `.env`                                                                                    | Path to the backend env file.                                                                                                                                 |
| `APP_NAME`                   | `Data-Forge Analysis Platform`                                                            | Application name for UI/logging metadata.                                                                                                                     |
| `APP_VERSION`                | `1.0.0`                                                                                   | Application version string.                                                                                                                                   |
| `DEBUG`                      | `false`                                                                                   | Enables verbose/debug behavior.                                                                                                                               |
| `PROD_MODE_ENABLED`          | `false`                                                                                   | Must be `true` in production. Enables static-file serving from `packages/frontend/build/`. In dev, leave `false` so FastAPI does not try to serve the frontend. |
| `PORT`                       | `8000`                                                                                    | Backend HTTP port.                                                                                                                                            |
| `DATA_DIR`                   | system temp dir + `/data-forge`                                                           | Base writable directory for app data.                                                                                                                         |
| `DATABASE_URL`               | none                                                                                      | Full backend PostgreSQL database URL. Required.                                                                                                                |
| `DF_API_IMAGE`              | `ghcr.io/volturine/data-forge-api:1.0.0`                                                  | Docker compose production image tag for the `api` service. Pull this image before `docker compose up`.                                                         |
| `DF_SCHEDULER_IMAGE`        | `ghcr.io/volturine/data-forge-scheduler:1.0.0`                                            | Docker compose production image tag for the `scheduler` service.                                                                                                 |
| `DF_WORKER_IMAGE`           | `ghcr.io/volturine/data-forge-worker:1.0.0`                                               | Docker compose production image tag for the `worker` service.                                                                                                    |
| `DISTRIBUTED_RUNTIME_ENABLED`| `false`                                                                                   | Enables supported distributed runtime behavior when `DATABASE_URL` is Postgres.                                                                                |
| `DEFAULT_NAMESPACE`          | `default`                                                                                 | Namespace used when no namespace is selected.                                                                                                                 |
| `CORS_ORIGINS`               | `http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed browser origins. Required in dev (Vite server is cross-origin). In prod (single port) same-origin applies and this can be left unset. |
| `UPLOAD_CHUNK_SIZE`          | `5242880`                                                                                 | Upload chunk size in bytes. Valid range: `1024` to `104857600`.                                                                                               |
| `UPLOAD_MAX_FILE_SIZE_BYTES` | `2147483648`                                                                              | Maximum upload size in bytes.                                                                                                                                 |

### Engine, scheduling, and resource limits

| Variable                          | Default | Notes                                                           |
| --------------------------------- | ------- | --------------------------------------------------------------- |
| `SCHEDULER_CHECK_INTERVAL`        | `60`    | Seconds between scheduler polls.                                |
| `LOCK_TTL_SECONDS`                | `30`    | Lock lease duration.                                            |
| `LOCK_HEARTBEAT_INTERVAL_SECONDS` | `10`    | Must stay lower than `LOCK_TTL_SECONDS`.                        |
| `POLARS_MAX_THREADS`              | `0`     | `0` means auto-detect.                                          |
| `POLARS_MAX_MEMORY_MB`            | `0`     | `0` means unlimited.                                            |
| `POLARS_STREAMING_CHUNK_SIZE`     | `0`     | `0` means automatic chunk sizing.                               |
| `MAX_CONCURRENT_ENGINES`          | `10`    | Valid range: `1` to `100`.                                      |
| `WORKERS`                         | `1`     | Valid range: `0` to `32`; `0` means auto in deployment scripts. The checked-in production env templates currently set this to `4`. |
| `WORKER_CONNECTIONS`              | `1000`  | Maximum connections per worker.                                 |
| `BUILD_WORKER_MIN_PROCESSES`      | `0`     | Minimum warm build-worker subprocesses to keep alive.           |
| `BUILD_WORKER_MAX_PROCESSES`      | `10`    | Maximum dynamic build-worker subprocesses. Must be <= `MAX_CONCURRENT_ENGINES`. |
| `BUILD_WORKER_IDLE_EXIT_SECONDS`  | `30`    | Seconds an idle build worker waits before exiting.              |
| `EMBEDDED_BUILD_WORKER_ENABLED`   | `false` | Debug-only local override. It is incompatible with distributed runtime mode. |
| `DATABASE_POOL_SIZE`              | `10`    | SQLAlchemy pool size for Postgres runtime.                      |
| `DATABASE_MAX_OVERFLOW`           | `20`    | Extra Postgres connections allowed above pool size.             |
| `DATABASE_POOL_TIMEOUT`           | `30`    | Seconds to wait for a Postgres pooled connection.               |

### Logging and time handling

| Variable                            | Default            | Notes                                                                                                                    |
| ----------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `LOG_LEVEL`                         | `info`             | One of `debug`, `info`, `warning`, `error`, `critical`.                                                                  |
| `UVICORN_ACCESS_LOG`                | `true`             | Enables uvicorn access logs.                                                                                             |
| `TIMEZONE`                          | `UTC`              | Must be a valid IANA timezone.                                                                                           |
| `NORMALIZE_TZ`                      | `false`            | Normalizes datetime values to `TIMEZONE`.                                                                                |
| `LOG_CLIENT_BATCH_SIZE`             | `20`               | Client audit batch size.                                                                                                 |
| `LOG_CLIENT_FLUSH_INTERVAL_MS`      | `5000`             | Client audit flush interval.                                                                                             |
| `LOG_CLIENT_DEDUPE_WINDOW_MS`       | `500`              | Dedupe window for repeated client events.                                                                                |
| `LOG_CLIENT_FLUSH_COOLDOWN_MS`      | `3000`             | Cooldown before repeating client flush-failure logs.                                                                     |
| `LOG_FLUSH_INTERVAL_SECONDS`        | `5`                | Flush interval for database-backed server logs.                                                                          |
| `LOG_QUEUE_MAX_SIZE`                | `2000`             | Max queued log batches.                                                                                                  |
| `LOG_QUEUE_OVERFLOW`                | `drop`             | One of `block` or `drop`.                                                                                                |
| `LOG_MAX_BODY_SIZE`                 | `65536`            | Max request/response body bytes to log. `0` means unlimited.                                                             |
| `PUBLIC_IDB_DEBUG`                  | `false`            | Enables IndexedDB debug panels in the frontend. Seeded via the backend config API endpoint — not a Vite/browser env var. |

### AI and provider settings

| Variable                       | Default                                | Notes                                             |
| ------------------------------ | -------------------------------------- | ------------------------------------------------- |
| `OLLAMA_BASE_URL`              | `http://localhost:11434`               | Base URL for Ollama.                              |
| `OLLAMA_DEFAULT_MODEL`         | `llama3.2`                             | Default Ollama chat model.                        |
| `OPENAI_API_KEY`               | empty                                  | OpenAI API key.                                   |
| `OPENAI_BASE_URL`              | `https://api.openai.com`               | OpenAI-compatible API base URL.                   |
| `OPENAI_DEFAULT_MODEL`         | `gpt-4o-mini`                          | Default OpenAI model.                             |
| `OPENAI_ORGANIZATION_ID`       | empty                                  | Optional OpenAI org id.                           |
| `HUGGINGFACE_API_TOKEN`        | empty                                  | Hugging Face token.                               |
| `HUGGINGFACE_DEFAULT_MODEL`    | `google/flan-t5-base`                  | Default Hugging Face model.                       |
| `HUGGINGFACE_API_BASE_URL`     | `https://api-inference.huggingface.co` | Hugging Face inference base URL.                  |
| `OPENROUTER_API_KEY`           | empty                                  | Seeded into DB on first run if DB field is empty. |
| `OPENROUTER_DEFAULT_MODEL`     | empty                                  | Seeded into DB on first run if DB field is empty. |
| `OPENAI_DEFAULT_MODEL_DB`      | empty                                  | DB-seeded default model override.                 |
| `OPENAI_ENDPOINT_URL_DB`       | empty                                  | DB-seeded endpoint override.                      |
| `OPENAI_ORGANIZATION_ID_DB`    | empty                                  | DB-seeded organization override.                  |
| `OLLAMA_ENDPOINT_URL_DB`       | empty                                  | DB-seeded Ollama endpoint override.               |
| `OLLAMA_DEFAULT_MODEL_DB`      | empty                                  | DB-seeded Ollama model override.                  |
| `HUGGINGFACE_DEFAULT_MODEL_DB` | empty                                  | DB-seeded Hugging Face model override.            |

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
| `DEFAULT_USER_EMAIL`    | `default@example.com`                               | Default env-managed account email.                                                                                                                                                                                        |
| `DEFAULT_USER_PASSWORD` | `ChangeMe123`                                       | Must contain upper, lower, and digit, and be at least 8 chars.                                                                                                                                                            |
| `DEFAULT_USER_NAME`     | `Default User`                                      | Default env-managed account name.                                                                                                                                                                                         |
| `AUTH_FRONTEND_URL`     | `http://localhost:5173`                             | Frontend URL used by auth redirects. In prod (single port) set to the backend URL (e.g. `http://your-server:8000`). In dev set to the Vite dev-server URL — must match `FRONTEND_PORT` (default `http://localhost:3000`). |
| `SESSION_MAX_AGE_DAYS`  | `30`                                                | Session lifetime in days.                                                                                                                                                                                                 |
| `TRUSTED_PROXY_HOPS`    | `0`                                                 | Number of trusted reverse proxies in front of the app. `0` means ignore `X-Forwarded-For` and use the direct client socket.                                                                                           |
| `GOOGLE_CLIENT_ID`      | empty                                               | Google OAuth client id.                                                                                                                                                                                                   |
| `GOOGLE_CLIENT_SECRET`  | empty                                               | Google OAuth client secret.                                                                                                                                                                                               |
| `GOOGLE_REDIRECT_URI`   | `http://localhost:8000/api/v1/auth/google/callback` | Google OAuth callback.                                                                                                                                                                                                    |
| `GITHUB_CLIENT_ID`      | empty                                               | GitHub OAuth client id.                                                                                                                                                                                                   |
| `GITHUB_CLIENT_SECRET`  | empty                                               | GitHub OAuth client secret.                                                                                                                                                                                               |
| `GITHUB_REDIRECT_URI`   | `http://localhost:8000/api/v1/auth/github/callback` | GitHub OAuth callback.                                                                                                                                                                                                    |

## Frontend dev-server variables

> **Development only.** These configure the Vite dev server and its proxy.
> They live in `packages/shared/dev.env` alongside the backend variables. `just dev`
> sources that file so both processes share the same configuration.
> In production the Vite dev server is not running, so none of these have any
> effect on the deployed application.

| Variable        | Default     | Notes                                                   |
| --------------- | ----------- | ------------------------------------------------------- |
| `FRONTEND_PORT` | `3000`      | Local Vite dev-server port.  Must match `AUTH_FRONTEND_URL`. |
| `BACKEND_HOST`  | `127.0.0.1` | Backend hostname used by the Vite proxy (Bun/Vite only, not exposed to browser code). |
| `BACKEND_PORT`  | `PORT`      | Backend port used by the Vite proxy. Defaults to `PORT` when unset. |

## Test and tooling variables

| Variable         | Default | Notes                                |
| ---------------- | ------- | ------------------------------------ |
| `PW_E2E_WORKERS` | auto    | Optional Playwright worker override. |

## Recommended additions to consider later

These are **not implemented yet**, but they are reasonable future env-driven enhancements if you want more operational control:

- Rate limiting (`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_BURST`)
- Retention / cleanup (`DATA_RETENTION_DAYS`, `AUTO_CLEANUP_ENABLED`)
- Response caching (`CACHE_TTL_SECONDS`, `CACHE_MAX_SIZE_MB`)
- Alerting (`ERROR_ALERT_EMAIL`, `ENABLE_ERROR_NOTIFICATIONS`)
- Feature flags for experimental UI modules
