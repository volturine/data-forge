# Backend Core Infrastructure

**Parallel Group**: Backend Foundation
**Dependencies**: None (start first)
**Blocks**: All other backend modules

## Relevant Files

- `backend/core/config.py` - Application configuration and settings
- `backend/core/database.py` - Async SQLAlchemy database setup
- `backend/core/__init__.py` - Core module exports
- `database/alembic.ini` - Alembic configuration
- `database/alembic/env.py` - Alembic environment setup
- `database/alembic/versions/` - Migration scripts directory

## Tasks

- [x] 1.0 Setup Backend Core Infrastructure
  - [x] 1.1 Create `backend/core/config.py` with application settings:
    - [x] 1.1.1 Define Settings class with Pydantic BaseSettings
    - [x] 1.1.2 Add DATABASE_URL (default: sqlite+aiosqlite:///./data/app.db)
    - [x] 1.1.3 Add UPLOAD_DIR (default: ./data/uploads)
    - [x] 1.1.4 Add RESULTS_DIR (default: ./data/results)
    - [x] 1.1.5 Add COMPUTE_TIMEOUT (default: 300 seconds)
    - [x] 1.1.6 Add MAX_UPLOAD_SIZE (default: 10GB)
    - [x] 1.1.7 Export settings singleton instance
  - [x] 1.2 Create `backend/core/database.py` with async SQLAlchemy:
    - [x] 1.2.1 Create async engine with create_async_engine()
    - [x] 1.2.2 Create async_sessionmaker for session management
    - [x] 1.2.3 Create Base declarative class for models
    - [x] 1.2.4 Create get_db() async dependency for FastAPI
    - [x] 1.2.5 Create init_db() function to create tables
  - [x] 1.3 Add required dependencies to `backend/pyproject.toml`:
    - [x] 1.3.1 Add polars
    - [x] 1.3.2 Add sqlalchemy[asyncio]
    - [x] 1.3.3 Add aiosqlite
    - [x] 1.3.4 Add alembic
    - [x] 1.3.5 Add python-multipart (for file uploads)
  - [x] 1.4 Setup Alembic for database migrations:
    - [x] 1.4.1 Run `alembic init database/alembic`
    - [x] 1.4.2 Configure `database/alembic.ini` with SQLite URL
    - [x] 1.4.3 Update `database/alembic/env.py` for async support
    - [x] 1.4.4 Import all models in env.py for autogenerate
  - [x] 1.5 Create initial migration with all tables:
    - [x] 1.5.1 Create `analyses` table (id, name, description, pipeline_definition, status, created_at, updated_at, result_path, thumbnail)
    - [x] 1.5.2 Create `datasources` table (id, name, source_type, config, schema_cache, created_at)
    - [x] 1.5.3 Create `analysis_datasources` junction table (analysis_id, datasource_id)
    - [x] 1.5.4 Create `compute_jobs` table (id, analysis_id, status, progress, current_step, error_message, process_id, started_at, completed_at) - NOT NEEDED (status tracked in Analysis model)
    - [x] 1.5.5 Run migration with `alembic upgrade head`
  - [x] 1.6 Update `backend/main.py`:
    - [x] 1.6.1 Add lifespan context manager for startup/shutdown
    - [x] 1.6.2 Initialize database on startup
    - [x] 1.6.3 Create upload and results directories on startup (implemented in config.py)
  - [x] 1.7 Create `backend/core/__init__.py`:
    - [x] 1.7.1 Export settings
    - [x] 1.7.2 Export get_db dependency
    - [x] 1.7.3 Export Base class
    - [x] 1.7.4 Export init_db function

## Completion Criteria

- [x] All dependencies installed successfully (`uv sync`)
- [x] Database migrations run without errors
- [x] Application starts with `just dev` without errors
- [x] Database file created in `data/app.db`
- [x] Upload and results directories created

**Completion: 100%**
