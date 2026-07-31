from __future__ import annotations

import base64
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

import grpc
from google.protobuf import json_format, struct_pb2, timestamp_pb2

from dataforge_protocol import analysis_pb2, common_pb2, compute_pb2, datasource_pb2, enums_pb2, worker_runtime_pb2, worker_runtime_pb2_grpc

_TOKEN_METADATA_KEY = "x-internal-token"
_T = TypeVar("_T")


def dict_to_struct(payload: dict[str, object] | None) -> struct_pb2.Struct:
    return json_format.ParseDict(payload or {}, struct_pb2.Struct())


def struct_to_dict(payload: struct_pb2.Struct) -> dict[str, object]:
    decoded = json_format.MessageToDict(payload, preserving_proto_field_name=True)
    if not isinstance(decoded, dict):
        raise ValueError("gRPC JSON payload must decode to an object")
    return cast(dict[str, object], decoded)


def optional_struct_to_dict(message: Any, field: str) -> dict[str, object] | None:
    if not message.HasField(field):
        return None
    return struct_to_dict(getattr(message, field))


def datetime_to_timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def optional_timestamp_to_datetime(message: Any, field: str) -> datetime | None:
    if not message.HasField(field):
        return None
    return getattr(message, field).ToDatetime()


def enum_to_proto_value(prefix: str, value: str) -> Any:
    return getattr(enums_pb2, f"{prefix}_{value.upper()}")


def proto_value_to_enum_name(enum_type: Any, prefix: str, value: int) -> str:
    enum_name = enum_type.Name(value)
    suffix = enum_name.removeprefix(f"{prefix}_")
    if suffix == "UNSPECIFIED" or suffix == enum_name:
        raise ValueError(f"Unsupported {prefix} enum value: {enum_name}")
    return suffix.lower()


@dataclass(frozen=True)
class ClaimedBuildJob:
    job_id: str
    build_id: str
    namespace: str
    claim_token: str
    lease_generation: int
    lease_expires_at: datetime
    attempt: int
    lease_ttl_seconds: int


@dataclass(frozen=True)
class StartedBuildRun:
    id: str
    namespace: str
    analysis_id: str
    analysis_name: str
    analysis_pipeline: analysis_pb2.AnalysisPipelinePayload
    tab_id: str | None
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
    kind: enums_pb2.ComputeRequestKind
    command_envelope: compute_pb2.ComputeCommandEnvelope
    worker_id: str
    claim_token: str
    lease_generation: int
    lease_expires_at: datetime
    attempt: int
    lease_ttl_seconds: int


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


class BuildJobLeaseLost(RuntimeError):
    pass


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
        response = self._call(
            lambda: self._stub.ClaimBuildJob(
                common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        if not response.HasField("job"):
            return None
        lease_expires_at = optional_timestamp_to_datetime(response.job, "lease_expires_at")
        if lease_expires_at is None:
            raise ValueError(f"Claimed build job {response.job.job_id} has no lease expiry")
        if lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        return ClaimedBuildJob(
            job_id=response.job.job_id,
            build_id=response.job.build_id,
            namespace=response.job.namespace,
            claim_token=response.job.claim_token,
            lease_generation=response.job.lease_generation,
            lease_expires_at=lease_expires_at,
            attempt=response.job.attempt,
            lease_ttl_seconds=response.job.lease_ttl_seconds,
        )

    def renew_build_job_lease(
        self,
        *,
        job_id: str,
        namespace: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        timeout_seconds: float,
    ) -> int | None:
        response = self._call(
            lambda: self._stub.RenewBuildJobLease(
                worker_runtime_pb2.WorkerBuildJobClaimRequest(
                    job_id=job_id,
                    namespace=namespace,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                    worker_id=worker_id,
                ),
                timeout=min(self._timeout_seconds, timeout_seconds),
                metadata=self._metadata(),
            )
        )
        if not response.renewed:
            return None
        if not response.HasField("lease_ttl_seconds"):
            raise ValueError(f"Renewed build job {job_id} has no lease TTL")
        return int(response.lease_ttl_seconds)

    def claim_compute_request(self, *, worker_id: str) -> ClaimedComputeRequest | None:
        response = self._call(lambda: self._stub.ClaimComputeRequest(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata()))
        if not response.HasField("request"):
            return None
        command = response.request.command
        lease_expires_at = optional_timestamp_to_datetime(response.request, "lease_expires_at")
        if lease_expires_at is None:
            raise ValueError(f"Claimed compute request {response.request.id} has no lease expiry")
        if lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        return ClaimedComputeRequest(
            id=response.request.id,
            namespace=response.request.namespace,
            kind=command.kind,
            command_envelope=command,
            worker_id=worker_id,
            claim_token=response.request.claim_token,
            lease_generation=response.request.lease_generation,
            lease_expires_at=lease_expires_at,
            attempt=response.request.attempt,
            lease_ttl_seconds=response.request.lease_ttl_seconds,
        )

    def renew_compute_request_lease(
        self,
        *,
        request_id: str,
        namespace: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        timeout_seconds: float,
    ) -> int | None:
        response = self._call(
            lambda: self._stub.RenewComputeRequestLease(
                worker_runtime_pb2.WorkerComputeRequestClaimRequest(
                    request_id=request_id,
                    namespace=namespace,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                ),
                timeout=min(self._timeout_seconds, timeout_seconds),
                metadata=self._metadata(),
            )
        )
        if not response.renewed:
            return None
        if not response.HasField("lease_ttl_seconds"):
            raise ValueError(f"Renewed compute request {request_id} has no lease TTL")
        return int(response.lease_ttl_seconds)

    def complete_compute_request(
        self,
        *,
        namespace: str,
        request_id: str,
        kind: enums_pb2.ComputeRequestKind,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        response: compute_pb2.ComputeResponse,
        artifact_path: str | None = None,
        artifact_name: str | None = None,
        artifact_content_type: str | None = None,
    ) -> None:
        request = worker_runtime_pb2.WorkerCompleteComputeRequestRequest(
            namespace=namespace,
            request_id=request_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            response_envelope=_compute_response_envelope(
                kind=kind,
                request_id=request_id,
                status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
                response=response,
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
        kind: enums_pb2.ComputeRequestKind,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        error_message: str,
        error: compute_pb2.ComputeErrorResult,
    ) -> None:
        self._call(
            lambda: self._stub.FailComputeRequest(
                worker_runtime_pb2.WorkerFailComputeRequestRequest(
                    namespace=namespace,
                    request_id=request_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                    error_message=error_message,
                    response_envelope=_compute_response_envelope(
                        kind=kind,
                        request_id=request_id,
                        status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
                        response=compute_pb2.ComputeResponse(error=error),
                        error_message=error_message,
                    ),
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def execute_datasource_request(
        self,
        *,
        namespace: str,
        kind: enums_pb2.ComputeRequestKind,
        command: datasource_pb2.DatasourceCommand,
        request_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
    ) -> datasource_pb2.DatasourceResult:
        response = self._call(
            lambda: self._stub.ExecuteDatasourceRequest(
                worker_runtime_pb2.WorkerExecuteDatasourceRequest(
                    namespace=namespace,
                    kind=kind,
                    command=command,
                    request_id=request_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return response.result

    def schedule_ingest_datasource(
        self,
        *,
        namespace: str,
        datasource_id: str,
        job_id: str,
        build_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
    ) -> datasource_pb2.DataSourceRecord:
        response = self._call(
            lambda: self._stub.ScheduleIngestDatasource(
                worker_runtime_pb2.WorkerScheduleIngestDatasourceRequest(
                    namespace=namespace,
                    datasource_id=datasource_id,
                    job_id=job_id,
                    build_id=build_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return response.datasource

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
            schema_cache=_schema_info_payload(response.schema_info) if response.HasField("schema_info") else None,
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

    def update_build_result(
        self,
        *,
        namespace: str,
        build_id: str,
        job_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        result_json: dict[str, object],
    ) -> None:
        try:
            self._call(
                lambda: self._stub.UpdateBuildResult(
                    worker_runtime_pb2.WorkerUpdateBuildResultRequest(
                        namespace=namespace,
                        build_id=build_id,
                        job_id=job_id,
                        worker_id=worker_id,
                        claim_token=claim_token,
                        lease_generation=lease_generation,
                        result=dict_to_struct(result_json),
                    ),
                    timeout=self._timeout_seconds,
                    metadata=self._metadata(),
                )
            )
        except BackendWorkerRpcError as exc:
            if exc.error_code == "FAILED_PRECONDITION":
                raise BuildJobLeaseLost(f"Build job {job_id} result update was rejected because its lease is no longer active") from exc
            raise

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
        job_id: str | None,
        build_id: str | None,
        worker_id: str | None,
        claim_token: str | None,
        lease_generation: int | None,
        build_result_json: dict[str, object] | None,
        notification_deliveries: Sequence[Mapping[str, object]],
    ) -> DatasourceMetadata:
        request = worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest(
            namespace=namespace,
            result_id=result_id,
            name=name,
            source_type=enum_to_proto_value("DATA_SOURCE_TYPE", source_type),
            config=dict_to_struct(config),
            schema_info=_schema_info_proto(schema_cache),
            keep_schema_cache=keep_schema_cache,
            notification_delivery=[_notification_delivery_proto(delivery) for delivery in notification_deliveries],
        )
        claim_values = (job_id, build_id, worker_id, claim_token, lease_generation, build_result_json)
        if any(value is not None for value in claim_values):
            if any(value is None for value in claim_values):
                raise ValueError("Output publication claim fields must be provided together")
            request.job_id = cast(str, job_id)
            request.build_id = cast(str, build_id)
            request.worker_id = cast(str, worker_id)
            request.claim_token = cast(str, claim_token)
            request.lease_generation = cast(int, lease_generation)
            request.build_result.CopyFrom(dict_to_struct(cast(dict[str, object], build_result_json)))
        if analysis_id is not None:
            request.analysis_id = analysis_id
        if is_hidden is not None:
            request.is_hidden = is_hidden
        try:
            response = self._call(lambda: self._stub.UpsertOutputDatasource(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        except BackendWorkerRpcError as exc:
            if exc.error_code == "FAILED_PRECONDITION" and job_id is not None:
                raise BuildJobLeaseLost(f"Build job {job_id} output publication was rejected because its lease is no longer active") from exc
            raise
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
            execution_entry=[_engine_run_execution_entry_proto(entry) for entry in execution_entries or []],
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
            request.timing_by_key.update({str(key): float(value) for key, value in step_timings.items()})
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
                    merge_result=merge_result_json,
                    update=_engine_run_update_proto(fields),
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

    def fail_build_job(self, *, job_id: str, build_id: str, namespace: str, worker_id: str, claim_token: str, lease_generation: int, error: str) -> bool:
        response = self._call(
            lambda: self._stub.FailBuildJob(
                worker_runtime_pb2.WorkerFailBuildJobRequest(
                    job_id=job_id,
                    namespace=namespace,
                    error=error,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                    worker_id=worker_id,
                    build_id=build_id,
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return bool(response.value)

    def finalize_build_job(self, *, job_id: str, build_id: str, namespace: str, worker_id: str, claim_token: str, lease_generation: int) -> bool:
        response = self._call(
            lambda: self._stub.FinalizeBuildJob(
                worker_runtime_pb2.WorkerFinalizeBuildJobRequest(
                    job_id=job_id,
                    build_id=build_id,
                    namespace=namespace,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                    worker_id=worker_id,
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return bool(response.value)

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
        job_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        event: dict[str, object],
        resource_config_json: dict[str, object] | None = None,
    ) -> int | None:
        request = worker_runtime_pb2.WorkerPersistBuildEventRequest(
            namespace=namespace,
            build_id=build_id,
            job_id=job_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            build_event=_build_event_proto(namespace, event),
        )
        if resource_config_json is not None:
            request.build_resource_config.CopyFrom(_build_resource_config_proto(resource_config_json))
        response = self._call(lambda: self._stub.PersistBuildEvent(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return int(response.sequence) if response.HasField("sequence") else None

    def start_build_run(self, *, namespace: str, build_id: str, job_id: str, worker_id: str, claim_token: str, lease_generation: int) -> StartedBuildRun | None:
        response = self._call(
            lambda: self._stub.StartBuildRun(
                worker_runtime_pb2.WorkerStartBuildRunRequest(
                    namespace=namespace,
                    build_id=build_id,
                    job_id=job_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                ),
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
            analysis_pipeline=run.analysis_pipeline,
            tab_id=_optional_str(run, "tab_id"),
            starter_json=_build_starter_payload(run.build_starter),
            resource_config_json=_build_resource_config_payload(run.build_resource_config) if run.HasField("build_resource_config") else None,
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
                    engine_status=[_engine_status_result_proto(status) for status in statuses],
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
        namespace: str,
        to: str,
        subject: str,
        body: str,
        attachments: list[Mapping[str, object]] | None = None,
    ) -> bool:
        response = self._call(
            lambda: self._stub.SendEmail(
                worker_runtime_pb2.WorkerSendEmailRequest(
                    namespace=namespace,
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
        namespace: str,
        chat_id: str,
        message: str,
        bot_token: str | None = None,
        attachments: list[Mapping[str, object]] | None = None,
    ) -> bool:
        request = worker_runtime_pb2.WorkerSendTelegramRequest(
            namespace=namespace,
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
    return {
        grpc.StatusCode.OK: 200,
        grpc.StatusCode.CANCELLED: 499,
        grpc.StatusCode.UNKNOWN: 500,
        grpc.StatusCode.INVALID_ARGUMENT: 400,
        grpc.StatusCode.DEADLINE_EXCEEDED: 504,
        grpc.StatusCode.NOT_FOUND: 404,
        grpc.StatusCode.ALREADY_EXISTS: 409,
        grpc.StatusCode.PERMISSION_DENIED: 403,
        grpc.StatusCode.RESOURCE_EXHAUSTED: 429,
        grpc.StatusCode.FAILED_PRECONDITION: 412,
        grpc.StatusCode.ABORTED: 409,
        grpc.StatusCode.OUT_OF_RANGE: 400,
        grpc.StatusCode.UNIMPLEMENTED: 501,
        grpc.StatusCode.INTERNAL: 500,
        grpc.StatusCode.UNAVAILABLE: 503,
        grpc.StatusCode.DATA_LOSS: 500,
        grpc.StatusCode.UNAUTHENTICATED: 401,
    }[code]


def _worker(worker_id: str) -> common_pb2.RuntimeWorkerRequest:
    return common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2)


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


def _notification_delivery_proto(delivery: Mapping[str, object]) -> worker_runtime_pb2.WorkerNotificationDelivery:
    method = delivery.get("method")
    if method == "email":
        return worker_runtime_pb2.WorkerNotificationDelivery(
            email=worker_runtime_pb2.WorkerEmailDelivery(
                to=_required_mapping_str(delivery, "recipient"),
                subject=_required_mapping_str(delivery, "subject"),
                body=str(delivery.get("body", "")),
            )
        )
    if method == "telegram":
        telegram = worker_runtime_pb2.WorkerTelegramDelivery(
            chat_id=_required_mapping_str(delivery, "recipient"),
            message=_required_mapping_str(delivery, "message"),
        )
        token = delivery.get("bot_token")
        if isinstance(token, str) and token:
            telegram.bot_token = token
        return worker_runtime_pb2.WorkerNotificationDelivery(telegram=telegram)
    raise ValueError(f"Unsupported notification delivery method: {method!r}")


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


def _mapping_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"Payload missing string {key}: {payload!r}")
    return value


def _required_mapping_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"Payload missing boolean {key}: {payload!r}")
    return value


def _required_mapping_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"Payload missing integer {key}: {payload!r}")
    return value


def _optional_mapping_float(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise RuntimeError(f"Payload field {key} must be numeric: {payload!r}")
    return float(value)


def _optional_mapping_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Payload field {key} must be a string: {payload!r}")
    return value


def _engine_run_entry_step_type(payload: Mapping[str, object]) -> enums_pb2.StepType | None:
    value = payload.get("step_type")
    if value is None:
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            value = metadata.get("step_type")
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Engine run execution entry step_type must be a string: {payload!r}")
    return cast(enums_pb2.StepType, enum_to_proto_value("STEP_TYPE", value))


def _engine_run_execution_entry_proto(payload: Mapping[str, object]) -> compute_pb2.EngineRunExecutionEntry:
    entry = compute_pb2.EngineRunExecutionEntry(
        key=_required_mapping_str(payload, "key"),
        label=_required_mapping_str(payload, "label"),
        category=enum_to_proto_value("ENGINE_RUN_EXECUTION_CATEGORY", _required_mapping_str(payload, "category")),
        order=_required_mapping_int(payload, "order"),
    )
    duration_ms = _optional_mapping_float(payload, "duration_ms")
    if duration_ms is not None:
        entry.duration_ms = duration_ms
    share_pct = _optional_mapping_float(payload, "share_pct")
    if share_pct is not None:
        entry.share_pct = share_pct
    optimized_plan = _optional_mapping_str(payload, "optimized_plan")
    if optimized_plan is not None:
        entry.optimized_plan = optimized_plan
    unoptimized_plan = _optional_mapping_str(payload, "unoptimized_plan")
    if unoptimized_plan is not None:
        entry.unoptimized_plan = unoptimized_plan
    step_type = _engine_run_entry_step_type(payload)
    if step_type is not None:
        entry.step_type = step_type
    return entry


def _datetime_field(value: object, *, key: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise RuntimeError(f"Payload field {key} must be an ISO datetime string: {value!r}")


def _mapping_dict_field(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Payload field {key} must be an object: {payload!r}")
    return value


def _engine_resource_config_proto(payload: Mapping[str, object]) -> compute_pb2.EngineResourceConfig:
    config = compute_pb2.EngineResourceConfig()
    for field in ("max_threads", "max_memory_mb", "streaming_chunk_size"):
        value = payload.get(field)
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                raise RuntimeError(f"Engine resource field {field} must be an integer: {payload!r}")
            setattr(config, field, value)
    return config


def _engine_defaults_proto(payload: Mapping[str, object]) -> compute_pb2.EngineDefaults:
    return compute_pb2.EngineDefaults(
        max_threads=_required_mapping_int(payload, "max_threads"),
        max_memory_mb=_required_mapping_int(payload, "max_memory_mb"),
        streaming_chunk_size=_required_mapping_int(payload, "streaming_chunk_size"),
    )


def _engine_status_result_proto(payload: Mapping[str, object]) -> compute_pb2.EngineStatusResult:
    status = compute_pb2.EngineStatusResult(
        analysis_id=_mapping_str(payload, "analysis_id"),
        resource_id=_required_mapping_str(payload, "resource_id"),
        status=enum_to_proto_value("ENGINE_STATUS", _required_mapping_str(payload, "status")),
    )
    process_id = payload.get("process_id")
    if process_id is not None:
        if not isinstance(process_id, int) or isinstance(process_id, bool):
            raise RuntimeError(f"Engine status process_id must be an integer: {payload!r}")
        status.process_id = process_id
    for field in ("last_activity", "current_job_id", "datasource_id", "build_id", "current_build_id", "current_engine_run_id"):
        value = payload.get(field)
        if value is not None:
            if not isinstance(value, str):
                raise RuntimeError(f"Engine status field {field} must be a string: {payload!r}")
            setattr(status, field, value)
    resource_config = payload.get("resource_config")
    if isinstance(resource_config, Mapping):
        status.resource_config.CopyFrom(_engine_resource_config_proto(resource_config))
    effective_resources = payload.get("effective_resources")
    if isinstance(effective_resources, Mapping):
        status.effective_resources.CopyFrom(_engine_resource_config_proto(effective_resources))
    defaults = payload.get("defaults")
    if isinstance(defaults, Mapping):
        status.defaults.CopyFrom(_engine_defaults_proto(defaults))
    scope = payload.get("scope")
    if scope is not None:
        if not isinstance(scope, str):
            raise RuntimeError(f"Engine status scope must be a string: {payload!r}")
        status.scope = enum_to_proto_value("ENGINE_SCOPE", scope)
    reuse_policy = payload.get("reuse_policy")
    if reuse_policy is not None:
        if not isinstance(reuse_policy, str):
            raise RuntimeError(f"Engine status reuse_policy must be a string: {payload!r}")
        status.reuse_policy = enum_to_proto_value("ENGINE_REUSE_POLICY", reuse_policy)
    return status


def _engine_run_update_proto(fields: Mapping[str, object]) -> worker_runtime_pb2.WorkerEngineRunUpdateFields:
    update = worker_runtime_pb2.WorkerEngineRunUpdateFields()
    if "analysis_id" in fields:
        update.analysis_id = _required_mapping_str(fields, "analysis_id")
    if "datasource_id" in fields:
        update.datasource_id = _required_mapping_str(fields, "datasource_id")
    if "kind" in fields:
        update.kind = enum_to_proto_value("ENGINE_RUN_KIND", _required_mapping_str(fields, "kind"))
    if "status" in fields:
        update.status = enum_to_proto_value("ENGINE_RUN_STATUS", _required_mapping_str(fields, "status"))
    if "request_json" in fields:
        update.request_json.CopyFrom(dict_to_struct(_mapping_dict_field(fields, "request_json")))
    if "result_json" in fields:
        update.result_json.CopyFrom(dict_to_struct(_mapping_dict_field(fields, "result_json")))
    if "error_message" in fields:
        update.error_message = _required_mapping_str(fields, "error_message")
    if "completed_at" in fields:
        update.completed_at.CopyFrom(datetime_to_timestamp(_datetime_field(fields["completed_at"], key="completed_at")))
    if "duration_ms" in fields:
        update.duration_ms = _required_mapping_int(fields, "duration_ms")
    if "step_timings" in fields:
        step_timings = _mapping_dict_field(fields, "step_timings")
        update.step_timings.SetInParent()
        for key, value in step_timings.items():
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise RuntimeError(f"Step timing value must be numeric: {fields!r}")
            update.step_timings.values[str(key)] = float(value)
    if "query_plan" in fields:
        update.query_plan = _required_mapping_str(fields, "query_plan")
    if "execution_entries" in fields:
        entries = fields.get("execution_entries")
        if not isinstance(entries, list):
            raise RuntimeError(f"Payload field execution_entries must be a list: {fields!r}")
        update.execution_entries.SetInParent()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise RuntimeError(f"Execution entry must be an object: {entry!r}")
            update.execution_entries.entries.append(_engine_run_execution_entry_proto(entry))
    if "progress" in fields:
        progress = _optional_mapping_float(fields, "progress")
        if progress is None:
            raise RuntimeError(f"Payload field progress must be numeric: {fields!r}")
        update.progress = progress
    if "current_step" in fields:
        value = fields.get("current_step")
        if value is None:
            update.clear_current_step = True
        elif isinstance(value, str) and value:
            update.current_step = value
        else:
            raise RuntimeError(f"Payload field current_step must be a string or null: {fields!r}")
    if "triggered_by" in fields:
        update.triggered_by = _required_mapping_str(fields, "triggered_by")
    return update


def _required_mapping_dict(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Payload missing object {key}: {payload!r}")
    return value


def _enum_name_from_token(enum_descriptor: Any, value: object) -> object:
    if not isinstance(value, str) or value in enum_descriptor.values_by_name:
        return value
    prefixed_value = f"{_enum_prefix(enum_descriptor)}_{value}"
    if prefixed_value in enum_descriptor.values_by_name:
        return prefixed_value
    for enum_value in enum_descriptor.values:
        options = enum_value.GetOptions()
        if not options.HasExtension(cast(Any, enums_pb2.dataforge_token)):
            continue
        token = options.Extensions[cast(Any, enums_pb2.dataforge_token)]
        if token == value:
            return enum_value.name
    return value


def _enum_prefix(enum_descriptor: Any) -> str:
    chars: list[str] = []
    for index, char in enumerate(enum_descriptor.name):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.upper())
    return "".join(chars)


def _enum_number_from_token(enum_descriptor: Any, value: object, *, field_name: str) -> Any:
    enum_name = _enum_name_from_token(enum_descriptor, value)
    if not isinstance(enum_name, str):
        raise ValueError(f"{field_name} must be a string enum token")
    try:
        return cast(int, enum_descriptor.values_by_name[enum_name].number)
    except KeyError as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _optional_payload_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _build_resource_config_proto(payload: Mapping[str, object]) -> compute_pb2.BuildResourceConfigSummary:
    config = compute_pb2.BuildResourceConfigSummary()
    for key in ("max_threads", "max_memory_mb", "streaming_chunk_size"):
        value = _optional_payload_int(payload, key)
        if value is not None:
            setattr(config, key, value)
    return config


def _build_resource_config_payload(config: compute_pb2.BuildResourceConfigSummary) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("max_threads", "max_memory_mb", "streaming_chunk_size"):
        if config.HasField(key):
            payload[key] = getattr(config, key)
    return payload


def _build_starter_payload(starter: compute_pb2.BuildStarter) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("user_id", "display_name", "email", "triggered_by"):
        if starter.HasField(key):
            payload[key] = getattr(starter, key)
    return payload


def _schema_info_proto(payload: Mapping[str, object]) -> datasource_pb2.SchemaInfo:
    schema = datasource_pb2.SchemaInfo()
    raw_columns = payload.get("columns")
    if raw_columns is not None:
        if not isinstance(raw_columns, list):
            raise ValueError("schema columns must be a list")
        for raw_column in raw_columns:
            if not isinstance(raw_column, Mapping):
                raise ValueError("schema column must be an object")
            name = raw_column.get("name")
            dtype = raw_column.get("dtype")
            nullable = raw_column.get("nullable")
            if not isinstance(name, str) or not isinstance(dtype, str) or not isinstance(nullable, bool):
                raise ValueError("schema column requires name, dtype, and nullable")
            column = schema.columns.add(name=name, dtype=dtype, nullable=nullable)
            for key in ("sample_value", "description"):
                value = raw_column.get(key)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(f"schema column {key} must be a string")
                    setattr(column, key, value)
    row_count = _optional_payload_int(payload, "row_count")
    if row_count is not None:
        schema.row_count = row_count
    raw_sheet_names = payload.get("sheet_names")
    if raw_sheet_names is not None:
        if not isinstance(raw_sheet_names, list) or not all(isinstance(item, str) for item in raw_sheet_names):
            raise ValueError("schema sheet_names must be a list of strings")
        schema.sheet_names.extend(raw_sheet_names)
    return schema


def _schema_info_payload(value: datasource_pb2.SchemaInfo) -> dict[str, object]:
    columns: list[dict[str, object]] = []
    for column in value.columns:
        column_payload: dict[str, object] = {
            "name": column.name,
            "dtype": column.dtype,
            "nullable": column.nullable,
        }
        if column.HasField("sample_value"):
            column_payload["sample_value"] = column.sample_value
        if column.HasField("description"):
            column_payload["description"] = column.description
        columns.append(column_payload)

    payload: dict[str, object] = {}
    if columns:
        payload["columns"] = columns
    if value.HasField("row_count"):
        payload["row_count"] = value.row_count
    if value.sheet_names:
        payload["sheet_names"] = list(value.sheet_names)
    return payload


def _required_event_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"build event {key} is required")
    return value


def _optional_event_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"build event {key} must be a string")
    return value


def _optional_event_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"build event {key} must be an integer")
    return value


def _required_event_int(payload: Mapping[str, object], key: str) -> int:
    value = _optional_event_int(payload, key)
    if value is None:
        raise ValueError(f"build event {key} is required")
    return value


def _optional_event_float(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"build event {key} must be numeric")
    return float(value)


def _required_event_float(payload: Mapping[str, object], key: str) -> float:
    value = _optional_event_float(payload, key)
    if value is None:
        raise ValueError(f"build event {key} is required")
    return value


def _event_datetime(payload: Mapping[str, object], key: str) -> datetime:
    value = payload.get(key)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"build event {key} is required")


def _build_step_kind_proto(step_type: object) -> compute_pb2.BuildStepKind:
    if not isinstance(step_type, str) or not step_type.strip():
        raise ValueError("build step event step_type is required")
    message = compute_pb2.BuildStepKind()
    try:
        message.pipeline = _enum_number_from_token(enums_pb2.StepType.DESCRIPTOR, step_type, field_name="step_type")
        return message
    except ValueError:
        category = _enum_number_from_token(enums_pb2.EngineRunExecutionCategory.DESCRIPTOR, step_type, field_name="step_type")
        if category not in {enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_READ, enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_WRITE}:
            raise ValueError(f"Unsupported build execution category for protocol step event: {step_type!r}") from None
        message.execution_category = category
        return message


def _build_tab_result_proto(payload: Mapping[str, object]) -> compute_pb2.BuildTabResult:
    message = compute_pb2.BuildTabResult(
        tab_id=_required_event_str(payload, "tab_id"),
        tab_name=_required_event_str(payload, "tab_name"),
    )
    message.status = _enum_number_from_token(enums_pb2.BuildTabStatus.DESCRIPTOR, payload.get("status"), field_name="status")
    for field in ("output_id", "output_name", "error"):
        value = _optional_event_str(payload, field)
        if value is not None:
            setattr(message, field, value)
    return message


def _build_terminal_event_proto(payload: Mapping[str, object]) -> compute_pb2.BuildTerminalEvent:
    message = compute_pb2.BuildTerminalEvent(
        progress=_required_event_float(payload, "progress"),
        elapsed_ms=_required_event_int(payload, "elapsed_ms"),
        total_steps=_required_event_int(payload, "total_steps"),
        tabs_built=_required_event_int(payload, "tabs_built"),
        duration_ms=_required_event_int(payload, "duration_ms"),
    )
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("build terminal event results must be a list")
    for result in results:
        if not isinstance(result, Mapping):
            raise ValueError("build terminal event results must be objects")
        message.results.append(_build_tab_result_proto(result))
    error = _optional_event_str(payload, "error")
    if error is not None:
        message.error = error
    if payload.get("cancelled_at") is not None:
        message.cancelled_at.CopyFrom(datetime_to_timestamp(_event_datetime(payload, "cancelled_at")))
    cancelled_by = _optional_event_str(payload, "cancelled_by")
    if cancelled_by is not None:
        message.cancelled_by = cancelled_by
    return message


def _build_event_proto(namespace: str, payload: Mapping[str, object]) -> compute_pb2.BuildEvent:
    context = compute_pb2.BuildEventContext(
        build_id=_required_event_str(payload, "build_id"),
        analysis_id=_required_event_str(payload, "analysis_id"),
        emitted_at=datetime_to_timestamp(_event_datetime(payload, "emitted_at")),
    )
    sequence = _optional_event_int(payload, "sequence")
    if sequence is not None:
        context.sequence = sequence
    current_kind = payload.get("current_kind")
    if current_kind is not None:
        context.current_kind = _enum_number_from_token(enums_pb2.EngineRunKind.DESCRIPTOR, current_kind, field_name="current_kind")
    for field in ("current_datasource_id", "tab_id", "tab_name", "current_output_id", "current_output_name", "engine_run_id"):
        value = _optional_event_str(payload, field)
        if value is not None:
            setattr(context, field, value)

    message = compute_pb2.BuildEvent(context=context, namespace=namespace)
    match _required_event_str(payload, "type"):
        case "plan":
            message.plan.optimized_plan = _required_event_str(payload, "optimized_plan")
            message.plan.unoptimized_plan = _required_event_str(payload, "unoptimized_plan")
        case "step_start":
            message.step_started.build_step_index = _required_event_int(payload, "build_step_index")
            message.step_started.step_index = _required_event_int(payload, "step_index")
            message.step_started.step_id = _required_event_str(payload, "step_id")
            message.step_started.step_name = _required_event_str(payload, "step_name")
            message.step_started.total_steps = _required_event_int(payload, "total_steps")
            message.step_started.step_kind.CopyFrom(_build_step_kind_proto(payload.get("step_type")))
        case "step_complete":
            message.step_completed.build_step_index = _required_event_int(payload, "build_step_index")
            message.step_completed.step_index = _required_event_int(payload, "step_index")
            message.step_completed.step_id = _required_event_str(payload, "step_id")
            message.step_completed.step_name = _required_event_str(payload, "step_name")
            message.step_completed.duration_ms = _required_event_int(payload, "duration_ms")
            row_count = _optional_event_int(payload, "row_count")
            if row_count is not None:
                message.step_completed.row_count = row_count
            message.step_completed.total_steps = _required_event_int(payload, "total_steps")
            message.step_completed.step_kind.CopyFrom(_build_step_kind_proto(payload.get("step_type")))
        case "step_failed":
            message.step_failed.build_step_index = _required_event_int(payload, "build_step_index")
            message.step_failed.step_index = _required_event_int(payload, "step_index")
            message.step_failed.step_id = _required_event_str(payload, "step_id")
            message.step_failed.step_name = _required_event_str(payload, "step_name")
            message.step_failed.error = _required_event_str(payload, "error")
            message.step_failed.total_steps = _required_event_int(payload, "total_steps")
            message.step_failed.step_kind.CopyFrom(_build_step_kind_proto(payload.get("step_type")))
        case "progress":
            message.progress.progress = _required_event_float(payload, "progress")
            message.progress.elapsed_ms = _required_event_int(payload, "elapsed_ms")
            estimated_remaining_ms = _optional_event_int(payload, "estimated_remaining_ms")
            if estimated_remaining_ms is not None:
                message.progress.estimated_remaining_ms = estimated_remaining_ms
            current_step = _optional_event_str(payload, "current_step")
            if current_step is not None:
                message.progress.current_step = current_step
            current_step_index = _optional_event_int(payload, "current_step_index")
            if current_step_index is not None:
                message.progress.current_step_index = current_step_index
            message.progress.total_steps = _required_event_int(payload, "total_steps")
        case "resources":
            message.resources.cpu_percent = _required_event_float(payload, "cpu_percent")
            message.resources.memory_mb = _required_event_float(payload, "memory_mb")
            memory_limit_mb = _optional_event_float(payload, "memory_limit_mb")
            if memory_limit_mb is not None:
                message.resources.memory_limit_mb = memory_limit_mb
            message.resources.active_threads = _required_event_int(payload, "active_threads")
            max_threads = _optional_event_int(payload, "max_threads")
            if max_threads is not None:
                message.resources.max_threads = max_threads
        case "log":
            message.log.level = _enum_number_from_token(enums_pb2.BuildLogLevel.DESCRIPTOR, payload.get("level"), field_name="level")
            message.log.message = _required_event_str(payload, "message")
            for field in ("step_name", "step_id"):
                value = _optional_event_str(payload, field)
                if value is not None:
                    setattr(message.log, field, value)
        case "complete":
            message.completed.CopyFrom(_build_terminal_event_proto(payload))
        case "failed":
            message.failed.CopyFrom(_build_terminal_event_proto(payload))
        case "cancelled":
            message.cancelled.CopyFrom(_build_terminal_event_proto(payload))
        case event_type:
            raise ValueError(f"Unsupported build event type: {event_type!r}")
    return message


def _compute_response_envelope(
    *,
    kind: enums_pb2.ComputeRequestKind,
    request_id: str,
    status: enums_pb2.ComputeRequestStatus,
    response: compute_pb2.ComputeResponse,
    error_message: str | None = None,
) -> compute_pb2.ComputeResponseEnvelope:
    envelope = compute_pb2.ComputeResponseEnvelope(
        kind=kind,
        version=1,
        correlation_id=request_id,
        status=status,
    )
    envelope.response.CopyFrom(response)
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
