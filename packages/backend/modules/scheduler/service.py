import logging
import uuid
from collections import deque
from collections.abc import Collection, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import croniter  # type: ignore[import-untyped]
from sqlalchemy import Select, case, func, literal, or_, select, tuple_
from sqlmodel import Session

from backend_core import (
    build_datasource_dependencies,
    build_jobs_service as build_job_service,
    build_runs_service as build_run_service,
    runtime_ipc,
    runtime_outbox_service,
    runtime_work_service,
)
from backend_core.claiming import claim_by_lease_owner, with_for_update_skip_locked
from backend_core.domain.build_jobs.live import hub as build_job_hub
from backend_core.domain.build_jobs.models import BuildJobStatus
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.datasource.models import DataSourceTargetKind
from backend_core.domain.engine_runs.schemas import EngineRunKind
from backend_core.domain.scheduler.schemas import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from backend_core.exceptions import (
    ScheduleValidationError,
    datasource_not_found,
    schedule_not_found,
)
from backend_core.lease_observability import record_lease_transition
from backend_core.namespace import get_namespace
from backend_core.persistence.analysis.models import Analysis, AnalysisDataSource
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.scheduler.models import Schedule
from backend_core.sqlmodel_typing import col
from backend_core.time import utc_now as _utcnow
from backend_core.transitions import TransitionOutcome
from modules.analysis.step_schemas import normalize_pipeline_step_configs_for_protocol

logger = logging.getLogger(__name__)

_SCHEDULE_TERMINAL_STATUSES = frozenset(status for status in BuildRunStatus.members() if status.is_terminal)
_SCHEDULE_LEASE_DURATION = timedelta(minutes=5)
_SCHEDULE_CANDIDATE_BATCH_SIZE = 100


def _build_request_json(request: compute_schemas.BuildRequest) -> dict[str, object]:
    pipeline = normalize_pipeline_step_configs_for_protocol(request.pipeline_payload())
    return {
        'analysis_pipeline': {
            'analysis_id': pipeline['analysis_id'],
            'tabs': pipeline['tabs'],
        },
        'tab_id': request.tab_id,
    }


def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _wake_build_worker(namespace: str) -> None:
    """Wake the worker after a schedule transaction commits.

    The outbox remains authoritative if PostgreSQL NOTIFY is unavailable; the
    direct message only removes the recovery-cursor delay for normal runs.
    """
    try:
        runtime_ipc.notify_build_job(namespace)
    except Exception:
        logger.warning('Direct scheduled-build wake failed namespace=%s; durable outbox will recover it', namespace, exc_info=True)


def _mark_schedule_failure(
    session: Session,
    *,
    schedule: Schedule,
    error: str,
    claim_token: str,
    lease_generation: int,
    now: datetime | None = None,
) -> Schedule:
    stamp = now or _utcnow()
    if schedule.claim_token != claim_token or schedule.lease_generation != lease_generation:
        raise ValueError(f'Schedule {schedule.id} claim was replaced')
    schedule.last_failure_at = stamp
    schedule.lease_owner = None
    schedule.claim_token = None
    schedule.lease_expires_at = None
    session.add(schedule)
    runtime_work_service.mark_schedule_pending(session, namespace=get_namespace())
    session.commit()
    session.refresh(schedule)
    return schedule


def mark_schedule_enqueue_failed(
    session: Session,
    schedule_id: str,
    *,
    error: str,
    claim_token: str,
    lease_generation: int,
) -> Schedule | None:
    schedule = session.execute(select(Schedule).where(col(Schedule.id) == schedule_id).with_for_update()).scalar_one_or_none()
    if schedule is None:
        return None
    return _mark_schedule_failure(
        session,
        schedule=schedule,
        error=error,
        claim_token=claim_token,
        lease_generation=lease_generation,
    )


def build_analysis_pipeline_payload(session: Session, analysis: Analysis, datasource_id: str | None = None) -> dict[str, Any]:
    pipeline = analysis.pipeline_definition
    tabs = pipeline.get('tabs', []) if isinstance(pipeline, dict) else []
    if not isinstance(tabs, list) or not tabs:
        return {'analysis_id': str(analysis.id), 'tabs': []}

    output_map: dict[str, str] = {}
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        tab_id = tab.get('id')
        output = tab.get('output')
        if not isinstance(output, dict):
            raise ValueError('Analysis pipeline tab missing output configuration')
        output_id = output.get('result_id')
        if not output_id:
            raise ValueError('Analysis pipeline tab missing output.result_id')
        if tab_id:
            output_map[str(tab_id)] = str(output_id)

    output_to_tab = {output_id: tab_id for tab_id, output_id in output_map.items()}

    def enrich_step(step: dict[str, object]) -> dict[str, Any]:
        config = step.get('config')
        if not isinstance(config, dict):
            return step
        next_config = dict(config)
        right_source = next_config.get('right_source') or next_config.get('rightDataSource')
        if isinstance(right_source, str) and right_source and right_source not in output_to_tab:
            datasource_model = session.get(DataSource, right_source)
            if datasource_model is not None:
                next_config['right_source_datasource'] = {
                    'id': right_source,
                    'analysis_tab_id': None,
                    'source_type': datasource_model.source_type,
                    'config': dict(datasource_model.config),
                }
        raw_sources = next_config.get('sources')
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
                    'id': source,
                    'analysis_tab_id': None,
                    'source_type': datasource_model.source_type,
                    'config': dict(datasource_model.config),
                }
            )
        if refs:
            next_config['source_datasources'] = refs
        return {**step, 'config': next_config}

    next_tabs: list[dict[str, Any]] = []
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        datasource = tab.get('datasource')
        if not isinstance(datasource, dict):
            raise ValueError('Analysis pipeline tab datasource must be a dict')
        output = tab.get('output')
        if not isinstance(output, dict):
            raise ValueError('Analysis pipeline tab missing output configuration')
        output_id = output.get('result_id')
        if not output_id:
            raise ValueError('Analysis pipeline tab missing output.result_id')
        config = datasource.get('config')
        if not isinstance(config, dict):
            raise ValueError('Analysis pipeline tab datasource.config must be a dict')
        branch = config.get('branch')
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError('Analysis pipeline tab datasource.config.branch is required')
        tab_datasource_id = datasource.get('id')
        if not tab_datasource_id:
            raise ValueError('Analysis pipeline tab missing datasource.id')
        analysis_tab_id = datasource.get('analysis_tab_id') if isinstance(datasource.get('analysis_tab_id'), str) else None
        source_type = 'analysis' if analysis_tab_id or str(tab_datasource_id) in output_to_tab else None
        merged_config = dict(config)
        if source_type is None:
            datasource_model = session.get(DataSource, str(tab_datasource_id))
            if datasource_model is not None:
                source_type = datasource_model.source_type
                merged_config = {'branch': branch, **datasource_model.config, **config}
        if datasource_id and str(datasource_id) != str(output_id) and str(datasource_id) != str(tab_datasource_id):
            next_tabs.append(
                {
                    **tab,
                    'datasource': {
                        **datasource,
                        'id': tab_datasource_id,
                        'analysis_tab_id': analysis_tab_id,
                        'source_type': source_type,
                        'config': merged_config,
                    },
                    'steps': [enrich_step(step) for step in tab.get('steps', []) if isinstance(step, dict)],
                }
            )
            continue
        next_tabs.append(
            {
                **tab,
                'datasource': {
                    **datasource,
                    'id': tab_datasource_id,
                    'analysis_tab_id': analysis_tab_id,
                    'source_type': source_type,
                    'config': merged_config,
                },
                'steps': [enrich_step(step) for step in tab.get('steps', []) if isinstance(step, dict)],
            }
        )

    return {'analysis_id': str(analysis.id), 'tabs': next_tabs}


def _build_analysis_request(session: Session, schedule: Schedule, analysis_id: str) -> tuple[compute_schemas.BuildRequest, str, str, str | None, str | None]:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found for datasource {schedule.datasource_id}')

    pipeline = analysis.pipeline
    target_tab = next(
        (tab for tab in pipeline.tabs if tab.output.result_id == schedule.datasource_id),
        None,
    )
    if target_tab is None:
        raise ValueError(f'No tab found in analysis {analysis_id} that produces datasource {schedule.datasource_id}')

    pipeline_payload = build_analysis_pipeline_payload(session, analysis, datasource_id=schedule.datasource_id)
    request = compute_schemas.BuildRequest.model_validate(
        {
            'analysis_pipeline': pipeline_payload,
            'tab_id': target_tab.id,
        }
    )
    return request, str(analysis.id), analysis.name, target_tab.id, target_tab.name


def _build_ingest_request(schedule: Schedule) -> compute_schemas.BuildRequest:
    pipeline = {
        'analysis_id': schedule.id,
        'tabs': [
            {
                'id': schedule.id,
                'name': 'Scheduled ingest',
                'datasource': {
                    'id': schedule.datasource_id,
                    'analysis_tab_id': None,
                    'source_type': 'schedule',
                    'config': {'branch': 'master'},
                },
                'output': {
                    'result_id': schedule.datasource_id,
                    'datasource_type': 'iceberg',
                    'format': 'parquet',
                    'filename': f'schedule_ingest_{schedule.id}',
                },
                'steps': [],
            }
        ],
    }
    return compute_schemas.BuildRequest.model_validate({'analysis_pipeline': pipeline, 'tab_id': schedule.id})


def _enqueue_schedule_ingest_build(
    session: Session,
    *,
    schedule: Schedule,
    target_kind: str,
    namespace: str,
    now: datetime,
) -> build_run_service.BuildRun:
    build_id = str(uuid.uuid4())
    datasource = session.get(DataSource, schedule.datasource_id)
    datasource_name = datasource.name if datasource is not None and datasource.name else schedule.datasource_id
    analysis_name = f'Schedule ingest {datasource_name}'
    request = _build_ingest_request(schedule)
    datasource_ids = build_datasource_dependencies.external_datasource_ids(request.analysis_pipeline)
    build_datasource_dependencies.lock_active_datasources(session, namespace=namespace, datasource_ids=datasource_ids)
    run = build_run_service.stage_build_run(
        session,
        build_id=build_id,
        namespace=namespace,
        schedule_id=schedule.id,
        analysis_id=schedule.id,
        analysis_name=analysis_name,
        request_json=_build_request_json(request),
        starter_json=compute_schemas.BuildStarter.for_schedule(schedule.id).model_dump(mode='json'),
        status=BuildRunStatus.QUEUED,
        current_kind=target_kind,
        current_datasource_id=schedule.datasource_id,
        current_tab_id=schedule.id,
        current_tab_name='Scheduled ingest',
        current_output_id=schedule.datasource_id,
        current_output_name=analysis_name,
        total_tabs=1,
        datasource_ids=datasource_ids,
        created_at=now,
        started_at=now,
    )
    build_job_service.stage_job(session, build_id=build_id, namespace=namespace)
    runtime_outbox_service.enqueue_build_job_notification(session)
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
    datasource_ids = build_datasource_dependencies.external_datasource_ids(request.analysis_pipeline)
    build_datasource_dependencies.lock_active_datasources(session, namespace=namespace, datasource_ids=datasource_ids)
    run = build_run_service.stage_build_run(
        session,
        build_id=build_id,
        namespace=namespace,
        schedule_id=schedule.id,
        analysis_id=analysis_id,
        analysis_name=analysis_name,
        request_json=_build_request_json(request),
        starter_json=compute_schemas.BuildStarter.for_schedule(schedule.id).model_dump(mode='json'),
        status=BuildRunStatus.QUEUED,
        current_kind=EngineRunKind.BUILD.value,
        current_datasource_id=schedule.datasource_id,
        current_tab_id=tab_id,
        current_tab_name=tab_name,
        current_output_id=schedule.datasource_id,
        current_output_name=tab_name,
        total_tabs=len(request.analysis_pipeline.tabs),
        datasource_ids=datasource_ids,
        created_at=now,
        started_at=now,
    )
    build_job_service.stage_job(session, build_id=build_id, namespace=namespace)
    runtime_outbox_service.enqueue_build_job_notification(session)
    return run


def is_schedule_target_eligible(datasource: DataSource) -> bool:
    """Schedules can target any existing datasource."""
    return datasource is not None


def _resolve_schedule_target(session: Session, datasource_id: str) -> tuple[DataSourceTargetKind, str | None, str | None]:
    """Resolve schedule execution path and optional analysis provenance."""
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        raise datasource_not_found(datasource_id)

    analysis_id = datasource.created_by_analysis_id
    if datasource.target_kind() == DataSourceTargetKind.ANALYSIS and analysis_id:
        tab_id = datasource.config.get('analysis_tab_id') if isinstance(datasource.config, dict) else None
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
        'id': schedule.id,
        'datasource_id': schedule.datasource_id,
        'description': schedule.description,
        'cron_expression': schedule.cron_expression,
        'enabled': schedule.enabled,
        'depends_on': schedule.depends_on,
        'trigger_on_datasource_id': schedule.trigger_on_datasource_id,
        'last_run': schedule.last_run,
        'next_run': schedule.next_run,
        'created_at': schedule.created_at,
    }

    if datasource:
        data['analysis_id'] = datasource.created_by_analysis_id

        tab_id = datasource.config.get('analysis_tab_id') if isinstance(datasource.config, dict) else None
        data['tab_id'] = tab_id

        if analysis:
            data['analysis_name'] = analysis.name

            if tab_id:
                for ptab in analysis.pipeline.tabs:
                    if ptab.id == tab_id:
                        data['tab_name'] = ptab.name or 'unnamed'
                        break

    return ScheduleResponse.model_validate(data)


def enrich_schedule_response(session: Session, schedule: Schedule) -> ScheduleResponse:
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
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ScheduleResponse]:
    """List schedules with optional filtering by target datasource and text search."""
    query = (
        select(Schedule)
        .join(DataSource, col(Schedule.datasource_id) == col(DataSource.id), isouter=True)
        .join(Analysis, col(DataSource.created_by_analysis_id) == col(Analysis.id), isouter=True)
    )
    if datasource_id:
        query = query.where(col(Schedule.datasource_id) == datasource_id)
    if search:
        q = f'%{search}%'
        query = query.where(
            or_(
                col(Schedule.id).ilike(q),
                col(Schedule.datasource_id).ilike(q),
                col(Schedule.cron_expression).ilike(q),
                col(DataSource.name).ilike(q),
                col(Analysis.name).ilike(q),
            )
        )
    query = query.order_by(col(Schedule.created_at).desc(), col(Schedule.id).asc()).limit(limit).offset(offset)
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


def stage_create_schedule(session: Session, payload: ScheduleCreate) -> Schedule:
    """Create a new schedule targeting a specific datasource.

    analysis_id and tab_id are resolved from datasource provenance at execution time.
    """
    # Validate datasource exists
    datasource = session.get(DataSource, payload.datasource_id)
    if not datasource:
        raise datasource_not_found(payload.datasource_id)
    if datasource.is_analysis_output and not datasource.created_by_analysis_id:
        raise ScheduleValidationError(
            'Datasource has no analysis provenance',
            details={'datasource_id': payload.datasource_id},
        )

    # Validate dependency if provided
    if payload.depends_on:
        dep_schedule = session.get(Schedule, payload.depends_on)
        if not dep_schedule:
            raise ScheduleValidationError(
                'Dependency schedule not found',
                details={'depends_on': payload.depends_on},
            )

    # Validate trigger datasource if provided
    if payload.trigger_on_datasource_id:
        trigger_ds = session.get(DataSource, payload.trigger_on_datasource_id)
        if not trigger_ds:
            raise datasource_not_found(payload.trigger_on_datasource_id)

    next_run = Schedule.compute_next_run(payload.cron_expression)
    record = Schedule(
        id=str(uuid.uuid4()),
        datasource_id=payload.datasource_id,
        description=payload.description,
        cron_expression=payload.cron_expression,
        enabled=payload.enabled,
        depends_on=payload.depends_on,
        trigger_on_datasource_id=payload.trigger_on_datasource_id,
        last_run=None,
        next_run=next_run,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    session.flush()
    runtime_work_service.mark_schedule_pending(session, namespace=get_namespace())
    return record


def stage_update_schedule(session: Session, schedule_id: str, payload: ScheduleUpdate) -> Schedule:
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise schedule_not_found(schedule_id)

    # Validate new datasource if provided
    if payload.datasource_id:
        datasource = session.get(DataSource, payload.datasource_id)
        if not datasource:
            raise datasource_not_found(payload.datasource_id)

    # Validate dependency if provided
    if payload.depends_on:
        dep_schedule = session.get(Schedule, payload.depends_on)
        if not dep_schedule:
            raise ScheduleValidationError(
                'Dependency schedule not found',
                details={'depends_on': payload.depends_on},
            )

    # Validate trigger datasource if provided
    if payload.trigger_on_datasource_id:
        trigger_ds = session.get(DataSource, payload.trigger_on_datasource_id)
        if not trigger_ds:
            raise datasource_not_found(payload.trigger_on_datasource_id)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(schedule, key, value)

    if payload.cron_expression:
        schedule.next_run = Schedule.compute_next_run(payload.cron_expression)

    session.add(schedule)
    session.flush()
    runtime_work_service.mark_schedule_pending(session, namespace=get_namespace())
    return schedule


def stage_delete_schedule(session: Session, schedule_id: str) -> None:
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise schedule_not_found(schedule_id)
    session.delete(schedule)
    session.flush()
    runtime_work_service.mark_schedule_pending(session, namespace=get_namespace())


def get_build_order(session: Session, analysis_id: str) -> list[str]:
    """Compute topological build order for analyses based on datasource dependencies.

    Returns list of analysis IDs in dependency order (upstream first).
    """
    graph: dict[str, set[str]] = {}
    in_degree: dict[str, int] = {}

    analyses = session.execute(select(Analysis)).scalars().all()
    for analysis in analyses:
        if analysis.id not in graph:
            graph[analysis.id] = set()
            in_degree[analysis.id] = 0

    deps = (
        session.execute(
            select(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id).in_(list(graph.keys()))),
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

    queue = deque(sorted(aid for aid, degree in in_degree.items() if degree == 0))
    ordered: list[str] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        for neighbor in sorted(graph.get(node, set())):
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


def _schedule_candidate_query(now: datetime) -> Select[tuple[Schedule]]:
    due_candidates = or_(
        col(Schedule.depends_on).is_not(None),
        col(Schedule.trigger_on_datasource_id).is_not(None),
        col(Schedule.next_run).is_(None),
        col(Schedule.next_run) <= now,
    )
    return select(Schedule).where(col(Schedule.enabled).is_(True)).where(due_candidates)


def _schedule_candidate_batches(session: Session, statement: Select[tuple[Schedule]]) -> Iterator[list[Schedule]]:
    # NULL next_run sorts first, followed by a stable total order. Advance over
    # every examined candidate, including dependency/event rows that are not due.
    due_key = func.coalesce(col(Schedule.next_run), datetime.min)
    key = tuple_(due_key, col(Schedule.created_at), col(Schedule.id))
    cursor: tuple[datetime, datetime, str] | None = None
    while True:
        batch_query = statement.order_by(due_key, col(Schedule.created_at), col(Schedule.id)).limit(_SCHEDULE_CANDIDATE_BATCH_SIZE)
        if cursor is not None:
            batch_query = batch_query.where(key > tuple_(literal(cursor[0]), literal(cursor[1]), literal(cursor[2])))
        schedules = list(session.execute(batch_query).scalars().all())
        if not schedules:
            return
        last = schedules[-1]
        cursor = (_naive_utc(last.next_run) if last.next_run is not None else datetime.min, _naive_utc(last.created_at), last.id)
        yield schedules
        if len(schedules) < _SCHEDULE_CANDIDATE_BATCH_SIZE:
            return


def get_due_schedules(session: Session) -> list[Schedule]:
    """Evaluate eligibility using bounded, ordered database candidate batches."""
    now = _naive_utc(_utcnow())
    return [
        schedule for batch in _schedule_candidate_batches(session, _schedule_candidate_query(now)) for schedule in _due_schedule_candidates(session, batch, now)
    ]


def _due_schedule_candidates(session: Session, schedules: Sequence[Schedule], now: datetime) -> list[Schedule]:
    ds_ids = {
        datasource_id for schedule in schedules for datasource_id in (schedule.datasource_id, schedule.trigger_on_datasource_id) if datasource_id is not None
    }
    valid_ds_ids: set[str] = set()
    if ds_ids:
        id_rows = session.execute(select(col(DataSource.id)).where(col(DataSource.id).in_(ds_ids))).all()
        valid_ds_ids = {str(row[0]) for row in id_rows}

    dependency_ids = {schedule.depends_on for schedule in schedules if schedule.depends_on is not None}
    dependency_success: dict[str, datetime] = {}
    if dependency_ids:
        dependency_rows = session.execute(select(col(Schedule.id), col(Schedule.last_success_at)).where(col(Schedule.id).in_(dependency_ids))).all()
        dependency_success = {str(schedule_id): last_success for schedule_id, last_success in dependency_rows if last_success is not None}

    trigger_ids = {
        schedule.trigger_on_datasource_id
        for schedule in schedules
        if schedule.trigger_on_datasource_id is not None and schedule.trigger_on_datasource_id in valid_ds_ids
    }
    latest_completed_at: dict[str, datetime] = {}
    if trigger_ids:
        for datasource_column in (BuildRun.current_datasource_id, BuildRun.current_output_id):
            completed_rows = session.execute(
                select(col(datasource_column), func.max(col(BuildRun.completed_at)))
                .where(col(datasource_column).in_(trigger_ids))
                .where(col(BuildRun.status) == BuildRunStatus.COMPLETED)
                .where(col(BuildRun.completed_at).is_not(None))
                .group_by(col(datasource_column))
            ).all()
            for datasource_id, completed_at in completed_rows:
                if datasource_id is None or completed_at is None:
                    continue
                key = str(datasource_id)
                previous = latest_completed_at.get(key)
                if previous is None or _naive_utc(completed_at) > _naive_utc(previous):
                    latest_completed_at[key] = completed_at

    due: list[Schedule] = []
    for sched in schedules:
        if sched.datasource_id not in valid_ds_ids:
            continue
        if sched.depends_on:
            completed = dependency_success.get(sched.depends_on)
            if completed is not None and (sched.last_triggered_at is None or _naive_utc(completed) > _naive_utc(sched.last_triggered_at)):
                due.append(sched)
                continue
        if sched.trigger_on_datasource_id:
            completed = latest_completed_at.get(sched.trigger_on_datasource_id)
            reference = sched.last_triggered_at or sched.last_run
            if completed is not None and (reference is None or _naive_utc(completed) > _naive_utc(reference)):
                due.append(sched)
                continue
        if sched.depends_on or sched.trigger_on_datasource_id:
            continue
        reference = sched.last_triggered_at or sched.last_run
        next_run = sched.next_run.replace(tzinfo=None) if sched.next_run and sched.next_run.tzinfo else sched.next_run
        if next_run is not None and next_run <= now:
            due.append(sched)
            continue
        if next_run is None and should_run(sched.cron_expression, reference):
            due.append(sched)
    return due


def _next_schedule_namespace_due_at(session: Session) -> datetime | None:
    now = _utcnow()
    active_build = (
        select(col(BuildRun.id))
        .where(col(BuildRun.schedule_id) == col(Schedule.id))
        .where(col(BuildRun.status).in_((BuildRunStatus.QUEUED, BuildRunStatus.RUNNING)))
        .exists()
    )
    eligible_cron = col(Schedule.enabled).is_(True) & col(Schedule.depends_on).is_(None) & col(Schedule.trigger_on_datasource_id).is_(None) & ~active_build
    next_cron = session.execute(
        select(func.min(col(Schedule.next_run)))
        .where(eligible_cron)
        .where(col(Schedule.next_run).is_not(None))
        .where(or_(col(Schedule.lease_owner).is_(None), col(Schedule.lease_expires_at) <= now))
    ).scalar_one_or_none()

    lease_due = session.execute(
        select(
            func.min(
                case(
                    (col(Schedule.lease_expires_at) > now, col(Schedule.lease_expires_at)),
                    else_=now,
                )
            )
        )
        .where(col(Schedule.enabled).is_(True))
        .where(col(Schedule.lease_owner).is_not(None))
        .where(col(Schedule.lease_expires_at).is_not(None))
        .where(~active_build)
    ).scalar_one_or_none()

    candidates = [value for value in (next_cron, lease_due) if value is not None]
    missing_next_runs = session.execute(
        select(Schedule)
        .where(eligible_cron)
        .where(col(Schedule.next_run).is_(None))
        .where(or_(col(Schedule.lease_owner).is_(None), col(Schedule.lease_expires_at) <= now))
    ).scalars()
    for schedule in missing_next_runs:
        if schedule.last_run is None:
            candidates.append(now)
            continue
        next_run = Schedule.compute_next_run(schedule.cron_expression, now=schedule.last_run)
        if next_run is None:
            continue
        schedule.next_run = next_run
        session.add(schedule)
        candidates.append(max(now, next_run, key=_naive_utc))

    if not candidates:
        return None
    due_at = min(candidates, key=_naive_utc)
    return due_at.replace(tzinfo=UTC) if due_at.tzinfo is None else due_at.astimezone(UTC)


def finish_schedule_work_scan(session: Session, *, namespace: str, generation: int, wake_ids: Collection[int] = ()) -> None:
    """Ack the scanned event generation and publish the next cron/lease wake."""
    runtime_work_service.finish_schedule_scan(
        session,
        namespace=namespace,
        generation=generation,
        due_at=_next_schedule_namespace_due_at(session),
        wake_ids=wake_ids,
    )
    session.commit()


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
    if limit < 1:
        return []
    active_build = (
        select(col(BuildRun.id))
        .where(col(BuildRun.schedule_id) == col(Schedule.id))
        .where(col(BuildRun.status).in_((BuildRunStatus.QUEUED, BuildRunStatus.RUNNING)))
        .exists()
    )
    base = (
        _schedule_candidate_query(naive_stamp)
        .where(~active_build)
        .where(
            or_(
                table.c.lease_owner.is_(None),
                table.c.lease_owner.in_(reclaimable),
                table.c.lease_expires_at <= naive_stamp,
            )
        )
    )
    claimed: list[Schedule] = []
    for candidates in _schedule_candidate_batches(session, base):
        due_ids = [schedule.id for schedule in _due_schedule_candidates(session, candidates, naive_stamp)]
        if not due_ids:
            continue
        locked_query = (
            base.where(col(Schedule.id).in_(due_ids))
            .order_by(table.c.next_run.asc().nullsfirst(), table.c.created_at.asc(), table.c.id.asc())
            .limit(_SCHEDULE_CANDIDATE_BATCH_SIZE)
            .execution_options(populate_existing=True)
        )
        schedules = session.execute(with_for_update_skip_locked(session, locked_query)).scalars().all()
        for schedule in _due_schedule_candidates(session, schedules, naive_stamp):
            if build_run_service.has_inflight_build_for_schedule(session, schedule.id):
                continue
            claim_token = str(uuid.uuid4())
            claimed_schedule = claim_by_lease_owner(
                session,
                Schedule,
                table=table,
                row_id=schedule.id,
                previous_owner=schedule.lease_owner,
                values={
                    'lease_owner': worker_id,
                    'claim_token': claim_token,
                    'lease_generation': table.c.lease_generation + 1,
                    'lease_expires_at': naive_stamp + _SCHEDULE_LEASE_DURATION,
                    'last_claimed_at': naive_stamp,
                    'attempts': table.c.attempts + 1,
                },
            )
            if not claimed_schedule:
                continue
            record_lease_transition(
                kind='schedule',
                transition='reclaim' if schedule.lease_owner is not None else 'claim',
                outcome=TransitionOutcome.APPLIED,
                entity_id=schedule.id,
                owner_id=worker_id,
                claim_token=claim_token,
                generation=schedule.lease_generation + 1,
                attempt=schedule.attempts + 1,
            )
            claimed.append(schedule)
            if len(claimed) >= limit:
                break
        if len(claimed) >= limit:
            break
    if not claimed:
        session.rollback()
        return []
    session.commit()
    claimed_ids = [schedule.id for schedule in claimed]
    refreshed = session.execute(select(Schedule).where(col(Schedule.id).in_(claimed_ids))).scalars().all()
    rows_by_id = {row.id: row for row in refreshed}
    return [rows_by_id[schedule_id] for schedule_id in claimed_ids]


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
    schedule.claim_token = None
    schedule.lease_expires_at = None
    session.add(schedule)
    runtime_work_service.mark_schedule_pending(session, namespace=get_namespace())
    session.commit()


def enqueue_schedule_run(
    session: Session,
    schedule_id: str,
    *,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
) -> str:
    schedule = session.execute(select(Schedule).where(col(Schedule.id) == schedule_id).with_for_update()).scalar_one_or_none()
    if not schedule:
        raise ValueError(f'Schedule {schedule_id} not found')
    if build_run_service.has_inflight_build_for_schedule(session, schedule_id):
        raise ValueError(f'Schedule {schedule_id} already has an in-flight build')

    stamp = _utcnow()
    naive_stamp = _naive_utc(stamp)
    if (
        schedule.lease_owner != worker_id
        or schedule.claim_token != claim_token
        or schedule.lease_generation != lease_generation
        or schedule.lease_expires_at is None
        or _naive_utc(schedule.lease_expires_at) <= naive_stamp
    ):
        raise ValueError(f'Schedule {schedule_id} claim is stale')

    target_kind, analysis_id, _ = _resolve_schedule_target(session, schedule.datasource_id)
    namespace = get_namespace()
    schedule.last_triggered_at = naive_stamp
    schedule.last_failure_at = None

    if target_kind == DataSourceTargetKind.RAW:
        run = _enqueue_schedule_ingest_build(
            session,
            schedule=schedule,
            target_kind=EngineRunKind.BUILD.value,
            namespace=namespace,
            now=stamp,
        )
        session.add(schedule)
        session.commit()
        _wake_build_worker(namespace)
        build_job_hub.publish()
        return run.id

    if target_kind == DataSourceTargetKind.DATASOURCE:
        run = _enqueue_schedule_ingest_build(
            session,
            schedule=schedule,
            target_kind=EngineRunKind.BUILD.value,
            namespace=namespace,
            now=stamp,
        )
        session.add(schedule)
        session.commit()
        _wake_build_worker(namespace)
        build_job_hub.publish()
        return run.id

    if analysis_id is None:
        raise ValueError(f'Analysis provenance missing for schedule {schedule_id}')
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
    session.add(schedule)
    session.commit()
    _wake_build_worker(namespace)
    build_job_hub.publish()
    return run.id


def apply_schedule_run_reconciliation(session: Session, *, build_id: str) -> Schedule | None:
    run = build_run_service.get_build_run(session, build_id)
    if run is None or run.status not in _SCHEDULE_TERMINAL_STATUSES:
        return None
    if run.schedule_id is None:
        return None
    schedule = session.execute(
        select(Schedule).where(col(Schedule.id) == run.schedule_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if schedule is None:
        return None

    completed = run.completed_at or run.updated_at
    stamp = completed.replace(tzinfo=None) if completed.tzinfo is not None else completed
    if schedule.last_triggered_at is not None and run.created_at < schedule.last_triggered_at:
        return None
    already_applied = (
        schedule.last_successful_build_id == run.id
        if run.status == BuildRunStatus.COMPLETED
        else schedule.last_failure_at is not None and _naive_utc(schedule.last_failure_at) >= stamp
    )
    if schedule.lease_owner is None and already_applied:
        return None

    schedule.lease_owner = None
    schedule.claim_token = None
    schedule.lease_expires_at = None
    if run.status == BuildRunStatus.COMPLETED:
        schedule.last_run = stamp
        schedule.last_success_at = stamp
        schedule.last_successful_build_id = run.id
        schedule.next_run = Schedule.compute_next_run(schedule.cron_expression)
    else:
        schedule.last_failure_at = stamp
    session.add(schedule)
    session.flush()
    return schedule


def reconcile_pending_schedule_runs(session: Session, *, namespace: str, limit: int = _SCHEDULE_CANDIDATE_BATCH_SIZE) -> int:
    """Apply terminal scheduled builds whose schedule lease is still outstanding."""
    candidates = (
        session.execute(
            select(col(BuildRun.id))
            .join(Schedule, col(Schedule.id) == col(BuildRun.schedule_id))
            .join(BuildJob, col(BuildJob.build_id) == col(BuildRun.id))
            .where(col(BuildRun.namespace) == namespace)
            .where(col(BuildRun.status).in_(_SCHEDULE_TERMINAL_STATUSES))
            .where(col(BuildJob.status).in_([status for status in BuildJobStatus.members() if status.is_terminal]))
            .where(col(Schedule.lease_owner).is_not(None))
            .where(col(Schedule.last_triggered_at).is_(None) | (col(BuildRun.created_at) >= col(Schedule.last_triggered_at)))
            .order_by(col(BuildRun.completed_at), col(BuildRun.id))
            .limit(limit)
        )
        .scalars()
        .all()
    )
    reconciled = 0
    for build_id in candidates:
        if apply_schedule_run_reconciliation(session, build_id=build_id) is not None:
            reconciled += 1
    if candidates:
        session.commit()
    return reconciled


def reconcile_schedule_run(session: Session, *, build_id: str) -> Schedule | None:
    schedule = apply_schedule_run_reconciliation(session, build_id=build_id)
    if schedule is None:
        return None
    session.commit()
    session.refresh(schedule)
    return schedule
