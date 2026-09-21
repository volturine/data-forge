from __future__ import annotations

from typing import Any

from runtime.global_engine_capacity import GlobalEngineCapacity


class _Result:
    def __init__(self, value: bool) -> None:
        self.value = value

    def fetchone(self) -> tuple[bool]:
        return (self.value,)


class _Connection:
    def __init__(self, locks: set[tuple[int, int]]) -> None:
        self.locks = locks
        self.held: set[tuple[int, int]] = set()
        self.closed = False

    def execute(self, statement: str, params: tuple[int, int]) -> _Result:
        key = tuple(params)
        if "pg_try_advisory_lock" in statement:
            if key in self.locks:
                return _Result(False)
            self.locks.add(key)
            self.held.add(key)
            return _Result(True)
        if "pg_advisory_unlock" in statement:
            unlocked = key in self.held
            self.held.discard(key)
            self.locks.discard(key)
            return _Result(unlocked)
        raise AssertionError(statement)

    def close(self) -> None:
        self.closed = True
        for key in self.held:
            self.locks.discard(key)
        self.held.clear()


def test_global_engine_capacity_coordinates_deployments() -> None:
    locks: set[tuple[int, int]] = set()
    connections: list[_Connection] = []

    def connect(_url: str, **_kwargs: Any) -> _Connection:
        connection = _Connection(locks)
        connections.append(connection)
        return connection

    first = GlobalEngineCapacity(
        deployment_id="test-deployment",
        max_slots=1,
        database_url="postgresql://db/test",
        connect=connect,
    )
    second = GlobalEngineCapacity(
        deployment_id="test-deployment",
        max_slots=1,
        database_url="postgresql://db/test",
        connect=connect,
    )

    first_slot = first.try_acquire()
    assert first_slot is not None
    assert second.try_acquire() is None

    first_slot.release()
    second_slot = second.try_acquire()
    assert second_slot is not None
    assert connections[0].closed

    second.close()
    assert connections[1].closed
    assert not locks


def test_global_engine_capacity_is_disabled_without_database_url() -> None:
    capacity = GlobalEngineCapacity(deployment_id="test", max_slots=1, database_url="")

    assert not capacity.enabled
    assert capacity.try_acquire() is None


def test_global_engine_capacity_keeps_reserved_slots_for_interactive_manager() -> None:
    locks: set[tuple[int, int]] = set()

    def connect(_url: str, **_kwargs: Any) -> _Connection:
        return _Connection(locks)

    capacity = GlobalEngineCapacity(
        deployment_id="test-deployment",
        max_slots=4,
        reserved_slots=2,
        database_url="postgresql://db/test",
        connect=connect,
    )

    first = capacity.try_acquire()
    second = capacity.try_acquire()
    third = capacity.try_acquire()

    assert first is not None and first.index == 2
    assert second is not None and second.index == 3
    assert third is None

    first.release()
    replacement = capacity.try_acquire()
    assert replacement is not None and replacement.index == 2

    capacity.close()
    assert not locks
