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

- [ ] 1.0 Setup Backend Core Infrastructure
  - [ ] 1.1 Create `backend/core/config.py` with application settings:
    - [ ] 1.1.1 Define Settings class with Pydantic BaseSettings
    - [ ] 1.1.2 Add DATABASE_URL (default: sqlite+aiosqlite:///./data/app.db)
    - [ ] 1.1.3 Add UPLOAD_DIR (default: ./data/uploads)
    - [ ] 1.1.4 Add RESULTS_DIR (default: ./data/results)
    - [ ] 1.1.5 Add COMPUTE_TIMEOUT (default: 300 seconds)
    - [ ] 1.1.6 Add MAX_UPLOAD_SIZE (default: 10GB)
    - [ ] 1.1.7 Export settings singleton instance
  - [ ] 1.2 Create `backend/core/database.py` with async SQLAlchemy:
    - [ ] 1.2.1 Create async engine with create_async_engine()
    - [ ] 1.2.2 Create async_sessionmaker for session management
    - [ ] 1.2.3 Create Base declarative class for models
    - [ ] 1.2.4 Create get_db() async dependency for FastAPI
    - [ ] 1.2.5 Create init_db() function to create tables
  - [ ] 1.3 Add required dependencies to `backend/pyproject.toml`:
    - [ ] 1.3.1 Add polars
    - [ ] 1.3.2 Add sqlalchemy[asyncio]
    - [ ] 1.3.3 Add aiosqlite
    - [ ] 1.3.4 Add alembic
    - [ ] 1.3.5 Add python-multipart (for file uploads)
  - [ ] 1.4 Setup Alembic for database migrations:
    - [ ] 1.4.1 Run `alembic init database/alembic`
    - [ ] 1.4.2 Configure `database/alembic.ini` with SQLite URL
    - [ ] 1.4.3 Update `database/alembic/env.py` for async support
    - [ ] 1.4.4 Import all models in env.py for autogenerate
  - [ ] 1.5 Create initial migration with all tables:
    - [ ] 1.5.1 Create `analyses` table (id, name, description, pipeline_definition, status, created_at, updated_at, result_path, thumbnail)
    - [ ] 1.5.2 Create `datasources` table (id, name, source_type, config, schema_cache, created_at)
    - [ ] 1.5.3 Create `analysis_datasources` junction table (analysis_id, datasource_id)
    - [ ] 1.5.4 Create `compute_jobs` table (id, analysis_id, status, progress, current_step, error_message, process_id, started_at, completed_at)
    - [ ] 1.5.5 Run migration with `alembic upgrade head`
  - [ ] 1.6 Update `backend/main.py`:
    - [ ] 1.6.1 Add lifespan context manager for startup/shutdown
    - [ ] 1.6.2 Initialize database on startup
    - [ ] 1.6.3 Create upload and results directories on startup
  - [ ] 1.7 Create `backend/core/__init__.py`:
    - [ ] 1.7.1 Export settings
    - [ ] 1.7.2 Export get_db dependency
    - [ ] 1.7.3 Export Base class
    - [ ] 1.7.4 Export init_db function

## Completion Criteria

- [ ] All dependencies installed successfully (`uv sync`)
- [ ] Database migrations run without errors
- [ ] Application starts with `just dev` without errors
- [ ] Database file created in `data/app.db`
- [ ] Upload and results directories created
