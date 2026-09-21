from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import grpc
import pytest

from dataforge_protocol import engine_runtime_pb2, engine_runtime_pb2_grpc
from runtime import engine_server
from runtime.domain.compute.base import EngineResult
from runtime.engine_server import ENGINE_PROTOCOL_VERSION, PolarsEngineServicer, _EngineJobs


@pytest.fixture
def engine_stub(monkeypatch):
    def execute(*, job_id: str, kind: str, payload: dict, progress_callback):
        assert kind == "preview"
        assert payload == {"datasource_config": {}, "steps": [], "row_limit": 100, "offset": 0}
        assert isinstance(payload["row_limit"], int)
        assert isinstance(payload["offset"], int)
        progress_callback({"type": "compute_start"})
        return EngineResult(job_id=job_id, data={"rows": [], "as_of": date(2026, 8, 10)}, error=None)

    monkeypatch.setattr(engine_server, "_execute_job", execute)
    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    engine_runtime_pb2_grpc.add_PolarsEngineServiceServicer_to_server(
        PolarsEngineServicer(engine_identity="analysis-1", application_version="test", token="token", on_shutdown=lambda: None), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield engine_runtime_pb2_grpc.PolarsEngineServiceStub(channel)
    finally:
        channel.close()
        server.stop(grace=0)


def test_engine_server_submits_and_streams_progress_and_result(engine_stub) -> None:
    metadata = (("x-engine-token", "token"),)
    health = engine_stub.Health(engine_runtime_pb2.EngineHealthRequest(), metadata=metadata)
    assert health.ready
    assert health.engine_identity == "analysis-1"
    assert health.protocol_version == ENGINE_PROTOCOL_VERSION

    submitted = engine_stub.SubmitJob(
        engine_runtime_pb2.EngineSubmitJobRequest(
            protocol_version=ENGINE_PROTOCOL_VERSION,
            job_id="job-1",
            kind="preview",
            payload_json=json.dumps({"datasource_config": {}, "steps": [], "row_limit": 100, "offset": 0}).encode(),
        ),
        metadata=metadata,
    )
    assert submitted.job_id == "job-1"

    events = list(engine_stub.WatchJob(engine_runtime_pb2.EngineWatchJobRequest(job_id="job-1"), metadata=metadata))
    assert json.loads(events[0].progress_json)["type"] == "compute_start"
    assert events[1].result.job_id == "job-1"
    assert json.loads(events[1].result.data_json) == {"rows": [], "as_of": "2026-08-10"}


def test_engine_server_rejects_invalid_token(engine_stub) -> None:
    with pytest.raises(grpc.RpcError) as exc_info:
        engine_stub.Health(engine_runtime_pb2.EngineHealthRequest(), metadata=(("x-engine-token", "invalid"),))
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


def test_export_stages_artifact_in_object_store(monkeypatch, tmp_path) -> None:
    staged: dict[str, object] = {}

    def execute_export(_datasource, _steps, output_path, export_format, _job_id, _additional, _progress):
        assert export_format == "parquet"
        with open(output_path, "wb") as output:
            output.write(b"parquet")
        return {"row_count": 1, "step_timings": {}}

    class Response:
        def raise_for_status(self) -> None:
            return None

    def put(url, *, data, headers, timeout):
        staged.update(url=url, content_type=headers["Content-Type"], data=data.read(), timeout=timeout)
        return Response()

    monkeypatch.setattr(engine_server.PolarsComputeEngine, "execute_export", execute_export)
    monkeypatch.setattr(engine_server.requests, "put", put)

    result = engine_server._execute_job(
        job_id="job-1",
        kind="export",
        payload={
            "datasource_config": {},
            "steps": [],
            "artifact_url": "s3://tenant-a/runtime-staging/engine/job-1/output.parquet",
            "artifact_upload_url": "http://object-store/presigned-put",
            "export_format": "parquet",
        },
        progress_callback=lambda _event: None,
    )

    assert staged["data"] == b"parquet"
    assert staged["url"] == "http://object-store/presigned-put"
    assert result.data is not None
    assert result.data["output_path"] == "s3://tenant-a/runtime-staging/engine/job-1/output.parquet"


def test_engine_job_retention_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(
        engine_server,
        "_execute_job",
        lambda *, job_id, **_kwargs: EngineResult(job_id=job_id, data={}, error=None),
    )
    jobs = _EngineJobs()
    try:
        for index in range(105):
            state = jobs.submit(job_id=f"job-{index}", kind="preview", payload={})
            with state.condition:
                state.condition.wait_for(lambda state=state: state.done, timeout=1)
        assert len(jobs._jobs) == 8
        assert "job-0" not in jobs._jobs
        assert "job-104" in jobs._jobs
    finally:
        jobs.shutdown()


def test_engine_jobs_cancel_queued_job_without_stopping_running_job(monkeypatch) -> None:
    running_started = threading.Event()
    release_running = threading.Event()

    def execute(*, job_id: str, **_kwargs):
        if job_id == "running":
            running_started.set()
            assert release_running.wait(timeout=2)
        return EngineResult(job_id=job_id, data={}, error=None)

    monkeypatch.setattr(engine_server, "_execute_job", execute)
    jobs = _EngineJobs()
    try:
        running = jobs.submit(job_id="running", kind="preview", payload={})
        assert running_started.wait(timeout=1)
        queued = jobs.submit(job_id="queued", kind="preview", payload={})

        assert jobs.cancel("queued")
        with queued.condition:
            assert queued.condition.wait_for(lambda: queued.done, timeout=1)
            assert queued.result is not None
            assert queued.result.error_kind == "job_cancelled"

        release_running.set()
        with running.condition:
            assert running.condition.wait_for(lambda: running.done, timeout=1)
            assert running.result is not None
            assert running.result.error is None
    finally:
        release_running.set()
        jobs.shutdown()


def test_engine_jobs_run_independent_requests_concurrently(monkeypatch) -> None:
    entered = 0
    entered_lock = threading.Lock()
    both_entered = threading.Event()
    release = threading.Event()

    def execute(*, job_id: str, **_kwargs):
        nonlocal entered
        with entered_lock:
            entered += 1
            if entered == 2:
                both_entered.set()
        assert release.wait(timeout=2)
        return EngineResult(job_id=job_id, data={}, error=None)

    monkeypatch.setattr(engine_server, "_execute_job", execute)
    jobs = _EngineJobs(max_workers=2)
    try:
        first = jobs.submit(job_id="first", kind="preview", payload={})
        second = jobs.submit(job_id="second", kind="preview", payload={})
        assert both_entered.wait(timeout=1), "the second independent job was queued behind the first"
        release.set()
        for state in (first, second):
            with state.condition:
                assert state.condition.wait_for(lambda state=state: state.done, timeout=1)
                assert state.result is not None
                assert state.result.error is None
    finally:
        release.set()
        jobs.shutdown()


def test_engine_rpc_control_calls_are_not_starved_by_watch_streams(monkeypatch) -> None:
    release_jobs = threading.Event()

    def execute(*, job_id: str, **_kwargs):
        assert release_jobs.wait(timeout=5)
        return EngineResult(job_id=job_id, data={}, error=None)

    monkeypatch.setattr(engine_server, "_execute_job", execute)
    server = grpc.server(
        ThreadPoolExecutor(max_workers=engine_server._engine_rpc_worker_count(4)),
    )
    engine_runtime_pb2_grpc.add_PolarsEngineServiceServicer_to_server(
        PolarsEngineServicer(
            engine_identity="shared-preview",
            application_version="test",
            token="token",
            on_shutdown=lambda: None,
            engine_job_concurrency=4,
        ),
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = engine_runtime_pb2_grpc.PolarsEngineServiceStub(channel)
    metadata = (("x-engine-token", "token"),)
    watch_pool = ThreadPoolExecutor(max_workers=8)
    watch_futures = []

    try:
        for index in range(8):
            stub.SubmitJob(
                engine_runtime_pb2.EngineSubmitJobRequest(
                    protocol_version=ENGINE_PROTOCOL_VERSION,
                    job_id=f"burst-{index}",
                    kind="preview",
                    payload_json=b"{}",
                ),
                metadata=metadata,
            )

        watch_futures = [
            watch_pool.submit(
                lambda job_id=job_id: list(
                    stub.WatchJob(
                        engine_runtime_pb2.EngineWatchJobRequest(job_id=job_id),
                        metadata=metadata,
                    )
                )
            )
            for job_id in (f"burst-{index}" for index in range(8))
        ]

        # With the old eight-thread server pool these streams consumed every
        # handler and this call hit its deadline. The production-sized pool
        # must continue serving liveness/control traffic independently.
        health = stub.Health(engine_runtime_pb2.EngineHealthRequest(), metadata=metadata, timeout=2)
        assert health.ready
    finally:
        release_jobs.set()
        for future in watch_futures:
            future.result(timeout=5)
        watch_pool.shutdown(wait=True)
        channel.close()
        server.stop(grace=0)


def test_engine_server_warm_mode_and_initialize(monkeypatch) -> None:
    def execute(*, job_id: str, kind: str, payload: dict, progress_callback):
        return EngineResult(job_id=job_id, data={"rows": []}, error=None)

    monkeypatch.setattr(engine_server, "_execute_job", execute)
    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    servicer = PolarsEngineServicer(
        engine_identity="",
        application_version="test",
        token="",
        on_shutdown=lambda: None,
    )
    engine_runtime_pb2_grpc.add_PolarsEngineServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = engine_runtime_pb2_grpc.PolarsEngineServiceStub(channel)

    try:
        # 1. Uninitialized warm probe
        health = stub.Health(engine_runtime_pb2.EngineHealthRequest())
        assert not health.ready
        assert health.engine_identity == ""

        # 2. Uninitialized submit rejected
        with pytest.raises(grpc.RpcError) as exc_info:
            stub.SubmitJob(
                engine_runtime_pb2.EngineSubmitJobRequest(
                    protocol_version=ENGINE_PROTOCOL_VERSION,
                    job_id="warm-job",
                    kind="preview",
                    payload_json=b"{}",
                )
            )
        assert exc_info.value.code() == grpc.StatusCode.FAILED_PRECONDITION

        # 3. Initialize RPC
        init_resp = stub.Initialize(
            engine_runtime_pb2.EngineInitializeRequest(
                protocol_version=ENGINE_PROTOCOL_VERSION,
                engine_identity="analysis-warm-1",
                token="warm-token-123",
                object_store_endpoint="http://rustfs:9000",
                object_store_region="us-east-1",
                object_store_access_key="key",
                object_store_secret_key="secret",
                polars_max_threads=4,
                polars_streaming_chunk_size=1000,
            )
        )
        assert init_resp.ready
        assert init_resp.engine_identity == "analysis-warm-1"

        # 4. Authenticated health
        auth_health = stub.Health(
            engine_runtime_pb2.EngineHealthRequest(),
            metadata=(("x-engine-token", "warm-token-123"),),
        )
        assert auth_health.ready
        assert auth_health.engine_identity == "analysis-warm-1"

        # 5. Unauthenticated rejected after init
        with pytest.raises(grpc.RpcError) as exc_info:
            stub.Health(engine_runtime_pb2.EngineHealthRequest())
        assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED

        # 6. SubmitJob succeeds with token
        submitted = stub.SubmitJob(
            engine_runtime_pb2.EngineSubmitJobRequest(
                protocol_version=ENGINE_PROTOCOL_VERSION,
                job_id="job-initialized",
                kind="preview",
                payload_json=b"{}",
            ),
            metadata=(("x-engine-token", "warm-token-123"),),
        )
        assert submitted.job_id == "job-initialized"
    finally:
        channel.close()
        server.stop(grace=0)


def test_uninitialized_engine_stops_after_init_deadline(monkeypatch) -> None:
    shutdowns: list[str] = []

    def execute(*, job_id: str, kind: str, payload: dict, progress_callback):
        return EngineResult(job_id=job_id, data={"rows": []}, error=None)

    monkeypatch.setattr(engine_server, "_execute_job", execute)
    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    servicer = PolarsEngineServicer(
        engine_identity="",
        application_version="test",
        token="",
        on_shutdown=lambda: shutdowns.append("stopped"),
        heartbeat_timeout_seconds=15,
        init_timeout_seconds=1,
    )
    engine_runtime_pb2_grpc.add_PolarsEngineServiceServicer_to_server(servicer, server)
    server.start()

    try:
        # Watchdog checks every ~1s; the 1s deadline must fire and stop the
        # engine because no Initialize arrived.
        deadline = time.monotonic() + 10
        while not shutdowns and time.monotonic() < deadline:
            time.sleep(0.2)
        assert shutdowns == ["stopped"]
    finally:
        server.stop(grace=0)


def test_initialized_engine_ignores_init_deadline(monkeypatch) -> None:
    def execute(*, job_id: str, kind: str, payload: dict, progress_callback):
        return EngineResult(job_id=job_id, data={"rows": []}, error=None)

    monkeypatch.setattr(engine_server, "_execute_job", execute)
    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    servicer = PolarsEngineServicer(
        engine_identity="",
        application_version="test",
        token="",
        on_shutdown=lambda: None,
        heartbeat_timeout_seconds=15,
        init_timeout_seconds=1,
    )
    engine_runtime_pb2_grpc.add_PolarsEngineServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = engine_runtime_pb2_grpc.PolarsEngineServiceStub(channel)

    try:
        stub.Initialize(
            engine_runtime_pb2.EngineInitializeRequest(
                protocol_version=ENGINE_PROTOCOL_VERSION,
                engine_identity="analysis-1",
                token="token",
            )
        )
        # Initialized before the deadline: the engine must stay up past it.
        time.sleep(2)
        health = stub.Health(
            engine_runtime_pb2.EngineHealthRequest(),
            metadata=(("x-engine-token", "token"),),
        )
        assert health.ready
    finally:
        channel.close()
        server.stop(grace=0)
