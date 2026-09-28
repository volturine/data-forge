import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from backend_core import database
from backend_core.database import clear_engine_override, get_db, set_engine_override
from backend_core.namespace import reset_namespace, set_namespace_context


def test_get_db_session_is_lazy_about_connection_checkout() -> None:
    engine = create_engine('sqlite:///:memory:')
    checkouts: list[object] = []

    @event.listens_for(engine, 'checkout')
    def _track_checkout(dbapi_connection, _connection_record, _connection_proxy) -> None:
        checkouts.append(dbapi_connection)

    set_engine_override(engine)
    token = set_namespace_context('default')
    session_gen = None
    session: Session | None = None
    try:
        session_gen = get_db()
        session = next(session_gen)

        assert checkouts == []

        session.connection()

        assert len(checkouts) == 1
    finally:
        if session is not None:
            session.close()
        if session_gen is not None:
            session_gen.close()
        reset_namespace(token)
        clear_engine_override()


@pytest.mark.asyncio
async def test_async_api_session_dependencies_close_on_the_bounded_executor(monkeypatch) -> None:
    engine = create_engine(
        'sqlite:///:memory:',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(database, '_get_tenant_engine', lambda: engine)
    monkeypatch.setattr(database, 'get_settings_engine', lambda: engine)

    loop_thread = threading.get_ident()
    close_threads: list[int] = []
    original_close = Session.close

    def tracked_close(session: Session) -> None:
        close_threads.append(threading.get_ident())
        original_close(session)

    monkeypatch.setattr(Session, 'close', tracked_close)
    for dependency in (database.get_db_async(), database.get_settings_db_async()):
        session = await anext(dependency)
        await asyncio.to_thread(session.execute, text('SELECT 1'))
        await dependency.aclose()
        assert not session.in_transaction()

    assert len(close_threads) == 2
    assert all(thread_id != loop_thread for thread_id in close_threads)
    engine.dispose()


def test_database_statement_timing_collects_sql_and_commit_costs() -> None:
    engine = create_engine('sqlite:///:memory:')
    metrics: dict[str, object] = {'sql_count': 0, 'sql_ms': 0.0, 'commit_ms': 0.0}

    with database.database_statement_timing(metrics), Session(engine) as session:
        session.execute(text('SELECT 1'))
        session.commit()

    engine.dispose()
    assert isinstance(metrics['sql_count'], int) and metrics['sql_count'] >= 1
    assert isinstance(metrics['sql_ms'], (int, float)) and float(metrics['sql_ms']) >= 0
    assert isinstance(metrics['commit_ms'], (int, float)) and float(metrics['commit_ms']) >= 0


def test_request_database_access_does_not_run_namespace_migrations(monkeypatch) -> None:
    engine = create_engine('sqlite:///:memory:')
    migrations: list[str] = []
    monkeypatch.setattr(database, '_get_tenant_engine', lambda: engine)
    monkeypatch.setattr(database, '_run_namespace_init_locked', lambda namespace, _initialize: migrations.append(namespace))
    token = set_namespace_context(f'request-path-{time.time_ns()}')
    session_gen = None
    session: Session | None = None
    try:
        session_gen = get_db()
        session = next(session_gen)
        assert database.run_db(lambda _session: 'available') == 'available'
    finally:
        if session is not None:
            session.close()
        if session_gen is not None:
            session_gen.close()
        reset_namespace(token)
        engine.dispose()

    assert migrations == []


def test_database_startup_runs_postgres_bootstrap_off_event_loop(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    setup_threads: list[int] = []

    def run_locked(initializer) -> None:
        setup_threads.append(threading.get_ident())
        initializer()

    monkeypatch.setattr(database, '_run_postgres_init_locked', run_locked)
    monkeypatch.setattr(database, '_bootstrap_postgres', lambda: setup_threads.append(threading.get_ident()))
    monkeypatch.setattr(database, '_seed_shared_state', lambda: setup_threads.append(threading.get_ident()))

    asyncio.run(database.init_db())

    assert len(setup_threads) == 3
    assert all(thread_id != loop_thread for thread_id in setup_threads)


def test_namespace_provision_lock_serializes_concurrent_sessions() -> None:
    def max_concurrent_provisions(names: tuple[str, str]) -> int:
        ready = threading.Barrier(3)
        active = 0
        max_active = 0
        state_lock = threading.Lock()

        def provision(name: str) -> None:
            nonlocal active, max_active
            ready.wait(timeout=5)
            with database.namespace_provision_lock(name):
                with state_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.1)
                with state_lock:
                    active -= 1

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(provision, name) for name in names]
            ready.wait(timeout=5)
            for future in futures:
                future.result(timeout=10)
        return max_active

    assert max_concurrent_provisions(('same-namespace', 'same-namespace')) == 1
    assert max_concurrent_provisions(('namespace-a', 'namespace-b')) == 2


def test_namespace_migration_holds_advisory_lock_without_checking_out_pool_connection(monkeypatch) -> None:
    lock_key = database._namespace_init_lock_key('tenant-a')
    lock_entered = False

    class PostgresEngine:
        dialect = SimpleNamespace(name='postgresql')

        def begin(self):
            raise AssertionError('Migration lock must not hold a pooled SQLAlchemy connection')

    @contextmanager
    def advisory_lock(actual_key: int):
        nonlocal lock_entered
        assert actual_key == lock_key
        lock_entered = True
        try:
            yield
        finally:
            lock_entered = False

    monkeypatch.setattr(database, 'get_settings_engine', lambda: PostgresEngine())
    monkeypatch.setattr(database, '_postgres_advisory_lock', advisory_lock)
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _url: None)

    def migrate() -> None:
        assert lock_entered

    database._run_namespace_init_locked('tenant-a', migrate)

    assert not lock_entered
