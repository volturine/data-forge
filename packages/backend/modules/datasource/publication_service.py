"""Authoritative datasource metadata publication for worker-owned execution.

Workers execute Polars/Iceberg workloads and call these functions only to persist
fenced metadata. No dataframe loading or Iceberg table writes belong here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend_core import storage_cleanup_service
from backend_core.domain.datasource.models import DataSourceCreatedBy
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.exceptions import datasource_not_found
from backend_core.persistence.datasource.models import DataSource, DataSourceColumnMetadata
from backend_core.sqlmodel_typing import col, sa
from dataforge_protocol import datasource_pb2
from modules.datasource.schema_protocol import schema_info_payload
from modules.datasource.schemas import (
    DataSourceDescriptionModel,
    DataSourceResponse,
)


class DatasourcePublicationClaimLost(RuntimeError):
    """Raised when a fenced ingest publication loses ownership before commit."""


class DatasourcePublicationRevisionChanged(RuntimeError):
    """Raised when schema work was computed from an obsolete datasource revision."""


def _schema_cache_payload(schema_info: datasource_pb2.SchemaInfo | None) -> dict[str, Any] | None:
    if schema_info is None:
        return None
    payload = schema_info_payload(schema_info)
    columns = cast(list[dict[str, object]], payload.get('columns', []))
    for column in columns:
        column.pop('description', None)
    if not columns:
        payload.pop('columns', None)
    return payload


def _response(datasource: DataSource) -> DataSourceResponse:
    return DataSourceResponse.model_validate(datasource)


def _enriched_response(datasource: DataSource, response: DataSourceResponse) -> DataSourceResponse:
    """Add the computed last_data_update the proto record cannot carry.

    Publication responses serialize as DataSourceRecord, which has no
    last_data_update field: the API re-derives it from the freshly published
    config so re-ingest feedback shows the new ingest time immediately.
    """
    from modules.datasource.service import _last_data_update_from_config

    response.last_data_update = _last_data_update_from_config(datasource)
    return response


def create_datasource(
    session: Session,
    *,
    datasource_id: str,
    name: str,
    description: str | None,
    source_type: str,
    config: Mapping[str, object],
    owner_id: str | None,
    schema_info: datasource_pb2.SchemaInfo | None = None,
    publication_guard: Callable[[Session], None] | None = None,
) -> DataSourceResponse:
    if publication_guard is not None:
        publication_guard(session)
    resolved_type = DataSourceType.require(source_type)
    existing = session.get(DataSource, datasource_id)
    if existing is not None:
        # Compute requests are retried at least once when a worker loses its
        # response connection after committing the publication. The request
        # ID is the datasource ID for create requests, so replaying the same
        # request must return the committed row instead of inserting another
        # row with the same user-visible name.
        if existing.name != name or existing.source_type != resolved_type or existing.owner_id != owner_id:
            raise ValueError(f'Datasource publication ID {datasource_id} is already in use')
        storage_cleanup_service.settle_publication(session, existing.config)
        session.commit()
        return _enriched_response(existing, _response(existing))

    datasource = DataSource(
        id=datasource_id,
        name=name,
        description=DataSourceDescriptionModel.normalize_description(description),
        source_type=resolved_type,
        config=dict(config),
        schema_cache=_schema_cache_payload(schema_info),
        owner_id=owner_id,
        created_by=DataSourceCreatedBy.IMPORT.value,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(datasource)
    try:
        storage_cleanup_service.settle_publication(session, config)
        session.commit()
    except IntegrityError:
        # Another replay may have committed the same request between the
        # existence check and this insert. Treat that race exactly like the
        # already-committed case above.
        session.rollback()
        existing = session.get(DataSource, datasource_id)
        if existing is None:
            raise
        if existing.name != name or existing.source_type != resolved_type or existing.owner_id != owner_id:
            raise ValueError(f'Datasource publication ID {datasource_id} is already in use')
        if publication_guard is not None:
            publication_guard(session)
        storage_cleanup_service.settle_publication(session, existing.config)
        session.commit()
        return _enriched_response(existing, _response(existing))
    session.refresh(datasource)
    return _enriched_response(datasource, _response(datasource))


def publish_ingest(
    session: Session,
    *,
    datasource_id: str,
    config: Mapping[str, object],
    expected_revision: int,
    schema_info: datasource_pb2.SchemaInfo | None,
    publication_guard: Callable[[Session], None] | None = None,
) -> DataSourceResponse:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise datasource_not_found(datasource_id)
    if publication_guard is not None:
        publication_guard(session)
    values: dict[str, object] = {
        'config': dict(config),
        'revision': expected_revision + 1,
    }
    if schema_info is not None:
        values['schema_cache'] = _schema_cache_payload(schema_info)
    else:
        values['schema_cache'] = None
    statement = (
        update(DataSource)
        .where(sa(DataSource.id == datasource_id), sa(DataSource.revision == expected_revision), col(DataSource.is_pending_delete).is_(False))
        .values(**values)
    )
    publication = cast(CursorResult[Any], session.execute(statement))
    if publication.rowcount != 1:
        session.rollback()
        raise DatasourcePublicationClaimLost(f'Datasource {datasource_id} publication fence was replaced')
    storage_cleanup_service.settle_publication(session, config)
    session.commit()
    session.expire(datasource)
    session.refresh(datasource)
    return _enriched_response(datasource, _response(datasource))


def publish_schema_cache(
    session: Session,
    *,
    datasource_id: str,
    expected_revision: int,
    schema_info: datasource_pb2.SchemaInfo,
    publication_guard: Any,
) -> datasource_pb2.SchemaInfo:
    publication_guard(session)
    statement = (
        update(DataSource)
        .where(
            sa(DataSource.id == datasource_id),
            sa(DataSource.revision == expected_revision),
            col(DataSource.is_pending_delete).is_(False),
        )
        .values(schema_cache=_schema_cache_payload(schema_info))
    )
    publication = cast(CursorResult[Any], session.execute(statement))
    if publication.rowcount != 1:
        session.rollback()
        datasource = session.get(DataSource, datasource_id)
        if datasource is None or datasource.is_pending_delete:
            raise datasource_not_found(datasource_id)
        raise DatasourcePublicationRevisionChanged(f'Datasource {datasource_id} revision changed before schema publication')
    session.commit()
    return attach_column_descriptions(session, datasource_id, schema_info)


def column_description_map(session: Session, datasource_id: str) -> dict[str, str]:
    rows = session.exec(select(DataSourceColumnMetadata).where(sa(DataSourceColumnMetadata.datasource_id == datasource_id))).all()
    return {row.column_name: row.description for row in rows if row.description is not None}


def attach_column_descriptions(
    session: Session,
    datasource_id: str,
    schema_info: datasource_pb2.SchemaInfo,
) -> datasource_pb2.SchemaInfo:
    descriptions = column_description_map(session, datasource_id)
    for column in schema_info.columns:
        description = descriptions.get(column.name)
        if description is not None:
            column.description = description
    return schema_info


def get_datasource_for_worker(session: Session, datasource_id: str) -> DataSource | None:
    return session.get(DataSource, datasource_id)
