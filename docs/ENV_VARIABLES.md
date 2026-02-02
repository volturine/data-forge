# Complete Environment Variable Reference

This document lists ALL environment variables supported by the application.

## Quick Reference

| Variable                      | Type    | Default                                 | Description                                          |
| ----------------------------- | ------- | --------------------------------------- | ---------------------------------------------------- |
| **Application**               |         |                                         |                                                      |
| `APP_NAME`                    | string  | Polars-FastAPI-Svelte Analysis Platform | Application name                                     |
| `APP_VERSION`                 | string  | 1.0.0                                   | Application version                                  |
| `DEBUG`                       | boolean | false                                   | Enable debug mode (verbose logging, SQL echo)        |
| `PORT`                        | integer | 8000                                    | Port to bind (Docker only)                           |
| **Database**                  |         |                                         |                                                      |
| `DATABASE_URL`                | string  | sqlite+aiosqlite:///./database/app.db   | Database connection URL                              |
| **CORS**                      |         |                                         |                                                      |
| `CORS_ORIGINS`                | string  | localhost:3000,...                      | Comma-separated allowed origins                      |
| **File Storage**              |         |                                         |                                                      |
| `UPLOAD_DIR`                  | path    | /app/data/uploads                       | Upload directory path                                |
| `CLEAN_DIR`                   | path    | /app/data/clean                         | Results directory path                               |
| `EXPORTS_DIR`                 | path    | /app/data/exports                       | Exports directory path                               |
| `MAX_UPLOAD_SIZE`             | integer | 10737418240                             | Max upload size in bytes (10GB)                      |
| **Polars Engine**             |         |                                         |                                                      |
| `POLARS_MAX_THREADS`          | integer | 0                                       | Max threads per engine (0=auto)                      |
| `POLARS_MAX_MEMORY_MB`        | integer | 0                                       | Memory limit per engine MB (0=unlimited)             |
| `POLARS_STREAMING_CHUNK_SIZE` | integer | 0                                       | Streaming chunk size (0=auto)                        |
| `MAX_CONCURRENT_ENGINES`      | integer | 10                                      | Max simultaneous engines (1-100)                     |
| **Workers**                   |         |                                         |                                                      |
| `WORKERS`                     | integer | 1                                       | Gunicorn/Uvicorn workers (0=auto: 2\*cores+1)        |
| `WORKER_CONNECTIONS`          | integer | 1000                                    | Max connections per worker                           |
| **Engine Lifecycle**          |         |                                         |                                                      |
| `ENGINE_IDLE_TIMEOUT`         | integer | 300                                     | Idle timeout before cleanup (seconds, reset on save) |
| `ENGINE_POOLING_INTERVAL`     | integer | 5                                       | Polling interval to check engine states (seconds)    |
| **Job Management**            |         |                                         |                                                      |
| `JOB_TIMEOUT`                 | integer | 300                                     | Max job execution time (seconds)                     |
| **Logging**                   |         |                                         |                                                      |
| `LOG_LEVEL`                   | string  | info                                    | Log level (debug/info/warning/error/critical)        |

## Validation Rules

### Integer Ranges

- `MAX_CONCURRENT_ENGINES`: 1-100
- `WORKERS`: 0-32
- `MAX_UPLOAD_SIZE`: ≥1024 bytes

### Positive Values Required

- `ENGINE_IDLE_TIMEOUT` > 0
- `JOB_TIMEOUT` > 0
- `ENGINE_POOLING_INTERVAL` > 0

### Non-Negative Values

- `POLARS_MAX_THREADS` ≥ 0 (0 = auto)
- `POLARS_MAX_MEMORY_MB` ≥ 0 (0 = unlimited)
- `POLARS_STREAMING_CHUNK_SIZE` ≥ 0 (0 = auto)

### String Enums

- `LOG_LEVEL`: Must be one of: debug, info, warning, error, critical

## Configuration by Environment

### Development (Local)

```bash
DEBUG=true
LOG_LEVEL=debug
WORKERS=1
POLARS_MAX_THREADS=4
MAX_CONCURRENT_ENGINES=3
UPLOAD_DIR=./data/uploads
CLEAN_DIR=./data/results
EXPORTS_DIR=./data/exports
```

### Development (Docker)

```bash
DEBUG=true
LOG_LEVEL=debug
WORKERS=1
POLARS_MAX_THREADS=4
MAX_CONCURRENT_ENGINES=3
UPLOAD_DIR=/app/data/uploads
CLEAN_DIR=/app/data/clean
EXPORTS_DIR=/app/data/exports
```

### Production (Small Server - 2 cores, 4GB)

```bash
DEBUG=false
LOG_LEVEL=info
WORKERS=2
WORKER_CONNECTIONS=1000
POLARS_MAX_THREADS=1
POLARS_MAX_MEMORY_MB=1024
MAX_CONCURRENT_ENGINES=3
UPLOAD_DIR=/app/data/uploads
CLEAN_DIR=/app/data/clean
EXPORTS_DIR=/app/data/exports
```

### Production (Medium Server - 4 cores, 8GB)

```bash
DEBUG=false
LOG_LEVEL=info
WORKERS=4
WORKER_CONNECTIONS=1000
POLARS_MAX_THREADS=2
POLARS_MAX_MEMORY_MB=2048
MAX_CONCURRENT_ENGINES=5
UPLOAD_DIR=/app/data/uploads
CLEAN_DIR=/app/data/clean
EXPORTS_DIR=/app/data/exports
```

### Production (Large Server - 8+ cores, 16+ GB)

```bash
DEBUG=false
LOG_LEVEL=info
WORKERS=8
WORKER_CONNECTIONS=1000
POLARS_MAX_THREADS=4
POLARS_MAX_MEMORY_MB=4096
MAX_CONCURRENT_ENGINES=10
UPLOAD_DIR=/app/data/uploads
CLEAN_DIR=/app/data/clean
EXPORTS_DIR=/app/data/exports
```

## Database Configuration Examples

### SQLite (Default)

```bash
DATABASE_URL="sqlite+aiosqlite:///./database/app.db"
```

### PostgreSQL

```bash
DATABASE_URL="postgresql+asyncpg://username:password@hostname:5432/database"
```

### PostgreSQL with Docker Compose

```bash
# In docker-compose.yml, add postgres service
DATABASE_URL="postgresql+asyncpg://polars:secretpass@postgres:5432/polars_db"
```

## CORS Configuration

### Development

```bash
CORS_ORIGINS="http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000"
```

### Production

```bash
CORS_ORIGINS="https://yourdomain.com,https://www.yourdomain.com"
```

### Allow All (NOT RECOMMENDED for production)

```bash
CORS_ORIGINS="*"
```

## Resource Planning Formulas

### CPU Calculation

```
Total CPU Cores Needed = WORKERS + (MAX_CONCURRENT_ENGINES × POLARS_MAX_THREADS)
```

**Example**: 8-core server

- WORKERS=4
- MAX_CONCURRENT_ENGINES=5
- POLARS_MAX_THREADS=1
- Total: 4 + (5 × 1) = 9 cores (slight over-subscription is OK)

### Memory Calculation

```
Total Memory = System (2GB) + Workers (500MB × WORKERS) + (MAX_CONCURRENT_ENGINES × POLARS_MAX_MEMORY_MB)
```

**Example**: 16GB server

- System: 2GB
- Workers: 4 × 500MB = 2GB
- Engines: 5 × 2048MB = 10GB
- Total: 14GB (leaving 2GB buffer)

## Special Notes

### Directory Paths

- **Local Development**: Use relative paths like `./data/uploads`
- **Docker**: Use absolute container paths like `/app/data/uploads`
- Directories are automatically created if they don't exist
- Must be writable by the application user

### Worker Auto-Configuration

When `WORKERS=0`:

```python
workers = (2 * cpu_cores) + 1
```

Example on 4-core machine: `workers = (2 * 4) + 1 = 9`

### Polars Auto-Configuration

When `POLARS_MAX_THREADS=0`:

- Uses all available CPU cores
- May cause contention with workers
- Recommended to set explicitly in production

### Memory Management

- Set `POLARS_MAX_MEMORY_MB` to prevent OOM
- Leave 2GB for system overhead
- Leave 500MB per worker
- Distribute remaining memory to engines

## Environment Variable Priority

1. **Environment Variables** (highest priority)
2. **`.env` file** in backend directory
3. **Default values** in code (lowest priority)

## Debugging Configuration Issues

### Check Current Configuration

```bash
# In Python shell
from core.config import settings
print(settings.model_dump())
```

### Validate Configuration

Configuration is validated on startup. Invalid values will cause the application to fail with a clear error message.

### Common Issues

1. **Directory not writable**: Ensure proper permissions
2. **Invalid log level**: Must be one of: debug, info, warning, error, critical
3. **Out of range values**: Check validation rules above
4. **Path issues**: Use absolute paths in Docker, relative in local dev

## See Also

- `.env.example` - Template with defaults
- `backend/.env.example` - Backend-specific template
- `DEPLOYMENT.md` - Deployment guide
- `docker-compose.yml` - Docker configuration
