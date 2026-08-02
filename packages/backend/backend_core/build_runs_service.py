import uuid
from datetime import UTC, datetime
from typing import Any, cast

from google.protobuf import json_format, timestamp_pb2
from sqlalchemy import desc, func, or_, select, update
from sqlmodel import Session

from backend_core import runtime_outbox_service
from backend_core.domain.analysis.step_types import PipelineStepType
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.engine_runs.schemas import EngineRunExecutionCategory, EngineRunKind
from backend_core.json_utils import copy_json_dict
from backend_core.persistence.build_runs.models import BuildEvent, BuildRun
from backend_core.persistence.datasource.models import DataSource
from backend_core.sqlmodel_typing import col, sa
from backend_core.time import utc_now as _utcnow
from backend_core.transactions import committed
from dataforge_protocol import compute_pb2

_TERMINAL_STATUSES = frozenset(status for status in BuildRunStatus.members() if status.is_terminal)


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(normalized)
    return timestamp


def _build_event_context_proto(
    event: compute_schemas.BuildEvent,
    *,
    sequence: int,
) -> compute_pb2.BuildEventContext:
    context = compute_pb2.BuildEventContext(
        build_id=event.build_id,
        analysis_id=event.analysis_id,
        emitted_at=_timestamp(event.emitted_at),
        sequence=sequence,
    )
    if event.current_kind is not None:
        context.current_kind = cast(Any, event.current_kind.number)
    if event.current_datasource_id is not None:
        context.current_datasource_id = event.current_datasource_id
    if event.tab_id is not None:
        context.tab_id = event.tab_id
    if event.tab_name is not None:
        context.tab_name = event.tab_name
    if event.current_output_id is not None:
        context.current_output_id = event.current_output_id
    if event.current_output_name is not None:
        context.current_output_name = event.current_output_name
    if event.engine_run_id is not None:
        context.engine_run_id = event.engine_run_id
    return context


def _build_tab_result_proto(result: compute_schemas.BuildTabResult) -> compute_pb2.BuildTabResult:
    message = compute_pb2.BuildTabResult(
        tab_id=result.tab_id,
        tab_name=result.tab_name,
    )
    message.status = cast(Any, result.status.number)
    if result.output_id is not None:
        message.output_id = result.output_id
    if result.output_name is not None:
        message.output_name = result.output_name
    if result.error is not None:
        message.error = result.error
    return message


def _build_step_kind_proto(step_type: str) -> compute_pb2.BuildStepKind:
    message = compute_pb2.BuildStepKind()
    try:
        message.pipeline = cast(Any, PipelineStepType.require(step_type).number)
        return message
    except ValueError:
        pass

    try:
        category = EngineRunExecutionCategory.require(step_type)
    except ValueError:
        raise ValueError(f'Unsupported build step type for protocol event: {step_type!r}') from None
    if category in {EngineRunExecutionCategory.READ, EngineRunExecutionCategory.WRITE}:
        message.execution_category = cast(Any, category.number)
        return message
    raise ValueError(f'Unsupported build execution category for protocol step event: {step_type!r}')


def _build_terminal_event_proto(
    event: compute_schemas.BuildCompleteEvent | compute_schemas.BuildFailedEvent | compute_schemas.BuildCancelledEvent,
) -> compute_pb2.BuildTerminalEvent:
    message = compute_pb2.BuildTerminalEvent(
        progress=event.progress,
        elapsed_ms=event.elapsed_ms,
        total_steps=event.total_steps,
        tabs_built=event.tabs_built,
        duration_ms=event.duration_ms,
    )
    message.results.extend(_build_tab_result_proto(result) for result in event.results)
    if isinstance(event, compute_schemas.BuildFailedEvent) and event.error is not None:
        message.error = event.error
    if isinstance(event, compute_schemas.BuildCancelledEvent):
        message.cancelled_at.CopyFrom(_timestamp(event.cancelled_at))
        if event.cancelled_by is not None:
            message.cancelled_by = event.cancelled_by
    return message


def _build_event_proto(event: compute_schemas.BuildEvent, *, namespace: str, sequence: int) -> compute_pb2.BuildEvent:
    message = compute_pb2.BuildEvent(context=_build_event_context_proto(event, sequence=sequence), namespace=namespace)
    match event:
        case compute_schemas.BuildPlanEvent():
            message.plan.optimized_plan = event.optimized_plan
            message.plan.unoptimized_plan = event.unoptimized_plan
            return message
        case compute_schemas.BuildStepStartEvent():
            message.step_started.build_step_index = event.build_step_index
            message.step_started.step_index = event.step_index
            message.step_started.step_id = event.step_id
            message.step_started.step_name = event.step_name
            message.step_started.step_kind.CopyFrom(_build_step_kind_proto(event.step_type))
            message.step_started.total_steps = event.total_steps
            return message
        case compute_schemas.BuildStepCompleteEvent():
            message.step_completed.build_step_index = event.build_step_index
            message.step_completed.step_index = event.step_index
            message.step_completed.step_id = event.step_id
            message.step_completed.step_name = event.step_name
            message.step_completed.step_kind.CopyFrom(_build_step_kind_proto(event.step_type))
            message.step_completed.duration_ms = event.duration_ms
            message.step_completed.total_steps = event.total_steps
            if event.row_count is not None:
                message.step_completed.row_count = event.row_count
            return message
        case compute_schemas.BuildStepFailedEvent():
            message.step_failed.build_step_index = event.build_step_index
            message.step_failed.step_index = event.step_index
            message.step_failed.step_id = event.step_id
            message.step_failed.step_name = event.step_name
            message.step_failed.step_kind.CopyFrom(_build_step_kind_proto(event.step_type))
            message.step_failed.error = event.error
            message.step_failed.total_steps = event.total_steps
            return message
        case compute_schemas.BuildProgressEvent():
            message.progress.progress = event.progress
            message.progress.elapsed_ms = event.elapsed_ms
            message.progress.total_steps = event.total_steps
            if event.estimated_remaining_ms is not None:
                message.progress.estimated_remaining_ms = event.estimated_remaining_ms
            if event.current_step is not None:
                message.progress.current_step = event.current_step
            if event.current_step_index is not None:
                message.progress.current_step_index = event.current_step_index
            return message
        case compute_schemas.BuildResourceEvent():
            message.resources.cpu_percent = event.cpu_percent
            message.resources.memory_mb = event.memory_mb
            message.resources.active_threads = event.active_threads
            if event.memory_limit_mb is not None:
                message.resources.memory_limit_mb = event.memory_limit_mb
            if event.max_threads is not None:
                message.resources.max_threads = event.max_threads
            return message
        case compute_schemas.BuildLogEvent():
            message.log.level = cast(Any, event.level.number)
            message.log.message = event.message
            if event.step_name is not None:
                message.log.step_name = event.step_name
            if event.step_id is not None:
                message.log.step_id = event.step_id
            return message
        case compute_schemas.BuildCompleteEvent():
            message.completed.CopyFrom(_build_terminal_event_proto(event))
            return message
        case compute_schemas.BuildFailedEvent():
            message.failed.CopyFrom(_build_terminal_event_proto(event))
            return message
        case compute_schemas.BuildCancelledEvent():
            message.cancelled.CopyFrom(_build_terminal_event_proto(event))
            return message
    raise ValueError(f'Unsupported build event type: {type(event).__name__}')


def stage_build_run(
    session: Session,
    *,
    build_id: str,
    namespace: str,
    schedule_id: str | None = None,
    analysis_id: str,
    analysis_name: str,
    request_json: dict[str, Any],
    starter_json: dict[str, Any],
    resource_config_json: dict[str, Any] | None = None,
    result_json: dict[str, Any] | None = None,
    status: BuildRunStatus | str = BuildRunStatus.RUNNING,
    current_engine_run_id: str | None = None,
    current_kind: str | None = None,
    current_datasource_id: str | None = None,
    current_tab_id: str | None = None,
    current_tab_name: str | None = None,
    current_output_id: str | None = None,
    current_output_name: str | None = None,
    total_tabs: int = 0,
    execution_generation: int = 0,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
) -> BuildRun:
    now = created_at or _utcnow()
    run_started_at = started_at or now
    run = BuildRun(
        id=build_id,
        namespace=namespace,
        schedule_id=schedule_id,
        analysis_id=analysis_id,
        analysis_name=analysis_name,
        status=BuildRunStatus.require(status),
        request_json=copy_json_dict(request_json),
        starter_json=copy_json_dict(starter_json),
        resource_config_json=copy_json_dict(resource_config_json) if isinstance(resource_config_json, dict) else None,
        result_json=copy_json_dict(result_json) if isinstance(result_json, dict) else None,
        current_engine_run_id=current_engine_run_id,
        current_kind=current_kind,
        current_datasource_id=current_datasource_id,
        current_tab_id=current_tab_id,
        current_tab_name=current_tab_name,
        current_output_id=current_output_id,
        current_output_name=current_output_name,
        created_at=now,
        started_at=run_started_at,
        updated_at=now,
        total_tabs=total_tabs,
        execution_generation=execution_generation,
    )
    session.add(run)
    session.flush()
    return run


create_build_run = committed(stage_build_run, refresh=True)


def get_build_run(session: Session, build_id: str) -> BuildRun | None:
    return session.get(BuildRun, build_id)


def get_build_run_by_engine_run(session: Session, engine_run_id: str) -> BuildRun | None:
    stmt = select(BuildRun).where(sa(BuildRun.current_engine_run_id == engine_run_id)).order_by(desc(sa(BuildRun.updated_at)), sa(BuildRun.id)).limit(1)
    return session.execute(stmt).scalars().first()


def list_build_runs(
    session: Session,
    *,
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: str | None = None,
    status: BuildRunStatus | str | None = None,
    current_engine_run_id: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BuildRun]:
    stmt = select(BuildRun).join(
        DataSource,
        col(BuildRun.current_datasource_id) == col(DataSource.id),
        isouter=True,
    )
    if analysis_id is not None:
        stmt = stmt.where(sa(BuildRun.analysis_id == analysis_id))
    if datasource_id is not None:
        stmt = stmt.where(
            or_(
                sa(BuildRun.current_datasource_id == datasource_id),
                sa(BuildRun.current_output_id == datasource_id),
            )
        )
    if kind is not None:
        stmt = stmt.where(sa(BuildRun.current_kind == kind))
    if status is not None:
        stmt = stmt.where(sa(BuildRun.status == BuildRunStatus.require(status)))
    if current_engine_run_id is not None:
        stmt = stmt.where(sa(BuildRun.current_engine_run_id == current_engine_run_id))
    if search:
        q = f'%{search}%'
        stmt = stmt.where(
            or_(
                col(BuildRun.id).ilike(q),
                col(BuildRun.analysis_id).ilike(q),
                col(BuildRun.current_datasource_id).ilike(q),
                col(BuildRun.current_output_id).ilike(q),
                col(BuildRun.current_tab_name).ilike(q),
                col(BuildRun.current_output_name).ilike(q),
                col(BuildRun.current_step).ilike(q),
                col(BuildRun.analysis_name).ilike(q),
                col(DataSource.name).ilike(q),
            )
        )
    stmt = stmt.order_by(desc(sa(BuildRun.created_at)), sa(BuildRun.id)).limit(limit).offset(offset)
    runs = list(session.execute(stmt).scalars().all())
    for run in runs:
        session.refresh(run)
    return runs


def has_inflight_build_for_schedule(session: Session, schedule_id: str) -> bool:
    stmt = select(BuildRun).where(sa(BuildRun.schedule_id == schedule_id)).where(sa(BuildRun.status == BuildRunStatus.QUEUED)).limit(1)
    if session.execute(stmt).first() is not None:
        return True
    running_stmt = select(BuildRun).where(sa(BuildRun.schedule_id == schedule_id)).where(sa(BuildRun.status == BuildRunStatus.RUNNING)).limit(1)
    return session.execute(running_stmt).first() is not None


def _cas_update_build_run(session: Session, *, run: BuildRun, values: dict[str, object], expected_status: BuildRunStatus) -> BuildRun | None:
    result = session.execute(
        update(BuildRun)
        .where(sa(BuildRun.id == run.id))
        .where(sa(BuildRun.status == expected_status))
        .where(sa(BuildRun.version == run.version))
        .values(**values)
    )
    rowcount = getattr(result, 'rowcount', None)
    if rowcount != 1:
        session.rollback()
        fresh = session.get(BuildRun, run.id)
        if fresh is not None:
            session.refresh(fresh)
        return fresh
    session.commit()
    fresh = session.get(BuildRun, run.id)
    if fresh is None:
        return None
    session.refresh(fresh)
    return fresh


def guarded_terminal_update(session: Session, *, build_id: str, event: compute_schemas.BuildEvent) -> BuildRun | None:
    session.expire_all()
    run = session.get(BuildRun, build_id)
    if run is None:
        raise ValueError(f'Build run {build_id} not found')
    if run.status in _TERMINAL_STATUSES:
        return None
    expected_status = run.status
    values = BuildRun.terminal_update_values(event)
    if values is None:
        return None
    values['version'] = run.version + 1
    updated = _cas_update_build_run(session, run=run, values=values, expected_status=expected_status)
    if updated is None:
        return None
    terminal_status = BuildRun.terminal_status_for_event(event)
    if updated.status in _TERMINAL_STATUSES and updated.status != expected_status and updated.status != terminal_status:
        return None
    return updated


def mark_build_running(session: Session, build_id: str, *, execution_generation: int, now: datetime | None = None) -> BuildRun | None:
    session.expire_all()
    run = session.get(BuildRun, build_id)
    if run is None:
        return None
    if run.status not in {BuildRunStatus.QUEUED, BuildRunStatus.RUNNING}:
        return run
    if execution_generation < run.execution_generation:
        return None
    if run.status == BuildRunStatus.RUNNING and execution_generation == run.execution_generation:
        return run
    marker = now or _utcnow()
    return _cas_update_build_run(
        session,
        run=run,
        expected_status=run.status,
        values={
            'status': BuildRunStatus.RUNNING,
            'execution_generation': execution_generation,
            'updated_at': marker,
            'version': run.version + 1,
        },
    )


def stage_build_result_json(session: Session, build_id: str, result_json: dict[str, Any] | None) -> BuildRun:
    run = session.get(BuildRun, build_id)
    if run is None:
        raise ValueError(f'Build run {build_id} not found')
    run.result_json = copy_json_dict(result_json) if isinstance(result_json, dict) else None
    run.updated_at = _utcnow()
    run.version += 1
    session.add(run)
    session.flush()
    return run


update_build_result_json = committed(stage_build_result_json, refresh=True)


def stage_build_event(
    session: Session,
    *,
    build_id: str,
    event: compute_schemas.BuildEvent,
    resource_config_json: dict[str, Any] | None = None,
    expected_execution_generation: int | None = None,
    authoritative_execution_generation: int | None = None,
) -> BuildEvent | None:
    if expected_execution_generation is not None and authoritative_execution_generation is not None:
        raise ValueError('Expected and authoritative execution generations are mutually exclusive')
    run = session.execute(select(BuildRun).where(sa(BuildRun.id == build_id)).with_for_update().execution_options(populate_existing=True)).scalars().first()
    if run is None:
        raise ValueError(f'Build run {build_id} not found')
    if expected_execution_generation is not None and run.execution_generation != expected_execution_generation:
        return None
    if authoritative_execution_generation is not None and authoritative_execution_generation <= run.execution_generation:
        return None
    terminal_status = BuildRun.terminal_status_for_event(event)
    if run.status in _TERMINAL_STATUSES and terminal_status != run.status:
        return None
    run_namespace = run.namespace

    should_update_run = run.status not in _TERMINAL_STATUSES
    if should_update_run:
        if authoritative_execution_generation is not None:
            run.execution_generation = authoritative_execution_generation
        run.apply_event_context(event)
        if resource_config_json is not None:
            run.resource_config_json = copy_json_dict(resource_config_json)

        run.apply_runtime_event(event)

        if terminal_status is not None and not run.apply_terminal_event(event):
            return None

        run.updated_at = event.emitted_at
        run.version += 1
    sequence = run.next_event_sequence
    run.next_event_sequence += 1
    event_id = str(uuid.uuid4())
    payload_json = event.model_dump(mode='json')
    created_at = _utcnow()
    event_row = BuildEvent(
        id=event_id,
        build_id=build_id,
        namespace=run.namespace,
        sequence=sequence,
        type=event.type,
        payload_json=payload_json,
        engine_run_id=event.engine_run_id,
        emitted_at=event.emitted_at,
        created_at=created_at,
    )
    session.add(event_row)
    session.add(run)
    runtime_outbox_service.enqueue_api_build_notification(
        session,
        namespace=run_namespace,
        build_id=build_id,
        latest_sequence=sequence,
    )
    session.flush()
    return BuildEvent(
        id=event_id,
        build_id=build_id,
        namespace=run_namespace,
        sequence=sequence,
        type=event.type,
        payload_json=payload_json,
        engine_run_id=event.engine_run_id,
        emitted_at=event.emitted_at,
        created_at=created_at,
    )


append_build_event = committed(stage_build_event)


def _list_build_events(session: Session, build_id: str) -> list[BuildEvent]:
    stmt = select(BuildEvent).where(sa(BuildEvent.build_id == build_id)).order_by(sa(BuildEvent.sequence))
    return list(session.execute(stmt).scalars().all())


def list_build_events_after(session: Session, build_id: str, sequence: int = 0) -> list[BuildEvent]:
    stmt = select(BuildEvent).where(sa(BuildEvent.build_id == build_id)).where(sa(BuildEvent.sequence > sequence)).order_by(sa(BuildEvent.sequence))
    return list(session.execute(stmt).scalars().all())


def get_latest_sequence(session: Session, build_id: str) -> int:
    stmt = select(sa(BuildRun.next_event_sequence)).where(sa(BuildRun.id == build_id))
    next_sequence = session.execute(stmt).scalar_one_or_none()
    return next_sequence - 1 if isinstance(next_sequence, int) else 0


def latest_namespace_update(session: Session, *, namespace: str) -> datetime | None:
    stmt = select(func.max(BuildRun.updated_at)).where(sa(BuildRun.namespace == namespace))
    updated = session.execute(stmt).scalar_one()
    return updated if isinstance(updated, datetime) else None


def serialize_event_row(row: BuildEvent) -> dict[str, object]:
    event = compute_schemas.BuildEventAdapter.validate_python(row.payload_json)
    return cast(
        dict[str, object],
        json_format.MessageToDict(
            _build_event_proto(event, namespace=row.namespace, sequence=row.sequence),
            always_print_fields_with_no_presence=True,
        ),
    )


def fold_build_detail(session: Session, build_run: BuildRun) -> compute_schemas.ActiveBuildDetail:
    steps: dict[tuple[str | None, str], compute_schemas.BuildStepSnapshot] = {}
    plans: dict[tuple[str | None, str | None], compute_schemas.BuildQueryPlanSnapshot] = {}
    resources: list[compute_schemas.BuildResourceSnapshot] = []
    logs: list[compute_schemas.BuildLogEntry] = []
    results: list[compute_schemas.BuildTabResult] = []

    for row in _list_build_events(session, build_run.id):
        event = compute_schemas.BuildEventAdapter.validate_python(row.payload_json)
        if isinstance(event, compute_schemas.BuildPlanEvent):
            plans[(event.tab_id, event.tab_name)] = compute_schemas.BuildQueryPlanSnapshot(
                tab_id=event.tab_id, tab_name=event.tab_name, optimized_plan=event.optimized_plan, unoptimized_plan=event.unoptimized_plan
            )
            continue
        if isinstance(event, compute_schemas.BuildStepStartEvent):
            steps[(event.tab_id, event.step_id)] = compute_schemas.BuildStepSnapshot(
                build_step_index=event.build_step_index,
                step_index=event.step_index,
                step_id=event.step_id,
                step_name=event.step_name,
                step_type=event.step_type,
                tab_id=event.tab_id,
                tab_name=event.tab_name,
                state=compute_schemas.BuildStepState.RUNNING,
            )
            continue
        if isinstance(event, compute_schemas.BuildStepCompleteEvent):
            steps[(event.tab_id, event.step_id)] = compute_schemas.BuildStepSnapshot(
                build_step_index=event.build_step_index,
                step_index=event.step_index,
                step_id=event.step_id,
                step_name=event.step_name,
                step_type=event.step_type,
                tab_id=event.tab_id,
                tab_name=event.tab_name,
                state=compute_schemas.BuildStepState.COMPLETED,
                duration_ms=event.duration_ms,
                row_count=event.row_count,
            )
            continue
        if isinstance(event, compute_schemas.BuildStepFailedEvent):
            steps[(event.tab_id, event.step_id)] = compute_schemas.BuildStepSnapshot(
                build_step_index=event.build_step_index,
                step_index=event.step_index,
                step_id=event.step_id,
                step_name=event.step_name,
                step_type=event.step_type,
                tab_id=event.tab_id,
                tab_name=event.tab_name,
                state=compute_schemas.BuildStepState.FAILED,
                error=event.error,
            )
            continue
        if isinstance(event, compute_schemas.BuildResourceEvent):
            resources.append(
                compute_schemas.BuildResourceSnapshot(
                    sampled_at=event.emitted_at,
                    cpu_percent=event.cpu_percent,
                    memory_mb=event.memory_mb,
                    memory_limit_mb=event.memory_limit_mb,
                    active_threads=event.active_threads,
                    max_threads=event.max_threads,
                )
            )
            continue
        if isinstance(event, compute_schemas.BuildLogEvent):
            logs.append(
                compute_schemas.BuildLogEntry(
                    timestamp=event.emitted_at,
                    level=event.level,
                    message=event.message,
                    step_name=event.step_name,
                    step_id=event.step_id,
                    tab_id=event.tab_id,
                    tab_name=event.tab_name,
                )
            )
            continue
        if isinstance(event, compute_schemas.BuildCompleteEvent | compute_schemas.BuildFailedEvent | compute_schemas.BuildCancelledEvent):
            results = list(event.results)

    status, orphan_error = build_run.status_kind().to_active_build_status()
    error = build_run.error_message or orphan_error
    resource_config = (
        compute_schemas.BuildResourceConfigSummary.model_validate(build_run.resource_config_json) if isinstance(build_run.resource_config_json, dict) else None
    )
    starter = compute_schemas.BuildStarter.model_validate(build_run.starter_json)
    result_json = copy_json_dict(build_run.result_json) if isinstance(build_run.result_json, dict) else None
    return compute_schemas.ActiveBuildDetail(
        build_id=build_run.id,
        analysis_id=build_run.analysis_id,
        analysis_name=build_run.analysis_name,
        namespace=build_run.namespace,
        status=status,
        started_at=build_run.started_at,
        starter=starter,
        resource_config=resource_config,
        progress=build_run.progress,
        elapsed_ms=build_run.elapsed_ms,
        estimated_remaining_ms=build_run.estimated_remaining_ms,
        current_step=build_run.current_step,
        current_step_index=build_run.current_step_index,
        total_steps=build_run.total_steps,
        current_kind=EngineRunKind.parse(build_run.current_kind),
        current_datasource_id=build_run.current_datasource_id,
        current_tab_id=build_run.current_tab_id,
        current_tab_name=build_run.current_tab_name,
        current_output_id=build_run.current_output_id,
        current_output_name=build_run.current_output_name,
        current_engine_run_id=build_run.current_engine_run_id,
        total_tabs=build_run.total_tabs,
        cancelled_at=build_run.cancelled_at,
        cancelled_by=build_run.cancelled_by,
        result_json=result_json,
        steps=sorted(steps.values(), key=lambda item: item.build_step_index),
        query_plans=list(plans.values()),
        latest_resources=resources[-1] if resources else None,
        resources=resources,
        logs=logs,
        results=results,
        duration_ms=build_run.duration_ms,
        error=error,
        request_json=dict(build_run.request_json),
    )


def build_summary(build_run: BuildRun) -> compute_schemas.ActiveBuildSummary:
    status, _orphan_error = build_run.status_kind().to_active_build_status()
    resource_config = (
        compute_schemas.BuildResourceConfigSummary.model_validate(build_run.resource_config_json) if isinstance(build_run.resource_config_json, dict) else None
    )
    starter = compute_schemas.BuildStarter.model_validate(build_run.starter_json)
    return compute_schemas.ActiveBuildSummary(
        build_id=build_run.id,
        analysis_id=build_run.analysis_id,
        analysis_name=build_run.analysis_name,
        namespace=build_run.namespace,
        status=status,
        started_at=build_run.started_at,
        starter=starter,
        resource_config=resource_config,
        progress=build_run.progress,
        elapsed_ms=build_run.elapsed_ms,
        estimated_remaining_ms=build_run.estimated_remaining_ms,
        current_step=build_run.current_step,
        current_step_index=build_run.current_step_index,
        total_steps=build_run.total_steps,
        current_kind=EngineRunKind.parse(build_run.current_kind),
        current_datasource_id=build_run.current_datasource_id,
        current_tab_id=build_run.current_tab_id,
        current_tab_name=build_run.current_tab_name,
        current_output_id=build_run.current_output_id,
        current_output_name=build_run.current_output_name,
        current_engine_run_id=build_run.current_engine_run_id,
        total_tabs=build_run.total_tabs,
        cancelled_at=build_run.cancelled_at,
        cancelled_by=build_run.cancelled_by,
        result_json=copy_json_dict(build_run.result_json) if isinstance(build_run.result_json, dict) else None,
    )


def mark_running_builds_orphaned(session: Session, *, now: datetime | None = None) -> int:
    marker = now or _utcnow()
    stmt = select(BuildRun).where(sa(BuildRun.status == BuildRunStatus.RUNNING))
    runs = list(session.execute(stmt).scalars().all())
    if not runs:
        return 0
    for run in runs:
        started_at = run.started_at if run.started_at.tzinfo is not None else run.started_at.replace(tzinfo=UTC)
        run.status = BuildRunStatus.ORPHANED
        run.completed_at = marker
        run.updated_at = marker
        run.estimated_remaining_ms = None
        run.duration_ms = max(int((marker - started_at).total_seconds() * 1000), 0)
        run.elapsed_ms = run.duration_ms
        run.error_message = 'Build orphaned during startup recovery'
        run.version += 1
        session.add(run)
    session.commit()
    return len(runs)
