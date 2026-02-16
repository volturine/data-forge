import logging
import uuid
from datetime import UTC, datetime

import croniter  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlmodel import Session

from core.exceptions import AnalysisNotFoundError, DataSourceNotFoundError, ScheduleNotFoundError, ScheduleValidationError
from modules.analysis.models import Analysis
from modules.datasource.models import DataSource
from modules.engine_runs.models import EngineRun
from modules.scheduler.models import Schedule
from modules.scheduler.schemas import ScheduleCreate, ScheduleResponse, ScheduleUpdate

logger = logging.getLogger(__name__)


def _resolve_schedule_target(session: Session, datasource_id: str) -> tuple[str, str | None]:
    """Resolve a datasource to its producing analysis and tab.

    Returns: (analysis_id, tab_id) - tab_id may be None
    """
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    analysis_id = datasource.created_by_analysis_id
    if not analysis_id:
        raise ScheduleValidationError('Datasource has no provenance (not created by analysis)', details={'datasource_id': datasource_id})

    # Tab ID is stored in config
    tab_id = None
    if isinstance(datasource.config, dict):
        tab_id = datasource.config.get('analysis_tab_id')

    return analysis_id, tab_id


def _enrich_schedule_response(session: Session, schedule: Schedule) -> ScheduleResponse:
    """Enrich schedule with resolved analysis/tab info from datasource provenance."""
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

    # Resolve provenance from datasource
    datasource = session.get(DataSource, schedule.datasource_id)
    if datasource:
        data['analysis_id'] = datasource.created_by_analysis_id

        # Tab ID is stored in config
        tab_id = None
        if isinstance(datasource.config, dict):
            tab_id = datasource.config.get('analysis_tab_id')
        data['tab_id'] = tab_id

        # Get analysis name
        if datasource.created_by_analysis_id:
            analysis = session.get(Analysis, datasource.created_by_analysis_id)
            if analysis:
                data['analysis_name'] = analysis.name

                # Get tab name from pipeline definition
                if tab_id and analysis.pipeline_definition:
                    pipeline = analysis.pipeline_definition
                    if isinstance(pipeline, dict):
                        tabs = pipeline.get('tabs', [])
                        for tab in tabs:
                            if tab.get('id') == tab_id:
                                data['tab_name'] = tab.get('name', 'unnamed')
                                break

    return ScheduleResponse.model_validate(data)


def list_schedules(
    session: Session,
    datasource_id: str | None = None,
) -> list[ScheduleResponse]:
    """List schedules with optional filtering by target datasource."""
    query = select(Schedule)
    if datasource_id:
        query = query.where(Schedule.datasource_id == datasource_id)  # type: ignore[arg-type]
    result = session.execute(query)
    schedules = result.scalars().all()
    return [_enrich_schedule_response(session, schedule) for schedule in schedules]


def create_schedule(session: Session, payload: ScheduleCreate) -> ScheduleResponse:
    """Create a new schedule targeting a specific dataset.

    The datasource must be an analysis output (created_by='analysis').
    The analysis_id and tab_id are resolved from the datasource at execution time,
    not stored in the schedule.
    """
    # Validate datasource exists and is an analysis output
    datasource = session.get(DataSource, payload.datasource_id)
    if not datasource:
        raise DataSourceNotFoundError(payload.datasource_id)
    if datasource.created_by != 'analysis':
        raise ScheduleValidationError(
            'Schedules can only be created for analysis-output datasources',
            details={'datasource_id': payload.datasource_id, 'created_by': datasource.created_by},
        )
    if not datasource.created_by_analysis_id:
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
        if datasource.created_by != 'analysis':
            raise ScheduleValidationError(
                'Schedules can only target analysis-output datasources', details={'datasource_id': payload.datasource_id}
            )
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

    deps = session.execute(select(AnalysisDataSource)).scalars().all()
    for dep in deps:
        datasource = session.get(DataSource, dep.datasource_id)
        if not datasource or not datasource.created_by_analysis_id:
            continue
        upstream = datasource.created_by_analysis_id
        graph.setdefault(upstream, set()).add(dep.analysis_id)
        in_degree[dep.analysis_id] = in_degree.get(dep.analysis_id, 0) + 1

    queue = [aid for aid, degree in in_degree.items() if degree == 0]
    ordered: list[str] = []
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for neighbor in graph.get(node, set()):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    if analysis_id in ordered:
        return ordered
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
    result = session.execute(
        select(EngineRun)
        .where(EngineRun.datasource_id == datasource_id)  # type: ignore[arg-type]
        .where(EngineRun.status == 'success')  # type: ignore[arg-type]
        .where(EngineRun.kind.in_(['datasource_update', 'datasource_create']))  # type: ignore[arg-type, attr-defined]
        .order_by(EngineRun.created_at.desc())  # type: ignore[arg-type, attr-defined]
        .limit(1)
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
        select(Schedule).where(Schedule.enabled == True)  # type: ignore[arg-type]  # noqa: E712
    )
    schedules = result.scalars().all()
    due: list[Schedule] = []
    for sched in schedules:
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


def execute_schedule(session: Session, schedule_id: str, triggered_by: str = 'schedule') -> dict:
    """Execute a schedule by building its target dataset.

    The datasource determines which analysis and tab to run.
    The LATEST version of the analysis is always used.

    BUILD BEHAVIOR:
    - Single execution builds the target tab
    - Lazyframe inputs: Query plan automatically includes upstream tab logic (single query)
    - Exported inputs: Uses current snapshot data (may be stale, that's OK)

    Returns build results.
    """
    from modules.compute import service as compute_service

    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise ValueError(f'Schedule {schedule_id} not found')

    # Resolve target at execution time
    analysis_id, _ = _resolve_schedule_target(session, schedule.datasource_id)

    # Get the LATEST analysis version
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found for datasource {schedule.datasource_id}')

    # Find the specific tab that produces this datasource
    pipeline = analysis.pipeline_definition
    tabs = pipeline.get('tabs', []) if isinstance(pipeline, dict) else []

    target_tab = None
    for tab in tabs:
        if tab.get('output_datasource_id') == schedule.datasource_id:
            target_tab = tab
            break

    if not target_tab:
        raise ValueError(f'No tab found in analysis {analysis_id} that produces datasource {schedule.datasource_id}')

    tab_id = target_tab.get('id', 'unknown')
    tab_name = target_tab.get('name', 'unnamed')
    tab_datasource_id = target_tab.get('datasource_id')
    steps = target_tab.get('steps', [])
    datasource_config = target_tab.get('datasource_config')

    if not tab_datasource_id:
        raise ValueError(f'Tab {tab_id} has no input datasource')

    # Extract output config
    output_config = None
    if isinstance(datasource_config, dict):
        output_config = datasource_config.get('output')

    if not output_config:
        raise ValueError(f'Tab {tab_id} missing output configuration')

    # Determine target step
    target_step_id = 'source'
    if steps:
        target_step_id = steps[-1].get('id', 'source')

    # Build the tab (single execution - query plan handles lazyframe deps automatically)
    datasource_type = 'iceberg'
    export_format = 'parquet'
    filename = output_config.get('filename', f'{tab_name}_out')

    iceberg_options = None
    iceberg_cfg = output_config.get('iceberg')
    if iceberg_cfg and isinstance(iceberg_cfg, dict):
        iceberg_options = {
            'table_name': iceberg_cfg.get('table_name', 'exported_data'),
            'namespace': iceberg_cfg.get('namespace', 'exports'),
        }

    logger.info(f'Schedule {schedule_id}: Building tab {tab_name} (lazyframe deps auto-resolved in query plan)')

    compute_service.export_data(
        session=session,
        datasource_id=tab_datasource_id,
        pipeline_steps=steps,
        target_step_id=target_step_id,
        export_format=export_format,
        filename=filename,
        destination='datasource',
        datasource_type=datasource_type,
        iceberg_options=iceberg_options,
        duckdb_options=None,
        datasource_config=datasource_config,
        analysis_id=analysis_id,
        triggered_by=triggered_by,
        output_datasource_id=schedule.datasource_id,
    )

    return {
        'schedule_id': schedule_id,
        'datasource_id': schedule.datasource_id,
        'analysis_id': analysis_id,
        'tab_id': tab_id,
        'tab_name': tab_name,
        'status': 'success',
    }


def _resolve_upstream_tabs(tabs: list[dict], target_tab_id: str) -> set[str]:
    """Find all tab IDs that the target tab depends on via lazyframe inputs (including itself)."""
    output_to_tab: dict[str, str] = {}
    tab_input: dict[str, str] = {}

    for tab in tabs:
        tid = tab.get('id')
        output_id = tab.get('output_datasource_id')
        input_id = tab.get('datasource_id')
        if tid and output_id:
            output_to_tab[output_id] = tid
        if tid and input_id:
            tab_input[tid] = input_id

    required: set[str] = set()
    queue = [target_tab_id]
    while queue:
        current = queue.pop(0)
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

    pipeline = analysis.pipeline_definition
    tabs = pipeline.get('tabs', []) if isinstance(pipeline, dict) else []
    if not tabs:
        logger.warning(f'Scheduler: analysis {analysis_id} has no tabs, skipping build')
        return {'analysis_id': analysis_id, 'tabs_built': 0, 'results': []}

    required_tabs = _resolve_upstream_tabs(tabs, tab_id) if tab_id else None

    results: list[dict] = []
    tabs_built = 0

    for tab in tabs:
        current_tab_id = tab.get('id', 'unknown')
        tab_name = tab.get('name', 'unnamed')
        tab_datasource_id = tab.get('datasource_id')
        tab_output_id = tab.get('output_datasource_id')
        steps = tab.get('steps', [])
        datasource_config = tab.get('datasource_config')

        if not tab_datasource_id:
            continue

        if required_tabs and current_tab_id not in required_tabs:
            continue

        if datasource_id and tab_output_id != datasource_id:
            continue

        # Extract output config if present
        output_config = None
        if isinstance(datasource_config, dict):
            output_config = datasource_config.get('output')

        # Determine the target step (last step, or 'source' if no steps)
        target_step_id = 'source'
        if steps:
            target_step_id = steps[-1].get('id', 'source')

        try:
            if output_config is not None:
                # Tab has export config — run full export (Iceberg-only)
                datasource_type = 'iceberg'
                export_format = 'parquet'
                filename = output_config.get('filename', f'{tab_name}_out')

                iceberg_options = None
                iceberg_cfg = output_config.get('iceberg')
                if iceberg_cfg and isinstance(iceberg_cfg, dict):
                    iceberg_options = {
                        'table_name': iceberg_cfg.get('table_name', 'exported_data'),
                        'namespace': iceberg_cfg.get('namespace', 'exports'),
                    }

                duckdb_options = None

                compute_service.export_data(
                    session=session,
                    datasource_id=tab_datasource_id,
                    pipeline_steps=steps,
                    target_step_id=target_step_id,
                    export_format=export_format,
                    filename=filename,
                    destination='datasource',
                    datasource_type=datasource_type,
                    iceberg_options=iceberg_options,
                    duckdb_options=duckdb_options,
                    datasource_config=datasource_config,
                    analysis_id=analysis_id,
                    triggered_by=triggered_by,
                    output_datasource_id=tab.get('output_datasource_id'),
                )
            else:
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
