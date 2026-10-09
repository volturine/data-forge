from fastapi import HTTPException

from backend_core import compute_worker_runs_service as service
from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_db
from backend_core.domain.compute_worker_runs import schemas
from backend_core.domain.compute_worker_runs.schemas import ComputeWorkerRunKind, ComputeWorkerRunStatus
from backend_core.error_handlers import handle_errors
from backend_core.validation import (
    ComputeWorkerRunId,
    parse_analysis_id,
    parse_compute_worker_run_id,
    parse_datasource_id,
)
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/compute-worker-runs', tags=['compute-worker-runs'])


@router.get('/compare', response_model=schemas.BuildComparisonResponse, mcp=True)
@handle_errors(operation='compare compute worker runs')
async def compare_runs(
    run_a: str,
    run_b: str,
    datasource_id: str | None = None,
):
    """Compare two compute worker runs side-by-side: row counts, schema changes, and step timing deltas.

    Requires run_a and run_b (compute worker run IDs from GET /compute-worker-runs).
    Optionally filter by datasource_id.
    """
    return await run_api_blocking(
        run_db,
        service.compare_compute_worker_runs,
        parse_compute_worker_run_id(run_a),
        parse_compute_worker_run_id(run_b),
        datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
    )


@router.get('/stats', response_model=schemas.DurationStatsResponse, mcp=True)
@handle_errors(operation='get duration stats')
async def duration_stats(
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: ComputeWorkerRunKind | None = None,
    limit: int = 20,
):
    """Duration aggregates for the last N terminal runs (avg, p50, p95, trend).

    For kind=BUILD (default when omitted), uses build_runs. Other kinds use compute_worker_runs.
    """
    return await run_api_blocking(
        run_db,
        service.duration_stats,
        analysis_id=parse_analysis_id(analysis_id) if analysis_id else None,
        datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
        kind=kind,
        limit=limit,
    )


@router.get('', response_model=list[schemas.ComputeWorkerRunResponseSchema], mcp=True)
@handle_errors(operation='list compute worker runs')
async def list_runs(
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: ComputeWorkerRunKind | None = None,
    status: ComputeWorkerRunStatus | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List compute worker runs with optional filters.

    Filters: analysis_id, datasource_id, kind (preview/row_count/download),
    status (success/failed/cancelled/running). Supports pagination via limit/offset.
    """
    return await run_api_blocking(
        run_db,
        service.list_compute_worker_runs,
        analysis_id=parse_analysis_id(analysis_id) if analysis_id else None,
        datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
        kind=kind,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get('/{run_id}', response_model=schemas.ComputeWorkerRunResponseSchema, mcp=True)
@handle_errors(operation='get compute worker run')
async def get_run(run_id: ComputeWorkerRunId):
    """Get a single compute worker run by ID with full request/result JSON and step timings."""
    run = await run_api_blocking(run_db, service.get_compute_worker_run, parse_compute_worker_run_id(run_id))
    if not run:
        raise HTTPException(status_code=404, detail='Compute worker run not found')
    return run
