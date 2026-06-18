from __future__ import annotations

import base64
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar, cast

import grpc

from dataforge_protocol import common_pb2, compute_pb2, enums_pb2, worker_runtime_pb2, worker_runtime_pb2_grpc
from worker_grpc.codec import (
    datetime_to_timestamp,
    dict_to_struct,
    enum_to_proto_value,
    optional_struct_to_dict,
    optional_timestamp_to_datetime,
    proto_value_to_enum_name,
    struct_to_dict,
)

_TOKEN_METADATA_KEY = "x-internal-token"
_T = TypeVar("_T")


@dataclass(frozen=True)
class ClaimedBuildJob:
    job_id: str
    build_id: str
    namespace: str


@dataclass(frozen=True)
class StartedBuildRun:
    id: str
    namespace: str
    analysis_id: str
    analysis_name: str
    request_json: dict[str, object]
    starter_json: dict[str, object]
    resource_config_json: dict[str, object] | None
    current_kind: str | None
    current_datasource_id: str | None
    current_tab_id: str | None
    current_tab_name: str | None
    current_output_id: str | None
    current_output_name: str | None
    started_at: datetime
    total_tabs: int


@dataclass(frozen=True)
class PendingDatasourceDelete:
    namespace: str
    datasource_id: str


@dataclass(frozen=True)
class TelegramTarget:
    chat_id: str
    bot_token: str


@dataclass(frozen=True)
class DatasourceMetadata:
    found: bool
    id: str | None
    name: str | None
    source_type: str | None
    config: dict[str, object] | None
    schema_cache: dict[str, object] | None
    is_hidden: bool | None


@dataclass(frozen=True)
class HealthCheckSpec:
    id: str
    name: str
    check_type: str
    config: dict[str, object]
    critical: bool


@dataclass(frozen=True)
class ClaimedComputeRequest:
    id: str
    namespace: str
    kind: str
    request_json: dict[str, object]
    command_envelope: compute_pb2.ComputeCommandEnvelope


class BackendWorkerRpcError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        error: str,
        error_code: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.error_code = error_code
        self.details = details or {}


class WorkerInternalApiClient:
    def __init__(self, *, target: str, token: str, timeout_seconds: float = 120.0, registration_retry_seconds: float = 90.0) -> None:
        self._target = target
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._registration_retry_seconds = registration_retry_seconds
        self._channel = grpc.insecure_channel(target)
        self._stub = worker_runtime_pb2_grpc.WorkerRuntimeServiceStub(self._channel)

    def register_worker(self, *, worker_id: str, kind: str, hostname: str, pid: int, capacity: int, active_jobs: int = 0) -> None:
        request = worker_runtime_pb2.RuntimeWorkerRegisterRequest(
            worker_id=worker_id,
            kind=enum_to_proto_value("RUNTIME_WORKER_KIND", kind),
            hostname=hostname,
            pid=pid,
            capacity=capacity,
            active_jobs=active_jobs,
        )
        self._call_registration(lambda: self._stub.RegisterWorker(request, timeout=self._timeout_seconds, metadata=self._metadata()))

    def heartbeat_worker(self, *, worker_id: str, active_jobs: int | None = None) -> None:
        request = worker_runtime_pb2.RuntimeWorkerHeartbeatRequest(worker_id=worker_id)
        if active_jobs is not None:
            request.active_jobs = active_jobs
        self._call(lambda: self._stub.HeartbeatWorker(request, timeout=self._timeout_seconds, metadata=self._metadata()))

    def stop_worker(self, *, worker_id: str) -> None:
        self._call(lambda: self._stub.StopWorker(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata()))

    def claim_build_job(self, *, worker_id: str) -> ClaimedBuildJob | None:
        response = self._call(lambda: self._stub.ClaimBuildJob(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata()))
        if not response.HasField("job"):
            return None
        return ClaimedBuildJob(job_id=response.job.job_id, build_id=response.job.build_id, namespace=response.job.namespace)

    def claim_compute_request(self, *, worker_id: str) -> ClaimedComputeRequest | None:
        response = self._call(lambda: self._stub.ClaimComputeRequest(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata()))
        if not response.HasField("request"):
            return None
        command = response.request.command
        return ClaimedComputeRequest(
            id=response.request.id,
            namespace=response.request.namespace,
            kind=proto_value_to_enum_name(enums_pb2.ComputeRequestKind, "COMPUTE_REQUEST_KIND", command.kind),
            request_json=struct_to_dict(command.payload),
            command_envelope=command,
        )

    def complete_compute_request(
        self,
        *,
        namespace: str,
        request_id: str,
        kind: str,
        response_json: dict[str, object] | None = None,
        artifact_path: str | None = None,
        artifact_name: str | None = None,
        artifact_content_type: str | None = None,
    ) -> None:
        request = worker_runtime_pb2.WorkerCompleteComputeRequestRequest(
            namespace=namespace,
            request_id=request_id,
            response_envelope=_compute_response_envelope(
                kind=kind,
                request_id=request_id,
                status="completed",
                response_json=response_json or {},
            ),
        )
        if artifact_path is not None:
            request.artifact_path = artifact_path
        if artifact_name is not None:
            request.artifact_name = artifact_name
        if artifact_content_type is not None:
            request.artifact_content_type = artifact_content_type
        self._call(lambda: self._stub.CompleteComputeRequest(request, timeout=self._timeout_seconds, metadata=self._metadata()))

    def fail_compute_request(
        self,
        *,
        namespace: str,
        request_id: str,
        kind: str,
        error_message: str,
        response_json: dict[str, object],
    ) -> None:
        self._call(
            lambda: self._stub.FailComputeRequest(
                worker_runtime_pb2.WorkerFailComputeRequestRequest(
                    namespace=namespace,
                    request_id=request_id,
                    error_message=error_message,
                    response_envelope=_compute_response_envelope(
                        kind=kind,
                        request_id=request_id,
                        status="failed",
                        response_json=response_json,
                        error_message=error_message,
                    ),
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def release_compute_requests(self, *, worker_id: str) -> int:
        return int(self._call(lambda: self._stub.ReleaseComputeRequests(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata())).count)

    def execute_datasource_request(self, *, namespace: str, kind: str, request_json: dict[str, object]) -> dict[str, object]:
        response = self._call(
            lambda: self._stub.ExecuteDatasourceRequest(
                worker_runtime_pb2.WorkerExecuteDatasourceRequest(
                    namespace=namespace,
                    kind=enum_to_proto_value("COMPUTE_REQUEST_KIND", kind),
                    request=dict_to_struct(request_json),
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return struct_to_dict(response.response)

    def schedule_ingest_datasource(self, *, namespace: str, datasource_id: str) -> dict[str, object]:
        response = self._call(
            lambda: self._stub.ScheduleIngestDatasource(
                worker_runtime_pb2.WorkerScheduleIngestDatasourceRequest(namespace=namespace, datasource_id=datasource_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return struct_to_dict(response.response)

    def datasource_metadata(self, *, namespace: str, datasource_id: str) -> DatasourceMetadata:
        response = self._call(
            lambda: self._stub.GetDatasourceMetadata(
                worker_runtime_pb2.WorkerDatasourceMetadataRequest(namespace=namespace, datasource_id=datasource_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return DatasourceMetadata(
            found=response.found,
            id=_optional_str(response, "id"),
            name=_optional_str(response, "name"),
            source_type=_optional_proto_enum_name(response, "source_type", enums_pb2.DataSourceType, "DATA_SOURCE_TYPE"),
            config=optional_struct_to_dict(response, "config"),
            schema_cache=optional_struct_to_dict(response, "schema_cache"),
            is_hidden=_optional_bool(response, "is_hidden"),
        )

    def udf_codes(self, *, namespace: str, udf_ids: list[str]) -> dict[str, str]:
        response = self._call(
            lambda: self._stub.GetUdfCodes(
                worker_runtime_pb2.WorkerUdfCodesRequest(namespace=namespace, udf_ids=udf_ids),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return dict(response.codes)

    def analysis_name(self, *, namespace: str, analysis_id: str) -> str | None:
        response = self._call(
            lambda: self._stub.GetAnalysisMetadata(
                worker_runtime_pb2.WorkerAnalysisMetadataRequest(namespace=namespace, analysis_id=analysis_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        if not response.found:
            return None
        return _optional_str(response, "name")

    def build_cancel_status(self, *, namespace: str, build_id: str) -> tuple[bool, str | None, str | None]:
        response = self._call(
            lambda: self._stub.GetBuildCancelStatus(
                worker_runtime_pb2.WorkerBuildCancelStatusRequest(namespace=namespace, build_id=build_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return (response.cancelled, _optional_timestamp_iso(response, "cancelled_at"), _optional_str(response, "cancelled_by"))

    def update_build_result(self, *, namespace: str, build_id: str, result_json: dict[str, object]) -> None:
        self._call(
            lambda: self._stub.UpdateBuildResult(
                worker_runtime_pb2.WorkerUpdateBuildResultRequest(namespace=namespace, build_id=build_id, result=dict_to_struct(result_json)),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def upsert_output_datasource(
        self,
        *,
        namespace: str,
        result_id: str,
        name: str,
        source_type: str,
        config: dict[str, object],
        schema_cache: dict[str, object],
        analysis_id: str | None,
        is_hidden: bool | None,
        keep_schema_cache: bool,
    ) -> DatasourceMetadata:
        request = worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest(
            namespace=namespace,
            result_id=result_id,
            name=name,
            source_type=enum_to_proto_value("DATA_SOURCE_TYPE", source_type),
            config=dict_to_struct(config),
            schema_cache=dict_to_struct(schema_cache),
            keep_schema_cache=keep_schema_cache,
        )
        if analysis_id is not None:
            request.analysis_id = analysis_id
        if is_hidden is not None:
            request.is_hidden = is_hidden
        response = self._call(lambda: self._stub.UpsertOutputDatasource(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return DatasourceMetadata(
            found=True,
            id=response.datasource_id,
            name=response.datasource_name,
            source_type=source_type,
            config=config,
            schema_cache=schema_cache,
            is_hidden=response.is_hidden,
        )

    def list_healthchecks(self, *, namespace: str, datasource_id: str) -> list[HealthCheckSpec]:
        response = self._call(
            lambda: self._stub.ListHealthChecks(
                worker_runtime_pb2.WorkerListHealthChecksRequest(namespace=namespace, datasource_id=datasource_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return [
            HealthCheckSpec(
                id=check.id,
                name=check.name,
                check_type=proto_value_to_enum_name(enums_pb2.HealthCheckType, "HEALTH_CHECK_TYPE", check.check_type),
                config=struct_to_dict(check.config),
                critical=check.critical,
            )
            for check in response.checks
        ]

    def record_healthcheck_results(self, *, namespace: str, results: list[Mapping[str, object]]) -> int:
        request = worker_runtime_pb2.WorkerRecordHealthCheckResultsRequest(
            namespace=namespace,
            results=[
                worker_runtime_pb2.WorkerHealthCheckResultPayload(
                    healthcheck_id=_required_mapping_str(result, "healthcheck_id"),
                    passed=_required_mapping_bool(result, "passed"),
                    message=_required_mapping_str(result, "message"),
                    details=dict_to_struct(_required_mapping_dict(result, "details")),
                    checked_at=datetime_to_timestamp(datetime.fromisoformat(_required_mapping_str(result, "checked_at"))),
                )
                for result in results
            ],
        )
        return int(self._call(lambda: self._stub.RecordHealthCheckResults(request, timeout=self._timeout_seconds, metadata=self._metadata())).count)

    def create_engine_run(
        self,
        *,
        namespace: str,
        analysis_id: str | None,
        datasource_id: str,
        kind: str,
        status: str,
        request_json: dict[str, object],
        result_json: dict[str, object] | None = None,
        error_message: str | None = None,
        created_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
        step_timings: dict[str, float] | None = None,
        query_plan: str | None = None,
        execution_entries: list[dict[str, object]] | None = None,
        progress: float = 0.0,
        current_step: str | None = None,
        triggered_by: str | None = None,
    ) -> str:
        request = worker_runtime_pb2.WorkerCreateEngineRunRequest(
            namespace=namespace,
            datasource_id=datasource_id,
            kind=enum_to_proto_value("ENGINE_RUN_KIND", kind),
            status=enum_to_proto_value("ENGINE_RUN_STATUS", status),
            request=dict_to_struct(request_json),
            execution_entries=[dict_to_struct(entry) for entry in execution_entries or []],
            progress=progress,
        )
        if analysis_id is not None:
            request.analysis_id = analysis_id
        if result_json is not None:
            request.result.CopyFrom(dict_to_struct(result_json))
        if error_message is not None:
            request.error_message = error_message
        if created_at is not None:
            request.created_at.CopyFrom(datetime_to_timestamp(created_at))
        if completed_at is not None:
            request.completed_at.CopyFrom(datetime_to_timestamp(completed_at))
        if duration_ms is not None:
            request.duration_ms = duration_ms
        if step_timings is not None:
            request.step_timings.CopyFrom(dict_to_struct(cast(dict[str, object], step_timings)))
        if query_plan is not None:
            request.query_plan = query_plan
        if current_step is not None:
            request.current_step = current_step
        if triggered_by is not None:
            request.triggered_by = triggered_by
        return self._call(lambda: self._stub.CreateEngineRun(request, timeout=self._timeout_seconds, metadata=self._metadata())).id

    def update_engine_run(
        self,
        *,
        namespace: str,
        run_id: str,
        fields: dict[str, object],
        merge_result_json: bool = True,
    ) -> str:
        response = self._call(
            lambda: self._stub.UpdateEngineRun(
                worker_runtime_pb2.WorkerUpdateEngineRunRequest(
                    namespace=namespace,
                    run_id=run_id,
                    fields=dict_to_struct(fields),
                    merge_result=merge_result_json,
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return response.id

    def engine_run_state(self, *, namespace: str, run_id: str) -> dict[str, object] | None:
        response = self._call(
            lambda: self._stub.GetEngineRunState(
                worker_runtime_pb2.WorkerEngineRunStateRequest(namespace=namespace, run_id=run_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        if not response.found:
            return None
        return {
            "status": _optional_proto_enum_name(response, "status", enums_pb2.EngineRunStatus, "ENGINE_RUN_STATUS"),
            "result_json": optional_struct_to_dict(response, "result") or {},
            "cancelled_at": _optional_timestamp_iso(response, "cancelled_at"),
            "cancelled_by": _optional_str(response, "cancelled_by"),
        }

    def fail_build_job(self, *, job_id: str, namespace: str, error: str) -> None:
        self._call(
            lambda: self._stub.FailBuildJob(
                worker_runtime_pb2.WorkerFailBuildJobRequest(job_id=job_id, namespace=namespace, error=error),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def finalize_build_job(self, *, job_id: str, build_id: str, namespace: str) -> None:
        self._call(
            lambda: self._stub.FinalizeBuildJob(
                worker_runtime_pb2.WorkerFinalizeBuildJobRequest(job_id=job_id, build_id=build_id, namespace=namespace),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def release_build_worker_jobs(self, *, worker_id: str) -> int:
        return int(self._call(lambda: self._stub.ReleaseBuildWorkerJobs(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata())).count)

    def queued_build_job_count(self) -> int:
        return int(
            self._call(lambda: self._stub.GetQueuedBuildJobCount(common_pb2.EmptyRequest(), timeout=self._timeout_seconds, metadata=self._metadata())).count
        )

    def dispatch_runtime_outbox(self) -> int:
        return int(
            self._call(lambda: self._stub.DispatchRuntimeOutbox(common_pb2.EmptyRequest(), timeout=self._timeout_seconds, metadata=self._metadata())).count
        )

    def idle_build_worker_pids(self) -> set[int]:
        response = self._call(lambda: self._stub.GetIdleBuildWorkerPids(common_pb2.EmptyRequest(), timeout=self._timeout_seconds, metadata=self._metadata()))
        return set(response.pids)

    def runtime_namespaces(self) -> list[str]:
        response = self._call(lambda: self._stub.ListRuntimeNamespaces(common_pb2.EmptyRequest(), timeout=self._timeout_seconds, metadata=self._metadata()))
        return list(response.namespaces)

    def persist_build_event(
        self,
        *,
        namespace: str,
        build_id: str,
        event: dict[str, object],
        resource_config_json: dict[str, object] | None = None,
    ) -> int | None:
        request = worker_runtime_pb2.WorkerPersistBuildEventRequest(namespace=namespace, build_id=build_id, event=dict_to_struct(event))
        if resource_config_json is not None:
            request.resource_config.CopyFrom(dict_to_struct(resource_config_json))
        response = self._call(lambda: self._stub.PersistBuildEvent(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return int(response.sequence) if response.HasField("sequence") else None

    def start_build_run(self, *, namespace: str, build_id: str) -> StartedBuildRun | None:
        response = self._call(
            lambda: self._stub.StartBuildRun(
                worker_runtime_pb2.WorkerStartBuildRunRequest(namespace=namespace, build_id=build_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        if not response.HasField("run"):
            return None
        run = response.run
        return StartedBuildRun(
            id=run.id,
            namespace=run.namespace,
            analysis_id=run.analysis_id,
            analysis_name=run.analysis_name,
            request_json=struct_to_dict(run.request),
            starter_json=struct_to_dict(run.starter),
            resource_config_json=optional_struct_to_dict(run, "resource_config"),
            current_kind=_optional_proto_enum_name(run, "current_kind", enums_pb2.EngineRunKind, "ENGINE_RUN_KIND"),
            current_datasource_id=_optional_str(run, "current_datasource_id"),
            current_tab_id=_optional_str(run, "current_tab_id"),
            current_tab_name=_optional_str(run, "current_tab_name"),
            current_output_id=_optional_str(run, "current_output_id"),
            current_output_name=_optional_str(run, "current_output_name"),
            started_at=optional_timestamp_to_datetime(run, "started_at") or datetime.min,
            total_tabs=run.total_tabs,
        )

    def persist_engine_snapshot(self, *, worker_id: str, namespace: str, statuses: list[Mapping[str, object]]) -> int:
        response = self._call(
            lambda: self._stub.PersistEngineSnapshot(
                worker_runtime_pb2.WorkerPersistEngineSnapshotRequest(
                    worker_id=worker_id,
                    namespace=namespace,
                    statuses=[dict_to_struct(dict(status)) for status in statuses],
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return int(response.count)

    def pending_datasource_deletes(self) -> list[PendingDatasourceDelete]:
        response = self._call(
            lambda: self._stub.ListPendingDatasourceDeletes(common_pb2.EmptyRequest(), timeout=self._timeout_seconds, metadata=self._metadata())
        )
        return [PendingDatasourceDelete(namespace=delete.namespace, datasource_id=delete.datasource_id) for delete in response.deletes]

    def finalize_datasource_delete(self, *, namespace: str, datasource_id: str) -> bool:
        response = self._call(
            lambda: self._stub.FinalizeDatasourceDelete(
                worker_runtime_pb2.WorkerFinalizeDatasourceDeleteRequest(namespace=namespace, datasource_id=datasource_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return response.deleted

    def telegram_enabled(self) -> bool:
        response = self._call(lambda: self._stub.GetTelegramSettings(common_pb2.EmptyRequest(), timeout=self._timeout_seconds, metadata=self._metadata()))
        return response.enabled

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Mapping[str, object]] | None = None,
    ) -> bool:
        response = self._call(
            lambda: self._stub.SendEmail(
                worker_runtime_pb2.WorkerSendEmailRequest(
                    to=to,
                    subject=subject,
                    body=body,
                    attachments=_serialize_attachments(attachments or []),
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return response.value

    def send_telegram(
        self,
        *,
        chat_id: str,
        message: str,
        bot_token: str | None = None,
        attachments: list[Mapping[str, object]] | None = None,
    ) -> bool:
        request = worker_runtime_pb2.WorkerSendTelegramRequest(
            chat_id=chat_id,
            message=message,
            attachments=_serialize_attachments(attachments or []),
        )
        if bot_token is not None:
            request.bot_token = bot_token
        response = self._call(lambda: self._stub.SendTelegram(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return response.value

    def generate_ai(
        self,
        *,
        provider: str,
        prompts: list[str],
        model: str,
        endpoint_url: str | None,
        api_key: str | None,
        options: dict[str, object],
    ) -> list[str]:
        request = worker_runtime_pb2.WorkerGenerateAIRequest(
            provider=enum_to_proto_value("AI_PROVIDER", provider),
            prompts=prompts,
            model=model,
            options=dict_to_struct(options),
        )
        if endpoint_url is not None:
            request.endpoint_url = endpoint_url
        if api_key is not None:
            request.api_key = api_key
        response = self._call(lambda: self._stub.GenerateAI(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return list(response.outputs)

    def telegram_targets(self, *, namespace: str, datasource_id: str | None = None, active_subscribers: bool = False) -> list[TelegramTarget]:
        request = worker_runtime_pb2.WorkerTelegramTargetsRequest(namespace=namespace, active_subscribers=active_subscribers)
        if datasource_id is not None:
            request.datasource_id = datasource_id
        response = self._call(lambda: self._stub.GetTelegramTargets(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return [TelegramTarget(chat_id=target.chat_id, bot_token=target.bot_token) for target in response.targets]

    def close(self) -> None:
        self._channel.close()

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return ((_TOKEN_METADATA_KEY, self._token),)

    def _call(self, fn: Callable[[], _T]) -> _T:
        try:
            return fn()
        except grpc.RpcError as exc:
            raise _rpc_error_from_grpc_error(exc, target=self._target) from exc

    def _call_registration(self, fn: Callable[[], _T]) -> _T:
        deadline = time.monotonic() + self._registration_retry_seconds
        while True:
            try:
                return self._call(fn)
            except BackendWorkerRpcError as exc:
                if time.monotonic() >= deadline or exc.error_code not in {"UNAVAILABLE", "DEADLINE_EXCEEDED"}:
                    raise
                time.sleep(1.0)


def _rpc_error_from_grpc_error(exc: grpc.RpcError, *, target: str) -> BackendWorkerRpcError:
    code = exc.code()
    details = exc.details() or f"Backend worker gRPC call to {target} failed"
    return BackendWorkerRpcError(
        status_code=_grpc_status_number(code),
        error=details,
        error_code=code.name,
        details={},
    )


def _grpc_status_number(code: grpc.StatusCode) -> int:
    value = code.value
    if isinstance(value, tuple) and value and isinstance(value[0], int):
        return value[0]
    return 0


def _worker(worker_id: str) -> common_pb2.RuntimeWorkerRequest:
    return common_pb2.RuntimeWorkerRequest(worker_id=worker_id)


def _optional_str(message: Any, field: str) -> str | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_bool(message: Any, field: str) -> bool | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_timestamp_iso(message: Any, field: str) -> str | None:
    value = optional_timestamp_to_datetime(message, field)
    return value.isoformat() if value is not None else None


def _optional_proto_enum_name(message: Any, field: str, enum_type: Any, prefix: str) -> str | None:
    if not message.HasField(field):
        return None
    return proto_value_to_enum_name(enum_type, prefix, getattr(message, field))


def _serialize_attachments(attachments: list[Mapping[str, object]]) -> list[common_pb2.NotificationAttachment]:
    serialized: list[common_pb2.NotificationAttachment] = []
    for attachment in attachments:
        content = attachment.get("content")
        if not isinstance(content, bytes):
            raise RuntimeError(f"Notification attachment content must be bytes: {attachment!r}")
        serialized.append(
            common_pb2.NotificationAttachment(
                filename=_required_mapping_str(attachment, "filename"),
                content_base64=base64.b64encode(content).decode("ascii"),
                content_type=str(attachment.get("content_type") or "text/plain"),
            )
        )
    return serialized


def _required_mapping_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Payload missing string {key}: {payload!r}")
    return value


def _required_mapping_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"Payload missing boolean {key}: {payload!r}")
    return value


def _required_mapping_dict(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Payload missing object {key}: {payload!r}")
    return value


def _compute_response_envelope(
    *,
    kind: str,
    request_id: str,
    status: str,
    response_json: dict[str, object],
    error_message: str | None = None,
) -> compute_pb2.ComputeResponseEnvelope:
    envelope = compute_pb2.ComputeResponseEnvelope(
        kind=enum_to_proto_value("COMPUTE_REQUEST_KIND", kind),
        version=1,
        correlation_id=request_id,
        status=enum_to_proto_value("COMPUTE_REQUEST_STATUS", status),
    )
    envelope.payload.CopyFrom(dict_to_struct(response_json))
    envelope.response.dynamic_response.CopyFrom(dict_to_struct(response_json))
    if error_message is not None:
        envelope.error_message = error_message
    return envelope


def client_from_env() -> WorkerInternalApiClient:
    return WorkerInternalApiClient(
        target=_required_env("INTERNAL_GRPC_TARGET"),
        token=_required_env("INTERNAL_API_TOKEN"),
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be configured for the worker runtime")
    return value.strip()
