import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, or_, select, update
from sqlmodel import Session

from contracts.build_runs.models import BuildEvent, BuildRun, BuildRunStatus
from contracts.compute import schemas as compute_schemas
from contracts.engine_runs.schemas import EngineRunKind

_TERMINAL_STATUSES = frozenset(status for status in BuildRunStatus if status.is_terminal)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _copy_json_dict(value: dict[str, Any] | None) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def create_build_run(
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
        request_json=_copy_json_dict(request_json),
        starter_json=_copy_json_dict(starter_json),
        resource_config_json=_copy_json_dict(resource_config_json) if isinstance(resource_config_json, dict) else None,
        result_json=_copy_json_dict(result_json) if isinstance(result_json, dict) else None,
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
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_build_run(session: Session, build_id: str) -> BuildRun | None:
    return session.get(BuildRun, build_id)


def get_build_run_by_engine_run(session: Session, engine_run_id: str) -> BuildRun | None:
    stmt = (
        select(BuildRun)
        .where(BuildRun.current_engine_run_id == engine_run_id)  # type: ignore[arg-type]
        .order_by(desc(BuildRun.updated_at))  # type: ignore[arg-type]
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def list_build_runs(
    session: Session,
    *,
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: str | None = None,
    status: BuildRunStatus | str | None = None,
    current_engine_run_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BuildRun]:
    stmt = select(BuildRun)
    if analysis_id is not None:
        stmt = stmt.where(BuildRun.analysis_id == analysis_id)  # type: ignore[arg-type]
    if datasource_id is not None:
        stmt = stmt.where(
            or_(
                BuildRun.current_datasource_id == datasource_id,  # type: ignore[arg-type]
                BuildRun.current_output_id == datasource_id,  # type: ignore[arg-type]
            )
        )
    if kind is not None:
        stmt = stmt.where(BuildRun.current_kind == kind)  # type: ignore[arg-type]
    if status is not None:
        stmt = stmt.where(BuildRun.status == BuildRunStatus.require(status))  # type: ignore[arg-type]
    if current_engine_run_id is not None:
        stmt = stmt.where(BuildRun.current_engine_run_id == current_engine_run_id)  # type: ignore[arg-type]
    stmt = stmt.order_by(desc(BuildRun.created_at)).limit(limit).offset(offset)  # type: ignore[arg-type]
    runs = list(session.execute(stmt).scalars().all())
    for run in runs:
        session.refresh(run)
    return runs


def has_inflight_build_for_schedule(session: Session, schedule_id: str) -> bool:
    stmt = (
        select(BuildRun)
        .where(BuildRun.schedule_id == schedule_id)  # type: ignore[arg-type]
        .where(BuildRun.status == BuildRunStatus.QUEUED)  # type: ignore[arg-type]
        .limit(1)
    )
    if session.execute(stmt).first() is not None:
        return True
    running_stmt = (
        select(BuildRun)
        .where(BuildRun.schedule_id == schedule_id)  # type: ignore[arg-type]
        .where(BuildRun.status == BuildRunStatus.RUNNING)  # type: ignore[arg-type]
        .limit(1)
    )
    return session.execute(running_stmt).first() is not None


def _next_sequence(session: Session, build_id: str) -> int:
    stmt = select(func.max(BuildEvent.sequence)).where(BuildEvent.build_id == build_id)  # type: ignore[arg-type]
    last = session.execute(stmt).scalar_one()
    return (int(last) if isinstance(last, int) else 0) + 1


def _cas_update_build_run(session: Session, *, run: BuildRun, values: dict[str, object], expected_status: BuildRunStatus) -> BuildRun | None:
    result = session.execute(
        update(BuildRun)
        .where(BuildRun.id == run.id)  # type: ignore[arg-type]
        .where(BuildRun.status == expected_status)  # type: ignore[arg-type]
        .where(BuildRun.version == run.version)  # type: ignore[arg-type]
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


def mark_build_running(session: Session, build_id: str, *, now: datetime | None = None) -> BuildRun | None:
    session.expire_all()
    run = session.get(BuildRun, build_id)
    if run is None:
        return None
    if run.status != BuildRunStatus.QUEUED:
        return run
    marker = now or _utcnow()
    return _cas_update_build_run(
        session, run=run, expected_status=BuildRunStatus.QUEUED, values={'status': BuildRunStatus.RUNNING, 'updated_at': marker, 'version': run.version + 1}
    )


def update_build_result_json(session: Session, build_id: str, result_json: dict[str, Any] | None) -> BuildRun:
    run = session.get(BuildRun, build_id)
    if run is None:
        raise ValueError(f'Build run {build_id} not found')
    run.result_json = _copy_json_dict(result_json) if isinstance(result_json, dict) else None
    run.updated_at = _utcnow()
    run.version += 1
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def append_build_event(
    session: Session, *, build_id: str, event: compute_schemas.BuildEvent, resource_config_json: dict[str, Any] | None = None
) -> BuildEvent | None:
    run = session.get(BuildRun, build_id)
    if run is None:
        raise ValueError(f'Build run {build_id} not found')
    terminal_status = BuildRun.terminal_status_for_event(event)
    if run.status in _TERMINAL_STATUSES and terminal_status != run.status:
        return None
    run_namespace = run.namespace

    should_update_run = run.status not in _TERMINAL_STATUSES
    if should_update_run:
        run.apply_event_context(event)
        if resource_config_json is not None:
            run.resource_config_json = _copy_json_dict(resource_config_json)

        run.apply_runtime_event(event)

        if terminal_status is not None and not run.apply_terminal_event(event):
            return None

        run.updated_at = event.emitted_at
        run.version += 1
    sequence = _next_sequence(session, build_id)
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
    if should_update_run:
        session.add(run)
    session.commit()
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


def _list_build_events(session: Session, build_id: str) -> list[BuildEvent]:
    stmt = (
        select(BuildEvent)
        .where(BuildEvent.build_id == build_id)  # type: ignore[arg-type]
        .order_by(BuildEvent.sequence)  # type: ignore[arg-type]
    )
    return list(session.execute(stmt).scalars().all())


def list_build_events_after(session: Session, build_id: str, sequence: int = 0) -> list[BuildEvent]:
    stmt = (
        select(BuildEvent)
        .where(BuildEvent.build_id == build_id)  # type: ignore[arg-type]
        .where(BuildEvent.sequence > sequence)  # type: ignore[arg-type]
        .order_by(BuildEvent.sequence)  # type: ignore[arg-type]
    )
    return list(session.execute(stmt).scalars().all())


def get_latest_sequence(session: Session, build_id: str) -> int:
    stmt = select(func.max(BuildEvent.sequence)).where(BuildEvent.build_id == build_id)  # type: ignore[arg-type]
    last = session.execute(stmt).scalar_one()
    return int(last) if isinstance(last, int) else 0


def latest_namespace_update(session: Session, *, namespace: str) -> datetime | None:
    stmt = select(func.max(BuildRun.updated_at)).where(BuildRun.namespace == namespace)  # type: ignore[arg-type]
    updated = session.execute(stmt).scalar_one()
    return updated if isinstance(updated, datetime) else None


def serialize_event_row(row: BuildEvent) -> dict[str, object]:
    event = compute_schemas.BuildEventAdapter.validate_python(row.payload_json)
    payload = event.model_dump(mode='json')
    payload['sequence'] = row.sequence
    return payload


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

    status, orphan_error = build_run.status.to_active_build_status()
    error = build_run.error_message or orphan_error
    resource_config = (
        compute_schemas.BuildResourceConfigSummary.model_validate(build_run.resource_config_json) if isinstance(build_run.resource_config_json, dict) else None
    )
    starter = compute_schemas.BuildStarter.model_validate(build_run.starter_json)
    result_json = _copy_json_dict(build_run.result_json) if isinstance(build_run.result_json, dict) else None
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
    status, _orphan_error = build_run.status.to_active_build_status()
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
        result_json=_copy_json_dict(build_run.result_json) if isinstance(build_run.result_json, dict) else None,
    )


def mark_running_builds_orphaned(session: Session, *, now: datetime | None = None) -> int:
    marker = now or _utcnow()
    stmt = select(BuildRun).where(BuildRun.status == BuildRunStatus.RUNNING)  # type: ignore[arg-type]
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
