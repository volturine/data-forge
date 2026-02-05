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
    SQLModel.metadata.create_all(engine)
