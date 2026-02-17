from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import LockResourceId, parse_lock_resource_id
from modules.locks import schemas, service

router = APIRouter(prefix='/locks', tags=['locks'])


@router.post('/{resource_id}/acquire', response_model=schemas.LockResponse)
@handle_errors(operation='acquire lock')
def acquire_lock(
    resource_id: LockResourceId,
    request: schemas.LockAcquireRequest,
    session: Session = Depends(get_db),
):
    """Acquire a lock on a resource."""
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
def heartbeat(
    resource_id: LockResourceId,
    request: schemas.LockHeartbeatRequest,
    session: Session = Depends(get_db),
):
    """Extend lock lease via heartbeat."""
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
def release_lock(
    resource_id: LockResourceId,
    request: schemas.LockReleaseRequest,
    session: Session = Depends(get_db),
):
    """Release a lock."""
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
def get_lock_status(
    resource_id: LockResourceId,
    client_id: str | None = None,
    session: Session = Depends(get_db),
):
    """Get current lock status for a resource."""
    return service.get_lock_status(session, parse_lock_resource_id(resource_id), client_id)
