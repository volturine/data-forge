"""Tests for bug fixes and new features."""

import asyncio
import contextvars
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest
from pydantic import ValidationError

from builds.build_live import RuntimeBuild
from dataforge_protocol import analysis_pb2, compute_pb2, datasource_pb2, enums_pb2
from datasources import execution as datasource_execution
from operations.download import DownloadParams
from operations.export import ExportParams
from operations.notification import NotificationHandler, NotificationParams
from operations.plot import ChartHandler, ChartParams, compute_chart_data
from operations.step_converter import analysis_pipeline_to_execution_payload
from runtime import compute_request_runtime, compute_service, datasource_delete_runtime, worker_runtime_client
from runtime.compute_engine import PolarsComputeEngine
from runtime.compute_manager import (
    ENGINE_ADMISSION_PRIORITY_DATASOURCE,
    ENGINE_ADMISSION_PRIORITY_INTERACTIVE,
    ENGINE_ADMISSION_PRIORITY_LIFECYCLE,
    ProcessManager,
)
from runtime.compute_service import ExportDatasourceResult
from runtime.domain.compute import schemas as compute_schemas
from runtime.domain.engine_runs.schemas import EngineRunResponseSchema
from runtime.executors import (
    CLEANUP_EXECUTOR,
    COMPUTE_EXECUTOR,
    CONTROL_EXECUTOR,
    ENGINE_IO_EXECUTOR,
    LEASE_EXECUTOR,
    run_compute_in_thread,
    run_control_in_thread,
    run_engine_io_in_thread,
    run_lease_in_thread,
)
from runtime.worker_runtime_client import BackendWorkerRpcError, PendingDatasourceDelete

# ---------------------------------------------------------------------------
# Build runtime regressions
# ---------------------------------------------------------------------------


def test_datasource_schema_publication_carries_metadata_revision_and_claim(monkeypatch) -> None:
    from contextlib import contextmanager

    from runtime.domain.compute.result import EngineResult

    schema_info = datasource_pb2.SchemaInfo(columns=[datasource_pb2.ColumnSchema(name="value", dtype="Int64", nullable=True)])
    published: dict[str, object] = {}
    engine_payloads = []

    class Client:
        def datasource_metadata(self, **_kwargs):
            return worker_runtime_client.DatasourceMetadata(
                found=True,
                id="datasource-1",
                name="Source",
                source_type="file",
                config={"file_path": "s3://default/uploads/source.csv", "file_type": "csv"},
                schema_cache=None,
                is_hidden=False,
                revision=7,
            )

        def publish_datasource_schema_cache(self, **kwargs):
            published.update(kwargs)
            return kwargs["schema_info"]

    class Engine:
        def datasource_job(self, kind, payload):
            engine_payloads.append((kind, payload))
            return "engine-job"

        def get_result(self, **_kwargs):
            return EngineResult(job_id="engine-job", data={"columns": [{"name": "value", "dtype": "Int64", "nullable": True}]}, error=None)

    class Manager:
        @contextmanager
        def acquire_engine(self, identity):
            assert identity.resource_id == "datasource-1"
            yield Engine()

    def fail_local_compute(*_args, **_kwargs):
        raise AssertionError("Datasource schema extraction ran in the manager")

    monkeypatch.setattr(datasource_execution, "_extract_schema_from_metadata", fail_local_compute)
    command = compute_pb2.ComputeCommand()
    command.datasource.schema.CopyFrom(datasource_pb2.DatasourceSchemaCommand(datasource_id="datasource-1", refresh=True))
    command.input_revisions.add(datasource_id="datasource-1", revision=7)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="request-1",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command_envelope=compute_pb2.ComputeCommandEnvelope(command=command),
        worker_id="worker-1",
        claim_token="claim-1",
        lease_generation=3,
        lease_ttl_seconds=300,
    )
    result = compute_request_runtime._execute_datasource_command(Client(), claimed, Manager(), command.datasource)
    assert result.schema == schema_info
    assert published == {
        "namespace": "default",
        "datasource_id": "datasource-1",
        "schema_info": schema_info,
        "expected_revision": 7,
        "compute_request_id": "request-1",
        "worker_id": "worker-1",
        "claim_token": "claim-1",
        "lease_generation": 3,
    }
    assert engine_payloads[0][0] == "datasource_schema"
    assert engine_payloads[0][1]["datasource_metadata"]["revision"] == 7
    assert "claim_token" not in engine_payloads[0][1]


def test_terminal_compute_completion_retries_after_api_reconnect(monkeypatch) -> None:
    calls = 0

    class Client:
        def complete_compute_request(self, **kwargs) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise BackendWorkerRpcError(
                    status_code=503,
                    error="API unavailable",
                    error_code="UNAVAILABLE",
                )
            assert kwargs["timeout_seconds"] == 15.0

    monkeypatch.setattr(compute_request_runtime.time, "sleep", lambda _seconds: None)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="terminal-retry",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=compute_pb2.ComputeCommandEnvelope(),
    )

    compute_request_runtime._complete_request(
        Client(),
        claimed,
        response=compute_pb2.ComputeResponse(),
    )

    assert calls == 2


@pytest.mark.asyncio
async def test_claim_hash_survives_client_to_dispatcher_handoff(monkeypatch) -> None:
    command_hash = "7a4c-hash"
    claimed_by_client = worker_runtime_client.ClaimedComputeRequest(
        id="request-with-hash",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command_envelope=_preview_command_envelope(request_id="request-with-hash"),
        worker_id="worker-test",
        claim_token="claim-token",
        lease_generation=1,
        lease_expires_at=datetime.now(UTC),
        attempt=1,
        lease_ttl_seconds=300,
        command_hash=command_hash,
    )

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def claim_compute_request(self, **_kwargs):
            return claimed_by_client

    async def execute_request(_claimed, _manager, *, work_semaphore=None) -> None:
        return None

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: Client())
    monkeypatch.setattr(compute_request_runtime, "_execute_request", execute_request)

    claimed = compute_request_runtime.next_compute_request("worker-test", namespace="default")
    assert claimed is not None
    assert claimed.command_hash == command_hash
    assert await compute_request_runtime._run_once(
        worker_id="worker-test",
        manager=cast(Any, SimpleNamespace()),
        namespace="default",
    )


def test_compute_request_lease_batcher_coalesces_by_namespace() -> None:
    batches: list[tuple[str, list[str]]] = []

    class Client:
        _target = "runtime-coordinator"

        def _metadata(self):
            return (("x-runtime-coordinator-generation", "1"),)

        def _renew_compute_request_leases_batch(self, *, namespace, worker_id, renewals, timeout_seconds):
            assert worker_id == "worker-batch"
            assert timeout_seconds == 10
            request_ids = [request_id for request_id, _token, _generation in renewals]
            batches.append((namespace, request_ids))
            return {request_id: 30 for request_id in request_ids if request_id != "request-stale"}

    batcher = worker_runtime_client._ComputeLeaseRenewalBatcher(batch_window_seconds=0.1)
    submissions = [("default", f"request-{index}") for index in range(8)] + [("tenant-a", "request-a"), ("tenant-b", "request-b"), ("default", "request-stale")]
    barrier = threading.Barrier(len(submissions))

    def renew(namespace: str, request_id: str) -> int | None:
        barrier.wait(timeout=1)
        return batcher.renew(
            Client(),
            request_id=request_id,
            namespace=namespace,
            worker_id="worker-batch",
            claim_token=f"token-{request_id}",
            lease_generation=1,
            timeout_seconds=10,
        )

    try:
        with ThreadPoolExecutor(max_workers=len(submissions)) as executor:
            futures = [executor.submit(renew, namespace, request_id) for namespace, request_id in submissions]
            results = [future.result(timeout=2) for future in futures]
    finally:
        batcher.close()

    assert results == [30] * 8 + [30, 30, None]
    assert {namespace: set(request_ids) for namespace, request_ids in batches} == {
        "default": {*(f"request-{index}" for index in range(8)), "request-stale"},
        "tenant-a": {"request-a"},
        "tenant-b": {"request-b"},
    }
    assert len(batches) == 3


def test_compute_request_lease_client_routes_through_batcher(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Batcher:
        def renew(self, client, **kwargs):
            captured["client"] = client
            captured.update(kwargs)
            return 45

    client = cast(Any, object.__new__(worker_runtime_client.WorkerRuntimeClient))
    monkeypatch.setattr(worker_runtime_client, "_get_compute_lease_batcher", lambda: Batcher())

    renewed_ttl = client.renew_compute_request_lease(
        request_id="request-batched",
        namespace="tenant-a",
        worker_id="worker-batch",
        claim_token="claim-token",
        lease_generation=3,
        timeout_seconds=20,
    )

    assert renewed_ttl == 45
    assert captured == {
        "client": client,
        "request_id": "request-batched",
        "namespace": "tenant-a",
        "worker_id": "worker-batch",
        "claim_token": "claim-token",
        "lease_generation": 3,
        "timeout_seconds": 20,
    }


@pytest.mark.asyncio
async def test_compute_claim_lease_is_extended_immediately(monkeypatch) -> None:
    renewed = asyncio.Event()
    stop_event = asyncio.Event()
    calls = 0
    client_closed = False

    class Client:
        def renew_compute_request_lease(self, **_kwargs) -> float:
            raise AssertionError("lease RPC must run through the dedicated lease executor")

        def close(self) -> None:
            nonlocal client_closed
            client_closed = True

    client = Client()

    async def fake_run_lease_in_thread(function, **_kwargs) -> float:
        nonlocal calls
        assert function == client.renew_compute_request_lease
        calls += 1
        renewed.set()
        stop_event.set()
        return 300.0

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: client)
    monkeypatch.setattr(compute_request_runtime, "run_lease_in_thread", fake_run_lease_in_thread)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="short-delivery-lease",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=20,
        lease_deadline_monotonic=asyncio.get_running_loop().time() + 20,
        command_envelope=compute_pb2.ComputeCommandEnvelope(),
    )

    renewal = asyncio.create_task(compute_request_runtime._renew_compute_lease(claimed, stop_event=stop_event))
    try:
        await asyncio.wait_for(renewed.wait(), timeout=0.5)
        await asyncio.wait_for(renewal, timeout=0.5)
    finally:
        stop_event.set()
        if not renewal.done():
            renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)

    assert calls == 1
    assert client_closed


@pytest.mark.asyncio
async def test_control_executor_remains_available_when_compute_budget_is_full() -> None:
    capacity = COMPUTE_EXECUTOR._max_workers
    release = threading.Event()
    capacity_reached = threading.Event()
    started = 0
    started_lock = threading.Lock()

    def block_control_call() -> None:
        nonlocal started
        with started_lock:
            started += 1
            if started == capacity:
                capacity_reached.set()
        release.wait()

    calls = [asyncio.create_task(run_compute_in_thread(block_control_call)) for _ in range(capacity)]
    try:
        assert await asyncio.wait_for(asyncio.to_thread(capacity_reached.wait, 2), timeout=3)
        control_thread = await asyncio.wait_for(run_control_in_thread(lambda: threading.current_thread().name), timeout=1)
        assert control_thread.startswith("runtime-control")
    finally:
        release.set()
    await asyncio.gather(*calls)


def test_compute_executor_matches_the_single_runtime_work_budget() -> None:
    workers = compute_request_runtime.compute_request_worker_count()
    assert COMPUTE_EXECUTOR._max_workers == workers
    assert ENGINE_IO_EXECUTOR._max_workers == workers
    assert CONTROL_EXECUTOR._max_workers == min(4, workers)
    assert LEASE_EXECUTOR._max_workers == min(2, workers)
    assert CLEANUP_EXECUTOR._max_workers == min(2, workers)
    assert len({COMPUTE_EXECUTOR, CONTROL_EXECUTOR, LEASE_EXECUTOR, CLEANUP_EXECUTOR, ENGINE_IO_EXECUTOR}) == 5


@pytest.mark.asyncio
async def test_engine_io_uses_a_separate_executor_from_runtime_control() -> None:
    engine_io_thread = await run_engine_io_in_thread(lambda: threading.current_thread().name)
    control_thread = await run_control_in_thread(lambda: threading.current_thread().name)

    assert engine_io_thread.startswith("engine-io")
    assert control_thread.startswith("runtime-control")


@pytest.mark.asyncio
async def test_lease_renewals_use_a_separate_executor_from_control_work() -> None:
    lease_thread = await run_lease_in_thread(lambda: threading.current_thread().name)
    control_thread = await run_control_in_thread(lambda: threading.current_thread().name)

    assert lease_thread.startswith("runtime-lease")
    assert control_thread.startswith("runtime-control")


@pytest.mark.asyncio
async def test_runtime_executor_preserves_request_context() -> None:
    namespace = contextvars.ContextVar("executor-test-namespace", default="missing")
    token = namespace.set("tenant-a")
    try:
        assert await run_control_in_thread(namespace.get) == "tenant-a"
    finally:
        namespace.reset(token)


@pytest.mark.asyncio
async def test_cancelled_compute_keeps_its_slot_until_thread_stops() -> None:
    thread_started = threading.Event()
    release_thread = threading.Event()
    cancellation_started = threading.Event()

    def blocking_work() -> None:
        thread_started.set()
        release_thread.wait()

    task = asyncio.create_task(
        run_compute_in_thread(
            blocking_work,
            cancel_work=cancellation_started.set,
        )
    )
    try:
        assert await asyncio.wait_for(asyncio.to_thread(thread_started.wait, 2), timeout=3)
        task.cancel()
        assert await asyncio.wait_for(asyncio.to_thread(cancellation_started.wait, 2), timeout=3)
        assert not task.done()
    finally:
        release_thread.set()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_engine_admission_prioritizes_shared_datasource_preview() -> None:
    datasource_identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id="datasource-rid",
        resource_id="datasource-rid",
    )
    analysis_identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id="analysis-rid",
        resource_id="analysis-rid",
    )

    assert (
        compute_request_runtime._engine_admission_priority(
            enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            datasource_identity,
        )
        == ENGINE_ADMISSION_PRIORITY_DATASOURCE
    )
    assert (
        compute_request_runtime._engine_admission_priority(
            enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            analysis_identity,
        )
        == ENGINE_ADMISSION_PRIORITY_INTERACTIVE
    )
    assert (
        compute_request_runtime._engine_admission_priority(
            enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
            analysis_identity,
        )
        == ENGINE_ADMISSION_PRIORITY_LIFECYCLE
    )


@pytest.mark.asyncio
async def test_compute_request_claims_share_a_bounded_control_plane(monkeypatch) -> None:
    active = 0
    peak = 0

    def fake_next_request(*_args, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        time.sleep(0.02)
        active -= 1
        return None

    monkeypatch.setattr(compute_request_runtime, "next_compute_request", fake_next_request)
    claim_capacity = compute_request_runtime.compute_request_claim_worker_count()
    assert claim_capacity == min(compute_request_runtime.compute_request_worker_count(), 4)
    claim_semaphore = asyncio.Semaphore(claim_capacity)

    await asyncio.gather(
        *(
            compute_request_runtime._run_once(
                worker_id=f"worker-{index}",
                manager=cast(Any, SimpleNamespace()),
                namespace="default",
                claim_semaphore=claim_semaphore,
            )
            for index in range(8)
        )
    )

    assert peak == claim_capacity


def test_engine_run_execution_entry_proto_uses_typed_fields() -> None:
    entry = worker_runtime_client._engine_run_execution_entry_proto(
        {
            "key": "filter",
            "label": "Filter",
            "category": "step",
            "order": 0,
            "duration_ms": 12.5,
            "share_pct": 100.0,
            "metadata": {"step_type": "filter"},
        }
    )

    assert isinstance(entry, compute_pb2.EngineRunExecutionEntry)
    assert entry.category == enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_STEP
    assert entry.step_type == enums_pb2.STEP_TYPE_FILTER
    assert entry.duration_ms == 12.5
    assert entry.share_pct == 100.0


def test_engine_run_execution_entries_normalize_invalid_timing_metrics() -> None:
    entries = compute_service._build_execution_entries(
        step_timings={"filter": -5.0, "join": float("nan")},
        read_duration_ms=-10.0,
        collect_duration_ms=250.0,
        total_duration_ms=1,
    )

    assert [entry["key"] for entry in entries] == ["compute"]
    assert entries[0]["duration_ms"] == 250.0
    assert entries[0]["share_pct"] == 100.0


def test_export_operation_params_accept_generated_enum_numbers() -> None:
    params = ExportParams.model_validate(
        {
            "format": enums_pb2.EXPORT_FORMAT_PARQUET,
            "filename": "result",
            "destination": enums_pb2.EXPORT_DESTINATION_DOWNLOAD,
        }
    )

    assert params.format == enums_pb2.EXPORT_FORMAT_PARQUET
    assert params.destination == enums_pb2.EXPORT_DESTINATION_DOWNLOAD


def test_download_operation_params_accept_generated_enum_numbers() -> None:
    params = DownloadParams.model_validate(
        {
            "format": enums_pb2.EXPORT_FORMAT_JSON,
            "filename": "result",
        }
    )

    assert params.format == enums_pb2.EXPORT_FORMAT_JSON


def test_engine_run_update_proto_uses_typed_patch_fields() -> None:
    update = worker_runtime_client._engine_run_update_proto(
        {
            "status": "success",
            "result_json": {"row_count": 2},
            "completed_at": datetime.now(UTC).isoformat(),
            "duration_ms": 42,
            "step_timings": {"filter": 2.5},
            "execution_entries": [
                {
                    "key": "filter",
                    "label": "Filter",
                    "category": "step",
                    "order": 0,
                    "duration_ms": 2.5,
                    "metadata": {"step_type": "filter"},
                }
            ],
            "progress": 1.0,
            "current_step": None,
        }
    )

    assert update.status == enums_pb2.ENGINE_RUN_STATUS_SUCCESS
    assert update.HasField("result_json")
    assert update.HasField("completed_at")
    assert update.step_timings.values["filter"] == 2.5
    assert update.execution_entries.entries[0].step_type == enums_pb2.STEP_TYPE_FILTER
    assert update.progress == 1.0
    assert update.clear_current_step is True


def test_engine_run_finalization_uses_the_existing_typed_update() -> None:
    finalization = worker_runtime_client._engine_run_finalization_proto(
        worker_runtime_client.EngineRunFinalization(
            run_id="run-1",
            fields={
                "status": "success",
                "result_json": {"row_count": 5},
                "completed_at": datetime.now(UTC),
            },
        )
    )

    assert finalization.run_id == "run-1"
    assert finalization.merge_result is False
    assert finalization.update.status == enums_pb2.ENGINE_RUN_STATUS_SUCCESS
    assert finalization.update.result_json.fields["row_count"].number_value == 5
    assert finalization.update.HasField("completed_at")


def test_engine_status_result_proto_uses_typed_snapshot_fields() -> None:
    status = worker_runtime_client._engine_status_result_proto(
        {
            "analysis_id": "analysis-1",
            "resource_id": "datasource-1",
            "status": "healthy",
            "container_id": "container-1234",
            "image_digest": "sha256:abc",
            "lifecycle_status": "running",
            "supervisor_id": "worker-1",
            "owner_id": "worker-1",
            "last_activity": datetime.now(UTC).isoformat(),
            "current_job_id": "job-1",
            "resource_config": {"max_threads": 2},
            "effective_resources": {"max_threads": 2, "max_memory_mb": 1024},
            "defaults": {"max_threads": 2, "max_memory_mb": 1024, "streaming_chunk_size": 500},
            "scope": "datasource_preview",
            "reuse_policy": "shared",
            "datasource_id": "datasource-1",
        }
    )

    assert status.status == enums_pb2.ENGINE_STATUS_HEALTHY
    assert status.resource_config.max_threads == 2
    assert status.effective_resources.max_memory_mb == 1024
    assert status.defaults.streaming_chunk_size == 500
    assert status.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW


def _engine_identity_payload(identity) -> dict[str, str]:
    payload: dict[str, str] = {
        "scope": "datasource_preview" if identity.HasField("datasource_id") else "build" if identity.HasField("build_id") else "analysis_interactive",
        "reuse_policy": "exclusive" if identity.HasField("build_id") else "shared",
        "resource_id": identity.resource_id,
    }
    if identity.HasField("analysis_id"):
        payload["analysis_id"] = identity.analysis_id
    if identity.HasField("datasource_id"):
        payload["datasource_id"] = identity.datasource_id
    if identity.HasField("build_id"):
        payload["build_id"] = identity.build_id
    return payload


def _analysis_identity(analysis_id: str) -> compute_pb2.EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id=analysis_id,
        resource_id=analysis_id,
    )


def _datasource_preview_identity(datasource_id: str) -> compute_pb2.EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id=datasource_id,
        resource_id=datasource_id,
    )


def _command_envelope(
    *,
    kind: enums_pb2.ComputeRequestKind,
    request_id: str,
    payload: dict[str, object],
    shutdown_identity=None,
) -> compute_pb2.ComputeCommandEnvelope:
    envelope = compute_pb2.ComputeCommandEnvelope(
        kind=kind,
        version=1,
        idempotency_key=request_id,
        correlation_id=request_id,
    )
    if shutdown_identity is not None:
        envelope.command.shutdown_engine.engine_identity.CopyFrom(shutdown_identity)
    else:
        datasource_id = payload.get("datasource_id")
        if not isinstance(datasource_id, str):
            raise ValueError("datasource_id is required")
        envelope.command.datasource.schema.CopyFrom(datasource_pb2.DatasourceSchemaCommand(datasource_id=datasource_id))
    return envelope


def _preview_command_envelope(*, request_id: str) -> compute_pb2.ComputeCommandEnvelope:
    return compute_pb2.ComputeCommandEnvelope(
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        version=1,
        idempotency_key=request_id,
        correlation_id=request_id,
        command=compute_pb2.ComputeCommand(
            preview=compute_pb2.StepPreviewCommand(
                analysis_id="analysis-from-proto",
                target_step_id="source",
                analysis_pipeline=analysis_pb2.AnalysisPipelinePayload(
                    analysis_id="analysis-from-proto",
                    tabs=[
                        analysis_pb2.AnalysisPipelineTab(
                            id="tab-1",
                            datasource=analysis_pb2.AnalysisPipelineDatasource(
                                id="datasource-1",
                                analysis_tab_id="tab-1",
                                source_type=enums_pb2.DATA_SOURCE_TYPE_FILE,
                            ),
                            output=analysis_pb2.AnalysisPipelineOutput(
                                result_id="result-1",
                                filename="result.csv",
                                format=enums_pb2.EXPORT_FORMAT_CSV,
                            ),
                        )
                    ],
                ),
                row_limit=25,
                page=2,
            )
        ),
    )


def test_analysis_pipeline_protocol_view_config_uses_worker_service_key() -> None:
    pipeline = analysis_pb2.AnalysisPipelinePayload(
        analysis_id="analysis-1",
        tabs=[
            analysis_pb2.AnalysisPipelineTab(
                id="tab-1",
                datasource=analysis_pb2.AnalysisPipelineDatasource(
                    id="datasource-1",
                    analysis_tab_id="tab-1",
                    source_type=enums_pb2.DATA_SOURCE_TYPE_FILE,
                ),
                output=analysis_pb2.AnalysisPipelineOutput(
                    result_id="result-1",
                    filename="result.csv",
                    format=enums_pb2.EXPORT_FORMAT_CSV,
                ),
                steps=[
                    analysis_pb2.AnalysisPipelineStep(
                        id="view-1",
                        step_type=enums_pb2.STEP_TYPE_VIEW,
                        config=analysis_pb2.StepConfig(view=analysis_pb2.ViewConfig(row_limit=100)),
                    )
                ],
            )
        ],
    )

    payload = analysis_pipeline_to_execution_payload(pipeline)

    tabs = cast(list[dict[str, object]], payload["tabs"])
    steps = cast(list[dict[str, object]], tabs[0]["steps"])
    step_config = steps[0]["config"]
    assert step_config == {"row_limit": 100}


def test_analysis_pipeline_protocol_step_type_drives_service_step_type() -> None:
    pipeline = analysis_pb2.AnalysisPipelinePayload(
        analysis_id="analysis-1",
        tabs=[
            analysis_pb2.AnalysisPipelineTab(
                id="tab-1",
                datasource=analysis_pb2.AnalysisPipelineDatasource(
                    id="datasource-1",
                    analysis_tab_id="tab-1",
                    source_type=enums_pb2.DATA_SOURCE_TYPE_FILE,
                ),
                output=analysis_pb2.AnalysisPipelineOutput(
                    result_id="result-1",
                    filename="result.csv",
                    format=enums_pb2.EXPORT_FORMAT_CSV,
                ),
                steps=[
                    analysis_pb2.AnalysisPipelineStep(
                        id="plot-1",
                        step_type=enums_pb2.STEP_TYPE_PLOT_SCATTER,
                        config=analysis_pb2.StepConfig(chart=analysis_pb2.ChartConfig(chart_type=enums_pb2.CHART_TYPE_SCATTER)),
                    )
                ],
            )
        ],
    )

    payload = analysis_pipeline_to_execution_payload(pipeline)

    tabs = cast(list[dict[str, object]], payload["tabs"])
    steps = cast(list[dict[str, object]], tabs[0]["steps"])
    step = steps[0]
    assert step["type"] == "plot_scatter"
    assert "step_type" not in step
    assert step["config"] == {"chart_type": enums_pb2.CHART_TYPE_SCATTER}


def test_analysis_pipeline_protocol_deduplicate_absent_subset_is_not_null() -> None:
    pipeline = analysis_pb2.AnalysisPipelinePayload(
        analysis_id="analysis-1",
        tabs=[
            analysis_pb2.AnalysisPipelineTab(
                id="tab-1",
                datasource=analysis_pb2.AnalysisPipelineDatasource(
                    id="datasource-1",
                    analysis_tab_id="tab-1",
                    source_type=enums_pb2.DATA_SOURCE_TYPE_FILE,
                ),
                output=analysis_pb2.AnalysisPipelineOutput(
                    result_id="result-1",
                    filename="result.csv",
                    format=enums_pb2.EXPORT_FORMAT_CSV,
                ),
                steps=[
                    analysis_pb2.AnalysisPipelineStep(
                        id="dedup-1",
                        step_type=enums_pb2.STEP_TYPE_DEDUPLICATE,
                        config=analysis_pb2.StepConfig(deduplicate=analysis_pb2.DeduplicateConfig(keep=enums_pb2.DEDUPLICATE_KEEP_FIRST)),
                    )
                ],
            )
        ],
    )

    payload = analysis_pipeline_to_execution_payload(pipeline)

    tabs = cast(list[dict[str, object]], payload["tabs"])
    steps = cast(list[dict[str, object]], tabs[0]["steps"])
    step_config = cast(dict[str, object], steps[0]["config"])
    assert "subset" not in step_config
    assert step_config == {"keep": enums_pb2.DEDUPLICATE_KEEP_FIRST}


def test_preview_compute_request_uses_typed_command_not_legacy_payload(monkeypatch) -> None:
    completed: list[compute_pb2.ComputeResponse] = []
    publication_order: list[str] = []

    monkeypatch.setattr(compute_request_runtime, "set_namespace_context", lambda namespace: namespace)
    monkeypatch.setattr(compute_request_runtime, "reset_namespace", lambda token: None)

    def fake_preview_step(**kwargs):
        assert kwargs["analysis_id"] == "analysis-from-proto"
        assert kwargs["target_step_id"] == "source"
        assert kwargs["row_limit"] == 25
        assert kwargs["page"] == 2
        assert kwargs["analysis_pipeline"]["analysis_id"] == "analysis-from-proto"
        assert kwargs["request_json"]["analysis_id"] == "analysis-from-proto"
        assert "legacy_payload" not in kwargs["request_json"]
        return compute_request_runtime.service.PreviewOutcome(
            response=compute_schemas.StepPreviewResponse(
                step_id="source",
                columns=[],
                data=[],
                total_rows=0,
                page=2,
                page_size=25,
            )
        )

    class _Client:
        def close(self):
            pass

        def complete_compute_request(self, **kwargs):
            publication_order.append("durable")
            completed.append(kwargs["response"])

        def fail_compute_request(self, **_kwargs):
            raise AssertionError("request should not fail")

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())
    monkeypatch.setattr(compute_request_runtime.service, "preview_step", fake_preview_step)

    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-preview",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-preview"),
    )

    compute_request_runtime._execute_request_sync(claimed, cast(Any, SimpleNamespace()))

    assert len(completed) == 1
    assert completed[0].WhichOneof("response") == "preview"
    assert completed[0].preview.step_id == "source"
    assert publication_order == ["durable"]


@pytest.mark.asyncio
async def test_compute_request_renewal_reports_lost_claim(monkeypatch) -> None:
    class _Client:
        def close(self):
            pass

        def renew_compute_request_lease(self, **_kwargs):
            return None

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-lost",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=0.03,
        command_envelope=_preview_command_envelope(request_id="req-lost"),
    )

    with pytest.raises(compute_request_runtime.ComputeRequestLeaseLost, match="no longer active"):
        await compute_request_runtime._renew_compute_lease(claimed, stop_event=asyncio.Event())


@pytest.mark.asyncio
async def test_compute_waiting_for_worker_admission_does_not_hold_execution_permit(monkeypatch) -> None:
    admission_started = asyncio.Event()
    release_admission = asyncio.Event()
    execution_started = asyncio.Event()
    work_semaphore = asyncio.Semaphore(1)

    class _Client:
        def close(self):
            pass

        def renew_compute_request_lease(self, **_kwargs):
            return None

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "tenant-a"
            assert priority == compute_request_runtime.ENGINE_ADMISSION_PRIORITY_INTERACTIVE
            admission_started.set()
            await release_admission.wait()
            return True

        def reserve_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_spawn_admission(self, _identity, *, namespace, owned: bool) -> None:
            assert namespace == "tenant-a"
            assert owned is True

    async def keep_lease_alive(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
        lease_confirmed.set()
        await stop_event.wait()

    async def run_in_thread(function, *args, **kwargs) -> None:
        del kwargs
        function(*args)

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())
    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", keep_lease_alive)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", run_in_thread)
    monkeypatch.setattr(
        compute_request_runtime,
        "_execute_request_sync",
        lambda *_args: execution_started.set(),
    )
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-admission-permit",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-admission-permit"),
    )

    task = asyncio.create_task(
        compute_request_runtime._execute_request(
            claimed,
            cast(Any, _Manager()),
            work_semaphore=work_semaphore,
        )
    )
    await asyncio.wait_for(admission_started.wait(), timeout=1)
    assert await asyncio.wait_for(work_semaphore.acquire(), timeout=0.1)
    work_semaphore.release()
    release_admission.set()
    await asyncio.wait_for(execution_started.wait(), timeout=1)
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_same_engine_waiter_does_not_hold_global_permit_or_overtake_other_engine(monkeypatch) -> None:
    work_semaphore = asyncio.Semaphore(2)
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    third_started = asyncio.Event()
    release_first = asyncio.Event()
    slots: dict[str, asyncio.Lock] = {}

    class _Client:
        def close(self):
            pass

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "tenant-a"
            return False

        async def await_engine_job_slot(self, identity, *, namespace):
            assert namespace == "tenant-a"
            slot = slots.setdefault(identity.resource_id, asyncio.Lock())
            await slot.acquire()

        def release_engine_job_slot(self, identity, *, namespace):
            assert namespace == "tenant-a"
            slots[identity.resource_id].release()

        def reserve_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_spawn_admission(self, _identity, *, namespace, owned):
            assert namespace == "tenant-a"
            assert owned is False

    async def keep_lease_alive(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
        lease_confirmed.set()
        await stop_event.wait()

    async def run_in_thread(function, claimed, manager):
        if claimed.id == "same-rid-first":
            first_started.set()
            await release_first.wait()
        elif claimed.id == "same-rid-second":
            second_started.set()
        else:
            third_started.set()
        function(claimed, manager)

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())
    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", keep_lease_alive)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", run_in_thread)
    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", lambda *_args: None)

    def claim(request_id: str, analysis_id: str) -> compute_request_runtime.ClaimedComputeRequest:
        command = _preview_command_envelope(request_id=request_id)
        command.command.preview.analysis_id = analysis_id
        command.command.preview.analysis_pipeline.analysis_id = analysis_id
        return compute_request_runtime.ClaimedComputeRequest(
            id=request_id,
            namespace="tenant-a",
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            worker_id="worker-test",
            claim_token=f"claim-{request_id}",
            lease_generation=1,
            lease_ttl_seconds=300,
            command_envelope=command,
        )

    manager = cast(Any, _Manager())
    first = asyncio.create_task(compute_request_runtime._execute_request(claim("same-rid-first", "analysis-shared"), manager, work_semaphore=work_semaphore))
    await asyncio.wait_for(first_started.wait(), timeout=1)
    second = asyncio.create_task(compute_request_runtime._execute_request(claim("same-rid-second", "analysis-shared"), manager, work_semaphore=work_semaphore))
    await asyncio.sleep(0)
    third = asyncio.create_task(compute_request_runtime._execute_request(claim("other-rid", "analysis-other"), manager, work_semaphore=work_semaphore))
    try:
        await asyncio.wait_for(third_started.wait(), timeout=1)
        assert not second_started.is_set()
    finally:
        release_first.set()

    await asyncio.wait_for(asyncio.gather(first, second, third), timeout=2)
    assert second_started.is_set()


@pytest.mark.asyncio
async def test_compute_capacity_race_releases_permit_before_rejoining_admission(monkeypatch) -> None:
    work_semaphore = asyncio.Semaphore(1)
    race_wait_started = asyncio.Event()
    race_wait_release = asyncio.Event()
    admissions = 0
    releases = 0
    executions = 0

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            nonlocal admissions
            assert namespace == "tenant-a"
            admissions += 1
            return True

        def reserve_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_spawn_admission(self, _identity, *, namespace, owned: bool) -> None:
            nonlocal releases
            assert namespace == "tenant-a"
            assert owned is True
            releases += 1

    class _Client:
        def close(self):
            pass

    async def keep_lease_alive(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
        lease_confirmed.set()
        await stop_event.wait()

    async def run_in_thread(function, *args, **kwargs) -> None:
        nonlocal executions
        del kwargs
        executions += 1
        if executions == 1:
            raise compute_request_runtime.EngineCapacityFull("lost admission race")
        function(*args)

    async def wait_after_capacity_race(_manager) -> None:
        # The failed attempt has already released its permit and manager slot.
        assert await asyncio.wait_for(work_semaphore.acquire(), timeout=0.1)
        work_semaphore.release()
        race_wait_started.set()
        await race_wait_release.wait()

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())
    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", keep_lease_alive)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", run_in_thread)
    monkeypatch.setattr(compute_request_runtime, "_wait_after_engine_capacity_race", wait_after_capacity_race)
    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", lambda *_args: None)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-capacity-race",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-capacity-race"),
    )

    task = asyncio.create_task(
        compute_request_runtime._execute_request(
            claimed,
            cast(Any, _Manager()),
            work_semaphore=work_semaphore,
        )
    )
    await asyncio.wait_for(race_wait_started.wait(), timeout=1)
    assert admissions == 1
    assert releases == 1
    race_wait_release.set()
    await asyncio.wait_for(task, timeout=1)
    assert admissions == 2
    assert releases == 2
    assert executions == 2


@pytest.mark.asyncio
async def test_cancelled_compute_holds_permit_until_executor_thread_stops(monkeypatch) -> None:
    thread_started = threading.Event()
    release_thread = threading.Event()
    work_semaphore = asyncio.Semaphore(1)
    admission_released = asyncio.Event()

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "tenant-a"
            return False

        def reserve_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_spawn_admission(self, _identity, *, namespace, owned: bool) -> None:
            assert namespace == "tenant-a"
            assert owned is False
            admission_released.set()

    class _Client:
        def close(self):
            pass

    async def keep_lease_alive(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
        lease_confirmed.set()
        await stop_event.wait()

    def blocking_execution(*_args) -> None:
        thread_started.set()
        release_thread.wait()

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())
    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", keep_lease_alive)
    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", blocking_execution)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-cancel-running",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-cancel-running"),
    )

    task = asyncio.create_task(
        compute_request_runtime._execute_request(
            claimed,
            cast(Any, _Manager()),
            work_semaphore=work_semaphore,
        )
    )
    try:
        assert await asyncio.wait_for(asyncio.to_thread(thread_started.wait, 2), timeout=3)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
        assert not admission_released.is_set()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(work_semaphore.acquire(), timeout=0.05)
    finally:
        release_thread.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(admission_released.wait(), timeout=1)
    assert await asyncio.wait_for(work_semaphore.acquire(), timeout=1)
    work_semaphore.release()


@pytest.mark.asyncio
async def test_compute_request_lease_loss_cancels_shared_job_without_stopping_worker(monkeypatch) -> None:
    cancelled = threading.Event()
    execution_started = asyncio.Event()
    cancelled_jobs: list[tuple[str, str | None, str | None]] = []
    shutdown_calls: list[tuple[str, str | None]] = []
    loop = asyncio.get_running_loop()

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "tenant-a"
            assert priority == compute_request_runtime.ENGINE_ADMISSION_PRIORITY_INTERACTIVE
            return False

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_spawn_admission(self, _identity, *, namespace, owned: bool) -> None:
            assert namespace == "tenant-a"
            assert owned is False

        def shutdown_engine(self, identity, *, namespace: str | None = None) -> None:
            shutdown_calls.append((identity.resource_id, namespace))

        def cancel_engine_job(self, _identity, *, namespace, job_id):
            cancelled_jobs.append((_identity.resource_id, namespace, job_id))
            assert namespace == "tenant-a"
            assert job_id == "req-lease-loss"
            cancelled.set()

        def shutdown_engine_after_request_lease_loss(self, identity, *, namespace):
            assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
            assert namespace == "tenant-a"

    async def lose_lease(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
        del stop_event
        lease_confirmed.set()
        await execution_started.wait()
        raise compute_request_runtime.ComputeRequestLeaseLost("lease lost")

    def run_engine(_claimed, _manager, _terminal_publication_started=None) -> None:
        loop.call_soon_threadsafe(execution_started.set)
        assert cancelled.wait(timeout=2)

    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", lose_lease)
    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", run_engine)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-lease-loss",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-lease-loss"),
    )
    identity = compute_request_runtime._engine_identity_for_claimed(claimed)
    assert identity is not None
    assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED

    with pytest.raises(compute_request_runtime.ComputeRequestLeaseLost, match="lease lost"):
        await asyncio.wait_for(
            compute_request_runtime._execute_request(claimed, cast(Any, _Manager())),
            timeout=2,
        )

    assert cancelled_jobs == [("analysis-from-proto", "tenant-a", "req-lease-loss")]
    assert shutdown_calls == []


@pytest.mark.asyncio
async def test_compute_request_waits_for_first_lease_confirmation_before_admission(monkeypatch) -> None:
    renewal_started = asyncio.Event()
    allow_renewal = asyncio.Event()
    admission_started = asyncio.Event()

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "tenant-a"
            admission_started.set()
            return False

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_spawn_admission(self, _identity, *, namespace, owned):
            assert namespace == "tenant-a"
            assert owned is False

    async def renew_after_gate(_claimed, *, stop_event, lease_confirmed):
        renewal_started.set()
        await allow_renewal.wait()
        lease_confirmed.set()
        await stop_event.wait()

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", renew_after_gate)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", run_inline)
    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", lambda *_args: None)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-first-lease-confirmation",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=20,
        command_envelope=_preview_command_envelope(request_id="req-first-lease-confirmation"),
    )

    task = asyncio.create_task(compute_request_runtime._execute_request(claimed, cast(Any, _Manager())))
    try:
        await asyncio.wait_for(renewal_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert not admission_started.is_set()

        allow_renewal.set()
        await asyncio.wait_for(task, timeout=1)
        assert admission_started.is_set()
    finally:
        allow_renewal.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_lease_loss_releases_admission_completed_in_same_turn(monkeypatch) -> None:
    admission_ready = asyncio.Event()
    admission_started = asyncio.Event()
    renewal_ready = asyncio.Event()
    acquire = asyncio.Event()
    held_admissions = 0
    released_admissions: list[bool] = []

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            nonlocal held_admissions
            assert namespace == "tenant-a"
            admission_started.set()
            await admission_ready.wait()
            held_admissions += 1
            return True

        def reserve_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_spawn_admission(self, _identity, *, namespace, owned):
            nonlocal held_admissions
            assert namespace == "tenant-a"
            released_admissions.append(owned)
            if owned:
                held_admissions -= 1

        def cancel_engine_job(self, _identity, *, namespace, job_id):
            assert namespace == "tenant-a"
            assert job_id == "req-admission-handoff"

        def shutdown_engine_after_request_lease_loss(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def shutdown_engine(self, _identity, *, namespace):
            assert namespace == "tenant-a"

    async def lose_lease(_claimed, *, stop_event, lease_confirmed):
        del stop_event
        lease_confirmed.set()
        renewal_ready.set()
        await acquire.wait()
        raise compute_request_runtime.ComputeRequestLeaseLost("lease lost during admission")

    manager = _Manager()
    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", lose_lease)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-admission-handoff",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-admission-handoff"),
    )

    task = asyncio.create_task(compute_request_runtime._execute_request(claimed, cast(Any, manager)))
    try:
        await asyncio.wait_for(renewal_ready.wait(), timeout=1)
        await asyncio.wait_for(admission_started.wait(), timeout=1)
        # The admission child and lease renewal are released in one event-loop
        # turn, so cleanup must observe ownership even if renewal wins the wait.
        admission_ready.set()
        acquire.set()
        with pytest.raises(compute_request_runtime.ComputeRequestLeaseLost, match="lease lost during admission"):
            await asyncio.wait_for(task, timeout=1)

        assert released_admissions == [True]
        assert held_admissions == 0
    finally:
        admission_ready.set()
        acquire.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_lease_loss_releases_engine_lane_acquired_in_same_turn(monkeypatch) -> None:
    job_slot_started = asyncio.Event()
    renewal_ready = asyncio.Event()
    acquire = asyncio.Event()
    engine_job_locked = False
    request_reservations = 0
    released_admissions: list[bool] = []

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "tenant-a"
            nonlocal request_reservations
            request_reservations += 1
            return False

        def release_spawn_admission(self, _identity, *, namespace, owned):
            assert namespace == "tenant-a"
            released_admissions.append(owned)

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"
            job_slot_started.set()
            await acquire.wait()
            nonlocal engine_job_locked
            engine_job_locked = True

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"
            nonlocal engine_job_locked
            assert engine_job_locked
            engine_job_locked = False

        def release_engine_request(self, _identity, *, namespace):
            nonlocal request_reservations
            assert namespace == "tenant-a"
            request_reservations -= 1

        def cancel_engine_job(self, _identity, *, namespace, job_id):
            assert namespace == "tenant-a"
            assert job_id == "req-engine-lane-handoff"

        def shutdown_engine_after_request_lease_loss(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def shutdown_engine(self, _identity, *, namespace):
            assert namespace == "tenant-a"

    async def lose_lease(_claimed, *, stop_event, lease_confirmed):
        del stop_event
        lease_confirmed.set()
        renewal_ready.set()
        await acquire.wait()
        raise compute_request_runtime.ComputeRequestLeaseLost("lease lost during engine lane acquisition")

    manager = _Manager()
    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", lose_lease)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-engine-lane-handoff",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-engine-lane-handoff"),
    )

    task = asyncio.create_task(
        compute_request_runtime._execute_request(
            claimed,
            cast(Any, manager),
            work_semaphore=asyncio.Semaphore(0),
        )
    )
    try:
        await asyncio.wait_for(job_slot_started.wait(), timeout=1)
        await asyncio.wait_for(renewal_ready.wait(), timeout=1)
        acquire.set()
        with pytest.raises(
            compute_request_runtime.ComputeRequestLeaseLost,
            match="lease lost during engine lane acquisition",
        ):
            await asyncio.wait_for(task, timeout=1)

        assert not engine_job_locked
        assert request_reservations == 0
        assert released_admissions == [False]
    finally:
        acquire.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_lease_loss_releases_work_permit_acquired_in_same_turn(monkeypatch) -> None:
    permit_waiting = asyncio.Event()
    renewal_ready = asyncio.Event()
    acquire = asyncio.Event()
    request_reservations = 0
    engine_job_locked = False

    class TrackedSemaphore(asyncio.Semaphore):
        async def acquire(self) -> bool:
            permit_waiting.set()
            return await super().acquire()

    work_semaphore = TrackedSemaphore(0)

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "tenant-a"
            nonlocal request_reservations
            request_reservations += 1
            return False

        def release_spawn_admission(self, _identity, *, namespace, owned):
            assert namespace == "tenant-a"
            assert owned is False

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"
            nonlocal engine_job_locked
            engine_job_locked = True

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"
            nonlocal engine_job_locked
            assert engine_job_locked
            engine_job_locked = False

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"
            nonlocal request_reservations
            request_reservations -= 1

        def cancel_engine_job(self, _identity, *, namespace, job_id):
            assert namespace == "tenant-a"
            assert job_id == "req-work-permit-handoff"

        def shutdown_engine_after_request_lease_loss(self, _identity, *, namespace):
            assert namespace == "tenant-a"

    async def lose_lease(_claimed, *, stop_event, lease_confirmed):
        del stop_event
        lease_confirmed.set()
        renewal_ready.set()
        await acquire.wait()
        raise compute_request_runtime.ComputeRequestLeaseLost("lease lost during work permit acquisition")

    async def block_execution(_function, *_args, **_kwargs):
        await asyncio.Future()

    manager = _Manager()
    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", lose_lease)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", block_execution)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-work-permit-handoff",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-work-permit-handoff"),
    )

    task = asyncio.create_task(
        compute_request_runtime._execute_request(
            claimed,
            cast(Any, manager),
            work_semaphore=work_semaphore,
        )
    )
    try:
        await asyncio.wait_for(permit_waiting.wait(), timeout=1)
        await asyncio.wait_for(renewal_ready.wait(), timeout=1)
        # Wake both child acquisitions before the parent consumes either
        # result, reproducing lease loss during ownership handoff.
        work_semaphore.release()
        acquire.set()

        with pytest.raises(
            compute_request_runtime.ComputeRequestLeaseLost,
            match="lease lost during work permit acquisition",
        ):
            await asyncio.wait_for(task, timeout=1)

        assert not engine_job_locked
        assert request_reservations == 0
        assert await asyncio.wait_for(work_semaphore.acquire(), timeout=1)
        work_semaphore.release()
    finally:
        acquire.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_terminal_compute_publication_wins_late_lease_loss(monkeypatch) -> None:
    publication_entered = threading.Event()
    allow_publication_return = threading.Event()
    lease_loss_reported = asyncio.Event()
    published_requests: list[str] = []
    shutdown_calls: list[str] = []
    cancelled_jobs: list[str] = []

    async def lose_lease(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
        del stop_event
        lease_confirmed.set()
        await asyncio.to_thread(publication_entered.wait)
        lease_loss_reported.set()
        raise compute_request_runtime.ComputeRequestLeaseLost("late renewal failure")

    async def complete_request(function, *args, **kwargs) -> None:
        del kwargs
        execution = asyncio.create_task(asyncio.to_thread(function, *args))
        await asyncio.to_thread(publication_entered.wait)
        await asyncio.to_thread(allow_publication_return.wait)
        await execution

    class _Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "tenant-a"
            assert priority == compute_request_runtime.ENGINE_ADMISSION_PRIORITY_INTERACTIVE
            return False

        def release_spawn_admission(self, _identity, *, namespace: str, owned: bool) -> None:
            assert namespace == "tenant-a"
            assert owned is False

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        async def await_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def release_engine_job_slot(self, _identity, *, namespace):
            assert namespace == "tenant-a"

        def shutdown_engine(self, identity, *, namespace: str | None = None) -> None:
            del namespace
            shutdown_calls.append(identity.resource_id)

        def cancel_engine_job(self, identity, *, namespace, job_id):
            del namespace, job_id
            cancelled_jobs.append(identity.resource_id)

        def shutdown_engine_after_request_lease_loss(self, identity, *, namespace):
            del namespace
            shutdown_calls.append(identity.resource_id)

    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", lose_lease)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", complete_request)

    def publish_request(
        request: compute_request_runtime.ClaimedComputeRequest,
        _manager,
        terminal_publication_started: threading.Event,
    ) -> bool:
        terminal_publication_started.set()
        publication_entered.set()
        assert allow_publication_return.wait(timeout=1)
        published_requests.append(request.id)
        return True

    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", publish_request)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-completed-with-late-renewal",
        namespace="tenant-a",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_preview_command_envelope(request_id="req-completed-with-late-renewal"),
    )

    execution = asyncio.create_task(compute_request_runtime._execute_request(claimed, cast(Any, _Manager())))
    try:
        await asyncio.wait_for(lease_loss_reported.wait(), timeout=1)
        await asyncio.sleep(0)
        assert shutdown_calls == []
        assert cancelled_jobs == []
        allow_publication_return.set()
        await asyncio.wait_for(execution, timeout=1)

        assert published_requests == [claimed.id]
        assert shutdown_calls == []
        assert cancelled_jobs == []
    finally:
        allow_publication_return.set()
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)


def test_shutdown_compute_request_removes_active_engine_and_emits_empty_snapshot(monkeypatch) -> None:
    completed: list[compute_pb2.ComputeResponse] = []
    identity = _analysis_identity("analysis-1")

    class _Engine:
        current_job_id = "job-1"
        process_id = 1234
        resource_config: dict[str, object] = {}
        effective_resources: dict[str, object] = {}

        def __init__(self) -> None:
            self.alive = False
            self.shutdown_calls = 0

        def start(self) -> None:
            self.alive = True

        def is_process_alive(self) -> bool:
            return self.alive

        @property
        def last_known_alive(self) -> bool:
            return self.alive

        def check_health(self) -> bool:
            return self.alive

        def shutdown(self) -> None:
            self.shutdown_calls += 1
            self.alive = False

    engine = _Engine()
    snapshots: list[list[object]] = []

    class _Client:
        def close(self):
            pass

        def complete_compute_request(self, **kwargs):
            completed.append(kwargs["response"])

        def fail_compute_request(self, **_kwargs):
            raise AssertionError("request should not fail")

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())

    manager = ProcessManager(engine_factory=lambda _identity, _resource_config: cast(Any, engine), on_snapshot=snapshots.append)
    manager.spawn_engine(identity)
    assert manager.get_engine(identity) is engine
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-1",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_command_envelope(
            kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
            request_id="req-1",
            payload={"engine_identity": _engine_identity_payload(identity)},
            shutdown_identity=identity,
        ),
    )

    try:
        compute_request_runtime._execute_request_sync(claimed, manager)

        assert manager.get_engine(identity) is None
        assert engine.shutdown_calls == 1
        assert snapshots[-1] == []
        assert len(completed) == 1
        assert completed[0].WhichOneof("response") == "ack"
        assert completed[0].ack.success is True
    finally:
        manager.shutdown_all()


def test_shutdown_compute_request_is_idempotent_when_engine_already_absent(monkeypatch) -> None:
    completed: list[compute_pb2.ComputeResponse] = []
    identity = _analysis_identity("analysis-already-gone")

    class _Client:
        def close(self):
            pass

        def complete_compute_request(self, **kwargs):
            completed.append(kwargs["response"])

        def fail_compute_request(self, **_kwargs):
            raise AssertionError("missing engines must complete shutdown successfully")

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())
    manager = ProcessManager(engine_factory=lambda _identity, _resource_config: cast(Any, object()))
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-missing-shutdown",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_command_envelope(
            kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
            request_id="req-missing-shutdown",
            payload={"engine_identity": _engine_identity_payload(identity)},
            shutdown_identity=identity,
        ),
    )

    try:
        compute_request_runtime._execute_request_sync(claimed, manager)
        assert len(completed) == 1
        assert completed[0].WhichOneof("response") == "ack"
        assert completed[0].ack.success is True
    finally:
        manager.shutdown_all()


def test_compute_request_maps_missing_datasource_to_error_result(monkeypatch) -> None:
    completed: list[compute_pb2.ComputeResponse] = []
    metadata_calls = 0

    monkeypatch.setattr(compute_request_runtime, "set_namespace_context", lambda namespace: namespace)
    monkeypatch.setattr(compute_request_runtime, "reset_namespace", lambda token: None)

    class _Client:
        def close(self):
            pass

        def datasource_metadata(self, **_kwargs):
            nonlocal metadata_calls
            metadata_calls += 1
            from runtime.worker_runtime_client import DatasourceMetadata

            return DatasourceMetadata(
                found=False,
                id=None,
                name=None,
                source_type=None,
                config=None,
                schema_cache=None,
                is_hidden=None,
                revision=None,
            )

        def complete_compute_request(self, **kwargs):
            completed.append(kwargs["response"])

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())

    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-404",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=_command_envelope(
            kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
            request_id="req-404",
            payload={"datasource_id": "datasource-1"},
        ),
    )
    claimed.command_envelope.command.input_revisions.add(datasource_id="datasource-1", revision=7)

    compute_request_runtime._execute_request_sync(claimed, cast(Any, SimpleNamespace()))

    assert len(completed) == 1
    assert completed[0].WhichOneof("response") == "datasource"
    assert completed[0].datasource.WhichOneof("result") == "error"
    assert completed[0].datasource.error.error == "datasource_not_found"
    assert completed[0].datasource.error.message == "datasource-1"
    assert metadata_calls == 1


def test_grpc_precondition_error_does_not_invent_domain_error_code() -> None:
    error = compute_request_runtime._error_result(
        BackendWorkerRpcError(
            status_code=412,
            error="Datasource publication claim is no longer active",
            error_code="FAILED_PRECONDITION",
        )
    )

    assert error.status_code == 412
    assert not error.HasField("error_code")


def test_retired_compute_request_lease_drains_without_error_log(monkeypatch, caplog) -> None:
    class _Client:
        def close(self):
            pass

        def fail_compute_request(self, **_kwargs):
            raise BackendWorkerRpcError(
                status_code=412,
                error="Compute request lease is no longer active",
                error_code="FAILED_PRECONDITION",
            )

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", lambda: _Client())
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="req-retired",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_UNSPECIFIED,
        worker_id="worker-test",
        claim_token="claim-test",
        lease_generation=1,
        lease_ttl_seconds=300,
        command_envelope=compute_pb2.ComputeCommandEnvelope(),
    )

    compute_request_runtime._execute_request_sync(claimed, cast(Any, SimpleNamespace()))

    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_datasource_delete_claim_rpc_does_not_block_the_runtime_event_loop() -> None:
    class BlockingClient:
        def pending_datasource_deletes(self, **_kwargs):
            time.sleep(0.05)
            return []

    task = asyncio.create_task(
        datasource_delete_runtime._run_once(
            manager=cast(Any, SimpleNamespace()),
            client=cast(Any, BlockingClient()),
            namespace="default",
        )
    )
    await asyncio.sleep(0.005)
    assert not task.done()
    assert await task is False


@pytest.mark.asyncio
async def test_pending_datasource_delete_waits_for_busy_preview_engine(monkeypatch) -> None:
    datasource_id = "datasource-1"

    cleanup_calls: list[str] = []
    finalized: list[tuple[str, str]] = []
    shutdown_calls: list[str] = []
    busy_engine = SimpleNamespace(current_job_id="job-1", is_process_alive=lambda: True)
    expected_identity = _datasource_preview_identity(datasource_id)
    manager = SimpleNamespace(
        get_engine=lambda identity, *, namespace=None: busy_engine if identity.resource_id == expected_identity.resource_id else None,
        shutdown_engine=lambda identity, *, namespace=None: shutdown_calls.append(identity.resource_id),
    )

    def finalize_delete(*, namespace: str, datasource_id: str) -> bool:
        finalized.append((namespace, datasource_id))
        return True

    client = SimpleNamespace(
        pending_datasource_deletes=lambda **_kwargs: [PendingDatasourceDelete(namespace="default", datasource_id=datasource_id)],
        finalize_datasource_delete=finalize_delete,
        close=lambda: None,
    )

    monkeypatch.setattr(datasource_delete_runtime, "worker_runtime_client", lambda: client)

    handled = await datasource_delete_runtime._run_once(manager=cast(Any, manager), client=cast(Any, client), namespace="default")

    assert handled is False
    assert cleanup_calls == []
    assert finalized == []
    assert shutdown_calls == []


@pytest.mark.asyncio
async def test_pending_datasource_delete_finalizes_once_preview_engine_is_idle(monkeypatch) -> None:
    datasource_id = "datasource-2"

    cleanup_calls: list[str] = []
    finalized: list[tuple[str, str]] = []
    shutdown_calls: list[str] = []
    idle_engine = SimpleNamespace(current_job_id=None, is_process_alive=lambda: True)
    expected_identity = _datasource_preview_identity(datasource_id)
    manager = SimpleNamespace(
        get_engine=lambda identity, *, namespace=None: idle_engine if identity.resource_id == expected_identity.resource_id else None,
        shutdown_engine=lambda identity, *, namespace=None: shutdown_calls.append(identity.resource_id),
    )

    def finalize_delete(*, namespace: str, datasource_id: str) -> bool:
        finalized.append((namespace, datasource_id))
        return True

    client = SimpleNamespace(
        pending_datasource_deletes=lambda **_kwargs: [PendingDatasourceDelete(namespace="default", datasource_id=datasource_id)],
        finalize_datasource_delete=finalize_delete,
        close=lambda: None,
    )

    monkeypatch.setattr(datasource_delete_runtime, "worker_runtime_client", lambda: client)

    handled = await datasource_delete_runtime._run_once(manager=cast(Any, manager), client=cast(Any, client), namespace="default")

    assert handled is True
    assert cleanup_calls == []
    assert finalized == [("default", datasource_id)]
    assert shutdown_calls == [expected_identity.resource_id]


@pytest.mark.asyncio
async def test_pending_datasource_delete_waits_when_backend_defers_finalization(monkeypatch) -> None:
    datasource_id = "datasource-3"
    finalized: list[tuple[str, str]] = []
    manager = SimpleNamespace(
        get_engine=lambda _identity, *, namespace=None: None,
        shutdown_engine=lambda _identity, *, namespace=None: None,
    )

    def finalize_delete(*, namespace: str, datasource_id: str) -> bool:
        finalized.append((namespace, datasource_id))
        return False

    client = SimpleNamespace(
        pending_datasource_deletes=lambda **_kwargs: [PendingDatasourceDelete(namespace="default", datasource_id=datasource_id)],
        finalize_datasource_delete=finalize_delete,
        close=lambda: None,
    )

    monkeypatch.setattr(datasource_delete_runtime, "worker_runtime_client", lambda: client)

    handled = await datasource_delete_runtime._run_once(manager=cast(Any, manager), client=cast(Any, client), namespace="default")

    assert handled is False
    assert finalized == [("default", datasource_id)]


@pytest.mark.asyncio
async def test_run_analysis_build_stream_shuts_down_build_engine_after_completion(
    monkeypatch,
) -> None:
    pipeline = {
        "analysis_id": "analysis-1",
        "tab_id": "tab-1",
        "tabs": [
            {
                "id": "tab-1",
                "name": "Output",
                "datasource": {
                    "id": "source-1",
                    "analysis_tab_id": None,
                    "source_type": "iceberg",
                    "config": {"branch": "main"},
                },
                "output": {
                    "result_id": "out-1",
                    "format": "parquet",
                    "filename": "output_table",
                    "build_mode": "full",
                    "iceberg": {
                        "table_name": "output_table",
                        "namespace": "outputs",
                        "branch": "main",
                    },
                },
                "steps": [],
            }
        ],
    }
    build = RuntimeBuild(
        build_id="build-1",
        analysis_id="analysis-1",
        analysis_name="Analysis 1",
        namespace="default",
        starter=compute_schemas.BuildStarter(triggered_by="user"),
        started_at=datetime.now(UTC),
    )
    events: list[compute_schemas.BuildEvent] = []
    shutdown_calls: list[str] = []
    seen_engine_identities: list[str] = []

    def fake_export_data(*, engine_identity, **_kwargs) -> ExportDatasourceResult:
        seen_engine_identities.append(engine_identity.resource_id)
        return ExportDatasourceResult(
            datasource_id="out-1",
            datasource_name="output_table",
            result_meta={},
            source_datasource_id="source-1",
            engine_run_id="run-1",
        )

    monkeypatch.setattr(compute_service, "export_data", fake_export_data)

    manager = cast(
        Any,
        SimpleNamespace(
            shutdown_engine=lambda identity: shutdown_calls.append(identity.resource_id),
        ),
    )

    async def emitter(event: compute_schemas.BuildEvent) -> None:
        events.append(event)

    result = await compute_service.run_analysis_build_stream(
        session=None,
        manager=manager,
        pipeline=pipeline,
        build=build,
        emitter=emitter,
        triggered_by="user",
    )

    assert result["analysis_id"] == "analysis-1"
    assert seen_engine_identities == ["build-1"]
    assert shutdown_calls == ["build-1"]
    assert events[-1].type == compute_schemas.BuildEventType.COMPLETE


# ---------------------------------------------------------------------------
# EngineRunResponseSchema.progress default
# ---------------------------------------------------------------------------


class TestEngineRunProgressDefault:
    def test_progress_defaults_to_zero(self):
        """progress: float = 0.0 means NULL from DB should not crash."""
        data = {
            "id": "run-1",
            "namespace": "default",
            "analysis_id": None,
            "datasource_id": "ds-1",
            "kind": "preview",
            "status": "success",
            "request_json": {},
            "result_json": None,
            "error_message": None,
            "created_at": "2024-01-01T00:00:00",
            "completed_at": None,
            "duration_ms": None,
            "step_timings": {},
            "query_plan": None,
            "current_step": None,
        }
        schema = EngineRunResponseSchema.model_validate(data)
        assert schema.progress == 0.0

    def test_progress_explicit_value(self):
        data = {
            "id": "run-2",
            "namespace": "default",
            "analysis_id": None,
            "datasource_id": "ds-1",
            "kind": "preview",
            "status": "success",
            "request_json": {},
            "result_json": None,
            "error_message": None,
            "created_at": "2024-01-01T00:00:00",
            "completed_at": None,
            "duration_ms": None,
            "step_timings": {},
            "query_plan": None,
            "progress": 0.75,
            "current_step": "filter",
        }
        schema = EngineRunResponseSchema.model_validate(data)
        assert schema.progress == 0.75


# ---------------------------------------------------------------------------
# NotificationHandler
# ---------------------------------------------------------------------------


class TestNotificationHandler:
    def test_per_row_stages_and_adds_status_column(self):
        """NotificationHandler stages per-row delivery and adds a status column."""
        handler = NotificationHandler()
        lf = pl.DataFrame({"msg": ["hello", "world"]}).lazy()
        result = handler(
            lf,
            {
                "method": "email",
                "recipient": "test@example.com",
                "input_columns": ["msg"],
                "output_column": "status",
                "message_template": "{{msg}}",
                "subject_template": "Test",
            },
            step_id="step-1",
        )
        collected = result.collect()
        assert "status" in collected.columns
        assert collected["status"].to_list() == ["staged", "staged"]

    def test_validates_params(self):
        """Invalid params raise ValidationError."""
        handler = NotificationHandler()
        lf = pl.DataFrame({"a": [1]}).lazy()
        with pytest.raises(ValidationError):
            handler(
                lf,
                {
                    "method": "invalid_method",
                    "recipient": "test@test.com",
                    "input_columns": ["a"],
                },
                step_id="step-1",
            )

    def test_extra_fields_forbidden(self):
        """Extra fields in notification params are rejected."""
        with pytest.raises(ValidationError):
            NotificationParams.model_validate(
                {
                    "method": "email",
                    "recipient": "test@test.com",
                    "input_columns": ["a"],
                    "unknown_field": "bad",
                },
            )

    def test_defaults(self):
        """Default values are applied correctly."""
        params = NotificationParams.model_validate(
            {
                "method": "email",
                "recipient": "test@test.com",
                "input_columns": ["col"],
            },
        )
        assert params.subject_template == "Notification"
        assert params.output_column == "notification_status"
        assert params.message_template == "{{message}}"
        assert params.batch_size == 10


# Template rendering and pipeline notification preparation tests live in test_notification.py.


# ---------------------------------------------------------------------------
# ChartHandler
# ---------------------------------------------------------------------------


def _chart_frame() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "category": ["A", "A", "B", "B", "C"],
            "value": [10.0, 20.0, 30.0, 40.0, 50.0],
            "group": ["x", "y", "x", "y", "x"],
            "group_rank": ["b", "a", "b", "a", "b"],
        },
    ).lazy()


class TestChartParams:
    def test_defaults(self):
        params = ChartParams.model_validate(
            {
                "chart_type": "bar",
                "x_column": "category",
            },
        )
        assert params.aggregation == enums_pb2.CHART_AGGREGATION_SUM
        assert params.bins == 10
        assert params.y_column is None
        assert params.group_column is None
        assert params.sort_by is None
        assert params.sort_order == enums_pb2.SORT_DIRECTION_ASC
        assert params.legend_position == enums_pb2.LEGEND_POSITION_RIGHT
        assert params.decimal_places == 2
        assert params.stack_mode == enums_pb2.STACK_MODE_GROUPED
        assert params.group_sort_by is None
        assert params.group_sort_order == enums_pb2.SORT_DIRECTION_ASC

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            ChartParams.model_validate(
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "unknown": True,
                },
            )

    def test_group_sort_fields(self):
        params = ChartParams.model_validate(
            {
                "chart_type": "bar",
                "x_column": "category",
                "group_column": "group",
                "group_sort_by": "value",
                "group_sort_order": "desc",
            },
        )
        assert params.group_sort_by == enums_pb2.GROUP_SORT_BY_VALUE
        assert params.group_sort_order == enums_pb2.SORT_DIRECTION_DESC

    def test_overlay_validation(self):
        with pytest.raises(ValidationError):
            ChartParams.model_validate(
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "overlays": [
                        {
                            "chart_type": "line",
                            "y_column": "value",
                            "aggregation": "sum",
                            "y_axis_position": "left",
                            "extra": True,
                        },
                    ],
                },
            )

    def test_reference_line_validation(self):
        with pytest.raises(ValidationError):
            ChartParams.model_validate(
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "reference_lines": [
                        {
                            "axis": "z",
                            "value": 1,
                        },
                    ],
                },
            )

    def test_reference_line_value_optional(self):
        params = ChartParams.model_validate(
            {
                "chart_type": "bar",
                "x_column": "category",
                "reference_lines": [
                    {
                        "axis": "y",
                        "value": None,
                    },
                ],
            },
        )
        assert params.reference_lines[0].value is None

    def test_interactivity_defaults(self):
        params = ChartParams.model_validate(
            {
                "chart_type": "bar",
                "x_column": "category",
            },
        )
        assert params.pan_zoom_enabled is False
        assert params.selection_enabled is False
        assert params.area_selection_enabled is False

    def test_protocol_chart_dimensions_are_declared(self):
        params = ChartParams.model_validate(
            {
                "chart_type": "bar",
                "x_column": "category",
                "chart_height": 2,
                "chart_width": 1,
            },
        )

        assert params.chart_height == enums_pb2.CHART_HEIGHT_MEDIUM
        assert params.chart_width == enums_pb2.CHART_WIDTH_NORMAL


class TestChartHandlerPassThrough:
    """Chart handler must return input lf unchanged (pass-through for DAG)."""

    def test_pass_through_preserves_schema(self):
        handler = ChartHandler()
        lf = _chart_frame()
        result = handler(
            lf,
            {
                "chart_type": "bar",
                "x_column": "category",
                "y_column": "value",
                "aggregation": "sum",
            },
        )
        # Pass-through: output columns must match input columns
        assert result.collect_schema().names() == lf.collect_schema().names()

    def test_pass_through_data_unchanged(self):
        handler = ChartHandler()
        lf = _chart_frame()
        result = handler(lf, {"chart_type": "scatter", "x_column": "category", "y_column": "value"})
        assert result.collect().height == lf.collect().height
        assert result.collect().columns == lf.collect().columns


class TestChartDataBar:
    def test_bar_no_group(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "y_column": "value",
                    "aggregation": "sum",
                },
            )
            .collect()
            .sort("x")
        )

        assert result.columns == ["x", "y"]
        assert result["x"].to_list() == ["A", "B", "C"]
        assert result["y"].to_list() == [30.0, 70.0, 50.0]

    def test_bar_with_group(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "y_column": "value",
                    "aggregation": "sum",
                    "group_column": "group",
                },
            )
            .collect()
            .sort("x", "group")
        )

        assert "group" in result.columns
        assert result.height == 5  # A-x, A-y, B-x, B-y, C-x

    def test_bar_count_no_y(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    "chart_type": "bar",
                    "x_column": "category",
                },
            )
            .collect()
            .sort("x")
        )

        assert result["y"].to_list() == [2, 2, 1]

    def test_bar_aggregation_mean(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "y_column": "value",
                    "aggregation": "mean",
                },
            )
            .collect()
            .sort("x")
        )

        assert result["y"].to_list() == [15.0, 35.0, 50.0]

    def test_bar_aggregation_median(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "y_column": "value",
                    "aggregation": "median",
                },
            )
            .collect()
            .sort("x")
        )

        assert result["y"].to_list() == [15.0, 35.0, 50.0]

    def test_bar_aggregation_std(self):
        lf = pl.DataFrame(
            {
                "category": ["A", "A", "A", "B", "B", "B"],
                "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            },
        ).lazy()
        result = (
            compute_chart_data(
                lf,
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "y_column": "value",
                    "aggregation": "std",
                },
            )
            .collect()
            .sort("x")
        )

        assert result["y"].to_list() == pytest.approx([1.0, 1.0])

    def test_bar_aggregation_variance(self):
        lf = pl.DataFrame(
            {
                "category": ["A", "A", "A", "B", "B", "B"],
                "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            },
        ).lazy()
        result = (
            compute_chart_data(
                lf,
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "y_column": "value",
                    "aggregation": "variance",
                },
            )
            .collect()
            .sort("x")
        )

        assert result["y"].to_list() == pytest.approx([1.0, 1.0])

    def test_bar_aggregation_unique_count(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    "chart_type": "bar",
                    "x_column": "category",
                    "y_column": "group",
                    "aggregation": "unique_count",
                },
            )
            .collect()
            .sort("x")
        )

        assert result["y"].to_list() == [2, 2, 1]

    def test_bar_sort_by_y_desc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "bar",
                "x_column": "category",
                "y_column": "value",
                "aggregation": "sum",
                "sort_by": "y",
                "sort_order": "desc",
            },
        ).collect()

        assert result["y"].to_list() == sorted(result["y"].to_list(), reverse=True)

    def test_bar_sort_by_x_desc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "bar",
                "x_column": "category",
                "y_column": "value",
                "aggregation": "sum",
                "sort_by": "x",
                "sort_order": "desc",
            },
        ).collect()

        assert result["x"].to_list() == ["C", "B", "A"]

    def test_bar_date_bucket_month(self):
        lf = pl.DataFrame(
            {
                "date": [
                    "2024-01-05T00:00:00",
                    "2024-01-15T00:00:00",
                    "2024-02-01T00:00:00",
                ],
                "value": [1, 2, 3],
            },
        ).lazy()
        result = (
            compute_chart_data(
                lf,
                {
                    "chart_type": "bar",
                    "x_column": "date",
                    "y_column": "value",
                    "aggregation": "sum",
                    "date_bucket": "month",
                },
            )
            .collect()
            .sort("x")
        )

        assert result["y"].to_list() == [3, 3]

    def test_bar_group_sort_by_value_desc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "bar",
                "x_column": "category",
                "y_column": "value",
                "aggregation": "sum",
                "group_column": "group",
                "group_sort_by": "value",
                "group_sort_order": "desc",
            },
        ).collect()

        groups = result["group"].to_list()
        assert groups[:2] == ["y", "y"]

    def test_bar_group_sort_by_name_desc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "bar",
                "x_column": "category",
                "y_column": "value",
                "aggregation": "sum",
                "group_column": "group",
                "group_sort_by": "name",
                "group_sort_order": "desc",
            },
        ).collect()

        groups = result["group"].to_list()
        assert groups[:2] == ["y", "y"]

    def test_bar_group_sort_by_custom_asc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "bar",
                "x_column": "category",
                "y_column": "value",
                "aggregation": "sum",
                "group_column": "group",
                "group_sort_by": "custom",
                "group_sort_order": "asc",
                "group_sort_column": "group_rank",
            },
        ).collect()

        groups = result["group"].to_list()
        assert groups[:2] == ["y", "y"]


class TestChartDataLine:
    def test_line_basic(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    "chart_type": "line",
                    "x_column": "category",
                    "y_column": "value",
                    "aggregation": "sum",
                },
            )
            .collect()
            .sort("x")
        )

        assert result.columns == ["x", "y"]
        assert result["x"].to_list() == ["A", "B", "C"]

    def test_line_with_group(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "line",
                "x_column": "category",
                "y_column": "value",
                "group_column": "group",
            },
        ).collect()

        assert "group" in result.columns


class TestChartDataPie:
    def test_pie_basic(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "pie",
                "x_column": "category",
                "y_column": "value",
            },
        ).collect()

        assert "label" in result.columns
        assert "y" in result.columns
        assert set(result["label"].to_list()) == {"A", "B", "C"}

    def test_pie_sorted_descending(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "pie",
                "x_column": "category",
                "y_column": "value",
            },
        ).collect()

        # Should be sorted by y descending
        values = result["y"].to_list()
        assert values == sorted(values, reverse=True)

    def test_pie_sort_by_label(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "pie",
                "x_column": "category",
                "y_column": "value",
                "sort_by": "x",
                "sort_order": "asc",
            },
        ).collect()

        assert result["label"].to_list() == ["A", "B", "C"]

    def test_pie_group_sort_by_name(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "pie",
                "x_column": "category",
                "y_column": "value",
                "group_column": "group",
                "group_sort_by": "name",
                "group_sort_order": "desc",
            },
        ).collect()

        assert result["group"].to_list()[0] == "y"

    def test_pie_date_ordinal_day_of_week(self):
        lf = pl.DataFrame(
            {
                "date": [
                    "2024-01-01T00:00:00",
                    "2024-01-08T00:00:00",
                ],
                "value": [5, 7],
            },
        ).lazy()
        result = compute_chart_data(
            lf,
            {
                "chart_type": "pie",
                "x_column": "date",
                "y_column": "value",
                "date_ordinal": "day_of_week",
            },
        ).collect()

        assert set(result["label"].to_list()) == {0}

    def test_pie_group_sort_by_value(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "pie",
                "x_column": "category",
                "y_column": "value",
                "group_column": "group",
                "group_sort_by": "value",
                "group_sort_order": "desc",
            },
        ).collect()

        assert result["group"].to_list()[0] == "y"

    def test_pie_group_sort_by_custom(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "pie",
                "x_column": "category",
                "y_column": "value",
                "group_column": "group",
                "group_sort_by": "custom",
                "group_sort_order": "desc",
                "group_sort_column": "group",
            },
        ).collect()

        assert result["group"].to_list()[0] == "y"


class TestChartDataHistogram:
    def test_histogram_basic(self):
        lf = pl.DataFrame({"val": list(range(100))}).lazy()
        result = compute_chart_data(
            lf,
            {
                "chart_type": "histogram",
                "x_column": "val",
                "bins": 10,
            },
        ).collect()

        assert result.columns == ["bin_start", "bin_end", "count"]
        assert result.height == 10
        assert sum(result["count"].to_list()) == 100

    def test_histogram_empty(self):
        lf = pl.DataFrame({"val": []}).cast({"val": pl.Float64}).lazy()
        result = compute_chart_data(
            lf,
            {
                "chart_type": "histogram",
                "x_column": "val",
            },
        ).collect()

        assert result.height == 0

    def test_histogram_single_value(self):
        lf = pl.DataFrame({"val": [5.0, 5.0, 5.0]}).lazy()
        result = compute_chart_data(
            lf,
            {
                "chart_type": "histogram",
                "x_column": "val",
            },
        ).collect()

        assert result.height == 1
        assert result["count"].to_list() == [3]


class TestChartDataScatter:
    def test_scatter_basic(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "scatter",
                "x_column": "category",
                "y_column": "value",
            },
        ).collect()

        assert "x" in result.columns
        assert "y" in result.columns
        assert result.height == 5

    def test_scatter_with_group(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                "chart_type": "scatter",
                "x_column": "category",
                "y_column": "value",
                "group_column": "group",
            },
        ).collect()

        assert "group" in result.columns

    def test_scatter_limit_5000(self):
        lf = pl.DataFrame(
            {
                "x": list(range(10000)),
                "y": list(range(10000)),
            },
        ).lazy()
        result = compute_chart_data(
            lf,
            {
                "chart_type": "scatter",
                "x_column": "x",
                "y_column": "y",
            },
        ).collect()

        assert result.height == 5000


class TestChartDataBoxplot:
    def test_boxplot_with_group(self):
        lf = pl.DataFrame(
            {
                "cat": ["A"] * 100 + ["B"] * 100,
                "val": list(range(100)) + list(range(50, 150)),
            },
        ).lazy()
        result = (
            compute_chart_data(
                lf,
                {
                    "chart_type": "boxplot",
                    "x_column": "cat",
                    "y_column": "val",
                },
            )
            .collect()
            .sort("group")
        )

        assert result.columns == ["group", "min", "q1", "median", "q3", "max"]
        assert result.height == 2
        assert result["group"].to_list() == ["A", "B"]
        # A: min=0, max=99; B: min=50, max=149
        assert result["min"].to_list() == [0.0, 50.0]
        assert result["max"].to_list() == [99.0, 149.0]

    def test_boxplot_no_group(self):
        lf = pl.DataFrame({"val": list(range(100))}).lazy()
        result = compute_chart_data(
            lf,
            {
                "chart_type": "boxplot",
                "x_column": "val",
            },
        ).collect()

        assert result.height == 1
        assert "group" in result.columns
        assert result["group"].to_list() == ["all"]
        assert result["min"][0] == 0.0
        assert result["max"][0] == 99.0


class TestChartDataHeatgrid:
    def test_heatgrid_basic(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    "chart_type": "heatgrid",
                    "x_column": "category",
                    "y_column": "group",
                    "aggregation": "count",
                },
            )
            .collect()
            .sort(["x", "y"])
        )

        assert result.columns == ["x", "y", "value"]
        assert result["value"].to_list() == [1, 1, 1, 1, 1]


# ---------------------------------------------------------------------------
# Step Timing Labels — human-readable names instead of UUIDs
# ---------------------------------------------------------------------------


class TestStepTimingLabels:
    def test_missing_object_store_metadata_is_datasource_metadata_missing(self):
        error = RuntimeError("AWS Error NO_SUCH_KEY during GetObject operation: The specified key does not exist.")

        error_kind, error_details = PolarsComputeEngine._classify_engine_error(error)

        assert error_kind == "datasource_metadata_missing"
        assert error_details == {}

    def _make_csv_config(self) -> tuple[str, dict]:
        """Create a temp CSV file and return (path, datasource_config)."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w") as f:
            f.write("a,b\n1,4\n2,5\n3,6\n")
        config = {"source_type": "file", "file_path": path, "file_type": "csv"}
        return path, config

    def test_timing_keys_use_step_type(self):
        """step_timings keys should use step type, not UUID."""
        path, config = self._make_csv_config()
        try:
            steps = [
                {
                    "id": "id-abc123",
                    "type": "select",
                    "config": {"columns": ["a"]},
                    "depends_on": [],
                },
            ]
            _, timings, _plan_frames, _read_duration_ms = PolarsComputeEngine._build_pipeline(config, steps, "job-1")
            assert "select" in timings
            assert "id-abc123" not in timings
        finally:
            os.unlink(path)

    def test_timing_keys_deduplicate(self):
        """Multiple steps of same type get _2, _3, etc."""
        path, config = self._make_csv_config()
        try:
            steps = [
                {
                    "id": "id-1",
                    "type": "select",
                    "config": {"columns": ["a", "b"]},
                    "depends_on": [],
                },
                {
                    "id": "id-2",
                    "type": "select",
                    "config": {"columns": ["a"]},
                    "depends_on": ["id-1"],
                },
            ]
            _, timings, _plan_frames, _read_duration_ms = PolarsComputeEngine._build_pipeline(config, steps, "job-2")
            assert "select" in timings
            assert "select_2" in timings
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# ChartParams sort_by / group_sort_by coercion
# ---------------------------------------------------------------------------


class TestChartParamsSortByCoercion:
    def test_invalid_sort_by_coerces_to_none(self):
        params = ChartParams.model_validate({"chart_type": "bar", "x_column": "cat", "sort_by": "rank"})
        assert params.sort_by is None

    def test_invalid_group_sort_by_coerces_to_none(self):
        params = ChartParams.model_validate({"chart_type": "bar", "x_column": "cat", "group_sort_by": "total"})
        assert params.group_sort_by is None

    def test_valid_sort_by_preserved(self):
        params = ChartParams.model_validate({"chart_type": "bar", "x_column": "cat", "sort_by": "y"})
        assert params.sort_by == enums_pb2.SORT_BY_Y

    def test_valid_group_sort_by_preserved(self):
        params = ChartParams.model_validate({"chart_type": "bar", "x_column": "cat", "group_sort_by": "value"})
        assert params.group_sort_by == enums_pb2.GROUP_SORT_BY_VALUE

    def test_invalid_sort_by_does_not_raise_in_compute(self):
        lf = pl.DataFrame({"cat": ["A", "B"], "val": [1.0, 2.0]}).lazy()
        result = compute_chart_data(
            lf,
            {
                "chart_type": "bar",
                "x_column": "cat",
                "y_column": "val",
                "sort_by": "rank",
            },
        ).collect()
        assert result.height == 2


# ---------------------------------------------------------------------------
# Security audit fixes — PR #30
# ---------------------------------------------------------------------------


class TestSafeBuiltinsUdf:
    """UDF execution sandbox must not allow attribute-chain escapes."""

    def _run_udf(self, code: str):
        # exec() here is intentional: we are verifying that the _SAFE_BUILTINS
        # sandbox correctly blocks dangerous builtins. The code strings are
        # hard-coded in each test — no user input reaches this helper.

        import polars as pl

        from operations.with_columns import _SAFE_BUILTINS

        scope: dict[str, Any] = {"pl": pl, "__builtins__": _SAFE_BUILTINS}
        local_scope: dict[str, Any] = {}
        exec(code, scope, local_scope)  # noqa: S102
        udf = local_scope.get("udf") or scope.get("udf")
        return udf() if udf else None

    def test_getattr_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf('def udf(): return getattr([], "__class__")')

    def test_setattr_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf('def udf():\n    class C: pass\n    setattr(C, "x", 1)\n    return C.x')

    def test_vars_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf("def udf(): return vars()")

    def test_dir_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf("def udf(): return dir([])")

    def test_open_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf('def udf(): return open("/etc/passwd")')

    def test_dunder_escape_blocked_before_exec(self):
        from operations.with_columns import WithColumnsHandler

        handler = WithColumnsHandler()
        with pytest.raises(ValueError, match="forbidden dunder access"):
            handler(
                pl.DataFrame({"id": [1]}).lazy(),
                {
                    "expressions": [
                        {
                            "name": "bad",
                            "type": "udf",
                            "code": "def udf():\n    return [].__class__",
                        }
                    ]
                },
            )

    def test_safe_arithmetic_works(self):
        result = self._run_udf("def udf(): return 2 + 2")
        assert result == 4

    def test_safe_len_works(self):
        result = self._run_udf("def udf(): return len([1, 2, 3])")
        assert result == 3


class TestValidateRegexPattern:
    """Shared operations.validation.validate_regex_pattern helper."""

    def test_valid_pattern_passes(self):
        from operations.validation import validate_regex_pattern

        validate_regex_pattern(r"\d+")

    def test_invalid_pattern_raises(self):
        from operations.validation import validate_regex_pattern

        with pytest.raises(ValueError, match="Invalid regex pattern"):
            validate_regex_pattern(r"[unclosed")


class TestAssertSelectOnly:
    """SQL read-only guard in datasource operations."""

    def _check(self, query: str):
        from datasources.datasource_loading import _assert_select_only

        _assert_select_only(query)

    def test_select_allowed(self):
        self._check("SELECT * FROM t")

    def test_select_leading_whitespace(self):
        self._check("  SELECT * FROM t")

    def test_with_cte_allowed(self):
        self._check("WITH cte AS (SELECT 1) SELECT * FROM cte")

    def test_insert_rejected(self):
        with pytest.raises(ValueError, match="Only SELECT"):
            self._check("INSERT INTO t VALUES (1)")

    def test_drop_rejected(self):
        with pytest.raises(ValueError, match="Only SELECT"):
            self._check("DROP TABLE t")

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="Only SELECT"):
            self._check("")


class TestParseDatetimeString:
    """FilterValueType.parse_datetime accepts ISO 8601 only."""

    def test_iso8601(self):
        from datetime import datetime

        from operations.filter import FilterValueType

        dt = FilterValueType.parse_datetime("2024-06-15T12:30:00")
        assert dt == datetime(2024, 6, 15, 12, 30, 0)

    def test_z_suffix(self):
        from operations.filter import FilterValueType

        dt = FilterValueType.parse_datetime("2024-06-15T12:30:00Z")
        assert dt.year == 2024 and dt.month == 6 and dt.day == 15

    def test_non_iso_rejected(self):
        from operations.filter import FilterValueType

        with pytest.raises(ValueError, match="Accepted format: ISO 8601"):
            FilterValueType.parse_datetime("2024-06-15 12:30:00")

    def test_invalid_raises(self):
        from operations.filter import FilterValueType

        with pytest.raises(ValueError, match="Cannot parse datetime string"):
            FilterValueType.parse_datetime("not-a-date")


class TestCoerceValueNumber:
    """coerce_value handles scientific notation strings correctly."""

    def test_integer_string(self):
        from operations.filter import FilterValueType

        assert FilterValueType.NUMBER.coerce("42") == 42
        assert isinstance(FilterValueType.NUMBER.coerce("42"), int)

    def test_float_string(self):
        from operations.filter import FilterValueType

        assert FilterValueType.NUMBER.coerce("3.14") == pytest.approx(3.14)

    def test_scientific_notation(self):
        from operations.filter import FilterValueType

        val = FilterValueType.NUMBER.coerce("1e5")
        assert val == pytest.approx(100000.0)
        assert isinstance(val, float)  # '1e5' contains 'e', must stay float
