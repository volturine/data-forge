from __future__ import annotations

import asyncio
import threading
from typing import cast

import grpc
import pytest

from dataforge_protocol import object_store_pb2
from worker_grpc import data_plane_server
from worker_grpc.data_plane_server import ObjectStoreServicer


@pytest.mark.asyncio
async def test_cancel_during_multipart_commit_waits_and_keeps_completed_object(monkeypatch: pytest.MonkeyPatch) -> None:
    commit_started = threading.Event()
    finish_commit = threading.Event()
    calls: list[str] = []

    class Upload:
        def __init__(self, *_args, **_kwargs) -> None:
            self.completed = False

        def commit(self) -> str:
            commit_started.set()
            assert finish_commit.wait(timeout=5)
            self.completed = True
            calls.append("commit")
            return "s3://analytics/uploads/artifact.bin"

        def abort(self) -> None:
            if not self.completed:
                calls.append("abort")

    async def allow_request(_context) -> None:
        return None

    monkeypatch.setattr(data_plane_server, "_require_internal_token", allow_request)
    monkeypatch.setattr(data_plane_server.object_store, "MultipartObjectUpload", Upload)

    async def frames():
        yield object_store_pb2.ObjectStoreUploadRequest(
            start=object_store_pb2.ObjectStoreUploadStart(
                target=object_store_pb2.ObjectStoreUrl(url="s3://analytics/uploads/artifact.bin"),
                max_bytes=1024,
            )
        )
        yield object_store_pb2.ObjectStoreUploadRequest(commit=object_store_pb2.ObjectStoreUploadCommit())

    context = cast(grpc.aio.ServicerContext, object())
    request = asyncio.create_task(ObjectStoreServicer().UploadObject(frames(), context))
    try:
        assert await asyncio.to_thread(commit_started.wait, 2)
        request.cancel()
        finish_commit.set()
        with pytest.raises(asyncio.CancelledError):
            await request
    finally:
        finish_commit.set()
        await asyncio.gather(request, return_exceptions=True)

    assert calls == ["commit"]
