from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from modules.engine_runs import schemas, service
from modules.engine_runs.models import EngineRun

router = APIRouter(prefix='/engine-runs', tags=['engine-runs'])


@router.get('/compare', response_model=schemas.BuildComparisonResponse)
@handle_errors(operation='compare engine runs')
def compare_runs(
    run_a: str,
    run_b: str,
    session: Session = Depends(get_db),
):
    return service.compare_engine_runs(session, run_a, run_b)


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


@router.get('/{run_id}', response_model=schemas.EngineRunResponseSchema)
@handle_errors(operation='get engine run')
def get_run(run_id: str, session: Session = Depends(get_db)):
    run = session.get(EngineRun, run_id)
    if not run:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail='Engine run not found')
    return schemas.EngineRunResponseSchema.model_validate(run)
