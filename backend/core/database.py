import threading
from collections import OrderedDict
from collections.abc import Callable, Generator
from contextlib import contextmanager
from threading import Lock
from typing import Concatenate, ParamSpec, TypeVar

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, create_engine

from core.config import settings
from core.namespace import get_namespace, list_namespaces, namespace_paths, normalize_namespace

P = ParamSpec('P')
T = TypeVar('T')

_MAX_NAMESPACE_ENGINES = 50
_PUBLIC_SCHEMA = 'public'
_POSTGRES_INIT_LOCK_KEY = 4815162342
_TENANT_TABLES = frozenset(
    {
        'analyses',
        'analysis_datasources',
        'analysis_versions',
        'build_events',
        'build_jobs',
        'build_runs',
        'datasources',
        'datasource_column_metadata',
        'engine_runs',
        'healthcheck_results',
        'healthchecks',
        'resource_locks',
        'schedules',
        'telegram_listeners',
        'telegram_subscribers',
        'udfs',
    }
)


def _engine_kwargs() -> dict[str, object]:
    if settings.is_postgres:
        return {
            'pool_pre_ping': True,
            'pool_size': settings.database_pool_size,
            'max_overflow': settings.database_max_overflow,
            'pool_timeout': settings.database_pool_timeout,
        }
    return {'connect_args': {}}


def _enable_sqlite_pragmas(engine: Engine) -> None:
    if engine.dialect.name != 'sqlite':
        return

    @event.listens_for(engine, 'connect')
    def _on_connect(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.close()


def _sqlite_columns(connection: Connection, table: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA table_info('{table}')")).all()
    return {str(row[1]) for row in rows}


def _sqlite_indexes(connection: Connection, table: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA index_list('{table}')")).all()
    return {str(row[1]) for row in rows}


def _ensure_sqlite_column(connection: Connection, table: str, column: str, statement: str) -> None:
    if column in _sqlite_columns(connection, table):
        return
    try:
        connection.execute(text(statement))
    except OperationalError:
        if column in _sqlite_columns(connection, table):
            return
        raise


def _ensure_sqlite_index(connection: Connection, table: str, index: str, statement: str) -> None:
    if index in _sqlite_indexes(connection, table):
        return
    try:
        connection.execute(text(statement))
    except OperationalError:
        if index in _sqlite_indexes(connection, table):
            return
        raise


def _ensure_namespace_runtime_columns(engine: Engine) -> None:
    if engine.dialect.name != 'sqlite':
        return
    with engine.begin() as connection:
        table_rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
        tables = {str(row[0]) for row in table_rows}
        if 'datasources' in tables:
            _ensure_sqlite_column(
                connection,
                'datasources',
                'description',
                'ALTER TABLE datasources ADD COLUMN description VARCHAR(4000)',
            )
        if 'schedules' in tables:
            additions = {
                'lease_owner': 'ALTER TABLE schedules ADD COLUMN lease_owner VARCHAR',
                'lease_expires_at': 'ALTER TABLE schedules ADD COLUMN lease_expires_at DATETIME',
                'last_claimed_at': 'ALTER TABLE schedules ADD COLUMN last_claimed_at DATETIME',
                'last_triggered_at': 'ALTER TABLE schedules ADD COLUMN last_triggered_at DATETIME',
                'last_success_at': 'ALTER TABLE schedules ADD COLUMN last_success_at DATETIME',
                'last_failure_at': 'ALTER TABLE schedules ADD COLUMN last_failure_at DATETIME',
                'last_successful_build_id': 'ALTER TABLE schedules ADD COLUMN last_successful_build_id VARCHAR',
            }
            for column, statement in additions.items():
                _ensure_sqlite_column(connection, 'schedules', column, statement)
            _ensure_sqlite_index(
                connection,
                'schedules',
                'ix_schedules_lease_owner',
                'CREATE INDEX ix_schedules_lease_owner ON schedules (lease_owner)',
            )
        if 'build_runs' not in tables:
            return
        _ensure_sqlite_column(connection, 'build_runs', 'schedule_id', 'ALTER TABLE build_runs ADD COLUMN schedule_id VARCHAR')
        _ensure_sqlite_index(
            connection,
            'build_runs',
            'ix_build_runs_schedule_id',
            'CREATE INDEX ix_build_runs_schedule_id ON build_runs (schedule_id)',
        )


def _create_engine(url: str) -> Engine:
    engine = create_engine(url, echo=settings.debug, **_engine_kwargs())
    _enable_sqlite_pragmas(engine)
    return engine


settings_engine: Engine | None = None
_settings_engine_lock = Lock()

_namespace_engines: OrderedDict[str, Engine] = OrderedDict()
_namespace_engines_lock = threading.Lock()

_engine_override: Engine | None = None
_settings_engine_override: Engine | None = None


def set_engine_override(test_engine: Engine):
    global _engine_override
    _engine_override = test_engine


def clear_engine_override():
    global _engine_override
    _engine_override = None


def set_settings_engine_override(test_engine: Engine):
    global _settings_engine_override
    _settings_engine_override = test_engine
    from modules.settings.service import invalidate_resolved_settings_cache

    invalidate_resolved_settings_cache()


def clear_settings_engine_override():
    global _settings_engine_override
    _settings_engine_override = None
    from modules.settings.service import invalidate_resolved_settings_cache

    invalidate_resolved_settings_cache()


def _apply_postgres_search_path(connection: Connection, namespace: str) -> None:
    if connection.dialect.name != 'postgresql':
        return
    connection.execute(text(f'SET search_path TO "{namespace}", {_PUBLIC_SCHEMA}'))


def _set_dbapi_search_path(dbapi_conn, search_path: str) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_conn.cursor()
    cursor.execute(search_path)
    cursor.close()


def _attach_postgres_search_path(engine: Engine, search_path: str) -> None:
    @event.listens_for(engine, 'connect')
    def _on_connect(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
        _set_dbapi_search_path(dbapi_conn, search_path)

    @event.listens_for(engine.pool, 'checkout')
    def _on_checkout(dbapi_conn, _connection_record, _connection_proxy):  # type: ignore[no-untyped-def]
        _set_dbapi_search_path(dbapi_conn, search_path)


def _create_postgres_namespace_engine(namespace: str) -> Engine:
    engine = _create_engine(settings.database_url)
    _attach_postgres_search_path(engine, f'SET search_path TO "{namespace}", {_PUBLIC_SCHEMA}')
    return engine


def _create_public_engine() -> Engine:
    engine = _create_engine(settings.database_url)
    _attach_postgres_search_path(engine, f'SET search_path TO {_PUBLIC_SCHEMA}')
    return engine


def get_settings_engine() -> Engine:
    global settings_engine

    if _settings_engine_override is not None:
        return _settings_engine_override
    if settings_engine is not None:
        return settings_engine

    with _settings_engine_lock:
        if settings_engine is None:
            settings_engine = _create_public_engine() if settings.is_postgres else _create_engine(settings.database_url)
        return settings_engine


def _create_sqlite_namespace_engine(namespace: str) -> Engine:
    paths = namespace_paths(namespace)
    return _create_engine(f'sqlite:///{paths.db_path}')


def _get_namespace_engine() -> Engine:
    namespace = get_namespace()
    if _engine_override is not None:
        return _engine_override
    with _namespace_engines_lock:
        if namespace in _namespace_engines:
            _namespace_engines.move_to_end(namespace)
            return _namespace_engines[namespace]
        if len(_namespace_engines) >= _MAX_NAMESPACE_ENGINES:
            oldest = next(iter(_namespace_engines))
            _namespace_engines.pop(oldest).dispose()
        engine = _create_postgres_namespace_engine(namespace) if settings.is_postgres else _create_sqlite_namespace_engine(namespace)
        _namespace_engines[namespace] = engine
        _init_namespace_db_unlocked(namespace)
        return engine


@contextmanager
def namespace_connection(namespace: str) -> Generator[Connection, None, None]:
    engine = get_settings_engine() if settings.is_postgres else _get_namespace_engine()
    with engine.begin() as connection:
        if settings.is_postgres:
            _apply_postgres_search_path(connection, namespace)
        yield connection


def get_db():
    engine_to_use = _engine_override or _get_namespace_engine()
    with Session(engine_to_use) as session:
        yield session


def get_settings_db():
    engine_to_use = get_settings_engine()
    with Session(engine_to_use) as session:
        yield session


def run_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = _engine_override or _get_namespace_engine()
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def run_settings_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = get_settings_engine()
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def _shared_tables():
    from modules.auth.models import AuthProvider, User, UserSession, VerificationToken
    from modules.chat.sessions import ChatSession
    from modules.engine_instances.models import EngineInstance
    from modules.runtime_workers.models import RuntimeWorker
    from modules.settings.models import AppSettings

    table_names = {
        AppSettings.__tablename__,
        ChatSession.__tablename__,
        User.__tablename__,
        AuthProvider.__tablename__,
        EngineInstance.__tablename__,
        RuntimeWorker.__tablename__,
        UserSession.__tablename__,
        VerificationToken.__tablename__,
    }
    return [table for table in AppSettings.metadata.sorted_tables if table.name in table_names]


def _tenant_tables():
    from modules.analysis.models import Analysis, AnalysisDataSource
    from modules.analysis_versions.models import AnalysisVersion
    from modules.build_jobs.models import BuildJob
    from modules.build_runs.models import BuildEvent, BuildRun
    from modules.datasource.models import DataSource, DataSourceColumnMetadata
    from modules.engine_runs.models import EngineRun
    from modules.healthcheck.models import HealthCheck, HealthCheckResult
    from modules.locks.models import ResourceLock
    from modules.scheduler.models import Schedule
    from modules.telegram.models import TelegramListener, TelegramSubscriber
    from modules.udf.models import Udf

    table_names = {
        Analysis.__tablename__,
        AnalysisDataSource.__tablename__,
        AnalysisVersion.__tablename__,
        BuildEvent.__tablename__,
        BuildJob.__tablename__,
        BuildRun.__tablename__,
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


def _create_shared_tables_sqlite() -> None:
    engine_to_use = get_settings_engine()
    metadata = _shared_tables()[0].metadata if _shared_tables() else None
    if metadata is None:
        return
    metadata.create_all(engine_to_use, tables=_shared_tables())


def _create_shared_tables_postgres() -> None:
    engine_to_use = get_settings_engine()
    tables = _shared_tables()
    metadata = tables[0].metadata if tables else None
    if metadata is None:
        return
    with engine_to_use.begin() as connection:
        connection.execute(text(f'SET search_path TO {_PUBLIC_SCHEMA}'))
        metadata.create_all(connection, tables=tables)


def _create_tenant_tables_sqlite(namespace: str) -> None:
    namespace_engine = _namespace_engines.get(namespace)
    if namespace_engine is None:
        namespace_engine = _create_sqlite_namespace_engine(namespace)
        _namespace_engines[namespace] = namespace_engine
    metadata = _tenant_tables()[0].metadata if _tenant_tables() else None
    if metadata is None:
        return
    metadata.create_all(namespace_engine, tables=_tenant_tables())
    _ensure_namespace_runtime_columns(namespace_engine)


def _ensure_postgres_schema(connection: Connection, schema: str) -> None:
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def _init_postgres_namespace(namespace: str) -> None:
    tables = _tenant_tables()
    metadata = tables[0].metadata if tables else None
    if metadata is None:
        return
    with get_settings_engine().begin() as connection:
        _ensure_postgres_schema(connection, namespace)
    engine = _namespace_engines.get(namespace)
    if engine is None:
        engine = _create_postgres_namespace_engine(namespace)
        _namespace_engines[namespace] = engine
    with engine.begin() as connection:
        _apply_postgres_search_path(connection, namespace)
        metadata.create_all(connection, tables=tables)


def _seed_shared_state() -> None:
    from modules.auth.service import ensure_default_user
    from modules.settings.service import invalidate_resolved_settings_cache, seed_settings_from_env

    def _seed(session: Session) -> None:
        seed_settings_from_env(session)
        ensure_default_user(session)

    run_settings_db(_seed)
    invalidate_resolved_settings_cache()


def _run_postgres_init_locked(func) -> None:
    engine = get_settings_engine()
    with engine.connect() as connection:
        connection.execute(text('SELECT pg_advisory_lock(:key)'), {'key': _POSTGRES_INIT_LOCK_KEY})
        try:
            func()
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': _POSTGRES_INIT_LOCK_KEY})


def _init_settings_db() -> None:
    if settings.is_postgres:
        return
    _create_shared_tables_sqlite()
    _seed_shared_state()


def _init_namespace_db(namespace: str) -> None:
    with _namespace_engines_lock:
        _init_namespace_db_unlocked(namespace)


def _init_namespace_db_unlocked(namespace: str) -> None:
    if settings.is_postgres:
        _init_postgres_namespace(namespace)
        return
    _create_tenant_tables_sqlite(namespace)


def _bootstrap_sqlite() -> None:
    _init_settings_db()
    namespaces = list_namespaces()
    if not namespaces:
        namespaces = [settings.default_namespace]
    for namespace in namespaces:
        namespace_paths(namespace)
        _init_namespace_db(namespace)


def _bootstrap_postgres() -> None:
    from core.migrations import migrate_runtime
    from modules.settings.service import invalidate_resolved_settings_cache

    namespaces = list_namespaces()
    if settings.default_namespace not in namespaces:
        namespaces = [*namespaces, settings.default_namespace]
    normalized = [normalize_namespace(namespace) for namespace in namespaces]
    migrate_runtime(normalized)
    for namespace in normalized:
        namespace_paths(namespace)
    invalidate_resolved_settings_cache()


async def init_db() -> None:
    if settings.is_postgres:

        def _init_postgres() -> None:
            _bootstrap_postgres()
            _seed_shared_state()

        _run_postgres_init_locked(_init_postgres)
        return
    _bootstrap_sqlite()


def supports_distributed_runtime() -> bool:
    return settings.distributed_runtime_enabled and settings.is_postgres
