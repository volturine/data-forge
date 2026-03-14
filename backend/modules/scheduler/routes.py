from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import DataSourceId, ScheduleId, parse_datasource_id, parse_schedule_id
from modules.mcp.decorators import deterministic_tool
from modules.scheduler import schemas, service

router = APIRouter(prefix='/schedules', tags=['schedules'])


@router.get('', response_model=list[schemas.ScheduleResponse])
@handle_errors(operation='list schedules')
@deterministic_tool
def list_schedules(
    datasource_id: DataSourceId | None = None,
    session: Session = Depends(get_db),
):
    return service.list_schedules(session, parse_datasource_id(datasource_id) if datasource_id else None)


@router.post('', response_model=schemas.ScheduleResponse)
@handle_errors(operation='create schedule')
@deterministic_tool
def create_schedule(payload: schemas.ScheduleCreate, session: Session = Depends(get_db)):
    return service.create_schedule(session, payload)


@router.put('/{schedule_id}', response_model=schemas.ScheduleResponse)
@handle_errors(operation='update schedule')
@deterministic_tool
def update_schedule(schedule_id: ScheduleId, payload: schemas.ScheduleUpdate, session: Session = Depends(get_db)):
    return service.update_schedule(session, parse_schedule_id(schedule_id), payload)


@router.delete('/{schedule_id}', status_code=204)
@handle_errors(operation='delete schedule')
@deterministic_tool
def delete_schedule(schedule_id: ScheduleId, session: Session = Depends(get_db)):
    service.delete_schedule(session, parse_schedule_id(schedule_id))
    return None
