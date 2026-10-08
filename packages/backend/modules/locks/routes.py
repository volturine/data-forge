import asyncio
import logging
from collections.abc import Callable

import anyio
from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend_core import runtime_ipc
from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_db, run_settings_db
from backend_core.dependencies import get_lock_owner_id, resolve_lock_owner_id
from backend_core.error_handlers import handle_errors
from backend_core.namespace import get_namespace, reset_namespace, set_namespace_context
from backend_core.websocket import (
    is_disconnect_runtime_error,
    resolve_websocket_session_token,
    safe_close_websocket,
    safe_send_json,
)
from modules.locks import schemas, service, watchers
from modules.mcp.router import MCPRouter

logger = logging.getLogger(__name__)


async def _run_lock[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    return await run_api_blocking(function, *args, **kwargs)


router = MCPRouter(prefix='/locks', tags=['locks'])


async def _get_websocket_owner_id(websocket: WebSocket) -> str | None:
    return await _run_lock(
        run_settings_db,
        resolve_lock_owner_id,
        resolve_websocket_session_token(websocket),
        websocket.query_params.get('editor_client_id'),
    )


async def _require_websocket_user(websocket: WebSocket) -> str:
    owner_id = await _get_websocket_owner_id(websocket)
    if owner_id is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return owner_id


def _status_message(resource_type: str, resource_id: str, lock: schemas.LockStatusResponse | None) -> schemas.LockWebsocketStatusMessage:
    return schemas.LockWebsocketStatusMessage(
        resource_type=resource_type,
        resource_id=resource_id,
        lock=lock,
    )


async def _send_status(
    websocket: WebSocket,
    resource_type: str,
    resource_id: str,
    lock: schemas.LockStatusResponse | None,
) -> None:
    await safe_send_json(websocket, _status_message(resource_type, resource_id, lock))


async def _send_error(websocket: WebSocket, error: str, status_code: int) -> None:
    await safe_send_json(
        websocket,
        schemas.LockWebsocketErrorMessage(
            error=error,
            status_code=status_code,
        ),
    )


async def _notify_watchers(resource_type: str, resource_id: str, lock: schemas.LockStatusResponse | None) -> None:
    payload = _status_message(resource_type, resource_id, lock)
    namespace = get_namespace()
    await watchers.notify_watchers(namespace, resource_type, resource_id, payload)
    # The local websockets are already notified above. The database NOTIFY
    # round trip reaches every other API process and replica that owns a
    # websocket for this namespace; PostgreSQL is the only shared state, so
    # the publish never depends on a deployment flag.
    try:
        await _run_lock(
            runtime_ipc.notify_api_lock,
            namespace,
            resource_type,
            resource_id,
            payload,
        )
    except Exception:
        logger.warning(
            'Failed to publish cross-process lock update for %s %s',
            resource_type,
            resource_id,
            exc_info=True,
        )


async def _lookup_lock_status(resource_type: str, resource_id: str) -> tuple[schemas.LockStatusResponse | None, bool]:
    return await _run_lock(run_db, service.lookup_lock_status, resource_type, resource_id)


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
        return await _run_lock(
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
    *,
    on_acquired: Callable[[schemas.LockStatusResponse], None] | None = None,
) -> schemas.LockStatusResponse:
    if owner_id is None:
        raise HTTPException(status_code=401, detail='Lock owner identity is required')
    try:
        # asyncio.to_thread cannot stop a database transaction after the
        # websocket task is cancelled. Keep the result shielded until its
        # token is recorded, or the finally block could not release a lock
        # that committed just before cancellation.
        with anyio.CancelScope(shield=True):
            acquisition = asyncio.create_task(
                _run_lock(
                    run_db,
                    service.acquire_lock,
                    resource_type,
                    resource_id,
                    owner_id,
                    ttl_seconds,
                )
            )
            try:
                lock = await asyncio.shield(acquisition)
            except asyncio.CancelledError as cancellation:
                while not acquisition.done():
                    try:
                        await asyncio.shield(acquisition)
                    except asyncio.CancelledError:
                        continue
                try:
                    lock = acquisition.result()
                except BaseException:
                    raise cancellation
                if on_acquired is not None:
                    on_acquired(lock)
                raise cancellation
            if on_acquired is not None:
                on_acquired(lock)
        return lock
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
    return await _run_lock(
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
    owner_id: str = Depends(get_lock_owner_id),
) -> schemas.LockStatusResponse:
    lock = await _run_lock(
        run_db,
        service.acquire_lock,
        body.resource_type,
        body.resource_id,
        owner_id,
        body.ttl_seconds,
    )
    await _notify_watchers(body.resource_type, body.resource_id, lock)
    return lock


@router.get(
    '/{resource_type}/{resource_id}',
    response_model=schemas.LockStatusResponse | None,
    mcp=True,
    dependencies=[Depends(get_lock_owner_id)],
)
@handle_errors(operation='get lock status')
async def get_lock_status(
    resource_type: str,
    resource_id: str,
) -> schemas.LockStatusResponse | None:
    lock, cleaned = await _lookup_lock_status(resource_type, resource_id)
    if cleaned:
        await _notify_watchers(resource_type, resource_id, None)
    return lock


@router.post(
    '/{resource_type}/{resource_id}/heartbeat',
    response_model=schemas.LockStatusResponse,
    mcp=True,
)
@handle_errors(operation='heartbeat lock', value_error_status=409)
async def heartbeat_lock(
    resource_type: str,
    resource_id: str,
    body: schemas.LockHeartbeatRequest,
    owner_id: str = Depends(get_lock_owner_id),
) -> schemas.LockStatusResponse:
    lock = await _run_lock(
        run_db,
        service.heartbeat_lock,
        resource_type,
        resource_id,
        owner_id,
        body.lock_token,
        body.ttl_seconds,
    )
    await _notify_watchers(resource_type, resource_id, lock)
    return lock


@router.delete(
    '/{resource_type}/{resource_id}',
    response_model=schemas.LockReleaseResponse,
    mcp=True,
)
@handle_errors(operation='release lock')
async def release_lock(
    resource_type: str,
    resource_id: str,
    body: schemas.LockReleaseRequest,
    owner_id: str = Depends(get_lock_owner_id),
) -> schemas.LockReleaseResponse:
    released = await _run_lock(
        run_db,
        service.release_lock,
        resource_type,
        resource_id,
        owner_id,
        body.lock_token,
    )
    if released:
        await _notify_watchers(resource_type, resource_id, None)
    return schemas.LockReleaseResponse(released=released)


@router.websocket('/ws')
async def lock_websocket(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    # Accept before doing the database lookup. Navigation can close a socket
    # while authentication is still pending; sending the initial message from
    # the CONNECTING state then turns an ordinary disconnect into a 500.
    await websocket.accept()
    owner_id: str | None = None
    watch_type: str | None = None
    watch_id: str | None = None
    watch_token: str | None = None
    try:
        owner_id = await _require_websocket_user(websocket)
        await safe_send_json(websocket, schemas.LockWebsocketConnectedMessage())
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
                        switching = (watch_type, watch_id) != (next_type, next_id)
                        await watchers.registry.add(websocket, namespace, next_type, next_id)
                        try:
                            lock = await _heartbeat_lock(next_type, next_id, owner_id, message.lock_token, message.ttl_seconds)
                        except BaseException:
                            if switching:
                                with anyio.CancelScope(shield=True):
                                    await watchers.registry.discard(websocket, namespace, next_type, next_id)
                            raise
                        next_token = message.lock_token
                        if switching and watch_type is not None and watch_id is not None:
                            await watchers.registry.discard(websocket, namespace, watch_type, watch_id)
                        watch_type = next_type
                        watch_id = next_id
                        watch_token = next_token
                        await _notify_watchers(watch_type, watch_id, lock)
                        continue
                    if watch_type is not None and watch_id is not None:
                        await watchers.registry.discard(websocket, namespace, watch_type, watch_id)
                    watch_type = next_type
                    watch_id = next_id
                    watch_token = next_token
                    await watchers.registry.add(websocket, namespace, watch_type, watch_id)
                    version = await watchers.registry.current_version(namespace, watch_type, watch_id)
                    status, cleaned = await _lookup_lock_status(next_type, next_id)
                    if cleaned:
                        if await watchers.registry.current_version(namespace, watch_type, watch_id) != version:
                            status, _cleaned = await _lookup_lock_status(watch_type, watch_id)
                        await _notify_watchers(watch_type, watch_id, status)
                        continue
                    await watchers.refresh_watchers(namespace, watch_type, watch_id, _status_message(watch_type, watch_id, status), expected_version=version)
                    continue

                if message.action == schemas.LockWebsocketAction.ACQUIRE:
                    if watch_type is None or watch_id is None:
                        await _send_error(websocket, 'watch must be called before acquire', 400)
                        continue

                    def remember_acquired_lock(lock: schemas.LockStatusResponse) -> None:
                        nonlocal watch_token
                        watch_token = lock.lock_token

                    lock = await _acquire_lock(
                        watch_type,
                        watch_id,
                        owner_id,
                        message.ttl_seconds,
                        on_acquired=remember_acquired_lock,
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
                    if lock.lock_token != token_value:
                        # This socket's token was rotated. Tell it the live lock
                        # without adopting that token, so disconnect cannot release it.
                        await _send_status(websocket, watch_type, watch_id, lock)
                        continue
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
    except HTTPException as exc:
        await _send_error(websocket, str(exc.detail), exc.status_code)
    except WebSocketDisconnect:
        return
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        logger.error('Lock websocket error: %s', exc, exc_info=True)
        await _send_error(websocket, 'An internal error occurred', 500)
    except Exception as exc:
        logger.error('Lock websocket error: %s', exc, exc_info=True)
        await _send_error(websocket, 'An internal error occurred', 500)
    finally:
        # A server can cancel a websocket task immediately after delivering a
        # disconnect. Keep ownership cleanup alive so a lock is not left until
        # its TTL merely because the disconnect raced the handler shutdown.
        with anyio.CancelScope(shield=True):
            if watch_type is not None and watch_id is not None:
                await watchers.registry.discard(websocket, namespace, watch_type, watch_id)
            if watch_type is not None and watch_id is not None and watch_token is not None and owner_id is not None:
                released = await _release_lock(watch_type, watch_id, owner_id, watch_token)
                if released:
                    await _notify_watchers(watch_type, watch_id, None)
            reset_namespace(token)
            await safe_close_websocket(websocket)
