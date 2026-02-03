from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.database import get_db
from modules.locks import schemas, service

router = APIRouter(prefix='/locks', tags=['locks'])


@router.post('/{resource_id}/acquire', response_model=schemas.LockResponse)
def acquire_lock(
    resource_id: str,
    request: schemas.LockAcquireRequest,
    session: Session = Depends(get_db),
):
    """Acquire a lock on a resource."""
    try:
        return service.acquire_lock(
            session,
            resource_id,
            request.client_id,
            request.client_signature,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to acquire lock: {str(e)}')


@router.post('/{resource_id}/heartbeat', response_model=schemas.LockResponse)
def heartbeat(
    resource_id: str,
    request: schemas.LockHeartbeatRequest,
    session: Session = Depends(get_db),
):
    """Extend lock lease via heartbeat."""
    try:
        return service.heartbeat(
            session,
            resource_id,
            request.client_id,
            request.lock_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Heartbeat failed: {str(e)}')


@router.post('/{resource_id}/release')
def release_lock(
    resource_id: str,
    request: schemas.LockReleaseRequest,
    session: Session = Depends(get_db),
):
    """Release a lock."""
    try:
        service.release_lock(
            session,
            resource_id,
            request.client_id,
            request.lock_token,
        )
        return {'status': 'released'}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to release lock: {str(e)}')


@router.get('/{resource_id}', response_model=schemas.LockStatusResponse)
def get_lock_status(
    resource_id: str,
    client_id: str | None = None,
    session: Session = Depends(get_db),
):
    """Get current lock status for a resource."""
    try:
        return service.get_lock_status(session, resource_id, client_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get lock status: {str(e)}')
