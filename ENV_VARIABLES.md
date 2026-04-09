# Environment Variables

This project uses environment variables for three different layers:

1. **Backend runtime** — loaded by `/home/runner/work/polars-fastapi-svelte/polars-fastapi-svelte/backend/core/config.py`
2. **Frontend dev server** — loaded by Vite from `/home/runner/work/polars-fastapi-svelte/polars-fastapi-svelte/frontend/.env*`
3. **Local e2e tooling** — optional overrides for Playwright

## What to configure first

If you only want the high-value knobs, start with these:

- `DATA_DIR` — where app data, SQLite state, and logs live
- `PORT` — backend port
- `CORS_ORIGINS` — allowed browser origins
- `AUTH_REQUIRED` — turn login on/off
- `SETTINGS_ENCRYPTION_KEY` — strongly recommended when auth is enabled
- `POLARS_MAX_THREADS`, `POLARS_MAX_MEMORY_MB`, `MAX_CONCURRENT_ENGINES` — performance limits
- `VITE_BACKEND_HOST`, `VITE_BACKEND_PORT`, `FRONTEND_PORT` — frontend local-dev wiring

## How configuration is loaded

### Backend

- `Settings()` reads process environment first, then an env file.
- `ENV_FILE` chooses the env file path. Default: `.env`.
- Set `ENV_FILE` to an empty value only if you want to rely on process env alone.
- `DATABASE_URL` currently exists as a setting, but the backend recomputes the SQLite URL from `DATA_DIR` on startup.
- Some values such as SMTP and provider defaults are **seeded into the database once**. After the UI saves a value, the database value wins until it is cleared.

### Frontend

- Vite reads `frontend/.env`, `frontend/.env.local`, and shell env vars.
- Only variables prefixed with `VITE_` are exposed to browser code.
- `FRONTEND_PORT` is used by Vite/Playwright tooling and does not go into browser code.

## Setup examples

### Backend local development

```bash
cd backend
cp .env.example .env
```

### Docker / compose from the repository root

```bash
cp .env.example .env
```

### Frontend local development

```bash
cd frontend
cp .env.example .env
```

## Backend variables

### Application and files

| Variable | Default | Notes |
| --- | --- | --- |
| `ENV_FILE` | `.env` | Path to the backend env file. |
| `APP_NAME` | `Data-Forge Analysis Platform` | Application name for UI/logging metadata. |
| `APP_VERSION` | `1.0.0` | Application version string. |
| `DEBUG` | `false` | Enables verbose/debug behavior. |
| `PROD_MODE_ENABLED` | `false` | Production mode toggle used by deployment paths. |
| `PORT` | `8000` | Backend HTTP port. |
| `DATA_DIR` | system temp dir + `/data-forge` | Base writable directory for app data. |
| `DATABASE_URL` | derived from `DATA_DIR` | Present for compatibility, but current code rebuilds the SQLite URL from `DATA_DIR`. |
| `DEFAULT_NAMESPACE` | `default` | Namespace used when no namespace is selected. |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed browser origins. |
| `UPLOAD_CHUNK_SIZE` | `5242880` | Upload chunk size in bytes. Valid range: `1024` to `104857600`. |
| `UPLOAD_MAX_FILE_SIZE_BYTES` | `2147483648` | Maximum upload size in bytes. |

### Engine, scheduling, and resource limits

| Variable | Default | Notes |
| --- | --- | --- |
| `ENGINE_IDLE_TIMEOUT` | `60` | Seconds before idle engines are cleaned up. |
| `ENGINE_POOLING_INTERVAL` | `30` | Seconds between idle-engine cleanup passes. |
| `SCHEDULER_CHECK_INTERVAL` | `60` | Seconds between scheduler polls. |
| `JOB_TIMEOUT` | `300` | Maximum job runtime in seconds. |
| `LOCK_TTL_SECONDS` | `30` | Lock lease duration. |
| `LOCK_HEARTBEAT_INTERVAL_SECONDS` | `10` | Must stay lower than `LOCK_TTL_SECONDS`. |
| `POLARS_MAX_THREADS` | `0` | `0` means auto-detect. |
| `POLARS_MAX_MEMORY_MB` | `0` | `0` means unlimited. |
| `POLARS_STREAMING_CHUNK_SIZE` | `0` | `0` means automatic chunk sizing. |
| `MAX_CONCURRENT_ENGINES` | `10` | Valid range: `1` to `100`. |
| `WORKERS` | `1` | Valid range: `0` to `32`; `0` means auto in deployment scripts. |
| `WORKER_CONNECTIONS` | `1000` | Maximum connections per worker. |

### Logging and time handling

| Variable | Default | Notes |
| --- | --- | --- |
| `LOG_LEVEL` | `info` | One of `debug`, `info`, `warning`, `error`, `critical`. |
| `UVICORN_ACCESS_LOG` | `true` | Enables uvicorn access logs. |
| `TIMEZONE` | `UTC` | Must be a valid IANA timezone. |
| `NORMALIZE_TZ` | `false` | Normalizes datetime values to `TIMEZONE`. |
| `LOG_CLIENT_BATCH_SIZE` | `20` | Client audit batch size. |
| `LOG_CLIENT_FLUSH_INTERVAL_MS` | `5000` | Client audit flush interval. |
| `LOG_CLIENT_DEDUPE_WINDOW_MS` | `500` | Dedupe window for repeated client events. |
| `LOG_CLIENT_FLUSH_COOLDOWN_MS` | `3000` | Cooldown before repeating client flush-failure logs. |
| `LOG_SQLITE_PATH` | `${DATA_DIR}/logs` | Directory for SQLite-backed logs. Leave blank to use the default under `DATA_DIR`. |
| `LOG_SQLITE_FLUSH_INTERVAL_SECONDS` | `5` | Flush interval for SQLite logs. |
| `LOG_QUEUE_MAX_SIZE` | `2000` | Max queued log batches. |
| `LOG_QUEUE_OVERFLOW` | `drop` | One of `block` or `drop`. |
| `LOG_MAX_BODY_SIZE` | `65536` | Max request/response body bytes to log. `0` means unlimited. |
| `PUBLIC_IDB_DEBUG` | `false` | Enables IndexedDB debug panels in the frontend. |

### AI and provider settings

| Variable | Default | Notes |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Base URL for Ollama. |
| `OLLAMA_DEFAULT_MODEL` | `llama3.2` | Default Ollama chat model. |
| `OPENAI_API_KEY` | empty | OpenAI API key. |
| `OPENAI_BASE_URL` | `https://api.openai.com` | OpenAI-compatible API base URL. |
| `OPENAI_DEFAULT_MODEL` | `gpt-4o-mini` | Default OpenAI model. |
| `OPENAI_ORGANIZATION_ID` | empty | Optional OpenAI org id. |
| `HUGGINGFACE_API_TOKEN` | empty | Hugging Face token. |
| `HUGGINGFACE_DEFAULT_MODEL` | `google/flan-t5-base` | Default Hugging Face model. |
| `HUGGINGFACE_API_BASE_URL` | `https://api-inference.huggingface.co` | Hugging Face inference base URL. |
| `OPENROUTER_API_KEY` | empty | Seeded into DB on first run if DB field is empty. |
| `OPENROUTER_DEFAULT_MODEL` | empty | Seeded into DB on first run if DB field is empty. |
| `OPENAI_DEFAULT_MODEL_DB` | empty | DB-seeded default model override. |
| `OPENAI_ENDPOINT_URL_DB` | empty | DB-seeded endpoint override. |
| `OPENAI_ORGANIZATION_ID_DB` | empty | DB-seeded organization override. |
| `OLLAMA_ENDPOINT_URL_DB` | empty | DB-seeded Ollama endpoint override. |
| `OLLAMA_DEFAULT_MODEL_DB` | empty | DB-seeded Ollama model override. |
| `HUGGINGFACE_DEFAULT_MODEL_DB` | empty | DB-seeded Hugging Face model override. |

### Notifications and encrypted settings

| Variable | Default | Notes |
| --- | --- | --- |
| `SETTINGS_ENCRYPTION_KEY` | empty | Strongly recommended in production when `AUTH_REQUIRED=true`; secrets stay unencrypted otherwise. |
| `SMTP_HOST` | empty | DB-seeded SMTP host. |
| `SMTP_PORT` | `587` | DB-seeded SMTP port. |
| `SMTP_USER` | empty | DB-seeded SMTP username. |
| `SMTP_PASSWORD` | empty | DB-seeded SMTP password. |
| `TELEGRAM_BOT_TOKEN` | empty | DB-seeded Telegram token. |
| `TELEGRAM_BOT_ENABLED` | `false` | DB-seeded Telegram enable flag. |

### Authentication and OAuth

| Variable | Default | Notes |
| --- | --- | --- |
| `AUTH_REQUIRED` | `false` | Enables authenticated routes. |
| `DEFAULT_USER_EMAIL` | `default@example.com` | Default env-managed account email. |
| `DEFAULT_USER_PASSWORD` | `ChangeMe123` | Must contain upper, lower, and digit, and be at least 8 chars. |
| `DEFAULT_USER_NAME` | `Default User` | Default env-managed account name. |
| `AUTH_FRONTEND_URL` | `http://localhost:5173` | Frontend URL used by auth redirects. |
| `SESSION_MAX_AGE_DAYS` | `30` | Session lifetime in days. |
| `GOOGLE_CLIENT_ID` | empty | Google OAuth client id. |
| `GOOGLE_CLIENT_SECRET` | empty | Google OAuth client secret. |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/auth/google/callback` | Google OAuth callback. |
| `GITHUB_CLIENT_ID` | empty | GitHub OAuth client id. |
| `GITHUB_CLIENT_SECRET` | empty | GitHub OAuth client secret. |
| `GITHUB_REDIRECT_URI` | `http://localhost:8000/api/v1/auth/github/callback` | GitHub OAuth callback. |

## Frontend variables

| Variable | Default | Notes |
| --- | --- | --- |
| `FRONTEND_PORT` | `3000` | Local Vite dev-server port. |
| `VITE_BACKEND_HOST` | `127.0.0.1` | Backend hostname used by the Vite proxy and direct dev websockets. |
| `VITE_BACKEND_PORT` | `8000` | Backend port used by the Vite proxy and direct dev websockets. |

## Test and tooling variables

| Variable | Default | Notes |
| --- | --- | --- |
| `PW_E2E_WORKERS` | auto | Optional Playwright worker override. |

## Recommended additions to consider later

These are **not implemented yet**, but they are reasonable future env-driven enhancements if you want more operational control:

- Rate limiting (`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_BURST`)
- Retention / cleanup (`DATA_RETENTION_DAYS`, `AUTO_CLEANUP_ENABLED`)
- Response caching (`CACHE_TTL_SECONDS`, `CACHE_MAX_SIZE_MB`)
- Alerting (`ERROR_ALERT_EMAIL`, `ENABLE_ERROR_NOTIFICATIONS`)
- Feature flags for experimental UI modules
