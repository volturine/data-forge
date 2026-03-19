from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import EngineRunId, parse_analysis_id, parse_datasource_id, parse_engine_run_id
from modules.engine_runs import schemas, service
from modules.engine_runs.models import EngineRun
from modules.mcp.decorators import deterministic_tool

router = APIRouter(prefix='/engine-runs', tags=['engine-runs'])


@router.get('/compare', response_model=schemas.BuildComparisonResponse)
@handle_errors(operation='compare engine runs')
@deterministic_tool
def compare_runs(
    run_a: str,
    run_b: str,
    datasource_id: str | None = None,
    session: Session = Depends(get_db),
):
    """Compare two engine runs side-by-side: row counts, schema changes, and step timing deltas.

    Requires run_a and run_b (engine run IDs from GET /engine-runs).
    Optionally filter by datasource_id.
    """
    return service.compare_engine_runs(
        session,
        parse_engine_run_id(run_a),
        parse_engine_run_id(run_b),
        datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
    )


@router.get('', response_model=list[schemas.EngineRunResponseSchema])
@handle_errors(operation='list engine runs')
@deterministic_tool
def list_runs(
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_db),
):
    """List engine runs with optional filters.

    Filters: analysis_id, datasource_id, kind (preview/export/datasource_update),
    status (pending/running/success/failed). Supports pagination via limit/offset.
    """
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
@deterministic_tool
def get_run(run_id: EngineRunId, session: Session = Depends(get_db)):
    """Get a single engine run by ID with full request/result JSON and step timings."""
    run = session.get(EngineRun, parse_engine_run_id(run_id))
    if not run:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail='Engine run not found')
    return schemas.EngineRunResponseSchema.model_validate(run)
