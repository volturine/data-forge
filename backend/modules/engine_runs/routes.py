import asyncio
import logging

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlmodel import Session
from starlette.websockets import WebSocketState

from core.database import get_db
from core.error_handlers import handle_errors
from core.namespace import get_namespace, reset_namespace, set_namespace_context
from core.validation import EngineRunId, parse_analysis_id, parse_datasource_id, parse_engine_run_id
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
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


async def _safe_send_json(websocket: WebSocket, payload: dict) -> bool:
    if websocket.client_state is WebSocketState.DISCONNECTED:
        return False
    if websocket.application_state is WebSocketState.DISCONNECTED:
        return False
    try:
        await websocket.send_json(payload)
    except RuntimeError:
        return False
    except WebSocketDisconnect:
        return False
    return True


def _resolve_websocket_session_token(websocket: WebSocket) -> str | None:
    cookie_token = websocket.cookies.get('session_token')
    if cookie_token:
        return cookie_token
    header_token = websocket.headers.get('X-Session-Token')
    if header_token:
        return header_token
    return None


def _resolve_websocket_user(websocket: WebSocket) -> User | None:
    override = websocket.app.dependency_overrides.get(get_current_user)
    if override is not None:
        return override()

    from core.database import run_settings_db
    from modules.auth.service import ensure_default_user, validate_session

    token = _resolve_websocket_session_token(websocket)

    def _lookup(session: Session) -> User | None:
        if token:
            return validate_session(session, token)
        from core.config import settings

        if not settings.auth_required:
            return ensure_default_user(session)
        return None

    return run_settings_db(_lookup)


async def _require_websocket_user(websocket: WebSocket) -> User:
    user = await run_in_threadpool(_resolve_websocket_user, websocket)
    if user is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return user


def _list_params(
    *,
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: EngineRunKind | None = None,
    status: EngineRunStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> schemas.EngineRunListParams:
    return schemas.EngineRunListParams(
        analysis_id=parse_analysis_id(analysis_id) if analysis_id else None,
        datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
        kind=kind,
        status=status,
        limit=limit,
        offset=offset,
    )


def _parse_list_params(websocket: WebSocket) -> schemas.EngineRunListParams:
    raw_limit = websocket.query_params.get('limit')
    raw_offset = websocket.query_params.get('offset')
    params = schemas.EngineRunListParams.model_validate(
        {
            'analysis_id': websocket.query_params.get('analysis_id') or None,
            'datasource_id': websocket.query_params.get('datasource_id') or None,
            'kind': websocket.query_params.get('kind') or None,
            'status': websocket.query_params.get('status') or None,
            'limit': int(raw_limit) if raw_limit is not None else 100,
            'offset': int(raw_offset) if raw_offset is not None else 0,
        }
    )
    if params.analysis_id:
        params.analysis_id = parse_analysis_id(params.analysis_id)
    if params.datasource_id:
        params.datasource_id = parse_datasource_id(params.datasource_id)
    return params


@router.websocket('/ws')
async def engine_run_list_stream(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        params = _parse_list_params(websocket)
        watchers.registry.add(namespace, websocket, loop=asyncio.get_running_loop(), params=params)
        session_gen = get_db()
        session = next(session_gen)
        try:
            runs = service.list_engine_runs(
                session=session,
                analysis_id=params.analysis_id,
                datasource_id=params.datasource_id,
                kind=params.kind,
                status=params.status,
                limit=params.limit,
                offset=params.offset,
            )
        finally:
            session.close()
            session_gen.close()
        await _safe_send_json(websocket, schemas.EngineRunListSnapshotMessage(runs=runs).model_dump(mode='json'))
        watchers.registry.set_run_ids(namespace, websocket, tuple(run.id for run in runs))
        while True:
            await asyncio.sleep(3600)
    except WebSocketDisconnect:
        return
    except ValidationError as exc:
        await _safe_send_json(
            websocket,
            schemas.EngineRunWebsocketErrorMessage(error=str(exc), status_code=400).model_dump(mode='json'),
        )
    except ValueError as exc:
        await _safe_send_json(
            websocket,
            schemas.EngineRunWebsocketErrorMessage(error=str(exc), status_code=400).model_dump(mode='json'),
        )
    except HTTPException as exc:
        await _safe_send_json(
            websocket,
            schemas.EngineRunWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code).model_dump(mode='json'),
        )
    except Exception as exc:
        logger.error('Engine run websocket error: %s', exc, exc_info=True)
        await _safe_send_json(
            websocket,
            schemas.EngineRunWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    finally:
        watchers.registry.discard(namespace, websocket)
        reset_namespace(token)
        await _safe_close_websocket(websocket)


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
    params = _list_params(
        analysis_id=analysis_id,
        datasource_id=datasource_id,
        kind=kind,
        status=status,
        limit=limit,
        offset=offset,
    )
    return service.list_engine_runs(
        session=session,
        analysis_id=params.analysis_id,
        datasource_id=params.datasource_id,
        kind=params.kind,
        status=params.status,
        limit=params.limit,
        offset=params.offset,
    )


@router.get('/{run_id}', response_model=schemas.EngineRunResponseSchema, mcp=True)
@handle_errors(operation='get engine run')
def get_run(run_id: EngineRunId, session: Session = Depends(get_db)):
    """Get a single engine run by ID with full request/result JSON and step timings."""
    run = service.get_engine_run(session, parse_engine_run_id(run_id))
    if not run:
        raise HTTPException(status_code=404, detail='Engine run not found')
    return run
