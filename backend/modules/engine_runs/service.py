import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

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
_UNSET = object()
_MAX_LIVE_RESOURCES = 120
_MAX_LIVE_LOGS = 500


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
    write_duration_ms: float | None = None,
    total_duration_ms: int | None = None,
) -> list[dict[str, Any]]:
    normalized_timings = normalize_step_timings(step_timings)
    timed_total = sum(normalized_timings.values())
    if isinstance(read_duration_ms, (int, float)):
        timed_total += float(read_duration_ms)
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


def _payload_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _payload_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _upsert_live_item(items: list[dict[str, Any]], item: dict[str, Any], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    next_items = [existing for existing in items if any(existing.get(key) != item.get(key) for key in keys)]
    next_items.append(item)
    if 'build_step_index' in item:
        next_items.sort(key=lambda existing: int(existing.get('build_step_index', 0)))
    return next_items


def _step_timings_from_live_steps(steps: list[dict[str, Any]]) -> dict[str, float]:
    timings: dict[str, float] = {}
    counters: dict[str, int] = {}
    for step in sorted(steps, key=lambda item: int(item.get('build_step_index', 0))):
        state = step.get('state')
        step_type = step.get('step_type')
        duration_ms = step.get('duration_ms')
        if state != 'completed' or not isinstance(step_type, str) or step_type in {'read', 'write'}:
            continue
        if not isinstance(duration_ms, (int, float)):
            continue
        counters[step_type] = counters.get(step_type, 0) + 1
        key = f'{step_type}_{counters[step_type]}'
        timings[key] = round(float(duration_ms), 2)
    return timings


def _execution_entries_from_live_result(result_json: dict[str, Any], total_duration_ms: int | None) -> list[dict[str, Any]]:
    steps_raw = result_json.get('steps')
    steps = [step for step in steps_raw if isinstance(step, dict)] if isinstance(steps_raw, list) else []
    plans_raw = result_json.get('query_plans')
    plans = [plan for plan in plans_raw if isinstance(plan, dict)] if isinstance(plans_raw, list) else []
    total = float(total_duration_ms) if isinstance(total_duration_ms, int) and total_duration_ms > 0 else None
    timed_total = 0.0
    for step in steps:
        duration_ms = step.get('duration_ms')
        if isinstance(duration_ms, (int, float)):
            timed_total += float(duration_ms)
    denominator = total if total is not None else (timed_total if timed_total > 0 else None)

    entries: list[dict[str, Any]] = []

    def append_entry(
        *,
        key: str,
        label: str,
        category: EngineRunExecutionCategory,
        order: int,
        duration_ms: float | None = None,
        optimized_plan: str | None = None,
        unoptimized_plan: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        share_pct = round((duration_ms / denominator) * 100, 1) if duration_ms is not None and denominator else None
        entries.append(
            {
                'key': key,
                'label': label,
                'category': category,
                'order': order,
                'duration_ms': round(duration_ms, 2) if duration_ms is not None else None,
                'share_pct': share_pct,
                'optimized_plan': optimized_plan,
                'unoptimized_plan': unoptimized_plan,
                'metadata': metadata,
            }
        )

    order = 0
    for plan in plans:
        append_entry(
            key=f'query_plan_{order}',
            label='Query Plan',
            category=EngineRunExecutionCategory.PLAN,
            order=order,
            optimized_plan=plan.get('optimized_plan') if isinstance(plan.get('optimized_plan'), str) else None,
            unoptimized_plan=plan.get('unoptimized_plan') if isinstance(plan.get('unoptimized_plan'), str) else None,
        )
        order += 1

    for step in sorted(steps, key=lambda item: int(item.get('build_step_index', 0))):
        step_name = step.get('step_name')
        if not isinstance(step_name, str) or not step_name:
            continue
        step_type = step.get('step_type') if isinstance(step.get('step_type'), str) else 'unknown'
        duration_ms = step.get('duration_ms')
        category = EngineRunExecutionCategory.STEP
        metadata: dict[str, Any] | None = {'step_type': step_type}
        if step_type == 'read':
            category = EngineRunExecutionCategory.READ
            metadata = None
        elif step_type == 'write':
            category = EngineRunExecutionCategory.WRITE
            metadata = None
        append_entry(
            key=str(step.get('step_id') or f'step_{order}'),
            label=step_name,
            category=category,
            order=order,
            duration_ms=float(duration_ms) if isinstance(duration_ms, (int, float)) else None,
            metadata=metadata,
        )
        order += 1

    return entries


def _serialize_run(run: EngineRun) -> EngineRunResponseSchema:
    result_json = run.result_json if isinstance(run.result_json, dict) else {}
    execution_entries_raw = result_json.get('execution_entries')
    if isinstance(execution_entries_raw, list):
        execution_entries = [EngineRunExecutionEntry.model_validate(entry).model_dump(mode='json') for entry in execution_entries_raw]
    else:
        query_plans = result_json.get('query_plans')
        execution_entries = build_execution_entries(
            step_timings=run.step_timings,
            query_plans=query_plans if isinstance(query_plans, dict) else None,
            query_plan=run.query_plan,
            total_duration_ms=run.duration_ms,
        )
    return EngineRunResponseSchema.model_validate(
        {
            **run.model_dump(),
            'step_timings': normalize_step_timings(run.step_timings),
            'execution_entries': execution_entries,
        }
    )


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
    analysis_id: str | None | object = _UNSET,
    datasource_id: str | object = _UNSET,
    kind: EngineRunKind | str | object = _UNSET,
    status: EngineRunStatus | str | object = _UNSET,
    request_json: dict[str, Any] | object = _UNSET,
    result_json: dict[str, Any] | None | object = _UNSET,
    merge_result_json: bool = True,
    error_message: str | None | object = _UNSET,
    completed_at: datetime | None | object = _UNSET,
    duration_ms: int | None | object = _UNSET,
    step_timings: dict[str, float] | None | object = _UNSET,
    query_plan: str | None | object = _UNSET,
    execution_entries: list[dict[str, Any]] | None | object = _UNSET,
    progress: float | object = _UNSET,
    current_step: str | None | object = _UNSET,
    triggered_by: str | None | object = _UNSET,
) -> EngineRunResponseSchema:
    run = session.get(EngineRun, run_id)
    if run is None:
        raise FastAPIHTTPException(status_code=404, detail=f'Engine run {run_id} not found')
    session.refresh(run)

    if analysis_id is not _UNSET:
        run.analysis_id = analysis_id if analysis_id is None or isinstance(analysis_id, str) else run.analysis_id
    if datasource_id is not _UNSET and isinstance(datasource_id, str):
        run.datasource_id = datasource_id
    if kind is not _UNSET:
        run.kind = _coerce_kind(kind) if isinstance(kind, (EngineRunKind, str)) else run.kind
    if status is not _UNSET:
        run.status = _coerce_status(status) if isinstance(status, (EngineRunStatus, str)) else run.status
    if request_json is not _UNSET and isinstance(request_json, dict):
        run.request_json = request_json
    if result_json is not _UNSET:
        if result_json is None:
            run.result_json = None
        elif isinstance(result_json, dict):
            base = _copy_result_json(run.result_json) if merge_result_json else {}
            base.update(result_json)
            run.result_json = base
    if error_message is not _UNSET:
        run.error_message = error_message if error_message is None or isinstance(error_message, str) else run.error_message
    if completed_at is not _UNSET:
        run.completed_at = completed_at if completed_at is None or isinstance(completed_at, datetime) else run.completed_at
    if duration_ms is not _UNSET:
        run.duration_ms = duration_ms if duration_ms is None or isinstance(duration_ms, int) else run.duration_ms
    if step_timings is not _UNSET:
        run.step_timings = normalize_step_timings(step_timings if isinstance(step_timings, dict) else None)
    if query_plan is not _UNSET:
        run.query_plan = query_plan if query_plan is None or isinstance(query_plan, str) else run.query_plan
    if progress is not _UNSET and isinstance(progress, (int, float)):
        run.progress = float(progress)
    if current_step is not _UNSET:
        run.current_step = current_step if current_step is None or isinstance(current_step, str) else run.current_step
    if triggered_by is not _UNSET:
        run.triggered_by = triggered_by if triggered_by is None or isinstance(triggered_by, str) else run.triggered_by
    if execution_entries is not _UNSET:
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


def apply_live_event(
    session: Session,
    run_id: str,
    payload: dict[str, Any],
) -> EngineRunResponseSchema | None:
    run = session.get(EngineRun, run_id)
    if run is None:
        return None

    result_json = _copy_result_json(run.result_json)
    event_type = _payload_str(payload, 'type')
    if event_type is None:
        return _serialize_run(run)

    current_tab_id = _payload_str(payload, 'tab_id')
    current_tab_name = _payload_str(payload, 'tab_name')
    current_output_id = _payload_str(payload, 'current_output_id')
    current_output_name = _payload_str(payload, 'current_output_name')
    if current_tab_id is not None:
        result_json['current_tab_id'] = current_tab_id
    if current_tab_name is not None:
        result_json['current_tab_name'] = current_tab_name
    if current_output_id is not None:
        result_json['current_output_id'] = current_output_id
    if current_output_name is not None:
        result_json['current_output_name'] = current_output_name

    if event_type == 'plan':
        plans_raw = result_json.get('query_plans')
        plans = [plan for plan in plans_raw if isinstance(plan, dict)] if isinstance(plans_raw, list) else []
        result_json['query_plans'] = _upsert_live_item(
            plans,
            {
                'tab_id': current_tab_id,
                'tab_name': current_tab_name,
                'optimized_plan': _payload_str(payload, 'optimized_plan') or '',
                'unoptimized_plan': _payload_str(payload, 'unoptimized_plan') or '',
            },
            keys=('tab_id', 'tab_name'),
        )
        if run.query_plan is None:
            run.query_plan = _payload_str(payload, 'optimized_plan') or _payload_str(payload, 'unoptimized_plan')

    if event_type in {'step_start', 'step_complete', 'step_failed'}:
        steps_raw = result_json.get('steps')
        steps = [step for step in steps_raw if isinstance(step, dict)] if isinstance(steps_raw, list) else []
        next_state = 'running' if event_type == 'step_start' else 'completed' if event_type == 'step_complete' else 'failed'
        result_json['steps'] = _upsert_live_item(
            steps,
            {
                'build_step_index': _payload_int(payload, 'build_step_index') or 0,
                'step_index': _payload_int(payload, 'step_index') or 0,
                'step_id': _payload_str(payload, 'step_id') or 'unknown',
                'step_name': _payload_str(payload, 'step_name') or 'Unnamed step',
                'step_type': _payload_str(payload, 'step_type') or 'unknown',
                'tab_id': current_tab_id,
                'tab_name': current_tab_name,
                'state': next_state,
                'duration_ms': _payload_int(payload, 'duration_ms'),
                'row_count': _payload_int(payload, 'row_count'),
                'error': _payload_str(payload, 'error'),
            },
            keys=('build_step_index',),
        )
        run.step_timings = _step_timings_from_live_steps(result_json['steps'])

    if event_type == 'progress':
        progress = _payload_float(payload, 'progress')
        elapsed_ms = _payload_int(payload, 'elapsed_ms')
        if progress is not None:
            run.progress = progress
        if elapsed_ms is not None:
            run.duration_ms = elapsed_ms
        run.current_step = _payload_str(payload, 'current_step')
        result_json['estimated_remaining_ms'] = _payload_int(payload, 'estimated_remaining_ms')
        result_json['current_step_index'] = _payload_int(payload, 'current_step_index')
        result_json['total_steps'] = _payload_int(payload, 'total_steps') or result_json.get('total_steps', 0)

    if event_type == 'resources':
        resources_raw = result_json.get('resources')
        resources = [resource for resource in resources_raw if isinstance(resource, dict)] if isinstance(resources_raw, list) else []
        resource = {
            'sampled_at': _payload_str(payload, 'emitted_at') or datetime.now(UTC).isoformat(),
            'cpu_percent': _payload_float(payload, 'cpu_percent') or 0.0,
            'memory_mb': _payload_float(payload, 'memory_mb') or 0.0,
            'memory_limit_mb': _payload_float(payload, 'memory_limit_mb'),
            'active_threads': _payload_int(payload, 'active_threads') or 0,
            'max_threads': _payload_int(payload, 'max_threads'),
        }
        next_resources = [*resources, resource]
        result_json['resources'] = next_resources[-_MAX_LIVE_RESOURCES:]
        result_json['latest_resources'] = resource

    if event_type == 'log':
        logs_raw = result_json.get('logs')
        logs = [entry for entry in logs_raw if isinstance(entry, dict)] if isinstance(logs_raw, list) else []
        next_logs = [
            *logs,
            {
                'timestamp': _payload_str(payload, 'emitted_at') or datetime.now(UTC).isoformat(),
                'level': _payload_str(payload, 'level') or 'info',
                'message': _payload_str(payload, 'message') or '',
                'step_name': _payload_str(payload, 'step_name'),
                'step_id': _payload_str(payload, 'step_id'),
                'tab_id': current_tab_id,
                'tab_name': current_tab_name,
            },
        ]
        result_json['logs'] = next_logs[-_MAX_LIVE_LOGS:]

    if event_type == 'resource_config':
        result_json['resource_config'] = {
            'max_threads': _payload_int(payload, 'max_threads'),
            'max_memory_mb': _payload_int(payload, 'max_memory_mb'),
            'streaming_chunk_size': _payload_int(payload, 'streaming_chunk_size'),
        }

    result_json['execution_entries'] = _execution_entries_from_live_result(result_json, run.duration_ms)
    run.result_json = result_json
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
