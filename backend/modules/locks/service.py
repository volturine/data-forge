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
    now = datetime.now(UTC)
    # SQLite stores naive datetimes, so we need to compare carefully
    # Fetch all locks and filter in Python to avoid timezone issues
    result = session.execute(select(Lock))
    locks = result.scalars().all()

    for lock in locks:
        expires_at = lock.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
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
    # Clean up expired locks first
    cleanup_expired_locks(session)

    now = datetime.now(UTC)

    # Check if resource is already locked
    result = session.execute(select(Lock).where(col(Lock.resource_id) == resource_id))
    existing = result.scalar_one_or_none()

    if existing:
        if existing.client_id != client_id:
            raise ValueError(f'Resource is locked by another client until {existing.expires_at}')
        # Same client - update the lock
        existing.lock_token = str(uuid.uuid4())
        existing.client_signature = client_signature
        existing.acquired_at = now
        existing.expires_at = now + timedelta(seconds=LOCK_TTL_SECONDS)
        existing.last_heartbeat = now
    else:
        # Create new lock
        lock = Lock(
            resource_id=resource_id,
            client_id=client_id,
            client_signature=client_signature,
            lock_token=str(uuid.uuid4()),
            acquired_at=now,
            expires_at=now + timedelta(seconds=LOCK_TTL_SECONDS),
            last_heartbeat=now,
        )
        session.add(lock)
        existing = lock

    session.commit()
    session.refresh(existing)

    return LockResponse(
        resource_id=existing.resource_id,
        client_id=existing.client_id,
        lock_token=existing.lock_token,
        expires_at=existing.expires_at.isoformat(),
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
    now = datetime.now(UTC)

    result = session.execute(select(Lock).where(col(Lock.resource_id) == resource_id))
    lock = result.scalar_one_or_none()

    if not lock:
        raise ValueError('Lock not found or expired')

    if lock.lock_token != lock_token:
        raise ValueError('Invalid lock token')

    if lock.client_id != client_id:
        raise ValueError('Lock held by another client')

    # Handle timezone-aware vs naive datetime comparison
    expires_at = lock.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if expires_at < now:
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
