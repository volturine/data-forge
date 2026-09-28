from __future__ import annotations

import asyncio
import threading
import time

import grpc
import pytest

from dataforge_protocol import common_pb2, iceberg_pb2, object_store_pb2
from runtime.config import settings
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
