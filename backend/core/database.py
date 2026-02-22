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

_namespace_engines: dict[str, Engine] = {}

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
        _init_namespace_db(namespace)


def _init_settings_db() -> None:
    from modules.settings.models import AppSettings

    AppSettings.metadata.create_all(settings_engine)
    _run_settings_migrations(settings_engine)


def _run_settings_migrations(db_engine: Engine) -> None:
    from sqlalchemy import inspect, text as sa_text

    inspector = inspect(db_engine)
    if not inspector.has_table('app_settings'):
        return

    settings_columns = {col['name'] for col in inspector.get_columns('app_settings')}
    with db_engine.connect() as conn:
        if 'telegram_bot_enabled' not in settings_columns:
            conn.execute(sa_text('ALTER TABLE app_settings ADD COLUMN telegram_bot_enabled BOOLEAN NOT NULL DEFAULT 0'))
            conn.commit()
        if 'smtp_password_encrypted' not in settings_columns:
            conn.execute(sa_text("ALTER TABLE app_settings ADD COLUMN smtp_password_encrypted TEXT NOT NULL DEFAULT ''"))
            conn.commit()


def _run_namespace_migrations(db_engine: Engine) -> None:
    from sqlalchemy import inspect, text as sa_text

    inspector = inspect(db_engine)

    if inspector.has_table('engine_runs'):
        columns = {col['name'] for col in inspector.get_columns('engine_runs')}
        with db_engine.connect() as conn:
            if 'triggered_by' not in columns:
                conn.execute(sa_text('ALTER TABLE engine_runs ADD COLUMN triggered_by TEXT'))
                conn.commit()

    if inspector.has_table('datasources'):
        ds_columns = {col['name'] for col in inspector.get_columns('datasources')}
        with db_engine.connect() as conn:
            if 'is_hidden' not in ds_columns:
                conn.execute(sa_text('ALTER TABLE datasources ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT 0'))
                conn.commit()
            if 'created_by' not in ds_columns:
                conn.execute(sa_text("ALTER TABLE datasources ADD COLUMN created_by TEXT NOT NULL DEFAULT 'import'"))
                conn.commit()

    if inspector.has_table('schedules'):
        sched_columns = {col['name'] for col in inspector.get_columns('schedules')}
        with db_engine.connect() as conn:
            if 'datasource_id' not in sched_columns:
                conn.execute(sa_text('ALTER TABLE schedules ADD COLUMN datasource_id TEXT'))
                conn.commit()
            if 'depends_on' not in sched_columns:
                conn.execute(sa_text('ALTER TABLE schedules ADD COLUMN depends_on TEXT'))
                conn.commit()
            if 'trigger_on_datasource_id' not in sched_columns:
                conn.execute(sa_text('ALTER TABLE schedules ADD COLUMN trigger_on_datasource_id TEXT'))
                conn.commit()

    if inspector.has_table('healthchecks'):
        hc_columns = {col['name'] for col in inspector.get_columns('healthchecks')}
        with db_engine.connect() as conn:
            if 'critical' not in hc_columns:
                conn.execute(sa_text('ALTER TABLE healthchecks ADD COLUMN critical BOOLEAN NOT NULL DEFAULT 0'))
                conn.commit()


def _get_namespace_engine() -> Engine:
    namespace = get_namespace()
    if namespace in _namespace_engines:
        return _namespace_engines[namespace]
    paths = namespace_paths(namespace)
    engine_to_use = create_engine(
        f'sqlite:///{paths.db_path}',
        echo=settings.debug,
        connect_args={},
    )
    _enable_sqlite_pragmas(engine_to_use)
    _namespace_engines[namespace] = engine_to_use
    _init_namespace_db(namespace)
    return engine_to_use


def _init_namespace_db(namespace: str) -> None:
    paths = namespace_paths(namespace)
    namespace_engine = create_engine(
        f'sqlite:///{paths.db_path}',
        echo=settings.debug,
        connect_args={},
    )
    _enable_sqlite_pragmas(namespace_engine)
    from modules.analysis.models import Analysis, AnalysisDataSource
    from modules.analysis_versions.models import AnalysisVersion
    from modules.datasource.models import DataSource
    from modules.engine_runs.models import EngineRun
    from modules.healthcheck.models import HealthCheck, HealthCheckResult
    from modules.locks.models import Lock
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
    Lock.metadata.create_all(namespace_engine)
    Schedule.metadata.create_all(namespace_engine)
    TelegramListener.metadata.create_all(namespace_engine)
    TelegramSubscriber.metadata.create_all(namespace_engine)
    Udf.metadata.create_all(namespace_engine)
    _run_namespace_migrations(namespace_engine)
