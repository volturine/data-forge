from __future__ import annotations

import psycopg
import pytest

from runtime import manager_lease
from runtime.manager_lease import LEASE_SESSION_OPTIONS, MANAGER_LOCK_KEY, WorkerManagerLease, WorkerManagerLeaseLost


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def fetchone(self) -> tuple[object, ...]:
        return (self._value,)


class _Connection:
    def __init__(self, *, acquired: bool) -> None:
        self.acquired = acquired
        self.closed = False
        self.statements: list[tuple[str, tuple[object, ...] | None]] = []
        self.fail_ping: Exception | None = None

    def execute(self, statement: str, params: tuple[object, ...] | None = None) -> _Result:
        self.statements.append((statement, params))
        if "pg_try_advisory_lock" in statement:
            return _Result(self.acquired)
        if statement == "SELECT 1" and self.fail_ping is not None:
            raise self.fail_ping
        return _Result(True)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def conninfo(monkeypatch):
    monkeypatch.setattr(manager_lease, "_database_conninfo", lambda: "postgresql://test")


def test_lease_session_asks_postgres_to_notice_a_vanished_owner(conninfo) -> None:
    kwargs: dict[str, object] = {}
    connection = _Connection(acquired=True)

    def connect(_conninfo: str, **options):
        kwargs.update(options)
        return connection

    lease = WorkerManagerLease(connection_factory=connect)
    assert lease.acquire() is True

    options = str(kwargs["options"])
    assert options == LEASE_SESSION_OPTIONS
    # Server-side keepalives are what free the advisory lock when the owning
    # machine dies without closing its connection.
    assert "tcp_keepalives_idle=5" in options
    assert "tcp_keepalives_interval=2" in options
    assert "tcp_keepalives_count=3" in options
    # Keepalives only run on an idle socket; a ping in flight when the machine
    # died is bounded by the user timeout on both ends instead.
    assert "tcp_user_timeout=10000" in options
    assert kwargs["tcp_user_timeout"] == 10000
    assert kwargs["autocommit"] is True
    assert connection.statements[0] == ("SELECT pg_try_advisory_lock(%s)", (MANAGER_LOCK_KEY,))


def test_lease_holds_checks_and_releases_the_session_lock(conninfo) -> None:
    connection = _Connection(acquired=True)
    clock = [100.0]
    lease = WorkerManagerLease(connection_factory=lambda *_a, **_k: connection, clock=lambda: clock[0])

    assert lease.acquire() is True
    assert lease.held is True
    lease.check()
    lease.check()  # within the freshness window: no second ping
    clock[0] += 1.0
    lease.check()
    lease.check(force=True)
    lease.release()

    pings = sum(statement == "SELECT 1" for statement, _ in connection.statements)
    assert pings == 3
    assert any("pg_advisory_unlock" in statement for statement, _ in connection.statements)
    assert connection.closed
    assert lease.held is False


def test_standby_keeps_its_session_between_attempts(conninfo) -> None:
    connection = _Connection(acquired=False)
    created = 0

    def connect(*_a, **_k):
        nonlocal created
        created += 1
        return connection

    lease = WorkerManagerLease(connection_factory=connect)
    assert lease.acquire() is False
    assert lease.acquire() is False
    connection.acquired = True
    assert lease.acquire() is True
    assert created == 1
    with pytest.raises(RuntimeError, match="already held"):
        lease.acquire()


def test_check_fails_once_the_lock_session_is_gone(conninfo) -> None:
    connection = _Connection(acquired=True)
    lease = WorkerManagerLease(connection_factory=lambda *_a, **_k: connection)
    assert lease.acquire() is True

    connection.fail_ping = psycopg.OperationalError("server closed the connection unexpectedly")
    with pytest.raises(WorkerManagerLeaseLost):
        lease.check(force=True)

    connection.fail_ping = None
    connection.closed = True
    with pytest.raises(WorkerManagerLeaseLost):
        lease.check(force=True)


def test_check_without_a_lease_fails(conninfo) -> None:
    lease = WorkerManagerLease(connection_factory=lambda *_a, **_k: _Connection(acquired=False))
    with pytest.raises(WorkerManagerLeaseLost):
        lease.check()
    assert lease.acquire() is False
    with pytest.raises(WorkerManagerLeaseLost, match="not held"):
        lease.check()


def test_ping_timeout_keeps_the_lease_but_does_not_refresh_the_cache(conninfo) -> None:
    connection = _Connection(acquired=True)
    clock = [50.0]
    lease = WorkerManagerLease(connection_factory=lambda *_a, **_k: connection, clock=lambda: clock[0])
    assert lease.acquire() is True

    connection.fail_ping = psycopg.errors.QueryCanceled("statement timeout")
    lease.check(force=True)  # tolerated: PostgreSQL answered
    lease.check()  # not cached, so it pings again
    assert sum(statement == "SELECT 1" for statement, _ in connection.statements) == 2
    assert lease.held is True
