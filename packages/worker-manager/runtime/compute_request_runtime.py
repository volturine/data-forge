from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path

from contracts.compute import schemas as compute_schemas
from contracts.compute_requests.live import request_hub
from contracts.compute_requests.models import ComputeRequestKind
from contracts.runtime import ipc as runtime_ipc
from contracts.runtime_workers.models import RuntimeWorkerKind
from core import compute_requests_service, runtime_workers_service
from core.app_error_status import status_for_app_error
from core.config import settings
from core.database import get_db, run_db, run_settings_db
from core.exceptions import AppError, EngineBusyError, EngineNotFoundError
from core.namespace import reset_namespace, set_namespace_context
from sqlmodel import Session

from datasources import datasource_service
from datasources.datasource_schemas import CSVOptions
from runtime import compute_service as service
from runtime.compute_manager import ProcessManager
from runtime.worker_runtime import runtime_namespaces

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedComputeRequest:
    id: str
    namespace: str
    kind: ComputeRequestKind
    request_json: dict[str, object]

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
    reclaimable_owner_ids = run_settings_db(
        runtime_workers_service.reclaimable_worker_ids,
        kind=RuntimeWorkerKind.BUILD_MANAGER,
    )
    for namespace in runtime_namespaces():
        token = set_namespace_context(namespace)
        try:

            def _claim(session: Session) -> ClaimedComputeRequest | None:
                request = compute_requests_service.claim_next_request(
                    session,
                    worker_id=worker_id,
                    reclaimable_owner_ids=reclaimable_owner_ids,
                )
                if request is None:
                    return None
                return ClaimedComputeRequest(
                    id=request.id,
                    namespace=request.namespace,
                    kind=request.kind,
                    request_json=request.request_json,
                )

            claimed = run_db(_claim)
        finally:
            reset_namespace(token)
        if claimed is not None:
            return claimed
    return None


async def compute_request_loop(
    stop_event: asyncio.Event,
    *,
    worker_id: str,
    manager: ProcessManager,
) -> None:
    last_seen = request_hub.version()
    try:
        while not stop_event.is_set():
            handled = await _run_once(worker_id=worker_id, manager=manager)
            if handled:
                last_seen = request_hub.version()
                continue
            wait_task = asyncio.create_task(request_hub.wait(last_seen))
            stop_task = asyncio.create_task(stop_event.wait())
            done, pending = await asyncio.wait(
                {wait_task, stop_task},
                timeout=0.25,
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
    for namespace in runtime_namespaces():
        token = set_namespace_context(namespace)
        try:
            run_db(compute_requests_service.release_worker_requests, worker_id=worker_id)
        finally:
            reset_namespace(token)


async def _execute_request(claimed: ClaimedComputeRequest, manager: ProcessManager) -> None:
    token = set_namespace_context(claimed.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        if claimed.kind == ComputeRequestKind.PREVIEW:
            preview_request = compute_schemas.StepPreviewRequest.model_validate(claimed.request_json)
            preview_response = service.preview_step(
                session=session,
                manager=manager,
                target_step_id=preview_request.target_step_id,
                analysis_pipeline=preview_request.analysis_pipeline.model_dump(mode="json"),
                row_limit=preview_request.row_limit,
                page=preview_request.page,
                analysis_id=preview_request.analysis_id,
                resource_config=preview_request.resource_config.model_dump() if preview_request.resource_config else None,
                tab_id=preview_request.tab_id,
                request_json=preview_request.model_dump(mode="json"),
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=preview_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.SCHEMA:
            schema_request = compute_schemas.StepSchemaRequest.model_validate(claimed.request_json)
            if schema_request.analysis_id is None:
                raise ValueError("analysis_id is required")
            schema_response = service.get_step_schema(
                session=session,
                manager=manager,
                target_step_id=schema_request.target_step_id,
                analysis_id=schema_request.analysis_id,
                analysis_pipeline=schema_request.analysis_pipeline.model_dump(mode="json"),
                tab_id=schema_request.tab_id,
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=schema_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.ROW_COUNT:
            row_count_request = compute_schemas.StepRowCountRequest.model_validate(claimed.request_json)
            if row_count_request.analysis_id is None:
                raise ValueError("analysis_id is required")
            row_count_response = service.get_step_row_count(
                session=session,
                manager=manager,
                target_step_id=row_count_request.target_step_id,
                analysis_id=row_count_request.analysis_id,
                analysis_pipeline=row_count_request.analysis_pipeline.model_dump(mode="json"),
                tab_id=row_count_request.tab_id,
                request_json=row_count_request.model_dump(mode="json"),
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=row_count_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.DOWNLOAD:
            download_request = compute_schemas.DownloadRequest.model_validate(claimed.request_json)
            file_bytes, filename, content_type = service.download_step(
                session=session,
                manager=manager,
                target_step_id=download_request.target_step_id,
                analysis_pipeline=download_request.analysis_pipeline.model_dump(mode="json"),
                export_format=download_request.format.value,
                filename=download_request.filename,
                analysis_id=download_request.analysis_id,
                tab_id=download_request.tab_id,
            )
            artifact_path = _write_artifact(claimed.id, filename, file_bytes)
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                artifact_path=str(artifact_path),
                artifact_name=filename,
                artifact_content_type=content_type,
            )
        elif claimed.kind == ComputeRequestKind.EXPORT:
            export_request = compute_schemas.ExportRequest.model_validate(claimed.request_json)
            result = service.export_data(
                session=session,
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
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=export_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.CREATE_FILE_DATASOURCE:
            raw_csv_options = claimed.request_json.get("csv_options")
            csv_options = CSVOptions.model_validate(raw_csv_options) if isinstance(raw_csv_options, dict) else None
            datasource_response = datasource_service.create_file_datasource(
                session=session,
                name=str(claimed.request_json["name"]),
                description=str(claimed.request_json["description"]) if claimed.request_json.get("description") is not None else None,
                file_path=str(claimed.request_json["file_path"]),
                file_type=str(claimed.request_json["file_type"]),
                options=claimed.read_dict("options"),
                csv_options=csv_options,
                sheet_name=claimed.read_str("sheet_name"),
                start_row=claimed.read_int("start_row"),
                start_col=claimed.read_int("start_col"),
                end_col=claimed.read_int("end_col"),
                end_row=claimed.read_int("end_row"),
                has_header=bool(claimed.request_json["has_header"]) if claimed.request_json.get("has_header") is not None else None,
                table_name=claimed.read_str("table_name"),
                named_range=claimed.read_str("named_range"),
                cell_range=claimed.read_str("cell_range"),
                owner_id=claimed.read_str("owner_id"),
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=datasource_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.CREATE_DATABASE_DATASOURCE:
            datasource_response = datasource_service.create_database_datasource(
                session=session,
                name=str(claimed.request_json["name"]),
                description=str(claimed.request_json["description"]) if claimed.request_json.get("description") is not None else None,
                connection_string=str(claimed.request_json["connection_string"]),
                query=str(claimed.request_json["query"]),
                branch=str(claimed.request_json["branch"]),
                owner_id=str(claimed.request_json["owner_id"]) if claimed.request_json.get("owner_id") is not None else None,
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=datasource_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.CREATE_ICEBERG_DATASOURCE:
            raw_source = claimed.request_json.get("source")
            if not isinstance(raw_source, dict):
                raise ValueError("source is required")
            datasource_response = datasource_service.create_iceberg_datasource(
                session=session,
                name=str(claimed.request_json["name"]),
                description=str(claimed.request_json["description"]) if claimed.request_json.get("description") is not None else None,
                source=dict(raw_source),
                branch=str(claimed.request_json["branch"]),
                owner_id=str(claimed.request_json["owner_id"]) if claimed.request_json.get("owner_id") is not None else None,
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=datasource_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.REFRESH_DATASOURCE:
            datasource_id = str(claimed.request_json["datasource_id"])
            datasource_response = datasource_service.refresh_external_datasource(session, datasource_id)
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=datasource_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.DATASOURCE_SCHEMA:
            schema_response = datasource_service.get_datasource_schema(
                session,
                str(claimed.request_json["datasource_id"]),
                sheet_name=claimed.read_str("sheet_name"),
                refresh=bool(claimed.request_json.get("refresh", False)),
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=schema_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.DATASOURCE_COLUMN_STATS:
            stats_response = datasource_service.get_column_stats(
                session=session,
                datasource_id=str(claimed.request_json["datasource_id"]),
                column_name=str(claimed.request_json["column_name"]),
                use_sample=bool(claimed.request_json.get("use_sample", True)),
                sample_size=claimed.read_int("sample_size") or 10000,
                datasource_config=claimed.read_dict("datasource_config"),
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=stats_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.COMPARE_ICEBERG_SNAPSHOTS:
            compare_response = datasource_service.compare_iceberg_snapshots(
                session,
                str(claimed.request_json["datasource_id"]),
                str(claimed.request_json["snapshot_a"]),
                str(claimed.request_json["snapshot_b"]),
                claimed.read_int("row_limit") or 10,
            )
            compute_requests_service.mark_request_completed(
                session,
                claimed.id,
                response_json=compare_response.model_dump(mode="json"),
            )
        elif claimed.kind == ComputeRequestKind.SPAWN_ENGINE:
            analysis_id = str(claimed.request_json["analysis_id"])
            resource_config = claimed.request_json.get("resource_config")
            manager.spawn_engine(
                analysis_id,
                resource_config=resource_config if isinstance(resource_config, dict) else None,
            )
            response = compute_schemas.EngineStatusSchema.model_validate(manager.get_engine_status(analysis_id))
            compute_requests_service.mark_request_completed(session, claimed.id, response_json=response.model_dump(mode="json"))
        elif claimed.kind == ComputeRequestKind.CONFIGURE_ENGINE:
            analysis_id = str(claimed.request_json["analysis_id"])
            resource_config = claimed.request_json.get("resource_config")
            if not isinstance(resource_config, dict):
                raise ValueError("resource_config is required")
            manager.restart_engine_with_config(analysis_id, resource_config)
            response = compute_schemas.EngineStatusSchema.model_validate(manager.get_engine_status(analysis_id))
            compute_requests_service.mark_request_completed(session, claimed.id, response_json=response.model_dump(mode="json"))
        elif claimed.kind == ComputeRequestKind.SHUTDOWN_ENGINE:
            analysis_id = str(claimed.request_json["analysis_id"])
            engine = manager.get_engine(analysis_id)
            if engine is None:
                raise EngineNotFoundError(analysis_id)
            if engine.current_job_id and engine.is_process_alive():
                raise EngineBusyError(analysis_id)
            manager.shutdown_engine(analysis_id)
            compute_requests_service.mark_request_completed(session, claimed.id, response_json={"success": True})
        else:
            raise ValueError(f"Unsupported compute request kind: {claimed.kind.value}")
    except Exception as exc:
        payload = _error_payload(exc)
        status_code = payload.get("status_code")
        if isinstance(status_code, int) and status_code >= 500:
            logger.error("Compute request %s failed: %s", claimed.id, exc, exc_info=True)
        elif isinstance(status_code, int) and status_code >= 400:
            logger.info("Compute request %s rejected: %s", claimed.id, exc)
        else:
            logger.warning("Compute request %s failed: %s", claimed.id, exc)
        compute_requests_service.mark_request_failed(
            session,
            claimed.id,
            error_message=_error_message(exc),
            response_json=payload,
        )
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)
        await asyncio.to_thread(runtime_ipc.notify_compute_response, claimed.id)


def _write_artifact(request_id: str, filename: str, content: bytes) -> Path:
    directory = Path(settings.data_dir) / "runtime-compute-downloads"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{request_id}-{filename}"
    path.write_bytes(content)
    return path


def _error_message(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.message
    return str(exc)


def _error_payload(exc: Exception) -> dict[str, object]:
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
