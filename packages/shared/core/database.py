from collections.abc import Callable, Generator
from contextlib import contextmanager
from threading import Lock
from typing import Concatenate, ParamSpec, TypeVar

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlmodel import Session, create_engine

from core.config import settings
from core.namespace import get_namespace, list_namespaces, namespace_paths, normalize_namespace

P = ParamSpec('P')
T = TypeVar('T')

_PUBLIC_SCHEMA = 'public'
_POSTGRES_INIT_LOCK_KEY = 4815162342


def _engine_kwargs() -> dict[str, object]:
    return {
        'pool_pre_ping': True,
        'pool_size': settings.database_pool_size,
        'max_overflow': settings.database_max_overflow,
        'pool_timeout': settings.database_pool_timeout,
    }


def _create_engine(url: str, *, connect_args: dict[str, object] | None = None) -> Engine:
    kwargs = _engine_kwargs()
    if connect_args is not None:
        kwargs['connect_args'] = connect_args
    return create_engine(url, echo=settings.sql_echo, **kwargs)


settings_engine: Engine | None = None
tenant_engine: Engine | None = None
_settings_engine_lock = Lock()
_tenant_engine_lock = Lock()
_initialized_namespaces: set[tuple[str, str]] = set()
_initialized_namespaces_lock = Lock()

_engine_override: Engine | None = None
_settings_engine_override: Engine | None = None
_settings_bootstrap_hook: Callable[[Session], None] | None = None
_settings_cache_invalidator: Callable[[], None] | None = None


def register_settings_bootstrap_hook(hook: Callable[[Session], None] | None) -> None:
    global _settings_bootstrap_hook
    _settings_bootstrap_hook = hook


def register_settings_cache_invalidator(hook: Callable[[], None] | None) -> None:
    global _settings_cache_invalidator
    _settings_cache_invalidator = hook


def _invalidate_settings_cache() -> None:
    if _settings_cache_invalidator is not None:
        _settings_cache_invalidator()


def set_engine_override(test_engine: Engine):
    global _engine_override
    _engine_override = test_engine


def clear_engine_override():
    global _engine_override
    _engine_override = None


def set_settings_engine_override(test_engine: Engine):
    global _settings_engine_override
    _settings_engine_override = test_engine
    _invalidate_settings_cache()


def clear_settings_engine_override():
    global _settings_engine_override
    _settings_engine_override = None
    _invalidate_settings_cache()


def _set_postgres_search_path(raw_connection: object, namespace: str) -> None:
    cursor = getattr(raw_connection, 'cursor', None)
    if not callable(cursor):
        return
    db_cursor = cursor()
    try:
        db_cursor.execute(f'SET search_path TO "{namespace}", {_PUBLIC_SCHEMA}')
    finally:
        db_cursor.close()


def _apply_postgres_search_path(connection: Connection, namespace: str) -> None:
    if connection.dialect.name != 'postgresql':
        return
    connection.execute(text(f'SET search_path TO "{namespace}", {_PUBLIC_SCHEMA}'))


def _create_public_engine() -> Engine:
    engine = _create_engine(settings.database_url, connect_args={'options': f'-c search_path={_PUBLIC_SCHEMA}'})

    @event.listens_for(engine, 'checkout')
    def _set_public_search_path(dbapi_connection, _connection_record, _connection_proxy) -> None:
        _set_postgres_search_path(dbapi_connection, _PUBLIC_SCHEMA)

    return engine


def get_settings_engine() -> Engine:
    global settings_engine

    if _settings_engine_override is not None:
        return _settings_engine_override
    if settings_engine is not None:
        return settings_engine

    with _settings_engine_lock:
        if settings_engine is None:
            settings_engine = _create_public_engine()
        return settings_engine


def _get_tenant_engine() -> Engine:
    global tenant_engine

    if _engine_override is not None:
        return _engine_override
    if tenant_engine is not None:
        return tenant_engine

    with _tenant_engine_lock:
        if tenant_engine is None:
            tenant_engine = _create_engine(settings.database_url)

            @event.listens_for(tenant_engine, 'checkout')
            def _set_namespace_search_path(dbapi_connection, _connection_record, _connection_proxy) -> None:
                _set_postgres_search_path(dbapi_connection, get_namespace())

        return tenant_engine


@contextmanager
def namespace_connection(namespace: str) -> Generator[Connection, None, None]:
    engine = _get_tenant_engine()
    with engine.begin() as connection:
        _apply_postgres_search_path(connection, namespace)
        yield connection


def get_db():
    namespace = get_namespace()
    _init_namespace_db(namespace)
    engine_to_use = _get_tenant_engine()
    with Session(engine_to_use) as session:
        yield session


def get_settings_db():
    engine_to_use = get_settings_engine()
    with Session(engine_to_use) as session:
        yield session


def run_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    namespace = get_namespace()
    _init_namespace_db(namespace)
    engine_to_use = _get_tenant_engine()
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def run_settings_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = get_settings_engine()
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def _shared_tables():
    from contracts.engine_instances.models import EngineInstance
    from contracts.namespaces.models import RuntimeNamespace
    from contracts.runtime_workers.models import RuntimeWorker
    from contracts.settings_models import AppSettings

    table_names = {AppSettings.__tablename__, EngineInstance.__tablename__, RuntimeNamespace.__tablename__, RuntimeWorker.__tablename__}
    return [table for table in AppSettings.metadata.sorted_tables if table.name in table_names]


def _tenant_tables():
    from contracts.analysis.models import Analysis, AnalysisDataSource, AnalysisFavorite
    from contracts.analysis_versions.models import AnalysisVersion
    from contracts.build_jobs.models import BuildJob
    from contracts.build_runs.models import BuildEvent, BuildRun
    from contracts.compute_requests.models import ComputeRequest
    from contracts.datasource.models import DataSource, DataSourceColumnMetadata
    from contracts.engine_runs.models import EngineRun
    from contracts.healthcheck_models import HealthCheck, HealthCheckResult
    from contracts.locks.models import ResourceLock
    from contracts.scheduler.models import Schedule
    from contracts.telegram_models import TelegramListener, TelegramSubscriber
    from contracts.udf_models import Udf

    table_names = {
        Analysis.__tablename__,
        AnalysisDataSource.__tablename__,
        AnalysisFavorite.__tablename__,
        AnalysisVersion.__tablename__,
        BuildEvent.__tablename__,
        BuildJob.__tablename__,
        BuildRun.__tablename__,
        ComputeRequest.__tablename__,
        DataSource.__tablename__,
        DataSourceColumnMetadata.__tablename__,
        EngineRun.__tablename__,
        HealthCheck.__tablename__,
        HealthCheckResult.__tablename__,
        ResourceLock.__tablename__,
        Schedule.__tablename__,
        TelegramListener.__tablename__,
        TelegramSubscriber.__tablename__,
        Udf.__tablename__,
    }
    return [table for table in Analysis.metadata.sorted_tables if table.name in table_names]


def _create_shared_tables_postgres() -> None:
    engine_to_use = get_settings_engine()
    tables = _shared_tables()
    metadata = tables[0].metadata if tables else None
    if metadata is None:
        return
    with engine_to_use.begin() as connection:
        connection.execute(text(f'SET search_path TO {_PUBLIC_SCHEMA}'))
        metadata.create_all(connection, tables=tables)


def _ensure_postgres_schema(connection: Connection, schema: str) -> None:
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def _init_postgres_namespace(namespace: str) -> None:
    from core.migrations import migrate_runtime

    migrate_runtime([namespace])


def _seed_shared_state() -> None:
    from core.namespaces_service import register_namespace

    def _seed(session: Session) -> None:
        if _settings_bootstrap_hook is not None:
            _settings_bootstrap_hook(session)
        register_namespace(session, settings.default_namespace)

    run_settings_db(_seed)
    _invalidate_settings_cache()


def _run_postgres_init_locked(func) -> None:
    from core.migrations import ensure_database_exists

    ensure_database_exists(settings.database_url)
    engine = get_settings_engine()
    with engine.connect() as connection:
        connection.execute(text('SELECT pg_advisory_lock(:key)'), {'key': _POSTGRES_INIT_LOCK_KEY})
        try:
            func()
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': _POSTGRES_INIT_LOCK_KEY})


def _namespace_init_key(namespace: str) -> tuple[str, str]:
    return settings.database_url, normalize_namespace(namespace)


def _mark_namespace_initialized(namespace: str) -> None:
    with _initialized_namespaces_lock:
        _initialized_namespaces.add(_namespace_init_key(namespace))


def clear_namespace_init_cache() -> None:
    with _initialized_namespaces_lock:
        _initialized_namespaces.clear()


def _init_namespace_db(namespace: str) -> None:
    if _engine_override is not None:
        return
    key = _namespace_init_key(namespace)
    with _initialized_namespaces_lock:
        if key in _initialized_namespaces:
            return
    _init_namespace_db_unlocked(namespace)


def _init_namespace_db_unlocked(namespace: str) -> None:
    with _initialized_namespaces_lock:
        key = _namespace_init_key(namespace)
        if key in _initialized_namespaces:
            return
        _run_postgres_init_locked(lambda: _init_postgres_namespace(namespace))
        _initialized_namespaces.add(key)


def _bootstrap_postgres() -> None:
    from core.migrations import migrate_runtime

    namespaces = list_namespaces()
    if settings.default_namespace not in namespaces:
        namespaces = [*namespaces, settings.default_namespace]
    normalized = [normalize_namespace(namespace) for namespace in namespaces]
    migrate_runtime(normalized)
    for namespace in normalized:
        namespace_paths(namespace)
        _mark_namespace_initialized(namespace)
    _invalidate_settings_cache()


async def init_db() -> None:

    def _init_postgres() -> None:
        _bootstrap_postgres()
        _seed_shared_state()

    _run_postgres_init_locked(_init_postgres)


def supports_distributed_runtime() -> bool:
    return settings.distributed_runtime_enabled
