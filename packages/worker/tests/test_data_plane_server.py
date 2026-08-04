from __future__ import annotations

import grpc
import pytest

from dataforge_protocol import object_store_pb2
from runtime.config import settings
from worker_grpc.data_plane_server import ObjectStoreServicer


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
async def test_object_store_delete_rejects_external_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)

    with pytest.raises(RuntimeError, match="PERMISSION_DENIED: Prefix is outside the worker-managed storage prefix"):
        await ObjectStoreServicer().DeletePrefix(object_store_pb2.ObjectStoreUrl(url="s3://external-bucket/data/file.csv"), context)
