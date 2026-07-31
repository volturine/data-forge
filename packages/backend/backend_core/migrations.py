from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text

from backend_core.config import settings
from backend_core.namespace import namespace_database_schema

_PUBLIC_BASE_REVISION = '0001_runtime_public'
_PUBLIC_REVISION = '0003_engine_identity_public'
_TENANT_BASE_REVISION = '0002_runtime_tenant'
_TENANT_BASE_REVISIONS = {_TENANT_BASE_REVISION, '0004_compute_envelopes_tenant', '0005_fenced_build_jobs_tenant'}
_TENANT_REVISION = '0006_atomic_build_events_tenant'
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


def _upgrade_schema(*, scope: str, schema: str, revision: str) -> None:
    command.upgrade(_alembic_config(scope=scope, schema=schema), revision, tag=scope)


def migrate_runtime(namespaces: list[str]) -> None:
    ensure_database_exists()
    public_revision = _current_revision('public')
    if public_revision is not None and public_revision not in {_PUBLIC_BASE_REVISION, _PUBLIC_REVISION}:
        raise RuntimeError(f'Unsupported existing public schema revision: {public_revision}. Expected {_PUBLIC_BASE_REVISION} or {_PUBLIC_REVISION}.')
    if public_revision != _PUBLIC_REVISION:
        _upgrade_schema(scope='public', schema='public', revision=_PUBLIC_REVISION)
    for namespace in namespaces:
        tenant_schema = namespace_database_schema(namespace)
        revision = _current_revision(tenant_schema)
        supported_revisions = _TENANT_BASE_REVISIONS | {_TENANT_REVISION}
        if revision is not None and revision not in supported_revisions:
            raise RuntimeError(
                f'Unsupported existing tenant schema revision for namespace {namespace}: {revision}. Expected one of {sorted(supported_revisions)}.'
            )
        if revision == _TENANT_REVISION:
            continue
        _upgrade_schema(scope='tenant', schema=tenant_schema, revision=_TENANT_REVISION)
