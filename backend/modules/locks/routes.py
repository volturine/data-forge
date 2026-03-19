from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import LockResourceId, parse_lock_resource_id
from modules.locks import schemas, service
from modules.mcp.decorators import deterministic_tool

router = APIRouter(prefix='/locks', tags=['locks'])


@router.post('/{resource_id}/acquire', response_model=schemas.LockResponse)
@handle_errors(operation='acquire lock')
@deterministic_tool
def acquire_lock(
    resource_id: LockResourceId,
    request: schemas.LockAcquireRequest,
    session: Session = Depends(get_db),
):
    """Acquire an editing lock on a resource (typically an analysis ID).

    Required for PUT /analysis/{id} updates. Provide client_id (unique per browser tab)
    and optional client_signature (display name). Returns lock_token needed for updates.
    Returns 409 if already locked by another client.
    """
    try:
        return service.acquire_lock(
            session,
            parse_lock_resource_id(resource_id),
            request.client_id,
            request.client_signature,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post('/{resource_id}/heartbeat', response_model=schemas.LockResponse)
@handle_errors(operation='heartbeat lock')
@deterministic_tool
def heartbeat(
    resource_id: LockResourceId,
    request: schemas.LockHeartbeatRequest,
    session: Session = Depends(get_db),
):
    """Extend an active lock's expiration. Call periodically (every 30s) to keep the lock alive.

    Requires the client_id and lock_token from the original acquire response.
    """
    try:
        return service.heartbeat(
            session,
            parse_lock_resource_id(resource_id),
            request.client_id,
            request.lock_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post('/{resource_id}/release')
@handle_errors(operation='release lock')
@deterministic_tool
def release_lock(
    resource_id: LockResourceId,
    request: schemas.LockReleaseRequest,
    session: Session = Depends(get_db),
):
    """Release an editing lock. Requires the client_id and lock_token from acquire.

    Call this when done editing to allow other clients to acquire the lock.
    """
    try:
        service.release_lock(
            session,
            parse_lock_resource_id(resource_id),
            request.client_id,
            request.lock_token,
        )
        return {'status': 'released'}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get('/{resource_id}', response_model=schemas.LockStatusResponse)
@handle_errors(operation='get lock status')
@deterministic_tool
def get_lock_status(
    resource_id: LockResourceId,
    client_id: str | None = None,
    session: Session = Depends(get_db),
):
    """Check if a resource is locked and by whom.

    Optionally pass client_id to check if you hold the lock (locked_by_me field).
    """
    return service.get_lock_status(session, parse_lock_resource_id(resource_id), client_id)
