# FastAPI Backend

FastAPI backend with async SQLAlchemy, Alembic migrations, and SQLite database.

## Setup

1. Install dependencies:

   ```bash
   uv sync --extra dev
   ```

2. Configure environment (optional):

   ```bash
   cp .env.example .env
   # Edit .env if needed
   ```

3. Run database migrations:

   ```bash
   ./migrate.sh upgrade
   # Or manually: uv run alembic -c database/alembic.ini upgrade head
   ```

4. Start the development server:
   ```bash
   uv run main.py
   # Or: uv run uvicorn main:app --reload
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
├── main.py             # Application entry point
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

Local setup:

```bash
cp .env.example .env
```

Common settings:

- `DATA_DIR` - Base writable data directory
- `PORT` - Backend HTTP port
- `CORS_ORIGINS` - Allowed browser origins
- `UPLOAD_CHUNK_SIZE` - Upload chunk size in bytes
- `JOB_TIMEOUT` - Job execution timeout in seconds
- `ENGINE_IDLE_TIMEOUT` - Idle engine timeout in seconds
- `AUTH_REQUIRED` - Whether authenticated routes require login

Override in `.env` file or environment variables. Use `ENV_FILE` to point to a specific env file (set to empty to disable env-file loading).

See [`../ENV_VARIABLES.md`](../ENV_VARIABLES.md) for the complete reference, including frontend development variables and notes about DB-seeded settings.

## Production Deployment

1. Set environment variables:

   ```bash
   export DATABASE_URL="sqlite:///${DATA_DIR}/app.db"
   # ... other settings
   ```

2. Run migrations:

   ```bash
   ./migrate.sh upgrade
   ```

3. Start server with production settings:
   ```bash
   uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

## Troubleshooting

### Database Issues

If you encounter database errors:

1. Check migration status: `./migrate.sh current`
2. View migration history: `./migrate.sh history`
3. Try downgrading and upgrading: `./migrate.sh downgrade && ./migrate.sh upgrade`

### SQLite Locked

SQLite can lock if another process is accessing it. Make sure:

- Only one server instance is running
- No SQLite browser tools are connected
- Database file has proper permissions

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Migration Guide](database/README.md)
