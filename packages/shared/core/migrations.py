from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text

from core.config import settings

_PUBLIC_REVISION = '0001_runtime_public'
_TENANT_REVISION = '0002_runtime_tenant'
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


def _schema_has_table(*, schema: str, table_name: str) -> bool:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text('SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table_name'),
                {'schema': schema, 'table_name': table_name},
            ).first()
        return row is not None
    finally:
        engine.dispose()


def _stamp_schema(*, scope: str, schema: str, revision: str) -> None:
    command.stamp(_alembic_config(scope=scope, schema=schema), revision)


def _upgrade_schema(*, scope: str, schema: str, revision: str) -> None:
    command.upgrade(_alembic_config(scope=scope, schema=schema), revision, tag=scope)


def migrate_runtime(namespaces: list[str]) -> None:
    ensure_database_exists()
    public_revision = _current_revision('public')
    if public_revision is not None and public_revision != _PUBLIC_REVISION:
        raise RuntimeError(f'Unsupported existing public schema revision: {public_revision}. Expected {_PUBLIC_REVISION}.')
    if public_revision is None:
        if _schema_has_table(schema='public', table_name='app_settings'):
            _stamp_schema(scope='public', schema='public', revision=_PUBLIC_REVISION)
        else:
            _upgrade_schema(scope='public', schema='public', revision=_PUBLIC_REVISION)
    for namespace in namespaces:
        revision = _current_revision(namespace)
        if revision is not None and revision != _TENANT_REVISION:
            raise RuntimeError(f'Unsupported existing tenant schema revision for namespace {namespace}: {revision}. Expected {_TENANT_REVISION}.')
        if revision == _TENANT_REVISION:
            continue
        if revision is None and _schema_has_table(schema=namespace, table_name='datasources'):
            _stamp_schema(scope='tenant', schema=namespace, revision=_TENANT_REVISION)
            continue
        _upgrade_schema(scope='tenant', schema=namespace, revision=_TENANT_REVISION)
