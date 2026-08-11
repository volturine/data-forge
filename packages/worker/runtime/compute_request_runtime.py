from __future__ import annotations

import asyncio
import contextlib
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, cast

from google.protobuf import json_format, message

from dataforge_protocol import compute_pb2, datasource_pb2, enums_pb2, errors_pb2
from datasources import execution as datasource_execution
from datasources.schemas import CSVOptions
from operations.step_converter import analysis_pipeline_to_execution_payload
from runtime import compute_service as service
from runtime.compute_manager import EngineCapacityFull, ProcessManager
from runtime.config import settings
from runtime.domain.compute import schemas as compute_schemas
from runtime.domain.compute_requests.live import request_hub
from runtime.domain.domain_enums import domain_token
from runtime.exceptions import AppError, status_for_app_error
from runtime.json_values import dict_to_struct
from runtime.namespace import reset_namespace, set_namespace_context
from runtime.object_store import object_store_url, upload_bytes
from runtime.worker_runtime_client import BackendWorkerRpcError, WorkerRuntimeClient, client_from_env

logger = logging.getLogger(__name__)

_COMPUTE_REQUEST_MAX_WORKERS = max(
    1,
    min(settings.compute_request_concurrency, max(settings.build_worker_max_processes, 6)),
)
_COMPUTE_REQUEST_EXECUTOR = ThreadPoolExecutor(
    max_workers=_COMPUTE_REQUEST_MAX_WORKERS,
    thread_name_prefix="compute-request",
)
_DATASOURCE_REQUEST_KINDS = {
    enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
    enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
    enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
    enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
    enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
    enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
    enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
}


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


def compute_request_worker_count() -> int:
    return _COMPUTE_REQUEST_MAX_WORKERS


def _compute_request_kind_name(kind: enums_pb2.ComputeRequestKind) -> str:
    enum_name = enums_pb2.ComputeRequestKind.Name(kind)
    return enum_name.removeprefix("COMPUTE_REQUEST_KIND_").lower()


@dataclass(frozen=True)
class ClaimedComputeRequest:
    id: str
    namespace: str
    kind: enums_pb2.ComputeRequestKind
    command_envelope: compute_pb2.ComputeCommandEnvelope
    worker_id: str
    claim_token: str
    lease_generation: int
    lease_ttl_seconds: int


class ComputeRequestLeaseLost(RuntimeError):
    pass


def next_compute_request(worker_id: str) -> ClaimedComputeRequest | None:
    claimed = worker_runtime_client().claim_compute_request(worker_id=worker_id)
    if claimed is None:
        return None
    return ClaimedComputeRequest(
        id=claimed.id,
        namespace=claimed.namespace,
        kind=claimed.kind,
        command_envelope=claimed.command_envelope,
        worker_id=claimed.worker_id,
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
        lease_ttl_seconds=claimed.lease_ttl_seconds,
    )


async def compute_request_loop(
    stop_event: asyncio.Event,
    *,
    worker_id: str,
    manager: ProcessManager,
) -> None:
    last_seen = request_hub.version()
    while not stop_event.is_set():
        try:
            handled = await _run_once(worker_id=worker_id, manager=manager)
            if handled:
                last_seen = request_hub.version()
                continue
        except Exception as exc:
            logger.warning("Compute request loop iteration failed; will retry: %s", exc)
            await asyncio.sleep(1.0)
            continue
        wait_task = asyncio.create_task(request_hub.wait(last_seen))
        stop_task = asyncio.create_task(stop_event.wait())
        poll_task = asyncio.create_task(asyncio.sleep(settings.runtime_reconciliation_poll_interval_seconds))
        done, pending = await asyncio.wait(
            {wait_task, stop_task, poll_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if stop_task in done:
            return
        with contextlib.suppress(asyncio.CancelledError):
            if wait_task in done:
                value = await wait_task
                if isinstance(value, int):
                    last_seen = value


async def _run_once(*, worker_id: str, manager: ProcessManager) -> bool:
    claimed = next_compute_request(worker_id)
    if claimed is None:
        return False
    try:
        await _execute_request(claimed, manager)
    except ComputeRequestLeaseLost:
        logger.warning("Compute request %s lease was lost; execution drained without publication", claimed.id)
    return True


async def _execute_request(claimed: ClaimedComputeRequest, manager: ProcessManager) -> None:
    """Run the request on the compute pool; park off-pool when engine capacity is full.

    EngineCapacityFull means every engine slot is busy. The executor thread is
    released immediately so the capacity "queue" never holds runners. Lease
    renewal continues while we wait for a free/idle slot.
    """
    loop = asyncio.get_running_loop()
    renewal_stop = asyncio.Event()
    renewal = asyncio.create_task(_renew_compute_lease(claimed, stop_event=renewal_stop))
    try:
        while True:
            execution = loop.run_in_executor(_COMPUTE_REQUEST_EXECUTOR, _execute_request_sync, claimed, manager)
            done, _pending = await asyncio.wait({execution, renewal}, return_when=asyncio.FIRST_COMPLETED)
            if renewal in done:
                try:
                    await renewal
                except ComputeRequestLeaseLost:
                    await asyncio.gather(execution, return_exceptions=True)
                    raise
                raise RuntimeError(f"Compute request {claimed.id} lease renewal stopped unexpectedly")
            try:
                await execution
                return
            except EngineCapacityFull:
                logger.info(
                    "Compute request %s parked for engine capacity (not holding a runner)",
                    claimed.id,
                )
                await manager.wait_for_capacity()
    finally:
        renewal_stop.set()
        await asyncio.gather(renewal, return_exceptions=True)


async def _renew_compute_lease(claimed: ClaimedComputeRequest, *, stop_event: asyncio.Event) -> None:
    clock = asyncio.get_running_loop().time
    deadline = clock() + claimed.lease_ttl_seconds
    delay = claimed.lease_ttl_seconds / 3
    client = worker_runtime_client()
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
            return
        except TimeoutError:
            pass
        remaining = deadline - clock()
        if remaining <= 0:
            raise ComputeRequestLeaseLost(f"Compute request {claimed.id} lease renewal was not confirmed before expiry")
        renewal_started = clock()
        try:
            lease_ttl_seconds = await asyncio.to_thread(
                client.renew_compute_request_lease,
                request_id=claimed.id,
                namespace=claimed.namespace,
                worker_id=claimed.worker_id,
                claim_token=claimed.claim_token,
                lease_generation=claimed.lease_generation,
                timeout_seconds=remaining,
            )
        except Exception as exc:
            remaining = deadline - clock()
            if remaining <= 0:
                raise ComputeRequestLeaseLost(f"Compute request {claimed.id} lease renewal was not confirmed before expiry") from exc
            delay = min(1.0, max(remaining / 3, 0.05))
            logger.warning("Compute request %s lease renewal failed; retrying before confirmed expiry: %s", claimed.id, exc)
            continue
        if lease_ttl_seconds is None:
            raise ComputeRequestLeaseLost(f"Compute request {claimed.id} lease is no longer active")
        deadline = renewal_started + lease_ttl_seconds
        delay = lease_ttl_seconds / 3


def _datasource_result_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> datasource_pb2.DatasourceResult:
    from google.protobuf import json_format

    from dataforge_protocol import datasource_pb2

    result = datasource_pb2.DatasourceResult()
    if "error" in payload:
        result.error.CopyFrom(json_format.ParseDict(payload, datasource_pb2.DatasourceErrorResult()))
        return result
    if kind in {
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
    }:
        proto_payload = dict(payload)
        schema_cache = proto_payload.pop("schema_cache", None)
        if isinstance(schema_cache, dict):
            proto_payload["schema_info"] = schema_cache
        if "source_type" in proto_payload:
            from runtime.protocol_mapping import enum_to_proto_value

            proto_payload["source_type"] = enum_to_proto_value("DATA_SOURCE_TYPE", str(proto_payload["source_type"]))
        if "created_by" in proto_payload:
            from runtime.protocol_mapping import enum_to_proto_value

            proto_payload["created_by"] = enum_to_proto_value("DATA_SOURCE_CREATED_BY", str(proto_payload["created_by"]))
        result.datasource.CopyFrom(json_format.ParseDict(proto_payload, datasource_pb2.DataSourceRecord()))
        return result
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
        result.schema.CopyFrom(json_format.ParseDict(payload, datasource_pb2.SchemaInfo()))
        return result
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS:
        result.column_stats.CopyFrom(json_format.ParseDict(payload, datasource_pb2.ColumnStatsResult()))
        return result
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS:
        proto_payload = dict(payload)
        raw_schema_diff = proto_payload.get("schema_diff")
        if isinstance(raw_schema_diff, list):
            converted = []
            for raw_diff in raw_schema_diff:
                if not isinstance(raw_diff, dict):
                    converted.append(raw_diff)
                    continue
                diff = dict(raw_diff)
                status = diff.get("status")
                if isinstance(status, str):
                    from runtime.protocol_mapping import enum_to_proto_value

                    diff["status"] = enum_to_proto_value("SCHEMA_DIFF_STATUS", status)
                converted.append(diff)
            proto_payload["schema_diff"] = converted
        result.snapshot_compare.CopyFrom(json_format.ParseDict(proto_payload, datasource_pb2.SnapshotCompareResult()))
        return result
    raise ValueError(f"Unsupported datasource response kind: {_compute_request_kind_name(kind)}")


def _execute_datasource_command(client: WorkerRuntimeClient, claimed: ClaimedComputeRequest, command) -> datasource_pb2.DatasourceResult:
    from runtime.protocol_mapping import proto_value_to_enum_name, struct_to_dict

    kind = claimed.kind
    namespace = claimed.namespace
    database_url = settings.database_url
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE:
        if command.WhichOneof("command") != "create_file":
            raise ValueError("datasource command must contain create_file")
        create_file = command.create_file
        csv_options = None
        if create_file.HasField("csv_options"):
            csv_options = CSVOptions(
                delimiter=create_file.csv_options.delimiter,
                quote_char=create_file.csv_options.quote_char,
                has_header=create_file.csv_options.has_header,
                skip_rows=create_file.csv_options.skip_rows,
                encoding=create_file.csv_options.encoding,
            )
        record = datasource_execution.create_file_datasource(
            client,
            namespace=namespace,
            database_url=database_url,
            name=create_file.name,
            description=create_file.description if create_file.HasField("description") else None,
            file_path=create_file.file_path,
            file_type=proto_value_to_enum_name(enums_pb2.DataSourceFileType, "DATA_SOURCE_FILE_TYPE", create_file.file_type),
            options=struct_to_dict(create_file.options),
            csv_options=csv_options,
            sheet_name=create_file.sheet_name if create_file.HasField("sheet_name") else None,
            start_row=create_file.start_row if create_file.HasField("start_row") else None,
            start_col=create_file.start_col if create_file.HasField("start_col") else None,
            end_col=create_file.end_col if create_file.HasField("end_col") else None,
            end_row=create_file.end_row if create_file.HasField("end_row") else None,
            has_header=create_file.has_header if create_file.HasField("has_header") else None,
            table_name=create_file.table_name if create_file.HasField("table_name") else None,
            named_range=create_file.named_range if create_file.HasField("named_range") else None,
            cell_range=create_file.cell_range if create_file.HasField("cell_range") else None,
            owner_id=create_file.owner_id if create_file.HasField("owner_id") else None,
        )
        return _datasource_result_from_payload(kind, record.model_dump(mode="json"))
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE:
        if command.WhichOneof("command") != "create_database":
            raise ValueError("datasource command must contain create_database")
        create_database = command.create_database
        record = datasource_execution.create_database_datasource(
            client,
            namespace=namespace,
            database_url=database_url,
            name=create_database.name,
            description=create_database.description if create_database.HasField("description") else None,
            connection_string=create_database.connection_string,
            query=create_database.query,
            branch=create_database.branch,
            owner_id=create_database.owner_id if create_database.HasField("owner_id") else None,
        )
        return _datasource_result_from_payload(kind, record.model_dump(mode="json"))
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE:
        if command.WhichOneof("command") != "create_iceberg":
            raise ValueError("datasource command must contain create_iceberg")
        create_iceberg = command.create_iceberg
        record = datasource_execution.create_iceberg_datasource(
            client,
            namespace=namespace,
            database_url=database_url,
            name=create_iceberg.name,
            description=create_iceberg.description if create_iceberg.HasField("description") else None,
            source=struct_to_dict(create_iceberg.source),
            branch=create_iceberg.branch,
            owner_id=create_iceberg.owner_id if create_iceberg.HasField("owner_id") else None,
        )
        return _datasource_result_from_payload(kind, record.model_dump(mode="json"))
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE:
        if command.WhichOneof("command") != "ingest":
            raise ValueError("datasource command must contain ingest")
        record = datasource_execution.ingest_external_datasource(
            client,
            namespace=namespace,
            database_url=database_url,
            datasource_id=command.ingest.datasource_id,
            staging_key=claimed.claim_token,
            worker_id=claimed.worker_id,
            claim_token=claimed.claim_token,
            lease_generation=claimed.lease_generation,
            compute_request_id=claimed.id,
        )
        return _datasource_result_from_payload(kind, record.model_dump(mode="json"))
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
        if command.WhichOneof("command") != "schema":
            raise ValueError("datasource command must contain schema")
        from runtime.protocol_mapping import schema_info_payload

        schema = command.schema
        schema_result = datasource_execution.get_datasource_schema(
            client,
            namespace=namespace,
            datasource_id=schema.datasource_id,
            sheet_name=schema.sheet_name if schema.HasField("sheet_name") else None,
            refresh=schema.refresh,
        )
        return _datasource_result_from_payload(kind, schema_info_payload(schema_result))
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS:
        if command.WhichOneof("command") != "column_stats":
            raise ValueError("datasource command must contain column_stats")
        column_stats = command.column_stats
        stats_result = datasource_execution.get_column_stats(
            client,
            namespace=namespace,
            datasource_id=column_stats.datasource_id,
            column_name=column_stats.column_name,
            use_sample=column_stats.use_sample,
            sample_size=column_stats.sample_size,
            datasource_config=(struct_to_dict(column_stats.datasource_config) or None),
        )
        return _datasource_result_from_payload(kind, cast(dict[str, object], stats_result.model_dump(mode="json")))
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS:
        if command.WhichOneof("command") != "compare_iceberg_snapshots":
            raise ValueError("datasource command must contain compare_iceberg_snapshots")
        compare_snapshots = command.compare_iceberg_snapshots
        compare_result = datasource_execution.compare_iceberg_snapshots(
            client,
            namespace=namespace,
            datasource_id=compare_snapshots.datasource_id,
            snapshot_a=compare_snapshots.snapshot_a,
            snapshot_b=compare_snapshots.snapshot_b,
            row_limit=compare_snapshots.row_limit,
        )
        return _datasource_result_from_payload(kind, cast(dict[str, object], compare_result.model_dump(mode="json")))
    raise ValueError(f"Unsupported datasource request kind: {_compute_request_kind_name(kind)}")


def _execute_request_sync(claimed: ClaimedComputeRequest, manager: ProcessManager) -> None:
    client = worker_runtime_client()
    token = set_namespace_context(claimed.namespace)
    try:
        if claimed.kind in _DATASOURCE_REQUEST_KINDS:
            if claimed.command_envelope.command.WhichOneof("command") != "datasource":
                raise ValueError("compute command envelope must contain datasource")
            datasource_command = claimed.command_envelope.command.datasource
            try:
                result = _execute_datasource_command(client, claimed, datasource_command)
            except datasource_execution.DatasourceNotFound as exc:
                payload: dict[str, object] = {"error": "datasource_not_found", "message": str(exc)}
                result = _datasource_result_from_payload(claimed.kind, payload)
            except datasource_execution.DatasourcePublicationClaimLost as exc:
                raise ComputeRequestLeaseLost(str(exc) or "Datasource publication claim is no longer active") from exc
            _complete_request(client, claimed, response=compute_pb2.ComputeResponse(datasource=result))
            return

        if claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW:
            preview_request = cast(compute_pb2.StepPreviewCommand, _compute_command_from_claimed(claimed, "preview"))
            analysis_pipeline = analysis_pipeline_to_execution_payload(preview_request.analysis_pipeline)
            request_json = _step_preview_request_json(preview_request)
            preview_response = service.preview_step(
                session=None,
                manager=manager,
                target_step_id=preview_request.target_step_id,
                analysis_pipeline=analysis_pipeline,
                row_limit=preview_request.row_limit,
                page=preview_request.page,
                analysis_id=preview_request.analysis_id if preview_request.HasField("analysis_id") else None,
                engine_identity=preview_request.engine_identity if preview_request.HasField("engine_identity") else None,
                resource_config=_resource_config_from_preview_command(preview_request),
                tab_id=preview_request.tab_id if preview_request.HasField("tab_id") else None,
                request_json=request_json,
            )
            _complete_request(client, claimed, response=_preview_result(preview_response))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA:
            schema_request = cast(compute_pb2.StepSchemaCommand, _compute_command_from_claimed(claimed, "schema"))
            if not schema_request.HasField("analysis_id"):
                raise ValueError("analysis_id is required")
            schema_response = service.get_step_schema(
                session=None,
                manager=manager,
                target_step_id=schema_request.target_step_id,
                analysis_id=schema_request.analysis_id,
                analysis_pipeline=analysis_pipeline_to_execution_payload(schema_request.analysis_pipeline),
                tab_id=schema_request.tab_id if schema_request.HasField("tab_id") else None,
            )
            _complete_request(client, claimed, response=_schema_result(schema_response))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT:
            row_count_request = cast(compute_pb2.StepRowCountCommand, _compute_command_from_claimed(claimed, "row_count"))
            if not row_count_request.HasField("analysis_id"):
                raise ValueError("analysis_id is required")
            request_json = _step_request_json(row_count_request)
            row_count_response = service.get_step_row_count(
                session=None,
                manager=manager,
                target_step_id=row_count_request.target_step_id,
                analysis_id=row_count_request.analysis_id,
                analysis_pipeline=analysis_pipeline_to_execution_payload(row_count_request.analysis_pipeline),
                tab_id=row_count_request.tab_id if row_count_request.HasField("tab_id") else None,
                request_json=request_json,
            )
            _complete_request(client, claimed, response=_row_count_result(row_count_response))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD:
            download_request = cast(compute_pb2.DownloadCommand, _compute_command_from_claimed(claimed, "download"))
            file_bytes, filename, content_type = service.download_step(
                session=None,
                manager=manager,
                target_step_id=download_request.target_step_id,
                analysis_pipeline=analysis_pipeline_to_execution_payload(download_request.analysis_pipeline),
                export_format=domain_token("ExportFormat", download_request.format),
                filename=download_request.filename,
                analysis_id=download_request.analysis_id if download_request.HasField("analysis_id") else None,
                tab_id=download_request.tab_id if download_request.HasField("tab_id") else None,
            )
            artifact_path = _write_artifact(claimed.id, filename, file_bytes)
            _complete_request(
                client,
                claimed,
                response=compute_pb2.ComputeResponse(ack=compute_pb2.ComputeAckResult(success=True)),
                artifact_path=artifact_path,
                artifact_name=filename,
                artifact_content_type=content_type,
            )
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_EXPORT:
            export_request = cast(compute_pb2.ExportCommand, _compute_command_from_claimed(claimed, "export"))
            request_json = _export_request_json(export_request)
            export_operation_result = service.export_data(
                session=None,
                manager=manager,
                target_step_id=export_request.target_step_id,
                analysis_pipeline=analysis_pipeline_to_execution_payload(export_request.analysis_pipeline),
                filename=export_request.filename,
                iceberg_options=_message_to_service_payload(export_request.iceberg_options) if export_request.HasField("iceberg_options") else None,
                analysis_id=export_request.analysis_id if export_request.HasField("analysis_id") else None,
                tab_id=export_request.tab_id if export_request.HasField("tab_id") else None,
                request_json=request_json,
                result_id=export_request.result_id if export_request.HasField("result_id") else None,
            )
            export_result = compute_pb2.ExportResult(
                success=True,
                filename=export_operation_result.datasource_name,
                format=export_request.format,
                destination=export_request.destination,
                message=f"Created datasource {export_operation_result.datasource_name}",
                datasource_id=export_operation_result.datasource_id,
            )
            datasource_name = export_operation_result.result_meta.get("datasource_name") if isinstance(export_operation_result.result_meta, dict) else None
            if isinstance(datasource_name, str):
                export_result.datasource_name = datasource_name
            _complete_request(client, claimed, response=compute_pb2.ComputeResponse(export=export_result))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE:
            command = _lifecycle_command_from_claimed(claimed, "spawn_engine")
            identity = command.engine_identity
            resource_config = _resource_config_from_lifecycle_command(command)
            manager.spawn_engine(
                identity,
                resource_config=resource_config,
            )
            response = compute_schemas.EngineStatusSchema.model_validate(manager.get_engine_status(identity))
            _complete_request(client, claimed, response=_engine_status_result(response))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE:
            command = _lifecycle_command_from_claimed(claimed, "configure_engine")
            identity = command.engine_identity
            resource_config = _resource_config_from_lifecycle_command(command)
            if resource_config is None:
                raise ValueError("resource_config is required")
            manager.restart_engine_with_config(identity, resource_config)
            response = compute_schemas.EngineStatusSchema.model_validate(manager.get_engine_status(identity))
            _complete_request(client, claimed, response=_engine_status_result(response))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE:
            command = _lifecycle_command_from_claimed(claimed, "shutdown_engine")
            identity = command.engine_identity
            # Shutdown is idempotent: capacity eviction, idle reaping, or a prior
            # crash may already have removed the container. Missing engines are a
            # successful terminal state, matching reconciliation rules.
            manager.shutdown_engine(identity)
            _complete_request(client, claimed, response=compute_pb2.ComputeResponse(ack=compute_pb2.ComputeAckResult(success=True)))
        else:
            raise ValueError(f"Unsupported compute request kind: {_compute_request_kind_name(claimed.kind)}")
    except ComputeRequestLeaseLost:
        # Stale claim / replaced publication fence: drain without failing the request as an infrastructure error.
        raise
    except EngineCapacityFull:
        # Propagate so the async runner can park without holding a pool thread.
        raise
    except Exception as exc:
        error = _error_result(exc)
        status_code = error.status_code if error.HasField("status_code") else None
        try:
            client.fail_compute_request(
                namespace=claimed.namespace,
                request_id=claimed.id,
                kind=claimed.kind,
                worker_id=claimed.worker_id,
                claim_token=claimed.claim_token,
                lease_generation=claimed.lease_generation,
                error_message=_error_message(exc),
                error=error,
            )
        except BackendWorkerRpcError as publish_exc:
            if publish_exc.status_code == 412:
                logger.info("Compute request %s ended after its lease was retired", claimed.id)
                return
            raise
        if status_code is not None and status_code >= 500:
            logger.error("Compute request %s failed: %s", claimed.id, exc, exc_info=True)
        elif status_code is not None and status_code >= 400:
            logger.info("Compute request %s rejected: %s", claimed.id, exc)
        else:
            logger.warning("Compute request %s failed: %s", claimed.id, exc)
    finally:
        try:
            client.dispatch_runtime_outbox()
        except Exception as exc:
            logger.warning("Compute response outbox fast-path dispatch failed for request %s: %s", claimed.id, exc)
        reset_namespace(token)


def _lifecycle_command_from_claimed(claimed: ClaimedComputeRequest, field_name: str) -> compute_pb2.EngineLifecycleCommand:
    command = claimed.command_envelope.command
    if command.WhichOneof("command") != field_name:
        raise ValueError(f"compute command envelope must contain {field_name}")
    return getattr(command, field_name)


def _compute_command_from_claimed(claimed: ClaimedComputeRequest, field_name: str) -> message.Message:
    command = claimed.command_envelope.command
    if command.WhichOneof("command") != field_name:
        raise ValueError(f"compute command envelope must contain {field_name}")
    return cast(message.Message, getattr(command, field_name))


def _message_to_service_payload(value: message.Message) -> dict[str, object]:
    decoded = json_format.MessageToDict(
        value,
        preserving_proto_field_name=True,
        use_integers_for_enums=True,
    )
    if not isinstance(decoded, dict):
        raise ValueError(f"{value.DESCRIPTOR.full_name} must decode to an object")
    return cast(dict[str, object], decoded)


def _step_request_json(command: message.Message) -> dict[str, object]:
    request_json = _message_to_service_payload(command)
    pipeline = request_json.get("analysis_pipeline")
    if isinstance(pipeline, dict):
        request_json["analysis_pipeline"] = analysis_pipeline_to_execution_payload(cast(Any, command).analysis_pipeline)
    return request_json


def _step_preview_request_json(command: compute_pb2.StepPreviewCommand) -> dict[str, object]:
    return _step_request_json(command)


def _export_request_json(command: compute_pb2.ExportCommand) -> dict[str, object]:
    return _step_request_json(command)


def _resource_config_from_preview_command(command: compute_pb2.StepPreviewCommand) -> dict[str, object] | None:
    if not command.HasField("resource_config"):
        return None
    config = command.resource_config
    result: dict[str, object] = {}
    if config.HasField("max_threads"):
        result["max_threads"] = config.max_threads
    if config.HasField("max_memory_mb"):
        result["max_memory_mb"] = config.max_memory_mb
    if config.HasField("streaming_chunk_size"):
        result["streaming_chunk_size"] = config.streaming_chunk_size
    return result


def _resource_config_from_lifecycle_command(command: compute_pb2.EngineLifecycleCommand) -> dict[str, object] | None:
    if not command.HasField("resource_config"):
        return None
    config = command.resource_config
    result: dict[str, object] = {}
    if config.HasField("max_threads"):
        result["max_threads"] = config.max_threads
    if config.HasField("max_memory_mb"):
        result["max_memory_mb"] = config.max_memory_mb
    if config.HasField("streaming_chunk_size"):
        result["streaming_chunk_size"] = config.streaming_chunk_size
    return result


def _write_artifact(request_id: str, filename: str, content: bytes) -> str:
    artifact_url = object_store_url("runtime-artifacts", request_id, filename)
    upload_bytes(content, artifact_url)
    return artifact_url


def _preview_result(value: compute_schemas.StepPreviewResponse) -> compute_pb2.ComputeResponse:
    result = compute_pb2.StepPreviewResult(
        step_id=value.step_id,
        columns=value.columns,
        column_types=value.column_types or {},
        rows=[dict_to_struct(row) for row in value.data],
        total_rows=value.total_rows,
        page=value.page,
        page_size=value.page_size,
    )
    if value.metadata is not None:
        result.metadata.CopyFrom(dict_to_struct(value.metadata))
    return compute_pb2.ComputeResponse(preview=result)


def _schema_result(value: compute_schemas.StepSchemaResponse) -> compute_pb2.ComputeResponse:
    return compute_pb2.ComputeResponse(schema=compute_pb2.StepSchemaResult(step_id=value.step_id, columns=value.columns, column_types=value.column_types))


def _row_count_result(value: compute_schemas.StepRowCountResponse) -> compute_pb2.ComputeResponse:
    return compute_pb2.ComputeResponse(row_count=compute_pb2.StepRowCountResult(step_id=value.step_id, row_count=value.row_count))


def _resource_config_proto(value: compute_schemas.EngineResourceConfig | None) -> compute_pb2.EngineResourceConfig | None:
    if value is None:
        return None
    result = compute_pb2.EngineResourceConfig()
    if value.max_threads is not None:
        result.max_threads = value.max_threads
    if value.max_memory_mb is not None:
        result.max_memory_mb = value.max_memory_mb
    if value.streaming_chunk_size is not None:
        result.streaming_chunk_size = value.streaming_chunk_size
    return result


def _engine_status_result(value: compute_schemas.EngineStatusSchema) -> compute_pb2.ComputeResponse:
    result = compute_pb2.EngineStatusResult(
        analysis_id=value.analysis_id,
        resource_id=value.resource_id,
        status=cast(enums_pb2.EngineStatus, value.status.number),
    )
    optional_scalars = {
        "process_id": value.process_id,
        "last_activity": value.last_activity,
        "current_job_id": value.current_job_id,
        "datasource_id": value.datasource_id,
        "build_id": value.build_id,
        "current_build_id": value.current_build_id,
        "current_engine_run_id": value.current_engine_run_id,
    }
    for field_name, field_value in optional_scalars.items():
        if field_value is not None:
            setattr(result, field_name, field_value)
    if value.scope is not None:
        result.scope = cast(enums_pb2.EngineScope, value.scope.number)
    if value.reuse_policy is not None:
        result.reuse_policy = cast(enums_pb2.EngineReusePolicy, value.reuse_policy.number)
    for field_name, config in (("resource_config", value.resource_config), ("effective_resources", value.effective_resources)):
        proto_config = _resource_config_proto(config)
        if proto_config is not None:
            getattr(result, field_name).CopyFrom(proto_config)
    if value.defaults is not None:
        result.defaults.CopyFrom(
            compute_pb2.EngineDefaults(
                max_threads=value.defaults.max_threads,
                max_memory_mb=value.defaults.max_memory_mb,
                streaming_chunk_size=value.defaults.streaming_chunk_size,
            )
        )
    return compute_pb2.ComputeResponse(engine_status=result)


def _complete_request(
    client: WorkerRuntimeClient,
    claimed: ClaimedComputeRequest,
    *,
    response: compute_pb2.ComputeResponse,
    artifact_path: str | None = None,
    artifact_name: str | None = None,
    artifact_content_type: str | None = None,
) -> None:
    client.complete_compute_request(
        namespace=claimed.namespace,
        request_id=claimed.id,
        kind=claimed.kind,
        worker_id=claimed.worker_id,
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
        response=response,
        artifact_path=artifact_path,
        artifact_name=artifact_name,
        artifact_content_type=artifact_content_type,
    )


def _error_message(exc: Exception) -> str:
    if isinstance(exc, BackendWorkerRpcError):
        return exc.error
    if isinstance(exc, AppError):
        return exc.message
    return str(exc)


def _error_result(exc: Exception) -> compute_pb2.ComputeErrorResult:
    if isinstance(exc, BackendWorkerRpcError):
        result = compute_pb2.ComputeErrorResult(error=exc.error, status_code=exc.status_code)
        protocol_error_code = f"ERROR_CODE_{exc.error_code}" if exc.error_code is not None else None
        if protocol_error_code in errors_pb2.ErrorCode.keys():
            result.error_code = cast(errors_pb2.ErrorCode, errors_pb2.ErrorCode.Value(protocol_error_code))
        if exc.details:
            result.details.CopyFrom(dict_to_struct(exc.details))
        return result
    if isinstance(exc, AppError):
        result = compute_pb2.ComputeErrorResult(
            error=exc.message,
            status_code=status_for_app_error(exc),
            error_code=cast(errors_pb2.ErrorCode, exc.error_code_value),
        )
        if exc.details:
            result.details.CopyFrom(dict_to_struct(exc.details))
        return result
    if isinstance(exc, ValueError):
        return compute_pb2.ComputeErrorResult(error=str(exc), status_code=400)
    return compute_pb2.ComputeErrorResult(error="An internal error occurred", status_code=500)
