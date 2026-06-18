from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from dataforge_protocol import compute_pb2, enums_pb2
from runtime import compute_service as service
from runtime.compute_manager import ProcessManager, engine_identity_resource_id
from runtime.config import settings
from runtime.domain.compute import schemas as compute_schemas
from runtime.domain.compute_requests.live import request_hub
from runtime.exceptions import AppError, EngineBusyError, engine_not_found, status_for_app_error
from runtime.internal_api import BackendWorkerRpcError, WorkerInternalApiClient, client_from_env
from runtime.namespace import reset_namespace, set_namespace_context
from runtime.object_store import object_store_url, upload_bytes

logger = logging.getLogger(__name__)

_ENGINE_SHUTDOWN_WAIT_SECONDS = 15.0
_ENGINE_SHUTDOWN_POLL_SECONDS = 0.1

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


def _required_identity_id(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _required_payload_identity_id(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"engine identity {field_name} is required")
    return _required_identity_id(value, field_name)


def _engine_identity_from_payload(payload: dict[str, object]) -> compute_pb2.EngineIdentity:
    scope = payload.get("scope")
    if scope == "analysis_interactive":
        return compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            analysis_id=_required_payload_identity_id(payload, "analysis_id"),
        )
    if scope == "datasource_preview":
        return compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            datasource_id=_required_payload_identity_id(payload, "datasource_id"),
        )
    if scope == "build":
        return compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_BUILD,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
            build_id=_required_payload_identity_id(payload, "build_id"),
        )
    raise ValueError("engine identity scope is invalid")


def worker_internal_api_client() -> WorkerInternalApiClient:
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
    request_json: dict[str, object]
    command_envelope: compute_pb2.ComputeCommandEnvelope

    def read_int(self, key: str) -> int | None:
        value = self.request_json.get(key)
        return int(value) if value is not None and isinstance(value, (str, int)) else None

    def read_str(self, key: str) -> str | None:
        value = self.request_json.get(key)
        return str(value) if value is not None else None

    def read_dict(self, key: str) -> dict[str, object] | None:
        value = self.request_json.get(key)
        return dict(value) if isinstance(value, dict) else None


def next_compute_request(worker_id: str) -> ClaimedComputeRequest | None:
    claimed = worker_internal_api_client().claim_compute_request(worker_id=worker_id)
    if claimed is None:
        return None
    return ClaimedComputeRequest(
        id=claimed.id,
        namespace=claimed.namespace,
        kind=claimed.kind,
        request_json=claimed.request_json,
        command_envelope=claimed.command_envelope,
    )


async def compute_request_loop(
    stop_event: asyncio.Event,
    *,
    worker_id: str,
    manager: ProcessManager,
) -> None:
    last_seen = request_hub.version()
    try:
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
    finally:
        release_worker_requests(worker_id)


async def _run_once(*, worker_id: str, manager: ProcessManager) -> bool:
    claimed = next_compute_request(worker_id)
    if claimed is None:
        return False
    await _execute_request(claimed, manager)
    return True


def release_worker_requests(worker_id: str) -> None:
    worker_internal_api_client().release_compute_requests(worker_id=worker_id)


async def _execute_request(claimed: ClaimedComputeRequest, manager: ProcessManager) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_COMPUTE_REQUEST_EXECUTOR, _execute_request_sync, claimed, manager)


def _execute_request_sync(claimed: ClaimedComputeRequest, manager: ProcessManager) -> None:
    client = worker_internal_api_client()
    token = set_namespace_context(claimed.namespace)
    try:
        if claimed.kind in _DATASOURCE_REQUEST_KINDS:
            response_json = client.execute_datasource_request(namespace=claimed.namespace, kind=claimed.kind, request_json=claimed.request_json)
            _complete_request(client, claimed, response_json=response_json)
            return

        if claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW:
            preview_request = compute_schemas.StepPreviewRequest.model_validate(claimed.request_json)
            preview_identity = (
                _engine_identity_from_payload(preview_request.engine_identity.model_dump(mode="json")) if preview_request.engine_identity is not None else None
            )
            preview_response = service.preview_step(
                session=None,
                manager=manager,
                target_step_id=preview_request.target_step_id,
                analysis_pipeline=preview_request.analysis_pipeline.model_dump(mode="json"),
                row_limit=preview_request.row_limit,
                page=preview_request.page,
                analysis_id=preview_request.analysis_id,
                engine_identity=preview_identity,
                resource_config=preview_request.resource_config.model_dump() if preview_request.resource_config else None,
                tab_id=preview_request.tab_id,
                request_json=preview_request.model_dump(mode="json"),
            )
            _complete_request(client, claimed, response_json=preview_response.model_dump(mode="json"))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA:
            schema_request = compute_schemas.StepSchemaRequest.model_validate(claimed.request_json)
            if schema_request.analysis_id is None:
                raise ValueError("analysis_id is required")
            schema_response = service.get_step_schema(
                session=None,
                manager=manager,
                target_step_id=schema_request.target_step_id,
                analysis_id=schema_request.analysis_id,
                analysis_pipeline=schema_request.analysis_pipeline.model_dump(mode="json"),
                tab_id=schema_request.tab_id,
            )
            _complete_request(client, claimed, response_json=schema_response.model_dump(mode="json"))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT:
            row_count_request = compute_schemas.StepRowCountRequest.model_validate(claimed.request_json)
            if row_count_request.analysis_id is None:
                raise ValueError("analysis_id is required")
            row_count_response = service.get_step_row_count(
                session=None,
                manager=manager,
                target_step_id=row_count_request.target_step_id,
                analysis_id=row_count_request.analysis_id,
                analysis_pipeline=row_count_request.analysis_pipeline.model_dump(mode="json"),
                tab_id=row_count_request.tab_id,
                request_json=row_count_request.model_dump(mode="json"),
            )
            _complete_request(client, claimed, response_json=row_count_response.model_dump(mode="json"))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD:
            download_request = compute_schemas.DownloadRequest.model_validate(claimed.request_json)
            file_bytes, filename, content_type = service.download_step(
                session=None,
                manager=manager,
                target_step_id=download_request.target_step_id,
                analysis_pipeline=download_request.analysis_pipeline.model_dump(mode="json"),
                export_format=download_request.format.value,
                filename=download_request.filename,
                analysis_id=download_request.analysis_id,
                tab_id=download_request.tab_id,
            )
            artifact_path = _write_artifact(claimed.id, filename, file_bytes)
            _complete_request(client, claimed, artifact_path=artifact_path, artifact_name=filename, artifact_content_type=content_type)
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_EXPORT:
            export_request = compute_schemas.ExportRequest.model_validate(claimed.request_json)
            result = service.export_data(
                session=None,
                manager=manager,
                target_step_id=export_request.target_step_id,
                analysis_pipeline=export_request.analysis_pipeline.model_dump(mode="json"),
                filename=export_request.filename,
                iceberg_options=export_request.iceberg_options.model_dump() if export_request.iceberg_options else None,
                analysis_id=export_request.analysis_id,
                tab_id=export_request.tab_id,
                request_json=export_request.model_dump(mode="json"),
                result_id=export_request.result_id,
            )
            export_response = compute_schemas.ExportResponse(
                success=True,
                filename=result.datasource_name,
                format="iceberg",
                destination=export_request.destination.value,
                message=f"Created datasource {result.datasource_name}",
                datasource_id=result.datasource_id,
                datasource_name=result.result_meta.get("datasource_name") if isinstance(result.result_meta, dict) else None,
            )
            _complete_request(client, claimed, response_json=export_response.model_dump(mode="json"))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE:
            command = _lifecycle_command_from_claimed(claimed, "spawn_engine")
            identity = command.engine_identity
            resource_config = _resource_config_from_lifecycle_command(command)
            manager.spawn_engine(
                identity,
                resource_config=resource_config,
            )
            response = compute_schemas.EngineStatusSchema.model_validate(manager.get_engine_status(identity))
            _complete_request(client, claimed, response_json=response.model_dump(mode="json"))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE:
            command = _lifecycle_command_from_claimed(claimed, "configure_engine")
            identity = command.engine_identity
            resource_config = _resource_config_from_lifecycle_command(command)
            if resource_config is None:
                raise ValueError("resource_config is required")
            manager.restart_engine_with_config(identity, resource_config)
            response = compute_schemas.EngineStatusSchema.model_validate(manager.get_engine_status(identity))
            _complete_request(client, claimed, response_json=response.model_dump(mode="json"))
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE:
            command = _lifecycle_command_from_claimed(claimed, "shutdown_engine")
            identity = command.engine_identity
            engine = manager.get_engine(identity)
            if engine is None:
                raise engine_not_found(engine_identity_resource_id(identity))
            deadline = time.monotonic() + _ENGINE_SHUTDOWN_WAIT_SECONDS
            while engine.current_job_id and engine.is_process_alive() and time.monotonic() < deadline:
                time.sleep(_ENGINE_SHUTDOWN_POLL_SECONDS)
            if engine.current_job_id and engine.is_process_alive():
                raise EngineBusyError(engine_identity_resource_id(identity))
            manager.shutdown_engine(identity)
            _complete_request(client, claimed, response_json={"success": True})
        else:
            raise ValueError(f"Unsupported compute request kind: {_compute_request_kind_name(claimed.kind)}")
    except Exception as exc:
        payload = _error_payload(exc)
        status_code = payload.get("status_code")
        if isinstance(status_code, int) and status_code >= 500:
            logger.error("Compute request %s failed: %s", claimed.id, exc, exc_info=True)
        elif isinstance(status_code, int) and status_code >= 400:
            logger.info("Compute request %s rejected: %s", claimed.id, exc)
        else:
            logger.warning("Compute request %s failed: %s", claimed.id, exc)
        client.fail_compute_request(
            namespace=claimed.namespace, request_id=claimed.id, kind=claimed.kind, error_message=_error_message(exc), response_json=payload
        )
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


def _complete_request(
    client: WorkerInternalApiClient,
    claimed: ClaimedComputeRequest,
    *,
    response_json: dict[str, object] | None = None,
    artifact_path: str | None = None,
    artifact_name: str | None = None,
    artifact_content_type: str | None = None,
) -> None:
    client.complete_compute_request(
        namespace=claimed.namespace,
        request_id=claimed.id,
        kind=claimed.kind,
        response_json=response_json,
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


def _error_payload(exc: Exception) -> dict[str, object]:
    if isinstance(exc, BackendWorkerRpcError):
        payload: dict[str, object] = {
            "error": exc.error,
            "status_code": exc.status_code,
        }
        if exc.error_code is not None:
            payload["error_code"] = exc.error_code
        if exc.details:
            payload["details"] = exc.details
        return payload
    if isinstance(exc, AppError):
        return {
            "error": exc.message,
            "status_code": status_for_app_error(exc),
            "error_code": exc.error_code,
            "details": exc.details or {},
        }
    if isinstance(exc, ValueError):
        return {"error": str(exc), "status_code": 400}
    return {"error": "An internal error occurred", "status_code": 500}
