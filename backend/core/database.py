import asyncio
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Any, Concatenate, ParamSpec, TypeVar

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from core.config import settings
from core.namespace import get_namespace, list_namespaces, namespace_paths


def _enable_sqlite_pragmas(engine: Engine) -> None:
    """Set WAL journal mode and busy_timeout on every new SQLite connection."""

    @event.listens_for(engine, 'connect')
    def _on_connect(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.close()


def _create_settings_engine() -> Engine:
    engine = create_engine(
        settings.database_url,
        echo=settings.debug,
        connect_args={},
    )
    _enable_sqlite_pragmas(engine)
    return engine


settings_engine: Engine | None = None
_settings_engine_lock = Lock()

_namespace_engines: OrderedDict[str, Engine] = OrderedDict()
_namespace_engines_lock = asyncio.Lock()
_MAX_NAMESPACE_ENGINES = 50

# Engine override for testing - allows tests to swap the engine used by run_db
_engine_override: Engine | None = None
_settings_engine_override: Engine | None = None

P = ParamSpec('P')
T = TypeVar('T')


def _run_async(value: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise RuntimeError('Cannot synchronously access namespace database while the event loop is running')


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


def get_db():
    engine_to_use = _engine_override or _run_async(_get_namespace_engine())
    with Session(engine_to_use) as session:
        yield session


def get_settings_db():
    engine_to_use = get_settings_engine()
    with Session(engine_to_use) as session:
        yield session


def run_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = _engine_override or _run_async(_get_namespace_engine())
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def run_settings_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = get_settings_engine()
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def get_settings_engine() -> Engine:
    global settings_engine

    if _settings_engine_override is not None:
        return _settings_engine_override
    if settings_engine is not None:
        return settings_engine

    with _settings_engine_lock:
        if settings_engine is None:
            settings_engine = _create_settings_engine()
        return settings_engine


async def init_db() -> None:
    _init_settings_db()
    namespaces = list_namespaces()
    if not namespaces:
        namespaces = [settings.default_namespace]
    for namespace in namespaces:
        namespace_paths(namespace)
        await _init_namespace_db(namespace)


def _init_settings_db() -> None:
    from modules.auth.models import AuthProvider, User, UserSession, VerificationToken
    from modules.auth.service import ensure_default_user
    from modules.chat.sessions import ChatSession
    from modules.settings.models import AppSettings
    from modules.settings.service import invalidate_resolved_settings_cache, seed_settings_from_env

    engine_to_use = get_settings_engine()
    table_names = {
        AppSettings.__tablename__,
        ChatSession.__tablename__,
        User.__tablename__,
        AuthProvider.__tablename__,
        UserSession.__tablename__,
        VerificationToken.__tablename__,
    }
    tables = [table for table in AppSettings.metadata.sorted_tables if table.name in table_names]

    AppSettings.metadata.create_all(engine_to_use, tables=tables)
    with Session(engine_to_use) as session:
        seed_settings_from_env(session)
        ensure_default_user(session)
    invalidate_resolved_settings_cache()


async def _get_namespace_engine() -> Engine:
    namespace = get_namespace()
    async with _namespace_engines_lock:
        if namespace in _namespace_engines:
            _namespace_engines.move_to_end(namespace)
            return _namespace_engines[namespace]
        if len(_namespace_engines) >= _MAX_NAMESPACE_ENGINES:
            oldest = next(iter(_namespace_engines))
            _namespace_engines.pop(oldest).dispose()
        paths = namespace_paths(namespace)
        engine = create_engine(f'sqlite:///{paths.db_path}', echo=settings.debug, connect_args={})
        _enable_sqlite_pragmas(engine)
        _namespace_engines[namespace] = engine
        _init_namespace_db_unlocked(namespace)
        return engine


async def _init_namespace_db(namespace: str) -> None:
    async with _namespace_engines_lock:
        _init_namespace_db_unlocked(namespace)


def _init_namespace_db_unlocked(namespace: str) -> None:
    namespace_engine = _namespace_engines.get(namespace)
    if not namespace_engine:
        paths = namespace_paths(namespace)
        namespace_engine = create_engine(
            f'sqlite:///{paths.db_path}',
            echo=settings.debug,
            connect_args={},
        )
        _enable_sqlite_pragmas(namespace_engine)
        _namespace_engines[namespace] = namespace_engine
    from modules.analysis.models import Analysis, AnalysisDataSource
    from modules.analysis_versions.models import AnalysisVersion
    from modules.datasource.models import DataSource
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
        DataSource.__tablename__,
        EngineRun.__tablename__,
        HealthCheck.__tablename__,
        HealthCheckResult.__tablename__,
        ResourceLock.__tablename__,
        Schedule.__tablename__,
        TelegramListener.__tablename__,
        TelegramSubscriber.__tablename__,
        Udf.__tablename__,
    }
    tables = [table for table in Analysis.metadata.sorted_tables if table.name in table_names]

    Analysis.metadata.create_all(namespace_engine, tables=tables)
