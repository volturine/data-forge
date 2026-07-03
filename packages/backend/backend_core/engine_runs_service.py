import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import desc, or_, select
from sqlmodel import Session

from backend_core.domain.analysis.step_types import get_step_timing_key
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute.schemas import BuildLogLevel, BuildStepState
from backend_core.domain.engine_runs.schemas import (
    BuildComparisonResponse,
    ColumnDiff,
    EngineRunExecutionCategory,
    EngineRunExecutionEntry,
    EngineRunKind,
    EngineRunResponseSchema,
    EngineRunResultSummary,
    EngineRunStatus,
    RunSummary,
    SchemaDiffStatus,
    TimingDiff,
)
from backend_core.engine_runs_utils import normalize_step_timings
from backend_core.exceptions import EngineRunComparisonError, engine_run_not_found
from backend_core.json_utils import copy_json_dict
from backend_core.namespace import get_namespace
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.engine_runs.models import EngineRun
from backend_core.sqlmodel_typing import col, sa

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EngineRunPayload:
    analysis_id: str | None
    datasource_id: str
    kind: EngineRunKind
    status: EngineRunStatus
    request_json: dict[str, Any]
    result_json: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: int | None = None
    step_timings: dict[str, float] = field(default_factory=dict)
    query_plan: str | None = None
    progress: float = 0.0
    current_step: str | None = None
    triggered_by: str | None = None
    execution_entries: list[dict[str, Any]] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


class _UnsetType:
    __slots__ = ()


_UNSET: Final = _UnsetType()


def build_execution_entries(
    *,
    step_timings: dict[str, float] | None = None,
    query_plans: dict[str, Any] | None = None,
    query_plan: str | None = None,
    read_duration_ms: float | None = None,
    collect_duration_ms: float | None = None,
    write_duration_ms: float | None = None,
    total_duration_ms: int | None = None,
) -> list[dict[str, Any]]:
    normalized_timings = normalize_step_timings(step_timings)
    timed_total = sum(normalized_timings.values())
    if isinstance(read_duration_ms, (int, float)):
        timed_total += float(read_duration_ms)
    if isinstance(collect_duration_ms, (int, float)):
        timed_total += float(collect_duration_ms)
    if isinstance(write_duration_ms, (int, float)):
        timed_total += float(write_duration_ms)
    denominator = float(total_duration_ms) if total_duration_ms and total_duration_ms > 0 else timed_total

    entries: list[dict[str, Any]] = []

    def append_entry(
        *,
        key: str,
        label: str,
        category: EngineRunExecutionCategory,
        duration_ms: float | None = None,
        optimized_plan: str | None = None,
        unoptimized_plan: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        share_pct = round((duration_ms / denominator) * 100, 1) if duration_ms is not None and denominator > 0 else None
        entries.append(
            {
                'key': key,
                'label': label,
                'category': category,
                'order': len(entries),
                'duration_ms': round(duration_ms, 2) if duration_ms is not None else None,
                'share_pct': share_pct,
                'optimized_plan': optimized_plan,
                'unoptimized_plan': unoptimized_plan,
                'metadata': metadata,
            }
        )

    if isinstance(read_duration_ms, (int, float)):
        append_entry(key='initial_read', label='Initial Read', category=EngineRunExecutionCategory.READ, duration_ms=float(read_duration_ms))

    optimized_plan = query_plans.get('optimized') if isinstance(query_plans, dict) and isinstance(query_plans.get('optimized'), str) else None
    unoptimized_plan = query_plans.get('unoptimized') if isinstance(query_plans, dict) and isinstance(query_plans.get('unoptimized'), str) else None
    if optimized_plan or unoptimized_plan or query_plan:
        append_entry(
            key='query_plan',
            label='Query Plan',
            category=EngineRunExecutionCategory.PLAN,
            duration_ms=None,
            optimized_plan=optimized_plan or query_plan,
            unoptimized_plan=unoptimized_plan or query_plan,
        )

    for timing_key, duration_ms in normalized_timings.items():
        base_key, label = get_step_timing_key(timing_key)
        append_entry(key=timing_key, label=label, category=EngineRunExecutionCategory.STEP, duration_ms=duration_ms, metadata={'step_type': base_key})

    if isinstance(collect_duration_ms, (int, float)):
        append_entry(key='compute', label='Compute', category=EngineRunExecutionCategory.COMPUTE, duration_ms=float(collect_duration_ms))

    if isinstance(write_duration_ms, (int, float)):
        append_entry(key='write_output', label='Write Output', category=EngineRunExecutionCategory.WRITE, duration_ms=float(write_duration_ms))

    return entries


def _latest_completed_step_name(result_json: dict[str, Any]) -> str | None:
    raw_steps = result_json.get('steps')
    if not isinstance(raw_steps, list):
        return None
    completed_steps = [
        step for step in raw_steps if isinstance(step, dict) and BuildStepState.read(step.get('state'), default=None) == BuildStepState.COMPLETED
    ]
    if not completed_steps:
        return None

    def step_sort_key(step: dict[str, Any]) -> int:
        index = step.get('build_step_index')
        return index if isinstance(index, int) else -1

    completed_steps.sort(key=step_sort_key)
    latest = completed_steps[-1]
    step_name = latest.get('step_name')
    return step_name if isinstance(step_name, str) else None


def cancel_engine_run(session: Session, run_id: str, *, cancelled_by: str | None) -> compute_schemas.CancelBuildResponse:
    run = session.get(EngineRun, run_id)
    if run is None or run.namespace != get_namespace():
        raise ValueError('Engine run not found')
    session.refresh(run)
    if run.status_kind() != EngineRunStatus.RUNNING:
        raise ValueError('Only running builds can be cancelled')

    now = datetime.now(UTC)
    reason = f'Cancelled by {cancelled_by}' if cancelled_by else 'Cancelled'
    existing = copy_json_dict(run.result_json)
    existing.pop('data', None)
    existing.pop('schema', None)
    existing['results'] = []
    existing['cancelled_at'] = now.isoformat()
    existing['cancelled_by'] = cancelled_by
    last_completed_step = _latest_completed_step_name(existing)
    if last_completed_step is not None:
        existing['last_completed_step'] = last_completed_step
    existing_logs = existing.get('logs')
    logs = [entry for entry in existing_logs if isinstance(entry, dict)] if isinstance(existing_logs, list) else []
    logs.append(
        {
            'timestamp': now.isoformat(),
            'level': BuildLogLevel.WARNING.value,
            'message': reason,
            'step_name': None,
            'step_id': None,
            'tab_id': None,
            'tab_name': None,
        }
    )
    existing['logs'] = logs

    created_at = run.created_at if run.created_at.tzinfo is not None else run.created_at.replace(tzinfo=UTC)
    duration_ms = max(int((now - created_at).total_seconds() * 1000), 0)
    update_engine_run(
        session,
        run_id,
        status=EngineRunStatus.CANCELLED,
        result_json=existing,
        merge_result_json=False,
        error_message=reason,
        completed_at=now,
        duration_ms=duration_ms,
        progress=run.progress,
        current_step=run.current_step,
    )

    return compute_schemas.CancelBuildResponse(
        id=run_id, build_id=None, engine_run_id=run_id, status='cancelled', duration_ms=duration_ms, cancelled_at=now, cancelled_by=cancelled_by
    )


def _serialize_run(run: EngineRun) -> EngineRunResponseSchema:
    result_json = run.result_json if isinstance(run.result_json, dict) else {}
    execution_entries_raw = result_json.get('execution_entries')
    execution_entries = (
        [EngineRunExecutionEntry.model_validate(entry).model_dump(mode='json') for entry in execution_entries_raw]
        if isinstance(execution_entries_raw, list)
        else []
    )
    return EngineRunResponseSchema.model_validate(
        {**run.model_dump(), 'step_timings': normalize_step_timings(run.step_timings), 'execution_entries': execution_entries}
    )


def get_engine_run(session: Session, run_id: str) -> EngineRunResponseSchema | None:
    run = session.get(EngineRun, run_id)
    if run is None:
        return None
    if run.namespace != get_namespace():
        return None
    return _serialize_run(run)


def create_engine_run(session: Session, payload: EngineRunPayload) -> EngineRunResponseSchema:
    result_json = payload.result_json.copy() if isinstance(payload.result_json, dict) else None
    if payload.execution_entries:
        result_json = result_json or {}
        result_json['execution_entries'] = [EngineRunExecutionEntry.model_validate(entry).model_dump(mode='json') for entry in payload.execution_entries]

    run = EngineRun(
        id=payload.id,
        namespace=get_namespace(),
        analysis_id=payload.analysis_id,
        datasource_id=payload.datasource_id,
        kind=payload.kind.value,
        status=payload.status.value,
        request_json=payload.request_json,
        result_json=result_json,
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
    return _serialize_run(run)


def update_engine_run(
    session: Session,
    run_id: str,
    *,
    analysis_id: str | None | _UnsetType = _UNSET,
    datasource_id: str | _UnsetType = _UNSET,
    kind: EngineRunKind | str | _UnsetType = _UNSET,
    status: EngineRunStatus | str | _UnsetType = _UNSET,
    request_json: dict[str, Any] | _UnsetType = _UNSET,
    result_json: dict[str, Any] | None | _UnsetType = _UNSET,
    merge_result_json: bool = True,
    error_message: str | None | _UnsetType = _UNSET,
    completed_at: datetime | None | _UnsetType = _UNSET,
    duration_ms: int | None | _UnsetType = _UNSET,
    step_timings: dict[str, float] | None | _UnsetType = _UNSET,
    query_plan: str | None | _UnsetType = _UNSET,
    execution_entries: list[dict[str, Any]] | None | _UnsetType = _UNSET,
    progress: float | _UnsetType = _UNSET,
    current_step: str | None | _UnsetType = _UNSET,
    triggered_by: str | None | _UnsetType = _UNSET,
) -> EngineRunResponseSchema:
    run = session.get(EngineRun, run_id)
    if run is None or run.namespace != get_namespace():
        raise engine_run_not_found(run_id)
    session.refresh(run)

    if not isinstance(analysis_id, _UnsetType):
        run.analysis_id = analysis_id if analysis_id is None or isinstance(analysis_id, str) else run.analysis_id
    if not isinstance(datasource_id, _UnsetType) and isinstance(datasource_id, str):
        run.datasource_id = datasource_id
    if not isinstance(kind, _UnsetType):
        run.kind = EngineRunKind.require(kind).value if isinstance(kind, (EngineRunKind, str)) else run.kind
    if not isinstance(status, _UnsetType):
        new_status = EngineRunStatus.require(status) if isinstance(status, (EngineRunStatus, str)) else None
        current_status = run.status_kind()
        if new_status is not None and current_status.blocks_transition_to(new_status):
            logger.warning(f'Ignoring status transition from {current_status} to {new_status} for run {run_id}')
        elif new_status is not None:
            run.status = new_status.value
    if not isinstance(request_json, _UnsetType) and isinstance(request_json, dict):
        run.request_json = request_json
    if not isinstance(result_json, _UnsetType):
        if result_json is None:
            run.result_json = None
        elif isinstance(result_json, dict):
            base = copy_json_dict(run.result_json) if merge_result_json else {}
            base.update(result_json)
            run.result_json = base
    if not isinstance(error_message, _UnsetType):
        run.error_message = error_message if error_message is None or isinstance(error_message, str) else run.error_message
    if not isinstance(completed_at, _UnsetType):
        run.completed_at = completed_at if completed_at is None or isinstance(completed_at, datetime) else run.completed_at
    if not isinstance(duration_ms, _UnsetType):
        run.duration_ms = duration_ms if duration_ms is None or isinstance(duration_ms, int) else run.duration_ms
    if not isinstance(step_timings, _UnsetType):
        run.step_timings = normalize_step_timings(step_timings if isinstance(step_timings, dict) else None)
    if not isinstance(query_plan, _UnsetType):
        run.query_plan = query_plan if query_plan is None or isinstance(query_plan, str) else run.query_plan
    if not isinstance(progress, _UnsetType) and isinstance(progress, (int, float)):
        run.progress = float(progress)
    if not isinstance(current_step, _UnsetType):
        run.current_step = current_step if current_step is None or isinstance(current_step, str) else run.current_step
    if not isinstance(triggered_by, _UnsetType):
        run.triggered_by = triggered_by if triggered_by is None or isinstance(triggered_by, str) else run.triggered_by
    if not isinstance(execution_entries, _UnsetType):
        next_result_json = copy_json_dict(run.result_json)
        if execution_entries is None:
            next_result_json.pop('execution_entries', None)
        elif isinstance(execution_entries, list):
            next_result_json['execution_entries'] = [EngineRunExecutionEntry.model_validate(entry).model_dump(mode='json') for entry in execution_entries]
        run.result_json = next_result_json

    session.add(run)
    session.commit()
    session.refresh(run)
    return _serialize_run(run)


def create_engine_run_payload(
    analysis_id: str | None,
    datasource_id: str,
    kind: EngineRunKind | str,
    status: EngineRunStatus | str,
    request_json: dict[str, Any],
    result_json: dict[str, Any] | None = None,
    error_message: str | None = None,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
    duration_ms: int | None = None,
    step_timings: dict[str, float] | None = None,
    query_plan: str | None = None,
    execution_entries: list[dict[str, Any]] | None = None,
    progress: float = 0.0,
    current_step: str | None = None,
    triggered_by: str | None = None,
) -> EngineRunPayload:
    return EngineRunPayload(
        analysis_id=analysis_id,
        datasource_id=datasource_id,
        kind=EngineRunKind.require(kind),
        status=EngineRunStatus.require(status),
        request_json=request_json,
        result_json=result_json,
        error_message=error_message,
        created_at=created_at or datetime.now(UTC),
        completed_at=completed_at,
        duration_ms=duration_ms,
        step_timings=normalize_step_timings(step_timings),
        query_plan=query_plan,
        execution_entries=execution_entries or [],
        progress=progress,
        current_step=current_step,
        triggered_by=triggered_by,
    )


def list_engine_runs(
    session: Session,
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: EngineRunKind | str | None = None,
    status: EngineRunStatus | str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[EngineRunResponseSchema]:
    stmt = select(EngineRun).where(sa(EngineRun.namespace == get_namespace()))
    stmt = stmt.join(
        DataSource,
        col(EngineRun.datasource_id) == col(DataSource.id),
        isouter=True,
    )
    stmt = stmt.join(
        Analysis,
        col(EngineRun.analysis_id) == col(Analysis.id),
        isouter=True,
    )
    if analysis_id is not None:
        stmt = stmt.where(sa(EngineRun.analysis_id == analysis_id))
    if datasource_id is not None:
        stmt = stmt.where(sa(EngineRun.datasource_id == datasource_id))
    if kind is not None:
        coerced_kind = EngineRunKind.require(kind)
        if coerced_kind == EngineRunKind.BUILD:
            return []
        stmt = stmt.where(sa(EngineRun.kind == coerced_kind.value))
    else:
        stmt = stmt.where(sa(EngineRun.kind != EngineRunKind.BUILD.value))
    if status is not None:
        stmt = stmt.where(sa(EngineRun.status == EngineRunStatus.require(status).value))
    if search:
        q = f'%{search}%'
        stmt = stmt.where(
            or_(
                col(EngineRun.id).ilike(q),
                col(EngineRun.analysis_id).ilike(q),
                col(EngineRun.datasource_id).ilike(q),
                col(DataSource.name).ilike(q),
                col(Analysis.name).ilike(q),
            )
        )

    stmt = stmt.order_by(desc(sa(EngineRun.created_at))).limit(limit).offset(offset)
    runs = session.execute(stmt).scalars().all()
    return [_serialize_run(run) for run in runs]


def compare_engine_runs(session: Session, run_a_id: str, run_b_id: str, datasource_id: str | None = None) -> BuildComparisonResponse:
    """Compare two engine runs side-by-side: schema diff, row count delta, timing delta."""
    run_a = session.get(EngineRun, run_a_id)
    run_b = session.get(EngineRun, run_b_id)
    namespace = get_namespace()
    if run_a is not None and run_a.namespace != namespace:
        run_a = None
    if run_b is not None and run_b.namespace != namespace:
        run_b = None
    if not run_a or not run_b:
        missing = run_a_id if not run_a else run_b_id
        raise engine_run_not_found(missing)
    if run_a.datasource_id != run_b.datasource_id:
        raise EngineRunComparisonError('Engine runs must belong to the same datasource', run_a_id=run_a_id, run_b_id=run_b_id)
    if datasource_id and (run_a.datasource_id != datasource_id or run_b.datasource_id != datasource_id):
        raise EngineRunComparisonError('Engine runs do not match datasource', run_a_id=run_a_id, run_b_id=run_b_id, datasource_id=datasource_id)

    result_a = _load_result_summary(run_a.result_json)
    result_b = _load_result_summary(run_b.result_json)

    # Row counts
    rc_a = _safe_int(result_a.row_count)
    rc_b = _safe_int(result_b.row_count)
    rc_delta = (rc_b - rc_a) if rc_a is not None and rc_b is not None else None

    # Schema diff
    schema_a: dict[str, str] = result_a.schema_ or {}
    schema_b: dict[str, str] = result_b.schema_ or {}
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
    except TypeError, ValueError:
        return None


def _load_result_summary(result_json: dict[str, Any] | None) -> EngineRunResultSummary:
    payload = result_json if isinstance(result_json, dict) else {}
    schema = payload.get('schema')
    if not isinstance(schema, dict):
        schema = {}
    data = payload.get('data')
    if not isinstance(data, list):
        data = None
    metadata = payload.get('metadata')
    if not isinstance(metadata, dict):
        metadata = None
    return EngineRunResultSummary.model_validate({'row_count': payload.get('row_count'), 'schema': schema, 'data': data, 'metadata': metadata})


def _compute_schema_diff(schema_a: dict[str, str], schema_b: dict[str, str]) -> list[ColumnDiff]:
    diffs: list[ColumnDiff] = []
    all_cols = sorted(set(schema_a) | set(schema_b))
    for column in all_cols:
        in_a = column in schema_a
        in_b = column in schema_b
        if in_a and not in_b:
            diffs.append(ColumnDiff(column=column, status=SchemaDiffStatus.REMOVED, type_a=schema_a[column]))
        elif not in_a and in_b:
            diffs.append(ColumnDiff(column=column, status=SchemaDiffStatus.ADDED, type_b=schema_b[column]))
        elif schema_a[column] != schema_b[column]:
            diffs.append(ColumnDiff(column=column, status=SchemaDiffStatus.TYPE_CHANGED, type_a=schema_a[column], type_b=schema_b[column]))
    return diffs


def _compute_timing_diff(timings_a: dict[str, float], timings_b: dict[str, float]) -> list[TimingDiff]:
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
