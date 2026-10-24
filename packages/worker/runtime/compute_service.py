import asyncio
import concurrent.futures
import contextlib
import logging
import math
import os
import re
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pyiceberg.table import Table as IcebergTable

from builds.build_live import RuntimeBuild
from dataforge_protocol import compute_pb2, enums_pb2
from operations.datasource import pipeline_datasource_payload
from runtime.build_events import (
    BuildCancelledError,
    BuildEmitter,
    BuildEventContext,
    build_event,
    emit_build_event,
    emit_progress as _emit_progress,
)
from runtime.compute_manager import ProcessManager
from runtime.compute_utils import (
    apply_steps,
    await_compute_worker_result,
    find_step_index,
    resolve_applied_target,
)
from runtime.config import settings
from runtime.domain.analysis.step_types import STEP_TYPES
from runtime.domain.compute import schemas as compute_schemas
from runtime.domain.compute.base import ComputeWorker
from runtime.domain.compute.schemas import BuildStatus, BuildTabStatus, ComputeRunStatus
from runtime.domain.compute_worker_runs.schemas import ComputeWorkerRunExecutionCategory, ComputeWorkerRunKind, ComputeWorkerRunStatus
from runtime.domain.datasource.source_types import DataSourceType
from runtime.exceptions import (
    AppError,
    ComputeWorkerShutdownError,
    DataSourceSnapshotError,
    PipelineExecutionError,
    PipelineValidationError,
    datasource_not_found,
)
from runtime.executors import run_compute_in_thread, run_engine_io_in_thread, run_shutdown_in_thread
from runtime.healthchecks import (
    HealthCheckResult,
    persist_results,
    resolve_build_status,
    run_healthchecks,
)
from runtime.iceberg_catalog import ensure_catalog_namespace, load_runtime_catalog
from runtime.iceberg_metadata import resolve_iceberg_branch_metadata_path, resolve_iceberg_metadata_path, sync_iceberg_schema
from runtime.namespace import get_namespace
from runtime.notification_delivery import (
    STAGED_NOTIFICATION_PREFIX,
    extract_staged_deliveries,
    render_template,
    strip_staged_preview,
)
from runtime.object_store import (
    delete_prefix,
    ensure_bucket_exists,
    join_object_store_url,
    list_prefixes,
    object_store_storage_options,
    object_store_url,
    prefix_last_modified,
)
from runtime.resource_observation import (
    observe_stream_task,
    resource_summary,
    stop_stream_task,
    stream_resource_events,
)
from runtime.worker_runtime_client import ClaimedBuildJob, ComputeWorkerRunFinalization, ExecutionEntry, client_from_env

logger = logging.getLogger(__name__)


class _BuildJobCancellation:
    def __init__(self, manager: ProcessManager, identity: compute_pb2.ComputeWorkerIdentity, *, namespace: str) -> None:
        self._manager = manager
        self._identity = identity
        self._namespace = namespace
        self._lock = threading.Lock()
        self._requested = False
        self._job_id: str | None = None

    def raise_if_cancelled(self) -> None:
        with self._lock:
            requested = self._requested
        if requested:
            raise BuildCancelledError(self._identity.build_id)

    def job_started(self, job_id: str) -> None:
        with self._lock:
            self._job_id = job_id
            requested = self._requested
        if requested:
            self._manager.cancel_engine_job(self._identity, namespace=self._namespace, job_id=job_id)
            raise BuildCancelledError(self._identity.build_id)

    def cancel(self) -> None:
        with self._lock:
            if self._requested:
                return
            self._requested = True
            job_id = self._job_id
        if job_id is not None:
            self._manager.cancel_engine_job(self._identity, namespace=self._namespace, job_id=job_id)


MAX_DOWNLOAD_BYTES: Final = 10 * 1024 * 1024
_SLOW_PREVIEW_LOG_SECONDS = 5.0


def _secure_temp_path(suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


def _ensure_download_size(path: str) -> int:
    size = os.path.getsize(path)
    if size > MAX_DOWNLOAD_BYTES:
        limit_mb = MAX_DOWNLOAD_BYTES // (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        raise ValueError(f"Download is {actual_mb:.1f} MB; maximum supported download size is {limit_mb} MB")
    return size


def _internal_catalog_uri(config_uri: object) -> str | None:
    if settings.database_url:
        return settings.database_url
    if isinstance(config_uri, str) and config_uri:
        return config_uri
    return None


def _strip_staged_notification_columns(path: str) -> list[dict[str, object]] | None:
    parquet_file = pq.ParquetFile(path)
    staged_columns = [name for name in parquet_file.schema_arrow.names if name.startswith(STAGED_NOTIFICATION_PREFIX)]
    if not staged_columns:
        return None
    _, deliveries = extract_staged_deliveries(parquet_file.read(columns=staged_columns))
    kept_schema = pa.schema([field for field in parquet_file.schema_arrow if field.name not in set(staged_columns)])
    tmp_rewrite = _secure_temp_path(suffix=".parquet")
    try:
        with pq.ParquetWriter(tmp_rewrite, kept_schema) as writer:
            for batch in parquet_file.iter_batches(batch_size=65_536, columns=[field.name for field in kept_schema]):
                writer.write_batch(batch)
        os.replace(tmp_rewrite, path)
    finally:
        if os.path.exists(tmp_rewrite):
            os.unlink(tmp_rewrite)
    return deliveries


@dataclass(frozen=True, slots=True)
class PreviewOutcome:
    response: compute_schemas.StepPreviewResponse
    compute_worker_run_finalization: ComputeWorkerRunFinalization | None = None


class PreviewExecutionError(RuntimeError):
    def __init__(self, error: Exception, compute_worker_run_finalization: ComputeWorkerRunFinalization) -> None:
        super().__init__(str(error))
        self.error = error
        self.compute_worker_run_finalization = compute_worker_run_finalization


BuildContext = Mapping[str, object]


@dataclass(frozen=True)
class ExportDatasourceResult:
    datasource_id: str
    datasource_name: str
    result_meta: dict


@dataclass(slots=True)
class _SyntheticBuildStage:
    step_id: str
    step_name: str
    step_type: str
    build_step_index: int
    step_index: int
    started_at: float
    started: bool = False
    completed: bool = False


def _raise_engine_failure(
    result_data: dict,
    *,
    operation: str,
    datasource_id: str,
    failure_prefix: str,
) -> None:
    error = result_data.get("error")
    if not error:
        return

    error_text = str(error)
    error_kind = result_data.get("error_kind")
    raw_error_details = result_data.get("error_details")
    error_details = raw_error_details if isinstance(raw_error_details, dict) else {}

    if error_kind == "pipeline_validation":
        validation_details = error_details.get("details")
        details = dict(validation_details) if isinstance(validation_details, dict) else {}
        details["operation"] = operation
        details["datasource_id"] = datasource_id
        raise PipelineValidationError(error_text, details=details)

    if error_kind == "value_error":
        raise PipelineValidationError(
            error_text,
            details={
                "operation": operation,
                "datasource_id": datasource_id,
                **error_details,
            },
        )

    if error_kind == "datasource_metadata_missing":
        snapshot_details: dict[str, object] = {
            "operation": operation,
            "datasource_id": datasource_id,
        }
        metadata_path = error_details.get("metadata_path")
        if isinstance(metadata_path, str):
            snapshot_details["metadata_path"] = metadata_path
        raise DataSourceSnapshotError(
            "Datasource output is not available for this branch yet. Build the producing analysis first.",
            details=snapshot_details,
        )

    if error_kind == "engine_shutdown":
        raise ComputeWorkerShutdownError(
            details={
                "operation": operation,
                "datasource_id": datasource_id,
            }
        )

    raise PipelineExecutionError(
        f"{failure_prefix} failed: {error_text}",
        details={
            "operation": operation,
            "datasource_id": datasource_id,
            "error_kind": error_kind,
            **error_details,
        },
    )


def _preflight_datasource_for_compute(
    config: dict,
    *,
    operation: str,
    datasource_id: str,
) -> None:
    source_type = DataSourceType.read(config.get("source_type"), default=None)
    if source_type != DataSourceType.ICEBERG:
        return

    metadata_path = config.get("metadata_path")
    if not isinstance(metadata_path, str) or not metadata_path.strip():
        raise PipelineValidationError(
            "Iceberg datasource requires metadata_path",
            details={"operation": operation, "datasource_id": datasource_id},
        )
    branch = config.get("branch")
    branch_value = str(branch) if isinstance(branch, str) and branch else None
    namespace_name = config.get("namespace_name")
    namespace_value = str(namespace_name) if isinstance(namespace_name, str) and namespace_name.strip() else None
    try:
        resolved_metadata_path = resolve_iceberg_branch_metadata_path(
            metadata_path,
            branch_value,
            namespace_name=namespace_value,
        )
    except ValueError as exc:
        message = str(exc)
        if "Iceberg metadata_path not found" in message:
            raise DataSourceSnapshotError(
                "Datasource output is not available for this branch yet. Build the producing analysis first.",
                details={
                    "operation": operation,
                    "datasource_id": datasource_id,
                    "metadata_path": metadata_path,
                },
            ) from exc
        raise
    config["metadata_path"] = resolved_metadata_path


def _tab_output_config(analysis_pipeline: dict, tab_id: str | None) -> dict:
    """Output config of the requested tab, falling back to the first tab."""
    tabs = analysis_pipeline.get("tabs", [])
    selected = next((tab for tab in tabs if tab_id and tab.get("id") == tab_id), tabs[0] if tabs else {})
    return selected.get("output", {})


def _output_timeout_warning_ms(analysis_pipeline: dict, tab_id: str | None) -> int | None:
    # The protocol requires a positive value and the pipeline decoder keeps it an int.
    return _tab_output_config(analysis_pipeline, tab_id).get("build_timeout_warning_ms")


def _build_subscriber_message(context: BuildContext) -> str:
    status = BuildStatus.coerce(context.get("status", BuildStatus.SUCCESS))
    analysis_name = str(context.get("analysis_name", ""))
    row_count = str(context.get("row_count", ""))
    duration = str(context.get("duration_ms", ""))
    hc_summary = context.get("healthcheck_summary")
    hc_details = context.get("healthcheck_details")
    duration_warning = bool(context.get("duration_exceeded_warning"))

    if status == BuildStatus.WARNING:
        msg = f"Build complete: {analysis_name}\nStatus: built successfully, health checks failed"
    else:
        msg = f"Build complete: {analysis_name}\nStatus: {status.value}"

    if hc_summary:
        msg += f"\nHealth checks: {hc_summary}"

    msg += f"\nRows: {row_count}\nDuration: {duration}ms"
    if duration_warning:
        threshold = context.get("build_timeout_warning_ms")
        threshold_text = f" (threshold {threshold}ms)" if threshold is not None else ""
        msg += f"\nWarning: build exceeded duration threshold{threshold_text}"

    max_len = 3800
    if len(msg) <= max_len:
        return msg

    hc_tail = ""
    if isinstance(hc_details, list):
        hc_tail = "\n".join(f"  {'\u2713' if detail.passed else '\u2717'} {detail.name}: {detail.message} " for detail in hc_details)

    if not hc_tail:
        return msg[:max_len] + "\n…(truncated)"

    footer = f"\nHealth check details:\n{hc_tail}"
    combined = msg + footer
    if len(combined) <= max_len:
        return combined

    available = max_len - len(msg) - len("\nHealth check details:\n") - len("\n…(truncated)")
    if available <= 0:
        return msg[:max_len] + "\n…(truncated)"
    trimmed = hc_tail[:available]
    return f"{msg}\nHealth check details:\n{trimmed}\n…(truncated)"


def _prepare_pipeline_notifications(
    context: dict[str, object],
    output_notification: dict | None = None,
) -> list[dict[str, object]]:
    deliveries: list[dict[str, object]] = []

    if output_notification:
        method = output_notification.get("method", "email")
        recipient = output_notification.get("recipient", "")
        subject_template = output_notification.get("subject_template", "Build Complete")
        body_template = output_notification.get("body_template", "")
        if recipient and method == "email":
            subject = render_template(subject_template, context)
            body = render_template(body_template, context)
            deliveries.append({"method": "email", "recipient": recipient, "subject": subject, "body": body})

    # Subscriber-based notifications (from Telegram bot /subscribe)
    datasource_id = str(context.get("datasource_id", ""))
    if not datasource_id:
        return deliveries
    try:
        excluded: set[str] = set()
        if output_notification and output_notification.get("method") == "telegram":
            targets = client_from_env().telegram_targets(namespace=get_namespace(), active_subscribers=True)
            excluded_raw = output_notification.get("excluded_recipients")
            if isinstance(excluded_raw, list):
                excluded = {str(item) for item in excluded_raw}
        else:
            targets = client_from_env().telegram_targets(namespace=get_namespace(), datasource_id=datasource_id)
        pairs = [(target.chat_id, target.bot_token) for target in targets if target.chat_id not in excluded]
        if pairs:
            msg = _build_subscriber_message(cast(BuildContext, context))
            deliveries.extend({"method": "telegram", "recipient": cid, "message": msg, "bot_token": token} for cid, token in pairs if token)
    except Exception as e:
        raise PipelineExecutionError("Notification target resolution failed", details={"error": str(e)}) from e
    return deliveries


def _schema_cache_payload_from_arrow(arrow_schema: pa.Schema, data: Mapping[str, object]) -> dict[str, object]:
    raw_schema = data.get("schema")
    schema_by_name = raw_schema if isinstance(raw_schema, Mapping) else {}
    columns: list[dict[str, object]] = []
    for field in arrow_schema:
        raw_column = schema_by_name.get(field.name)
        dtype = raw_column.get("dtype") if isinstance(raw_column, Mapping) else raw_column
        nullable = raw_column.get("nullable") if isinstance(raw_column, Mapping) else None
        columns.append(
            {
                "name": field.name,
                "dtype": str(dtype if dtype is not None else field.type),
                "nullable": nullable if isinstance(nullable, bool) else field.nullable,
            }
        )

    payload: dict[str, object] = {"columns": columns}
    row_count = data.get("row_count")
    if isinstance(row_count, int) and not isinstance(row_count, bool):
        payload["row_count"] = row_count
    return payload


def _build_compute_worker_run_execution_entries(
    result_data: dict | None,
    *,
    duration_ms: int,
    write_duration_ms: float | None = None,
) -> list[ExecutionEntry]:
    payload = result_data or {}
    data = payload.get("data") or {}
    return _build_execution_entries(
        step_timings=payload.get("step_timings"),
        query_plans=data.get("query_plans"),
        query_plan=payload.get("query_plan"),
        read_duration_ms=payload.get("read_duration_ms"),
        collect_duration_ms=payload.get("collect_duration_ms"),
        write_duration_ms=write_duration_ms,
        total_duration_ms=duration_ms,
    )


def _nonnegative_duration(value: object) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    duration_ms = float(value)
    return duration_ms if math.isfinite(duration_ms) and duration_ms >= 0 else None


def _build_execution_entries(
    *,
    step_timings: dict | None = None,
    query_plans: dict[str, object] | None = None,
    query_plan: str | None = None,
    read_duration_ms: object = None,
    collect_duration_ms: object = None,
    write_duration_ms: float | None = None,
    total_duration_ms: int | None = None,
) -> list[ExecutionEntry]:
    normalized_timings: dict[str, float] = {}
    for key, value in (step_timings or {}).items():
        try:
            duration_ms = float(value)
        except TypeError, ValueError:
            continue
        if math.isfinite(duration_ms) and duration_ms >= 0:
            normalized_timings[str(key)] = duration_ms
    read_duration = _nonnegative_duration(read_duration_ms)
    collect_duration = _nonnegative_duration(collect_duration_ms)
    write_duration = _nonnegative_duration(write_duration_ms)
    total_duration = _nonnegative_duration(total_duration_ms)
    timed_total = sum(normalized_timings.values())
    timed_total += sum(duration for duration in (read_duration, collect_duration, write_duration) if duration is not None)
    denominator = total_duration if total_duration and total_duration > 0 else timed_total
    entries: list[ExecutionEntry] = []

    def append_entry(
        *,
        key: str,
        label: str,
        category: ComputeWorkerRunExecutionCategory,
        duration_ms: float | None = None,
        optimized_plan: str | None = None,
        unoptimized_plan: str | None = None,
        step_type: str | None = None,
    ) -> None:
        share_pct = None
        if duration_ms is not None and denominator > 0:
            share_pct = round(min(max((duration_ms / denominator) * 100, 0.0), 100.0), 1)
        entries.append(
            ExecutionEntry(
                key=key,
                label=label,
                category=category,
                order=len(entries),
                duration_ms=round(duration_ms, 2) if duration_ms is not None else None,
                share_pct=share_pct,
                optimized_plan=optimized_plan,
                unoptimized_plan=unoptimized_plan,
                step_type=step_type,
            )
        )

    if read_duration is not None:
        append_entry(key="initial_read", label="Initial Read", category=ComputeWorkerRunExecutionCategory.READ, duration_ms=read_duration)
    raw_plans = query_plans or {}
    raw_optimized_plan = raw_plans.get("optimized")
    raw_unoptimized_plan = raw_plans.get("unoptimized")
    optimized_plan = raw_optimized_plan if isinstance(raw_optimized_plan, str) else None
    unoptimized_plan = raw_unoptimized_plan if isinstance(raw_unoptimized_plan, str) else None
    if optimized_plan or unoptimized_plan or query_plan:
        append_entry(
            key="query_plan",
            label="Query Plan",
            category=ComputeWorkerRunExecutionCategory.PLAN,
            optimized_plan=optimized_plan or query_plan,
            unoptimized_plan=unoptimized_plan or query_plan,
        )
    for timing_key, timing_duration_ms in normalized_timings.items():
        base_key, label = STEP_TYPES.timing_key(timing_key)
        append_entry(
            key=timing_key,
            label=label,
            category=ComputeWorkerRunExecutionCategory.STEP,
            duration_ms=timing_duration_ms,
            step_type=base_key,
        )
    if collect_duration is not None:
        append_entry(key="compute", label="Compute", category=ComputeWorkerRunExecutionCategory.COMPUTE, duration_ms=collect_duration)
    if write_duration is not None:
        append_entry(key="write_output", label="Write Output", category=ComputeWorkerRunExecutionCategory.WRITE, duration_ms=write_duration)
    return entries


def _tab_name_from_pipeline(analysis_pipeline: dict, tab_id: str | None) -> str | None:
    tabs = analysis_pipeline.get("tabs", [])
    if isinstance(tab_id, str):
        for tab in tabs:
            if tab.get("id", "") != tab_id:
                continue
            return tab.get("name") or None
    if len(tabs) == 1:
        return tabs[0].get("name") or None
    return None


def _normalize_query_plan_snapshots(
    query_plans: object,
    *,
    tab_id: str | None,
    tab_name: str | None,
) -> list[dict[str, str | None]]:
    if isinstance(query_plans, list):

        def text(plan: dict, key: str, default: str | None) -> str | None:
            value = plan.get(key)
            return value if isinstance(value, str) and value else default

        return [
            {
                "tab_id": text(plan, "tab_id", tab_id),
                "tab_name": text(plan, "tab_name", tab_name),
                "optimized_plan": text(plan, "optimized_plan", ""),
                "unoptimized_plan": text(plan, "unoptimized_plan", ""),
            }
            for plan in query_plans
            if isinstance(plan, dict)
        ]

    if isinstance(query_plans, dict):
        optimized_plan = query_plans.get("optimized")
        unoptimized_plan = query_plans.get("unoptimized")
        if isinstance(optimized_plan, str) or isinstance(unoptimized_plan, str):
            return [
                {
                    "tab_id": tab_id,
                    "tab_name": tab_name,
                    "optimized_plan": optimized_plan if isinstance(optimized_plan, str) else "",
                    "unoptimized_plan": unoptimized_plan if isinstance(unoptimized_plan, str) else "",
                }
            ]

    return []


def _step_type_from_execution_entry(entry: ExecutionEntry) -> str:
    return entry.step_type or entry.category.default_step_type


def _build_step_snapshots_from_execution_entries(
    execution_entries: list[ExecutionEntry],
    *,
    tab_id: str | None,
    tab_name: str | None,
) -> list[dict[str, object]]:
    steps = [entry for entry in execution_entries if entry.category != ComputeWorkerRunExecutionCategory.PLAN]
    steps.sort(key=lambda entry: entry.order)
    snapshots: list[dict[str, object]] = []
    for index, entry in enumerate(steps):
        snapshots.append(
            {
                "build_step_index": index,
                "step_index": index,
                "step_id": entry.key or f"step_{index}",
                "step_name": entry.label or "Unnamed step",
                "step_type": _step_type_from_execution_entry(entry),
                "tab_id": tab_id,
                "tab_name": tab_name,
                "state": compute_schemas.BuildStepState.COMPLETED.value,
                "duration_ms": entry.duration_ms,
                "row_count": None,
                "error": None,
            }
        )
    return snapshots


def _load_compute_worker_run_result_json(run_id: str) -> dict[str, object]:
    state = client_from_env().compute_worker_run_state(namespace=get_namespace(), run_id=run_id)
    if state is None:
        return {}
    return dict(state.result_json)


def _raise_if_compute_worker_run_cancelled(run_id: str) -> None:
    state = client_from_env().compute_worker_run_state(namespace=get_namespace(), run_id=run_id)
    if state is None or state.status != ComputeWorkerRunStatus.CANCELLED.value:
        return
    raise BuildCancelledError(
        run_id,
        cancelled_at=state.cancelled_at,
        cancelled_by=state.cancelled_by,
    )


def _raise_if_build_cancelled(build_id: str) -> None:
    cancelled, cancelled_at, cancelled_by = client_from_env().build_cancel_status(namespace=get_namespace(), build_id=build_id)
    if not cancelled:
        return
    raise BuildCancelledError(build_id, cancelled_at=cancelled_at, cancelled_by=cancelled_by)


def _single_tab_run_finalization(
    run_id: str,
    *,
    existing_result: dict[str, object] | None,
    result_data: dict | None,
    started_perf: float,
    tab_id: str | None,
    tab_name: str | None,
    total_steps: int,
    error: Exception | None = None,
    summary_meta: dict[str, object] | None = None,
    log_message: str = "",
    resource_config: dict[str, int | None] | None = None,
    write_duration_ms: float | None = None,
    **fields: object,
) -> ComputeWorkerRunFinalization:
    """Terminal run update for a single-tab preview, row count, or download."""
    completed_at = datetime.now(UTC)
    duration_ms = int((time.perf_counter() - started_perf) * 1000)
    execution_entries = _build_compute_worker_run_execution_entries(result_data, duration_ms=duration_ms, write_duration_ms=write_duration_ms)
    failed = error is not None
    result_json = _build_canonical_compute_worker_run_result(
        existing_result=existing_result,
        summary_meta=summary_meta,
        execution_entries=execution_entries,
        current_tab_id=tab_id,
        current_tab_name=tab_name,
        total_steps=total_steps,
        resource_config=resource_config,
        results=[
            {
                "tab_id": tab_id or "",
                "tab_name": tab_name or "Build",
                "status": BuildTabStatus.FAILED if failed else BuildTabStatus.SUCCESS,
                **({"error": str(error)} if failed else {}),
            }
        ],
        append_logs=[
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "error" if failed else "info",
                "message": str(error) if failed else log_message,
                "step_id": None,
                "step_name": None,
                "tab_id": tab_id,
                "tab_name": tab_name,
            }
        ],
    )
    run_fields: dict[str, object] = {
        "status": ComputeRunStatus.FAILED if failed else ComputeRunStatus.SUCCESS,
        "result_json": result_json,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "step_timings": result_data.get("step_timings", {}) if isinstance(result_data, dict) else {},
        "execution_entries": execution_entries,
        "progress": 0.0 if failed else 1.0,
        **fields,
    }
    if failed:
        run_fields["error_message"] = str(error)
    return ComputeWorkerRunFinalization(run_id=run_id, fields=run_fields, merge_result_json=False)


def _apply_run_finalization(finalization: ComputeWorkerRunFinalization) -> None:
    client_from_env().update_compute_worker_run(
        namespace=get_namespace(),
        run_id=finalization.run_id,
        fields={key: value.isoformat() if isinstance(value, datetime) else value for key, value in finalization.fields.items()},
        merge_result_json=finalization.merge_result_json,
    )


def _build_canonical_compute_worker_run_result(
    *,
    existing_result: dict[str, object] | None,
    summary_meta: dict[str, object] | None,
    execution_entries: list[ExecutionEntry],
    current_tab_id: str | None,
    current_tab_name: str | None,
    total_steps: int,
    resource_config: dict[str, int | None] | None,
    results: list[dict[str, object]],
    append_logs: list[dict[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {**(existing_result or {}), **(summary_meta or {})}
    result["current_output_id"] = None
    result["current_output_name"] = None
    result["current_tab_id"] = current_tab_id
    result["current_tab_name"] = current_tab_name
    result["total_steps"] = max(total_steps, sum(1 for entry in execution_entries if entry.category != ComputeWorkerRunExecutionCategory.PLAN))
    result["total_tabs"] = 1
    if resource_config is not None:
        result["resource_config"] = resource_config
    result["query_plans"] = _normalize_query_plan_snapshots(result.get("query_plans"), tab_id=current_tab_id, tab_name=current_tab_name)
    result["steps"] = _build_step_snapshots_from_execution_entries(execution_entries, tab_id=current_tab_id, tab_name=current_tab_name)
    raw_resources = result.get("resources")
    resources = [resource for resource in raw_resources if isinstance(resource, dict)] if isinstance(raw_resources, list) else []
    result["resources"] = resources
    logs = result.get("logs")
    result["logs"] = [*(entry for entry in logs if isinstance(entry, dict)), *append_logs] if isinstance(logs, list) else append_logs
    if resources:
        result["latest_resources"] = resources[-1]
    else:
        result.pop("latest_resources", None)
    result["results"] = results
    return result


def _initial_live_run_result(
    *,
    current_tab_id: str | None,
    current_tab_name: str | None,
    total_steps: int,
    resource_config: dict[str, int | None] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "steps": [],
        "query_plans": [],
        "resources": [],
        "logs": [],
        "results": [],
        "current_output_id": None,
        "current_output_name": None,
        "current_tab_id": current_tab_id,
        "current_tab_name": current_tab_name,
        "total_steps": total_steps,
        "total_tabs": 1,
    }
    if resource_config is not None:
        result["resource_config"] = resource_config
    return result


_REVISION_DIR_PREFIX = "revision_"
# Superseded revision directories are only reclaimed after this grace period:
# a reader that resolved a revision moments before the swap must finish.
_REVISION_GC_GRACE_SECONDS: Final[int] = 3600


def prune_superseded_revisions(
    branch_base_url: str,
    *,
    keep_urls: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> None:
    """Delete superseded revision_* directories under a branch base, best-effort.

    A revision dir is reclaimable when it is not in keep_urls and its newest
    object is older than the grace period. Failures only cost storage, never
    correctness, so individual errors are logged and skipped.
    """
    current_time = now or datetime.now(UTC)
    try:
        names = list_prefixes(branch_base_url)
    except Exception as exc:
        logger.warning("Revision GC could not list %s: %s", branch_base_url, exc)
        return
    for name in names:
        if not name.startswith(_REVISION_DIR_PREFIX):
            continue
        revision_url = join_object_store_url(branch_base_url, name)
        if revision_url in keep_urls:
            continue
        try:
            newest = prefix_last_modified(revision_url)
        except Exception as exc:
            logger.warning("Revision GC could not inspect %s: %s", revision_url, exc)
            continue
        if newest is None or (current_time - newest).total_seconds() < _REVISION_GC_GRACE_SECONDS:
            continue
        try:
            delete_prefix(revision_url)
            logger.info("Revision GC removed superseded revision %s", revision_url)
        except Exception as exc:
            logger.warning("Revision GC failed to delete %s: %s", revision_url, exc)


def _set_snapshot_metadata(config: dict, snapshot_id: str | None, snapshot_timestamp_ms: int | None, metadata_file: str | None = None) -> dict:
    if snapshot_id is None or snapshot_timestamp_ms is None:
        return config
    updated = {
        **config,
        "current_snapshot_id": snapshot_id,
        "current_snapshot_timestamp_ms": snapshot_timestamp_ms,
        "snapshot_id": snapshot_id,
        "snapshot_timestamp_ms": snapshot_timestamp_ms,
    }
    # Readers resolve this exact file instead of listing the prefix: S3-style
    # stores guarantee single-object read-after-write, prefix listings do not.
    if metadata_file:
        updated["metadata_file"] = metadata_file
    return updated


def _ensure_request_branch(request_payload: dict, config: dict) -> dict:
    branch = config.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError("branch is required")
    payload = dict(request_payload)
    opts = payload.get("iceberg_options")
    if not isinstance(opts, dict):
        payload["iceberg_options"] = {"branch": branch.strip()}
    elif not (isinstance(opts.get("branch"), str) and opts["branch"].strip()):
        payload["iceberg_options"] = {**opts, "branch": branch.strip()}
    return payload


def _get_additional_datasources(
    steps: list[dict],
    analysis_pipeline: dict,
) -> dict[str, dict]:
    """Extract and fetch additional datasources referenced in pipeline steps (e.g., for joins)."""
    steps = apply_steps(steps)
    additional: dict[str, dict] = {}
    pipeline_id = analysis_pipeline.get("analysis_id")
    analysis_id = str(pipeline_id) if pipeline_id is not None else None
    output_to_tab = _pipeline_output_to_tab_id(analysis_pipeline)

    for step in steps:
        config = step.get("config", {})
        right_source_id = config.get("right_source")
        source_ids = ([right_source_id] if right_source_id else []) + config.get("sources", [])

        for source_id in source_ids:
            if source_id in additional:
                continue
            config_override = _resolve_step_source_config(
                source_id=source_id,
                analysis_pipeline=analysis_pipeline,
                output_to_tab=output_to_tab,
            )
            if config_override is None:
                continue
            if analysis_id and DataSourceType.read(config_override.get("source_type"), default=None) == DataSourceType.ANALYSIS:
                config_override = {
                    **config_override,
                    "analysis_pipeline": analysis_pipeline,
                }
            additional[source_id] = config_override

    return additional


def _library_udf_expression(expr: object) -> bool:
    from operations.enums import WithColumnsExprType

    if not isinstance(expr, dict) or expr.get("code") or not expr.get("udf_id"):
        return False
    return WithColumnsExprType.read(expr.get("type")) == WithColumnsExprType.UDF


def _hydrate_udfs(steps: list[dict]) -> list[dict]:
    udf_ids: list[str] = []
    for step in steps:
        expressions = step.get("config", {}).get("expressions", [])
        udf_ids.extend(str(expr["udf_id"]) for expr in expressions if _library_udf_expression(expr))
    codes = client_from_env().udf_codes(namespace=get_namespace(), udf_ids=sorted(set(udf_ids))) if udf_ids else {}
    next_steps: list[dict] = []
    for step in steps:
        if step.get("type") != "with_columns":
            next_steps.append(step)
            continue
        config = step.get("config", {})
        expressions = config.get("expressions", [])
        updated = []
        for expr in expressions:
            if not _library_udf_expression(expr):
                updated.append(expr)
                continue
            udf_id = expr.get("udf_id")
            code = codes.get(str(udf_id)) if udf_id else None
            if code is None:
                raise ValueError(f"UDF {udf_id} not found")
            updated.append({**expr, "code": code})
        next_steps.append({**step, "config": {**config, "expressions": updated}})
    return next_steps


def _pipeline_output_to_tab_id(pipeline: dict) -> dict[str, str]:
    output_to_tab: dict[str, str] = {}
    for tab in pipeline.get("tabs", []):
        tab_id = tab.get("id")
        output_id = tab.get("output", {}).get("result_id")
        if tab_id and output_id:
            output_to_tab[output_id] = tab_id
    return output_to_tab


def _analysis_source_config(analysis_id: str, analysis_tab_id: str, overrides: dict | None = None) -> dict:
    return {"source_type": "analysis", "analysis_id": analysis_id, "analysis_tab_id": analysis_tab_id, **(overrides or {})}


def _resolve_pipeline_datasource_config(
    pipeline: dict,
    datasource: dict,
) -> dict:
    datasource_id = datasource.get("id")
    if not datasource_id:
        raise ValueError("analysis_pipeline tab missing datasource.id")
    overrides = datasource.get("config")
    if not isinstance(overrides, dict):
        raise ValueError("analysis_pipeline tab datasource.config must be a dict")
    branch = overrides.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError("analysis_pipeline tab datasource.config.branch is required")
    analysis_tab_id = datasource.get("analysis_tab_id")
    output_to_tab = _pipeline_output_to_tab_id(pipeline)
    if analysis_tab_id:
        analysis_id = pipeline.get("analysis_id")
        if not analysis_id:
            raise ValueError("analysis_pipeline analysis_id is required for analysis sources")
        return _analysis_source_config(analysis_id, analysis_tab_id, overrides)
    if datasource_id in output_to_tab:
        analysis_id = pipeline.get("analysis_id")
        if not analysis_id:
            raise ValueError("analysis_pipeline analysis_id is required for analysis outputs")
        return _analysis_source_config(analysis_id, output_to_tab[datasource_id], overrides)
    from runtime.worker_runtime_client import frozen_datasource_metadata

    frozen = frozen_datasource_metadata(get_namespace(), datasource_id)
    if frozen is not None:
        selectors = {"branch", "snapshot_id", "snapshot_timestamp_ms", "time_travel_snapshot_id", "time_travel_snapshot_timestamp_ms", "reader"}
        selection = {key: value for key, value in overrides.items() if key in selectors}
        return {"source_type": frozen.source_type, **(frozen.config or {}), **selection}
    source_type = datasource.get("source_type")
    if isinstance(source_type, str) and source_type.strip():
        return {"source_type": source_type, **overrides}
    metadata = client_from_env().datasource_metadata(namespace=get_namespace(), datasource_id=datasource_id)
    if not metadata.found or metadata.source_type is None or metadata.config is None:
        raise ValueError(f"analysis_pipeline missing datasource config for {datasource_id}")
    return {
        "source_type": metadata.source_type,
        **metadata.config,
        **overrides,
    }


def _resolve_step_source_config(
    *,
    source_id: str,
    analysis_pipeline: dict,
    output_to_tab: dict[str, str],
) -> dict | None:
    if source_id in output_to_tab:
        analysis_id = analysis_pipeline.get("analysis_id")
        if not analysis_id:
            raise ValueError("analysis_pipeline analysis_id is required for analysis sources")
        return _analysis_source_config(analysis_id, output_to_tab[source_id])
    payload = pipeline_datasource_payload(analysis_pipeline, source_id)
    if payload is not None:
        return _resolve_pipeline_datasource_config(analysis_pipeline, payload)
    from runtime.worker_runtime_client import frozen_datasource_metadata

    metadata = frozen_datasource_metadata(get_namespace(), source_id)
    if metadata is None:
        metadata = client_from_env().datasource_metadata(namespace=get_namespace(), datasource_id=source_id)
    if not metadata.found or metadata.source_type is None or metadata.config is None:
        return None
    return {"source_type": metadata.source_type, **metadata.config}


def _select_pipeline_tab(pipeline: dict, tab_id: str | None, target_step_id: str) -> dict:
    tabs = pipeline.get("tabs", [])
    if not tabs:
        raise ValueError("analysis_pipeline missing tabs")

    selected = None
    if tab_id:
        selected = next((tab for tab in tabs if tab.get("id") == tab_id), None)
    if selected and target_step_id != "source":
        steps = selected.get("steps", [])
        if not any(step.get("id") == target_step_id for step in steps):
            selected = None
    if not selected and target_step_id != "source":
        selected = next((tab for tab in tabs if any(step.get("id") == target_step_id for step in tab.get("steps", []))), None)
    if not selected:
        selected = next((tab for tab in tabs if tab.get("steps")), None)
    if not selected:
        selected = tabs[0]
    return selected


def default_stateless_compute_worker_identity(analysis_id: str) -> compute_pb2.ComputeWorkerIdentity:
    """Return the shared engine identity owned by an analysis RID.

    Datasource previews carry an explicit datasource identity from the API, so
    every other pipeline operation must name its analysis RID. Keep this
    selection identical to the backend identity normalization so admission and
    execution refer to the same engine key.
    """
    if not analysis_id:
        raise ValueError("Malformed compute request: analysis_pipeline.analysis_id is required")
    return compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        analysis_id=analysis_id,
        resource_id=analysis_id,
    )


def _pipeline_analysis_id(analysis_pipeline: dict) -> str:
    """Analysis RID named by a pipeline payload; a missing or non-string value is empty."""
    analysis_id = analysis_pipeline.get("analysis_id")
    return analysis_id if isinstance(analysis_id, str) else ""


@dataclass(frozen=True, slots=True)
class _StepRequest:
    analysis_id: str | None
    datasource_id: str
    datasource_config: dict
    steps: list[dict]
    target_step_id: str


def _resolve_pipeline_request(
    pipeline: dict,
    tab_id: str | None,
    target_step_id: str,
    *,
    analysis_id: str | None,
    operation: str,
    analysis_required_by: str | None = None,
) -> _StepRequest:
    selected = _select_pipeline_tab(pipeline, tab_id, target_step_id)

    datasource = selected.get("datasource")
    if not isinstance(datasource, dict):
        raise ValueError("analysis_pipeline tab datasource must be a dict")
    datasource_id = datasource.get("id")
    if not datasource_id:
        raise ValueError("analysis_pipeline tab missing datasource.id")

    steps = selected.get("steps", [])

    merged = _resolve_pipeline_datasource_config(pipeline, datasource)
    pipeline_analysis_id = pipeline.get("analysis_id")
    pipeline_analysis_id = str(pipeline_analysis_id) if pipeline_analysis_id is not None else None
    if (
        pipeline_analysis_id
        and DataSourceType.read(merged.get("source_type"), default=None) == DataSourceType.ANALYSIS
        and str(merged.get("analysis_id")) == pipeline_analysis_id
    ):
        merged = {**merged, "analysis_pipeline": pipeline}

    resolved_target = resolve_applied_target(steps, target_step_id)
    resolved_analysis_id = pipeline_analysis_id if pipeline_analysis_id is not None else analysis_id
    if analysis_required_by is not None and not resolved_analysis_id:
        raise ValueError(f"{analysis_required_by} requires analysis_id")
    _preflight_datasource_for_compute(merged, operation=operation, datasource_id=str(datasource_id))
    return _StepRequest(
        analysis_id=resolved_analysis_id,
        datasource_id=str(datasource_id),
        datasource_config=merged,
        steps=steps,
        target_step_id=resolved_target,
    )


def _steps_through_target(steps: list[dict], target_step_id: str) -> list[dict]:
    """Applied steps up to and including the target, with library UDF code attached."""
    if target_step_id == "source":
        return []
    applied = apply_steps(steps)
    return _hydrate_udfs(applied[: find_step_index(applied, target_step_id) + 1])


def _build_compute_worker_identity(build_id: str) -> compute_pb2.ComputeWorkerIdentity:
    return compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_BUILD,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
        build_id=build_id,
        resource_id=build_id,
    )


def preview_step(
    manager: ProcessManager,
    target_step_id: str,
    analysis_pipeline: dict,
    row_limit: int = 1000,
    page: int = 1,
    analysis_id: str | None = None,
    compute_worker_identity: compute_pb2.ComputeWorkerIdentity | None = None,
    resource_config: dict | None = None,
    tab_id: str | None = None,
    request_json: dict | None = None,
    triggered_by: str | None = None,
    request_id: str | None = None,
    command_hash: str | None = None,
):
    """Preview the result of executing pipeline up to a specific step with pagination."""
    from runtime.domain.compute.schemas import StepPreviewResponse

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    request = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id, analysis_id=analysis_id, operation="preview", analysis_required_by="Preview")
    tab_name = _tab_name_from_pipeline(analysis_pipeline, tab_id)
    if request_json is None:
        raise ValueError("Preview requires request_json")
    request_payload = _ensure_request_branch(request_json, request.datasource_config)
    preview_steps = _steps_through_target(request.steps, request.target_step_id)

    resolved_compute_worker_identity = compute_worker_identity or default_stateless_compute_worker_identity(_pipeline_analysis_id(analysis_pipeline))
    request_namespace = get_namespace()
    run_id = None
    initial_run_result: dict[str, object] | None = None
    if settings.persist_preview_runs:
        initial_run_result = _initial_live_run_result(
            current_tab_id=tab_id,
            current_tab_name=tab_name,
            total_steps=len(preview_steps),
            resource_config=resource_config if isinstance(resource_config, dict) else None,
        )
        run_id = client_from_env().create_compute_worker_run(
            namespace=request_namespace,
            analysis_id=request.analysis_id,
            datasource_id=request.datasource_id,
            kind="preview",
            status="running",
            request_json=request_payload,
            result_json=initial_run_result,
            created_at=started_at,
            progress=0.0,
            triggered_by=triggered_by,
            idempotency_key=request_id,
        )

    additional_datasources = _get_additional_datasources(preview_steps, analysis_pipeline)
    offset = (page - 1) * row_limit
    preview_resource_summary: dict[str, int | None] = {}
    result_data: dict | None = None
    execution_phases = {"prepare_ms": (time.perf_counter() - started_perf) * 1000}
    execution_started = time.perf_counter()
    try:
        # The durable request layer owns active deduplication and the short
        # completed-response cache. Only the admitted leader executes; its
        # isolated compute worker may reuse versioned materialized prefixes.
        phase_started = time.perf_counter()
        with manager.acquire_engine(resolved_compute_worker_identity, resource_config=resource_config) as engine:
            execution_phases["engine_acquire_ms"] = (time.perf_counter() - phase_started) * 1000
            preview_resource_summary = resource_summary(engine)
            phase_started = time.perf_counter()
            job_id = engine.preview(
                datasource_config=request.datasource_config,
                steps=preview_steps,
                row_limit=row_limit,
                offset=offset,
                additional_datasources=additional_datasources,
            )
            execution_phases["engine_submit_ms"] = (time.perf_counter() - phase_started) * 1000
            # Keep the engine reservation until the terminal result has been
            # consumed. Once the watcher publishes that result, the engine is
            # idle again and a disconnect/shutdown path may otherwise evict it
            # while this request is still assembling its response.
            phase_started = time.perf_counter()
            result_data = await_compute_worker_result(engine, job_id=job_id)
            execution_phases["engine_result_wait_ms"] = (time.perf_counter() - phase_started) * 1000
        execution_phases["execution_ms"] = (time.perf_counter() - execution_started) * 1000
        _raise_engine_failure(result_data, operation="preview", datasource_id=request.datasource_id, failure_prefix="Preview")

        raw_data = result_data.get("data", {})
        if not isinstance(raw_data, Mapping):
            raise TypeError("Preview result data must be an object")
        data = strip_staged_preview(raw_data)

        compute_worker_run_finalization = None
        if run_id is not None:
            schema = data.get("schema", {}) or {}
            result_meta: dict[str, object] = {
                "schema": schema,
                "columns": list(schema.keys()),
                "row_count": data.get("row_count", 0),
                "page": page,
                "row_limit": row_limit,
                "offset": offset,
                "page_size": len(data.get("data", []) or []),
            }
            if query_plans := data.get("query_plans"):
                result_meta["query_plans"] = query_plans
            if metadata := data.get("metadata"):
                result_meta["metadata"] = metadata
            query_plan = result_data.get("query_plan")
            plan_fields: dict[str, Any] = {"query_plan": query_plan} if isinstance(query_plan, str) else {}
            compute_worker_run_finalization = _single_tab_run_finalization(
                run_id,
                existing_result=initial_run_result,
                result_data=result_data,
                started_perf=started_perf,
                tab_id=tab_id,
                tab_name=tab_name,
                total_steps=len(preview_steps),
                summary_meta=result_meta,
                log_message="Preview completed",
                resource_config=preview_resource_summary,
                current_step=None,
                **plan_fields,
            )

        return PreviewOutcome(
            response=StepPreviewResponse(
                step_id=request.target_step_id,
                columns=list(data.get("schema", {}).keys()),
                column_types=data.get("schema", {}),
                data=data.get("data", []),
                total_rows=data.get("row_count", 0),
                page=page,
                page_size=len(data.get("data", [])),
                metadata=data.get("metadata"),
            ),
            compute_worker_run_finalization=compute_worker_run_finalization,
        )
    except Exception as exc:
        if run_id is None:
            raise
        finalization = _single_tab_run_finalization(
            run_id,
            existing_result=initial_run_result,
            result_data=result_data,
            started_perf=started_perf,
            tab_id=tab_id,
            tab_name=tab_name,
            total_steps=len(preview_steps),
            error=exc,
            resource_config=preview_resource_summary,
            current_step=None,
        )
        raise PreviewExecutionError(exc, finalization) from exc
    finally:
        total_duration_ms = (time.perf_counter() - started_perf) * 1000
        if total_duration_ms >= _SLOW_PREVIEW_LOG_SECONDS * 1000:
            phase_timings = " ".join(f"{name}={value:.1f}" for name, value in execution_phases.items())
            try:
                engine_scope = enums_pb2.ComputeWorkerScope.Name(resolved_compute_worker_identity.scope).removeprefix("COMPUTE_WORKER_SCOPE_").lower()
            except ValueError:
                engine_scope = str(resolved_compute_worker_identity.scope)
            logger.warning(
                "Slow preview request_id=%s namespace=%s compute_worker_scope=%s resource_id=%s command_hash=%s duration_ms=%.1f %s",
                request_id or "unknown",
                request_namespace,
                engine_scope,
                resolved_compute_worker_identity.resource_id,
                command_hash or "-",
                total_duration_ms,
                phase_timings,
            )


def get_step_schema(
    manager: ProcessManager,
    target_step_id: str,
    analysis_id: str,
    analysis_pipeline: dict,
    tab_id: str | None = None,
):
    """Get the output schema of a pipeline step without returning data."""
    from runtime.domain.compute.schemas import StepSchemaResponse

    request = _resolve_pipeline_request(
        analysis_pipeline, tab_id, target_step_id, analysis_id=analysis_id, operation="schema", analysis_required_by="Schema fetch"
    )
    schema_steps = _steps_through_target(request.steps, request.target_step_id)
    with manager.acquire_engine(default_stateless_compute_worker_identity(_pipeline_analysis_id(analysis_pipeline))) as engine:
        job_id = engine.get_schema(
            datasource_config=request.datasource_config,
            steps=schema_steps,
            additional_datasources=_get_additional_datasources(schema_steps, analysis_pipeline),
        )
        result_data = await_compute_worker_result(engine, job_id=job_id)
    _raise_engine_failure(result_data, operation="schema", datasource_id=request.datasource_id, failure_prefix="Schema fetch")
    schema = result_data.get("data", {}).get("schema", {})
    return StepSchemaResponse(step_id=request.target_step_id, columns=list(schema.keys()), column_types=schema)


def _reported_row_count_error(exc: Exception) -> Exception:
    if isinstance(exc, (AppError, ValueError)):
        return exc
    if isinstance(exc, RuntimeError):
        return PipelineExecutionError(str(exc))
    import grpc

    if isinstance(exc, grpc.RpcError):
        details = exc.details() if callable(getattr(exc, "details", None)) else None
        return PipelineExecutionError(details or str(exc) or "Engine request failed")
    return exc


def get_step_row_count(
    manager: ProcessManager,
    target_step_id: str,
    analysis_id: str,
    analysis_pipeline: dict,
    tab_id: str | None = None,
    request_json: dict | None = None,
    triggered_by: str | None = None,
):
    """Get the row count of a pipeline step without collecting full data."""
    from runtime.domain.compute.schemas import StepRowCountResponse

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    request = _resolve_pipeline_request(
        analysis_pipeline, tab_id, target_step_id, analysis_id=analysis_id, operation="row_count", analysis_required_by="Row count"
    )
    tab_name = _tab_name_from_pipeline(analysis_pipeline, tab_id)
    if request_json is None:
        raise ValueError("Row count requires request_json")
    request_payload = _ensure_request_branch(request_json, request.datasource_config)
    count_steps = _steps_through_target(request.steps, request.target_step_id)

    run_id = client_from_env().create_compute_worker_run(
        namespace=get_namespace(),
        analysis_id=request.analysis_id,
        datasource_id=request.datasource_id,
        kind="row_count",
        status="running",
        request_json=request_payload,
        result_json=_initial_live_run_result(current_tab_id=tab_id, current_tab_name=tab_name, total_steps=len(count_steps)),
        created_at=started_at,
        progress=0.0,
        triggered_by=triggered_by,
    )
    result_data: dict | None = None
    try:
        with manager.acquire_engine(default_stateless_compute_worker_identity(_pipeline_analysis_id(analysis_pipeline))) as engine:
            job_id = engine.get_row_count(
                datasource_config=request.datasource_config,
                steps=count_steps,
                additional_datasources=_get_additional_datasources(count_steps, analysis_pipeline),
            )
            result_data = await_compute_worker_result(engine, job_id=job_id)
        _raise_engine_failure(result_data, operation="row_count", datasource_id=request.datasource_id, failure_prefix="Row count")
        row_count = result_data.get("data", {}).get("row_count", 0)
        _apply_run_finalization(
            _single_tab_run_finalization(
                run_id,
                existing_result=_load_compute_worker_run_result_json(run_id),
                result_data=result_data,
                started_perf=started_perf,
                tab_id=tab_id,
                tab_name=tab_name,
                total_steps=len(count_steps),
                summary_meta={"row_count": row_count},
                log_message=f"Computed row count: {row_count}",
                query_plan=result_data.get("query_plan"),
                current_step=None,
            )
        )
        return StepRowCountResponse(step_id=request.target_step_id, row_count=row_count)
    except Exception as exc:
        try:
            _raise_if_compute_worker_run_cancelled(run_id)
        except BuildCancelledError as cancel_exc:
            raise cancel_exc from exc

        reported = _reported_row_count_error(exc)
        _apply_run_finalization(
            _single_tab_run_finalization(
                run_id,
                existing_result=_load_compute_worker_run_result_json(run_id),
                result_data=result_data,
                started_perf=started_perf,
                tab_id=tab_id,
                tab_name=tab_name,
                total_steps=len(count_steps),
                error=reported,
                current_step=None,
            )
        )
        if reported is exc:
            raise
        raise reported from exc


def export_data(
    manager: ProcessManager,
    target_step_id: str,
    analysis_pipeline: dict,
    filename: str = "export",
    iceberg_options: dict | None = None,
    analysis_id: str | None = None,
    tab_id: str | None = None,
    result_id: str | None = None,
    build_mode: str = "full",
    job_started: Callable[[str, ComputeWorker], None] | None = None,
    on_write_start: Callable[[float | None], None] | None = None,
    on_write_complete: Callable[[float], None] | None = None,
    compute_worker_identity: compute_pb2.ComputeWorkerIdentity | None = None,
    build_id: str | None = None,
    publication_claim: ClaimedBuildJob | None = None,
    worker_id: str | None = None,
) -> ExportDatasourceResult:
    if result_id is None:
        raise ValueError("Output exports require result_id")
    if not iceberg_options or not isinstance(iceberg_options.get("branch"), str):
        raise ValueError("Iceberg exports require iceberg_options with an explicit branch")
    if build_id is not None:
        if publication_claim is None or worker_id is None:
            raise ValueError("Queued build exports require an active publication claim and worker identity")
        if publication_claim.build_id != build_id:
            raise ValueError("Output publication claim does not belong to the build")

    started_perf = time.perf_counter()
    request = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id, analysis_id=analysis_id, operation="export")
    datasource_id = request.datasource_id
    datasource_config = request.datasource_config
    existing_output_metadata = client_from_env().datasource_metadata(namespace=get_namespace(), datasource_id=result_id)
    output_hidden = existing_output_metadata.is_hidden if existing_output_metadata.found else True
    export_steps = _steps_through_target(request.steps, request.target_step_id)

    if compute_worker_identity is None:
        compute_worker_identity = (
            _build_compute_worker_identity(build_id)
            if build_id is not None
            else default_stateless_compute_worker_identity(_pipeline_analysis_id(analysis_pipeline))
        )
    additional_datasources = _get_additional_datasources(export_steps, analysis_pipeline)
    source_metadata = client_from_env().datasource_metadata(namespace=get_namespace(), datasource_id=datasource_id)
    source_datasource_name = source_metadata.name if source_metadata.found else None

    tmp_output = _secure_temp_path(suffix=".parquet")
    tab_name = _tab_name_from_pipeline(analysis_pipeline, tab_id)

    try:
        with manager.acquire_engine(compute_worker_identity) as engine:
            job_id = engine.export(
                datasource_config=datasource_config,
                steps=export_steps,
                output_path=tmp_output,
                export_format="parquet",
                additional_datasources=additional_datasources,
            )
            if job_started is not None:
                job_started(job_id, engine)
            result_data = await_compute_worker_result(engine, job_id=job_id)
        _raise_engine_failure(result_data, operation="export", datasource_id=datasource_id, failure_prefix="Export")
        if build_id is not None:
            _raise_if_build_cancelled(build_id)

        data = result_data.get("data", {})
        row_count = data.get("row_count", 0)
        logger.info(f"Export completed: {row_count} rows written to parquet")

        staged_result = _strip_staged_notification_columns(tmp_output)
        if staged_result is not None:
            data = strip_staged_preview(data)

        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        timeout_warning_ms = _output_timeout_warning_ms(analysis_pipeline, tab_id)
        duration_exceeded = timeout_warning_ms is not None and duration_ms > timeout_warning_ms

        result_meta: dict = {
            "row_count": data.get("row_count", 0),
            "export_format": data.get("export_format"),
            "file_size_bytes": os.path.getsize(tmp_output),
        }
        if query_plans := data.get("query_plans"):
            result_meta["query_plans"] = query_plans
        if timeout_warning_ms is not None:
            result_meta["build_timeout_warning_ms"] = timeout_warning_ms
            result_meta["duration_exceeded_warning"] = duration_exceeded

        hc_datasource_id = str(result_id)
        hc_checks = client_from_env().list_healthchecks(namespace=get_namespace(), datasource_id=hc_datasource_id)
        hc_results: list[HealthCheckResult] = []
        logger.info(f"Health checks: found {len(hc_checks)} enabled for datasource {hc_datasource_id}")
        if hc_checks:
            hc_lf = pl.scan_parquet(tmp_output)
            try:
                hc_results = run_healthchecks(hc_checks, hc_lf)
            except Exception as exc:
                if any(check.critical for check in hc_checks):
                    raise PipelineExecutionError(
                        "Critical health checks failed to run",
                        details={"datasource_id": hc_datasource_id, "error": str(exc)},
                    ) from exc
                logger.exception("Health check evaluation failed")
            else:
                if publication_claim is None:
                    persist_results(hc_results)
                critical_ids = {check.id for check in hc_checks if check.critical}
                critical_failed = [result for result in hc_results if not result.passed and result.healthcheck_id in critical_ids]
                if critical_failed:
                    raise PipelineExecutionError(
                        "Critical health checks failed",
                        details={
                            "datasource_id": hc_datasource_id,
                            "failed": [{"healthcheck_id": result.healthcheck_id, "message": result.message} for result in critical_failed],
                        },
                    )
                failed_count = sum(1 for r in hc_results if not r.passed)
                logger.info(f"Health checks: {len(hc_results)} evaluated, {failed_count} failed")

        status, hc_summary, hc_details = resolve_build_status(hc_results, hc_checks)

        analysis_name = client_from_env().analysis_name(namespace=get_namespace(), analysis_id=request.analysis_id) if request.analysis_id else None

        output_notification = datasource_config.get("notification")
        if not isinstance(output_notification, dict):
            tab_notification = _tab_output_config(analysis_pipeline, tab_id).get("notification")
            if isinstance(tab_notification, dict):
                output_notification = tab_notification
        excluded = datasource_config.get("excluded_recipients")
        if output_notification and excluded is not None:
            output_notification = {**output_notification, "excluded_recipients": excluded}

        namespace = iceberg_options.get("namespace", "outputs")
        branch_name = iceberg_options["branch"]
        safe_branch = re.sub(r"[^a-zA-Z0-9_]+", "_", branch_name).strip("_")
        published_table_name = f"{result_id}_{safe_branch}"
        published_export_base = object_store_url("exports", str(result_id), namespace=get_namespace())
        if publication_claim is None:
            table_name = published_table_name
            export_base = published_export_base
        else:
            safe_claim_token = re.sub(r"[^a-zA-Z0-9_]+", "_", publication_claim.claim_token).strip("_")
            table_name = f"{published_table_name}_claim_{safe_claim_token}"
            export_base = join_object_store_url(published_export_base, "claims", publication_claim.claim_token)
        table_path = join_object_store_url(export_base, branch_name)
        warehouse_path = object_store_url("exports", namespace=get_namespace())
        final_table_name: str = table_name
        final_metadata_path: str = export_base
        ensure_bucket_exists()

        catalog = load_runtime_catalog("local", type="sql", uri=settings.database_url, warehouse=warehouse_path, **object_store_storage_options())
        ensure_catalog_namespace(catalog, namespace)
        identifier = f"{namespace}.{table_name}"

        read_duration_ms = result_data.get("read_duration_ms")
        if on_write_start is not None:
            on_write_start(read_duration_ms)

        write_started = time.perf_counter()
        arrow_table = pq.read_table(tmp_output)
        table_exists = catalog.table_exists(identifier)

        if publication_claim is not None:
            # Claim rebuilds never drop: a drop purges metadata files that
            # concurrent readers may still be resolving. The claim table is
            # seeded/overwritten in place, swapping snapshots atomically.
            previous_arrow: pa.Table | None = None
            previous_config = existing_output_metadata.config
            if build_mode == "incremental" and isinstance(previous_config, dict):
                previous_namespace = previous_config.get("namespace")
                previous_table_name = previous_config.get("table")
                if isinstance(previous_namespace, str) and isinstance(previous_table_name, str):
                    previous_identifier = f"{previous_namespace}.{previous_table_name}"
                    if catalog.table_exists(previous_identifier):
                        previous_arrow = catalog.load_table(previous_identifier).scan().to_arrow()
            if table_exists:
                # Overwrite replaces the staged content exactly, matching the
                # previous drop+create semantics without purging metadata that
                # concurrent readers may still be resolving.
                iceberg_table = catalog.load_table(identifier)
                final = pa.concat_tables([previous_arrow, arrow_table], promote_options="default") if previous_arrow is not None else arrow_table
                sync_iceberg_schema(iceberg_table, final.schema)
                iceberg_table.overwrite(final)
            else:
                initial_schema = previous_arrow.schema if previous_arrow is not None else arrow_table.schema
                iceberg_table = catalog.create_table(identifier, schema=initial_schema, location=table_path)
                if previous_arrow is not None:
                    iceberg_table.append(previous_arrow)
                    sync_iceberg_schema(iceberg_table, arrow_table.schema)
                iceberg_table.append(arrow_table)
        elif table_exists:
            iceberg_table = catalog.load_table(identifier)
            if build_mode == "incremental":
                iceberg_table.append(arrow_table)
            else:
                try:
                    sync_iceberg_schema(iceberg_table, arrow_table.schema)
                    iceberg_table.overwrite(arrow_table)
                except Exception as exc:
                    # Incompatible schema evolution (e.g. a conflicting column
                    # type change) cannot be applied in place. Write a fresh
                    # revision table and repoint the published config at it;
                    # never drop the table readers may still be resolving.
                    logger.warning("In-place rebuild of %s failed (%s); writing revision table instead", identifier, exc)
                    revision_token = uuid.uuid4().hex[:8]
                    revision_table_name = f"{table_name}_rev{revision_token}"
                    revision_location = join_object_store_url(table_path, f"revision_{revision_token}")
                    iceberg_table = catalog.create_table(f"{namespace}.{revision_table_name}", schema=arrow_table.schema, location=revision_location)
                    iceberg_table.append(arrow_table)
                    final_table_name = revision_table_name
                    final_metadata_path = revision_location
        else:
            iceberg_table = catalog.create_table(identifier, schema=arrow_table.schema, location=table_path)
            iceberg_table.append(arrow_table)

        if publication_claim is None:
            # Best-effort reclaim of superseded revision directories from
            # earlier schema-incompatible rebuilds. Keep the revision this
            # build published and the one the previous config pointed at.
            keep = {final_metadata_path.rstrip("/")}
            previous_config = existing_output_metadata.config if existing_output_metadata.found else None
            previous_metadata_path = previous_config.get("metadata_path") if isinstance(previous_config, dict) else None
            if isinstance(previous_metadata_path, str):
                keep.add(previous_metadata_path.rstrip("/"))
            try:
                prune_superseded_revisions(table_path, keep_urls=frozenset(keep))
            except Exception as exc:
                logger.warning("Revision GC failed for %s: %s", table_path, exc)

        current_snapshot = iceberg_table.current_snapshot()
        snapshot_id = str(current_snapshot.snapshot_id) if current_snapshot else None
        snapshot_timestamp_ms = int(current_snapshot.timestamp_ms) if current_snapshot else None

        datasource_name = iceberg_options.get("table_name", "exported_data")
        iceberg_ds_config = {
            "catalog_type": "sql",
            "warehouse": warehouse_path,
            "namespace": namespace,
            "table": final_table_name,
            "table_name": datasource_name,
            "metadata_path": final_metadata_path,
            "branch": branch_name,
            "namespace_name": get_namespace(),
            "reader": "native",
        }
        if tab_id:
            iceberg_ds_config["analysis_tab_id"] = str(tab_id)
        iceberg_ds_config = _set_snapshot_metadata(iceberg_ds_config, snapshot_id, snapshot_timestamp_ms, metadata_file=iceberg_table.metadata_location)
        schema_cache = _schema_cache_payload_from_arrow(arrow_table.schema, data)
        write_duration_ms = (time.perf_counter() - write_started) * 1000
        if on_write_complete is not None:
            on_write_complete(write_duration_ms)
        result_meta["datasource_id"] = result_id
        result_meta["datasource_name"] = datasource_name
        if snapshot_id:
            result_meta["snapshot_id"] = snapshot_id
        if snapshot_timestamp_ms is not None:
            result_meta["snapshot_timestamp_ms"] = snapshot_timestamp_ms
        notification_deliveries = _prepare_pipeline_notifications(
            context={
                "analysis_name": analysis_name,
                "status": status,
                "duration_ms": str(duration_ms),
                "row_count": str(row_count),
                "datasource_id": hc_datasource_id,
                "format": "parquet",
                "destination": "datasource",
                "healthcheck_summary": hc_summary,
                "healthcheck_details": hc_details,
                "duration_exceeded_warning": duration_exceeded,
                "build_timeout_warning_ms": timeout_warning_ms,
            },
            output_notification=output_notification,
        )
        notification_deliveries.extend(staged_result or [])
        try:
            uuid.UUID(result_id)
        except ValueError, AttributeError:
            raise ValueError(f"result_id must be a valid UUID, got: {result_id!r}") from None
        target_ds = client_from_env().upsert_output_datasource(
            namespace=get_namespace(),
            result_id=result_id,
            name=datasource_name,
            source_type=str(DataSourceType.ICEBERG),
            config=iceberg_ds_config,
            schema_cache=schema_cache,
            analysis_id=request.analysis_id,
            is_hidden=output_hidden,
            keep_schema_cache=build_mode == "incremental" and publication_claim is None,
            publication=publication_claim,
            worker_id=worker_id,
            build_result_json=(
                {
                    **result_meta,
                    "source_datasource_id": datasource_id,
                    "source_datasource_name": source_datasource_name,
                    "current_output_id": result_id,
                    "current_output_name": datasource_name,
                    "current_tab_id": tab_id,
                    "current_tab_name": tab_name,
                    "branch": branch_name,
                    "duration_ms": duration_ms,
                    "duration_exceeded_warning": duration_exceeded,
                    "build_timeout_warning_ms": timeout_warning_ms,
                }
                if publication_claim is not None
                else None
            ),
            notification_deliveries=notification_deliveries,
        )
        if publication_claim is not None:
            persist_results(hc_results)
        return ExportDatasourceResult(datasource_id=str(target_ds.id), datasource_name=datasource_name, result_meta=result_meta)
    except BuildCancelledError:
        raise
    except Exception as exc:
        if build_id is None:
            raise
        try:
            _raise_if_build_cancelled(build_id)
        except BuildCancelledError as cancel_exc:
            raise cancel_exc from exc
        assert publication_claim is not None
        assert worker_id is not None
        initial_output_name = iceberg_options.get("table_name", filename)
        client_from_env().update_build_result(
            namespace=get_namespace(),
            build_id=build_id,
            job_id=publication_claim.job_id,
            worker_id=worker_id,
            claim_token=publication_claim.claim_token,
            lease_generation=publication_claim.lease_generation,
            result_json={
                "source_datasource_id": datasource_id,
                "source_datasource_name": source_datasource_name,
                "current_output_id": result_id,
                "current_output_name": initial_output_name if isinstance(initial_output_name, str) else filename,
                "current_tab_id": tab_id,
                "current_tab_name": tab_name,
                "branch": iceberg_options.get("branch"),
            },
        )
        raise
    finally:
        if os.path.exists(tmp_output):
            os.unlink(tmp_output)


def download_step(
    manager: ProcessManager,
    target_step_id: str,
    analysis_pipeline: dict,
    export_format: str = "csv",
    filename: str = "download",
    analysis_id: str | None = None,
    tab_id: str | None = None,
):
    """Download the result of a pipeline step in a specific format."""
    from runtime.export_formats import get_export_format

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    request = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id, analysis_id=analysis_id, operation="download")
    if not request.analysis_id:
        raise ValueError("Download requires analysis_id")

    target_step_id = request.target_step_id
    steps = [step for step in request.steps if step.get("type") != "download"]
    target_step = next((step for step in request.steps if step.get("id") == target_step_id), None)
    if target_step and target_step.get("type") == "download":
        depends_on = target_step.get("depends_on") or []
        parent_id = str(depends_on[0]) if depends_on and depends_on[0] else None
        if parent_id:
            target_step_id = parent_id
        elif steps:
            target_step_id = str(steps[-1].get("id") or "source")
        else:
            target_step_id = "source"
    download_steps = _steps_through_target(steps, target_step_id)

    tab_name = _tab_name_from_pipeline(analysis_pipeline, tab_id)
    request_payload = _ensure_request_branch(
        {
            "analysis_id": request.analysis_id,
            "datasource_id": request.datasource_id,
            "steps": download_steps,
            "target_step_id": target_step_id,
            "format": export_format,
            "filename": filename,
            "tab_id": tab_id,
            "analysis_pipeline": analysis_pipeline,
        },
        request.datasource_config,
    )
    additional_datasources = _get_additional_datasources(download_steps, analysis_pipeline)
    export_fmt = get_export_format(export_format)
    download_name = f"{filename}{export_fmt.extension}"

    tmp_output = _secure_temp_path(suffix=export_fmt.extension)
    run_id = None
    result_data: dict | None = None
    try:
        with manager.acquire_engine(default_stateless_compute_worker_identity(_pipeline_analysis_id(analysis_pipeline))) as engine:
            run_id = client_from_env().create_compute_worker_run(
                namespace=get_namespace(),
                analysis_id=request.analysis_id,
                datasource_id=request.datasource_id,
                kind="download",
                status="running",
                request_json=request_payload,
                result_json=_initial_live_run_result(
                    current_tab_id=tab_id,
                    current_tab_name=tab_name,
                    total_steps=len(download_steps),
                    resource_config=resource_summary(engine),
                ),
                created_at=started_at,
                progress=0.0,
            )
            job_id = engine.preview(
                datasource_config=request.datasource_config,
                steps=download_steps,
                row_limit=10_000_000,  # Large limit to get all data for download
                offset=0,
                additional_datasources=additional_datasources,
            )
            result_data = await_compute_worker_result(engine, job_id=job_id)
        _raise_engine_failure(result_data, operation="download", datasource_id=request.datasource_id, failure_prefix="Download")

        data = result_data.get("data", {})
        schema = data.get("schema", {})
        if not schema:
            raise ValueError("No data to download")

        from operations.fill_null import get_polars_type

        schema_types = {name: get_polars_type(dtype) or pl.Utf8() for name, dtype in schema.items()}
        df = pl.DataFrame(data.get("data", []), schema=schema_types)
        write_started = time.perf_counter()
        export_fmt.write_df(df, tmp_output)
        write_duration_ms = (time.perf_counter() - write_started) * 1000
        _ensure_download_size(tmp_output)
        with open(tmp_output, "rb") as f:
            file_bytes = f.read()

        _apply_run_finalization(
            _single_tab_run_finalization(
                run_id,
                existing_result=_load_compute_worker_run_result_json(run_id),
                result_data=result_data,
                started_perf=started_perf,
                tab_id=tab_id,
                tab_name=tab_name,
                total_steps=len(download_steps),
                summary_meta={"filename": download_name, "format": export_format},
                log_message=f"Prepared download {download_name}",
                resource_config=resource_summary(engine),
                write_duration_ms=write_duration_ms,
                query_plan=result_data.get("query_plan"),
            )
        )
        return file_bytes, download_name, export_fmt.content_type
    except Exception as exc:
        if run_id is None:
            raise
        _apply_run_finalization(
            _single_tab_run_finalization(
                run_id,
                existing_result=_load_compute_worker_run_result_json(run_id),
                result_data=result_data,
                started_perf=started_perf,
                tab_id=tab_id,
                tab_name=tab_name,
                total_steps=len(download_steps),
                error=exc,
                resource_config=resource_summary(engine),
                query_plan=result_data.get("query_plan") if isinstance(result_data, dict) else None,
            )
        )
        raise
    finally:
        if os.path.exists(tmp_output):
            os.remove(tmp_output)


def _build_execution_tab(pipeline: dict) -> dict:
    """The single tab to execute for this build.

    Builds are always tab-scoped: the tab's input datasource inlines the
    upstream tabs' steps into its own pipeline, so upstream tabs are
    recomputed lazily as part of it and are not built separately.
    """
    tabs = pipeline.get("tabs", [])
    if not tabs:
        raise ValueError("analysis_pipeline missing tabs")

    tab_id = pipeline.get("tab_id")
    if not isinstance(tab_id, str) or not tab_id:
        raise ValueError("analysis_pipeline missing tab_id")
    selected = next((tab for tab in tabs if tab.get("id") == tab_id), None)
    if selected is None:
        raise ValueError(f"analysis_pipeline missing tab {tab_id}")
    return selected


def _resolve_live_output_metadata(output_config: dict, tab_name: str) -> tuple[str | None, str | None]:
    output_id = output_config.get("result_id") if isinstance(output_config.get("result_id"), str) else None
    iceberg_cfg = output_config.get("iceberg")
    if isinstance(iceberg_cfg, dict):
        table_name = iceberg_cfg.get("table_name")
        if isinstance(table_name, str) and table_name.strip():
            return output_id, table_name.strip()

    filename = output_config.get("filename")
    if isinstance(filename, str) and filename.strip():
        return output_id, filename.strip()
    if output_id:
        return output_id, output_id
    return None, tab_name


def _count_total_build_steps(tab: dict) -> int:
    steps = tab.get("steps", [])
    if "filename" not in tab.get("output", {}):
        return max(len(steps), 1)
    # Synthetic read stage + pipeline steps + synthetic write stage.
    return len(steps) + 2


def _stage_event(stage: _SyntheticBuildStage, event_type: str, **fields: object) -> dict[str, object]:
    return {
        "type": event_type,
        "build_step_index": stage.build_step_index,
        "step_index": stage.step_index,
        "step_id": stage.step_id,
        "step_name": stage.step_name,
        "step_type": stage.step_type,
        **fields,
    }


async def _stream_engine_events(
    *,
    build: RuntimeBuild,
    analysis_id: str,
    engine,
    job_id: str,
    compute_worker_run_id: str | None,
    total_steps: int,
    started_perf: float,
    tab_id: str | None,
    tab_name: str | None,
    current_output_id: str | None,
    current_output_name: str | None,
    emitter: BuildEmitter | None,
    read_stage: _SyntheticBuildStage,
) -> None:
    completed_steps = 0

    async def emit_progress(current_step: object, current_step_index: object, *, progress_without_steps: float = 1.0) -> None:
        await _emit_progress(
            emitter,
            build=build,
            analysis_id=analysis_id,
            progress=(completed_steps / total_steps) if total_steps else progress_without_steps,
            elapsed_ms=int((time.perf_counter() - started_perf) * 1000),
            completed_steps=completed_steps,
            total_steps=total_steps,
            current_step=current_step if isinstance(current_step, str) else None,
            current_step_index=current_step_index if isinstance(current_step_index, int) else None,
            tab_id=tab_id,
            tab_name=tab_name,
            current_output_id=current_output_id,
            current_output_name=current_output_name,
            compute_worker_run_id=compute_worker_run_id,
        )

    draining = False
    drain_deadline: float | None = None
    while True:
        poll_timeout = 0.2 if not draining else 0.05
        event = await run_engine_io_in_thread(engine.get_progress_event, poll_timeout, job_id)
        if event is None:
            if draining:
                if drain_deadline is None:
                    drain_deadline = time.monotonic() + 0.5
                if time.monotonic() >= drain_deadline:
                    return
                continue
            if engine.current_job_id != job_id:
                draining = True
                drain_deadline = time.monotonic() + 0.5
            continue

        payload = dict(event.event)
        emitted_type = str(payload.get("type") or "")
        # Build stream events must stay in build context even if engine-internal events
        # include preview-oriented metadata.
        payload["current_kind"] = build.current_kind
        if emitted_type in {"step_start", "step_complete", "step_failed"} and not read_stage.completed:
            read_stage.completed = True
            await emit_build_event(
                emitter,
                event=build_event(
                    build,
                    analysis_id,
                    _stage_event(
                        read_stage,
                        "step_complete",
                        duration_ms=int((time.perf_counter() - read_stage.started_at) * 1000),
                        row_count=None,
                        total_steps=total_steps,
                        tab_id=tab_id,
                        tab_name=tab_name,
                        current_output_id=current_output_id,
                        current_output_name=current_output_name,
                        compute_worker_run_id=compute_worker_run_id,
                    ),
                ),
            )
            completed_steps += 1
            await emit_progress(read_stage.step_name, read_stage.build_step_index)

        step_index = payload.get("step_index")
        if isinstance(step_index, int):
            # Engine steps follow the synthetic read stage.
            payload["build_step_index"] = 1 + step_index
            payload["step_index"] = 1 + step_index
        payload["tab_id"] = tab_id
        payload["tab_name"] = tab_name
        payload["current_output_id"] = current_output_id
        payload["current_output_name"] = current_output_name
        payload["compute_worker_run_id"] = payload.get("compute_worker_run_id") or compute_worker_run_id

        if emitted_type not in {"compute_start", "compute_complete"}:
            await emit_build_event(emitter, event=build_event(build, analysis_id, payload))

        if emitted_type == "step_complete":
            completed_steps += 1
            await emit_progress(payload.get("step_name"), payload.get("build_step_index"))
        if emitted_type == "compute_start":
            await emit_progress("Computing", None)
        if emitted_type == "step_failed":
            await emit_progress(payload.get("step_name"), payload.get("build_step_index"), progress_without_steps=0.0)
            return


def _start_stream_tasks(
    loop: asyncio.AbstractEventLoop, *, build: RuntimeBuild, engine, job_id: str, **stream_kwargs
) -> tuple[asyncio.Task | None, asyncio.Task | None]:
    build.resource_config = compute_schemas.BuildResourceConfigSummary.model_validate(resource_summary(engine))
    if loop.is_closed() or not loop.is_running():
        logger.warning("Skipping build stream tasks for job %s because the event loop is unavailable", job_id)
        return None, None

    future: concurrent.futures.Future[tuple[asyncio.Task, asyncio.Task]] = concurrent.futures.Future()

    def assign() -> None:
        try:
            progress_task = loop.create_task(_stream_engine_events(build=build, engine=engine, job_id=job_id, **stream_kwargs))
            resource_task = loop.create_task(
                stream_resource_events(
                    build=build,
                    analysis_id=stream_kwargs["analysis_id"],
                    engine=engine,
                    emitter=stream_kwargs["emitter"],
                    tab_id=stream_kwargs["tab_id"],
                    tab_name=stream_kwargs["tab_name"],
                )
            )
            progress_task.add_done_callback(observe_stream_task)
            resource_task.add_done_callback(observe_stream_task)
            future.set_result((progress_task, resource_task))
        except Exception as exc:
            future.set_exception(exc)

    try:
        loop.call_soon_threadsafe(assign)
    except RuntimeError as exc:
        logger.warning("Skipping build stream tasks for job %s because the event loop rejected scheduling: %s", job_id, exc)
        return None, None

    try:
        return future.result()
    except RuntimeError as exc:
        logger.warning("Skipping build stream tasks for job %s because scheduling did not complete: %s", job_id, exc)
        return None, None


async def run_analysis_build_stream(
    manager: ProcessManager,
    pipeline: dict | None,
    *,
    build: RuntimeBuild,
    emitter: BuildEmitter | None,
    publication_claim: ClaimedBuildJob | None = None,
    worker_id: str | None = None,
) -> dict:
    if not isinstance(pipeline, dict):
        raise ValueError("analysis_pipeline is required")

    tab = _build_execution_tab(pipeline)
    analysis_id = pipeline.get("analysis_id")
    analysis_id_value = str(analysis_id) if analysis_id is not None else ""
    total_steps = _count_total_build_steps(tab)
    build.total_steps = total_steps
    started_perf = time.perf_counter()

    async def emit(payload: dict[str, object]) -> None:
        await emit_build_event(emitter, event=build_event(build, analysis_id_value, payload))

    await emit({"type": "log", "level": compute_schemas.BuildLogLevel.INFO.value, "message": f"Starting build for {build.analysis_name}"})
    await _emit_progress(
        emitter,
        build=build,
        analysis_id=analysis_id_value,
        progress=0.0,
        elapsed_ms=0,
        completed_steps=0,
        total_steps=total_steps,
        current_step=None,
        current_step_index=None,
        tab_id=None,
        tab_name=None,
        compute_worker_run_id=build.current_compute_worker_run_id,
    )

    build_identity = _build_compute_worker_identity(build.build_id)
    results: list[dict] = []
    loop = asyncio.get_running_loop()

    async def build_tab() -> BuildCancelledError | None:
        tab_id = str(tab.get("id", "unknown"))
        tab_name = str(tab.get("name", "unnamed"))
        tab_datasource_id = tab.get("datasource", {}).get("id")
        steps = tab.get("steps", [])
        output_config = tab.get("output", {})
        if not tab_datasource_id:
            return None

        build.current_kind = ComputeWorkerRunKind.BUILD.value
        build.current_datasource_id = str(tab_datasource_id)
        build.current_tab_id = tab_id
        build.current_tab_name = tab_name

        if "filename" not in output_config:
            error = f"Tab {tab_id} missing output configuration"
            results.append({"tab_id": tab_id, "tab_name": tab_name, "status": BuildTabStatus.FAILED, "error": error})
            await emit({"type": "log", "level": compute_schemas.BuildLogLevel.ERROR.value, "message": error, "tab_id": tab_id, "tab_name": tab_name})
            return None

        raw_filename = output_config.get("filename")
        if not isinstance(raw_filename, str) or not raw_filename.strip():
            raise ValueError(f"Build output filename is required for tab {tab_id}")
        result_id = output_config.get("result_id")
        current_output_id, current_output_name = _resolve_live_output_metadata(output_config, tab_name)
        iceberg_cfg = output_config.get("iceberg")
        if not isinstance(iceberg_cfg, dict):
            raise ValueError(f"Build output iceberg config is required for tab {tab_id}")
        for key in ("table_name", "namespace", "branch"):
            value = iceberg_cfg.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Build output iceberg.{key} is required for tab {tab_id}")
        build_mode = output_config.get("build_mode")
        if build_mode not in {"full", "incremental", "recreate"}:
            raise ValueError(f"Build output build_mode is required for tab {tab_id}")
        build.current_output_id = current_output_id
        build.current_output_name = current_output_name

        tab_fields = {"tab_id": tab_id, "tab_name": tab_name, "current_output_id": current_output_id, "current_output_name": current_output_name}
        progress_task: asyncio.Task | None = None
        resource_task: asyncio.Task | None = None
        cancellation = _BuildJobCancellation(manager, build_identity, namespace=build.namespace)
        read_stage = _SyntheticBuildStage(
            step_id=f"{tab_id}:initial_read",
            step_name="Initial Read",
            step_type="read",
            build_step_index=0,
            step_index=0,
            started_at=time.perf_counter(),
        )
        write_stage = _SyntheticBuildStage(
            step_id=f"{tab_id}:write_output",
            step_name="Write Output",
            step_type="write",
            build_step_index=len(steps) + 1,
            step_index=len(steps) + 1,
            started_at=read_stage.started_at,
        )

        def stage_event(stage: _SyntheticBuildStage, event_type: str, **fields: object) -> dict[str, object]:
            return _stage_event(stage, event_type, **fields, total_steps=total_steps, **tab_fields, compute_worker_run_id=build.current_compute_worker_run_id)

        async def emit_stage_progress(completed_steps: int, stage: _SyntheticBuildStage) -> None:
            await _emit_progress(
                emitter,
                build=build,
                analysis_id=analysis_id_value,
                progress=(completed_steps / total_steps) if total_steps else 1.0,
                elapsed_ms=int((time.perf_counter() - started_perf) * 1000),
                completed_steps=completed_steps,
                total_steps=total_steps,
                current_step=stage.step_name,
                current_step_index=stage.build_step_index,
                tab_id=tab_id,
                tab_name=tab_name,
                current_output_id=current_output_id,
                current_output_name=current_output_name,
                compute_worker_run_id=build.current_compute_worker_run_id,
            )

        def handle_job_started(job_id: str, engine: ComputeWorker) -> None:
            nonlocal progress_task, resource_task
            if not job_id:
                raise ValueError("Build engine job ID is required")
            cancellation.job_started(job_id)
            run_started: dict[str, object] = {
                "type": "progress",
                "progress": 0.0,
                "elapsed_ms": 0,
                "estimated_remaining_ms": None,
                "current_step": None,
                "current_step_index": None,
                "total_steps": total_steps,
                **tab_fields,
            }
            asyncio.run_coroutine_threadsafe(emit(run_started), loop).result()
            progress_task, resource_task = _start_stream_tasks(
                loop,
                build=build,
                engine=engine,
                job_id=job_id,
                analysis_id=analysis_id_value,
                compute_worker_run_id=build.current_compute_worker_run_id,
                total_steps=total_steps,
                started_perf=started_perf,
                emitter=emitter,
                read_stage=read_stage,
                **tab_fields,
            )

        def stage_duration_ms(duration_ms: float | None, synthetic_stage: _SyntheticBuildStage) -> int:
            if duration_ms is not None:
                return int(duration_ms)
            return int((time.perf_counter() - synthetic_stage.started_at) * 1000)

        def handle_write_start(read_duration_ms: float | None) -> None:
            if loop.is_closed() or not loop.is_running():
                return

            async def emit_write_start() -> None:
                if not read_stage.completed:
                    read_stage_duration_ms = stage_duration_ms(read_duration_ms, read_stage)
                    read_stage.completed = True
                    await emit(stage_event(read_stage, "step_complete", duration_ms=read_stage_duration_ms, row_count=None))
                    await emit_stage_progress(1, read_stage)
                write_stage.started = True
                write_stage.started_at = time.perf_counter()
                await emit(stage_event(write_stage, "step_start"))

            asyncio.run_coroutine_threadsafe(emit_write_start(), loop).result()

        def handle_write_complete(write_duration_ms: float) -> None:
            if loop.is_closed() or not loop.is_running():
                return

            async def emit_write_complete() -> None:
                write_stage_duration_ms = stage_duration_ms(write_duration_ms, write_stage)
                write_stage.completed = True
                await emit(stage_event(write_stage, "step_complete", duration_ms=write_stage_duration_ms, row_count=None))
                await emit_stage_progress(len(steps) + 2, write_stage)

            asyncio.run_coroutine_threadsafe(emit_write_complete(), loop).result()

        def run_export_job() -> ExportDatasourceResult:
            cancellation.raise_if_cancelled()
            return export_data(
                manager=manager,
                target_step_id=steps[-1].get("id", "source") if steps else "source",
                analysis_pipeline=pipeline,
                filename=raw_filename.strip(),
                iceberg_options={key: iceberg_cfg[key] for key in ("table_name", "namespace", "branch")},
                analysis_id=analysis_id_value,
                tab_id=tab_id,
                result_id=result_id,
                build_mode=build_mode,
                job_started=handle_job_started,
                on_write_start=handle_write_start,
                on_write_complete=handle_write_complete,
                compute_worker_identity=build_identity,
                build_id=build.build_id,
                publication_claim=publication_claim,
                worker_id=worker_id,
            )

        try:
            await emit({"type": "log", "level": compute_schemas.BuildLogLevel.INFO.value, "message": f"Starting tab {tab_name}", **tab_fields})
            read_stage.started = True
            await emit(stage_event(read_stage, "step_start"))
            export_result = await run_compute_in_thread(run_export_job, cancel_work=cancellation.cancel, expected_cancel_errors=(BuildCancelledError,))
            if progress_task is not None:
                _ = await progress_task
            await stop_stream_task(resource_task)
            build.current_output_id = export_result.datasource_id
            build.current_output_name = export_result.datasource_name
            results.append(
                {
                    "tab_id": tab_id,
                    "tab_name": tab_name,
                    "status": BuildTabStatus.SUCCESS,
                    "output_id": export_result.datasource_id,
                    "output_name": export_result.datasource_name,
                }
            )
            return None
        except BuildCancelledError as exc:
            if progress_task is not None:
                with contextlib.suppress(Exception):
                    _ = await progress_task
            await stop_stream_task(resource_task)
            await emit({"type": "log", "level": compute_schemas.BuildLogLevel.WARNING.value, "message": "Build cancellation requested", **tab_fields})
            return exc
        except Exception as exc:
            if progress_task is not None:
                with contextlib.suppress(Exception):
                    _ = await progress_task
            await stop_stream_task(resource_task)
            failed_stage = write_stage if write_stage.started and not write_stage.completed else read_stage if not read_stage.completed else None
            if failed_stage is not None:
                await emit(stage_event(failed_stage, "step_failed", error=str(exc)))
            results.append(
                {
                    "tab_id": tab_id,
                    "tab_name": tab_name,
                    "status": BuildTabStatus.FAILED,
                    "output_id": current_output_id,
                    "output_name": current_output_name,
                    "error": str(exc),
                }
            )
            await emit({"type": "log", "level": compute_schemas.BuildLogLevel.ERROR.value, "message": str(exc), **tab_fields})
            return None

    cancellation_error = await build_tab()
    tabs_built = sum(1 for result in results if result["status"] == BuildTabStatus.SUCCESS)
    elapsed_ms = int((time.perf_counter() - started_perf) * 1000)
    base = BuildEventContext.from_build(
        build,
        analysis_id_value,
        current_output_id=build.current_output_id,
        current_output_name=build.current_output_name,
        compute_worker_run_id=build.current_compute_worker_run_id,
    )
    terminal_fields: dict[str, object] = {
        "build_id": base.build_id,
        "analysis_id": base.analysis_id,
        "emitted_at": base.emitted_at,
        "current_kind": ComputeWorkerRunKind.parse(base.current_kind),
        "current_datasource_id": base.current_datasource_id,
        "tab_id": base.tab_id,
        "tab_name": base.tab_name,
        "current_output_id": base.current_output_id,
        "current_output_name": base.current_output_name,
        "compute_worker_run_id": base.compute_worker_run_id,
        "elapsed_ms": elapsed_ms,
        "total_steps": total_steps,
        "tabs_built": tabs_built,
        "results": [compute_schemas.BuildTabResult.model_validate(item) for item in results],
        "duration_ms": elapsed_ms,
    }
    terminal_event: compute_schemas.BuildEvent
    if cancellation_error is not None:
        cancelled_at = cancellation_error.cancelled_at
        terminal_event = compute_schemas.BuildCancelledEvent.model_validate(
            {
                **terminal_fields,
                "progress": 0.0,
                "cancelled_at": datetime.fromisoformat(cancelled_at) if cancelled_at is not None else datetime.now(UTC),
                "cancelled_by": cancellation_error.cancelled_by,
            }
        )
    elif any(result["status"] == BuildTabStatus.FAILED for result in results):
        terminal_event = compute_schemas.BuildFailedEvent.model_validate({**terminal_fields, "progress": 0.0, "error": "One or more tabs failed"})
    else:
        terminal_event = compute_schemas.BuildCompleteEvent.model_validate(terminal_fields)
    await emit_build_event(emitter, event=terminal_event)
    with contextlib.suppress(Exception):
        await run_shutdown_in_thread(manager.shutdown_compute_worker, _build_compute_worker_identity(build.build_id))
    return {
        "analysis_id": analysis_id_value,
        "tabs_built": tabs_built,
        "results": results,
    }


def _load_catalog_table(config: dict) -> IcebergTable | None:
    """Load a catalog-backed Iceberg datasource table, or None for static metadata datasources."""
    catalog_uri = _internal_catalog_uri(config.get("catalog_uri"))
    namespace = config.get("namespace")
    table_name = config.get("table")
    if not (config.get("catalog_type") and catalog_uri and namespace and table_name):
        return None
    catalog_config = {"type": config.get("catalog_type"), "uri": catalog_uri, **object_store_storage_options()}
    if warehouse := config.get("warehouse"):
        catalog_config["warehouse"] = warehouse
    return load_runtime_catalog("local", **catalog_config).load_table(f"{namespace}.{table_name}")


def list_iceberg_snapshots(
    datasource_id: str,
    branch: str | None = None,
    *,
    request_namespace: str,
):
    from runtime.domain.compute.schemas import IcebergSnapshotInfo, IcebergSnapshotsResponse

    datasource = client_from_env().datasource_metadata(namespace=request_namespace, datasource_id=datasource_id)

    if not datasource.found or datasource.config is None:
        raise datasource_not_found(datasource_id)
    if DataSourceType.read(datasource.source_type, default=None) != DataSourceType.ICEBERG:
        raise ValueError("Snapshots are only available for Iceberg datasources")

    metadata_path = datasource.config.get("metadata_path")
    if not isinstance(metadata_path, str) or not metadata_path:
        raise ValueError("Iceberg datasource missing metadata_path")
    raw_branch_name = branch or datasource.config.get("branch")
    branch_name = raw_branch_name if isinstance(raw_branch_name, str) else None

    table = _load_catalog_table(datasource.config)
    if table is not None:
        resolved = resolve_iceberg_metadata_path(str(table.metadata_location))
    else:
        from pyiceberg.table import StaticTable

        resolved = resolve_iceberg_branch_metadata_path(metadata_path, branch_name)
        table = StaticTable.from_metadata(resolved, properties=object_store_storage_options())

    current_snapshot = table.current_snapshot()
    current_snapshot_id = str(current_snapshot.snapshot_id) if current_snapshot else None
    snapshots = []
    for snap in table.snapshots():
        operation = str(snap.summary.operation) if snap.summary and snap.summary.operation else None
        snapshots.append(
            IcebergSnapshotInfo(
                snapshot_id=str(snap.snapshot_id),
                timestamp_ms=snap.timestamp_ms,
                parent_snapshot_id=str(snap.parent_snapshot_id) if snap.parent_snapshot_id is not None else None,
                operation=operation,
                is_current=str(snap.snapshot_id) == current_snapshot_id,
            ),
        )

    snapshots.sort(key=lambda s: s.timestamp_ms, reverse=True)

    table_path = resolved if resolved.startswith("s3://") else str(Path(resolved).parents[1])
    return IcebergSnapshotsResponse(
        datasource_id=datasource_id,
        table_path=table_path,
        snapshots=snapshots,
    )


def delete_iceberg_snapshot(datasource_id: str, snapshot_id: str, *, request_namespace: str):
    from runtime.domain.compute.schemas import IcebergSnapshotDeleteResponse

    datasource = client_from_env().datasource_metadata(namespace=request_namespace, datasource_id=datasource_id)

    if not datasource.found or datasource.config is None:
        raise datasource_not_found(datasource_id)
    if DataSourceType.read(datasource.source_type, default=None) != DataSourceType.ICEBERG:
        raise ValueError("Snapshots are only available for Iceberg datasources")

    try:
        snapshot_value = int(snapshot_id)
    except (TypeError, ValueError) as exc:
        raise DataSourceSnapshotError("Snapshot ID must be an integer", details={"snapshot_id": snapshot_id}) from exc

    table = _load_catalog_table(datasource.config)
    if table is None:
        raise DataSourceSnapshotError(
            "Snapshot deletion requires a catalog-backed Iceberg datasource",
            details={"snapshot_id": snapshot_id},
        )

    expire_snapshots = getattr(getattr(table, "maintenance", None), "expire_snapshots", None)
    if expire_snapshots is None:
        raise DataSourceSnapshotError(
            "Snapshot deletion is not supported by the current Iceberg runtime",
            details={"snapshot_id": snapshot_id},
        )

    try:
        current = table.current_snapshot()
        if current and current.snapshot_id == snapshot_value:
            raise DataSourceSnapshotError(
                "Cannot delete the current snapshot",
                details={"snapshot_id": snapshot_id},
            )
        available_ids = [snap.snapshot_id for snap in table.snapshots()]
        if snapshot_value not in available_ids:
            raise DataSourceSnapshotError(
                f"Snapshot with snapshot id {snapshot_value} does not exist",
                details={
                    "snapshot_id": snapshot_id,
                    "available_snapshot_ids": available_ids,
                },
            )
        expire_snapshots().by_id(snapshot_value).commit()
    except ValueError as exc:
        raise DataSourceSnapshotError(str(exc), details={"snapshot_id": snapshot_id}) from exc
    except NotImplementedError as exc:
        raise DataSourceSnapshotError(
            "Snapshot deletion is not supported by the current Iceberg catalog",
            details={"snapshot_id": snapshot_id},
        ) from exc

    return IcebergSnapshotDeleteResponse(
        datasource_id=datasource_id,
        snapshot_id=snapshot_id,
    )
