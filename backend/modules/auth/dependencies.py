from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from core.config import settings
from core.database import get_settings_db
from modules.auth.models import User
from modules.auth.service import ensure_default_user, validate_session


def _resolve_session_token(request: Request) -> str | None:
    cookie_token = request.cookies.get('session_token')
    if cookie_token:
        return cookie_token
    header_token = request.headers.get('X-Session-Token')
    if header_token:
        return header_token
    return None


def get_current_user(request: Request, session: Session = Depends(get_settings_db)) -> User:
    token = _resolve_session_token(request)
    if token:
        user = validate_session(session, token)
        if user:
            return user
    if not settings.auth_required:
        return ensure_default_user(session)
    raise HTTPException(status_code=401, detail='Not authenticated')


def get_optional_user(request: Request, session: Session = Depends(get_settings_db)) -> User | None:
    token = _resolve_session_token(request)
    if token:
        user = validate_session(session, token)
        if user:
            return user
    if not settings.auth_required:
        return ensure_default_user(session)
    return None
