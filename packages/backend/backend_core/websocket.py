from __future__ import annotations

import asyncio
import json
from weakref import WeakKeyDictionary

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from pydantic import BaseModel

from backend_core.api_execution_budget import run_api_blocking

_DISCONNECT_RUNTIME_ERRORS = (
    'Cannot call "receive" once a disconnect message has been received',
    'Cannot call "send" once a close message has been sent',
    'Unexpected ASGI message "websocket.close"',
    'WebSocket is not connected. Need to call "accept" first.',
)

_WEBSOCKET_SEND_LOCKS: WeakKeyDictionary[WebSocket, asyncio.Lock] = WeakKeyDictionary()


def _serialize_json(payload: object) -> str:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode='json')
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


async def serialize_json(payload: object) -> str:
    return await run_api_blocking(_serialize_json, payload)


def websocket_disconnected(websocket: WebSocket) -> bool:
    return websocket.client_state is WebSocketState.DISCONNECTED or websocket.application_state is WebSocketState.DISCONNECTED


def is_disconnect_runtime_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return any(fragment in message for fragment in _DISCONNECT_RUNTIME_ERRORS)


async def safe_close_websocket(websocket: WebSocket) -> None:
    if websocket_disconnected(websocket):
        return
    try:
        async with _send_lock_for(websocket):
            if websocket_disconnected(websocket):
                return
            await websocket.close()
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        raise


def _send_lock_for(websocket: WebSocket) -> asyncio.Lock:
    send_lock = _WEBSOCKET_SEND_LOCKS.get(websocket)
    if send_lock is None:
        send_lock = asyncio.Lock()
        _WEBSOCKET_SEND_LOCKS[websocket] = send_lock
    return send_lock


async def _send_serialized_json(websocket: WebSocket, serialized: str) -> bool:
    try:
        if websocket_disconnected(websocket):
            return False
        await websocket.send_text(serialized)
    except RuntimeError as exc:
        if websocket_disconnected(websocket) or is_disconnect_runtime_error(exc):
            return False
        raise
    except WebSocketDisconnect:
        return False
    return True


async def safe_send_json(websocket: WebSocket, payload: dict[str, object] | BaseModel) -> bool:
    if websocket_disconnected(websocket):
        return False
    try:
        async with _send_lock_for(websocket):
            if websocket_disconnected(websocket):
                return False
            serialized = await serialize_json(payload)
            return await _send_serialized_json(websocket, serialized)
    except RuntimeError as exc:
        if websocket_disconnected(websocket) or is_disconnect_runtime_error(exc):
            return False
        raise


async def safe_send_json_error(websocket: WebSocket, payload: dict[str, object] | BaseModel) -> bool:
    """Send a small terminal error frame without depending on the API thread pool."""
    if websocket_disconnected(websocket):
        return False
    try:
        async with _send_lock_for(websocket):
            if websocket_disconnected(websocket):
                return False
            return await _send_serialized_json(websocket, _serialize_json(payload))
    except RuntimeError as exc:
        if websocket_disconnected(websocket) or is_disconnect_runtime_error(exc):
            return False
        raise


async def safe_send_serialized_json(websocket: WebSocket, serialized: str) -> bool:
    if websocket_disconnected(websocket):
        return False
    try:
        async with _send_lock_for(websocket):
            return await _send_serialized_json(websocket, serialized)
    except RuntimeError as exc:
        if websocket_disconnected(websocket) or is_disconnect_runtime_error(exc):
            return False
        raise


def resolve_websocket_session_token(websocket: WebSocket) -> str | None:
    cookie_token = websocket.cookies.get('session_token')
    if cookie_token:
        return cookie_token
    header_token = websocket.headers.get('X-Session-Token')
    if header_token:
        return header_token
    return None
