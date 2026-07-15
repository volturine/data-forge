from collections.abc import Iterable, Mapping
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session


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
