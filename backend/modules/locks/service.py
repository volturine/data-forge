import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from core.config import settings
from modules.locks.models import ResourceLock
from modules.locks.schemas import LockStatusResponse


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _expires_at(now: datetime, ttl_seconds: int | None) -> datetime:
    ttl = ttl_seconds or settings.lock_ttl_seconds
    return now + timedelta(seconds=ttl)


def _status(lock: ResourceLock, now: datetime | None = None) -> LockStatusResponse:
    current = now or _utcnow()
    return LockStatusResponse(
        resource_type=lock.resource_type,
        resource_id=lock.resource_id,
        owner_id=lock.owner_id,
        lock_token=lock.lock_token,
        acquired_at=lock.acquired_at,
        expires_at=lock.expires_at,
        last_heartbeat=lock.last_heartbeat,
        is_expired=lock.expires_at <= current,
    )


def get_lock(session: Session, resource_type: str, resource_id: str) -> ResourceLock | None:
    return session.get(ResourceLock, (resource_type, resource_id))


def lookup_lock_status(session: Session, resource_type: str, resource_id: str) -> tuple[LockStatusResponse | None, bool]:
    lock = get_lock(session, resource_type, resource_id)
    if lock is None:
        return None, False
    now = _utcnow()
    if lock.expires_at <= now:
        session.delete(lock)
        session.commit()
        return None, True
    return _status(lock, now), False


def get_lock_status(session: Session, resource_type: str, resource_id: str) -> LockStatusResponse | None:
    status, _ = lookup_lock_status(session, resource_type, resource_id)
    return status


def acquire_lock(
    session: Session,
    resource_type: str,
    resource_id: str,
    owner_id: str,
    ttl_seconds: int | None = None,
) -> LockStatusResponse:
    now = _utcnow()
    lock = get_lock(session, resource_type, resource_id)
    if lock is None:
        lock = ResourceLock(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_id=owner_id,
            lock_token=uuid.uuid4().hex,
            acquired_at=now,
            expires_at=_expires_at(now, ttl_seconds),
            last_heartbeat=now,
        )
        session.add(lock)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            lock = get_lock(session, resource_type, resource_id)
            now = _utcnow()
            if lock is None:
                raise ValueError(f'{resource_type} {resource_id} lock could not be acquired') from None
        else:
            session.refresh(lock)
            return _status(lock, now)
    if lock.owner_id == owner_id or lock.expires_at <= now:
        lock.owner_id = owner_id
        lock.lock_token = uuid.uuid4().hex
        lock.acquired_at = now
        lock.last_heartbeat = now
        lock.expires_at = _expires_at(now, ttl_seconds)
        session.add(lock)
        session.commit()
        session.refresh(lock)
        return _status(lock, now)
    raise ValueError(f'{resource_type} {resource_id} is locked by another owner')


def heartbeat_lock(
    session: Session,
    resource_type: str,
    resource_id: str,
    owner_id: str,
    lock_token: str,
    ttl_seconds: int | None = None,
) -> LockStatusResponse:
    now = _utcnow()
    lock = get_lock(session, resource_type, resource_id)
    if lock is None or lock.expires_at <= now:
        raise ValueError(f'{resource_type} {resource_id} lock is not active')
    if lock.owner_id != owner_id or lock.lock_token != lock_token:
        raise ValueError(f'{resource_type} {resource_id} lock is owned by another owner')
    lock.last_heartbeat = now
    lock.expires_at = _expires_at(now, ttl_seconds)
    session.add(lock)
    session.commit()
    session.refresh(lock)
    return _status(lock, now)


def release_lock(
    session: Session,
    resource_type: str,
    resource_id: str,
    owner_id: str,
    lock_token: str,
) -> bool:
    """Release lock if caller still owns the active token.

    DELETE is idempotent: stale, missing, or superseded lock tokens return False
    rather than raising API conflicts.
    """
    now = _utcnow()
    lock = get_lock(session, resource_type, resource_id)
    if lock is None:
        return False
    if lock.expires_at <= now:
        session.delete(lock)
        session.commit()
        return False
    if lock.owner_id != owner_id or lock.lock_token != lock_token:
        return False
    session.delete(lock)
    session.commit()
    return True


def ensure_mutation_lock(session: Session, resource_type: str, resource_id: str, owner_id: str | None) -> None:
    now = _utcnow()
    lock = get_lock(session, resource_type, resource_id)
    if lock is None:
        return
    if lock.expires_at <= now:
        session.delete(lock)
        session.commit()
        return
    if owner_id != lock.owner_id:
        raise ValueError(f'{resource_type} {resource_id} is locked by another owner')
