import asyncio

from fastapi import Depends, HTTPException, Request
from starlette.requests import HTTPConnection

from backend_core.auth_config import settings as auth_settings
from backend_core.database import run_settings_db
from modules.auth.models import User
from modules.auth.service import ensure_default_user, get_default_user_id, validate_session


def _resolve_session_token(request: HTTPConnection) -> str | None:
    cookie_token = request.cookies.get('session_token')
    if cookie_token:
        return cookie_token
    header_token = request.headers.get('X-Session-Token')
    if header_token:
        return header_token
    return None


async def _resolve_user(request: HTTPConnection) -> User | None:
    token = _resolve_session_token(request)
    if token:
        user = await asyncio.to_thread(run_settings_db, validate_session, token)
        if user:
            return user
    if not auth_settings.auth_required:
        return await asyncio.to_thread(run_settings_db, ensure_default_user)
    return None


async def get_current_user(request: HTTPConnection) -> User | None:
    # WebSocket routes authenticate after accepting the connection so they can
    # send a protocol-level rejection over the socket.
    if request.scope['type'] == 'websocket':
        return None
    user = await _resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return user


async def get_optional_user(request: Request) -> User | None:
    return await _resolve_user(request)


async def get_optional_user_id(request: Request) -> str | None:
    token = _resolve_session_token(request)
    if token:
        user = await asyncio.to_thread(run_settings_db, validate_session, token)
        if user:
            return user.id
    if not auth_settings.auth_required:
        return get_default_user_id()
    return None


async def get_current_user_id(user_id: str | None = Depends(get_optional_user_id)) -> str:
    if user_id is not None:
        return user_id
    raise HTTPException(status_code=401, detail='Not authenticated')
