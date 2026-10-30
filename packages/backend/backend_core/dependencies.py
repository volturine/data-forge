from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from backend_core.api_execution_budget import run_api_blocking
from backend_core.auth_config import settings as auth_settings
from backend_core.database import run_settings_db
from modules.auth.dependencies import resolve_session_token
from modules.auth.service import get_default_user_id, validate_session


def _scope_lock_owner_id(owner_id: str, editor_client_id: str | None) -> str:
    if editor_client_id is None:
        return owner_id
    client_id = editor_client_id.strip()
    if not client_id or len(client_id) > 128:
        return owner_id
    return f'{owner_id}:{client_id}'


def resolve_lock_owner_id(
    session: Session,
    token: str | None,
    editor_client_id: str | None = None,
) -> str | None:
    if token:
        user = validate_session(session, token)
        if user is not None:
            return _scope_lock_owner_id(user.id, editor_client_id)
    if not auth_settings.auth_required:
        return _scope_lock_owner_id(get_default_user_id(), editor_client_id)
    return None


async def get_optional_lock_owner_id(request: Request) -> str | None:
    return await run_api_blocking(
        run_settings_db,
        resolve_lock_owner_id,
        resolve_session_token(request),
        request.headers.get('X-Editor-Client-Id'),
    )


async def get_lock_owner_id(
    owner_id: str | None = Depends(get_optional_lock_owner_id),
) -> str:
    if owner_id is not None:
        return owner_id
    raise HTTPException(status_code=401, detail='Lock owner identity is required')
