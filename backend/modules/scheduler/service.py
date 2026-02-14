import logging
import uuid
from datetime import UTC, datetime

import croniter  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlmodel import Session

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource
from modules.scheduler.models import Schedule
from modules.scheduler.schemas import ScheduleCreate, ScheduleResponse, ScheduleUpdate

logger = logging.getLogger(__name__)


def list_schedules(session: Session, analysis_id: str | None = None) -> list[ScheduleResponse]:
    query = select(Schedule)
    if analysis_id:
        query = query.where(Schedule.analysis_id == analysis_id)  # type: ignore[arg-type]
    result = session.execute(query)
    schedules = result.scalars().all()
    return [ScheduleResponse.model_validate(schedule) for schedule in schedules]


def create_schedule(session: Session, payload: ScheduleCreate) -> ScheduleResponse:
    next_run = _compute_next_run(payload.cron_expression)
    record = Schedule(
        id=str(uuid.uuid4()),
        analysis_id=payload.analysis_id,
        cron_expression=payload.cron_expression,
        enabled=payload.enabled,
        last_run=None,
        next_run=next_run,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return ScheduleResponse.model_validate(record)


def update_schedule(session: Session, schedule_id: str, payload: ScheduleUpdate) -> ScheduleResponse:
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise ValueError('Schedule not found')
    update_data = payload.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(schedule, key, value)
    if payload.cron_expression:
        schedule.next_run = _compute_next_run(payload.cron_expression)
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return ScheduleResponse.model_validate(schedule)


def delete_schedule(session: Session, schedule_id: str) -> None:
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        raise ValueError('Schedule not found')
    session.delete(schedule)
    session.commit()


def get_build_order(session: Session, analysis_id: str) -> list[str]:
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
    # Normalize last_run to naive UTC for consistent comparison
    # (SQLite may return naive datetimes, croniter follows input tzinfo)
    naive_last = last_run.replace(tzinfo=None) if last_run.tzinfo else last_run
    cron = croniter.croniter(cron_expr, naive_last)
    next_run = cron.get_next(datetime)
    now = datetime.now(UTC).replace(tzinfo=None)
    return next_run <= now


def get_due_schedules(session: Session) -> list[Schedule]:
    """Return all enabled schedules that are due to run."""
    # SQLModel field typed as bool; == creates SA expression at runtime
    result = session.execute(
        select(Schedule).where(Schedule.enabled == True)  # type: ignore[arg-type]  # noqa: E712
    )
    schedules = result.scalars().all()
    return [s for s in schedules if should_run(s.cron_expression, s.last_run)]


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


def run_analysis_build(session: Session, analysis_id: str) -> dict:
    """Execute a full build for an analysis — run exports for all tabs with output config.

    Returns a dict with build results per tab.
    """
    from modules.compute import service as compute_service

    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    pipeline = analysis.pipeline_definition
    tabs = pipeline.get('tabs', []) if isinstance(pipeline, dict) else []
    if not tabs:
        logger.warning(f'Scheduler: analysis {analysis_id} has no tabs, skipping build')
        return {'analysis_id': analysis_id, 'tabs_built': 0, 'results': []}

    results: list[dict] = []
    tabs_built = 0

    for tab in tabs:
        tab_id = tab.get('id', 'unknown')
        tab_name = tab.get('name', 'unnamed')
        datasource_id = tab.get('datasource_id')
        steps = tab.get('steps', [])
        datasource_config = tab.get('datasource_config')

        # Only build tabs that have output configuration
        output_config = None
        if isinstance(datasource_config, dict):
            output_config = datasource_config.get('output')

        if not output_config or not datasource_id:
            continue

        # Determine the target step (last step, or 'source' if no steps)
        target_step_id = 'source'
        if steps:
            target_step_id = steps[-1].get('id', 'source')

        # Extract export parameters from output config
        datasource_type = output_config.get('datasource_type', 'iceberg')
        export_format = output_config.get('format', 'csv')
        filename = output_config.get('filename', f'{tab_name}_out')

        iceberg_options = None
        iceberg_cfg = output_config.get('iceberg')
        if iceberg_cfg and isinstance(iceberg_cfg, dict):
            iceberg_options = {
                'table_name': iceberg_cfg.get('table_name', 'exported_data'),
                'namespace': iceberg_cfg.get('namespace', 'exports'),
            }

        duckdb_options = None
        duckdb_cfg = output_config.get('duckdb')
        if duckdb_cfg and isinstance(duckdb_cfg, dict):
            duckdb_options = {
                'table_name': duckdb_cfg.get('table_name', 'data'),
            }

        try:
            compute_service.export_data(
                session=session,
                datasource_id=datasource_id,
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
            )
            tabs_built += 1
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': 'success'})
            logger.info(f'Scheduler: built tab {tab_name} ({tab_id}) for analysis {analysis_id}')
        except Exception as e:
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': 'failed', 'error': str(e)})
            logger.error(f'Scheduler: failed to build tab {tab_name} ({tab_id}) for analysis {analysis_id}: {e}')

    return {'analysis_id': analysis_id, 'tabs_built': tabs_built, 'results': results}


def _compute_next_run(cron_expr: str) -> datetime | None:
    if not cron_expr:
        return None
    cron = croniter.croniter(cron_expr, datetime.now(UTC))
    return cron.get_next(datetime)
