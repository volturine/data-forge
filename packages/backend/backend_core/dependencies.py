from __future__ import annotations

from typing import Any, Protocol

from contracts.runtime_workers.models import RuntimeWorkerKind
from core import runtime_workers_service
from core.database import get_settings_db
from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from backend_core.auth_config import settings as auth_settings
from modules.auth.dependencies import _resolve_session_token
from modules.auth.service import ensure_default_user, validate_session


class RuntimeAvailabilityProbe(Protocol):
    def available(self, *, kind: RuntimeWorkerKind) -> bool:
        pass


class PersistedRuntimeAvailabilityProbe:
    def __init__(self, session: Session, *, heartbeat_seconds: float = 15.0) -> None:
        self._session = session
        self._heartbeat_seconds = heartbeat_seconds

    def available(self, *, kind: RuntimeWorkerKind) -> bool:
        return runtime_workers_service.worker_available(
            self._session,
            kind=kind,
            heartbeat_seconds=self._heartbeat_seconds,
        )


def get_manager(request: Request) -> Any:
    """FastAPI dependency that returns the ProcessManager from app state."""
    return request.app.state.manager


def resolve_lock_owner_id(session: Session, token: str | None) -> str | None:
    if token:
        user = validate_session(session, token)
        if user is not None:
            return user.id
    if not auth_settings.auth_required:
        return ensure_default_user(session).id
    return None


def get_optional_lock_owner_id(
    request: Request,
    session: Session = Depends(get_settings_db),
) -> str | None:
    return resolve_lock_owner_id(session, _resolve_session_token(request))


def get_runtime_availability_probe(
    request: Request,
    session: Session = Depends(get_settings_db),
) -> RuntimeAvailabilityProbe:
    probe = getattr(request.app.state, "runtime_availability_probe", None)
    if probe is not None:
        return probe
    return PersistedRuntimeAvailabilityProbe(session)


def get_lock_owner_id(
    owner_id: str | None = Depends(get_optional_lock_owner_id),
) -> str:
    if owner_id is not None:
        return owner_id
    raise HTTPException(status_code=401, detail="Lock owner identity is required")
