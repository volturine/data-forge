from fastapi import Depends
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import DataSourceId, ScheduleId, parse_datasource_id, parse_schedule_id
from modules.mcp.router import MCPRouter
from modules.scheduler import schemas, service

router = MCPRouter(prefix='/schedules', tags=['schedules'])


@router.get('', response_model=list[schemas.ScheduleResponse], mcp=True)
@handle_errors(operation='list schedules')
def list_schedules(
    datasource_id: DataSourceId | None = None,
    session: Session = Depends(get_db),
):
    """List all schedules. Optionally filter by datasource_id to see schedules for a specific output.

    Returns schedule details including resolved analysis name and tab name.
    """
    return service.list_schedules(session, parse_datasource_id(datasource_id) if datasource_id else None)


@router.post('', response_model=schemas.ScheduleResponse, mcp=True)
@handle_errors(operation='create schedule')
def create_schedule(payload: schemas.ScheduleCreate, session: Session = Depends(get_db)):
    """Create a build schedule for an analysis output datasource.

    Requires datasource_id (must be an analysis-output datasource from GET /datasource)
    and cron_expression (e.g., '0 6 * * *' for daily at 6am).
    Optional: depends_on (another schedule ID to run after), trigger_on_datasource_id
    (run when that datasource is updated instead of on cron).
    """
    return service.create_schedule(session, payload)


@router.put('/{schedule_id}', response_model=schemas.ScheduleResponse, mcp=True)
@handle_errors(operation='update schedule')
def update_schedule(schedule_id: ScheduleId, payload: schemas.ScheduleUpdate, session: Session = Depends(get_db)):
    """Update a schedule's cron expression, enabled state, or dependencies. Use GET /schedules to find schedule IDs."""
    return service.update_schedule(session, parse_schedule_id(schedule_id), payload)


@router.delete('/{schedule_id}', status_code=204, mcp=True)
@handle_errors(operation='delete schedule')
def delete_schedule(schedule_id: ScheduleId, session: Session = Depends(get_db)):
    """Delete a schedule by ID. Use GET /schedules to find schedule IDs."""
    service.delete_schedule(session, parse_schedule_id(schedule_id))
