from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar, cast

import grpc
from google.protobuf import json_format

from backend_core.config import settings
from dataforge_protocol import common_pb2, iceberg_pb2, iceberg_pb2_grpc, object_store_pb2, object_store_pb2_grpc

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


_T = TypeVar('_T')


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
        response = self._call(
            lambda: self._object_store.ClassifyUrl(
                object_store_pb2.ObjectStoreUrlClassificationRequest(value=value),
                timeout=self._trivial_timeout_seconds,
                metadata=self._metadata(),
            )
        )
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
        return self._call(lambda: self._object_store.BuildUrl(request, timeout=self._timeout_seconds, metadata=self._metadata())).url

    def join_object_url(self, base_url: str, *parts: str) -> str:
        request = object_store_pb2.ObjectStoreJoinRequest(base=object_store_pb2.ObjectStoreUrl(url=base_url), parts=parts)
        return self._call(lambda: self._object_store.JoinUrl(request, timeout=self._timeout_seconds, metadata=self._metadata())).url

    def read_object_store_storage_options(self) -> dict[str, object]:
        response = self._call(lambda: self._object_store.StorageOptions(common_pb2.EmptyRequest(), timeout=self._timeout_seconds, metadata=self._metadata()))
        return _object_store_storage_options_payload(response.storage_options)

    def ensure_object_store_bucket(self, name: str) -> None:
        self._call(
            lambda: self._object_store.EnsureBucket(
                object_store_pb2.ObjectStoreBucket(name=name),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def upload_object_bytes(self, data: bytes, target_url: str, *, content_type: str | None = None) -> str:
        if len(data) > _MAX_IN_MEMORY_OBJECT_BYTES:
            raise ValueError(f'in-memory object uploads are limited to {_MAX_IN_MEMORY_OBJECT_BYTES} bytes')
        chunks = (data[offset : offset + _OBJECT_TRANSFER_CHUNK_BYTES] for offset in range(0, len(data), _OBJECT_TRANSFER_CHUNK_BYTES))
        return self.upload_object_stream(chunks, target_url, content_type=content_type)

    def upload_object_file(
        self,
        path: Path,
        target_url: str,
        *,
        max_bytes: int,
        content_type: str | None = None,
    ) -> str:
        def chunks() -> Generator[bytes]:
            with path.open('rb') as source:
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
            return self._call(lambda: self._object_store.UploadObject(request_iterator, timeout=self._timeout_seconds, metadata=self._metadata())).url
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

    def download_object_file(self, source_url: str, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, partial_name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.partial', dir=path.parent)
        os.close(descriptor)
        partial_path = Path(partial_name)
        stream = self.download_object_stream(source_url)
        try:
            with partial_path.open('wb') as destination:
                for chunk in stream:
                    destination.write(chunk)
            os.replace(partial_path, path)
            return path
        finally:
            try:
                stream.close()
            finally:
                partial_path.unlink(missing_ok=True)

    def download_object_stream(self, source_url: str) -> Generator[bytes]:
        responses = self._call(
            lambda: self._object_store.DownloadObject(object_store_pb2.ObjectStoreUrl(url=source_url), timeout=self._timeout_seconds, metadata=self._metadata())
        )
        completed = False
        try:
            for response in responses:
                yield bytes(response.data)
            completed = True
        except grpc.RpcError as exc:
            code = exc.code()
            details = exc.details() or f'Worker data-plane call to {self._target} failed'
            raise WorkerDataPlaneError(target=self._target, code=code, details=details) from exc
        finally:
            if not completed:
                responses.cancel()

    def delete_object(self, source_url: str) -> None:
        self._call(
            lambda: self._object_store.DeleteObject(
                object_store_pb2.ObjectStoreUrl(url=source_url),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def object_exists(self, source_url: str) -> bool:
        response = self._call(
            lambda: self._object_store.Exists(
                object_store_pb2.ObjectStoreUrl(url=source_url),
                timeout=self._trivial_timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return bool(response.exists)

    def list_prefixes(self, prefix_url: str) -> list[str]:
        response = self._call(
            lambda: self._object_store.ListPrefixes(object_store_pb2.ObjectStoreUrl(url=prefix_url), timeout=self._timeout_seconds, metadata=self._metadata())
        )
        return list(response.prefixes)

    def list_metadata_files(self, base_url: str) -> list[str]:
        response = self._call(
            lambda: self._object_store.ListMetadataFiles(
                object_store_pb2.ObjectStoreUrl(url=base_url),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return [item.url for item in response.files]

    def delete_managed_prefix(self, prefix_url: str) -> None:
        self._call(
            lambda: self._object_store.DeletePrefix(
                object_store_pb2.ObjectStoreUrl(url=prefix_url),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def resolve_metadata_path(self, *, namespace: str, metadata_path: str, datasource_id: str | None = None) -> str:
        request = iceberg_pb2.IcebergTableRef(namespace=namespace, metadata_path=metadata_path)
        if datasource_id is not None:
            request.datasource_id = datasource_id
        response = self._call(
            lambda: self._iceberg.ResolveMetadataPath(
                request,
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return response.metadata_path

    def resolve_branch_metadata_path(
        self,
        *,
        namespace: str,
        metadata_path: str,
        datasource_id: str | None = None,
        branch: str | None = None,
    ) -> str:
        request = iceberg_pb2.IcebergTableRef(namespace=namespace, metadata_path=metadata_path)
        if datasource_id is not None:
            request.datasource_id = datasource_id
        if branch is not None:
            request.branch = branch
        response = self._call(lambda: self._iceberg.ResolveBranchMetadataPath(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return response.metadata_path

    def scan_snapshot(self, *, metadata_path: str, snapshot_id: str, limit: int | None = None) -> list[dict[str, object]]:
        request = iceberg_pb2.IcebergSnapshotScanRequest(metadata_path=metadata_path, snapshot_id=snapshot_id)
        if limit is not None:
            request.limit = limit
        response = self._call(lambda: self._iceberg.ScanSnapshot(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        rows = json_format.MessageToDict(response.rows, preserving_proto_field_name=True).get('rows')
        return cast(list[dict[str, object]], rows) if isinstance(rows, list) else []

    def sync_table_schema(self, *, metadata_path: str, schema_payload: dict[str, object]) -> None:
        request = iceberg_pb2.IcebergSchemaSyncRequest(metadata_path=metadata_path, arrow_schema=_arrow_schema_proto(schema_payload))
        self._call(lambda: self._iceberg.SyncSchema(request, timeout=self._timeout_seconds, metadata=self._metadata()))

    def list_snapshots(self, *, namespace: str, datasource_id: str, branch: str | None = None) -> IcebergSnapshots:
        request = iceberg_pb2.IcebergTableRef(namespace=namespace, datasource_id=datasource_id)
        if branch is not None:
            request.branch = branch
        response = self._call(lambda: self._iceberg.ListSnapshots(request, timeout=self._timeout_seconds, metadata=self._metadata()))
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
        response = self._call(
            lambda: self._iceberg.DeleteSnapshot(
                iceberg_pb2.IcebergSnapshotDeleteRequest(namespace=namespace, datasource_id=datasource_id, snapshot_id=snapshot_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return response.snapshot_id

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return ((_TOKEN_METADATA_KEY, self._token),)

    def close(self) -> None:
        """Release the client. The channel is process-shared and stays open."""

    def __enter__(self) -> WorkerDataPlaneClient:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def _call(self, fn: Callable[[], _T]) -> _T:
        try:
            return fn()
        except grpc.RpcError as exc:
            code = exc.code()
            details = exc.details() or f'Worker data-plane call to {self._target} failed'
            raise WorkerDataPlaneError(target=self._target, code=code, details=details) from exc


def client_from_settings() -> WorkerDataPlaneClient:
    return WorkerDataPlaneClient()


def _object_store_storage_options_payload(options: object_store_pb2.ObjectStoreStorageOptions) -> dict[str, object]:
    return {
        's3.endpoint': options.endpoint_url,
        's3.access-key-id': options.access_key_id,
        's3.secret-access-key': options.secret_access_key,
        's3.region': options.region,
        's3.force-virtual-addressing': options.force_virtual_addressing,
        'py-io-impl': options.py_io_impl,
    }


def _arrow_schema_proto(payload: dict[str, object]) -> iceberg_pb2.ArrowSchemaIpc:
    encoded = payload.get('arrow_schema_ipc_base64')
    if not isinstance(encoded, str) or not encoded:
        raise ValueError('schema.arrow_schema_ipc_base64 is required')
    import base64

    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError('schema.arrow_schema_ipc_base64 must contain base64-encoded Arrow schema IPC') from exc
    return iceberg_pb2.ArrowSchemaIpc(payload=data)
