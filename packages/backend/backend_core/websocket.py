from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

_DISCONNECT_RUNTIME_ERRORS = (
    'Cannot call "receive" once a disconnect message has been received',
    'Cannot call "send" once a close message has been sent',
    'Unexpected ASGI message "websocket.close"',
    'WebSocket is not connected. Need to call "accept" first.',
)


def websocket_disconnected(websocket: WebSocket) -> bool:
    return websocket.client_state is WebSocketState.DISCONNECTED or websocket.application_state is WebSocketState.DISCONNECTED


def is_disconnect_runtime_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return any(fragment in message for fragment in _DISCONNECT_RUNTIME_ERRORS)


async def safe_close_websocket(websocket: WebSocket) -> None:
    if websocket_disconnected(websocket):
        return
    try:
        await websocket.close()
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        raise


async def safe_send_json(websocket: WebSocket, payload: dict) -> bool:
    if websocket_disconnected(websocket):
        return False
    try:
        await websocket.send_json(payload)
    except RuntimeError as exc:
        if websocket_disconnected(websocket) or is_disconnect_runtime_error(exc):
            return False
        raise
    except WebSocketDisconnect:
        return False
    return True


def resolve_websocket_session_token(websocket: WebSocket) -> str | None:
    cookie_token = websocket.cookies.get("session_token")
    if cookie_token:
        return cookie_token
    header_token = websocket.headers.get("X-Session-Token")
    if header_token:
        return header_token
    return None
