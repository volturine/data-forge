import uuid
from datetime import UTC, datetime

from contracts.analysis.models import Analysis
from contracts.datasource.models import DataSource
from contracts.runtime import ipc as runtime_ipc
from contracts.scheduler import schemas
from contracts.scheduler.models import Schedule
from core.database import get_db
from core.exceptions import (
    DataSourceNotFoundError,
    ScheduleNotFoundError,
    ScheduleValidationError,
)
from fastapi import Depends
from sqlalchemy import select
from sqlmodel import Session, col

from backend_core.error_handlers import handle_errors
from backend_core.validation import (
    DataSourceId,
    ScheduleId,
    parse_datasource_id,
    parse_schedule_id,
)
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix="/schedules", tags=["schedules"])


def _response(schedule: Schedule, datasource: DataSource | None, analysis: Analysis | None) -> schemas.ScheduleResponse:
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
    if datasource is not None:
        data["analysis_id"] = datasource.created_by_analysis_id
        tab_id = datasource.config.get("analysis_tab_id") if isinstance(datasource.config, dict) else None
        data["tab_id"] = tab_id
        if analysis is not None:
            data["analysis_name"] = analysis.name
            if tab_id:
                for tab in analysis.pipeline.tabs:
                    if tab.id == tab_id:
                        data["tab_name"] = tab.name or "unnamed"
                        break
    return schemas.ScheduleResponse.model_validate(data)


def _enrich(session: Session, schedules: list[Schedule]) -> list[schemas.ScheduleResponse]:
    datasource_ids = {schedule.datasource_id for schedule in schedules}
    datasources = session.execute(select(DataSource).where(col(DataSource.id).in_(datasource_ids))).scalars().all() if datasource_ids else []
    datasource_map = {datasource.id: datasource for datasource in datasources}
    analysis_ids = {datasource.created_by_analysis_id for datasource in datasources if datasource.created_by_analysis_id}
    analyses = session.execute(select(Analysis).where(col(Analysis.id).in_(analysis_ids))).scalars().all() if analysis_ids else []
    analysis_map = {analysis.id: analysis for analysis in analyses}
    return [
        _response(
            schedule,
            datasource_map.get(schedule.datasource_id),
            analysis_map.get(datasource_map[schedule.datasource_id].created_by_analysis_id)
            if schedule.datasource_id in datasource_map and datasource_map[schedule.datasource_id].created_by_analysis_id
            else None,
        )
        for schedule in schedules
    ]


@router.get("", response_model=list[schemas.ScheduleResponse], mcp=True)
@handle_errors(operation="list schedules")
def list_schedules(
    datasource_id: DataSourceId | None = None,
    session: Session = Depends(get_db),
):
    """List all schedules. Optionally filter by datasource_id to see schedules for a specific output.

    Returns schedule details including resolved analysis name and tab name.
    """
    query = select(Schedule)
    if datasource_id:
        query = query.where(col(Schedule.datasource_id) == parse_datasource_id(datasource_id))
    schedules = list(session.execute(query).scalars().all())
    return _enrich(session, schedules)


@router.post("", response_model=schemas.ScheduleResponse, mcp=True)
@handle_errors(operation="create schedule")
def create_schedule(payload: schemas.ScheduleCreate, session: Session = Depends(get_db)):
    """Create a build schedule for an analysis output datasource.

    Requires datasource_id (must be an analysis-output datasource from GET /datasource)
    and cron_expression (e.g., '0 6 * * *' for daily at 6am).
    Optional: depends_on (another schedule ID to run after), trigger_on_datasource_id
    (run when that datasource is updated instead of on cron).
    """
    datasource = session.get(DataSource, payload.datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(payload.datasource_id)
    if datasource.is_analysis_output and not datasource.created_by_analysis_id:
        raise ScheduleValidationError(
            "Datasource has no analysis provenance",
            details={"datasource_id": payload.datasource_id},
        )
    if payload.depends_on and session.get(Schedule, payload.depends_on) is None:
        raise ScheduleValidationError("Dependency schedule not found", details={"depends_on": payload.depends_on})
    if payload.trigger_on_datasource_id and session.get(DataSource, payload.trigger_on_datasource_id) is None:
        raise DataSourceNotFoundError(payload.trigger_on_datasource_id)
    schedule = Schedule(
        id=str(uuid.uuid4()),
        datasource_id=payload.datasource_id,
        cron_expression=payload.cron_expression,
        enabled=payload.enabled,
        depends_on=payload.depends_on,
        trigger_on_datasource_id=payload.trigger_on_datasource_id,
        last_run=None,
        next_run=Schedule.compute_next_run(payload.cron_expression),
        created_at=datetime.now(UTC),
    )
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    runtime_ipc.notify_build_job()
    return _response(
        schedule,
        datasource,
        session.get(Analysis, datasource.created_by_analysis_id) if datasource.created_by_analysis_id else None,
    )


@router.put("/{schedule_id}", response_model=schemas.ScheduleResponse, mcp=True)
@handle_errors(operation="update schedule")
def update_schedule(
    schedule_id: ScheduleId,
    payload: schemas.ScheduleUpdate,
    session: Session = Depends(get_db),
):
    """Update a schedule's cron expression, enabled state, or dependencies. Use GET /schedules to find schedule IDs."""
    schedule = session.get(Schedule, parse_schedule_id(schedule_id))
    if schedule is None:
        raise ScheduleNotFoundError(parse_schedule_id(schedule_id))
    datasource = None
    if payload.datasource_id:
        datasource = session.get(DataSource, payload.datasource_id)
        if datasource is None:
            raise DataSourceNotFoundError(payload.datasource_id)
    if payload.depends_on and session.get(Schedule, payload.depends_on) is None:
        raise ScheduleValidationError("Dependency schedule not found", details={"depends_on": payload.depends_on})
    if payload.trigger_on_datasource_id and session.get(DataSource, payload.trigger_on_datasource_id) is None:
        raise DataSourceNotFoundError(payload.trigger_on_datasource_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(schedule, key, value)
    if payload.cron_expression:
        schedule.next_run = Schedule.compute_next_run(payload.cron_expression)
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    runtime_ipc.notify_build_job()
    datasource = datasource or session.get(DataSource, schedule.datasource_id)
    return _response(
        schedule,
        datasource,
        session.get(Analysis, datasource.created_by_analysis_id) if datasource and datasource.created_by_analysis_id else None,
    )


@router.delete("/{schedule_id}", status_code=204, mcp=True)
@handle_errors(operation="delete schedule")
def delete_schedule(schedule_id: ScheduleId, session: Session = Depends(get_db)):
    """Delete a schedule by ID. Use GET /schedules to find schedule IDs."""
    schedule = session.get(Schedule, parse_schedule_id(schedule_id))
    if schedule is None:
        raise ScheduleNotFoundError(parse_schedule_id(schedule_id))
    session.delete(schedule)
    session.commit()
