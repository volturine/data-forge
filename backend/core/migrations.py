from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text

from core.config import settings

_PUBLIC_REVISION = '0001_runtime_public'
_TENANT_REVISION = '0003_runtime_tenant_initial'


def _alembic_config(*, scope: str, schema: str) -> Config:
    path = Path(__file__).resolve().parent.parent / 'database' / 'alembic.ini'
    config = Config(str(path))
    config.set_main_option('sqlalchemy.url', settings.database_url)
    config.attributes['runtime_scope'] = scope
    config.attributes['target_schema'] = schema
    return config


def _ensure_schema(schema: str) -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    finally:
        engine.dispose()


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


def _stamp_schema(schema: str, revision: str) -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE TABLE IF NOT EXISTS "{schema}".alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
            connection.execute(text(f'DELETE FROM "{schema}".alembic_version'))
            connection.execute(
                text(f'INSERT INTO "{schema}".alembic_version (version_num) VALUES (:revision)'),
                {'revision': revision},
            )
    finally:
        engine.dispose()


def _bootstrap_public_schema() -> None:
    from core import database

    tables = database._shared_tables()
    if not tables:
        return
    metadata = tables[0].metadata
    engine = database._create_public_engine()
    try:
        with engine.begin() as connection:
            connection.execute(text('SET search_path TO public'))
            metadata.create_all(connection, tables=tables)
    finally:
        engine.dispose()
    _stamp_schema('public', _PUBLIC_REVISION)


def _bootstrap_tenant_schema(schema: str) -> None:
    from core import database

    _ensure_schema(schema)
    tables = database._tenant_tables()
    if not tables:
        return
    metadata = tables[0].metadata
    engine = database._create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'SET search_path TO "{schema}", public'))
            metadata.create_all(connection, tables=tables)
    finally:
        engine.dispose()
    _stamp_schema(schema, _TENANT_REVISION)


def migrate_runtime(namespaces: list[str]) -> None:
    public_revision = _current_revision('public')
    if public_revision is None:
        _bootstrap_public_schema()
    elif public_revision != _PUBLIC_REVISION:
        raise RuntimeError(
            f'Unsupported existing public schema revision: {public_revision}. Expected initialization revision {_PUBLIC_REVISION}.'
        )
    for namespace in namespaces:
        revision = _current_revision(namespace)
        if revision is None:
            _bootstrap_tenant_schema(namespace)
            continue
        if revision != _TENANT_REVISION:
            raise RuntimeError(
                'Unsupported existing tenant schema revision '
                f'for namespace {namespace}: {revision}. '
                f'Expected initialization revision {_TENANT_REVISION}.'
            )
