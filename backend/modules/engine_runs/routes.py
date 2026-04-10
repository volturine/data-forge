import logging

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlmodel import Session
from starlette.websockets import WebSocketState

from core.database import get_db
from core.error_handlers import handle_errors
from core.namespace import get_namespace, reset_namespace, set_namespace_context
from core.validation import EngineRunId, parse_analysis_id, parse_datasource_id, parse_engine_run_id
from modules.engine_runs import schemas, service, watchers
from modules.engine_runs.schemas import EngineRunKind, EngineRunStatus
from modules.mcp.router import MCPRouter

logger = logging.getLogger(__name__)

router = MCPRouter(prefix='/engine-runs', tags=['engine-runs'])


async def _safe_close_websocket(websocket: WebSocket) -> None:
    if websocket.client_state is WebSocketState.DISCONNECTED:
        return
    if websocket.application_state is WebSocketState.DISCONNECTED:
        return
    try:
        await websocket.close()
    except RuntimeError:
        return


def _parse_list_params(websocket: WebSocket) -> schemas.EngineRunListParams:
    params = schemas.EngineRunListParams.model_validate(dict(websocket.query_params))
    if params.analysis_id is not None:
        params.analysis_id = parse_analysis_id(params.analysis_id)
    if params.datasource_id is not None:
        params.datasource_id = parse_datasource_id(params.datasource_id)
    return params


async def _send_websocket_error(websocket: WebSocket, error: str, status_code: int) -> None:
    if websocket.client_state is WebSocketState.DISCONNECTED:
        return
    if websocket.application_state is WebSocketState.DISCONNECTED:
        return
    try:
        await websocket.send_json(schemas.EngineRunWebsocketErrorMessage(error=error, status_code=status_code).model_dump(mode='json'))
    except RuntimeError:
        return
    except WebSocketDisconnect:
        return


@router.get('/compare', response_model=schemas.BuildComparisonResponse, mcp=True)
@handle_errors(operation='compare engine runs')
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


@router.get('', response_model=list[schemas.EngineRunResponseSchema], mcp=True)
@handle_errors(operation='list engine runs')
def list_runs(
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: EngineRunKind | None = None,
    status: EngineRunStatus | None = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_db),
):
    """List engine runs with optional filters.

    Filters: analysis_id, datasource_id, kind (preview/row_count/download/datasource_create/datasource_update),
    status (success/failed). Supports pagination via limit/offset.
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


@router.get('/{run_id}', response_model=schemas.EngineRunResponseSchema, mcp=True)
@handle_errors(operation='get engine run')
def get_run(run_id: EngineRunId, session: Session = Depends(get_db)):
    """Get a single engine run by ID with full request/result JSON and step timings."""
    run = service.get_engine_run(session, parse_engine_run_id(run_id))
    if not run:
        raise HTTPException(status_code=404, detail='Engine run not found')
    return run


@router.websocket('/ws')
async def engine_run_list_websocket(websocket: WebSocket) -> None:
    token = None
    watch: watchers.EngineRunWatch | None = None
    await websocket.accept()
    try:
        token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
        watch = watchers.EngineRunWatch.from_params(get_namespace(), _parse_list_params(websocket))
        await watchers.registry.add(websocket, watch)
        await websocket.send_json((await watchers.registry.snapshot(watch)).model_dump(mode='json'))
        while True:
            await websocket.receive()
    except ValidationError as exc:
        await _send_websocket_error(websocket, str(exc), 400)
    except ValueError as exc:
        await _send_websocket_error(websocket, str(exc), 400)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.error('Engine run websocket error: %s', exc, exc_info=True)
        await _send_websocket_error(websocket, 'An internal error occurred', 500)
    finally:
        if watch is not None:
            await watchers.registry.discard(websocket, watch)
        if token is not None:
            reset_namespace(token)
        await _safe_close_websocket(websocket)
