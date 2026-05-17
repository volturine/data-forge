# Database Migrations with Alembic

This directory contains Alembic migrations for the Postgres-backed Data-Forge runtime.

## Overview

The runtime uses:
- **Alembic** for schema migrations
- **SQLAlchemy 2.0**
- **PostgreSQL** via `psycopg`
- runtime schemas for `public` plus tenant namespaces

## Directory Structure

```text
database/
├── alembic/              # Alembic configuration
│   ├── versions/         # Migration scripts
│   ├── env.py            # Alembic environment configuration
│   └── script.py.mako    # Migration template
├── alembic.ini           # Alembic configuration file
└── README.md             # This file
```

## Common Commands

Run these from `packages/shared`:

```bash
# Upgrade to the latest migration
uv run alembic -c database/alembic.ini upgrade head

# Show current migration version
uv run alembic -c database/alembic.ini current

# Show migration history
uv run alembic -c database/alembic.ini history

# Create a new migration
uv run alembic -c database/alembic.ini revision --autogenerate -m "description"
```

## Configuration

`DATABASE_URL` must be a PostgreSQL connection string, for example:

```env
DATABASE_URL=postgresql+psycopg://dataforge:dataforge@localhost:5432/dataforge
```

## Runtime model

- `public` schema stores shared/runtime-global tables
- tenant namespaces store analysis, datasource, build, compute, and other tenant-scoped tables
- runtime bootstrap ensures required schemas exist before use

## Development workflow

1. Modify models.
2. Import new models in `database/alembic/env.py` if needed.
3. Generate a migration.
4. Review the migration under `database/alembic/versions/`.
5. Apply it with `upgrade head`.
6. Commit both model and migration changes together.

## Troubleshooting

### Connection failures

- Verify PostgreSQL is reachable from `DATABASE_URL`
- Confirm the target database exists
- Check credentials and SSL/network settings as needed

### Migration issues

- Check current revision with `uv run alembic -c database/alembic.ini current`
- Review history with `uv run alembic -c database/alembic.ini history`
- Re-run against a clean database if you are validating a fresh bootstrap path

## Resources

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
