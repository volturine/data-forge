from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest

from dataforge_protocol import common_pb2, iceberg_pb2, object_store_pb2
from runtime.config import settings
from runtime.worker_runtime_client import BackendWorkerRpcError
from worker_grpc import data_plane_server
from worker_grpc.data_plane_server import IcebergServicer, ObjectStoreServicer


class FakeGrpcContext:
    def __init__(self, token: str) -> None:
        self._metadata = (("x-internal-token", token),)

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._metadata

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        raise RuntimeError(f"{code.name}: {details}")


def _context(monkeypatch: pytest.MonkeyPatch) -> FakeGrpcContext:
    token = "test-internal-token"
    monkeypatch.setattr(settings, "internal_api_token", token)
    return FakeGrpcContext(token)


@pytest.mark.asyncio
async def test_request_validation_runs_off_loop_with_bounded_parallelism(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    validation_started = threading.Event()
    release_validation = threading.Event()
    active = 0
    max_active = 0
    validation_threads: set[int] = set()
    active_lock = threading.Lock()

    def validate(_request, _method: str) -> None:
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
            validation_threads.add(threading.get_ident())
            if active == data_plane_server._VALIDATION_WORKERS:
                validation_started.set()
        if not release_validation.wait(timeout=5):
            raise TimeoutError("test did not release protobuf validation")
        with active_lock:
            active -= 1

    async def service(request, _context):
        return request

    async def continuation(_details):
        return grpc.unary_unary_rpc_method_handler(service)

    monkeypatch.setattr(data_plane_server, "_validate_proto", validate)
    interceptor = data_plane_server._WorkerRequestValidationInterceptor()
    handler = await interceptor.intercept_service(continuation, object())
    assert handler is not None and handler.unary_unary is not None

    calls = [asyncio.create_task(handler.unary_unary(common_pb2.EmptyRequest(), None)) for _ in range(data_plane_server._VALIDATION_WORKERS + 1)]
    try:
        assert await asyncio.to_thread(validation_started.wait, 2)
        await asyncio.sleep(0)
        with active_lock:
            assert active == data_plane_server._VALIDATION_WORKERS
        assert not calls[-1].done()
    finally:
        release_validation.set()
        await asyncio.gather(*calls, return_exceptions=True)

    assert max_active == data_plane_server._VALIDATION_WORKERS
    assert validation_threads
    assert loop_thread not in validation_threads


@pytest.mark.asyncio
async def test_blocking_lane_bounds_executor_queue_under_burst() -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = data_plane_server._BlockingLane(executor, max_in_flight=3)
    started = threading.Event()
    release = threading.Event()

    def blocking_call() -> None:
        started.set()
        assert release.wait(timeout=5)

    calls = [asyncio.create_task(data_plane_server._run_blocking(lane, blocking_call)) for _ in range(20)]
    try:
        assert await asyncio.to_thread(started.wait, 2)
        await asyncio.sleep(0.05)
        assert executor._work_queue.qsize() <= 2
        assert lane.semaphore(asyncio.get_running_loop())._value == 0
    finally:
        release.set()
        await asyncio.gather(*calls)
        await asyncio.to_thread(executor.shutdown, True)


@pytest.mark.asyncio
async def test_pending_blocking_call_cancellation_does_not_leak_admission() -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = data_plane_server._BlockingLane(executor, max_in_flight=1)
    started = threading.Event()
    release = threading.Event()

    def blocking_call() -> None:
        started.set()
        assert release.wait(timeout=5)

    running = asyncio.create_task(data_plane_server._run_blocking(lane, blocking_call))
    pending = asyncio.create_task(data_plane_server._run_blocking(lane, lambda: None))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        release.set()
        await running
        assert await data_plane_server._run_blocking(lane, lambda: "admitted") == "admitted"
    finally:
        release.set()
        await asyncio.gather(running, pending, return_exceptions=True)
        await asyncio.to_thread(executor.shutdown, True)


@pytest.mark.asyncio
async def test_running_call_holds_admission_until_thread_settles() -> None:
    executor = ThreadPoolExecutor(max_workers=2)
    lane = data_plane_server._BlockingLane(executor, max_in_flight=1)
    started = threading.Event()
    release = threading.Event()
    later_started = threading.Event()

    def blocking_call() -> None:
        started.set()
        assert release.wait(timeout=5)

    running = asyncio.create_task(data_plane_server._run_blocking(lane, blocking_call))
    later = None
    try:
        assert await asyncio.to_thread(started.wait, 2)
        running.cancel()
        later = asyncio.create_task(data_plane_server._run_blocking(lane, later_started.set))
        await asyncio.sleep(0.05)
        assert not later_started.is_set()
        assert lane.semaphore(asyncio.get_running_loop())._value == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
        await later
        assert later_started.is_set()
    finally:
        release.set()
        tasks = [running]
        if later is not None:
            tasks.append(later)
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(executor.shutdown, True)


@pytest.mark.asyncio
async def test_snapshot_response_serialization_runs_off_grpc_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    serialization_threads: list[int] = []

    class FakeFrame:
        def collect(self) -> FakeFrame:
            return self

        def to_dicts(self) -> list[dict[str, object]]:
            return [{"value": 1}]

    async def allow_request(_context) -> None:
        return None

    def serialize(payload: dict[str, object]):
        from google.protobuf import struct_pb2

        serialization_threads.append(threading.get_ident())
        return struct_pb2.Struct()

    monkeypatch.setattr(data_plane_server, "_require_internal_token", allow_request)
    monkeypatch.setattr(data_plane_server.iceberg_snapshot_reader, "scan_iceberg_snapshot", lambda *_args: FakeFrame())
    monkeypatch.setattr(data_plane_server, "dict_to_struct", serialize)

    response = await IcebergServicer().ScanSnapshot(
        iceberg_pb2.IcebergSnapshotScanRequest(metadata_path="metadata.json", snapshot_id="1"),
        object(),
    )

    assert response.rows is not None
    assert serialization_threads and all(thread_id != loop_thread for thread_id in serialization_threads)


def test_slow_request_validation_logs_its_duration(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    class SlowValidator:
        def validate(self, _request) -> None:
            time.sleep(data_plane_server._SLOW_VALIDATION_SECONDS + 0.02)

    monkeypatch.setattr(data_plane_server, "Validator", SlowValidator)
    if hasattr(data_plane_server._VALIDATOR_LOCAL, "validator"):
        del data_plane_server._VALIDATOR_LOCAL.validator

    with caplog.at_level("WARNING", logger=data_plane_server.__name__):
        data_plane_server._validate_proto(common_pb2.EmptyRequest(), "/test/slow")

    assert "Slow worker request validation" in caplog.text
    assert "method=/test/slow" in caplog.text
    assert "validation_ms=" in caplog.text


@pytest.mark.asyncio
async def test_object_store_classification_is_worker_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    servicer = ObjectStoreServicer()

    managed = await servicer.ClassifyUrl(
        object_store_pb2.ObjectStoreUrlClassificationRequest(value="s3://default/uploads/file.csv"),
        context,
    )
    external = await servicer.ClassifyUrl(
        object_store_pb2.ObjectStoreUrlClassificationRequest(value="s3://External-Bucket/file.csv"),
        context,
    )
    other_ns = await servicer.ClassifyUrl(
        object_store_pb2.ObjectStoreUrlClassificationRequest(value="s3://analytics/clean/file.csv"),
        context,
    )
    bucket_only = await servicer.ClassifyUrl(
        object_store_pb2.ObjectStoreUrlClassificationRequest(value="s3://default"),
        context,
    )
    local = await servicer.ClassifyUrl(
        object_store_pb2.ObjectStoreUrlClassificationRequest(value="/tmp/file.csv"),
        context,
    )

    assert managed.is_object_store is True
    assert managed.is_managed is True
    assert managed.object_url.url == "s3://default/uploads/file.csv"
    assert external.is_object_store is True
    assert external.is_managed is False
    assert other_ns.is_object_store is True
    assert other_ns.is_managed is True
    assert bucket_only.is_object_store is False
    assert local.is_object_store is False
    assert local.is_managed is False


@pytest.mark.asyncio
async def test_object_store_build_url_namespace_is_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    servicer = ObjectStoreServicer()

    built = await servicer.BuildUrl(
        object_store_pb2.ObjectStorePathParts(parts=["uploads", "file.csv"], namespace="analytics"),
        context,
    )
    assert built.url == "s3://analytics/uploads/file.csv"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "rpc_message"),
    [
        ("ListSnapshots", iceberg_pb2.IcebergTableRef(namespace="analytics", datasource_id="datasource-1")),
        (
            "DeleteSnapshot",
            iceberg_pb2.IcebergSnapshotDeleteRequest(namespace="analytics", datasource_id="datasource-1", snapshot_id="1"),
        ),
    ],
)
async def test_iceberg_servicers_preserve_nested_runtime_deadline_status(
    method: str,
    rpc_message: iceberg_pb2.IcebergTableRef | iceberg_pb2.IcebergSnapshotDeleteRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(monkeypatch)

    async def allow_request(_context) -> None:
        return None

    async def fail_blocking(_lane, _function, *_args, **kwargs):
        assert kwargs["request_namespace"] == "analytics"
        raise BackendWorkerRpcError(
            status_code=504,
            error="Datasource metadata lookup exceeded its deadline",
            error_code=grpc.StatusCode.DEADLINE_EXCEEDED.name,
        )

    monkeypatch.setattr(data_plane_server, "_require_internal_token", allow_request)
    monkeypatch.setattr(data_plane_server, "_run_blocking", fail_blocking)

    with pytest.raises(
        RuntimeError,
        match="DEADLINE_EXCEEDED: Datasource metadata lookup exceeded its deadline",
    ):
        await getattr(IcebergServicer(), method)(rpc_message, context)


@pytest.mark.asyncio
async def test_object_store_ensure_bucket_is_worker_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    ensured: list[str] = []
    monkeypatch.setattr("worker_grpc.data_plane_server.object_store.ensure_bucket_exists", ensured.append)

    response = await ObjectStoreServicer().EnsureBucket(object_store_pb2.ObjectStoreBucket(name="analytics"), context)

    assert response == common_pb2.EmptyRequest()
    assert ensured == ["analytics"]


@pytest.mark.asyncio
async def test_object_store_delete_rejects_external_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)

    with pytest.raises(RuntimeError, match="PERMISSION_DENIED: Prefix is outside the worker-managed storage prefix"):
        await ObjectStoreServicer().DeletePrefix(object_store_pb2.ObjectStoreUrl(url="s3://external-bucket/data/file.csv"), context)


@pytest.mark.asyncio
async def test_object_store_upload_requires_explicit_commit_and_streams_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    calls: list[object] = []

    class Upload:
        def __init__(self, target_url: str, *, content_type: str | None, max_bytes: int) -> None:
            calls.append(("start", target_url, content_type, max_bytes))

        def write(self, data: bytes) -> None:
            calls.append(("chunk", data))

        def commit(self) -> str:
            calls.append(("commit",))
            return "s3://analytics/uploads/data.csv"

        def abort(self) -> None:
            calls.append(("abort",))

    async def allow_request(_context) -> None:
        return None

    monkeypatch.setattr(data_plane_server, "_require_internal_token", allow_request)
    monkeypatch.setattr(data_plane_server.object_store, "MultipartObjectUpload", Upload)

    async def frames():
        yield object_store_pb2.ObjectStoreUploadRequest(
            start=object_store_pb2.ObjectStoreUploadStart(
                target=object_store_pb2.ObjectStoreUrl(url="s3://analytics/uploads/data.csv"),
                content_type="text/csv",
                max_bytes=64,
            )
        )
        yield object_store_pb2.ObjectStoreUploadRequest(chunk=object_store_pb2.ObjectStoreUploadChunk(data=b"data"))
        yield object_store_pb2.ObjectStoreUploadRequest(commit=object_store_pb2.ObjectStoreUploadCommit())

    response = await ObjectStoreServicer().UploadObject(frames(), context)

    assert response.url == "s3://analytics/uploads/data.csv"
    assert calls == [
        ("start", "s3://analytics/uploads/data.csv", "text/csv", 64),
        ("chunk", b"data"),
        ("commit",),
    ]


@pytest.mark.asyncio
async def test_object_store_upload_cancellation_aborts_only_open_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    calls: list[str] = []

    class Upload:
        def __init__(self, *_args, **_kwargs) -> None:
            calls.append("start")

        def write(self, _data: bytes) -> None:
            calls.append("chunk")

        def commit(self) -> str:
            raise AssertionError("cancelled upload must not commit")

        def abort(self) -> None:
            calls.append("abort")

    async def allow_request(_context) -> None:
        return None

    monkeypatch.setattr(data_plane_server, "_require_internal_token", allow_request)
    monkeypatch.setattr(data_plane_server.object_store, "MultipartObjectUpload", Upload)

    async def frames():
        yield object_store_pb2.ObjectStoreUploadRequest(
            start=object_store_pb2.ObjectStoreUploadStart(
                target=object_store_pb2.ObjectStoreUrl(url="s3://analytics/uploads/data.csv"),
                max_bytes=64,
            )
        )
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await ObjectStoreServicer().UploadObject(frames(), context)

    assert calls == ["start", "abort"]


@pytest.mark.asyncio
async def test_upload_abort_waits_for_cancelled_chunk_write_to_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    write_started = threading.Event()
    release_write = threading.Event()
    abort_started = threading.Event()
    calls: list[str] = []
    calls_lock = threading.Lock()
    executor = ThreadPoolExecutor(max_workers=2)
    lane = data_plane_server._BlockingLane(executor, max_in_flight=1)

    class Upload:
        def __init__(self, *_args, **_kwargs) -> None:
            calls.append("start")

        def write(self, _data: bytes) -> None:
            write_started.set()
            assert release_write.wait(timeout=5)
            with calls_lock:
                calls.append("write-settled")

        def commit(self) -> str:
            raise AssertionError("cancelled upload must not commit")

        def abort(self) -> None:
            abort_started.set()
            with calls_lock:
                calls.append("abort")

    async def allow_request(_context) -> None:
        return None

    monkeypatch.setattr(data_plane_server, "_require_internal_token", allow_request)
    monkeypatch.setattr(data_plane_server.object_store, "MultipartObjectUpload", Upload)
    monkeypatch.setattr(data_plane_server, "_OBJECT_STORE_LANE", lane)

    async def frames():
        yield object_store_pb2.ObjectStoreUploadRequest(
            start=object_store_pb2.ObjectStoreUploadStart(
                target=object_store_pb2.ObjectStoreUrl(url="s3://analytics/uploads/data.csv"),
                max_bytes=64,
            )
        )
        yield object_store_pb2.ObjectStoreUploadRequest(chunk=object_store_pb2.ObjectStoreUploadChunk(data=b"data"))
        await asyncio.Event().wait()

    call = asyncio.create_task(ObjectStoreServicer().UploadObject(frames(), context))
    try:
        assert await asyncio.to_thread(write_started.wait, 2)
        call.cancel()
        await asyncio.sleep(0.05)
        assert not call.done()
        assert not abort_started.is_set()
        release_write.set()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert abort_started.is_set()
        assert calls == ["start", "write-settled", "abort"]
    finally:
        release_write.set()
        await asyncio.gather(call, return_exceptions=True)
        await asyncio.to_thread(executor.shutdown, True)
