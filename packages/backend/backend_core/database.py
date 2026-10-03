import contextvars
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from hashlib import sha256
from threading import Lock
from typing import Any, Concatenate, ParamSpec

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import QueuePool
from sqlmodel import Session, create_engine

from backend_core.api_execution_budget import run_api_blocking
from backend_core.config import settings
from backend_core.namespace import (
    get_namespace,
    list_namespaces,
    namespace_database_schema,
    namespace_paths,
    normalize_namespace,
)

P = ParamSpec('P')

_PUBLIC_SCHEMA = 'public'
_POSTGRES_INIT_LOCK_KEY = 4815162342
_NAMESPACE_INIT_LOCK_PREFIX = 'dataforge-namespace-init:'
_NAMESPACE_PROVISION_LOCK_PREFIX = 'dataforge-namespace-provision:'
_ALEMBIC_MIGRATION_LOCK = Lock()
_POOL_CHECKOUTS_LOCK = Lock()
_POOL_CHECKOUTS: dict[tuple[int, int], tuple[float, int, str]] = {}
_ACTIVE_RUNTIME_COORDINATOR_GENERATION: int | None = None
_DATABASE_STATEMENT_TIMING: contextvars.ContextVar[dict[str, object] | None] = contextvars.ContextVar(
    'database_statement_timing',
    default=None,
)
_SQL_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
_SQL_QUOTED_IDENTIFIER = re.compile(r'"(?:""|[^"])*"')
_SQL_NUMBER = re.compile(r'(?<![A-Za-z_])\d+(?:\.\d+)?(?![A-Za-z_])')


class RuntimeCoordinatorFenced(RuntimeError):
    """Raised when work is attempted by a coordinator from an old epoch."""


@contextmanager
def database_statement_timing(metrics: dict[str, object]) -> Iterator[None]:
    """Collect bounded per-RPC SQL and transaction timings in this context."""
    token = _DATABASE_STATEMENT_TIMING.set(metrics)
    try:
        yield
    finally:
        _DATABASE_STATEMENT_TIMING.reset(token)


def _record_database_duration(metrics: dict[str, object], field: str, duration: float) -> None:
    recorded = metrics.get(field, 0.0)
    if not isinstance(recorded, (int, float)):
        recorded = 0.0
    metrics[field] = float(recorded) + max(duration, 0.0)


class _TimedQueuePool(QueuePool):
    """Record checkout wall time inside the active request/RPC timing span."""

    def connect(self) -> Any:
        metrics = _DATABASE_STATEMENT_TIMING.get()
        if metrics is None:
            return super().connect()
        started = time.perf_counter()
        try:
            return super().connect()
        finally:
            duration_ms = max((time.perf_counter() - started) * 1000, 0.0)
            _record_database_duration(metrics, 'db_pool_checkout_ms', duration_ms)
            count = metrics.get('db_pool_checkout_count', 0)
            metrics['db_pool_checkout_count'] = (count if isinstance(count, int) else 0) + 1
            max_checkout_ms = metrics.get('db_pool_checkout_max_ms', 0.0)
            if not isinstance(max_checkout_ms, (int, float)) or duration_ms > max_checkout_ms:
                metrics['db_pool_checkout_max_ms'] = duration_ms


def record_api_blocking_admission_wait(duration_ms: float, *, lane: str = 'general') -> None:
    """Add API blocking-lane admission delay to the active request timing context."""
    metrics = _DATABASE_STATEMENT_TIMING.get()
    if metrics is not None:
        _record_database_duration(metrics, 'api_blocking_admission_wait_ms', duration_ms)
        _record_database_duration(metrics, f'api_{lane}_admission_wait_ms', duration_ms)


def record_api_blocking_executor_queue(duration_ms: float, *, lane: str) -> None:
    metrics = _DATABASE_STATEMENT_TIMING.get()
    if metrics is not None:
        _record_database_duration(metrics, f'api_{lane}_executor_queue_ms', duration_ms)


def record_api_blocking_work(duration_ms: float, *, lane: str) -> None:
    metrics = _DATABASE_STATEMENT_TIMING.get()
    if metrics is not None:
        _record_database_duration(metrics, f'api_{lane}_work_ms', duration_ms)


def _before_cursor_execute(_connection, _cursor, _statement, _parameters, context, _executemany) -> None:
    metrics = _DATABASE_STATEMENT_TIMING.get()
    if metrics is None:
        return
    starts = metrics.setdefault('_statement_starts', {})
    if isinstance(starts, dict):
        statement = ' '.join(_statement.split())
        statement = _SQL_STRING_LITERAL.sub("'?'", statement)
        statement = _SQL_QUOTED_IDENTIFIER.sub('"?"', statement)
        statement = _SQL_NUMBER.sub('?', statement)
        starts[id(context)] = (time.perf_counter(), statement[:240])


def _finish_cursor_execute(context) -> None:
    metrics = _DATABASE_STATEMENT_TIMING.get()
    if metrics is None:
        return
    starts = metrics.get('_statement_starts')
    if not isinstance(starts, dict):
        return
    started = starts.pop(id(context), None)
    if isinstance(started, tuple) and len(started) == 2:
        started_at, statement = started
        if isinstance(started_at, (int, float)):
            duration_ms = (time.perf_counter() - started_at) * 1000
            _record_database_duration(metrics, 'sql_ms', duration_ms)
            slowest_sql_ms = metrics.get('slowest_sql_ms', 0.0)
            if isinstance(statement, str) and isinstance(slowest_sql_ms, (int, float)) and duration_ms > slowest_sql_ms:
                metrics['slowest_sql_ms'] = duration_ms
                metrics['slowest_sql_statement'] = statement
        sql_count = metrics.get('sql_count', 0)
        metrics['sql_count'] = (sql_count if isinstance(sql_count, int) else 0) + 1


def _handle_cursor_error(exception_context) -> None:
    if exception_context.execution_context is not None:
        _finish_cursor_execute(exception_context.execution_context)


event.listen(Engine, 'before_cursor_execute', _before_cursor_execute)
event.listen(Engine, 'after_cursor_execute', lambda _conn, _cursor, _statement, _params, context, _many: _finish_cursor_execute(context))
event.listen(Engine, 'handle_error', _handle_cursor_error)


def _start_session_commit(session: Session) -> None:
    metrics = _DATABASE_STATEMENT_TIMING.get()
    if metrics is not None:
        session.info['_database_commit_started'] = time.perf_counter()


def _finish_session_commit(session: Session) -> None:
    metrics = _DATABASE_STATEMENT_TIMING.get()
    started = session.info.pop('_database_commit_started', None)
    if metrics is not None and isinstance(started, (int, float)):
        _record_database_duration(metrics, 'commit_ms', (time.perf_counter() - started) * 1000)


event.listen(Session, 'before_commit', _start_session_commit)
event.listen(Session, 'after_commit', _finish_session_commit)
event.listen(Session, 'after_rollback', _finish_session_commit)


def set_active_runtime_coordinator_generation(generation: int | None) -> None:
    global _ACTIVE_RUNTIME_COORDINATOR_GENERATION
    if generation is not None and generation < 1:
        raise ValueError('Runtime coordinator generation must be positive')
    _ACTIVE_RUNTIME_COORDINATOR_GENERATION = generation


def active_runtime_coordinator_generation() -> int | None:
    return _ACTIVE_RUNTIME_COORDINATOR_GENERATION


def _fence_runtime_transaction(session: Session, _transaction, connection: Connection) -> None:
    del session
    generation = _ACTIVE_RUNTIME_COORDINATOR_GENERATION
    if generation is None or connection.dialect.name != 'postgresql':
        return
    current_generation = connection.execute(
        text('SELECT generation FROM public.runtime_coordinator_state WHERE singleton_id = 1 FOR SHARE')
    ).scalar_one_or_none()
    if current_generation != generation:
        raise RuntimeCoordinatorFenced(f'Runtime coordinator generation {generation} is fenced by generation {current_generation}')


event.listen(Session, 'after_begin', _fence_runtime_transaction)


def _track_pool_checkouts(engine: Engine, pool_name: str) -> None:
    engine_id = id(engine)

    def checkout(_dbapi_connection, record, _connection_proxy) -> None:
        owner = (time.monotonic(), threading.get_ident(), threading.current_thread().name)
        with _POOL_CHECKOUTS_LOCK:
            _POOL_CHECKOUTS[(engine_id, id(record))] = owner

    def checkin(_dbapi_connection, record) -> None:
        with _POOL_CHECKOUTS_LOCK:
            _POOL_CHECKOUTS.pop((engine_id, id(record)), None)

    event.listen(engine, 'checkout', checkout)
    event.listen(engine, 'checkin', checkin)


def _pool_checkout_snapshot(engine: Engine, pool_name: str) -> dict[str, int | str]:
    now = time.monotonic()
    with _POOL_CHECKOUTS_LOCK:
        checkouts = [
            (started_at, thread_id, thread_name)
            for (engine_id, _record_id), (started_at, thread_id, thread_name) in _POOL_CHECKOUTS.items()
            if engine_id == id(engine)
        ]
    if not checkouts:
        return {}

    checkouts.sort(key=lambda checkout: checkout[0])
    frames = sys._current_frames()
    owners: list[str] = []
    for started_at, thread_id, thread_name in checkouts[:3]:
        frame = frames.get(thread_id)
        location = 'thread-not-running'
        while frame is not None:
            filename = frame.f_code.co_filename.replace('\\', '/')
            is_application_frame = (
                '/packages/backend/' in filename
                and '/.venv/' not in filename
                and '/site-packages/' not in filename
                and not filename.endswith('/backend_core/database.py')
            )
            if is_application_frame:
                location = f'{filename.rsplit("/", 1)[-1]}:{frame.f_lineno}:{frame.f_code.co_name}'
                break
            frame = frame.f_back
        owners.append(f'{thread_name}:{location}:{max(0, int((now - started_at) * 1000))}ms')
    return {
        f'{pool_name}_checkout_oldest_ms': max(0, int((now - checkouts[0][0]) * 1000)),
        f'{pool_name}_checkout_owners': '|'.join(owners),
    }


_RUNTIME_CRITICAL_POOL_SIZE = 0


def _runtime_database_pool_split(pool_size: int, max_overflow: int) -> tuple[int, int, int]:
    """Reserve a small internal pool for coordinator lease/liveness transactions.

    The total connection ceiling remains ``pool_size + max_overflow``. The
    general pool gives up base connections only when the dedicated coordinator
    pool is enabled; this is not another deployment limit.
    """
    if pool_size <= 1:
        return pool_size, max_overflow, 0
    critical_pool_size = min(4, max(1, pool_size // 2))
    return pool_size - critical_pool_size, max_overflow, critical_pool_size


def configure_runtime_critical_database_budget() -> int:
    """Reserve coordinator-only SQL capacity before any database engine starts."""
    global _RUNTIME_CRITICAL_POOL_SIZE
    if _RUNTIME_CRITICAL_POOL_SIZE:
        return _RUNTIME_CRITICAL_POOL_SIZE
    if settings_engine is not None or tenant_engine is not None:
        raise RuntimeError('Runtime critical DB budget must be configured before database engines are created')
    _general_pool_size, _max_overflow, _RUNTIME_CRITICAL_POOL_SIZE = _runtime_database_pool_split(
        settings.database_pool_size,
        settings.database_max_overflow,
    )
    return _RUNTIME_CRITICAL_POOL_SIZE


def _engine_kwargs() -> dict[str, object]:
    general_pool_size, max_overflow, _critical_pool_size = _runtime_database_pool_split(
        settings.database_pool_size,
        settings.database_max_overflow,
    )
    if not _RUNTIME_CRITICAL_POOL_SIZE:
        general_pool_size = settings.database_pool_size
    return {
        'poolclass': _TimedQueuePool,
        'pool_pre_ping': True,
        'pool_size': general_pool_size,
        'max_overflow': max_overflow,
        'pool_timeout': settings.database_pool_timeout,
    }


def _create_engine(
    url: str,
    *,
    pool_name: str,
    connect_args: dict[str, object] | None = None,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> Engine:
    kwargs = _engine_kwargs()
    if pool_size is not None:
        kwargs['pool_size'] = pool_size
    if max_overflow is not None:
        kwargs['max_overflow'] = max_overflow
    if connect_args is not None:
        kwargs['connect_args'] = connect_args
    engine = create_engine(url, echo=settings.sql_echo, **kwargs)
    _track_pool_checkouts(engine, pool_name)
    return engine


settings_engine: Engine | None = None
tenant_engine: Engine | None = None
critical_settings_engine: Engine | None = None
critical_tenant_engine: Engine | None = None
_settings_engine_lock = Lock()
_tenant_engine_lock = Lock()
_critical_settings_engine_lock = Lock()
_critical_tenant_engine_lock = Lock()

_engine_override: Engine | None = None
_settings_engine_override: Engine | None = None
_settings_bootstrap_hook: Callable[[Session], None] | None = None


def register_settings_bootstrap_hook(hook: Callable[[Session], None] | None) -> None:
    global _settings_bootstrap_hook
    _settings_bootstrap_hook = hook


def set_engine_override(test_engine: Engine):
    global _engine_override
    _engine_override = test_engine


def clear_engine_override():
    global _engine_override
    _engine_override = None


def set_settings_engine_override(test_engine: Engine):
    global _settings_engine_override
    _settings_engine_override = test_engine


def clear_settings_engine_override():
    global _settings_engine_override
    _settings_engine_override = None


def _set_postgres_search_path(raw_connection: object, namespace: str) -> None:
    cursor = getattr(raw_connection, 'cursor', None)
    if not callable(cursor):
        return
    schema = namespace_database_schema(namespace)
    db_cursor = cursor()
    try:
        db_cursor.execute(f'SET search_path TO "{schema}", {_PUBLIC_SCHEMA}')
    finally:
        db_cursor.close()


def _apply_postgres_search_path(connection: Connection, namespace: str) -> None:
    if connection.dialect.name != 'postgresql':
        return
    schema = namespace_database_schema(namespace)
    connection.execute(text(f'SET search_path TO "{schema}", {_PUBLIC_SCHEMA}'))


def _create_public_engine(*, critical: bool = False) -> Engine:
    pool_size = _RUNTIME_CRITICAL_POOL_SIZE if critical else None
    engine = _create_engine(
        settings.database_url,
        pool_name='settings-critical' if critical else 'settings',
        connect_args={'options': f'-c search_path={_PUBLIC_SCHEMA}'},
        pool_size=pool_size if critical else None,
        max_overflow=0 if critical else None,
    )

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
            tenant_engine = _create_engine(settings.database_url, pool_name='tenant')

            @event.listens_for(tenant_engine, 'checkout')
            def _set_namespace_search_path(dbapi_connection, _connection_record, _connection_proxy) -> None:
                _set_postgres_search_path(dbapi_connection, get_namespace())

        return tenant_engine


def _get_critical_settings_engine() -> Engine:
    global critical_settings_engine
    if _settings_engine_override is not None:
        return _settings_engine_override
    if not _RUNTIME_CRITICAL_POOL_SIZE:
        return get_settings_engine()
    if critical_settings_engine is not None:
        return critical_settings_engine
    with _critical_settings_engine_lock:
        if critical_settings_engine is None:
            critical_settings_engine = _create_public_engine(critical=True)
        return critical_settings_engine


def _get_critical_tenant_engine() -> Engine:
    global critical_tenant_engine
    if _engine_override is not None:
        return _engine_override
    if not _RUNTIME_CRITICAL_POOL_SIZE:
        return _get_tenant_engine()
    if critical_tenant_engine is not None:
        return critical_tenant_engine
    with _critical_tenant_engine_lock:
        if critical_tenant_engine is None:
            critical_tenant_engine = _create_engine(
                settings.database_url,
                pool_name='tenant-critical',
                pool_size=_RUNTIME_CRITICAL_POOL_SIZE,
                max_overflow=0,
            )

            @event.listens_for(critical_tenant_engine, 'checkout')
            def _set_critical_namespace_search_path(dbapi_connection, _connection_record, _connection_proxy) -> None:
                _set_postgres_search_path(dbapi_connection, get_namespace())

        return critical_tenant_engine


@contextmanager
def namespace_connection(namespace: str) -> Generator[Connection]:
    engine = _get_tenant_engine()
    with engine.begin() as connection:
        _apply_postgres_search_path(connection, namespace)
        yield connection


def get_db():
    engine_to_use = _get_tenant_engine()
    with Session(engine_to_use) as session:
        yield session


def get_settings_db():
    engine_to_use = get_settings_engine()
    with Session(engine_to_use) as session:
        yield session


def run_db[**P, T](func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = _get_tenant_engine()
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def run_settings_db[**P, T](func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = get_settings_engine()
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def run_critical_db[**P, T](func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run a short lease-critical tenant transaction on its reserved pool."""
    with Session(_get_critical_tenant_engine()) as session:
        return func(session, *args, **kwargs)


def run_critical_settings_db[**P, T](func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run a short worker/scheduler heartbeat transaction on its reserved pool."""
    with Session(_get_critical_settings_engine()) as session:
        return func(session, *args, **kwargs)


def database_pool_snapshot() -> dict[str, object]:
    """Return non-blocking pool counters for slow-request diagnostics."""
    snapshots: dict[str, object] = {}
    engines: list[tuple[str, Engine | None]] = [
        ('settings', _settings_engine_override or settings_engine),
        ('tenant', _engine_override or tenant_engine),
        ('critical_settings', _settings_engine_override or critical_settings_engine),
        ('critical_tenant', _engine_override or critical_tenant_engine),
    ]
    seen: set[int] = set()
    for name, engine in engines:
        if engine is None or id(engine) in seen:
            continue
        seen.add(id(engine))
        pool = getattr(engine, 'pool', None)
        if pool is None:
            continue
        for field in ('size', 'checkedin', 'checkedout', 'overflow'):
            value = getattr(pool, field, None)
            if not callable(value):
                continue
            try:
                snapshots[f'{name}_{field}'] = int(value())
            except Exception:
                continue
        checkout_snapshot = _pool_checkout_snapshot(engine, name)
        if checkout_snapshot:
            snapshots.setdefault('process_id', os.getpid())
            snapshots.update(checkout_snapshot)
    return snapshots


def _shared_tables():
    from backend_core.persistence.engine_instances.models import EngineInstance
    from backend_core.persistence.mcp_pending.models import McpPendingAction
    from backend_core.persistence.namespaces.models import NamespaceEngineCredential, RuntimeNamespace
    from backend_core.persistence.runtime_events.models import RuntimeCoordinatorState, RuntimeNamespaceWork, RuntimeNamespaceWorkWake
    from backend_core.persistence.runtime_workers.models import RuntimeWorker
    from backend_core.persistence.settings.models import AppSettings
    from modules.chat.models import ChatEvent, ChatMessage, ChatSession, ChatTurn

    table_names = {
        AppSettings.__tablename__,
        EngineInstance.__tablename__,
        McpPendingAction.__tablename__,
        NamespaceEngineCredential.__tablename__,
        RuntimeNamespace.__tablename__,
        RuntimeCoordinatorState.__tablename__,
        RuntimeNamespaceWork.__tablename__,
        RuntimeNamespaceWorkWake.__tablename__,
        RuntimeWorker.__tablename__,
        ChatSession.__tablename__,
        ChatTurn.__tablename__,
        ChatMessage.__tablename__,
        ChatEvent.__tablename__,
    }
    return [table for table in AppSettings.metadata.sorted_tables if table.name in table_names]


def _tenant_tables():
    from backend_core.persistence.analysis.models import Analysis, AnalysisDataSource, AnalysisFavorite
    from backend_core.persistence.analysis_versions.models import AnalysisVersion
    from backend_core.persistence.build_jobs.models import BuildJob
    from backend_core.persistence.build_runs.models import BuildEvent, BuildRun, BuildRunDatasource
    from backend_core.persistence.compute_requests.models import ComputeRequest, ComputeRequestDatasource, ComputeRequestFlight
    from backend_core.persistence.datasource.models import DataSource, DataSourceColumnMetadata
    from backend_core.persistence.engine_runs.models import EngineRun
    from backend_core.persistence.healthchecks.models import HealthCheck, HealthCheckResult
    from backend_core.persistence.locks.models import ResourceLock
    from backend_core.persistence.runtime_events.models import NotificationDeliveryPartReceipt, NotificationDeliveryReceipt, RuntimeOutboxEvent
    from backend_core.persistence.scheduler.models import Schedule
    from backend_core.persistence.telegram.models import TelegramListener, TelegramSubscriber
    from backend_core.persistence.udfs.models import Udf

    table_names = {
        Analysis.__tablename__,
        AnalysisDataSource.__tablename__,
        AnalysisFavorite.__tablename__,
        AnalysisVersion.__tablename__,
        BuildEvent.__tablename__,
        BuildJob.__tablename__,
        BuildRun.__tablename__,
        BuildRunDatasource.__tablename__,
        ComputeRequest.__tablename__,
        ComputeRequestDatasource.__tablename__,
        ComputeRequestFlight.__tablename__,
        DataSource.__tablename__,
        DataSourceColumnMetadata.__tablename__,
        EngineRun.__tablename__,
        HealthCheck.__tablename__,
        HealthCheckResult.__tablename__,
        ResourceLock.__tablename__,
        RuntimeOutboxEvent.__tablename__,
        NotificationDeliveryReceipt.__tablename__,
        NotificationDeliveryPartReceipt.__tablename__,
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
    from backend_core.migrations import migrate_runtime

    # Alembic's EnvironmentContext uses process-global proxy state and cannot
    # run two upgrades concurrently in one API process, even for different
    # tenant schemas. The PostgreSQL advisory lock below provides
    # cross-process namespace ownership; this lock protects Alembic itself.
    with _ALEMBIC_MIGRATION_LOCK:
        migrate_runtime([namespace])


def _seed_shared_state() -> None:
    from backend_core.namespaces_service import register_namespace

    def _seed(session: Session) -> None:
        if _settings_bootstrap_hook is not None:
            _settings_bootstrap_hook(session)
        register_namespace(session, settings.default_namespace)

    run_settings_db(_seed)


def run_settings_connection_locked[T](func: Callable[[Connection], T]) -> T:
    engine = get_settings_engine()
    with engine.begin() as connection:
        if connection.dialect.name != 'postgresql':
            return func(connection)
        # Bind the lock to this transaction so a failed DDL transaction rolls
        # back and releases it without a second SQL statement that would be
        # rejected by PostgreSQL while the transaction is already aborted.
        connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _POSTGRES_INIT_LOCK_KEY})
        return func(connection)


def _run_postgres_init_locked(func) -> None:
    from backend_core.migrations import ensure_database_exists

    ensure_database_exists(settings.database_url)
    run_settings_connection_locked(lambda _connection: func())


def _namespace_init_lock_key(namespace: str) -> int:
    raw = f'{_NAMESPACE_INIT_LOCK_PREFIX}{normalize_namespace(namespace)}'.encode()
    return int.from_bytes(sha256(raw).digest()[:8], 'big', signed=True)


def _namespace_provision_lock_key(namespace: str) -> int:
    raw = f'{_NAMESPACE_PROVISION_LOCK_PREFIX}{normalize_namespace(namespace)}'.encode()
    return int.from_bytes(sha256(raw).digest()[:8], 'big', signed=True)


@contextmanager
def _postgres_advisory_lock(lock_key: int) -> Iterator[None]:
    """Hold a PostgreSQL advisory lock without checking out an ORM pool connection."""
    import psycopg

    database_url = settings.database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute('SELECT pg_advisory_lock(%s)', (lock_key,))
        try:
            yield
        finally:
            connection.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))


@contextmanager
def namespace_provision_lock(namespace: str) -> Generator[None]:
    """Fence namespace provisioning across API processes without using the DB pool."""
    if get_settings_engine().dialect.name != 'postgresql':
        yield
        return
    with _postgres_advisory_lock(_namespace_provision_lock_key(namespace)):
        yield


def _run_namespace_init_locked(namespace: str, func: Callable[[], None]) -> None:
    """Serialize migrations for one namespace without blocking other tenants."""
    from backend_core.migrations import ensure_database_exists

    ensure_database_exists(settings.database_url)
    if get_settings_engine().dialect.name != 'postgresql':
        func()
        return
    with _postgres_advisory_lock(_namespace_init_lock_key(namespace)):
        func()


def initialize_namespace_db(namespace: str) -> None:
    """Create and migrate a namespace schema before exposing it to clients."""
    if _engine_override is not None:
        return
    normalized = normalize_namespace(namespace)
    _run_namespace_init_locked(normalized, lambda: _init_postgres_namespace(normalized))


def _bootstrap_postgres() -> None:
    from backend_core.migrations import migrate_runtime

    namespaces = list_namespaces()
    if settings.default_namespace not in namespaces:
        namespaces = [*namespaces, settings.default_namespace]
    normalized = [normalize_namespace(namespace) for namespace in namespaces]
    with _ALEMBIC_MIGRATION_LOCK:
        migrate_runtime(normalized)
    for namespace in normalized:
        namespace_paths(namespace)


async def init_db() -> None:
    def _init_postgres() -> None:
        _bootstrap_postgres()
        _seed_shared_state()

    await run_api_blocking(_run_postgres_init_locked, _init_postgres)


def supports_distributed_runtime() -> bool:
    return settings.distributed_runtime_enabled
