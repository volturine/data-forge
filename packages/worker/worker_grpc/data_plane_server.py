from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

import grpc
import pyarrow as pa  # type: ignore[import-untyped]
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from protovalidate import ValidationError, Validator
from pyiceberg.table import StaticTable

from dataforge_protocol import common_pb2, iceberg_pb2, iceberg_pb2_grpc, object_store_pb2, object_store_pb2_grpc
from runtime import compute_service, iceberg_metadata, iceberg_snapshot_reader, object_store
from runtime.config import settings
from runtime.json_values import dict_to_struct

logger = logging.getLogger(__name__)
_TOKEN_METADATA_KEY = "x-internal-token"
_MAX_DATA_PLANE_MESSAGE_BYTES = 128 * 1024 * 1024


class _WorkerRequestValidationInterceptor(grpc.aio.ServerInterceptor):
    def __init__(self) -> None:
        self._validator = Validator()

    async def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler | None]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        handler = await continuation(handler_call_details)
        if handler is None or handler.unary_unary is None:
            return handler
        unary_unary = cast(Callable[[Message, grpc.aio.ServicerContext], Awaitable[Any]], handler.unary_unary)

        async def validate_request(request: Message, context: grpc.aio.ServicerContext) -> Any:
            try:
                self._validator.validate(request)
            except ValidationError as exc:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return await unary_unary(request, context)

        return grpc.unary_unary_rpc_method_handler(
            validate_request,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


def _object_store_storage_options_proto(payload: dict[str, object]) -> object_store_pb2.ObjectStoreStorageOptions:
    return object_store_pb2.ObjectStoreStorageOptions(
        endpoint_url=_required_str(payload, "s3.endpoint"),
        access_key_id=_required_str(payload, "s3.access-key-id"),
        secret_access_key=_required_str(payload, "s3.secret-access-key"),
        region=_required_str(payload, "s3.region"),
        force_virtual_addressing=_required_bool(payload, "s3.force-virtual-addressing"),
        py_io_impl=_required_str(payload, "py-io-impl"),
    )


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"object storage option {key} must be a non-empty string")
    return value


def _required_bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"object storage option {key} must be a boolean")
    return value


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
    async def ClassifyUrl(
        self,
        request: object_store_pb2.ObjectStoreUrlClassificationRequest,
        context: grpc.aio.ServicerContext,
    ) -> object_store_pb2.ObjectStoreUrlClassificationResponse:
        await _require_internal_token(context)
        is_object_store = object_store.is_object_store_url(request.value)
        response = object_store_pb2.ObjectStoreUrlClassificationResponse(
            is_object_store=is_object_store,
            is_managed=is_object_store and object_store.is_managed_object_store_url(request.value),
        )
        if is_object_store:
            response.object_url.url = request.value
        return response

    async def BuildUrl(self, request: object_store_pb2.ObjectStorePathParts, context: grpc.aio.ServicerContext) -> object_store_pb2.ObjectStoreUrl:
        await _require_internal_token(context)
        return object_store_pb2.ObjectStoreUrl(
            url=object_store.object_store_url(
                *request.parts,
                bucket=request.bucket if request.HasField("bucket") else None,
                namespace=request.namespace if request.HasField("namespace") else None,
            )
        )

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
        return object_store_pb2.ObjectStoreStorageOptionsResponse(
            storage_options=_object_store_storage_options_proto(object_store.object_store_storage_options())
        )

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
        if not object_store.is_managed_object_store_url(request.url):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Object is outside the worker-managed storage prefix")
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
        if not object_store.is_managed_object_store_url(request.url):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Prefix is outside the worker-managed storage prefix")
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
            schema = _arrow_schema_from_proto(request.arrow_schema)
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


def _arrow_schema_from_proto(payload: iceberg_pb2.ArrowSchemaIpc) -> pa.Schema:
    if not payload.payload:
        raise ValueError("arrow_schema.payload is required")
    try:
        schema = pa.ipc.read_schema(pa.BufferReader(bytes(payload.payload)))
    except Exception as exc:
        raise ValueError("arrow_schema.payload must contain a serialized Arrow schema") from exc
    if not isinstance(schema, pa.Schema):
        raise TypeError("arrow_schema.payload did not decode to a pyarrow.Schema")
    return schema


async def start_data_plane_grpc_server() -> grpc.aio.Server:
    server = grpc.aio.server(
        interceptors=(_WorkerRequestValidationInterceptor(),),
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
