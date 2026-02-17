import uuid
from datetime import UTC, datetime

from fastapi import HTTPException as FastAPIHTTPException
from sqlalchemy import desc, select
from sqlmodel import Session

from modules.engine_runs.models import EngineRun
from modules.engine_runs.schemas import (
    BuildComparisonResponse,
    ColumnDiff,
    EngineRunCreateSchema,
    EngineRunResponseSchema,
    RunSummary,
    TimingDiff,
)
from modules.engine_runs.utils import normalize_step_timings


def create_engine_run(
    session: Session,
    payload: EngineRunCreateSchema,
) -> EngineRunResponseSchema:
    run = EngineRun(
        id=payload.id,
        analysis_id=payload.analysis_id,
        datasource_id=payload.datasource_id,
        kind=payload.kind,
        status=payload.status,
        request_json=payload.request_json,
        result_json=payload.result_json,
        error_message=payload.error_message,
        created_at=payload.created_at,
        completed_at=payload.completed_at,
        duration_ms=payload.duration_ms,
        step_timings=normalize_step_timings(payload.step_timings),
        query_plan=payload.query_plan,
        progress=payload.progress,
        current_step=payload.current_step,
        triggered_by=payload.triggered_by,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return EngineRunResponseSchema.model_validate(run)


def create_engine_run_payload(
    analysis_id: str | None,
    datasource_id: str,
    kind: str,
    status: str,
    request_json: dict,
    result_json: dict | None = None,
    error_message: str | None = None,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
    duration_ms: int | None = None,
    step_timings: dict | None = None,
    query_plan: str | None = None,
    progress: float = 0.0,
    current_step: str | None = None,
    triggered_by: str | None = None,
) -> EngineRunCreateSchema:
    return EngineRunCreateSchema(
        id=str(uuid.uuid4()),
        analysis_id=analysis_id,
        datasource_id=datasource_id,
        kind=kind,
        status=status,
        request_json=request_json,
        result_json=result_json,
        error_message=error_message,
        created_at=created_at or datetime.now(UTC),
        completed_at=completed_at,
        duration_ms=duration_ms,
        step_timings=step_timings or {},
        query_plan=query_plan,
        progress=progress,
        current_step=current_step,
        triggered_by=triggered_by,
    )


def list_engine_runs(
    session: Session,
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[EngineRunResponseSchema]:
    stmt = select(EngineRun)
    # SQLModel type annotations not fully compatible with Pydantic v2 - needed for .where() calls
    if analysis_id is not None:
        stmt = stmt.where(EngineRun.analysis_id == analysis_id)  # type: ignore[arg-type]
    if datasource_id is not None:
        stmt = stmt.where(EngineRun.datasource_id == datasource_id)  # type: ignore[arg-type]
    if kind is not None:
        stmt = stmt.where(EngineRun.kind == kind)  # type: ignore[arg-type]
    if status is not None:
        stmt = stmt.where(EngineRun.status == status)  # type: ignore[arg-type]

    stmt = stmt.order_by(desc(EngineRun.created_at)).limit(limit).offset(offset)  # type: ignore[arg-type]
    result = session.execute(stmt)
    runs = result.scalars().all()
    response: list[EngineRunResponseSchema] = []
    for run in runs:
        payload = run.model_dump()
        payload['step_timings'] = normalize_step_timings(run.step_timings)
        response.append(EngineRunResponseSchema.model_validate(payload))
    return response


def compare_engine_runs(
    session: Session,
    run_a_id: str,
    run_b_id: str,
    datasource_id: str | None = None,
) -> BuildComparisonResponse:
    """Compare two engine runs side-by-side: schema diff, row count delta, timing delta."""
    run_a = session.get(EngineRun, run_a_id)
    run_b = session.get(EngineRun, run_b_id)
    if not run_a or not run_b:
        missing = run_a_id if not run_a else run_b_id
        raise FastAPIHTTPException(status_code=404, detail=f'Engine run {missing} not found')
    if run_a.datasource_id != run_b.datasource_id:
        raise FastAPIHTTPException(status_code=400, detail='Engine runs must belong to the same datasource')
    if datasource_id and (run_a.datasource_id != datasource_id or run_b.datasource_id != datasource_id):
        raise FastAPIHTTPException(status_code=400, detail='Engine runs do not match datasource')

    result_a = run_a.result_json or {}
    result_b = run_b.result_json or {}

    # Row counts
    rc_a = _safe_int(result_a.get('row_count'))
    rc_b = _safe_int(result_b.get('row_count'))
    rc_delta = (rc_b - rc_a) if rc_a is not None and rc_b is not None else None

    # Schema diff
    schema_a: dict[str, str] = result_a.get('schema') or {}
    schema_b: dict[str, str] = result_b.get('schema') or {}
    schema_diff = _compute_schema_diff(schema_a, schema_b)

    # Timing diff
    timings_a = normalize_step_timings(run_a.step_timings)
    timings_b = normalize_step_timings(run_b.step_timings)
    timing_diff = _compute_timing_diff(timings_a, timings_b)

    # Total duration delta
    dur_a = run_a.duration_ms
    dur_b = run_b.duration_ms
    dur_delta = (dur_b - dur_a) if dur_a is not None and dur_b is not None else None

    summary_a = RunSummary.model_validate(run_a.model_dump())
    summary_b = RunSummary.model_validate(run_b.model_dump())

    return BuildComparisonResponse(
        run_a=summary_a,
        run_b=summary_b,
        row_count_a=rc_a,
        row_count_b=rc_b,
        row_count_delta=rc_delta,
        schema_diff=schema_diff,
        timing_diff=timing_diff,
        total_duration_delta_ms=dur_delta,
    )


def _safe_int(val: object) -> int | None:
    if val is None:
        return None
    try:
        return int(val)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _compute_schema_diff(
    schema_a: dict[str, str],
    schema_b: dict[str, str],
) -> list[ColumnDiff]:
    diffs: list[ColumnDiff] = []
    all_cols = sorted(set(schema_a) | set(schema_b))
    for col in all_cols:
        in_a = col in schema_a
        in_b = col in schema_b
        if in_a and not in_b:
            diffs.append(ColumnDiff(column=col, status='removed', type_a=schema_a[col]))
        elif not in_a and in_b:
            diffs.append(ColumnDiff(column=col, status='added', type_b=schema_b[col]))
        elif schema_a[col] != schema_b[col]:
            diffs.append(
                ColumnDiff(
                    column=col,
                    status='type_changed',
                    type_a=schema_a[col],
                    type_b=schema_b[col],
                )
            )
    return diffs


def _compute_timing_diff(
    timings_a: dict[str, float],
    timings_b: dict[str, float],
) -> list[TimingDiff]:
    diffs: list[TimingDiff] = []
    all_steps = sorted(set(timings_a) | set(timings_b))
    for step in all_steps:
        ms_a = timings_a.get(step)
        ms_b = timings_b.get(step)
        delta_ms = (ms_b - ms_a) if ms_a is not None and ms_b is not None else None
        delta_pct: float | None = None
        if delta_ms is not None and ms_a and ms_a > 0:
            delta_pct = round((delta_ms / ms_a) * 100, 1)
        diffs.append(TimingDiff(step=step, ms_a=ms_a, ms_b=ms_b, delta_ms=delta_ms, delta_pct=delta_pct))
    return diffs
