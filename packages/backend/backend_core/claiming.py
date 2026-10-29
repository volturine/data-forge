from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast

from sqlalchemy import func, select, text, update
from sqlalchemy.engine import Connection, CursorResult, Engine
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session

# Initial claims only need to cover delivery to the worker and its first
# renewal. A lost claim response must not hold durable work for the full
# execution lease.
CLAIM_DELIVERY_LEASE_SECONDS = 20


def is_postgres(session_or_bind: Session | Engine | Connection) -> bool:
    get_bind = getattr(session_or_bind, 'get_bind', None)
    bind = get_bind() if callable(get_bind) else session_or_bind
    return getattr(getattr(bind, 'dialect', None), 'name', None) == 'postgresql'


def advisory_key(name: str) -> int:
    return int.from_bytes(sha256(name.encode()).digest()[:8], 'big', signed=True)


def advisory_xact_lock(session: Session, name: str, *, shared: bool = False) -> None:
    if not is_postgres(session):
        return
    lock_function = 'pg_advisory_xact_lock_shared' if shared else 'pg_advisory_xact_lock'
    session.execute(text(f'SELECT {lock_function}(:key)'), {'key': advisory_key(name)})


def database_now(session: Session, *, wall_clock: bool = False) -> datetime:
    """Return the database clock durable work availability is compared against.

    The default is the transaction timestamp; ``wall_clock`` reads PostgreSQL's
    current wall time for checks made after waiting on row locks.
    """
    clock = func.clock_timestamp() if wall_clock and is_postgres(session) else func.current_timestamp()
    value = session.execute(select(clock)).scalar_one()
    if not isinstance(value, datetime):
        raise TypeError('Database CURRENT_TIMESTAMP did not return a datetime')
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def database_lease_clock(session: Session, fallback: datetime) -> Any:
    """Use wall time at the lease write, not the transaction's start time."""
    if is_postgres(session):
        return func.clock_timestamp()
    return fallback


def with_for_update_skip_locked(session: Session, statement: Any) -> Any:
    if is_postgres(session):
        return statement.with_for_update(skip_locked=True)
    return statement


def claim_by_lease_owner(
    session: Session,
    model: type[Any],
    *,
    table: Any,
    row_id: object,
    previous_owner: object | None,
    values: Mapping[str, object],
    extra_conditions: Iterable[ColumnElement[bool]] = (),
) -> bool:
    statement = update(model).where(table.c.id == row_id)
    for condition in extra_conditions:
        statement = statement.where(condition)
    statement = statement.where(table.c.lease_owner.is_(None)) if previous_owner is None else statement.where(table.c.lease_owner == previous_owner)
    result = cast(CursorResult[Any], session.execute(statement.values(dict(values))))
    return result.rowcount == 1
