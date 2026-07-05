from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from backend_core.exceptions import datasource_not_found
from backend_core.persistence.datasource.models import DataSource
from backend_core.sqlmodel_typing import col, sa
from backend_core.time import utc_now as _utcnow


def get_datasource(session: Session, datasource_id: str) -> DataSource | None:
    return session.get(DataSource, datasource_id)


def get_active_datasource(session: Session, datasource_id: str) -> DataSource:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None or datasource.is_pending_delete:
        raise datasource_not_found(datasource_id)
    return datasource


def request_delete(session: Session, datasource_id: str, *, now: datetime | None = None) -> DataSource:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise datasource_not_found(datasource_id)
    if datasource.is_pending_delete:
        return datasource
    stamp = now or _utcnow()
    datasource.is_pending_delete = True
    datasource.is_hidden = True
    datasource.delete_requested_at = stamp
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    return datasource


def list_pending_deletes(session: Session) -> list[DataSource]:
    stmt = (
        select(DataSource)
        .where(col(DataSource.is_pending_delete).is_(True))
        .order_by(sa(DataSource.delete_requested_at), sa(DataSource.created_at), sa(DataSource.id))
    )
    return list(session.execute(stmt).scalars().all())
