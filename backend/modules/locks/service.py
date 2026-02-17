import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlmodel import Session, col

from modules.locks.models import Lock
from modules.locks.schemas import LockResponse, LockStatusResponse

# Lock configuration
LOCK_TTL_SECONDS = 30  # Lock expires after 30 seconds
HEARTBEAT_INTERVAL_SECONDS = 10  # Heartbeat every 10 seconds


def cleanup_expired_locks(session: Session) -> None:
    """Remove all expired locks."""
    now = datetime.now(UTC).replace(tzinfo=None)
    result = session.execute(select(Lock))
    locks = result.scalars().all()

    for lock in locks:
        expires_at = lock.expires_at
        if expires_at < now:
            session.delete(lock)

    session.commit()


def acquire_lock(
    session: Session,
    resource_id: str,
    client_id: str,
    client_signature: str,
) -> LockResponse:
    """Acquire a lock on a resource.

    Raises:
        ValueError: If resource is already locked by another client.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    expires_at = now + timedelta(seconds=LOCK_TTL_SECONDS)
    lock = session.get(Lock, resource_id)

    if not lock:
        lock = Lock(
            resource_id=resource_id,
            client_id=client_id,
            client_signature=client_signature,
            lock_token=str(uuid.uuid4()),
            acquired_at=now,
            expires_at=expires_at,
            last_heartbeat=now,
        )
        session.add(lock)
        session.commit()
        session.refresh(lock)

    if lock:
        if lock.expires_at < now:
            lock.client_id = client_id
            lock.client_signature = client_signature
            lock.lock_token = str(uuid.uuid4())
            lock.acquired_at = now
            lock.expires_at = expires_at
            lock.last_heartbeat = now
            session.commit()
            session.refresh(lock)
        elif lock.client_id != client_id:
            raise ValueError(f'Resource is locked by another client until {lock.expires_at}')
        else:
            lock.lock_token = str(uuid.uuid4())
            lock.client_signature = client_signature
            lock.acquired_at = now
            lock.expires_at = expires_at
            lock.last_heartbeat = now
            session.commit()
            session.refresh(lock)

    if not lock:
        raise ValueError('Failed to acquire lock')

    return LockResponse(
        resource_id=lock.resource_id,
        client_id=lock.client_id,
        lock_token=lock.lock_token,
        expires_at=lock.expires_at.isoformat(),
    )


def heartbeat(
    session: Session,
    resource_id: str,
    client_id: str,
    lock_token: str,
) -> LockResponse:
    """Extend lock lease via heartbeat.

    Raises:
        ValueError: If lock doesn't exist, expired, or token/client mismatch.
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    result = session.execute(select(Lock).where(col(Lock.resource_id) == resource_id))
    lock = result.scalar_one_or_none()

    if not lock:
        raise ValueError('Lock not found or expired')

    if lock.lock_token != lock_token:
        raise ValueError('Invalid lock token')

    if lock.client_id != client_id:
        raise ValueError('Lock held by another client')

    if lock.expires_at < now:
        # Lock expired - remove it
        session.delete(lock)
        session.commit()
        raise ValueError('Lock expired')

    # Extend lease
    lock.expires_at = now + timedelta(seconds=LOCK_TTL_SECONDS)
    lock.last_heartbeat = now

    session.commit()
    session.refresh(lock)

    return LockResponse(
        resource_id=lock.resource_id,
        client_id=lock.client_id,
        lock_token=lock.lock_token,
        expires_at=lock.expires_at.isoformat(),
    )


def release_lock(
    session: Session,
    resource_id: str,
    client_id: str,
    lock_token: str,
) -> None:
    """Release a lock.

    Raises:
        ValueError: If lock doesn't exist or client/token mismatch.
    """
    result = session.execute(select(Lock).where(col(Lock.resource_id) == resource_id))
    lock = result.scalar_one_or_none()

    if not lock:
        # Already released - not an error
        return

    if lock.client_id != client_id or lock.lock_token != lock_token:
        raise ValueError('Cannot release lock held by another client')

    session.delete(lock)
    session.commit()


def clear_lock(session: Session, resource_id: str) -> None:
    """Remove any lock for a resource (admin cleanup)."""
    result = session.execute(select(Lock).where(col(Lock.resource_id) == resource_id))
    lock = result.scalar_one_or_none()
    if not lock:
        return
    session.delete(lock)
    session.commit()


def get_lock_status(
    session: Session,
    resource_id: str,
    client_id: str | None = None,
) -> LockStatusResponse:
    """Get current lock status for a resource."""
    # Clean up expired locks first
    cleanup_expired_locks(session)

    result = session.execute(select(Lock).where(col(Lock.resource_id) == resource_id))
    lock = result.scalar_one_or_none()

    if not lock:
        return LockStatusResponse(locked=False)

    return LockStatusResponse(
        locked=True,
        locked_by_me=client_id is not None and lock.client_id == client_id,
        client_id=lock.client_id,
        expires_at=lock.expires_at.isoformat(),
    )


def validate_lock(
    session: Session,
    resource_id: str,
    client_id: str,
    lock_token: str,
) -> None:
    """Validate that a lock is held by the client and not expired."""
    cleanup_expired_locks(session)

    result = session.execute(select(Lock).where(col(Lock.resource_id) == resource_id))
    lock = result.scalar_one_or_none()

    if not lock:
        raise ValueError('Lock not found or expired')

    if lock.client_id != client_id:
        raise ValueError('Lock held by another client')

    if lock.lock_token != lock_token:
        raise ValueError('Invalid lock token')

    now = datetime.now(UTC).replace(tzinfo=None)
    if lock.expires_at < now:
        session.delete(lock)
        session.commit()
        raise ValueError('Lock expired')
