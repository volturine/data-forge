from core.database import get_settings_db, run_settings_db
from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from backend_core.auth_config import settings as auth_settings
from modules.auth.models import User
from modules.auth.service import ensure_default_user, get_default_user_id, validate_session


def _resolve_session_token(request: Request) -> str | None:
    cookie_token = request.cookies.get("session_token")
    if cookie_token:
        return cookie_token
    header_token = request.headers.get("X-Session-Token")
    if header_token:
        return header_token
    return None


def get_current_user(request: Request, session: Session = Depends(get_settings_db)) -> User:
    token = _resolve_session_token(request)
    if token:
        user = validate_session(session, token)
        if user:
            return user
    if not auth_settings.auth_required:
        return ensure_default_user(session)
    raise HTTPException(status_code=401, detail="Not authenticated")


def get_optional_user(request: Request, session: Session = Depends(get_settings_db)) -> User | None:
    token = _resolve_session_token(request)
    if token:
        user = validate_session(session, token)
        if user:
            return user
    if not auth_settings.auth_required:
        return ensure_default_user(session)
    return None


def get_optional_user_id(request: Request) -> str | None:
    token = _resolve_session_token(request)
    if token:
        user = run_settings_db(lambda session: validate_session(session, token))
        if user:
            return user.id
    if not auth_settings.auth_required:
        return get_default_user_id()
    return None


def get_current_user_id(user_id: str | None = Depends(get_optional_user_id)) -> str:
    if user_id is not None:
        return user_id
    raise HTTPException(status_code=401, detail="Not authenticated")
