from __future__ import annotations

import asyncio
import base64
import logging
import threading
from datetime import UTC, datetime
from typing import Any, cast

import grpc
import pyarrow as pa  # type: ignore[import-untyped]
from google.protobuf.timestamp_pb2 import Timestamp
from pyiceberg.table import StaticTable

from dataforge_protocol import common_pb2, iceberg_pb2, iceberg_pb2_grpc, object_store_pb2, object_store_pb2_grpc
from runtime import compute_service, iceberg_metadata, iceberg_snapshot_reader, object_store
from runtime.config import settings
from worker_grpc.codec import dict_to_struct, struct_to_dict
from worker_grpc.validation import ProtovalidateAioInterceptor

logger = logging.getLogger(__name__)
_TOKEN_METADATA_KEY = "x-internal-token"
_MAX_DATA_PLANE_MESSAGE_BYTES = 128 * 1024 * 1024


class ThreadedDataPlaneServer:
    def __init__(self, *, loop: asyncio.AbstractEventLoop, server: grpc.aio.Server, thread: threading.Thread) -> None:
        self._loop = loop
        self._server = server
        self._thread = thread

    async def stop(self, *, grace: float = 1.0) -> None:
        future = asyncio.run_coroutine_threadsafe(self._server.stop(grace=grace), self._loop)
        await asyncio.to_thread(future.result)
        self._loop.call_soon_threadsafe(self._loop.stop)
        await asyncio.to_thread(self._thread.join)


async def _require_internal_token(context: grpc.aio.ServicerContext) -> None:
    if not settings.internal_api_token:
        await context.abort(grpc.StatusCode.UNAVAILABLE, "INTERNAL_API_TOKEN must be configured before worker data-plane services can be used")
    invocation_metadata = cast(tuple[tuple[str, str], ...], context.invocation_metadata() or ())
    metadata = {key: value for key, value in invocation_metadata}
    if metadata.get(_TOKEN_METADATA_KEY) != settings.internal_api_token:
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid worker data-plane token")


class ObjectStoreServicer(object_store_pb2_grpc.ObjectStoreServiceServicer):
    async def BuildUrl(self, request: object_store_pb2.ObjectStorePathParts, context: grpc.aio.ServicerContext) -> object_store_pb2.ObjectStoreUrl:
        await _require_internal_token(context)
        return object_store_pb2.ObjectStoreUrl(url=object_store.object_store_url(*request.parts, bucket=request.bucket if request.HasField("bucket") else None))

    async def JoinUrl(self, request: object_store_pb2.ObjectStoreJoinRequest, context: grpc.aio.ServicerContext) -> object_store_pb2.ObjectStoreUrl:
        await _require_internal_token(context)
        return object_store_pb2.ObjectStoreUrl(url=object_store.join_object_store_url(request.base.url, *request.parts))

    async def StorageOptions(
        self,
        request: common_pb2.EmptyRequest,
        context: grpc.aio.ServicerContext,
    ) -> object_store_pb2.ObjectStoreStorageOptionsResponse:
        del request
        await _require_internal_token(context)
        return object_store_pb2.ObjectStoreStorageOptionsResponse(options=dict_to_struct(object_store.object_store_storage_options()))

    async def UploadBytes(self, request: object_store_pb2.ObjectStoreBytes, context: grpc.aio.ServicerContext) -> object_store_pb2.ObjectStoreUrl:
        await _require_internal_token(context)
        content_type = request.content_type if request.HasField("content_type") else None
        url = await asyncio.to_thread(object_store.upload_bytes, request.data, request.target.url, content_type=content_type)
        return object_store_pb2.ObjectStoreUrl(url=url)

    async def DownloadBytes(self, request: object_store_pb2.ObjectStoreUrl, context: grpc.aio.ServicerContext) -> object_store_pb2.ObjectStoreBytes:
        await _require_internal_token(context)
        data = await asyncio.to_thread(object_store.download_bytes, request.url)
        return object_store_pb2.ObjectStoreBytes(target=request, data=data)

    async def DeleteObject(self, request: object_store_pb2.ObjectStoreUrl, context: grpc.aio.ServicerContext) -> common_pb2.EmptyRequest:
        await _require_internal_token(context)
        await asyncio.to_thread(object_store.delete_object, request.url)
        return common_pb2.EmptyRequest()

    async def Exists(self, request: object_store_pb2.ObjectStoreUrl, context: grpc.aio.ServicerContext) -> object_store_pb2.ObjectStoreExistsResponse:
        await _require_internal_token(context)
        exists = await asyncio.to_thread(object_store.object_exists, request.url)
        return object_store_pb2.ObjectStoreExistsResponse(exists=exists)

    async def ListPrefixes(
        self,
        request: object_store_pb2.ObjectStoreUrl,
        context: grpc.aio.ServicerContext,
    ) -> object_store_pb2.ObjectStorePrefixesResponse:
        await _require_internal_token(context)
        prefixes = await asyncio.to_thread(object_store.list_prefixes, request.url)
        return object_store_pb2.ObjectStorePrefixesResponse(prefixes=prefixes)

    async def ListMetadataFiles(
        self,
        request: object_store_pb2.ObjectStoreUrl,
        context: grpc.aio.ServicerContext,
    ) -> object_store_pb2.ObjectStoreMetadataFilesResponse:
        await _require_internal_token(context)
        files = await asyncio.to_thread(object_store.list_metadata_files, request.url)
        return object_store_pb2.ObjectStoreMetadataFilesResponse(files=[object_store_pb2.ObjectStoreUrl(url=file) for file in files])

    async def DeletePrefix(self, request: object_store_pb2.ObjectStoreUrl, context: grpc.aio.ServicerContext) -> common_pb2.EmptyRequest:
        await _require_internal_token(context)
        await asyncio.to_thread(object_store.delete_prefix, request.url)
        return common_pb2.EmptyRequest()


class IcebergServicer(iceberg_pb2_grpc.IcebergServiceServicer):
    async def ResolveMetadataPath(
        self,
        request: iceberg_pb2.IcebergTableRef,
        context: grpc.aio.ServicerContext,
    ) -> iceberg_pb2.IcebergMetadataPathResponse:
        await _require_internal_token(context)
        if not request.HasField("metadata_path"):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "metadata_path is required")
        path = await asyncio.to_thread(
            iceberg_metadata.resolve_iceberg_metadata_path,
            request.metadata_path,
            namespace_name=request.namespace,
        )
        return iceberg_pb2.IcebergMetadataPathResponse(metadata_path=path)

    async def ResolveBranchMetadataPath(
        self,
        request: iceberg_pb2.IcebergTableRef,
        context: grpc.aio.ServicerContext,
    ) -> iceberg_pb2.IcebergMetadataPathResponse:
        await _require_internal_token(context)
        if not request.HasField("metadata_path"):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "metadata_path is required")
        branch = request.branch if request.HasField("branch") else None
        path = await asyncio.to_thread(
            iceberg_metadata.resolve_iceberg_branch_metadata_path,
            request.metadata_path,
            branch,
            namespace_name=request.namespace,
        )
        return iceberg_pb2.IcebergMetadataPathResponse(metadata_path=path)

    async def SyncSchema(self, request: iceberg_pb2.IcebergSchemaSyncRequest, context: grpc.aio.ServicerContext) -> common_pb2.EmptyRequest:
        await _require_internal_token(context)
        try:
            schema = _arrow_schema_from_payload(struct_to_dict(request.schema))
        except (TypeError, ValueError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        table = await asyncio.to_thread(
            StaticTable.from_metadata,
            request.metadata_path,
            properties=object_store.object_store_storage_options(),
        )
        await asyncio.to_thread(iceberg_metadata.sync_iceberg_schema, table, schema)
        return common_pb2.EmptyRequest()

    async def ListSnapshots(
        self,
        request: iceberg_pb2.IcebergTableRef,
        context: grpc.aio.ServicerContext,
    ) -> iceberg_pb2.IcebergSnapshotsResponse:
        await _require_internal_token(context)
        if not request.HasField("datasource_id"):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "datasource_id is required")
        branch = request.branch if request.HasField("branch") else None
        response = await asyncio.to_thread(compute_service.list_iceberg_snapshots, None, request.datasource_id, branch)
        return iceberg_pb2.IcebergSnapshotsResponse(
            datasource_id=response.datasource_id,
            table_path=response.table_path,
            snapshots=[
                iceberg_pb2.IcebergSnapshotInfo(
                    snapshot_id=item.snapshot_id,
                    timestamp=_timestamp_from_ms(item.timestamp_ms),
                    parent_snapshot_id=item.parent_snapshot_id,
                    operation=item.operation,
                    is_current=item.is_current,
                )
                for item in response.snapshots
            ],
        )

    async def ScanSnapshot(
        self,
        request: iceberg_pb2.IcebergSnapshotScanRequest,
        context: grpc.aio.ServicerContext,
    ) -> iceberg_pb2.IcebergSnapshotScanResponse:
        await _require_internal_token(context)
        try:
            snapshot_id = int(request.snapshot_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "snapshot_id must be an integer")
        limit = request.limit if request.HasField("limit") else None
        frame = await asyncio.to_thread(iceberg_snapshot_reader.scan_iceberg_snapshot, request.metadata_path, snapshot_id, None)
        rows = await asyncio.to_thread(lambda: frame.limit(limit).collect().to_dicts() if limit is not None else frame.collect().to_dicts())
        return iceberg_pb2.IcebergSnapshotScanResponse(rows=dict_to_struct({"rows": rows}))

    async def DeleteSnapshot(
        self,
        request: iceberg_pb2.IcebergSnapshotDeleteRequest,
        context: grpc.aio.ServicerContext,
    ) -> iceberg_pb2.IcebergSnapshotDeleteResponse:
        await _require_internal_token(context)
        response = await asyncio.to_thread(compute_service.delete_iceberg_snapshot, None, request.datasource_id, request.snapshot_id)
        return iceberg_pb2.IcebergSnapshotDeleteResponse(datasource_id=response.datasource_id, snapshot_id=response.snapshot_id)


def _timestamp_from_ms(timestamp_ms: int) -> Any:
    stamp = Timestamp()
    stamp.FromDatetime(datetime.fromtimestamp(timestamp_ms / 1000, UTC))
    return stamp


def _arrow_schema_from_payload(payload: dict[str, object]) -> pa.Schema:
    encoded = payload.get("arrow_schema_ipc_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("schema.arrow_schema_ipc_base64 is required")
    try:
        data = base64.b64decode(encoded, validate=True)
        schema = pa.ipc.read_schema(pa.BufferReader(data))
    except Exception as exc:
        raise ValueError("schema.arrow_schema_ipc_base64 must contain a serialized Arrow schema") from exc
    if not isinstance(schema, pa.Schema):
        raise TypeError("schema.arrow_schema_ipc_base64 did not decode to a pyarrow.Schema")
    return schema


async def start_data_plane_grpc_server() -> grpc.aio.Server:
    server = grpc.aio.server(
        interceptors=(ProtovalidateAioInterceptor(),),
        options=(
            ("grpc.max_send_message_length", _MAX_DATA_PLANE_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", _MAX_DATA_PLANE_MESSAGE_BYTES),
        ),
    )
    object_store_pb2_grpc.add_ObjectStoreServiceServicer_to_server(ObjectStoreServicer(), server)
    iceberg_pb2_grpc.add_IcebergServiceServicer_to_server(IcebergServicer(), server)
    server.add_insecure_port(f"{settings.data_plane_grpc_host}:{settings.data_plane_grpc_port}")
    await server.start()
    logger.info("Worker data-plane gRPC server listening on %s:%s", settings.data_plane_grpc_host, settings.data_plane_grpc_port)
    return server


def start_data_plane_grpc_server_in_thread() -> ThreadedDataPlaneServer:
    ready = threading.Event()
    holder: dict[str, object] = {}

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            server = loop.run_until_complete(start_data_plane_grpc_server())
        except Exception as exc:
            holder["error"] = exc
            ready.set()
            loop.close()
            return
        holder["loop"] = loop
        holder["server"] = server
        ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    thread = threading.Thread(target=_run, name="worker-data-plane-grpc", daemon=True)
    thread.start()
    if not ready.wait(timeout=30):
        raise RuntimeError("Timed out starting worker data-plane gRPC server")
    error = holder.get("error")
    if isinstance(error, Exception):
        raise error
    return ThreadedDataPlaneServer(
        loop=cast(asyncio.AbstractEventLoop, holder["loop"]),
        server=cast(grpc.aio.Server, holder["server"]),
        thread=thread,
    )
