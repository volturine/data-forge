from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from modules.engine_runs import schemas, service

router = APIRouter(prefix='/engine-runs', tags=['engine-runs'])


@router.get('', response_model=list[schemas.EngineRunResponseSchema])
@handle_errors(operation='list engine runs')
def list_runs(
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_db),
):
    return service.list_engine_runs(
        session=session,
        analysis_id=analysis_id,
        datasource_id=datasource_id,
        kind=kind,
        status=status,
        limit=limit,
        offset=offset,
    )
