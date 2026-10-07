from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, pool, text

from backend_core.config import settings
from backend_core.namespace import namespace_database_schema

_PUBLIC_REVISION = '0020_runtime_wakes'
_TENANT_REVISION = '0024_pivot_value_columns'
_MISSING_DATABASE_SQLSTATE = '3D000'


def _alembic_config(*, scope: str, schema: str) -> Config:
    path = Path(__file__).resolve().parent.parent / 'database' / 'alembic.ini'
    config = Config(str(path))
    config.set_main_option('sqlalchemy.url', settings.database_url)
    config.set_main_option('runtime_scope', scope)
    config.set_main_option('target_schema', schema)
    config.attributes['runtime_scope'] = scope
    config.attributes['target_schema'] = schema
    config.attributes['configure_logging'] = False
    return config


def _connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, autocommit=True)


def _normalized_database_url(database_url: str) -> str:
    if database_url.startswith('postgresql+psycopg://'):
        return database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
    return database_url


def _database_exists(database_url: str) -> bool:
    try:
        with _connect(database_url):
            return True
    except psycopg.OperationalError as exc:
        if getattr(exc, 'sqlstate', None) == _MISSING_DATABASE_SQLSTATE:
            return False
        if 'does not exist' in str(exc).lower():
            return False
        raise


def _maintenance_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path='/postgres'))


def ensure_database_exists(database_url: str | None = None) -> None:
    target_url = _normalized_database_url(database_url or settings.database_url)
    if _database_exists(target_url):
        return

    parsed = urlparse(target_url)
    database = parsed.path.lstrip('/')
    owner = parsed.username or ''
    if not database:
        raise ValueError('DATABASE_URL must include a database name')
    if not owner:
        raise ValueError('DATABASE_URL must include a username')

    maintenance_url = _maintenance_database_url(target_url)
    with _connect(maintenance_url) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (database,))
        if cursor.fetchone() is not None:
            return
        cursor.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database), sql.Identifier(owner)))


def _has_version_table(schema: str) -> bool:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text('SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table_name'),
                {'schema': schema, 'table_name': 'alembic_version'},
            ).first()
        return row is not None
    finally:
        engine.dispose()


def _current_revision(schema: str) -> str | None:
    if not _has_version_table(schema):
        return None
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version LIMIT 1')).first()
        if row is None:
            return None
        value = row[0]
        return str(value) if isinstance(value, str) else None
    finally:
        engine.dispose()


def _schema_is_empty(schema: str) -> bool:
    """Check whether a tenant schema can be bootstrapped from current metadata."""
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            has_tables = connection.execute(
                text('SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = :schema)'),
                {'schema': schema},
            ).scalar_one()
        return not bool(has_tables)
    finally:
        engine.dispose()


def _bootstrap_empty_tenant_schema(schema: str) -> None:
    """Create a fresh tenant schema directly at head instead of replaying history.

    Historical data migrations still run for existing schemas. A new namespace
    has no rows to transform, so create its final table/index definitions from
    the same SQLModel metadata and stamp the current tenant revision atomically.
    """
    from backend_core.database import _tenant_tables

    tables = _tenant_tables()
    if not tables:
        raise RuntimeError('Tenant metadata contains no tables')
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            quoted_schema = connection.dialect.identifier_preparer.quote(schema)
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS {quoted_schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {quoted_schema}, public'))
            tables[0].metadata.create_all(connection, tables=tables, checkfirst=False)
            connection.execute(text(f'CREATE TABLE {quoted_schema}.alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
            connection.execute(
                text(f'INSERT INTO {quoted_schema}.alembic_version (version_num) VALUES (:revision)'),
                {'revision': _TENANT_REVISION},
            )
    finally:
        engine.dispose()


def _upgrade_schema(*, scope: str, schema: str, revision: str) -> None:
    command.upgrade(_alembic_config(scope=scope, schema=schema), revision, tag=scope)


def migrate_runtime(namespaces: list[str]) -> None:
    ensure_database_exists()
    public_revision = _current_revision('public')
    if public_revision in {
        None,
        '0001_runtime_public',
        '0006_runtime_namespace_work',
        '0008_schedule_wake_due',
        '0009_runtime_lease_wake_due',
        '0010_mcp_pending_actions',
        '0013_runtime_work_wakes',
        '0014_runtime_coordinator_fencing',
        '0015_durable_chat_turns',
    }:
        _upgrade_schema(scope='public', schema='public', revision=_PUBLIC_REVISION)
    elif public_revision != _PUBLIC_REVISION:
        raise RuntimeError(f'Unsupported existing public schema revision: {public_revision}. Expected {_PUBLIC_REVISION}. Recreate the database.')
    supported_tenant_revisions = (
        None,
        '0002_runtime_tenant',
        '0003_engine_request_identity',
        '0004_compute_request_datasources',
        '0007_schedule_due_index',
        '0008_schedule_wake_due',
        '0008_schedule_trigger_index',
        '0009_runtime_lease_wake_due',
        '0010_mcp_pending_actions',
        '0011_namespace_preview_flights',
        '0012_compute_request_flights',
        '0013_runtime_work_wakes',
        '0014_runtime_coordinator_fencing',
        '0015_durable_chat_turns',
        '0016_telegram_runtime',
        '0017_compute_source_index',
        '0018_runtime_work_generations',
        _TENANT_REVISION,
    )
    for namespace in namespaces:
        tenant_schema = namespace_database_schema(namespace)
        revision = _current_revision(tenant_schema)
        if revision is None and _schema_is_empty(tenant_schema):
            _bootstrap_empty_tenant_schema(tenant_schema)
            continue
        if revision not in supported_tenant_revisions:
            raise RuntimeError(
                f'Unsupported existing tenant schema revision for namespace {namespace}: {revision}. Expected {_TENANT_REVISION}. Recreate the database.'
            )
        if revision != _TENANT_REVISION:
            _upgrade_schema(scope='tenant', schema=tenant_schema, revision=_TENANT_REVISION)
