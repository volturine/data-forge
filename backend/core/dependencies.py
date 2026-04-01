from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from core.config import settings
from core.database import get_settings_db
from modules.auth.dependencies import _resolve_session_token
from modules.auth.service import ensure_default_user, validate_session

if TYPE_CHECKING:
    from modules.compute.manager import ProcessManager


def get_manager(request: Request) -> ProcessManager:
    """FastAPI dependency that returns the ProcessManager from app state."""
    return request.app.state.manager


def resolve_lock_owner_id(session: Session, token: str | None) -> str | None:
    if token:
        user = validate_session(session, token)
        if user is not None:
            return user.id
    if not settings.auth_required:
        return ensure_default_user(session).id
    return None


def get_optional_lock_owner_id(
    request: Request,
    session: Session = Depends(get_settings_db),
) -> str | None:
    return resolve_lock_owner_id(session, _resolve_session_token(request))


def get_lock_owner_id(owner_id: str | None = Depends(get_optional_lock_owner_id)) -> str:
    if owner_id is not None:
        return owner_id
    raise HTTPException(status_code=401, detail='Lock owner identity is required')
