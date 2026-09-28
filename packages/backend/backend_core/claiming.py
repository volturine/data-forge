from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session

# Initial claims only need to cover delivery to the worker and its first
# renewal. A lost claim response must not hold durable work for the full
# execution lease.
CLAIM_DELIVERY_LEASE_SECONDS = 20


def database_lease_clock(session: Session, fallback: datetime) -> Any:
    """Use wall time at the lease write, not the transaction's start time."""
    if session.get_bind().dialect.name == 'postgresql':
        return func.clock_timestamp()
    return fallback


def with_for_update_skip_locked(session: Session, statement: Any) -> Any:
    if session.get_bind().dialect.name == 'postgresql':
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
