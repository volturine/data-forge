import logging
import uuid
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import croniter  # type: ignore[import-untyped]
from contracts.analysis.models import Analysis
from contracts.build_jobs.live import hub as build_job_hub
from contracts.build_runs.models import BuildRunStatus
from contracts.compute import schemas as compute_schemas
from contracts.datasource.models import DataSource, DataSourceTargetKind
from contracts.engine_runs.schemas import EngineRunKind
from contracts.runtime import ipc as runtime_ipc
from contracts.scheduler.models import Schedule
from contracts.scheduler.schemas import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from core import (
    build_jobs_service as build_job_service,
)
from core import (
    build_runs_service as build_run_service,
)
from core.exceptions import (
    DataSourceNotFoundError,
    ScheduleNotFoundError,
    ScheduleValidationError,
)
from core.namespace import get_namespace
from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col

logger = logging.getLogger(__name__)

_SCHEDULE_TERMINAL_STATUSES = frozenset(status for status in BuildRunStatus if status.is_terminal)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _mark_schedule_failure(
    session: Session,
    *,
    schedule: Schedule,
    error: str,
    now: datetime | None = None,
) -> Schedule:
    stamp = now or _utcnow()
    schedule.last_failure_at = stamp
    schedule.lease_owner = None
    schedule.lease_expires_at = None
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return schedule


def mark_schedule_enqueue_failed(session: Session, schedule_id: str, *, error: str) -> Schedule | None:
    schedule = session.get(Schedule, schedule_id)
    if schedule is None:
        return None
    return _mark_schedule_failure(session, schedule=schedule, error=error)


def build_analysis_pipeline_payload(session: Session, analysis: Analysis, datasource_id: str | None = None) -> dict[str, Any]:
    pipeline = analysis.pipeline_definition
    tabs = pipeline.get("tabs", []) if isinstance(pipeline, dict) else []
    if not isinstance(tabs, list) or not tabs:
        return {"analysis_id": str(analysis.id), "tabs": []}

    output_map: dict[str, str] = {}
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        tab_id = tab.get("id")
        output = tab.get("output")
        if not isinstance(output, dict):
            raise ValueError("Analysis pipeline tab missing output configuration")
        output_id = output.get("result_id")
        if not output_id:
            raise ValueError("Analysis pipeline tab missing output.result_id")
        if tab_id:
            output_map[str(tab_id)] = str(output_id)

    output_to_tab = {output_id: tab_id for tab_id, output_id in output_map.items()}

    def enrich_step(step: dict[str, object]) -> dict[str, Any]:
        config = step.get("config")
        if not isinstance(config, dict):
            return step
        next_config = dict(config)
        right_source = next_config.get("right_source") or next_config.get("rightDataSource")
        if isinstance(right_source, str) and right_source and right_source not in output_to_tab:
            datasource_model = session.get(DataSource, right_source)
            if datasource_model is not None:
                next_config["right_source_datasource"] = {
                    "id": right_source,
                    "analysis_tab_id": None,
                    "source_type": datasource_model.source_type,
                    "config": dict(datasource_model.config),
                }
        raw_sources = next_config.get("sources")
        source_ids = [raw_sources] if isinstance(raw_sources, str) else raw_sources if isinstance(raw_sources, list) else []
        refs: list[dict[str, Any]] = []
        for source in source_ids:
            if not isinstance(source, str) or not source or source in output_to_tab:
                continue
            datasource_model = session.get(DataSource, source)
            if datasource_model is None:
                continue
            refs.append(
                {
                    "id": source,
                    "analysis_tab_id": None,
                    "source_type": datasource_model.source_type,
                    "config": dict(datasource_model.config),
                }
            )
        if refs:
            next_config["source_datasources"] = refs
        return {**step, "config": next_config}

    next_tabs: list[dict[str, Any]] = []
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        datasource = tab.get("datasource")
        if not isinstance(datasource, dict):
            raise ValueError("Analysis pipeline tab datasource must be a dict")
        output = tab.get("output")
        if not isinstance(output, dict):
            raise ValueError("Analysis pipeline tab missing output configuration")
        output_id = output.get("result_id")
        if not output_id:
            raise ValueError("Analysis pipeline tab missing output.result_id")
        config = datasource.get("config")
        if not isinstance(config, dict):
            raise ValueError("Analysis pipeline tab datasource.config must be a dict")
        branch = config.get("branch")
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("Analysis pipeline tab datasource.config.branch is required")
        tab_datasource_id = datasource.get("id")
        if not tab_datasource_id:
            raise ValueError("Analysis pipeline tab missing datasource.id")
        analysis_tab_id = datasource.get("analysis_tab_id") if isinstance(datasource.get("analysis_tab_id"), str) else None
        source_type = "analysis" if analysis_tab_id or str(tab_datasource_id) in output_to_tab else None
        merged_config = dict(config)
        if source_type is None:
            datasource_model = session.get(DataSource, str(tab_datasource_id))
            if datasource_model is not None:
                source_type = datasource_model.source_type
                merged_config = {"branch": branch, **datasource_model.config, **config}
        if datasource_id and str(datasource_id) != str(output_id) and str(datasource_id) != str(tab_datasource_id):
            next_tabs.append(
                {
                    **tab,
                    "datasource": {
                        **datasource,
                        "id": tab_datasource_id,
                        "analysis_tab_id": analysis_tab_id,
                        "source_type": source_type,
                        "config": merged_config,
                    },
                    "steps": [enrich_step(step) for step in tab.get("steps", []) if isinstance(step, dict)],
                }
            )
            continue
        next_tabs.append(
            {
                **tab,
                "datasource": {
                    **datasource,
                    "id": tab_datasource_id,
                    "analysis_tab_id": analysis_tab_id,
                    "source_type": source_type,
                    "config": merged_config,
                },
                "steps": [enrich_step(step) for step in tab.get("steps", []) if isinstance(step, dict)],
            }
        )

    return {"analysis_id": str(analysis.id), "tabs": next_tabs}


def _build_analysis_request(session: Session, schedule: Schedule, analysis_id: str) -> tuple[compute_schemas.BuildRequest, str, str, str | None, str | None]:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise ValueError(f"Analysis {analysis_id} not found for datasource {schedule.datasource_id}")

    pipeline = analysis.pipeline
    target_tab = next(
        (tab for tab in pipeline.tabs if tab.output.result_id == schedule.datasource_id),
        None,
    )
    if target_tab is None:
        raise ValueError(f"No tab found in analysis {analysis_id} that produces datasource {schedule.datasource_id}")

    pipeline_payload = build_analysis_pipeline_payload(session, analysis, datasource_id=schedule.datasource_id)
    request = compute_schemas.BuildRequest.model_validate(
        {
            "analysis_pipeline": pipeline_payload,
            "tab_id": target_tab.id,
        }
    )
    return request, str(analysis.id), analysis.name, target_tab.id, target_tab.name


def _build_refresh_request(schedule: Schedule) -> compute_schemas.BuildRequest:
    pipeline = {
        "analysis_id": schedule.id,
        "tabs": [
            {
                "id": schedule.id,
                "name": "Scheduled refresh",
                "datasource": {
                    "id": schedule.datasource_id,
                    "analysis_tab_id": None,
                    "source_type": "schedule",
                    "config": {"branch": "master"},
                },
                "output": {
                    "result_id": schedule.datasource_id,
                    "datasource_type": "iceberg",
                    "format": "parquet",
                    "filename": f"schedule_{schedule.id}",
                },
                "steps": [],
            }
        ],
    }
    return compute_schemas.BuildRequest.model_validate({"analysis_pipeline": pipeline, "tab_id": schedule.id})


def _enqueue_schedule_refresh_build(
    session: Session,
    *,
    schedule: Schedule,
    target_kind: str,
    namespace: str,
    now: datetime,
) -> build_run_service.BuildRun:
    build_id = str(uuid.uuid4())
    analysis_name = f"Schedule refresh {schedule.datasource_id}"
    run = build_run_service.create_build_run(
        session,
        build_id=build_id,
        namespace=namespace,
        schedule_id=schedule.id,
        analysis_id=schedule.id,
        analysis_name=analysis_name,
        request_json=_build_refresh_request(schedule).model_dump(mode="json"),
        starter_json=compute_schemas.BuildStarter.for_schedule(schedule.id).model_dump(mode="json"),
        status=BuildRunStatus.QUEUED,
        current_kind=target_kind,
        current_datasource_id=schedule.datasource_id,
        current_tab_id=schedule.id,
        current_tab_name="Scheduled refresh",
        current_output_id=schedule.datasource_id,
        current_output_name=analysis_name,
        total_tabs=1,
        created_at=now,
        started_at=now,
    )
    build_job_service.create_job(session, build_id=build_id, namespace=namespace)
    return run


def _enqueue_schedule_analysis_build(
    session: Session,
    *,
    schedule: Schedule,
    namespace: str,
    analysis_id: str,
    analysis_name: str,
    tab_id: str | None,
    tab_name: str | None,
    request: compute_schemas.BuildRequest,
    now: datetime,
) -> build_run_service.BuildRun:
    build_id = str(uuid.uuid4())
    run = build_run_service.create_build_run(
        session,
        build_id=build_id,
        namespace=namespace,
        schedule_id=schedule.id,
        analysis_id=analysis_id,
        analysis_name=analysis_name,
        request_json=request.model_dump(mode="json"),
        starter_json=compute_schemas.BuildStarter.for_schedule(schedule.id).model_dump(mode="json"),
        status=BuildRunStatus.QUEUED,
        current_kind=EngineRunKind.BUILD.value,
        current_datasource_id=schedule.datasource_id,
        current_tab_id=tab_id,
        current_tab_name=tab_name,
        current_output_id=schedule.datasource_id,
        current_output_name=tab_name,
        total_tabs=len(request.analysis_pipeline.tabs),
        created_at=now,
        started_at=now,
    )
    build_job_service.create_job(session, build_id=build_id, namespace=namespace)
    return run


def is_schedule_target_eligible(datasource: DataSource) -> bool:
    """Schedules can target any existing datasource."""
    return datasource is not None


def _resolve_schedule_target(session: Session, datasource_id: str) -> tuple[DataSourceTargetKind, str | None, str | None]:
    """Resolve schedule execution path and optional analysis provenance."""
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    analysis_id = datasource.created_by_analysis_id
    if datasource.target_kind() == DataSourceTargetKind.ANALYSIS and analysis_id:
        tab_id = datasource.config.get("analysis_tab_id") if isinstance(datasource.config, dict) else None
        return DataSourceTargetKind.ANALYSIS, analysis_id, tab_id

    if datasource.target_kind() == DataSourceTargetKind.RAW:
        return DataSourceTargetKind.RAW, None, None

    return DataSourceTargetKind.DATASOURCE, None, None


def _build_schedule_response(
    schedule: Schedule,
    datasource: DataSource | None,
    analysis: Analysis | None,
) -> ScheduleResponse:
    """Build a schedule response from preloaded related models."""
    data = {
        "id": schedule.id,
        "datasource_id": schedule.datasource_id,
        "cron_expression": schedule.cron_expression,
        "enabled": schedule.enabled,
        "depends_on": schedule.depends_on,
        "trigger_on_datasource_id": schedule.trigger_on_datasource_id,
        "last_run": schedule.last_run,
        "next_run": schedule.next_run,
        "created_at": schedule.created_at,
    }

    if datasource:
        data["analysis_id"] = datasource.created_by_analysis_id

        tab_id = datasource.config.get("analysis_tab_id") if isinstance(datasource.config, dict) else None
        data["tab_id"] = tab_id

        if analysis:
            data["analysis_name"] = analysis.name

            if tab_id:
                for ptab in analysis.pipeline.tabs:
                    if ptab.id == tab_id:
                        data["tab_name"] = ptab.name or "unnamed"
                        break

    return ScheduleResponse.model_validate(data)


def _enrich_schedule_response(session: Session, schedule: Schedule) -> ScheduleResponse:
    """Enrich schedule with resolved analysis/tab info from datasource provenance."""
    datasource = session.get(DataSource, schedule.datasource_id)
    analysis = None
    if datasource and datasource.created_by_analysis_id:
        analysis = session.get(Analysis, datasource.created_by_analysis_id)
    return _build_schedule_response(schedule, datasource, analysis)


def _enrich_schedule_response_batch(
    schedules: Sequence[Schedule],
    ds_map: dict[str, DataSource],
    analysis_map: dict[str, Analysis],
) -> list[ScheduleResponse]:
    """Enrich schedules using preloaded datasource and analysis maps."""
    responses: list[ScheduleResponse] = []
    for schedule in schedules:
        datasource = ds_map.get(schedule.datasource_id)
        analysis = None
        if datasource and datasource.created_by_analysis_id:
            analysis = analysis_map.get(datasource.created_by_analysis_id)
        responses.append(_build_schedule_response(schedule, datasource, analysis))
    return responses


def list_schedules(
    session: Session,
    datasource_id: str | None = None,
) -> list[ScheduleResponse]:
    """List schedules with optional filtering by target datasource."""
    query = select(Schedule)
    if datasource_id:
        query = query.where(col(Schedule.datasource_id) == datasource_id)
    result = session.execute(query)
    schedules = result.scalars().all()
    datasource_ids = {schedule.datasource_id for schedule in schedules}

    ds_map: dict[str, DataSource] = {}
    if datasource_ids:
        datasources = session.execute(select(DataSource).where(col(DataSource.id).in_(list(datasource_ids)))).scalars().all()
        ds_map = {str(datasource.id): datasource for datasource in datasources}

    analysis_ids = {datasource.created_by_analysis_id for datasource in ds_map.values() if datasource.created_by_analysis_id}

    analysis_map: dict[str, Analysis] = {}
    if analysis_ids:
        analyses = session.execute(select(Analysis).where(col(Analysis.id).in_(list(analysis_ids)))).scalars().all()
        analysis_map = {str(analysis.id): analysis for analysis in analyses}

    return _enrich_schedule_response_batch(schedules, ds_map, analysis_map)


def create_schedule(session: Session, payload: ScheduleCreate) -> ScheduleResponse:
    """Create a new schedule targeting a specific datasource.

    analysis_id and tab_id are resolved from datasource provenance at execution time.
    """
    # Validate datasource exists
    datasource = session.get(DataSource, payload.datasource_id)
    if not datasource:
        raise DataSourceNotFoundError(payload.datasource_id)
    if datasource.is_analysis_output and not datasource.created_by_analysis_id:
        raise ScheduleValidationError(
            "Datasource has no analysis provenance",
            details={"datasource_id": payload.datasource_id},
        )

    # Validate dependency if provided
    if payload.depends_on:
        dep_schedule = session.get(Schedule, payload.depends_on)
        if not dep_schedule:
            raise ScheduleValidationError(
                "Dependency schedule not found",
                details={"depends_on": payload.depends_on},
            )

    # Validate trigger datasource if provided
    if payload.trigger_on_datasource_id:
        trigger_ds = session.get(DataSource, payload.trigger_on_datasource_id)
        if not trigger_ds:
            raise DataSourceNotFoundError(payload.trigger_on_datasource_id)

    next_run = Schedule.compute_next_run(payload.cron_expression)
    record = Schedule(
        id=str(uuid.uuid4()),
        datasource_id=payload.datasource_id,
        cron_expression=payload.cron_expression,
        enabled=payload.enabled,
        depends_on=payload.depends_on,
        trigger_on_datasource_id=payload.trigger_on_datasource_id,
        last_run=None,
        next_run=next_run,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return _enrich_schedule_response(session, record)


def update_schedule(session: Session, schedule_id: str, payload: ScheduleUpdate) -> ScheduleResponse:
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise ScheduleNotFoundError(schedule_id)

    # Validate new datasource if provided
    if payload.datasource_id:
        datasource = session.get(DataSource, payload.datasource_id)
        if not datasource:
            raise DataSourceNotFoundError(payload.datasource_id)

    # Validate dependency if provided
    if payload.depends_on:
        dep_schedule = session.get(Schedule, payload.depends_on)
        if not dep_schedule:
            raise ScheduleValidationError(
                "Dependency schedule not found",
                details={"depends_on": payload.depends_on},
            )

    # Validate trigger datasource if provided
    if payload.trigger_on_datasource_id:
        trigger_ds = session.get(DataSource, payload.trigger_on_datasource_id)
        if not trigger_ds:
            raise DataSourceNotFoundError(payload.trigger_on_datasource_id)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(schedule, key, value)

    if payload.cron_expression:
        schedule.next_run = Schedule.compute_next_run(payload.cron_expression)

    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return _enrich_schedule_response(session, schedule)


def delete_schedule(session: Session, schedule_id: str) -> None:
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise ScheduleNotFoundError(schedule_id)
    session.delete(schedule)
    session.commit()


def get_build_order(session: Session, analysis_id: str) -> list[str]:
    """Compute topological build order for analyses based on datasource dependencies.

    Returns list of analysis IDs in dependency order (upstream first).
    """
    from contracts.analysis.models import Analysis, AnalysisDataSource

    graph: dict[str, set[str]] = {}
    in_degree: dict[str, int] = {}

    analyses = session.execute(select(Analysis)).scalars().all()
    for analysis in analyses:
        if analysis.id not in graph:
            graph[analysis.id] = set()
            in_degree[analysis.id] = 0

    deps = (
        session.execute(
            select(AnalysisDataSource).where(AnalysisDataSource.analysis_id.in_(list(graph.keys()))),  # type: ignore[arg-type, attr-defined]
        )
        .scalars()
        .all()
    )
    dep_ds_ids = [dep.datasource_id for dep in deps]
    datasources_by_id: dict[str, DataSource] = {}
    if dep_ds_ids:
        ds_rows = session.execute(select(DataSource).where(col(DataSource.id).in_(dep_ds_ids))).scalars().all()
        datasources_by_id = {str(ds.id): ds for ds in ds_rows}
    for dep in deps:
        datasource = datasources_by_id.get(dep.datasource_id)
        if not datasource or not datasource.created_by_analysis_id:
            continue
        upstream = datasource.created_by_analysis_id
        if upstream not in graph or dep.analysis_id not in graph:
            continue
        edges = graph.setdefault(upstream, set())
        is_new = dep.analysis_id not in edges
        edges.add(dep.analysis_id)
        if is_new:
            in_degree[dep.analysis_id] = in_degree.get(dep.analysis_id, 0) + 1

    queue = deque(aid for aid, degree in in_degree.items() if degree == 0)
    ordered: list[str] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        for neighbor in graph.get(node, set()):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    return ordered


def should_run(cron_expr: str, last_run: datetime | None) -> bool:
    if not cron_expr:
        return False
    if last_run is None:
        return True
    naive_last = last_run.replace(tzinfo=None) if last_run.tzinfo else last_run
    cron = croniter.croniter(cron_expr, naive_last)
    next_run = cron.get_next(datetime)
    now = datetime.now(UTC).replace(tzinfo=None)
    return next_run <= now


def _is_triggered_by_datasource(
    session: Session,
    datasource_id: str,
    last_run: datetime | None,
) -> bool:
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        return False
    latest_runs = build_run_service.list_build_runs(
        session,
        datasource_id=datasource_id,
        status=BuildRunStatus.COMPLETED,
        limit=1,
    )
    latest = latest_runs[0] if latest_runs else None
    if not latest:
        return False
    if last_run is None:
        return True
    last_dt = last_run.replace(tzinfo=None) if last_run.tzinfo else last_run
    created = latest.created_at.replace(tzinfo=None) if latest.created_at.tzinfo else latest.created_at
    return created > last_dt


def _is_triggered_by_schedule(
    session: Session,
    dependency_id: str,
    last_triggered_at: datetime | None,
) -> bool:
    dependency = session.get(Schedule, dependency_id)
    if dependency is None or dependency.last_success_at is None:
        return False
    completed = dependency.last_success_at.replace(tzinfo=None) if dependency.last_success_at.tzinfo else dependency.last_success_at
    if last_triggered_at is None:
        return True
    previous = last_triggered_at.replace(tzinfo=None) if last_triggered_at.tzinfo else last_triggered_at
    return completed > previous


def get_due_schedules(session: Session) -> list[Schedule]:
    """Return all enabled schedules that are due to run."""
    now = _utcnow().replace(tzinfo=None)
    result = session.execute(
        select(Schedule).where(col(Schedule.enabled) == True),  # type: ignore[arg-type]  # noqa: E712
    )
    schedules = result.scalars().all()
    ds_ids = [sched.datasource_id for sched in schedules]
    valid_ds_ids: set[str] = set()
    if ds_ids:
        id_rows = session.execute(select(col(DataSource.id)).where(col(DataSource.id).in_(ds_ids))).all()
        valid_ds_ids = {str(row[0]) for row in id_rows}
    due: list[Schedule] = []
    for sched in schedules:
        if sched.datasource_id not in valid_ds_ids:
            continue
        reference = sched.last_triggered_at or sched.last_run
        if sched.depends_on and _is_triggered_by_schedule(session, sched.depends_on, sched.last_triggered_at):
            due.append(sched)
            continue
        if sched.trigger_on_datasource_id and _is_triggered_by_datasource(
            session,
            sched.trigger_on_datasource_id,
            reference,
        ):
            due.append(sched)
            continue
        if sched.depends_on or sched.trigger_on_datasource_id:
            continue
        next_run = sched.next_run.replace(tzinfo=None) if sched.next_run and sched.next_run.tzinfo else sched.next_run
        if next_run is not None and next_run <= now:
            due.append(sched)
            continue
        if next_run is None and should_run(sched.cron_expression, reference):
            due.append(sched)
    return due


def claim_due_schedules(
    session: Session,
    *,
    worker_id: str,
    reclaimable_owner_ids: set[str] | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> list[Schedule]:
    stamp = now or _utcnow()
    naive_stamp = _naive_utc(stamp)
    table = Schedule.metadata.tables[Schedule.__tablename__]
    reclaimable = set(reclaimable_owner_ids or ())
    base = (
        select(Schedule)
        .where(col(Schedule.enabled) == True)  # type: ignore[arg-type]  # noqa: E712
        .where(
            or_(
                table.c.lease_owner.is_(None),
                table.c.lease_owner.in_(reclaimable),
            )
        )
    )
    dialect = session.get_bind().dialect.name
    stmt = base.with_for_update(skip_locked=True) if dialect == "postgresql" else base
    schedules = list(session.execute(stmt).scalars().all())
    due_ids = {schedule.id for schedule in get_due_schedules(session)}
    due = [schedule for schedule in schedules if schedule.id in due_ids]
    claimed: list[Schedule] = []
    for schedule in due[:limit]:
        if build_run_service.has_inflight_build_for_schedule(session, schedule.id):
            continue
        claim = update(Schedule).where(Schedule.id == schedule.id)
        claim = (
            claim.where(table.c.lease_owner.is_(None)) if schedule.lease_owner is None else claim.where(Schedule.lease_owner == schedule.lease_owner)  # type: ignore[arg-type]
        )
        result = cast(
            CursorResult[Any],
            session.execute(
                claim.values(
                    lease_owner=worker_id,
                    lease_expires_at=None,
                    last_claimed_at=naive_stamp,
                )
            ),
        )
        if result.rowcount != 1:
            continue
        claimed.append(schedule)
    if not claimed:
        session.rollback()
        return []
    session.commit()
    claimed_ids = [schedule.id for schedule in claimed]
    refreshed = session.execute(select(Schedule).where(col(Schedule.id).in_(claimed_ids))).scalars().all()
    return list(refreshed)


def mark_schedule_run(session: Session, schedule_id: str) -> None:
    """Update last_run to now and recompute next_run after a successful build."""
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        return
    now = _utcnow().replace(tzinfo=None)
    schedule.last_run = now
    schedule.last_success_at = now
    schedule.next_run = Schedule.compute_next_run(schedule.cron_expression)
    schedule.lease_owner = None
    schedule.lease_expires_at = None
    session.add(schedule)
    session.commit()


def enqueue_schedule_run(session: Session, schedule_id: str, *, worker_id: str) -> str:
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise ValueError(f"Schedule {schedule_id} not found")
    if build_run_service.has_inflight_build_for_schedule(session, schedule_id):
        raise ValueError(f"Schedule {schedule_id} already has an in-flight build")

    stamp = _utcnow()
    naive_stamp = _naive_utc(stamp)
    if schedule.lease_owner != worker_id:
        raise ValueError(f"Schedule {schedule_id} is not owned by {worker_id}")

    target_kind, analysis_id, _ = _resolve_schedule_target(session, schedule.datasource_id)
    namespace = get_namespace()
    schedule.last_triggered_at = naive_stamp
    schedule.last_failure_at = None

    if target_kind == DataSourceTargetKind.RAW:
        run = _enqueue_schedule_refresh_build(
            session,
            schedule=schedule,
            target_kind=DataSourceTargetKind.RAW.value,
            namespace=namespace,
            now=stamp,
        )
        build_job_hub.publish()
        runtime_ipc.notify_build_job()
        return run.id

    if target_kind == DataSourceTargetKind.DATASOURCE:
        run = _enqueue_schedule_refresh_build(
            session,
            schedule=schedule,
            target_kind=EngineRunKind.BUILD.value,
            namespace=namespace,
            now=stamp,
        )
        build_job_hub.publish()
        runtime_ipc.notify_build_job()
        return run.id

    if analysis_id is None:
        raise ValueError(f"Analysis provenance missing for schedule {schedule_id}")
    request, resolved_analysis_id, analysis_name, tab_id, tab_name = _build_analysis_request(session, schedule, analysis_id)
    run = _enqueue_schedule_analysis_build(
        session,
        schedule=schedule,
        namespace=namespace,
        analysis_id=resolved_analysis_id,
        analysis_name=analysis_name,
        tab_id=tab_id,
        tab_name=tab_name,
        request=request,
        now=stamp,
    )
    build_job_hub.publish()
    runtime_ipc.notify_build_job()
    return run.id


def reconcile_schedule_run(session: Session, *, build_id: str) -> Schedule | None:
    run = build_run_service.get_build_run(session, build_id)
    if run is None or run.schedule_id is None or run.status not in _SCHEDULE_TERMINAL_STATUSES:
        return None
    schedule = session.get(Schedule, run.schedule_id)
    if schedule is None:
        return None

    completed = run.completed_at or run.updated_at
    stamp = completed.replace(tzinfo=None) if completed.tzinfo is not None else completed
    schedule.lease_owner = None
    schedule.lease_expires_at = None
    if run.status == BuildRunStatus.COMPLETED:
        schedule.last_run = stamp
        schedule.last_success_at = stamp
        schedule.last_successful_build_id = run.id
        schedule.next_run = Schedule.compute_next_run(schedule.cron_expression)
    else:
        schedule.last_failure_at = stamp
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return schedule
