from datetime import UTC, datetime

from backend_core.domain.compute import schemas
from backend_core.domain.compute_worker_runs.schemas import ComputeWorkerRunKind, ComputeWorkerRunResponseSchema, ComputeWorkerRunStatus


def compute_worker_run_to_build_lifecycle_status(status: ComputeWorkerRunStatus) -> schemas.BuildLifecycleStatus:
    return {
        ComputeWorkerRunStatus.RUNNING: schemas.BuildLifecycleStatus.RUNNING,
        ComputeWorkerRunStatus.SUCCESS: schemas.BuildLifecycleStatus.COMPLETED,
        ComputeWorkerRunStatus.FAILED: schemas.BuildLifecycleStatus.FAILED,
        ComputeWorkerRunStatus.CANCELLED: schemas.BuildLifecycleStatus.CANCELLED,
    }[status]


def compute_worker_run_status_filter(status: schemas.BuildLifecycleStatus | None) -> ComputeWorkerRunStatus | None:
    if status is None:
        return None
    return {
        schemas.BuildLifecycleStatus.RUNNING: ComputeWorkerRunStatus.RUNNING,
        schemas.BuildLifecycleStatus.COMPLETED: ComputeWorkerRunStatus.SUCCESS,
        schemas.BuildLifecycleStatus.FAILED: ComputeWorkerRunStatus.FAILED,
        schemas.BuildLifecycleStatus.CANCELLED: ComputeWorkerRunStatus.CANCELLED,
        schemas.BuildLifecycleStatus.QUEUED: ComputeWorkerRunStatus.RUNNING,
    }[status]


def compute_worker_run_kind_filter(kind: str | None) -> ComputeWorkerRunKind | str | None:
    return ComputeWorkerRunKind.INGEST if kind == 'build' else kind


def _elapsed_ms(run: ComputeWorkerRunResponseSchema) -> int:
    if run.duration_ms is not None:
        return run.duration_ms
    if run.status != ComputeWorkerRunStatus.RUNNING:
        return 0
    started_at = run.created_at if run.created_at.tzinfo is not None else run.created_at.replace(tzinfo=UTC)
    return max(int((datetime.now(UTC) - started_at).total_seconds() * 1000), 0)


def _result(run: ComputeWorkerRunResponseSchema) -> dict[str, object]:
    return dict(run.result_json) if isinstance(run.result_json, dict) else {}


def _result_str(result: dict[str, object], key: str) -> str | None:
    value = result.get(key)
    return value if isinstance(value, str) and value else None


def compute_worker_run_summary(run: ComputeWorkerRunResponseSchema, *, namespace: str) -> schemas.BuildRunSummary:
    result = _result(run)
    return schemas.BuildRunSummary(
        build_id=run.id,
        analysis_id=run.analysis_id or '',
        analysis_name=run.analysis_id or '',
        namespace=namespace,
        status=compute_worker_run_to_build_lifecycle_status(run.status),
        started_at=run.created_at,
        starter=schemas.BuildStarter(user_id=None, display_name=None, email=None, triggered_by=run.triggered_by),
        resource_config=None,
        progress=run.progress,
        elapsed_ms=_elapsed_ms(run),
        estimated_remaining_ms=None,
        current_step=run.current_step,
        current_step_index=None,
        total_steps=0,
        current_kind=run.kind,
        current_datasource_id=run.datasource_id,
        current_tab_id=_result_str(result, 'current_tab_id'),
        current_tab_name=_result_str(result, 'current_tab_name'),
        current_output_id=_result_str(result, 'current_output_id'),
        current_output_name=_result_str(result, 'current_output_name'),
        current_compute_worker_run_id=run.id,
        total_tabs=0,
        cancelled_at=run.completed_at if run.status == ComputeWorkerRunStatus.CANCELLED else None,
        cancelled_by=None,
        result_json=result,
    )


def compute_worker_run_detail(run: ComputeWorkerRunResponseSchema, *, namespace: str) -> schemas.BuildRunDetail:
    summary = compute_worker_run_summary(run, namespace=namespace)
    summary_payload = summary.model_dump()
    summary_payload.pop('result_json', None)
    return schemas.BuildRunDetail(
        **summary_payload,
        steps=[],
        query_plans=[],
        latest_resources=None,
        resources=[],
        logs=[],
        results=[],
        duration_ms=run.duration_ms,
        error=run.error_message,
        request_json=dict(run.request_json),
        result_json=_result(run),
    )
