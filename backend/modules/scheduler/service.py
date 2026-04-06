import logging
import uuid
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime

import croniter  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlmodel import Session, col

from core.exceptions import AnalysisNotFoundError, DataSourceNotFoundError, ScheduleNotFoundError, ScheduleValidationError
from modules.analysis.models import Analysis
from modules.analysis.pipeline_types import PipelineTab
from modules.compute.manager import ProcessManager
from modules.datasource.models import DataSource
from modules.datasource.service import is_reingestable_raw_datasource
from modules.engine_runs.models import EngineRun
from modules.scheduler.models import Schedule
from modules.scheduler.schemas import ScheduleCreate, ScheduleResponse, ScheduleUpdate

logger = logging.getLogger(__name__)


def is_schedule_target_eligible(datasource: DataSource) -> bool:
    """Schedules can target any existing datasource."""
    return datasource is not None


def _resolve_schedule_target(session: Session, datasource_id: str) -> tuple[str, str | None, str | None]:
    """Resolve schedule execution path and optional analysis provenance.

    Returns: (target_kind, analysis_id, tab_id)
    target_kind: analysis | raw | datasource
    """
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    analysis_id = datasource.created_by_analysis_id
    if datasource.created_by == 'analysis' and analysis_id:
        tab_id = datasource.config.get('analysis_tab_id') if isinstance(datasource.config, dict) else None
        return 'analysis', analysis_id, tab_id

    if is_reingestable_raw_datasource(datasource):
        return 'raw', None, None

    return 'datasource', None, None


def _build_schedule_response(
    schedule: Schedule,
    datasource: DataSource | None,
    analysis: Analysis | None,
) -> ScheduleResponse:
    """Build a schedule response from preloaded related models."""
    data = {
        'id': schedule.id,
        'datasource_id': schedule.datasource_id,
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
    if datasource.created_by == 'analysis' and not datasource.created_by_analysis_id:
        raise ScheduleValidationError('Datasource has no analysis provenance', details={'datasource_id': payload.datasource_id})

    # Validate dependency if provided
    if payload.depends_on:
        dep_schedule = session.get(Schedule, payload.depends_on)
        if not dep_schedule:
            raise ScheduleValidationError('Dependency schedule not found', details={'depends_on': payload.depends_on})

    # Validate trigger datasource if provided
    if payload.trigger_on_datasource_id:
        trigger_ds = session.get(DataSource, payload.trigger_on_datasource_id)
        if not trigger_ds:
            raise DataSourceNotFoundError(payload.trigger_on_datasource_id)

    next_run = _compute_next_run(payload.cron_expression)
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
        # Backward compatibility: store analysis_id for existing code
        analysis_id=datasource.created_by_analysis_id,
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
        # Update backward-compat analysis_id
        schedule.analysis_id = datasource.created_by_analysis_id

    # Validate dependency if provided
    if payload.depends_on:
        dep_schedule = session.get(Schedule, payload.depends_on)
        if not dep_schedule:
            raise ScheduleValidationError('Dependency schedule not found', details={'depends_on': payload.depends_on})

    # Validate trigger datasource if provided
    if payload.trigger_on_datasource_id:
        trigger_ds = session.get(DataSource, payload.trigger_on_datasource_id)
        if not trigger_ds:
            raise DataSourceNotFoundError(payload.trigger_on_datasource_id)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key != 'analysis_id':  # Don't allow direct analysis_id updates
            setattr(schedule, key, value)

    if payload.cron_expression:
        schedule.next_run = _compute_next_run(payload.cron_expression)

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
    from modules.analysis.models import Analysis, AnalysisDataSource

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
    result = session.execute(
        select(EngineRun)
        .where(EngineRun.datasource_id == datasource_id)  # type: ignore[arg-type]
        .where(EngineRun.status == 'success')  # type: ignore[arg-type]
        .where(EngineRun.kind.in_(['datasource_update', 'datasource_create']))  # type: ignore[arg-type, attr-defined]
        .order_by(EngineRun.created_at.desc())  # type: ignore[arg-type, attr-defined]
        .limit(1),
    )
    latest = result.scalar_one_or_none()
    if not latest:
        return False
    if last_run is None:
        return True
    last_dt = last_run.replace(tzinfo=None) if last_run.tzinfo else last_run
    created = latest.created_at.replace(tzinfo=None) if latest.created_at.tzinfo else latest.created_at
    return created > last_dt


def get_due_schedules(session: Session) -> list[Schedule]:
    """Return all enabled schedules that are due to run."""
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
        if should_run(sched.cron_expression, sched.last_run):
            due.append(sched)
            continue
        if sched.trigger_on_datasource_id and _is_triggered_by_datasource(
            session,
            sched.trigger_on_datasource_id,
            sched.last_run,
        ):
            due.append(sched)
    return due


def mark_schedule_run(session: Session, schedule_id: str) -> None:
    """Update last_run to now and recompute next_run after a successful build."""
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    schedule.last_run = now
    schedule.next_run = _compute_next_run(schedule.cron_expression)
    session.add(schedule)
    session.commit()


def execute_schedule(session: Session, manager: ProcessManager, schedule_id: str, triggered_by: str = 'schedule') -> dict:
    """Execute a schedule by building its target dataset.

    The datasource determines which analysis and tab to run.
    The LATEST version of the analysis is always used.

    BUILD BEHAVIOR:
    - Analysis provenance datasource: build the producing analysis tab
    - Reingestable raw iceberg datasource: refresh external source into iceberg
    - Other datasources: refresh schema/cache from current source and log update run

    Returns build results.
    """
    from modules.compute import service as compute_service

    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise ValueError(f'Schedule {schedule_id} not found')

    # Resolve target at execution time
    target_kind, analysis_id, _ = _resolve_schedule_target(session, schedule.datasource_id)

    if target_kind == 'raw':
        from modules.datasource import service as datasource_service

        refreshed = datasource_service.refresh_external_datasource(session, schedule.datasource_id)
        return {
            'schedule_id': schedule_id,
            'datasource_id': schedule.datasource_id,
            'analysis_id': None,
            'tab_id': None,
            'tab_name': refreshed.name,
            'status': 'success',
        }

    if target_kind == 'datasource':
        from modules.datasource import service as datasource_service

        refreshed = datasource_service.refresh_datasource_for_schedule(session, schedule.datasource_id)
        return {
            'schedule_id': schedule_id,
            'datasource_id': schedule.datasource_id,
            'analysis_id': None,
            'tab_id': None,
            'tab_name': refreshed.name,
            'status': 'success',
        }

    # Get the LATEST analysis version
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found for datasource {schedule.datasource_id}')

    # Find the specific tab that produces this datasource
    pipeline = analysis.pipeline

    target_tab = next(
        (t for t in pipeline.tabs if t.output.result_id == schedule.datasource_id),
        None,
    )

    if not target_tab:
        raise ValueError(f'No tab found in analysis {analysis_id} that produces datasource {schedule.datasource_id}')

    tab_id = target_tab.id or 'unknown'
    tab_name = target_tab.name or 'unnamed'

    if not target_tab.datasource.id:
        raise ValueError(f'Tab {tab_id} has no input datasource')

    if not target_tab.output.filename:
        raise ValueError(f'Tab {tab_id} missing output configuration')

    # Determine target step
    target_step_id = target_tab.steps[-1].id if target_tab.steps else 'source'

    # Build the tab (single execution - query plan handles lazyframe deps automatically)
    filename = target_tab.output.filename or f'{tab_name}_out'

    iceberg_options = None
    output_raw = target_tab.output.to_dict()
    iceberg_cfg = output_raw.get('iceberg')
    if isinstance(iceberg_cfg, dict):
        iceberg_options = {
            'table_name': iceberg_cfg.get('table_name', 'exported_data'),
            'namespace': iceberg_cfg.get('namespace', 'outputs'),
            'branch': iceberg_cfg.get('branch', 'master'),
        }

    tab_build_mode = output_raw.get('build_mode', 'full')

    logger.info(f'Schedule {schedule_id}: Building tab {tab_name} mode={tab_build_mode} (lazyframe deps auto-resolved in query plan)')

    pipeline_payload = compute_service.build_analysis_pipeline_payload(session, analysis, datasource_id=schedule.datasource_id)
    compute_service.export_data(
        session=session,
        manager=manager,
        target_step_id=target_step_id,
        analysis_pipeline=pipeline_payload,
        filename=filename,
        iceberg_options=iceberg_options,
        analysis_id=analysis_id,
        triggered_by=triggered_by,
        result_id=schedule.datasource_id,
        tab_id=str(tab_id),
        build_mode=tab_build_mode,
    )

    return {
        'schedule_id': schedule_id,
        'datasource_id': schedule.datasource_id,
        'analysis_id': analysis_id,
        'tab_id': tab_id,
        'tab_name': tab_name,
        'status': 'success',
    }


def _resolve_upstream_tabs(tabs: list[PipelineTab], target_tab_id: str) -> set[str]:
    """Find all tab IDs that the target tab depends on via lazyframe inputs (including itself)."""
    output_to_tab: dict[str, str] = {}
    tab_input: dict[str, str] = {}

    for tab in tabs:
        if tab.id and tab.output.result_id:
            output_to_tab[tab.output.result_id] = tab.id
        if tab.id and tab.datasource.id:
            tab_input[tab.id] = tab.datasource.id

    required: set[str] = set()
    queue: deque[str] = deque([target_tab_id])
    while queue:
        current = queue.popleft()
        if current in required:
            continue
        required.add(current)
        input_ds = tab_input.get(current)
        if input_ds and input_ds in output_to_tab:
            upstream = output_to_tab[input_ds]
            if upstream not in required:
                queue.append(upstream)

    return required


def run_analysis_build(
    session: Session,
    analysis_id: str,
    manager: ProcessManager | None = None,
    datasource_id: str | None = None,
    triggered_by: str = 'schedule',
    tab_id: str | None = None,
) -> dict:
    """Execute a full build for an analysis — run all tabs.

    Tabs with output config export data via export_data().
    Tabs without output config are skipped.
    Engine runs are tagged with ``triggered_by`` (default 'schedule').
    If ``tab_id`` is provided, that tab and its upstream lazyframe
    dependencies are built.

    Returns a dict with build results per tab.
    """
    from modules.compute import service as compute_service

    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    pipeline_payload = compute_service.build_analysis_pipeline_payload(session, analysis, datasource_id=datasource_id)

    pipeline = analysis.pipeline
    if not pipeline.tabs:
        logger.warning(f'Scheduler: analysis {analysis_id} has no tabs, skipping build')
        return {'analysis_id': analysis_id, 'tabs_built': 0, 'results': []}

    required_tabs = _resolve_upstream_tabs(pipeline.tabs, tab_id) if tab_id else None

    results: list[dict] = []
    tabs_built = 0

    for tab in pipeline.tabs:
        current_tab_id = tab.id or 'unknown'
        tab_name = tab.name or 'unnamed'
        tab_datasource_id = tab.datasource.id
        tab_output_id = tab.output.result_id
        has_output = bool(tab.output.filename)
        steps = tab.steps

        if not tab_datasource_id:
            continue

        if required_tabs and current_tab_id not in required_tabs:
            continue

        if datasource_id and tab_output_id != datasource_id:
            continue

        # Determine the target step (last step, or 'source' if no steps)
        target_step_id = steps[-1].id if steps else 'source'

        try:
            if has_output:
                # Tab has export config — run full export (Iceberg-only)
                filename = tab.output.filename or f'{tab_name}_out'

                iceberg_cfg = tab.output.to_dict().get('iceberg')
                iceberg_options = (
                    {
                        'table_name': iceberg_cfg.get('table_name', 'exported_data'),
                        'namespace': iceberg_cfg.get('namespace', 'outputs'),
                        'branch': iceberg_cfg.get('branch', 'master'),
                    }
                    if isinstance(iceberg_cfg, dict)
                    else None
                )

                compute_service.export_data(
                    session=session,
                    manager=manager,  # type: ignore[arg-type]
                    target_step_id=target_step_id,
                    analysis_pipeline=pipeline_payload,
                    filename=filename,
                    iceberg_options=iceberg_options,
                    analysis_id=analysis_id,
                    triggered_by=triggered_by,
                    result_id=tab.output.result_id,
                    tab_id=current_tab_id,
                )
            else:
                if required_tabs and current_tab_id != tab_id:
                    tabs_built += 1
                    results.append({'tab_id': current_tab_id, 'tab_name': tab_name, 'status': 'success'})
                    continue
                raise ScheduleValidationError(f'Tab {current_tab_id} missing output configuration')

            tabs_built += 1
            results.append({'tab_id': current_tab_id, 'tab_name': tab_name, 'status': 'success'})
            logger.info(f'Scheduler: built tab {tab_name} ({current_tab_id}) for analysis {analysis_id}')
        except Exception as e:
            results.append({'tab_id': current_tab_id, 'tab_name': tab_name, 'status': 'failed', 'error': str(e)})
            logger.error(f'Scheduler: failed to build tab {tab_name} ({current_tab_id}) for analysis {analysis_id}: {e}')

    return {'analysis_id': analysis_id, 'tabs_built': tabs_built, 'results': results}


def _compute_next_run(cron_expr: str) -> datetime | None:
    if not cron_expr:
        return None
    cron = croniter.croniter(cron_expr, datetime.now(UTC))
    return cron.get_next(datetime)
