from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast

import grpc
from google.protobuf import json_format

from backend_core.config import settings
from dataforge_protocol import common_pb2, iceberg_pb2, iceberg_pb2_grpc, object_store_pb2, object_store_pb2_grpc

_TOKEN_METADATA_KEY = 'x-internal-token'
_MAX_DATA_PLANE_MESSAGE_BYTES = 128 * 1024 * 1024
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
    def __init__(self, *, target: str | None = None, token: str | None = None, timeout_seconds: float = 120.0) -> None:
        self._target = target or settings.worker_data_plane_grpc_target
        self._token = token if token is not None else settings.internal_api_token
        self._timeout_seconds = timeout_seconds
        self._channel = grpc.insecure_channel(
            self._target,
            options=(
                ('grpc.max_send_message_length', _MAX_DATA_PLANE_MESSAGE_BYTES),
                ('grpc.max_receive_message_length', _MAX_DATA_PLANE_MESSAGE_BYTES),
            ),
        )
        self._object_store = object_store_pb2_grpc.ObjectStoreServiceStub(self._channel)
        self._iceberg = iceberg_pb2_grpc.IcebergServiceStub(self._channel)

    def classify_object_url(self, value: str) -> ObjectStoreUrlClassification:
        response = self._call(
            lambda: self._object_store.ClassifyUrl(
                object_store_pb2.ObjectStoreUrlClassificationRequest(value=value),
                timeout=self._timeout_seconds,
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
        request = object_store_pb2.ObjectStoreBytes(target=object_store_pb2.ObjectStoreUrl(url=target_url), data=data)
        if content_type is not None:
            request.content_type = content_type
        return self._call(lambda: self._object_store.UploadBytes(request, timeout=self._timeout_seconds, metadata=self._metadata())).url

    def download_object_bytes(self, source_url: str) -> bytes:
        response = self._call(
            lambda: self._object_store.DownloadBytes(object_store_pb2.ObjectStoreUrl(url=source_url), timeout=self._timeout_seconds, metadata=self._metadata())
        )
        return bytes(response.data)

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
                timeout=self._timeout_seconds,
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
