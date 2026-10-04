from __future__ import annotations

from typing import Any, Protocol

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from backend_core import runtime_workers_service
from backend_core.api_execution_budget import run_api_blocking
from backend_core.auth_config import settings as auth_settings
from backend_core.database import run_settings_db
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from modules.auth.dependencies import _resolve_session_token
from modules.auth.service import ensure_default_user, validate_session


class RuntimeAvailabilityProbe(Protocol):
    def available(self, *, kind: RuntimeWorkerKind) -> bool:
        pass


class PersistedRuntimeAvailabilityProbe:
    def __init__(self, *, heartbeat_seconds: float = 15.0) -> None:
        self._heartbeat_seconds = heartbeat_seconds

    def available(self, *, kind: RuntimeWorkerKind) -> bool:
        return run_settings_db(
            runtime_workers_service.worker_available,
            kind=kind,
            heartbeat_seconds=self._heartbeat_seconds,
        )


async def get_manager(request: Request) -> Any:
    """FastAPI dependency that returns the ProcessManager from app state."""
    return request.app.state.manager


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
        return _scope_lock_owner_id(ensure_default_user(session).id, editor_client_id)
    return None


async def get_optional_lock_owner_id(request: Request) -> str | None:
    return await run_api_blocking(
        run_settings_db,
        resolve_lock_owner_id,
        _resolve_session_token(request),
        request.headers.get('X-Editor-Client-Id'),
    )


async def get_runtime_availability_probe(
    request: Request,
) -> RuntimeAvailabilityProbe:
    probe = getattr(request.app.state, 'runtime_availability_probe', None)
    if probe is not None:
        return probe
    return PersistedRuntimeAvailabilityProbe()


async def get_lock_owner_id(
    owner_id: str | None = Depends(get_optional_lock_owner_id),
) -> str:
    if owner_id is not None:
        return owner_id
    raise HTTPException(status_code=401, detail='Lock owner identity is required')
