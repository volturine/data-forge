from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def _connection_string(database_url: str) -> str:
    """Return a psycopg connection string for either SQLAlchemy URL spelling."""
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    return database_url


def _deployment_lock_class(deployment_id: str) -> int:
    """Map a deployment name to a stable signed PostgreSQL advisory-lock key."""
    digest = hashlib.sha256(f"dataforge-engine-capacity:{deployment_id}".encode()).digest()
    value = int.from_bytes(digest[:4], byteorder="big", signed=False)
    return value if value < 2**31 else value - 2**32


@dataclass(slots=True)
class GlobalEngineSlot:
    """One application-wide engine slot held by a live PostgreSQL session."""

    _capacity: GlobalEngineCapacity
    index: int
    connection: psycopg.Connection
    _released: bool = False

    def release(self) -> None:
        self._capacity.release(self)


class GlobalEngineCapacity:
    """Coordinate engine slots across the manager and spawned build processes.

    PostgreSQL advisory locks are session-owned. Keeping the connection open for
    the lifetime of an engine makes the slot a real lease: a crashed worker or
    build child releases its slots when PostgreSQL observes the session close.
    A separate probe connection is reused while no slot is available so a burst
    of queued requests does not open one connection per slot attempt.
    """

    def __init__(
        self,
        *,
        deployment_id: str,
        max_slots: int,
        database_url: str,
        reserved_slots: int = 0,
        connect: Callable[..., psycopg.Connection] | None = None,
    ) -> None:
        self._enabled = bool(database_url.strip())
        self._max_slots = max_slots
        self._reserved_slots = min(max(reserved_slots, 0), max(max_slots, 0))
        self._lock_class = _deployment_lock_class(deployment_id)
        self._connect = connect or psycopg.connect
        self._lock = threading.Lock()
        self._probe: psycopg.Connection | None = None
        self._leases: dict[int, GlobalEngineSlot] = {}
        self._next_slot = self._reserved_slots
        self._closed = False
        self._database_url = _connection_string(database_url)

    @property
    def enabled(self) -> bool:
        return self._enabled and self._max_slots > 0

    def try_acquire(self) -> GlobalEngineSlot | None:
        """Try to lease one slot without waiting for another process."""
        if not self.enabled:
            return None
        with self._lock:
            if self._closed:
                return None
            connection = self._probe
            if connection is None:
                try:
                    connection = self._connect(self._database_url, autocommit=True, connect_timeout=3)
                except Exception:
                    logger.exception("Could not connect to PostgreSQL for global engine capacity")
                    return None
            try:
                for offset in range(self._max_slots):
                    index = (self._next_slot + offset) % self._max_slots
                    # The first reserved slots belong to the interactive
                    # manager. Build child managers share the advisory-lock
                    # class but may not consume that reserve after warm
                    # engines have been claimed.
                    if index < self._reserved_slots:
                        continue
                    result = connection.execute(
                        "SELECT pg_try_advisory_lock(%s, %s)",
                        (self._lock_class, index),
                    ).fetchone()
                    acquired = bool(result and result[0])
                    if acquired:
                        self._probe = None
                        self._next_slot = (index + 1) % self._max_slots
                        slot = GlobalEngineSlot(self, index, connection)
                        self._leases[index] = slot
                        return slot
            except Exception:
                logger.exception("Global engine capacity probe failed")
                with _suppress_close(connection):
                    connection.close()
                self._probe = None
                return None
            self._probe = connection
            self._next_slot = (self._next_slot + 1) % self._max_slots
            return None

    def release(self, slot: GlobalEngineSlot) -> None:
        """Release a lease and wake future callers through PostgreSQL."""
        with self._lock:
            if slot._released:
                return
            slot._released = True
            if self._leases.get(slot.index) is slot:
                self._leases.pop(slot.index, None)
            try:
                slot.connection.execute(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (self._lock_class, slot.index),
                )
            except Exception:
                logger.debug("Global engine slot %s could not be explicitly unlocked", slot.index, exc_info=True)
            with _suppress_close(slot.connection):
                slot.connection.close()

    def close(self) -> None:
        """Close probe and lease sessions during orderly manager shutdown."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connections = [slot.connection for slot in self._leases.values()]
            self._leases.clear()
            if self._probe is not None:
                connections.append(self._probe)
                self._probe = None
            for connection in connections:
                with _suppress_close(connection):
                    connection.close()


class _suppress_close:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def __enter__(self) -> None:
        return None

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> bool:
        return True
