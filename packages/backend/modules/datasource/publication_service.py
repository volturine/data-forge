"""Authoritative datasource metadata publication for worker-owned execution.

Workers execute Polars/Iceberg workloads and call these functions only to persist
fenced metadata. No dataframe loading or Iceberg table writes belong here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, select

from backend_core.domain.datasource.models import DataSourceCreatedBy
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.exceptions import datasource_not_found
from backend_core.persistence.datasource.models import DataSource, DataSourceColumnMetadata
from backend_core.sqlmodel_typing import sa
from dataforge_protocol import datasource_pb2
from modules.datasource.schema_protocol import schema_info_payload
from modules.datasource.schemas import (
    DataSourceDescriptionModel,
    DataSourceResponse,
)


class DatasourcePublicationClaimLost(RuntimeError):
    """Raised when a fenced ingest publication loses ownership before commit."""


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
) -> DataSourceResponse:
    resolved_type = DataSourceType.require(source_type)
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
    session.commit()
    session.refresh(datasource)
    return _response(datasource)


def publish_ingest(
    session: Session,
    *,
    datasource_id: str,
    config: Mapping[str, object],
    expected_revision: int,
    schema_info: datasource_pb2.SchemaInfo | None,
    publication_guard: Any | None = None,
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
    statement = update(DataSource).where(sa(DataSource.id == datasource_id), sa(DataSource.revision == expected_revision)).values(**values)
    publication = cast(CursorResult[Any], session.execute(statement))
    if publication.rowcount != 1:
        session.rollback()
        raise DatasourcePublicationClaimLost(f'Datasource {datasource_id} publication fence was replaced')
    session.commit()
    session.expire(datasource)
    session.refresh(datasource)
    return _response(datasource)


def publish_schema_cache(session: Session, *, datasource_id: str, schema_info: datasource_pb2.SchemaInfo) -> datasource_pb2.SchemaInfo:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise datasource_not_found(datasource_id)
    datasource.schema_cache = _schema_cache_payload(schema_info)
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
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
