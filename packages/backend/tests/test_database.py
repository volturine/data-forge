import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import event, text
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


def test_runtime_critical_pool_is_carved_from_the_configured_connection_ceiling() -> None:
    general_size, overflow, critical_size = database._runtime_database_pool_split(8, 4)

    assert (general_size, overflow, critical_size) == (4, 4, 4)
    assert general_size + overflow + critical_size == 8 + 4
    assert database._runtime_database_pool_split(4, 0) == (2, 0, 2)
    assert database._runtime_database_pool_split(1, 0) == (1, 0, 0)


def test_critical_db_helpers_run_sessions_on_their_reserved_engines(monkeypatch) -> None:
    engine = create_engine('sqlite:///:memory:')
    monkeypatch.setattr(database, '_get_critical_tenant_engine', lambda: engine)
    monkeypatch.setattr(database, '_get_critical_settings_engine', lambda: engine)

    def query(session: Session) -> int:
        return session.execute(text('SELECT 1')).scalar_one()

    try:
        assert database.run_critical_db(query) == 1
        assert database.run_critical_settings_db(query) == 1
    finally:
        engine.dispose()


def test_database_statement_timing_collects_sql_and_commit_costs() -> None:
    engine = database._create_engine('sqlite:///:memory:', pool_name='statement-timing')
    metrics: dict[str, object] = {'sql_count': 0, 'sql_ms': 0.0, 'commit_ms': 0.0}

    with database.database_statement_timing(metrics), Session(engine) as session:
        session.execute(text("SELECT 'sensitive-value', 123"))
        session.commit()

    engine.dispose()
    assert isinstance(metrics['sql_count'], int) and metrics['sql_count'] >= 1
    assert isinstance(metrics['sql_ms'], (int, float)) and float(metrics['sql_ms']) >= 0
    assert isinstance(metrics['slowest_sql_ms'], (int, float)) and float(metrics['slowest_sql_ms']) >= 0
    assert str(metrics['slowest_sql_statement']).startswith('SELECT')
    assert 'sensitive-value' not in str(metrics['slowest_sql_statement'])
    assert metrics['db_pool_checkout_count'] == 1
    assert isinstance(metrics['db_pool_checkout_ms'], (int, float)) and float(metrics['db_pool_checkout_ms']) >= 0
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
