import uuid
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, or_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import Session

from backend_core.config import settings
from backend_core.persistence.locks.models import ResourceLock
from backend_core.time import utc_now as _utcnow
from modules.locks.schemas import LockStatusResponse


def _expires_at(now: datetime, ttl_seconds: int | None) -> datetime:
    ttl = ttl_seconds or settings.lock_ttl_seconds
    return now + timedelta(seconds=ttl)


def _reset_session_after_conflict(session: Session) -> None:
    session.rollback()
    session.expire_all()


def _status(lock: ResourceLock, now: datetime | None = None) -> LockStatusResponse:
    current = ResourceLock.as_utc(now or _utcnow())
    return LockStatusResponse(
        resource_type=lock.resource_type,
        resource_id=lock.resource_id,
        owner_id=lock.owner_id,
        lock_token=lock.lock_token,
        acquired_at=lock.acquired_at,
        expires_at=lock.expires_at,
        last_heartbeat=lock.last_heartbeat,
        is_expired=lock.is_expired(now=current),
    )


def get_lock(session: Session, resource_type: str, resource_id: str) -> ResourceLock | None:
    return session.get(ResourceLock, (resource_type, resource_id))


def lookup_lock_status(session: Session, resource_type: str, resource_id: str) -> tuple[LockStatusResponse | None, bool]:
    lock = get_lock(session, resource_type, resource_id)
    if lock is None:
        return None, False
    now = _utcnow()
    if lock.is_expired(now=now):
        _delete_expired_lock(session, resource_type, resource_id, now)
        return None, True
    return _status(lock, now), False


def get_lock_status(session: Session, resource_type: str, resource_id: str) -> LockStatusResponse | None:
    status, _ = lookup_lock_status(session, resource_type, resource_id)
    return status


def _lock_table():
    return ResourceLock.metadata.tables[ResourceLock.__tablename__]


def _delete_expired_lock(session: Session, resource_type: str, resource_id: str, now: datetime) -> bool:
    """Delete an expired row without assuming the ORM identity is still current.

    Lock cleanup races with heartbeat, reacquire, and websocket disconnects. A
    conditional Core DELETE is idempotent when one of those operations wins the
    race and does not emit SQLAlchemy's stale-row warning.
    """
    table = _lock_table()
    statement = (
        delete(ResourceLock)
        .where(table.c.resource_type == resource_type)
        .where(table.c.resource_id == resource_id)
        .where(table.c.expires_at <= ResourceLock.as_utc(now))
    )
    result = cast(CursorResult[Any], session.execute(statement))
    session.commit()
    return result.rowcount == 1


def acquire_lock(
    session: Session,
    resource_type: str,
    resource_id: str,
    owner_id: str,
    ttl_seconds: int | None = None,
) -> LockStatusResponse:
    table = _lock_table()
    for _ in range(2):
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
            except IntegrityError, StaleDataError:
                _reset_session_after_conflict(session)
                continue
            session.refresh(lock)
            return _status(lock, now)
        if lock.owner_id != owner_id and not lock.is_expired(now=now):
            raise ValueError(f'{resource_type} {resource_id} is locked by another owner')
        token = uuid.uuid4().hex
        statement = (
            update(ResourceLock)
            .where(table.c.resource_type == resource_type)
            .where(table.c.resource_id == resource_id)
            .where(or_(table.c.owner_id == owner_id, table.c.expires_at <= ResourceLock.as_utc(now)))
            .values(
                owner_id=owner_id,
                lock_token=token,
                acquired_at=now,
                expires_at=_expires_at(now, ttl_seconds),
                last_heartbeat=now,
            )
        )
        result = cast(CursorResult[Any], session.execute(statement))
        if result.rowcount != 1:
            _reset_session_after_conflict(session)
            continue
        session.commit()
        session.expire_all()
        current = get_lock(session, resource_type, resource_id)
        if current is None:
            continue
        return _status(current, now)

    current = get_lock(session, resource_type, resource_id)
    if current is None:
        raise ValueError(f'{resource_type} {resource_id} lock could not be acquired')
    now = _utcnow()
    if current.owner_id == owner_id or current.is_expired(now=now):
        raise ValueError(f'{resource_type} {resource_id} lock could not be acquired')
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
    table = _lock_table()
    statement = (
        update(ResourceLock)
        .where(table.c.resource_type == resource_type)
        .where(table.c.resource_id == resource_id)
        .where(table.c.owner_id == owner_id)
        .where(table.c.lock_token == lock_token)
        .where(table.c.expires_at > ResourceLock.as_utc(now))
        .values(
            last_heartbeat=now,
            expires_at=_expires_at(now, ttl_seconds),
        )
    )
    result = cast(CursorResult[Any], session.execute(statement))
    if result.rowcount != 1:
        session.rollback()
        lock = get_lock(session, resource_type, resource_id)
        if lock is None or lock.is_expired(now=now):
            raise ValueError(f'{resource_type} {resource_id} lock is not active')
        # Same owner, newer token: report the live lock without extending it.
        # A 409 here makes the editor that rotated the token wait out the TTL.
        if lock.owner_id == owner_id:
            return _status(lock, now)
        raise ValueError(f'{resource_type} {resource_id} lock is owned by another owner')
    session.commit()
    session.expire_all()
    lock = get_lock(session, resource_type, resource_id)
    if lock is None:
        raise ValueError(f'{resource_type} {resource_id} lock is not active')
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
    table = _lock_table()
    statement = (
        delete(ResourceLock)
        .where(table.c.resource_type == resource_type)
        .where(table.c.resource_id == resource_id)
        .where(table.c.owner_id == owner_id)
        .where(table.c.lock_token == lock_token)
        .where(table.c.expires_at > ResourceLock.as_utc(now))
    )
    result = cast(CursorResult[Any], session.execute(statement))
    session.commit()
    if result.rowcount == 1:
        return True

    # Preserve the old idempotent behavior for an expired lock, while never
    # deleting a newer active lock that replaced it.
    _delete_expired_lock(session, resource_type, resource_id, now)
    return False


def ensure_mutation_lock(session: Session, resource_type: str, resource_id: str, owner_id: str | None) -> None:
    now = _utcnow()
    lock = get_lock(session, resource_type, resource_id)
    if lock is None:
        return
    if lock.is_expired(now=now):
        _delete_expired_lock(session, resource_type, resource_id, now)
        return
    if owner_id != lock.owner_id:
        raise ValueError(f'{resource_type} {resource_id} is locked by another owner')
