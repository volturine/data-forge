from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import EngineRunId, parse_analysis_id, parse_datasource_id, parse_engine_run_id
from modules.engine_runs import schemas, service
from modules.engine_runs.models import EngineRun

router = APIRouter(prefix='/engine-runs', tags=['engine-runs'])


@router.get('/compare', response_model=schemas.BuildComparisonResponse)
@handle_errors(operation='compare engine runs')
def compare_runs(
    run_a: str,
    run_b: str,
    datasource_id: str | None = None,
    session: Session = Depends(get_db),
):
    return service.compare_engine_runs(
        session,
        parse_engine_run_id(run_a),
        parse_engine_run_id(run_b),
        datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
    )


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
        analysis_id=parse_analysis_id(analysis_id) if analysis_id else None,
        datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
        kind=kind,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get('/{run_id}', response_model=schemas.EngineRunResponseSchema)
@handle_errors(operation='get engine run')
def get_run(run_id: EngineRunId, session: Session = Depends(get_db)):
    run = session.get(EngineRun, parse_engine_run_id(run_id))
    if not run:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail='Engine run not found')
    return schemas.EngineRunResponseSchema.model_validate(run)
