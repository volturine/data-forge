from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float = 30.0, registration_retry_seconds: float = 90.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._registration_retry_seconds = registration_retry_seconds

    def register_worker(self, *, worker_id: str, kind: str, hostname: str, pid: int, capacity: int, active_jobs: int = 0) -> None:
        self._post_registration(
            "/worker/register",
            {
                "worker_id": worker_id,
                "kind": kind,
                "hostname": hostname,
                "pid": pid,
                "capacity": capacity,
                "active_jobs": active_jobs,
            },
        )

    def heartbeat_worker(self, *, worker_id: str, active_jobs: int | None = None) -> None:
        self._post("/worker/heartbeat", {"worker_id": worker_id, "active_jobs": active_jobs})

    def stop_worker(self, *, worker_id: str) -> None:
        self._post("/worker/stop", {"worker_id": worker_id})

    def claim_build_job(self, *, worker_id: str) -> ClaimedBuildJob | None:
        response = self._post("/worker/claim-build-job", {"worker_id": worker_id})
        raw_job = response.get("job")
        if raw_job is None:
            return None
        if not isinstance(raw_job, dict):
            raise RuntimeError(f"Backend worker RPC returned invalid job payload: {response!r}")
        return ClaimedBuildJob(
            job_id=_required_str(raw_job, "job_id"),
            build_id=_required_str(raw_job, "build_id"),
            namespace=_required_str(raw_job, "namespace"),
        )

    def claim_compute_request(self, *, worker_id: str) -> ClaimedComputeRequest | None:
        response = self._post("/worker/claim-compute-request", {"worker_id": worker_id})
        raw_request = response.get("request")
        if raw_request is None:
            return None
        if not isinstance(raw_request, dict):
            raise RuntimeError(f"Backend worker RPC returned invalid compute request payload: {response!r}")
        return ClaimedComputeRequest(
            id=_required_str(raw_request, "id"),
            namespace=_required_str(raw_request, "namespace"),
            kind=_required_str(raw_request, "kind"),
            request_json=_required_dict(raw_request, "request_json"),
        )

    def complete_compute_request(
        self,
        *,
        namespace: str,
        request_id: str,
        response_json: dict[str, object] | None = None,
        artifact_path: str | None = None,
        artifact_name: str | None = None,
        artifact_content_type: str | None = None,
    ) -> None:
        self._post(
            "/worker/complete-compute-request",
            {
                "namespace": namespace,
                "request_id": request_id,
                "response_json": response_json,
                "artifact_path": artifact_path,
                "artifact_name": artifact_name,
                "artifact_content_type": artifact_content_type,
            },
        )

    def fail_compute_request(
        self,
        *,
        namespace: str,
        request_id: str,
        error_message: str,
        response_json: dict[str, object],
    ) -> None:
        self._post(
            "/worker/fail-compute-request",
            {
                "namespace": namespace,
                "request_id": request_id,
                "error_message": error_message,
                "response_json": response_json,
            },
        )

    def release_compute_requests(self, *, worker_id: str) -> int:
        response = self._post("/worker/release-compute-requests", {"worker_id": worker_id})
        return _required_int(response, "released")

    def execute_datasource_request(self, *, namespace: str, kind: str, request_json: dict[str, object]) -> dict[str, object]:
        response = self._post("/worker/execute-datasource-request", {"namespace": namespace, "kind": kind, "request_json": request_json})
        return _required_dict(response, "response_json")

    def schedule_ingest_datasource(self, *, namespace: str, datasource_id: str) -> dict[str, object]:
        response = self._post("/worker/schedule-ingest-datasource", {"namespace": namespace, "datasource_id": datasource_id})
        return _required_dict(response, "response_json")

    def datasource_metadata(self, *, namespace: str, datasource_id: str) -> DatasourceMetadata:
        response = self._post("/worker/datasource-metadata", {"namespace": namespace, "datasource_id": datasource_id})
        return DatasourceMetadata(
            found=_required_bool(response, "found"),
            id=_optional_str(response, "id"),
            name=_optional_str(response, "name"),
            source_type=_optional_str(response, "source_type"),
            config=_optional_dict(response, "config"),
            schema_cache=_optional_dict(response, "schema_cache"),
            is_hidden=_optional_bool(response, "is_hidden"),
        )

    def udf_codes(self, *, namespace: str, udf_ids: list[str]) -> dict[str, str]:
        response = self._post("/worker/udf-codes", {"namespace": namespace, "udf_ids": udf_ids})
        raw_codes = response.get("codes")
        if not isinstance(raw_codes, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in raw_codes.items()):
            raise RuntimeError(f"Backend worker RPC returned invalid UDF codes payload: {response!r}")
        return dict(raw_codes)

    def analysis_name(self, *, namespace: str, analysis_id: str) -> str | None:
        response = self._post("/worker/analysis-metadata", {"namespace": namespace, "analysis_id": analysis_id})
        if not _required_bool(response, "found"):
            return None
        return _optional_str(response, "name")

    def build_cancel_status(self, *, namespace: str, build_id: str) -> tuple[bool, str | None, str | None]:
        response = self._post("/worker/build-cancel-status", {"namespace": namespace, "build_id": build_id})
        return (
            _required_bool(response, "cancelled"),
            _optional_str(response, "cancelled_at"),
            _optional_str(response, "cancelled_by"),
        )

    def update_build_result(self, *, namespace: str, build_id: str, result_json: dict[str, object]) -> None:
        self._post("/worker/update-build-result", {"namespace": namespace, "build_id": build_id, "result_json": result_json})

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
        response = self._post(
            "/worker/upsert-output-datasource",
            {
                "namespace": namespace,
                "result_id": result_id,
                "name": name,
                "source_type": source_type,
                "config": config,
                "schema_cache": schema_cache,
                "analysis_id": analysis_id,
                "is_hidden": is_hidden,
                "keep_schema_cache": keep_schema_cache,
            },
        )
        return DatasourceMetadata(
            found=True,
            id=_required_str(response, "datasource_id"),
            name=_required_str(response, "datasource_name"),
            source_type=source_type,
            config=config,
            schema_cache=schema_cache,
            is_hidden=_required_bool(response, "is_hidden"),
        )

    def list_healthchecks(self, *, namespace: str, datasource_id: str) -> list[HealthCheckSpec]:
        response = self._post("/worker/list-healthchecks", {"namespace": namespace, "datasource_id": datasource_id})
        raw_checks = response.get("checks")
        if not isinstance(raw_checks, list):
            raise RuntimeError(f"Backend worker RPC returned invalid healthcheck list: {response!r}")
        checks: list[HealthCheckSpec] = []
        for raw_check in raw_checks:
            if not isinstance(raw_check, dict):
                raise RuntimeError(f"Backend worker RPC returned invalid healthcheck item: {raw_check!r}")
            checks.append(
                HealthCheckSpec(
                    id=_required_str(raw_check, "id"),
                    name=_required_str(raw_check, "name"),
                    check_type=_required_str(raw_check, "check_type"),
                    config=_required_dict(raw_check, "config"),
                    critical=_required_bool(raw_check, "critical"),
                )
            )
        return checks

    def record_healthcheck_results(self, *, namespace: str, results: list[Mapping[str, object]]) -> int:
        response = self._post("/worker/record-healthcheck-results", {"namespace": namespace, "results": [dict(result) for result in results]})
        return _required_int(response, "recorded")

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
        response = self._post(
            "/worker/create-engine-run",
            {
                "namespace": namespace,
                "analysis_id": analysis_id,
                "datasource_id": datasource_id,
                "kind": kind,
                "status": status,
                "request_json": request_json,
                "result_json": result_json,
                "error_message": error_message,
                "created_at": created_at.isoformat() if created_at is not None else None,
                "completed_at": completed_at.isoformat() if completed_at is not None else None,
                "duration_ms": duration_ms,
                "step_timings": step_timings,
                "query_plan": query_plan,
                "execution_entries": execution_entries,
                "progress": progress,
                "current_step": current_step,
                "triggered_by": triggered_by,
            },
        )
        return _required_str(response, "id")

    def update_engine_run(
        self,
        *,
        namespace: str,
        run_id: str,
        fields: dict[str, object],
        merge_result_json: bool = True,
    ) -> str:
        response = self._post(
            "/worker/update-engine-run",
            {
                "namespace": namespace,
                "run_id": run_id,
                "fields": fields,
                "merge_result_json": merge_result_json,
            },
        )
        return _required_str(response, "id")

    def engine_run_state(self, *, namespace: str, run_id: str) -> dict[str, object] | None:
        response = self._post("/worker/engine-run-state", {"namespace": namespace, "run_id": run_id})
        if not _required_bool(response, "found"):
            return None
        return {
            "status": _optional_str(response, "status"),
            "result_json": _optional_dict(response, "result_json") or {},
            "cancelled_at": _optional_str(response, "cancelled_at"),
            "cancelled_by": _optional_str(response, "cancelled_by"),
        }

    def fail_build_job(self, *, job_id: str, namespace: str, error: str) -> None:
        self._post("/worker/fail-build-job", {"job_id": job_id, "namespace": namespace, "error": error})

    def finalize_build_job(self, *, job_id: str, build_id: str, namespace: str) -> None:
        self._post("/worker/finalize-build-job", {"job_id": job_id, "build_id": build_id, "namespace": namespace})

    def release_build_worker_jobs(self, *, worker_id: str) -> int:
        response = self._post("/worker/release-build-worker-jobs", {"worker_id": worker_id})
        return _required_int(response, "released")

    def queued_build_job_count(self) -> int:
        response = self._post("/worker/queued-build-job-count", {})
        return _required_int(response, "queued")

    def dispatch_runtime_outbox(self) -> int:
        response = self._post("/worker/dispatch-runtime-outbox", {})
        return _required_int(response, "dispatched")

    def idle_build_worker_pids(self) -> set[int]:
        response = self._post("/worker/idle-build-worker-pids", {})
        raw_pids = response.get("pids")
        if not isinstance(raw_pids, list):
            raise RuntimeError(f"Backend worker RPC returned invalid pids payload: {response!r}")
        pids: set[int] = set()
        for raw_pid in raw_pids:
            if not isinstance(raw_pid, int):
                raise RuntimeError(f"Backend worker RPC returned non-integer pid: {raw_pid!r}")
            pids.add(raw_pid)
        return pids

    def runtime_namespaces(self) -> list[str]:
        response = self._post("/worker/runtime-namespaces", {})
        raw_namespaces = response.get("namespaces")
        if not isinstance(raw_namespaces, list):
            raise RuntimeError(f"Backend worker RPC returned invalid namespaces payload: {response!r}")
        namespaces: list[str] = []
        for raw_namespace in raw_namespaces:
            if not isinstance(raw_namespace, str) or not raw_namespace:
                raise RuntimeError(f"Backend worker RPC returned invalid namespace: {raw_namespace!r}")
            namespaces.append(raw_namespace)
        return namespaces

    def persist_build_event(
        self,
        *,
        namespace: str,
        build_id: str,
        event: dict[str, object],
        resource_config_json: dict[str, object] | None = None,
    ) -> int | None:
        response = self._post(
            "/worker/persist-build-event",
            {
                "namespace": namespace,
                "build_id": build_id,
                "event": event,
                "resource_config_json": resource_config_json,
            },
        )
        sequence = response.get("sequence")
        if sequence is None:
            return None
        if not isinstance(sequence, int):
            raise RuntimeError(f"Backend worker RPC response missing integer sequence: {response!r}")
        return sequence

    def start_build_run(self, *, namespace: str, build_id: str) -> StartedBuildRun | None:
        response = self._post("/worker/start-build-run", {"namespace": namespace, "build_id": build_id})
        raw_run = response.get("run")
        if raw_run is None:
            return None
        if not isinstance(raw_run, dict):
            raise RuntimeError(f"Backend worker RPC returned invalid build run payload: {response!r}")
        return StartedBuildRun(
            id=_required_str(raw_run, "id"),
            namespace=_required_str(raw_run, "namespace"),
            analysis_id=_required_str(raw_run, "analysis_id"),
            analysis_name=_required_str(raw_run, "analysis_name"),
            request_json=_required_dict(raw_run, "request_json"),
            starter_json=_required_dict(raw_run, "starter_json"),
            resource_config_json=_optional_dict(raw_run, "resource_config_json"),
            current_kind=_optional_str(raw_run, "current_kind"),
            current_datasource_id=_optional_str(raw_run, "current_datasource_id"),
            current_tab_id=_optional_str(raw_run, "current_tab_id"),
            current_tab_name=_optional_str(raw_run, "current_tab_name"),
            current_output_id=_optional_str(raw_run, "current_output_id"),
            current_output_name=_optional_str(raw_run, "current_output_name"),
            started_at=datetime.fromisoformat(_required_str(raw_run, "started_at")),
            total_tabs=_required_int(raw_run, "total_tabs"),
        )

    def persist_engine_snapshot(self, *, worker_id: str, namespace: str, statuses: list[Mapping[str, object]]) -> int:
        response = self._post(
            "/worker/persist-engine-snapshot",
            {
                "worker_id": worker_id,
                "namespace": namespace,
                "statuses": [dict(status) for status in statuses],
            },
        )
        return _required_int(response, "persisted")

    def pending_datasource_deletes(self) -> list[PendingDatasourceDelete]:
        response = self._post("/worker/pending-datasource-deletes", {})
        raw_deletes = response.get("deletes")
        if not isinstance(raw_deletes, list):
            raise RuntimeError(f"Backend worker RPC returned invalid datasource delete payload: {response!r}")
        deletes: list[PendingDatasourceDelete] = []
        for raw_delete in raw_deletes:
            if not isinstance(raw_delete, dict):
                raise RuntimeError(f"Backend worker RPC returned invalid datasource delete item: {raw_delete!r}")
            deletes.append(
                PendingDatasourceDelete(
                    namespace=_required_str(raw_delete, "namespace"),
                    datasource_id=_required_str(raw_delete, "datasource_id"),
                )
            )
        return deletes

    def finalize_datasource_delete(self, *, namespace: str, datasource_id: str) -> bool:
        response = self._post("/worker/finalize-datasource-delete", {"namespace": namespace, "datasource_id": datasource_id})
        deleted = response.get("deleted")
        if not isinstance(deleted, bool):
            raise RuntimeError(f"Backend worker RPC returned invalid datasource delete finalize response: {response!r}")
        return deleted

    def telegram_enabled(self) -> bool:
        response = self._post("/worker/telegram-settings", {})
        enabled = response.get("enabled")
        if not isinstance(enabled, bool):
            raise RuntimeError(f"Backend worker RPC returned invalid telegram settings response: {response!r}")
        return enabled

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Mapping[str, object]] | None = None,
    ) -> bool:
        response = self._post(
            "/worker/send-email",
            {
                "to": to,
                "subject": subject,
                "body": body,
                "attachments": _serialize_attachments(attachments or []),
            },
        )
        return _required_bool(response, "sent")

    def send_telegram(
        self,
        *,
        chat_id: str,
        message: str,
        bot_token: str | None = None,
        attachments: list[Mapping[str, object]] | None = None,
    ) -> bool:
        response = self._post(
            "/worker/send-telegram",
            {
                "chat_id": chat_id,
                "message": message,
                "bot_token": bot_token,
                "attachments": _serialize_attachments(attachments or []),
            },
        )
        return _required_bool(response, "sent")

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
        response = self._post(
            "/worker/generate-ai",
            {
                "provider": provider,
                "prompts": prompts,
                "model": model,
                "endpoint_url": endpoint_url,
                "api_key": api_key,
                "options": options,
            },
        )
        outputs = response.get("outputs")
        if not isinstance(outputs, list) or not all(isinstance(output, str) for output in outputs):
            raise RuntimeError(f"Backend worker RPC returned invalid AI response: {response!r}")
        return outputs

    def telegram_targets(self, *, namespace: str, datasource_id: str | None = None, active_subscribers: bool = False) -> list[TelegramTarget]:
        response = self._post(
            "/worker/telegram-targets",
            {
                "namespace": namespace,
                "datasource_id": datasource_id,
                "active_subscribers": active_subscribers,
            },
        )
        raw_targets = response.get("targets")
        if not isinstance(raw_targets, list):
            raise RuntimeError(f"Backend worker RPC returned invalid telegram targets response: {response!r}")
        targets: list[TelegramTarget] = []
        for raw_target in raw_targets:
            if not isinstance(raw_target, dict):
                raise RuntimeError(f"Backend worker RPC returned invalid telegram target item: {raw_target!r}")
            targets.append(
                TelegramTarget(
                    chat_id=_required_str(raw_target, "chat_id"),
                    bot_token=_required_str(raw_target, "bot_token"),
                )
            )
        return targets

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Token": self._token,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise _rpc_error_from_http_error(exc.code, detail) from exc
        if not raw:
            return {}
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError(f"Backend worker RPC returned non-object JSON: {decoded!r}")
        return decoded

    def _post_registration(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        deadline = time.monotonic() + self._registration_retry_seconds
        while True:
            try:
                return self._post(path, payload)
            except URLError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1.0)


def _rpc_error_from_http_error(status_code: int, detail: str) -> BackendWorkerRpcError:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return BackendWorkerRpcError(
            status_code=status_code,
            error=f"Backend worker RPC failed with HTTP {status_code}: {detail}",
        )

    if not isinstance(payload, dict):
        return BackendWorkerRpcError(
            status_code=status_code,
            error=f"Backend worker RPC failed with HTTP {status_code}: {payload!r}",
        )

    raw_detail = payload.get("detail")
    error = raw_detail if isinstance(raw_detail, str) else f"Backend worker RPC failed with HTTP {status_code}"
    error_code = payload.get("error_code")
    details = payload.get("details")
    return BackendWorkerRpcError(
        status_code=status_code,
        error=error,
        error_code=error_code if isinstance(error_code, str) else None,
        details=details if isinstance(details, dict) else None,
    )


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Backend worker RPC response missing string {key}: {payload!r}")
    return value


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise RuntimeError(f"Backend worker RPC response missing integer {key}: {payload!r}")
    return value


def _required_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"Backend worker RPC response missing boolean {key}: {payload!r}")
    return value


def _required_dict(payload: dict[str, Any], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Backend worker RPC response missing object {key}: {payload!r}")
    return value


def _optional_dict(payload: dict[str, Any], key: str) -> dict[str, object] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError(f"Backend worker RPC response has invalid object {key}: {payload!r}")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Backend worker RPC response has invalid string {key}: {payload!r}")
    return value


def _optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise RuntimeError(f"Backend worker RPC response has invalid boolean {key}: {payload!r}")
    return value


def _serialize_attachments(attachments: list[Mapping[str, object]]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for attachment in attachments:
        content = attachment.get("content")
        if not isinstance(content, bytes):
            raise RuntimeError(f"Notification attachment content must be bytes: {attachment!r}")
        serialized.append(
            {
                "filename": _required_mapping_str(attachment, "filename"),
                "content_base64": base64.b64encode(content).decode("ascii"),
                "content_type": str(attachment.get("content_type") or "text/plain"),
            }
        )
    return serialized


def _required_mapping_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Notification attachment missing string {key}: {payload!r}")
    return value


def client_from_env() -> WorkerInternalApiClient:
    return WorkerInternalApiClient(
        base_url=_required_env("INTERNAL_API_BASE_URL"),
        token=_required_env("INTERNAL_API_TOKEN"),
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be configured for the worker runtime")
    return value.strip()
