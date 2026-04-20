import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from fastapi import HTTPException as FastAPIHTTPException
from sqlalchemy import desc, select
from sqlmodel import Session

from modules.analysis.step_types import get_step_type_label
from modules.engine_runs.models import EngineRun
from modules.engine_runs.schemas import (
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
from modules.engine_runs.utils import normalize_step_timings

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({EngineRunStatus.SUCCESS, EngineRunStatus.FAILED, EngineRunStatus.CANCELLED})


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


_TIMING_SUFFIX_RE = re.compile(r'^(?P<base>.+?)_(?P<index>\d+)$')


class _UnsetType:
    __slots__ = ()


_UNSET: Final = _UnsetType()


def _step_label_for_timing_key(key: str) -> tuple[str, str]:
    match = _TIMING_SUFFIX_RE.match(key)
    base_key = match.group('base') if match else key
    suffix = int(match.group('index')) if match else None
    label = get_step_type_label(base_key)
    if suffix is not None:
        label = f'{label} {suffix}'
    return base_key, label


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
        append_entry(
            key='initial_read',
            label='Initial Read',
            category=EngineRunExecutionCategory.READ,
            duration_ms=float(read_duration_ms),
        )

    optimized_plan = (
        query_plans.get('optimized') if isinstance(query_plans, dict) and isinstance(query_plans.get('optimized'), str) else None
    )
    unoptimized_plan = (
        query_plans.get('unoptimized') if isinstance(query_plans, dict) and isinstance(query_plans.get('unoptimized'), str) else None
    )
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
        base_key, label = _step_label_for_timing_key(timing_key)
        append_entry(
            key=timing_key,
            label=label,
            category=EngineRunExecutionCategory.STEP,
            duration_ms=duration_ms,
            metadata={'step_type': base_key},
        )

    if isinstance(collect_duration_ms, (int, float)):
        append_entry(
            key='compute',
            label='Compute',
            category=EngineRunExecutionCategory.COMPUTE,
            duration_ms=float(collect_duration_ms),
        )

    if isinstance(write_duration_ms, (int, float)):
        append_entry(
            key='write_output',
            label='Write Output',
            category=EngineRunExecutionCategory.WRITE,
            duration_ms=float(write_duration_ms),
        )

    return entries


def _copy_result_json(value: dict[str, Any] | None) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _serialize_run(run: EngineRun) -> EngineRunResponseSchema:
    result_json = run.result_json if isinstance(run.result_json, dict) else {}
    execution_entries_raw = result_json.get('execution_entries')
    execution_entries = (
        [EngineRunExecutionEntry.model_validate(entry).model_dump(mode='json') for entry in execution_entries_raw]
        if isinstance(execution_entries_raw, list)
        else []
    )
    return EngineRunResponseSchema.model_validate(
        {
            **run.model_dump(),
            'step_timings': normalize_step_timings(run.step_timings),
            'execution_entries': execution_entries,
        }
    )


def get_engine_run(session: Session, run_id: str) -> EngineRunResponseSchema | None:
    run = session.get(EngineRun, run_id)
    if run is None:
        return None
    return _serialize_run(run)


def _coerce_kind(kind: EngineRunKind | str) -> EngineRunKind:
    return kind if isinstance(kind, EngineRunKind) else EngineRunKind(kind)


def _coerce_status(status: EngineRunStatus | str) -> EngineRunStatus:
    return status if isinstance(status, EngineRunStatus) else EngineRunStatus(status)


def create_engine_run(
    session: Session,
    payload: EngineRunPayload,
) -> EngineRunResponseSchema:
    result_json = payload.result_json.copy() if isinstance(payload.result_json, dict) else None
    if payload.execution_entries:
        result_json = result_json or {}
        result_json['execution_entries'] = [
            EngineRunExecutionEntry.model_validate(entry).model_dump(mode='json') for entry in payload.execution_entries
        ]

    run = EngineRun(
        id=payload.id,
        analysis_id=payload.analysis_id,
        datasource_id=payload.datasource_id,
        kind=payload.kind,
        status=payload.status,
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
    if run is None:
        raise FastAPIHTTPException(status_code=404, detail=f'Engine run {run_id} not found')
    session.refresh(run)

    if not isinstance(analysis_id, _UnsetType):
        run.analysis_id = analysis_id if analysis_id is None or isinstance(analysis_id, str) else run.analysis_id
    if not isinstance(datasource_id, _UnsetType) and isinstance(datasource_id, str):
        run.datasource_id = datasource_id
    if not isinstance(kind, _UnsetType):
        run.kind = _coerce_kind(kind) if isinstance(kind, (EngineRunKind, str)) else run.kind
    if not isinstance(status, _UnsetType):
        new_status = _coerce_status(status) if isinstance(status, (EngineRunStatus, str)) else None
        if new_status is not None and run.status in _TERMINAL_STATUSES and new_status != run.status:
            logger.warning(f'Ignoring status transition from {run.status} to {new_status} for run {run_id}')
        elif new_status is not None:
            run.status = new_status
    if not isinstance(request_json, _UnsetType) and isinstance(request_json, dict):
        run.request_json = request_json
    if not isinstance(result_json, _UnsetType):
        if result_json is None:
            run.result_json = None
        elif isinstance(result_json, dict):
            base = _copy_result_json(run.result_json) if merge_result_json else {}
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
        next_result_json = _copy_result_json(run.result_json)
        if execution_entries is None:
            next_result_json.pop('execution_entries', None)
        elif isinstance(execution_entries, list):
            next_result_json['execution_entries'] = [
                EngineRunExecutionEntry.model_validate(entry).model_dump(mode='json') for entry in execution_entries
            ]
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
        kind=_coerce_kind(kind),
        status=_coerce_status(status),
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
        stmt = stmt.where(EngineRun.kind == _coerce_kind(kind))  # type: ignore[arg-type]
    if status is not None:
        stmt = stmt.where(EngineRun.status == _coerce_status(status))  # type: ignore[arg-type]

    stmt = stmt.order_by(desc(EngineRun.created_at)).limit(limit).offset(offset)  # type: ignore[arg-type]
    runs = session.execute(stmt).scalars().all()
    return [_serialize_run(run) for run in runs]


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
    except (TypeError, ValueError):
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
    return EngineRunResultSummary.model_validate(
        {
            'row_count': payload.get('row_count'),
            'schema': schema,
            'data': data,
            'metadata': metadata,
        },
    )


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
            diffs.append(ColumnDiff(column=col, status=SchemaDiffStatus.REMOVED, type_a=schema_a[col]))
        elif not in_a and in_b:
            diffs.append(ColumnDiff(column=col, status=SchemaDiffStatus.ADDED, type_b=schema_b[col]))
        elif schema_a[col] != schema_b[col]:
            diffs.append(
                ColumnDiff(
                    column=col,
                    status=SchemaDiffStatus.TYPE_CHANGED,
                    type_a=schema_a[col],
                    type_b=schema_b[col],
                ),
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
