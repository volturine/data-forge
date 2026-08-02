from datetime import UTC, datetime

from backend_core.domain.compute import schemas
from backend_core.domain.engine_runs.schemas import EngineRunKind, EngineRunResponseSchema, EngineRunStatus


def engine_run_active_status(status: EngineRunStatus) -> schemas.ActiveBuildStatus:
    return {
        EngineRunStatus.RUNNING: schemas.ActiveBuildStatus.RUNNING,
        EngineRunStatus.SUCCESS: schemas.ActiveBuildStatus.COMPLETED,
        EngineRunStatus.FAILED: schemas.ActiveBuildStatus.FAILED,
        EngineRunStatus.CANCELLED: schemas.ActiveBuildStatus.CANCELLED,
    }[status]


def engine_run_status_filter(status: schemas.ActiveBuildStatus | None) -> EngineRunStatus | None:
    if status is None:
        return None
    return {
        schemas.ActiveBuildStatus.RUNNING: EngineRunStatus.RUNNING,
        schemas.ActiveBuildStatus.COMPLETED: EngineRunStatus.SUCCESS,
        schemas.ActiveBuildStatus.FAILED: EngineRunStatus.FAILED,
        schemas.ActiveBuildStatus.CANCELLED: EngineRunStatus.CANCELLED,
        schemas.ActiveBuildStatus.QUEUED: EngineRunStatus.RUNNING,
    }[status]


def engine_run_kind_filter(kind: str | None) -> EngineRunKind | str | None:
    return EngineRunKind.INGEST if kind == 'build' else kind


def _elapsed_ms(run: EngineRunResponseSchema) -> int:
    if run.duration_ms is not None:
        return run.duration_ms
    if run.status != EngineRunStatus.RUNNING:
        return 0
    started_at = run.created_at if run.created_at.tzinfo is not None else run.created_at.replace(tzinfo=UTC)
    return max(int((datetime.now(UTC) - started_at).total_seconds() * 1000), 0)


def _result(run: EngineRunResponseSchema) -> dict[str, object]:
    return dict(run.result_json) if isinstance(run.result_json, dict) else {}


def _result_str(result: dict[str, object], key: str) -> str | None:
    value = result.get(key)
    return value if isinstance(value, str) and value else None


def engine_run_summary(run: EngineRunResponseSchema, *, namespace: str) -> schemas.ActiveBuildSummary:
    result = _result(run)
    return schemas.ActiveBuildSummary(
        build_id=run.id,
        analysis_id=run.analysis_id or '',
        analysis_name=run.analysis_id or '',
        namespace=namespace,
        status=engine_run_active_status(run.status),
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
        current_engine_run_id=run.id,
        total_tabs=0,
        cancelled_at=run.completed_at if run.status == EngineRunStatus.CANCELLED else None,
        cancelled_by=None,
        result_json=result,
    )


def engine_run_detail(run: EngineRunResponseSchema, *, namespace: str) -> schemas.ActiveBuildDetail:
    summary = engine_run_summary(run, namespace=namespace)
    summary_payload = summary.model_dump()
    summary_payload.pop('result_json', None)
    return schemas.ActiveBuildDetail(
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
