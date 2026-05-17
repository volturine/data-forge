# Shared Runtime Contracts and Infrastructure

Neutral contracts, migrations, persistence primitives, and low-level infrastructure shared by the Postgres-backed Data-Forge runtime.

## Setup

1. Install dependencies:

   ```bash
   uv sync --extra dev
   ```

2. Configure environment:

   ```bash
   # Edit dev.env for local development settings
   ```

3. Run database migrations manually if needed:

   ```bash
   ./migrate.sh upgrade
   # Or manually: uv run alembic -c database/alembic.ini upgrade head
   ```

4. Start the local runtime from the repo root:
    ```bash
    just dev
    ```

## Database Migrations

This project uses Alembic for database migrations. See [`database/README.md`](database/README.md) for detailed documentation.

### Quick Commands

Use the `migrate.sh` script for common operations:

```bash
# Apply all pending migrations
./migrate.sh upgrade

# Create a new migration after modifying models
./migrate.sh create "Add new field to User table"

# Show current migration version
./migrate.sh current

# View migration history
./migrate.sh history

# Rollback one migration
./migrate.sh downgrade
```

Or use Alembic directly:

```bash
# Apply migrations
uv run alembic -c database/alembic.ini upgrade head

# Create new migration
uv run alembic -c database/alembic.ini revision --autogenerate -m "description"

# Show status
uv run alembic -c database/alembic.ini current
```

## Development

### Project Structure

```
backend/
├── api/                  # API routes (legacy)
├── core/                 # Core application code
│   ├── config.py        # Configuration and settings
│   └── database.py      # Database setup and Base model
├── database/            # Database and migrations
│   ├── alembic/        # Alembic migration files
│   ├── alembic.ini     # Alembic configuration
│   └── README.md       # Migration documentation
├── modules/             # Feature modules
│   ├── analysis/       # Analysis management
│   ├── compute/        # Computation engine
│   ├── datasource/     # Data source management
│   ├── health/         # Health checks
│   └── results/        # Result handling
├── main.py             # API entry point
├── migrate.sh          # Migration helper script
└── pyproject.toml      # Project dependencies
```

### Adding New Models

1. Create model in appropriate module (e.g., `modules/mymodule/models.py`):

   ```python
    from sqlalchemy import Column, String
    from sqlmodel import Field, SQLModel

    class MyModel(SQLModel, table=True):
        __tablename__ = 'my_table'
        id: str = Field(primary_key=True, sa_column=Column(String, primary_key=True))
        name: str = Field(sa_column=Column(String, nullable=False))
   ```

2. Import model in `database/alembic/env.py`:

   ```python
   from modules.mymodule.models import MyModel
   ```

3. Create and apply migration:
   ```bash
   ./migrate.sh create "Add MyModel table"
   ./migrate.sh upgrade
   ```

### Running Tests

```bash
uv run pytest
uv run pytest -k "test_name"              # Run specific test
uv run pytest path/to/test_file.py        # Run specific file
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint and fix
uv run ruff check --fix .

# Type check
uv run mypy .
```

## API Documentation

Once the server is running, visit:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Configuration

Configuration is managed through `core/config.py` using Pydantic settings.

Local setup uses `dev.env`.

Common settings:

- `DATA_DIR` - Base writable data directory
- `PORT` - Backend HTTP port
- `CORS_ORIGINS` - Allowed browser origins
- `UPLOAD_CHUNK_SIZE` - Upload chunk size in bytes
- `AUTH_REQUIRED` - Whether authenticated routes require login

Override in `dev.env`, `prod.env`, or process environment variables. Use `ENV_FILE` to point to a specific env file (set to empty to disable env-file loading).

See [`../ENV_VARIABLES.md`](../ENV_VARIABLES.md) for the complete reference, including frontend development variables and notes about DB-seeded settings.

## Production Deployment

1. Set production environment variables:

   ```bash
   export DATABASE_URL="postgresql+psycopg://user:pass@host:5432/dataforge"
   export DISTRIBUTED_RUNTIME_ENABLED=true
   # ... other settings
   ```

2. Start the production runtime:

   ```bash
   (cd ../backend && uv run --env-file ../shared/prod.env ./main.py)
   (cd ../scheduler && uv run --env-file ../shared/prod.env ./main.py)
   (cd ../worker-manager && uv run --env-file ../shared/prod.env ./main.py)
   ```

For Docker releases, customers should pull the published `data-forge-api`, `data-forge-scheduler`, and `data-forge-worker` images rather than building from source.

## Troubleshooting

### Database Issues

If you encounter database errors:

1. Check migration status: `./migrate.sh current`
2. View migration history: `./migrate.sh history`
3. Try downgrading and upgrading: `./migrate.sh downgrade && ./migrate.sh upgrade`

### PostgreSQL connectivity

If the runtime cannot reach PostgreSQL:

- Verify `DATABASE_URL` points to a reachable PostgreSQL instance
- Confirm migrations/bootstrap completed successfully
- Check connection-pool sizing versus available `max_connections`

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Migration Guide](database/README.md)
