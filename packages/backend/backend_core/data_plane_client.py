from __future__ import annotations

import threading
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import BinaryIO

import grpc

from backend_core.config import settings
from dataforge_protocol import iceberg_pb2, iceberg_pb2_grpc, object_store_pb2, object_store_pb2_grpc

_TOKEN_METADATA_KEY = 'x-internal-token'
_MAX_DATA_PLANE_MESSAGE_BYTES = 128 * 1024 * 1024
_MAX_OBJECT_TRANSFER_BYTES = 2 * 1024 * 1024 * 1024
_OBJECT_TRANSFER_CHUNK_BYTES = 8 * 1024 * 1024
# Keep bounded in-memory artifacts aligned with worker runtime.compute_service.MAX_DOWNLOAD_BYTES.
_MAX_IN_MEMORY_OBJECT_BYTES = 10 * 1024 * 1024

_channel_lock = threading.Lock()
_channels: dict[str, grpc.Channel] = {}


def _shared_channel(target: str) -> grpc.Channel:
    """One channel per target for the whole process.

    A client is constructed per request handler; gRPC channels are thread-safe
    and multiplex concurrent calls, so building one per client charged every
    request a DNS, TCP and HTTP/2 handshake.
    """
    with _channel_lock:
        channel = _channels.get(target)
        if channel is None:
            channel = grpc.insecure_channel(
                target,
                options=(
                    ('grpc.max_send_message_length', _MAX_DATA_PLANE_MESSAGE_BYTES),
                    ('grpc.max_receive_message_length', _MAX_DATA_PLANE_MESSAGE_BYTES),
                ),
            )
            _channels[target] = channel
        return channel


class WorkerDataPlaneError(RuntimeError):
    def __init__(self, *, target: str, code: grpc.StatusCode, details: str) -> None:
        super().__init__(f'Worker data-plane gRPC failed with {code.name}: {details}')
        self.target = target
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class IcebergSnapshotInfo:
    snapshot_id: str
    timestamp_ms: int
    parent_snapshot_id: str | None
    operation: str | None
    is_current: bool | None


@dataclass(frozen=True, slots=True)
class IcebergSnapshots:
    datasource_id: str
    table_path: str
    snapshots: list[IcebergSnapshotInfo]


@dataclass(frozen=True, slots=True)
class ObjectStoreUrlClassification:
    is_object_store: bool
    is_managed: bool
    object_url: str | None


class WorkerDataPlaneClient:
    def __init__(
        self,
        *,
        target: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 120.0,
        trivial_timeout_seconds: float = 15.0,
    ) -> None:
        self._target = target or settings.worker_data_plane_grpc_target
        self._token = token if token is not None else settings.internal_api_token
        self._timeout_seconds = timeout_seconds
        self._trivial_timeout_seconds = trivial_timeout_seconds
        self._channel = _shared_channel(self._target)
        self._object_store = object_store_pb2_grpc.ObjectStoreServiceStub(self._channel)
        self._iceberg = iceberg_pb2_grpc.IcebergServiceStub(self._channel)

    def classify_object_url(self, value: str) -> ObjectStoreUrlClassification:
        response = self._call(self._object_store.ClassifyUrl, object_store_pb2.ObjectStoreUrlClassificationRequest(value=value), trivial=True)
        return ObjectStoreUrlClassification(
            is_object_store=response.is_object_store,
            is_managed=response.is_managed,
            object_url=response.object_url.url if response.HasField('object_url') else None,
        )

    def build_object_url(self, *parts: str, bucket: str | None = None, namespace: str | None = None) -> str:
        request = object_store_pb2.ObjectStorePathParts(parts=parts)
        if bucket is not None:
            request.bucket = bucket
        if namespace is not None:
            request.namespace = namespace
        return self._call(self._object_store.BuildUrl, request).url

    def join_object_url(self, base_url: str, *parts: str) -> str:
        request = object_store_pb2.ObjectStoreJoinRequest(base=object_store_pb2.ObjectStoreUrl(url=base_url), parts=parts)
        return self._call(self._object_store.JoinUrl, request).url

    def ensure_object_store_bucket(self, name: str) -> None:
        self._call(self._object_store.EnsureBucket, object_store_pb2.ObjectStoreBucket(name=name))

    def upload_object_bytes(self, data: bytes, target_url: str, *, content_type: str | None = None) -> str:
        if len(data) > _MAX_IN_MEMORY_OBJECT_BYTES:
            raise ValueError(f'in-memory object uploads are limited to {_MAX_IN_MEMORY_OBJECT_BYTES} bytes')
        chunks = (data[offset : offset + _OBJECT_TRANSFER_CHUNK_BYTES] for offset in range(0, len(data), _OBJECT_TRANSFER_CHUNK_BYTES))
        return self.upload_object_stream(chunks, target_url, content_type=content_type)

    def upload_object_fileobj(
        self,
        source: BinaryIO,
        target_url: str,
        *,
        max_bytes: int,
        content_type: str | None = None,
    ) -> str:
        def chunks() -> Generator[bytes]:
            while chunk := source.read(_OBJECT_TRANSFER_CHUNK_BYTES):
                yield chunk

        stream = chunks()
        try:
            return self.upload_object_stream(stream, target_url, max_bytes=max_bytes, content_type=content_type)
        finally:
            stream.close()

    def upload_object_stream(
        self,
        chunks: Iterable[bytes],
        target_url: str,
        *,
        max_bytes: int = _MAX_OBJECT_TRANSFER_BYTES,
        content_type: str | None = None,
    ) -> str:
        bounded_limit = min(max_bytes or _MAX_OBJECT_TRANSFER_BYTES, _MAX_OBJECT_TRANSFER_BYTES)

        def requests() -> Generator[object_store_pb2.ObjectStoreUploadRequest]:
            start = object_store_pb2.ObjectStoreUploadStart(
                target=object_store_pb2.ObjectStoreUrl(url=target_url),
                max_bytes=bounded_limit,
            )
            if content_type is not None:
                start.content_type = content_type
            yield object_store_pb2.ObjectStoreUploadRequest(start=start)
            total = 0
            try:
                for chunk in chunks:
                    if not chunk:
                        continue
                    if len(chunk) > _OBJECT_TRANSFER_CHUNK_BYTES:
                        raise ValueError(f'object upload chunks must not exceed {_OBJECT_TRANSFER_CHUNK_BYTES} bytes')
                    total += len(chunk)
                    if total > bounded_limit:
                        raise ValueError(f'object upload exceeds {bounded_limit} byte limit')
                    yield object_store_pb2.ObjectStoreUploadRequest(chunk=object_store_pb2.ObjectStoreUploadChunk(data=chunk))
            except Exception:
                yield object_store_pb2.ObjectStoreUploadRequest(abort=object_store_pb2.ObjectStoreUploadAbort())
                raise
            yield object_store_pb2.ObjectStoreUploadRequest(commit=object_store_pb2.ObjectStoreUploadCommit())

        request_stream = requests()
        request_lock = threading.Lock()

        # gRPC consumes the request iterator on its own thread while the caller
        # may close it; serialize both so the generator is never re-entered.
        class RequestIterator:
            def __iter__(self) -> RequestIterator:
                return self

            def __next__(self) -> object_store_pb2.ObjectStoreUploadRequest:
                with request_lock:
                    return next(request_stream)

            def close(self) -> None:
                with request_lock:
                    request_stream.close()

        request_iterator = RequestIterator()
        try:
            return self._call(self._object_store.UploadObject, request_iterator).url
        finally:
            request_iterator.close()

    def download_object_bytes(self, source_url: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        stream = self.download_object_stream(source_url)
        try:
            for chunk in stream:
                total += len(chunk)
                if total > _MAX_IN_MEMORY_OBJECT_BYTES:
                    raise ValueError(f'in-memory object downloads are limited to {_MAX_IN_MEMORY_OBJECT_BYTES} bytes')
                chunks.append(chunk)
        finally:
            stream.close()
        return b''.join(chunks)

    def download_object_stream(self, source_url: str) -> Generator[bytes]:
        responses = self._call(self._object_store.DownloadObject, object_store_pb2.ObjectStoreUrl(url=source_url))
        completed = False
        try:
            for response in responses:
                yield bytes(response.data)
            completed = True
        except grpc.RpcError as exc:
            raise self._error(exc) from exc
        finally:
            if not completed:
                responses.cancel()

    def delete_object(self, source_url: str) -> None:
        self._call(self._object_store.DeleteObject, object_store_pb2.ObjectStoreUrl(url=source_url))

    def object_exists(self, source_url: str) -> bool:
        return bool(self._call(self._object_store.Exists, object_store_pb2.ObjectStoreUrl(url=source_url), trivial=True).exists)

    def list_prefixes(self, prefix_url: str) -> list[str]:
        return list(self._call(self._object_store.ListPrefixes, object_store_pb2.ObjectStoreUrl(url=prefix_url)).prefixes)

    def list_metadata_files(self, base_url: str) -> list[str]:
        response = self._call(self._object_store.ListMetadataFiles, object_store_pb2.ObjectStoreUrl(url=base_url))
        return [item.url for item in response.files]

    def list_snapshots(self, *, namespace: str, datasource_id: str, branch: str | None = None) -> IcebergSnapshots:
        request = iceberg_pb2.IcebergTableRef(namespace=namespace, datasource_id=datasource_id)
        if branch is not None:
            request.branch = branch
        response = self._call(self._iceberg.ListSnapshots, request)
        return IcebergSnapshots(
            datasource_id=response.datasource_id,
            table_path=response.table_path,
            snapshots=[
                IcebergSnapshotInfo(
                    snapshot_id=item.snapshot_id,
                    timestamp_ms=int(item.timestamp.ToMilliseconds()),
                    parent_snapshot_id=item.parent_snapshot_id if item.HasField('parent_snapshot_id') else None,
                    operation=item.operation if item.HasField('operation') else None,
                    is_current=item.is_current if item.HasField('is_current') else None,
                )
                for item in response.snapshots
            ],
        )

    def delete_snapshot(self, *, namespace: str, datasource_id: str, snapshot_id: str) -> str:
        request = iceberg_pb2.IcebergSnapshotDeleteRequest(namespace=namespace, datasource_id=datasource_id, snapshot_id=snapshot_id)
        return self._call(self._iceberg.DeleteSnapshot, request).snapshot_id

    def _call[Response](self, rpc: Callable[..., Response], request: object, *, trivial: bool = False) -> Response:
        timeout = self._trivial_timeout_seconds if trivial else self._timeout_seconds
        try:
            return rpc(request, timeout=timeout, metadata=((_TOKEN_METADATA_KEY, self._token),))
        except grpc.RpcError as exc:
            raise self._error(exc) from exc

    def _error(self, exc: grpc.RpcError) -> WorkerDataPlaneError:
        details = exc.details() or f'Worker data-plane call to {self._target} failed'
        return WorkerDataPlaneError(target=self._target, code=exc.code(), details=details)


def client_from_settings() -> WorkerDataPlaneClient:
    return WorkerDataPlaneClient()
