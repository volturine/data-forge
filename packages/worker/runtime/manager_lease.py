"""Singleton lease for the Docker-owning worker manager.

Several worker containers may run at once, one per machine. Only the one that
holds this PostgreSQL session-level advisory lock owns Docker and the compute
budget; the others stay in standby and serve the data plane only. The lock is
tied to the lease connection: when the owning process or its machine
disappears, PostgreSQL drops the session (its TCP keepalives are tightened so
a vanished peer is noticed in seconds, not hours) and the lock with it, and a
standby takes over.

The worker never imports backend code, so this is a deliberate, smaller
sibling of ``RuntimeCoordinatorLease`` in the backend package.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import psycopg

from runtime.config import settings

logger = logging.getLogger(__name__)

MANAGER_LOCK_KEY = int.from_bytes(hashlib.sha256(b"dataforge:worker-manager").digest()[:8], "big", signed=True)
# A lost owner must release the lock quickly even when its machine vanished
# without closing the TCP connection: ask the server to probe the session
# (idle 5s, then every 2s, three misses) and set the same on the client side.
LEASE_SESSION_OPTIONS = "-c statement_timeout=3000 -c lock_timeout=1000 -c tcp_keepalives_idle=5 -c tcp_keepalives_interval=2 -c tcp_keepalives_count=3"
_CHECK_FRESHNESS_SECONDS = 0.25


def _database_conninfo() -> str:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must be configured for the worker manager lease")
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


class WorkerManagerLeaseLost(RuntimeError):
    """The manager lease connection is gone; another worker may own Docker now."""


class WorkerManagerLease:
    """Hold the worker-manager lease on one dedicated PostgreSQL session."""

    def __init__(self, *, connection_factory: Callable[..., Any] = psycopg.connect, clock: Callable[[], float] = time.monotonic) -> None:
        self._connection_factory = connection_factory
        self._clock = clock
        self._connection: Any = None
        self._owns_lock = False
        self._lock = threading.Lock()
        self._check_valid_until = 0.0
        self._last_ping_timeout_log = 0.0

    @property
    def held(self) -> bool:
        return self._owns_lock

    def acquire(self) -> bool:
        """Try the lock once without blocking; keep the session for retries."""
        with self._lock:
            self._check_valid_until = 0.0
            if self._owns_lock:
                raise RuntimeError("Worker manager lease is already held")
            if self._connection is None or self._connection.closed:
                self._connection = self._connection_factory(
                    _database_conninfo(),
                    autocommit=True,
                    connect_timeout=5,
                    keepalives_idle=2,
                    keepalives_interval=1,
                    keepalives_count=3,
                    application_name="dataforge-worker-manager-lease",
                    options=LEASE_SESSION_OPTIONS,
                )
            try:
                row = self._connection.execute("SELECT pg_try_advisory_lock(%s)", (MANAGER_LOCK_KEY,)).fetchone()
                self._owns_lock = bool(row and row[0])
            except BaseException:
                if not self._connection.closed:
                    self._connection.close()
                self._connection = None
                self._owns_lock = False
                raise
            return self._owns_lock

    def check(self, *, force: bool = False) -> None:
        """Prove the lock-owning session is still alive.

        Raises ``WorkerManagerLeaseLost`` when it is not. A recent successful
        ping is reused for request-path callers; the monitor forces a new one.
        """
        with self._lock:
            if not force and self._clock() < self._check_valid_until:
                return
            connection = self._connection
            if connection is None or connection.closed:
                raise WorkerManagerLeaseLost("Worker manager lease connection is closed")
            if not self._owns_lock:
                raise WorkerManagerLeaseLost("Worker manager lease is not held")
            try:
                connection.execute("SELECT 1")
            except psycopg.errors.QueryCanceled:
                # The server answered, so the session and its lock are alive;
                # the probe just did not finish. Do not refresh the cache.
                now = self._clock()
                if now - self._last_ping_timeout_log >= 30.0:
                    logger.warning("Worker manager lease ping timed out; retaining the live session lock and retrying")
                    self._last_ping_timeout_log = now
                return
            except psycopg.Error as exc:
                raise WorkerManagerLeaseLost("Worker manager lease connection is unavailable") from exc
            self._check_valid_until = self._clock() + _CHECK_FRESHNESS_SECONDS

    def release(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            owns_lock = self._owns_lock
            self._owns_lock = False
            self._check_valid_until = 0.0
            if connection is None:
                return
            if owns_lock and not connection.closed:
                with contextlib.suppress(psycopg.Error):
                    connection.execute("SELECT pg_advisory_unlock(%s)", (MANAGER_LOCK_KEY,))
            with contextlib.suppress(Exception):
                connection.close()
