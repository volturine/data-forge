import logging

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlmodel import Session
from starlette.websockets import WebSocketState

from core.database import get_db, run_db, run_settings_db
from core.dependencies import get_lock_owner_id, resolve_lock_owner_id
from core.error_handlers import handle_errors
from core.namespace import get_namespace, reset_namespace, set_namespace_context
from modules.locks import schemas, service, watchers
from modules.mcp.router import MCPRouter

logger = logging.getLogger(__name__)

router = MCPRouter(prefix='/locks', tags=['locks'])


def _websocket_disconnected(websocket: WebSocket) -> bool:
    return websocket.client_state is WebSocketState.DISCONNECTED or websocket.application_state is WebSocketState.DISCONNECTED


def _is_disconnect_runtime_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return (
        'Cannot call "receive" once a disconnect message has been received' in message
        or 'Cannot call "send" once a close message has been sent' in message
        or 'Unexpected ASGI message "websocket.close"' in message
        or 'WebSocket is not connected. Need to call "accept" first.' in message
    )


async def _safe_close_websocket(websocket: WebSocket) -> None:
    if _websocket_disconnected(websocket):
        return
    try:
        await websocket.close()
    except RuntimeError as exc:
        if _is_disconnect_runtime_error(exc):
            return
        raise


async def _safe_send_json(websocket: WebSocket, payload: dict) -> bool:
    if _websocket_disconnected(websocket):
        return False
    try:
        await websocket.send_json(payload)
    except RuntimeError as exc:
        if _websocket_disconnected(websocket) or _is_disconnect_runtime_error(exc):
            return False
        raise
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


async def _get_websocket_owner_id(websocket: WebSocket) -> str | None:
    return await run_in_threadpool(run_settings_db, resolve_lock_owner_id, _resolve_websocket_session_token(websocket))


def _status_payload(resource_type: str, resource_id: str, lock: schemas.LockStatusResponse | None) -> dict:
    return schemas.LockWebsocketStatusMessage(
        resource_type=resource_type,
        resource_id=resource_id,
        lock=lock,
    ).model_dump(mode='json')


async def _send_status(websocket: WebSocket, resource_type: str, resource_id: str, lock: schemas.LockStatusResponse | None) -> None:
    await _safe_send_json(websocket, _status_payload(resource_type, resource_id, lock))


async def _send_error(websocket: WebSocket, error: str, status_code: int) -> None:
    await _safe_send_json(
        websocket,
        schemas.LockWebsocketErrorMessage(
            error=error,
            status_code=status_code,
        ).model_dump(mode='json'),
    )


async def _notify_watchers(resource_type: str, resource_id: str, lock: schemas.LockStatusResponse | None) -> None:
    payload = _status_payload(resource_type, resource_id, lock)
    stale: list[WebSocket] = []
    namespace = get_namespace()
    for websocket in await watchers.registry.sockets(namespace, resource_type, resource_id):
        try:
            sent = await _safe_send_json(websocket, payload)
        except Exception:
            stale.append(websocket)
            continue
        if not sent:
            stale.append(websocket)
    for websocket in stale:
        await watchers.registry.discard(websocket, namespace, resource_type, resource_id)


async def _lookup_lock_status(resource_type: str, resource_id: str) -> tuple[schemas.LockStatusResponse | None, bool]:
    return await run_in_threadpool(run_db, service.lookup_lock_status, resource_type, resource_id)


async def _heartbeat_lock(
    resource_type: str,
    resource_id: str,
    owner_id: str | None,
    lock_token: str,
    ttl_seconds: int | None,
) -> schemas.LockStatusResponse:
    if owner_id is None:
        raise HTTPException(status_code=401, detail='Lock owner identity is required')
    try:
        return await run_in_threadpool(
            run_db,
            service.heartbeat_lock,
            resource_type,
            resource_id,
            owner_id,
            lock_token,
            ttl_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _acquire_lock(
    resource_type: str,
    resource_id: str,
    owner_id: str | None,
    ttl_seconds: int | None,
) -> schemas.LockStatusResponse:
    if owner_id is None:
        raise HTTPException(status_code=401, detail='Lock owner identity is required')
    try:
        return await run_in_threadpool(
            run_db,
            service.acquire_lock,
            resource_type,
            resource_id,
            owner_id,
            ttl_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _release_lock(
    resource_type: str,
    resource_id: str,
    owner_id: str | None,
    lock_token: str,
) -> bool:
    if owner_id is None:
        raise HTTPException(status_code=401, detail='Lock owner identity is required')
    return await run_in_threadpool(
        run_db,
        service.release_lock,
        resource_type,
        resource_id,
        owner_id,
        lock_token,
    )


@router.post('', response_model=schemas.LockStatusResponse, mcp=True)
@handle_errors(operation='acquire lock', value_error_status=409)
async def acquire_lock(
    body: schemas.LockAcquireRequest,
    session: Session = Depends(get_db),
    owner_id: str = Depends(get_lock_owner_id),
) -> schemas.LockStatusResponse:
    lock = service.acquire_lock(session, body.resource_type, body.resource_id, owner_id, body.ttl_seconds)
    await _notify_watchers(body.resource_type, body.resource_id, lock)
    return lock


@router.get('/{resource_type}/{resource_id}', response_model=schemas.LockStatusResponse | None, mcp=True)
@handle_errors(operation='get lock status')
async def get_lock_status(
    resource_type: str,
    resource_id: str,
    session: Session = Depends(get_db),
) -> schemas.LockStatusResponse | None:
    lock, cleaned = service.lookup_lock_status(session, resource_type, resource_id)
    if cleaned:
        await _notify_watchers(resource_type, resource_id, None)
    return lock


@router.post('/{resource_type}/{resource_id}/heartbeat', response_model=schemas.LockStatusResponse, mcp=True)
@handle_errors(operation='heartbeat lock', value_error_status=409)
async def heartbeat_lock(
    resource_type: str,
    resource_id: str,
    body: schemas.LockHeartbeatRequest,
    session: Session = Depends(get_db),
    owner_id: str = Depends(get_lock_owner_id),
) -> schemas.LockStatusResponse:
    lock = service.heartbeat_lock(session, resource_type, resource_id, owner_id, body.lock_token, body.ttl_seconds)
    await _notify_watchers(resource_type, resource_id, lock)
    return lock


@router.delete('/{resource_type}/{resource_id}', response_model=schemas.LockReleaseResponse, mcp=True)
@handle_errors(operation='release lock')
async def release_lock(
    resource_type: str,
    resource_id: str,
    body: schemas.LockReleaseRequest,
    session: Session = Depends(get_db),
    owner_id: str = Depends(get_lock_owner_id),
) -> schemas.LockReleaseResponse:
    released = service.release_lock(session, resource_type, resource_id, owner_id, body.lock_token)
    if released:
        await _notify_watchers(resource_type, resource_id, None)
    return schemas.LockReleaseResponse(released=released)


@router.websocket('/ws')
async def lock_websocket(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    owner_id = await _get_websocket_owner_id(websocket)
    watch_type: str | None = None
    watch_id: str | None = None
    watch_token: str | None = None
    await websocket.accept()
    await _safe_send_json(websocket, schemas.LockWebsocketConnectedMessage().model_dump(mode='json'))
    try:
        while True:
            try:
                raw = await websocket.receive_json()
                message = schemas.LockWebsocketRequest.model_validate(raw)
            except ValidationError as exc:
                await _send_error(websocket, str(exc), 400)
                continue

            try:
                if message.action == schemas.LockWebsocketAction.WATCH:
                    next_type = message.resource_type
                    next_id = message.resource_id
                    next_token: str | None = None
                    assert next_type is not None
                    assert next_id is not None
                    if message.lock_token is not None:
                        lock = await _heartbeat_lock(
                            next_type,
                            next_id,
                            owner_id,
                            message.lock_token,
                            message.ttl_seconds,
                        )
                        next_token = message.lock_token
                        if watch_type is not None and watch_id is not None:
                            await watchers.registry.discard(websocket, namespace, watch_type, watch_id)
                        watch_type = next_type
                        watch_id = next_id
                        watch_token = next_token
                        await watchers.registry.add(websocket, namespace, watch_type, watch_id)
                        await _notify_watchers(watch_type, watch_id, lock)
                        continue
                    status, cleaned = await _lookup_lock_status(next_type, next_id)
                    if watch_type is not None and watch_id is not None:
                        await watchers.registry.discard(websocket, namespace, watch_type, watch_id)
                    watch_type = next_type
                    watch_id = next_id
                    watch_token = next_token
                    await watchers.registry.add(websocket, namespace, watch_type, watch_id)
                    if cleaned:
                        await _notify_watchers(watch_type, watch_id, None)
                        continue
                    if status is None:
                        await _send_status(websocket, watch_type, watch_id, None)
                        continue
                    await _send_status(websocket, watch_type, watch_id, status)
                    continue

                if message.action == schemas.LockWebsocketAction.ACQUIRE:
                    if watch_type is None or watch_id is None:
                        await _send_error(websocket, 'watch must be called before acquire', 400)
                        continue
                    lock = await _acquire_lock(
                        watch_type,
                        watch_id,
                        owner_id,
                        message.ttl_seconds,
                    )
                    watch_token = lock.lock_token
                    await _notify_watchers(watch_type, watch_id, lock)
                    continue

                if message.action == schemas.LockWebsocketAction.RELEASE:
                    if watch_type is None or watch_id is None:
                        await _send_error(websocket, 'watch must be called before release', 400)
                        continue
                    token_value = message.lock_token or watch_token
                    if token_value is None:
                        status, cleaned = await _lookup_lock_status(watch_type, watch_id)
                        if cleaned:
                            watch_token = None
                            await _notify_watchers(watch_type, watch_id, None)
                            continue
                        if status is None:
                            watch_token = None
                        await _send_status(websocket, watch_type, watch_id, status)
                        continue
                    released = await _release_lock(
                        watch_type,
                        watch_id,
                        owner_id,
                        token_value,
                    )
                    if released:
                        watch_token = None
                        await _notify_watchers(watch_type, watch_id, None)
                        continue
                    status, cleaned = await _lookup_lock_status(watch_type, watch_id)
                    if cleaned:
                        watch_token = None
                        await _notify_watchers(watch_type, watch_id, None)
                        continue
                    if status is None:
                        watch_token = None
                    await _send_status(websocket, watch_type, watch_id, status)
                    continue

                if watch_type is None or watch_id is None:
                    await _send_error(websocket, 'watch must be called before ping', 400)
                    continue

                token_value = message.lock_token or watch_token
                if token_value is not None:
                    lock = await _heartbeat_lock(
                        watch_type,
                        watch_id,
                        owner_id,
                        token_value,
                        message.ttl_seconds,
                    )
                    watch_token = token_value
                    await _notify_watchers(watch_type, watch_id, lock)
                    continue

                status, cleaned = await _lookup_lock_status(watch_type, watch_id)
                if cleaned:
                    await _notify_watchers(watch_type, watch_id, None)
                    continue
                if status is None:
                    await _send_status(websocket, watch_type, watch_id, None)
                    continue
                await _send_status(websocket, watch_type, watch_id, status)
            except HTTPException as exc:
                await _send_error(websocket, str(exc.detail), exc.status_code)
    except WebSocketDisconnect:
        return
    except RuntimeError as exc:
        if _is_disconnect_runtime_error(exc):
            return
        logger.error('Lock websocket error: %s', exc, exc_info=True)
        await _send_error(websocket, 'An internal error occurred', 500)
    except Exception as exc:
        logger.error('Lock websocket error: %s', exc, exc_info=True)
        await _send_error(websocket, 'An internal error occurred', 500)
    finally:
        if watch_type is not None and watch_id is not None:
            await watchers.registry.discard(websocket, namespace, watch_type, watch_id)
        if watch_type is not None and watch_id is not None and watch_token is not None and owner_id is not None:
            released = await _release_lock(watch_type, watch_id, owner_id, watch_token)
            if released:
                await _notify_watchers(watch_type, watch_id, None)
        reset_namespace(token)
        await _safe_close_websocket(websocket)
