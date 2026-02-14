from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from modules.healthcheck import schemas, service

router = APIRouter(prefix='/healthchecks', tags=['healthchecks'])


@router.get('', response_model=list[schemas.HealthCheckResponse])
@handle_errors(operation='list healthchecks')
def list_healthchecks(datasource_id: str, session: Session = Depends(get_db)):
    return service.list_healthchecks(session, datasource_id)


@router.get('/results', response_model=list[schemas.HealthCheckResultResponse])
@handle_errors(operation='list healthcheck results')
def list_results(datasource_id: str, limit: int = 10, session: Session = Depends(get_db)):
    return service.list_results(session, datasource_id, limit)


@router.post('', response_model=schemas.HealthCheckResponse)
@handle_errors(operation='create healthcheck')
def create_healthcheck(payload: schemas.HealthCheckCreate, session: Session = Depends(get_db)):
    return service.create_healthcheck(session, payload)


@router.put('/{healthcheck_id}', response_model=schemas.HealthCheckResponse)
@handle_errors(operation='update healthcheck')
def update_healthcheck(
    healthcheck_id: str,
    payload: schemas.HealthCheckUpdate,
    session: Session = Depends(get_db),
):
    try:
        return service.update_healthcheck(session, healthcheck_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete('/{healthcheck_id}')
@handle_errors(operation='delete healthcheck')
def delete_healthcheck(healthcheck_id: str, session: Session = Depends(get_db)):
    try:
        service.delete_healthcheck(session, healthcheck_id)
        return {'message': 'Healthcheck deleted'}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
