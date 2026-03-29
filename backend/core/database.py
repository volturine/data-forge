from collections import OrderedDict
from collections.abc import Callable
from typing import Concatenate, ParamSpec, TypeVar

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


settings_engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={},
)
_enable_sqlite_pragmas(settings_engine)

_namespace_engines: OrderedDict[str, Engine] = OrderedDict()
_MAX_NAMESPACE_ENGINES = 50

# Engine override for testing - allows tests to swap the engine used by run_db
_engine_override: Engine | None = None

P = ParamSpec('P')
T = TypeVar('T')


def set_engine_override(test_engine: Engine):
    global _engine_override
    _engine_override = test_engine


def clear_engine_override():
    global _engine_override
    _engine_override = None


def get_db():
    engine_to_use = _engine_override or _get_namespace_engine()
    with Session(engine_to_use) as session:
        yield session


def get_settings_db():
    with Session(settings_engine) as session:
        yield session


def run_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = _engine_override or _get_namespace_engine()
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def run_settings_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    with Session(settings_engine) as session:
        return func(session, *args, **kwargs)


def init_db() -> None:
    _init_settings_db()
    namespaces = list_namespaces()
    if not namespaces:
        namespaces = [settings.default_namespace]
    for namespace in namespaces:
        namespace_paths(namespace)
        _init_namespace_db(namespace)


def _init_settings_db() -> None:
    from modules.chat.sessions import ChatSession
    from modules.settings.models import AppSettings
    from modules.settings.service import seed_settings_from_env

    AppSettings.metadata.create_all(settings_engine)
    ChatSession.metadata.create_all(settings_engine)
    _run_settings_migrations(settings_engine)
    with Session(settings_engine) as session:
        seed_settings_from_env(session)


def _run_settings_migrations(db_engine: Engine) -> None:
    from sqlalchemy import inspect, text as sa_text

    inspector = inspect(db_engine)
    pending: list[str] = []

    if inspector.has_table('app_settings'):
        settings_columns = {col['name'] for col in inspector.get_columns('app_settings')}
        if 'telegram_bot_enabled' not in settings_columns:
            pending.append('ALTER TABLE app_settings ADD COLUMN telegram_bot_enabled BOOLEAN NOT NULL DEFAULT 0')
        if 'smtp_password_encrypted' not in settings_columns:
            pending.append("ALTER TABLE app_settings ADD COLUMN smtp_password_encrypted TEXT NOT NULL DEFAULT ''")
        if 'openrouter_api_key' not in settings_columns:
            pending.append("ALTER TABLE app_settings ADD COLUMN openrouter_api_key TEXT NOT NULL DEFAULT ''")
        if 'openrouter_default_model' not in settings_columns:
            pending.append("ALTER TABLE app_settings ADD COLUMN openrouter_default_model TEXT NOT NULL DEFAULT ''")
        if 'env_bootstrap_complete' not in settings_columns:
            pending.append('ALTER TABLE app_settings ADD COLUMN env_bootstrap_complete BOOLEAN NOT NULL DEFAULT 1')

    if inspector.has_table('chat_sessions'):
        chat_columns = {col['name'] for col in inspector.get_columns('chat_sessions')}
        if 'system_prompt' not in chat_columns:
            pending.append("ALTER TABLE chat_sessions ADD COLUMN system_prompt TEXT NOT NULL DEFAULT ''")

    if pending:
        with db_engine.connect() as conn:
            for sql in pending:
                conn.execute(sa_text(sql))
            conn.commit()


def _run_namespace_migrations(db_engine: Engine) -> None:
    from sqlalchemy import inspect, text as sa_text

    inspector = inspect(db_engine)
    pending: list[str] = []

    if inspector.has_table('engine_runs'):
        columns = {col['name'] for col in inspector.get_columns('engine_runs')}
        if 'triggered_by' not in columns:
            pending.append('ALTER TABLE engine_runs ADD COLUMN triggered_by TEXT')

    if inspector.has_table('datasources'):
        ds_columns = {col['name'] for col in inspector.get_columns('datasources')}
        if 'is_hidden' not in ds_columns:
            pending.append('ALTER TABLE datasources ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT 0')
        if 'created_by' not in ds_columns:
            pending.append("ALTER TABLE datasources ADD COLUMN created_by TEXT NOT NULL DEFAULT 'import'")

    if inspector.has_table('schedules'):
        sched_columns = {col['name'] for col in inspector.get_columns('schedules')}
        if 'datasource_id' not in sched_columns:
            pending.append('ALTER TABLE schedules ADD COLUMN datasource_id TEXT')
        if 'depends_on' not in sched_columns:
            pending.append('ALTER TABLE schedules ADD COLUMN depends_on TEXT')
        if 'trigger_on_datasource_id' not in sched_columns:
            pending.append('ALTER TABLE schedules ADD COLUMN trigger_on_datasource_id TEXT')

    if inspector.has_table('healthchecks'):
        hc_columns = {col['name'] for col in inspector.get_columns('healthchecks')}
        if 'critical' not in hc_columns:
            pending.append('ALTER TABLE healthchecks ADD COLUMN critical BOOLEAN NOT NULL DEFAULT 0')

    if pending:
        with db_engine.connect() as conn:
            for sql in pending:
                conn.execute(sa_text(sql))
            conn.commit()


def _get_namespace_engine() -> Engine:
    namespace = get_namespace()
    if namespace in _namespace_engines:
        _namespace_engines.move_to_end(namespace)
        return _namespace_engines[namespace]
    if len(_namespace_engines) >= _MAX_NAMESPACE_ENGINES:
        oldest = next(iter(_namespace_engines))
        del _namespace_engines[oldest]
    paths = namespace_paths(namespace)
    engine = create_engine(f'sqlite:///{paths.db_path}', echo=settings.debug, connect_args={})
    _enable_sqlite_pragmas(engine)
    _namespace_engines[namespace] = engine
    _init_namespace_db(namespace)
    return engine


def _init_namespace_db(namespace: str) -> None:
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
    from modules.scheduler.models import Schedule
    from modules.telegram.models import TelegramListener, TelegramSubscriber
    from modules.udf.models import Udf

    Analysis.metadata.create_all(namespace_engine)
    AnalysisDataSource.metadata.create_all(namespace_engine)
    AnalysisVersion.metadata.create_all(namespace_engine)
    DataSource.metadata.create_all(namespace_engine)
    EngineRun.metadata.create_all(namespace_engine)
    HealthCheck.metadata.create_all(namespace_engine)
    HealthCheckResult.metadata.create_all(namespace_engine)
    Schedule.metadata.create_all(namespace_engine)
    TelegramListener.metadata.create_all(namespace_engine)
    TelegramSubscriber.metadata.create_all(namespace_engine)
    Udf.metadata.create_all(namespace_engine)
    _run_namespace_migrations(namespace_engine)
