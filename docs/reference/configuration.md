# Configuration Reference

Complete reference for environment variables and application settings.

## Backend Configuration

The backend uses Pydantic Settings for type-safe configuration management with environment variable support.

### Settings Class

Located in `backend/core/config.py`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )

    app_name: str = 'Polars-FastAPI-Svelte Analysis Platform'
    app_version: str = '1.0.0'
    debug: bool = False
    cors_origins: str = 'http://localhost:3000,...'
    database_url: str = 'sqlite+aiosqlite:///./database/app.db'
    upload_dir: Path = Path('./data/uploads')
    results_dir: Path = Path('./data/results')
    exports_dir: Path = Path('./data/exports')
    max_upload_size: int = 10 * 1024 * 1024 * 1024  # 10GB
    compute_timeout: int = 300  # 5 minutes
    job_ttl: int = 3600  # 1 hour
```

## Environment Variables

### Application Settings

| Variable      | Type    | Default                                   | Description                                                             |
| ------------- | ------- | ----------------------------------------- | ----------------------------------------------------------------------- |
| `app_name`    | string  | `Polars-FastAPI-Svelte Analysis Platform` | Application display name shown in FastAPI docs                          |
| `app_version` | string  | `1.0.0`                                   | Application version displayed in API                                    |
| `debug`       | boolean | `false`                                   | Enable debug mode (SQL echo, verbose logging, detailed error responses) |

### Database

| Variable       | Type   | Default                                 | Description                        |
| -------------- | ------ | --------------------------------------- | ---------------------------------- |
| `DATABASE_URL` | string | `sqlite+aiosqlite:///./database/app.db` | SQLAlchemy async connection string |

#### Supported Database URLs

```bash
# SQLite (default)
DATABASE_URL=sqlite+aiosqlite:///./database/app.db

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dbname

# MySQL
DATABASE_URL=mysql+aiomysql://user:pass@localhost:3306/dbname
```

### CORS Configuration

| Variable       | Type   | Default                                                                                                               | Description                          |
| -------------- | ------ | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| `cors_origins` | string | `http://localhost:3000,http://127.0.0.1:3000,http://0.0.0.0:3000,http://192.168.1.140:3000,http://100.68.183.19:3000` | Comma-separated allowed CORS origins |

Default origins include:

- `http://localhost:3000`
- `http://127.0.0.1:3000`
- `http://0.0.0.0:3000`
- `http://192.168.1.140:3000`
- `http://100.68.183.19:3000`

#### Example

```bash
# Single origin
cors_origins=http://localhost:3000

# Multiple origins
cors_origins=http://localhost:3000,https://app.example.com

# Access via property in code
settings.cors_origins_list  # Returns ['http://localhost:3000', 'https://app.example.com']
```

#### Usage in Code

Located in `backend/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### File Storage

| Variable          | Type   | Default                       | Description                                            |
| ----------------- | ------ | ----------------------------- | ------------------------------------------------------ |
| `upload_dir`      | string | `{project_root}/data/uploads` | Directory for uploaded CSV/data files                  |
| `results_dir`     | string | `{project_root}/data/results` | Directory for computation results and analysis outputs |
| `exports_dir`     | string | `{project_root}/data/exports` | Directory for exported data files                      |
| `max_upload_size` | integer | `10737418240` (10GB)          | Maximum file upload size in bytes                      |

#### Details

- **Fully configurable via environment variables** - Set via `upload_dir`, `results_dir`, `exports_dir`, `max_upload_size` in `.env` or system environment
- All directories are created automatically on startup if they don't exist
- Paths support both relative and absolute paths
- If not set via environment variables, defaults to `{project_root}/data/{subdirectory}` where project_root is computed from config.py location
- Used in:
  - `upload_dir`: `backend/modules/datasource/routes.py` - File uploads
  - `results_dir`: `backend/modules/results/service.py` - Analysis results storage
  - `exports_dir`: `backend/modules/compute/routes.py` - Export operations

#### Example

```bash
# Use custom directories
upload_dir=/var/app/uploads
results_dir=/var/app/results
exports_dir=/var/app/exports

# Increase max upload size to 50GB
max_upload_size=53687091200
```

### Compute Engine

| Variable          | Type    | Default           | Description                                                |
| ----------------- | ------- | ----------------- | ---------------------------------------------------------- |
| `compute_timeout` | integer | `300` (5 minutes) | Maximum time allowed for pipeline execution (seconds)      |
| `job_ttl`         | integer | `3600` (1 hour)   | Job result retention time-to-live before cleanup (seconds) |

#### Details

- **Fully configurable via environment variables** - Set via `compute_timeout`, `job_ttl` in `.env` or system environment
- `compute_timeout`: Used to prevent long-running operations from consuming resources indefinitely
- `job_ttl`: Used in `backend/modules/compute/service.py` for automatic job cleanup
- Jobs older than `job_ttl` seconds are automatically cleaned up from the system
- If not set via environment variables, uses default values shown above

#### Example

```bash
# Extend timeout for long-running pipelines (10 minutes)
compute_timeout=600

# Keep job results for 2 hours
job_ttl=7200
```

## Frontend Configuration

### Vite Environment Variables

Frontend uses Vite's environment variable system with the `VITE_` prefix convention.

#### Configuration File

Located in `frontend/.env.example` and used in `frontend/src/lib/api/client.ts`:

| Variable       | Type   | Default | Description                                                                 |
| -------------- | ------ | ------- | --------------------------------------------------------------------------- |
| `VITE_API_URL` | string | (empty) | API base URL for production builds (empty = use dev proxy or relative URLs) |

#### How It Works

In `frontend/src/lib/api/client.ts`:

```typescript
const apiEnv = import.meta.env.VITE_API_URL?.trim();
export const BASE_URL = import.meta.env.DEV ? "" : apiEnv || runtimeBase;
```

- **Development**: Empty `VITE_API_URL` uses Vite dev proxy (relative URLs, routes to `localhost:8000`)
- **Production**: Requires explicit `VITE_API_URL` pointing to the API endpoint

#### Built-in Variables

| Variable              | Type    | Default | Description                                                   |
| --------------------- | ------- | ------- | ------------------------------------------------------------- |
| `import.meta.env.DEV` | boolean | (auto)  | Built-in Vite variable, true in dev mode, false in production |

#### Development vs Production

```bash
# Development (.env or .env.development)
# Empty - uses Vite dev proxy at localhost:8000
VITE_API_URL=

# Production (.env.production)
# Point to actual API endpoint
VITE_API_URL=https://api.example.com
```

### Vite Dev Server Proxy

In `frontend/vite.config.ts`, the dev server proxies `/api` routes:

```typescript
export default defineConfig({
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
```

This allows development without setting `VITE_API_URL`.

## Docker Configuration

### Environment File (.env.docker)

```bash
# Backend
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/app
CORS_ORIGINS=http://localhost:3000
DEBUG=false
UPLOAD_DIR=/app/data/uploads
RESULTS_DIR=/app/data/results
COMPUTE_TIMEOUT=600
JOB_TTL=7200

# Frontend
VITE_API_URL=http://api:8000
```

### Docker Compose

```yaml
services:
  api:
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - CORS_ORIGINS=${CORS_ORIGINS}
      - DEBUG=${DEBUG}
    volumes:
      - uploads:/app/data/uploads
      - results:/app/data/results

  frontend:
    environment:
      - VITE_API_URL=${VITE_API_URL}
```

## Configuration Precedence

### Backend (Pydantic Settings)

Settings are loaded in this order (later overrides earlier):

1. Default values in `Settings` class (defined in `backend/core/config.py`)
2. `.env` file in backend directory (if present)
3. System environment variables
4. Explicit constructor arguments (highest priority)

The Pydantic `SettingsConfigDict` specifies:

- Load from `.env` file: `env_file='.env'`
- Encoding: `env_file_encoding='utf-8'`
- Extra fields ignored: `extra='ignore'`

### Frontend (Vite)

Vite environment variables are resolved in this order:

1. `.env.{mode}.local` file (highest priority, git-ignored)
2. `.env.{mode}` file (mode = dev or production)
3. `.env.local` file (git-ignored)
4. `.env` file (lowest priority)
5. Built-in variables like `import.meta.env.DEV`

Where `{mode}` is determined by Vite build command (`dev` or `production`).

## Computed Properties

### `cors_origins_list`

Parses the comma-separated `cors_origins` string into a list:

```python
settings = Settings()
origins = settings.cors_origins_list
# ['http://localhost:3000', 'http://127.0.0.1:3000', ...]
```

## Debug Mode

When `debug=true`:

- SQL queries are echoed to console
- Verbose logging is enabled
- Stack traces shown in API responses
- Hot reload enabled

```bash
# Enable debug mode
DEBUG=true

# In Python
if settings.debug:
    logger.setLevel(logging.DEBUG)
```

## Example .env Files

### Backend Development (.env)

```bash
# Application
app_name=Polars-FastAPI-Svelte Analysis Platform
app_version=1.0.0

# Database
database_url=sqlite+aiosqlite:///./database/app.db

# Debug
debug=true

# CORS (frontend dev server)
cors_origins=http://localhost:3000,http://127.0.0.1:3000

# Compute
compute_timeout=300
job_ttl=3600

# Storage
upload_dir=./data/uploads
results_dir=./data/results
exports_dir=./data/exports
max_upload_size=10737418240
```

### Frontend Development (.env)

```bash
# Empty for dev proxy, or set explicit URL
VITE_API_URL=
```

### Production (.env.production)

```bash
# Application
app_name=Polars-FastAPI-Svelte Analysis Platform
app_version=1.0.0

# Database
database_url=postgresql+asyncpg://user:secure_password@db.example.com:5432/production

# Security
debug=false
cors_origins=https://app.example.com

# Extended timeouts for production workloads
compute_timeout=600
job_ttl=86400

# Persistent storage
upload_dir=/var/app/uploads
results_dir=/var/app/results
exports_dir=/var/app/exports
max_upload_size=10737418240
```

## Complete Environment Variables Reference

### All Backend Variables

| Variable          | Type    | Default                                                                                                               | Used In                                                       | Required |
| ----------------- | ------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | -------- |
| `app_name`        | string  | `Polars-FastAPI-Svelte Analysis Platform`                                                                             | `backend/main.py`                                             | No       |
| `app_version`     | string  | `1.0.0`                                                                                                               | `backend/main.py`                                             | No       |
| `debug`           | boolean | `false`                                                                                                               | `backend/main.py`, `backend/core/database.py`                 | No       |
| `cors_origins`    | string  | `http://localhost:3000,http://127.0.0.1:3000,http://0.0.0.0:3000,http://192.168.1.140:3000,http://100.68.183.19:3000` | `backend/main.py`                                             | No       |
| `database_url`    | string  | `sqlite+aiosqlite:///./database/app.db`                                                                               | `backend/core/database.py`, `backend/database/alembic/env.py` | No       |
| `upload_dir`      | Path    | `{project_root}/data/uploads`                                                                                         | `backend/modules/datasource/routes.py`                        | No       |
| `results_dir`     | Path    | `{project_root}/data/results`                                                                                         | `backend/modules/results/service.py`                          | No       |
| `exports_dir`     | Path    | `{project_root}/data/exports`                                                                                         | `backend/modules/compute/routes.py`                           | No       |
| `max_upload_size` | integer | `10737418240` (10GB)                                                                                                  | Configuration only                                            | No       |
| `compute_timeout` | integer | `300` (5 minutes)                                                                                                     | `backend/modules/compute/service.py`                          | No       |
| `job_ttl`         | integer | `3600` (1 hour)                                                                                                       | `backend/modules/compute/service.py`                          | No       |

### All Frontend Variables

| Variable       | Type   | Default | Used In                          | Required                                     |
| -------------- | ------ | ------- | -------------------------------- | -------------------------------------------- |
| `VITE_API_URL` | string | (empty) | `frontend/src/lib/api/client.ts` | No (optional in dev, required in production) |

### Built-in Vite Variables

| Variable               | Type    | Set By | Purpose                                       |
| ---------------------- | ------- | ------ | --------------------------------------------- |
| `import.meta.env.DEV`  | boolean | Vite   | True in development mode, false in production |
| `import.meta.env.PROD` | boolean | Vite   | True in production mode, false in development |
| `import.meta.env.SSR`  | boolean | Vite   | True if running in SSR context                |

## Quick Setup Guide

### Minimal Development Setup

For the quickest start with defaults:

**Backend**: No configuration needed, uses SQLite and defaults

**Frontend**: No configuration needed, uses Vite dev proxy

### Local Multi-Machine Development

If running frontend and backend on different machines:

**Backend `.env`**:

```bash
debug=true
cors_origins=http://<frontend-machine-ip>:3000
```

**Frontend `.env`**:

```bash
VITE_API_URL=http://<backend-machine-ip>:8000
```

### Docker Deployment

**Backend**: Set all variables in docker-compose or Dockerfile

```bash
database_url=postgresql+asyncpg://user:pass@db:5432/app
debug=false
```

**Frontend**: Build with:

```bash
VITE_API_URL=https://api.example.com npm run build
```

## See Also

- [Getting Started](../guides/getting-started.md) - Initial setup
- [Development Workflow](../guides/development-workflow.md) - Development configuration
- [Backend Documentation](../backend/README.md) - Backend architecture
