from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest
from pyiceberg.exceptions import NoSuchTableError

from dataforge_protocol import compute_pb2, enums_pb2
from runtime import storage_cleanup_runtime as cleanup
from runtime.compute_manager import ProcessManager
from runtime.worker_runtime import RuntimeNamespaceDirectory
from runtime.worker_runtime_client import StorageCleanupClaim, WorkerRuntimeClient


def _claim() -> StorageCleanupClaim:
    return StorageCleanupClaim(
        "default",
        "event-1",
        "outbox-token",
        1,
        "datasource-1",
        "s3://default/clean/datasource-1__claim_attempt/master",
        True,
        "clean.datasource-1__claim_attempt",
    )


def _manager() -> ProcessManager:
    # Exercise the real RID slot methods without starting Docker, reapers, or warm workers.
    manager = object.__new__(ProcessManager)
    manager._engine_job_slots = {}
    manager._engines = {}
    manager._engines_lock = threading.Lock()
    return manager


def _identity() -> compute_pb2.EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id="datasource-1",
        resource_id="datasource-1",
    )


class Client:
    def __init__(self, authorize: Callable[[], bool]) -> None:
        self.authorize = authorize
        self.authorization_calls = 0
        self.outcomes: list[str | None] = []

    def claim_storage_cleanups(self, *, namespace: str, limit: int = 1) -> list[StorageCleanupClaim]:
        return [_claim()]

    def authorize_storage_cleanup(self, claim: StorageCleanupClaim) -> bool:
        self.authorization_calls += 1
        return self.authorize()

    def complete_storage_cleanup(self, claim: StorageCleanupClaim, *, error: str | None = None) -> bool:
        self.outcomes.append(error)
        return True


@pytest.mark.asyncio
async def test_cleanup_waits_for_the_real_rid_slot_before_backend_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()
    identity = _identity()
    calls: list[str] = []

    def authorize() -> bool:
        calls.append("authorized")
        return True

    client = Client(authorize)
    monkeypatch.setattr(cleanup, "delete_cleanup_target", lambda _claim: calls.append("deleted"))
    await manager.await_engine_job_slot(identity, namespace="default")
    running = asyncio.create_task(cleanup.process_cleanup(manager, client, _claim()))
    try:
        await asyncio.sleep(0)
        assert client.authorization_calls == 0
        assert not running.done()
        manager.release_engine_job_slot(identity, namespace="default")
        assert await running
        assert calls == ["authorized", "deleted"]
        assert client.outcomes == [None]
        assert manager._engine_job_slots == {}
    finally:
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_while_waiting_for_the_rid_slot_releases_only_the_waiter() -> None:
    manager = _manager()
    identity = _identity()
    client = Client(lambda: pytest.fail("Cancelled cleanup must not authorize deletion"))
    await manager.await_engine_job_slot(identity, namespace="default")
    running = asyncio.create_task(cleanup.process_cleanup(manager, client, _claim()))
    await asyncio.sleep(0)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert next(iter(manager._engine_job_slots.values())).references == 1
    assert client.outcomes == []
    manager.release_engine_job_slot(identity, namespace="default")
    assert manager._engine_job_slots == {}


@pytest.mark.asyncio
async def test_ambiguous_publication_uses_backend_authorization_without_deleting(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client(lambda: False)
    monkeypatch.setattr(cleanup, "delete_cleanup_target", lambda _claim: pytest.fail("Published prefix must not be deleted"))
    assert not await cleanup.process_cleanup(_manager(), client, _claim())
    assert client.authorization_calls == 1
    assert client.outcomes[0] is not None


@pytest.mark.asyncio
async def test_storage_failure_is_recorded_for_durable_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client(lambda: True)

    def fail(_claim: StorageCleanupClaim) -> None:
        raise OSError("Storage is unavailable")

    monkeypatch.setattr(cleanup, "delete_cleanup_target", fail)
    assert not await cleanup.process_cleanup(_manager(), client, _claim())
    assert client.outcomes == ["Storage is unavailable"]


@pytest.mark.asyncio
async def test_busy_rid_does_not_park_unrelated_ready_namespace_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()
    identity = _identity()
    await manager.await_engine_job_slot(identity, namespace="busy")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    outcomes: list[tuple[str, str | None]] = []
    deleted: list[str] = []
    namespaces = iter(("busy", "ready"))

    class LaneClient(Client):
        def claim_storage_cleanups(self, *, namespace: str, limit: int = 1) -> list[StorageCleanupClaim]:
            return [StorageCleanupClaim(namespace, namespace, "token", 1, "datasource-1", f"s3://{namespace}/uploads/source.csv", False)]

        def authorize_storage_cleanup(self, claim: StorageCleanupClaim) -> bool:
            assert claim.namespace == "ready"
            return True

        def complete_storage_cleanup(self, claim: StorageCleanupClaim, *, error: str | None = None) -> bool:
            outcomes.append((claim.namespace, error))
            if error is None:
                loop.call_soon_threadsafe(stop.set)
            return True

        def close(self) -> None:
            return None

    async def next_namespace() -> str | None:
        return next(namespaces, None)

    client = LaneClient(lambda: True)
    directory = object.__new__(RuntimeNamespaceDirectory)
    monkeypatch.setattr(directory, "next_namespace", next_namespace)
    monkeypatch.setattr(cleanup, "client_from_env", lambda: client)
    monkeypatch.setattr(cleanup, "delete_cleanup_target", lambda claim: deleted.append(claim.namespace))
    try:
        async with asyncio.timeout(3.0):
            await cleanup.storage_cleanup_loop(stop, manager=manager, namespace_directory=directory)
        assert outcomes[0][0] == "busy" and outcomes[0][1] is not None
        assert deleted == ["ready"]
        assert outcomes[-1] == ("ready", None)
        assert next(iter(manager._engine_job_slots.values())).references == 1
    finally:
        manager.release_engine_job_slot(identity, namespace="busy")
    assert manager._engine_job_slots == {}


@pytest.mark.parametrize("catalog_missing", [False, True])
def test_cleanup_drops_only_the_exact_catalog_identifier_and_prefix(monkeypatch: pytest.MonkeyPatch, catalog_missing: bool) -> None:
    calls: list[tuple[str, str]] = []

    class Catalog:
        def drop_table(self, identifier: str) -> None:
            calls.append(("catalog", identifier))
            if catalog_missing:
                raise NoSuchTableError(identifier)

    monkeypatch.setattr(cleanup, "load_runtime_catalog", lambda *_args, **_kwargs: Catalog())
    monkeypatch.setattr(cleanup, "object_store_storage_options", lambda: {})
    monkeypatch.setattr(cleanup, "delete_prefix", lambda path: calls.append(("prefix", path)))
    cleanup.delete_cleanup_target(_claim())
    assert calls == [("catalog", "clean.datasource-1__claim_attempt"), ("prefix", "s3://default/clean/datasource-1__claim_attempt/master")]


def test_failed_registration_prevents_any_physical_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime import compute_request_runtime

    class RegistrationClient:
        def register_datasource_stage(self, **_kwargs: object) -> None:
            raise RuntimeError("Cleanup registration unavailable")

    command = compute_pb2.ComputeCommand()
    command.datasource.create_file.name = "Staged"
    command.datasource.create_file.file_type = enums_pb2.DATA_SOURCE_FILE_TYPE_CSV
    command.datasource.create_file.file_path = "s3://default/uploads/source.csv"
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="request-1",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        command_envelope=compute_pb2.ComputeCommandEnvelope(command=command),
        worker_id="writer",
        claim_token="claim-token",
        lease_generation=1,
        lease_ttl_seconds=300,
    )
    monkeypatch.setattr(compute_request_runtime, "_datasource_engine_job", lambda *_args, **_kwargs: pytest.fail("Staging wrote before registration"))
    with pytest.raises(RuntimeError, match="Cleanup registration unavailable"):
        compute_request_runtime._publish_staged_datasource(cast(WorkerRuntimeClient, RegistrationClient()), _manager(), claimed, command.datasource)


def test_worker_heartbeat_reports_registration_loss_and_recovery_on_its_thread() -> None:
    from runtime.worker_runtime_client import run_worker_heartbeat_loop

    stop = threading.Event()
    states: list[tuple[bool, int]] = []

    class HeartbeatClient:
        def __init__(self) -> None:
            self.calls = 0

        def heartbeat_worker(self, **_kwargs: object) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Coordinator unavailable")
            stop.set()

        def register_worker(self, **_kwargs: object) -> None:
            return None

    client = HeartbeatClient()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_worker_heartbeat_loop,
            client=cast(WorkerRuntimeClient, client),
            stop_signal=stop,
            worker_id="writer",
            kind="coordinator",
            hostname="test",
            pid=1,
            capacity=1,
            heartbeat_seconds=0.05,
            on_registration_changed=lambda available: states.append((available, threading.get_ident())),
        )
        future.result(timeout=3)
    assert [available for available, _thread in states] == [False, True]
    assert all(thread != threading.get_ident() for _available, thread in states)


@pytest.mark.asyncio
async def test_idle_compute_dispatcher_reports_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime import compute_request_runtime

    stop = asyncio.Event()
    directory = object.__new__(RuntimeNamespaceDirectory)

    async def no_namespace() -> str | None:
        return None

    monkeypatch.setattr(directory, "next_namespace", no_namespace)
    async with asyncio.timeout(1):
        await compute_request_runtime.compute_request_loop(
            stop,
            worker_id="writer",
            manager=_manager(),
            poll_for_work=False,
            namespace_directory=directory,
            on_progress=stop.set,
        )
    assert stop.is_set()
