from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import create_engine, pool, text

from backend_core.config import settings
from backend_core.namespace import namespace_database_schema

_SCHEMA_REVISION = 'runtime_schema_baseline'
_LEGACY_REVISIONS = {
    'public': {
        '0020_runtime_wakes',
        '0025_compute_worker_instances',
        '0027_compute_worker_instance',
        '0029_compute_worker_host',
    },
    'tenant': {
        '0022_telegram_part_receipts',
        '0023_drop_ds_freshness',
        '0024_pivot_value_columns',
        '0026_compute_worker_runs',
        '0028_compute_worker_run',
    },
}
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


def ensure_database_exists(database_url: str | None = None) -> None:
    target_url = (database_url or settings.database_url).replace('postgresql+psycopg://', 'postgresql://', 1)
    if _database_exists(target_url):
        return

    parsed = urlparse(target_url)
    database = parsed.path.lstrip('/')
    owner = parsed.username or ''
    if not database:
        raise ValueError('DATABASE_URL must include a database name')
    if not owner:
        raise ValueError('DATABASE_URL must include a username')

    maintenance_url = urlunparse(parsed._replace(path='/postgres'))
    with _connect(maintenance_url) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (database,))
        if cursor.fetchone() is not None:
            return
        cursor.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database), sql.Identifier(owner)))


def _current_revision(schema: str) -> str | None:
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            has_version_table = connection.execute(
                text('SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table_name'),
                {'schema': schema, 'table_name': 'alembic_version'},
            ).first()
            if has_version_table is None:
                return None
            value = connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version LIMIT 1')).scalar()
        return value if isinstance(value, str) else None
    finally:
        engine.dispose()


def _schema_is_empty(schema: str) -> bool:
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


def _upgrade_schema(*, scope: str, schema: str) -> None:
    command.upgrade(_alembic_config(scope=scope, schema=schema), _SCHEMA_REVISION, tag=scope)


def _upgrade_legacy_schema(*, scope: str, schema: str, revision: str) -> None:
    config = _alembic_config(scope=scope, schema=schema)
    baseline = ScriptDirectory.from_config(config).get_revision(_SCHEMA_REVISION)
    if baseline is None:
        raise RuntimeError(f'Missing migration baseline {_SCHEMA_REVISION}')

    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            preparer = connection.dialect.identifier_preparer
            quoted_schema = preparer.quote_schema(schema)
            connection.execute(text(f'SET LOCAL search_path TO {quoted_schema}, public'))
            migration_context = MigrationContext.configure(
                connection,
                opts={
                    'version_table_schema': schema,
                    'tag': scope,
                    'target_schema': schema,
                    'source_revision': revision,
                },
            )
            with Operations.context(migration_context):
                baseline.module.upgrade()
            result = connection.execute(
                text(f'UPDATE {quoted_schema}.alembic_version SET version_num = :revision'),
                {'revision': _SCHEMA_REVISION},
            )
            if result.rowcount != 1:
                raise RuntimeError(f'Expected one {schema}.alembic_version row while adopting {revision}; found {result.rowcount}')
    finally:
        engine.dispose()


def _migrate_scope(*, scope: str, schema: str) -> None:
    revision = _current_revision(schema)
    if revision == _SCHEMA_REVISION:
        return

    if revision is None:
        if scope == 'tenant' and not _schema_is_empty(schema):
            raise RuntimeError(f'Unsupported existing tenant schema without a migration revision: {schema}')
        _upgrade_schema(scope=scope, schema=schema)
        return

    if revision in _LEGACY_REVISIONS[scope]:
        _upgrade_legacy_schema(scope=scope, schema=schema, revision=revision)
        return

    raise RuntimeError(f'Unsupported existing {scope} schema revision: {revision}. Expected {_SCHEMA_REVISION} or a managed pre-squash revision.')


def migrate_runtime(namespaces: list[str]) -> None:
    ensure_database_exists()
    _migrate_scope(scope='public', schema='public')
    for namespace in namespaces:
        _migrate_scope(scope='tenant', schema=namespace_database_schema(namespace))
