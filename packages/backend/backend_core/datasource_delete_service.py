from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlmodel import Session, select

from backend_core.datasource_storage import cleanup_datasource_storage
from backend_core.domain.datasource.source_types import DataSourceType
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


def finalize_delete(session: Session, datasource_id: str) -> bool:
    """Delete the datasource row, then reclaim its storage out-of-band.

    Storage cleanup must never run inside the row-deletion transaction: if it
    failed mid-way the row would survive pointing at half-deleted storage.
    Deletion commits first (the dataset becomes unreachable atomically); any
    storage failure afterwards only costs orphaned bytes, never correctness.
    """
    datasource = get_datasource(session, datasource_id)
    if datasource is None:
        return False
    snapshot = {
        'id': str(datasource.id),
        'source_type': str(datasource.source_type),
        'is_iceberg': bool(datasource.is_iceberg),
        'config': deepcopy(datasource.config) if isinstance(datasource.config, dict) else None,
    }
    session.delete(datasource)
    session.commit()
    reclaim_storage(snapshot)
    return True


def reclaim_storage(snapshot: dict[str, Any]) -> None:
    stub = SimpleNamespace(
        id=snapshot['id'],
        source_type=snapshot['source_type'],
        is_iceberg=snapshot['is_iceberg'],
        config=snapshot['config'],
        source_type_kind=lambda: DataSourceType.require(snapshot['source_type']),
    )
    cleanup_datasource_storage(stub)
