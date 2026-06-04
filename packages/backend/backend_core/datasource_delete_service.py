from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from backend_core.exceptions import DataSourceNotFoundError
from backend_core.persistence.datasource.models import DataSource


def _utcnow() -> datetime:
    return datetime.now(UTC)


def get_datasource(session: Session, datasource_id: str) -> DataSource | None:
    return session.get(DataSource, datasource_id)


def get_active_datasource(session: Session, datasource_id: str) -> DataSource:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None or datasource.is_pending_delete:
        raise DataSourceNotFoundError(datasource_id)
    return datasource


def request_delete(session: Session, datasource_id: str, *, now: datetime | None = None) -> DataSource:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(datasource_id)
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
        .where(DataSource.is_pending_delete == True)  # type: ignore[arg-type]  # noqa: E712
        .order_by(DataSource.delete_requested_at, DataSource.created_at, DataSource.id)  # type: ignore[arg-type]
    )
    return list(session.execute(stmt).scalars().all())
