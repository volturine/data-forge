# Database Migrations with Alembic

This directory contains Alembic migrations for the FastAPI backend database.

## Overview

The project uses:
- **Alembic** for database migrations
- **SQLAlchemy 2.0** with async support
- **SQLite** via SQLAlchemy
- **SQLite** database (configured in `core/config.py`)

## Directory Structure

```
database/
├── alembic/              # Alembic configuration
│   ├── versions/         # Migration scripts
│   ├── env.py           # Alembic environment configuration
│   └── script.py.mako   # Migration template
├── alembic.ini          # Alembic configuration file
├── app.db              # SQLite database file (created after first migration)
└── README.md           # This file
```

## Common Commands

All commands should be run from the **backend root directory** (`/backend`).

### Create a New Migration

After modifying models in `modules/*/models.py`:

```bash
# Auto-generate migration from model changes
uv run alembic -c database/alembic.ini revision --autogenerate -m "Description of changes"

# Create empty migration (for data migrations or complex changes)
uv run alembic -c database/alembic.ini revision -m "Description of changes"
```

### Apply Migrations

```bash
# Upgrade to the latest migration
uv run alembic -c database/alembic.ini upgrade head

# Upgrade to a specific revision
uv run alembic -c database/alembic.ini upgrade <revision_id>

# Upgrade by one revision
uv run alembic -c database/alembic.ini upgrade +1
```

### Rollback Migrations

```bash
# Downgrade by one revision
uv run alembic -c database/alembic.ini downgrade -1

# Downgrade to a specific revision
uv run alembic -c database/alembic.ini downgrade <revision_id>

# Rollback all migrations
uv run alembic -c database/alembic.ini downgrade base
```

### View Migration Status

```bash
# Show current migration version
uv run alembic -c database/alembic.ini current

# Show migration history
uv run alembic -c database/alembic.ini history

# Show pending migrations
uv run alembic -c database/alembic.ini heads
```

## Configuration

### Database URL

The database URL is configured in `core/config.py`:

```python
database_url: str = 'sqlite:///${DATA_DIR}/app.db'
```

You can override this in `.env`:

```env
DATABASE_URL=sqlite:///${DATA_DIR}/app.db
```

### Adding New Models

When you create a new model:

1. Create the model class in the appropriate module (e.g., `modules/mymodule/models.py`)
2. Import the model in `database/alembic/env.py`:
   ```python
   from modules.mymodule.models import MyModel
   ```
3. Generate a migration:
   ```bash
   uv run alembic -c database/alembic.ini revision --autogenerate -m "Add MyModel table"
   ```
4. Review the generated migration in `database/alembic/versions/`
5. Apply the migration:
   ```bash
   uv run alembic -c database/alembic.ini upgrade head
   ```

## Integration with Application

### Replacing init_db()

Now that Alembic is set up, you should **run migrations instead of using `init_db()`**:

**Before (in `main.py`):**
```python
@asynccontextmanager
def lifespan(app: FastAPI):
    init_db()  # Creates tables directly - DON'T USE with Alembic
    yield
```

**After (recommended approach):**

1. Remove the `init_db()` call from `main.py` (or keep it for backward compatibility)
2. Run migrations before starting the application:
   ```bash
   # Apply migrations first
   uv run alembic -c database/alembic.ini upgrade head
   
   # Then start the server
   uv run main.py
   ```

3. Or create a startup script that runs both:
   ```bash
   #!/bin/bash
   # start.sh
   uv run alembic -c database/alembic.ini upgrade head
   uv run main.py
   ```

**Note:** The `init_db()` function in `core/database.py` uses `Base.metadata.create_all()` which creates tables but doesn't track migration history. With Alembic, migrations are tracked in the `alembic_version` table.

## Important Notes

### Sync Support

The Alembic configuration is set up for sync SQLAlchemy:
- Uses `create_engine` in `env.py`
- Uses SQLAlchemy's SQLite dialect

### SQLite Batch Mode

Migrations are configured with `render_as_batch=True` to support SQLite's limited ALTER TABLE support.

### Model Imports

All models must be imported in `database/alembic/env.py` for autogenerate to detect them:

```python
# Import all models to ensure they are registered with Base.metadata
from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource
```

### Running from Different Directories

Always use the `-c database/alembic.ini` flag when running from the backend root:

```bash
# From backend root (recommended)
uv run alembic -c database/alembic.ini upgrade head

# From database directory (alternative)
cd database && uv run alembic upgrade head
```

## Existing Migrations

### Initial Migration (a7fc1ff5a710)

Creates the initial database schema with three tables:

1. **datasources** - Stores data source configurations
   - id (String, primary key)
   - name (String)
   - source_type (String)
   - config (JSON)
   - schema_cache (JSON, nullable)
   - created_at (DateTime with timezone)

2. **analyses** - Stores analysis definitions and results
   - id (String, primary key)
   - name (String)
   - description (String, nullable)
   - pipeline_definition (JSON)
   - status (String)
   - created_at (DateTime with timezone)
   - updated_at (DateTime with timezone)
   - result_path (String, nullable)
   - thumbnail (String, nullable)

3. **analysis_datasources** - Junction table linking analyses to datasources
   - analysis_id (String, foreign key → analyses.id, CASCADE delete)
   - datasource_id (String, foreign key → datasources.id, CASCADE delete)
   - Composite primary key (analysis_id, datasource_id)

## Troubleshooting

### Database locked error

SQLite can have locking issues. Make sure:
- The database file is not open in another process
- You're not running multiple migrations simultaneously

### Migration not detected

If autogenerate doesn't detect your changes:
1. Verify the model is imported in `env.py`
2. Check that the model inherits from `Base` (from `core.database`)
3. Ensure you're using `Mapped` type hints

### Permission errors

Ensure the `database/` directory is writable:
```bash
chmod 755 database/
```

## Development Workflow

1. **Create/modify models** in `modules/*/models.py`
2. **Import models** in `database/alembic/env.py` (if new)
3. **Generate migration**: `uv run alembic -c database/alembic.ini revision --autogenerate -m "description"`
4. **Review migration** in `database/alembic/versions/`
5. **Apply migration**: `uv run alembic -c database/alembic.ini upgrade head`
6. **Commit** both the model changes and migration file to git

## Production Deployment

For production deployments:

1. **Backup database** before running migrations
2. **Test migrations** in a staging environment first
3. **Run migrations** as part of deployment:
   ```bash
   uv run alembic -c database/alembic.ini upgrade head
   ```
4. Consider using migration tools that support zero-downtime deployments

## Resources

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/)
- [FastAPI with Alembic Tutorial](https://fastapi.tiangolo.com/tutorial/sql-databases/)
