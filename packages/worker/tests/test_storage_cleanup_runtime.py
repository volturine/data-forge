from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import cast

import pytest
from pyiceberg.exceptions import NoSuchTableError
from sqlalchemy import create_engine, text

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
        "sql",
        "postgresql://worker:secret@catalog.example/iceberg",
        "s3://default/clean",
        "clean",
        "datasource-1__claim_attempt",
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
        self.rpc_threads: list[int] = []

    async def claim_storage_cleanups_async(self, *, namespace: str, limit: int = 1) -> list[StorageCleanupClaim]:
        self.rpc_threads.append(threading.get_ident())
        return [_claim()]

    async def authorize_storage_cleanup_async(self, claim: StorageCleanupClaim) -> bool:
        self.rpc_threads.append(threading.get_ident())
        self.authorization_calls += 1
        return self.authorize()

    async def complete_storage_cleanup_async(self, claim: StorageCleanupClaim, *, error: str | None = None) -> bool:
        self.rpc_threads.append(threading.get_ident())
        self.outcomes.append(error)
        return True


@pytest.mark.asyncio
async def test_cleanup_waits_for_the_real_rid_slot_before_backend_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()
    identity = _identity()
    calls: list[str] = []
    storage_threads: list[int] = []
    event_loop_thread = threading.get_ident()

    def authorize() -> bool:
        calls.append("authorized")
        return True

    client = Client(authorize)

    def delete_target(_claim: StorageCleanupClaim) -> None:
        storage_threads.append(threading.get_ident())
        calls.append("deleted")

    monkeypatch.setattr(cleanup, "delete_cleanup_target", delete_target)
    await manager.await_engine_job_slot(identity, namespace="default")
    running = asyncio.create_task(cleanup.process_cleanup(manager, client, _claim()))
    try:
        await asyncio.sleep(0)
        assert client.authorization_calls == 0
        assert not running.done()
        manager.release_engine_job_slot(identity, namespace="default")
        assert await running
        assert calls == ["authorized", "deleted"]
        assert storage_threads and all(thread_id != event_loop_thread for thread_id in storage_threads)
        assert client.rpc_threads and all(thread_id == event_loop_thread for thread_id in client.rpc_threads)
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
async def test_cancel_during_async_authorization_releases_the_rid_slot() -> None:
    manager = _manager()
    entered_authorization = asyncio.Event()
    never_authorized = asyncio.Event()

    class WaitingClient(Client):
        async def authorize_storage_cleanup_async(self, claim: StorageCleanupClaim) -> bool:
            entered_authorization.set()
            await never_authorized.wait()
            return True

    client = WaitingClient(lambda: True)
    running = asyncio.create_task(cleanup.process_cleanup(manager, client, _claim()))
    await entered_authorization.wait()
    assert manager._engine_job_slots
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert manager._engine_job_slots == {}
    assert client.outcomes == []


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
        raise OSError("Storage unavailable for postgresql://worker:secret@catalog.example/iceberg")

    monkeypatch.setattr(cleanup, "delete_cleanup_target", fail)
    assert not await cleanup.process_cleanup(_manager(), client, _claim())
    assert client.outcomes == ["OSError: storage cleanup failed"]


def test_datasource_delete_drops_only_its_catalog_table_family(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    catalog_engine = create_engine("sqlite://")
    with catalog_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE iceberg_tables ("
                "catalog_name VARCHAR NOT NULL, table_namespace VARCHAR NOT NULL, table_name VARCHAR NOT NULL, "
                "PRIMARY KEY (catalog_name, table_namespace, table_name))"
            )
        )
        connection.execute(
            text("INSERT INTO iceberg_tables (catalog_name, table_namespace, table_name) VALUES (:catalog_name, :namespace, :table_name)"),
            [
                {"catalog_name": "local", "namespace": "outputs", "table_name": "ds-owned_main"},
                {"catalog_name": "local", "namespace": "outputs", "table_name": "ds-owned_main_rev12345678"},
                {"catalog_name": "local", "namespace": "outputs", "table_name": "ds-owned_other_branch"},
                {"catalog_name": "local", "namespace": "outputs", "table_name": "ds-ownedish_main"},
                {"catalog_name": "local", "namespace": "other", "table_name": "ds-owned_foreign"},
                {"catalog_name": "other-catalog", "namespace": "outputs", "table_name": "ds-owned_foreign"},
            ],
        )

    class Catalog:
        name = "local"
        engine = catalog_engine

        def list_tables(self, _namespace: str) -> list[tuple[str, str]]:
            pytest.fail("SQL family deletion must filter table identities in the catalog query")

        def drop_table(self, identifier: str) -> None:
            calls.append(("drop", identifier))

    catalog_config: list[dict[str, object]] = []

    def load_catalog(_name: str, **kwargs: object) -> Catalog:
        catalog_config.append(kwargs)
        return Catalog()

    monkeypatch.setattr(cleanup, "load_runtime_catalog", load_catalog)
    monkeypatch.setattr(cleanup, "object_store_storage_options", lambda: {})
    monkeypatch.setattr(cleanup, "delete_prefix", lambda path: calls.append(("prefix", path)))
    claim = StorageCleanupClaim(
        "default",
        "event-family",
        "token",
        1,
        "ds-owned",
        "s3://default/exports/ds-owned",
        True,
        "outputs.ds-owned_main_rev12345678",
        "sql",
        "postgresql://catalog-user:secret@catalog.example/db",
        "s3://default/exports",
        "outputs",
        "ds-owned_main_rev12345678",
        "ds-owned_",
    )

    cleanup.delete_cleanup_target(claim)

    assert catalog_config == [
        {
            "type": "sql",
            "uri": "postgresql://catalog-user:secret@catalog.example/db",
            "warehouse": "s3://default/exports",
        }
    ]
    assert [identifier for action, identifier in calls if action == "drop"] == [
        "outputs.ds-owned_main",
        "outputs.ds-owned_main_rev12345678",
        "outputs.ds-owned_other_branch",
    ]
    assert calls[-1] == ("prefix", "s3://default/exports/ds-owned")
    catalog_engine.dispose()


def test_non_sql_catalog_family_uses_its_namespace_scoped_listing_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Catalog:
        def list_tables(self, namespace: str) -> list[tuple[str, str]]:
            assert namespace == "outputs"
            return [
                ("outputs", "ds-owned_main"),
                ("outputs", "ds-owned_main_rev2"),
                ("outputs", "ds-ownedish_main"),
                ("other", "ds-owned_foreign"),
            ]

        @staticmethod
        def namespace_to_string(namespace: tuple[str, ...]) -> str:
            return ".".join(namespace)

        def drop_table(self, identifier: str) -> None:
            calls.append(identifier)

    monkeypatch.setattr(cleanup, "load_runtime_catalog", lambda *_args, **_kwargs: Catalog())
    monkeypatch.setattr(cleanup, "object_store_storage_options", lambda: {})
    monkeypatch.setattr(cleanup, "delete_prefix", lambda _path: None)
    claim = replace(
        _claim(),
        catalog_identifier="outputs.ds-owned_main",
        catalog_type="rest",
        catalog_namespace="outputs",
        catalog_table="ds-owned_main",
        catalog_family_prefix="ds-owned_",
    )

    cleanup.delete_cleanup_target(claim)

    assert calls == ["outputs.ds-owned_main", "outputs.ds-owned_main_rev2"]


@pytest.mark.asyncio
async def test_busy_rid_does_not_park_unrelated_ready_namespace_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()
    identity = _identity()
    await manager.await_engine_job_slot(identity, namespace="busy")
    stop = asyncio.Event()
    outcomes: list[tuple[str, str | None]] = []
    deleted: list[str] = []
    close_calls = 0
    namespaces = iter(("busy", "ready"))

    class LaneClient(Client):
        async def claim_storage_cleanups_async(self, *, namespace: str, limit: int = 1) -> list[StorageCleanupClaim]:
            return [StorageCleanupClaim(namespace, namespace, "token", 1, "datasource-1", f"s3://{namespace}/uploads/source.csv", False)]

        async def authorize_storage_cleanup_async(self, claim: StorageCleanupClaim) -> bool:
            assert claim.namespace == "ready"
            return True

        async def complete_storage_cleanup_async(self, claim: StorageCleanupClaim, *, error: str | None = None) -> bool:
            outcomes.append((claim.namespace, error))
            if error is None:
                stop.set()
            return True

        async def aclose(self) -> None:
            nonlocal close_calls
            close_calls += 1

    async def next_namespace() -> str | None:
        return next(namespaces, None)

    client = LaneClient(lambda: True)
    directory = object.__new__(RuntimeNamespaceDirectory)
    monkeypatch.setattr(directory, "next_namespace", next_namespace)

    async def get_client() -> Client:
        return client

    monkeypatch.setattr(cleanup, "async_client_from_env", get_client)
    monkeypatch.setattr(cleanup, "delete_cleanup_target", lambda claim: deleted.append(claim.namespace))
    try:
        async with asyncio.timeout(3.0):
            await cleanup.storage_cleanup_loop(stop, manager=manager, namespace_directory=directory)
        assert outcomes[0][0] == "busy" and outcomes[0][1] is not None
        assert deleted == ["ready"]
        assert outcomes[-1] == ("ready", None)
        assert close_calls == 0
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


def test_failed_or_stale_import_leaves_only_claim_prefix_for_durable_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime import compute_request_runtime

    registrations = []
    deleted_objects = []
    imported = []

    class RegistrationClient:
        def register_datasource_stage(self, **kwargs: object) -> None:
            registrations.append(kwargs)

        def create_engine_run(self, **_kwargs: object) -> str:
            return "run-1"

        def update_engine_run(self, **_kwargs: object) -> None:
            return None

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
    manifest = {
        "file_paths": ["s3://default/clean/request-1__claim_claim_token/master/data.parquet"],
        "row_count": 1,
        "columns": [{"name": "value", "dtype": "Int64", "nullable": True}],
    }

    def fail_import(received: object, **kwargs: object) -> None:
        imported.append((received, kwargs))
        raise RuntimeError("claim is no longer active")

    monkeypatch.setattr(compute_request_runtime, "_datasource_engine_job", lambda *_args, **_kwargs: manifest)
    monkeypatch.setattr(compute_request_runtime.datasource_execution, "import_staged_parquet_files", fail_import)
    monkeypatch.setattr("runtime.object_store.delete_object", lambda path: deleted_objects.append(path))

    with pytest.raises(RuntimeError, match="no longer active"):
        compute_request_runtime._publish_staged_datasource(cast(WorkerRuntimeClient, RegistrationClient()), _manager(), claimed, command.datasource)

    assert len(registrations) == 1
    registered = registrations[0]
    assert registered["prefix_url"] == "s3://default/clean/request-1__claim_claim_token/master"
    assert registered["manifest_url"] == "s3://default/runtime-staging/datasource-stage/request-1/1/manifest.json"
    assert imported == [
        (
            manifest,
            {
                "table_path": registered["prefix_url"],
                "database_url": compute_request_runtime.settings.database_url,
            },
        )
    ]
    assert deleted_objects == []



def test_reingest_datasource_strips_stale_time_travel_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime import compute_request_runtime

    published_configs = []

    class ReingestClient:
        def register_datasource_stage(self, **kwargs: object) -> None:
            pass

        def create_engine_run(self, **_kwargs: object) -> str:
            return "run-ingest-1"

        def update_engine_run(self, **_kwargs: object) -> None:
            pass

        def publish_datasource_ingest(self, **kwargs: object) -> object:
            published_configs.append(kwargs.get("config"))
            class Rec:
                name = "ds-1"
                source_type = "iceberg"
                config = {}
                def model_dump(self, **kwargs):
                    return {"id": "ds-1", "name": "ds-1", "source_type": "iceberg", "config": {}}
            return Rec()

        def complete_engine_run(self, **_kwargs: object) -> None:
            pass

    command = compute_pb2.ComputeCommand()
    command.datasource.ingest.datasource_id = "ds-1"
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="request-reingest-1",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        command_envelope=compute_pb2.ComputeCommandEnvelope(command=command),
        worker_id="writer",
        claim_token="claim-token",
        lease_generation=1,
        lease_ttl_seconds=300,
    )
    manifest = {
        "file_paths": ["s3://default/clean/ds-1__claim_claim_token/master/data.parquet"],
        "row_count": 5,
        "columns": [{"name": "col1", "dtype": "string", "nullable": True}],
    }

    class DummyMetadata:
        source_type = 'iceberg'
        revision = 2
        config = {
            "source": {"source_type": "file", "file_path": "s3://default/uploads/file.csv", "file_type": "csv"},
            "branch": "master",
            "time_travel_snapshot_id": "9876543210",
            "time_travel_snapshot_timestamp_ms": 1700000000000,
            "time_travel_ui": {"selected": True},
        }

    monkeypatch.setattr(compute_request_runtime.datasource_execution, "_require_metadata", lambda *_args, **_kwargs: DummyMetadata())
    monkeypatch.setattr(compute_request_runtime, "_datasource_engine_job", lambda *_args, **_kwargs: manifest)
    monkeypatch.setattr(compute_request_runtime.datasource_execution, "import_staged_parquet_files", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(compute_request_runtime.datasource_execution, "_set_snapshot_metadata", lambda config, table: None)

    compute_request_runtime._publish_staged_datasource(
        cast(compute_request_runtime.WorkerRuntimeClient, ReingestClient()),
        _manager(),
        claimed,
        command.datasource
    )

    assert len(published_configs) == 1
    published_config = published_configs[0]
    assert "time_travel_snapshot_id" not in published_config
    assert "time_travel_snapshot_timestamp_ms" not in published_config
    assert "time_travel_ui" not in published_config
    assert "ingest" in published_config


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
