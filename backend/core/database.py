from collections.abc import Callable
from typing import Concatenate, ParamSpec, TypeVar

from sqlmodel import Session, SQLModel, create_engine

from core.config import settings


def _build_connect_args() -> dict:
    if 'libsql' not in settings.database_url:
        return {}
    if not settings.turso_database_url:
        return {}
    args: dict[str, object] = {
        'sync_url': settings.turso_database_url,
        'auth_token': settings.turso_auth_token,
    }
    if settings.turso_sync_interval:
        args['sync_interval'] = settings.turso_sync_interval
    return args


engine = create_engine(
    settings.database_url,
    echo=settings.debug,  # Only log SQL queries in debug mode
    connect_args=_build_connect_args(),
)

# Engine override for testing - allows tests to swap the engine used by run_db
_engine_override = None

P = ParamSpec('P')
T = TypeVar('T')


def set_engine_override(test_engine):
    """Set an engine override for testing purposes.

    This allows tests to inject a test engine that will be used by run_db
    instead of the production engine.
    """
    global _engine_override
    _engine_override = test_engine


def clear_engine_override():
    """Clear the engine override after testing."""
    global _engine_override
    _engine_override = None


def get_db():
    engine_to_use = _engine_override or engine
    with Session(engine_to_use) as session:
        yield session


def run_db(func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    engine_to_use = _engine_override or engine
    with Session(engine_to_use) as session:
        return func(session, *args, **kwargs)


def init_db() -> None:
    engine_to_use = _engine_override or engine
    SQLModel.metadata.create_all(engine_to_use)
    _run_migrations(engine_to_use)


def _run_migrations(db_engine) -> None:
    """Apply incremental schema migrations for columns added after initial table creation."""
    from sqlalchemy import inspect, text as sa_text

    inspector = inspect(db_engine)
    if not inspector.has_table('engine_runs'):
        return

    columns = {col['name'] for col in inspector.get_columns('engine_runs')}
    with db_engine.connect() as conn:
        if 'triggered_by' not in columns:
            conn.execute(sa_text('ALTER TABLE engine_runs ADD COLUMN triggered_by TEXT'))
            conn.commit()

    # Datasources: add is_hidden column
    if inspector.has_table('datasources'):
        ds_columns = {col['name'] for col in inspector.get_columns('datasources')}
        with db_engine.connect() as conn:
            if 'is_hidden' not in ds_columns:
                conn.execute(sa_text('ALTER TABLE datasources ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT 0'))
                conn.commit()
            if 'created_by' not in ds_columns:
                conn.execute(sa_text("ALTER TABLE datasources ADD COLUMN created_by TEXT NOT NULL DEFAULT 'import'"))
                conn.commit()

    # Schedules: add datasource_id column
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

    # App settings: add telegram_bot_enabled column
    if inspector.has_table('app_settings'):
        settings_columns = {col['name'] for col in inspector.get_columns('app_settings')}
        with db_engine.connect() as conn:
            if 'telegram_bot_enabled' not in settings_columns:
                conn.execute(sa_text('ALTER TABLE app_settings ADD COLUMN telegram_bot_enabled BOOLEAN NOT NULL DEFAULT 0'))
                conn.commit()
            if 'smtp_password_encrypted' not in settings_columns:
                conn.execute(sa_text("ALTER TABLE app_settings ADD COLUMN smtp_password_encrypted TEXT NOT NULL DEFAULT ''"))
                conn.commit()

    if inspector.has_table('healthchecks'):
        hc_columns = {col['name'] for col in inspector.get_columns('healthchecks')}
        with db_engine.connect() as conn:
            if 'critical' not in hc_columns:
                conn.execute(sa_text('ALTER TABLE healthchecks ADD COLUMN critical BOOLEAN NOT NULL DEFAULT 0'))
                conn.commit()
