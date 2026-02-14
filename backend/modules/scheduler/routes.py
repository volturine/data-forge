from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from modules.scheduler import schemas, service

router = APIRouter(prefix='/schedules', tags=['schedules'])


@router.get('', response_model=list[schemas.ScheduleResponse])
@handle_errors(operation='list schedules')
def list_schedules(analysis_id: str | None = None, session: Session = Depends(get_db)):
    return service.list_schedules(session, analysis_id)


@router.post('', response_model=schemas.ScheduleResponse)
@handle_errors(operation='create schedule')
def create_schedule(payload: schemas.ScheduleCreate, session: Session = Depends(get_db)):
    return service.create_schedule(session, payload)


@router.put('/{schedule_id}', response_model=schemas.ScheduleResponse)
@handle_errors(operation='update schedule')
def update_schedule(schedule_id: str, payload: schemas.ScheduleUpdate, session: Session = Depends(get_db)):
    try:
        return service.update_schedule(session, schedule_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete('/{schedule_id}')
@handle_errors(operation='delete schedule')
def delete_schedule(schedule_id: str, session: Session = Depends(get_db)):
    try:
        service.delete_schedule(session, schedule_id)
        return {'message': 'Schedule deleted'}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
