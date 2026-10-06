import logging
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import defer
from sqlmodel import Session

from backend_core import datasource_delete_service, storage_cleanup_service
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.datasource.models import DataSourceCreatedBy
from backend_core.domain.datasource.source_types import DataSourceFileType, DataSourceType
from backend_core.exceptions import DataSourceValidationError, datasource_not_found
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.persistence.datasource.models import DataSource, DataSourceColumnMetadata
from backend_core.secrets import MASKED_SECRET
from backend_core.sqlmodel_typing import col, sa
from dataforge_protocol import datasource_pb2
from modules.datasource.schema_protocol import schema_info_proto
from modules.datasource.schemas import (
    BatchColumnDescriptionUpdate,
    ColumnDescriptionPatch,
    DataSourceDescriptionModel,
    DataSourceListItem,
    DataSourceResponse,
    DataSourceUpdate,
    InternalPostgresTable,
)

logger = logging.getLogger(__name__)


_INTERNAL_POSTGRES_EXCLUDED_TABLES = {'alembic_version'}
_INTERNAL_POSTGRES_NAMESPACE_SCHEMA_PREFIX = 'df$tenant$'
_INTERNAL_POSTGRES_QUERY_RE = re.compile(r'^SELECT \* FROM "([^"]+)"\."([^"]+)"$')


class InternalPostgresOnboarding:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.inspector = inspect(session.get_bind())

    @staticmethod
    def _quote_identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    @classmethod
    def query_for(cls, schema_name: str, table_name: str) -> str:
        return f'SELECT * FROM {cls._quote_identifier(schema_name)}.{cls._quote_identifier(table_name)}'

    @staticmethod
    def display_schema_name(schema_name: str) -> str:
        if schema_name.startswith(_INTERNAL_POSTGRES_NAMESPACE_SCHEMA_PREFIX):
            return schema_name[len(_INTERNAL_POSTGRES_NAMESPACE_SCHEMA_PREFIX) :]
        return schema_name

    @classmethod
    def datasource_name_for(cls, schema_name: str, table_name: str) -> str:
        return f'internal.{cls.display_schema_name(schema_name)}.{table_name}'

    @classmethod
    def datasource_description_for(cls, schema_name: str, table_name: str) -> str:
        return f'Internal PostgreSQL table {cls.display_schema_name(schema_name)}.{table_name}'

    @staticmethod
    def query_schema_and_table(query: str | None) -> tuple[str, str] | None:
        if not isinstance(query, str):
            return None
        match = _INTERNAL_POSTGRES_QUERY_RE.fullmatch(query)
        if match is None:
            return None
        return match.group(1), match.group(2)

    @staticmethod
    def connection_string() -> str:
        from backend_core.config import settings

        return DataSource.normalize_connection_string(settings.database_url)

    def matching_datasources(self, schema_name: str, table_name: str) -> list[DataSource]:
        query = self.query_for(schema_name, table_name)
        connection_string = self.connection_string()
        datasource_name = self.datasource_name_for(schema_name, table_name)
        matches: list[DataSource] = []
        for datasource in self.session.execute(select(DataSource)).scalars().all():
            if datasource.name == datasource_name:
                matches.append(datasource)
                continue
            datasource_query, datasource_connection = datasource.query_and_connection()
            if datasource_query != query:
                continue
            if datasource_connection != connection_string:
                continue
            matches.append(datasource)
        return matches

    def _onboarded_table_keys(self) -> tuple[set[str], set[tuple[str, str]]]:
        """Load onboarding metadata once for the internal-table listing.

        The old list implementation called ``matching_datasources`` for every
        physical table. That method loaded every datasource on each call, so a
        namespace-heavy test run turned this endpoint into an O(tables ×
        datasources) query loop. Keep both matching rules, but materialize the
        two lookup sets once per request.
        """
        canonical_names: set[str] = set()
        query_sources: set[tuple[str, str]] = set()
        connection_string = self.connection_string()
        datasources = self.session.execute(select(DataSource)).scalars().all()
        for datasource in datasources:
            canonical_names.add(datasource.name)
            query, datasource_connection = datasource.query_and_connection()
            if datasource_connection != connection_string:
                continue
            source = self.query_schema_and_table(query)
            if source is not None:
                query_sources.add(source)
        return canonical_names, query_sources

    def list_tables(self) -> list[InternalPostgresTable]:
        rows: list[InternalPostgresTable] = []
        canonical_names, query_sources = self._onboarded_table_keys()
        bind = self.session.get_bind()
        physical_tables: list[tuple[str, str]]
        if bind.dialect.name == 'postgresql':
            physical_tables = [
                (str(schema_name), str(table_name))
                for schema_name, table_name in self.session.execute(
                    text(
                        """
                    SELECT namespace.nspname, relation.relname
                    FROM pg_catalog.pg_namespace AS namespace
                    JOIN pg_catalog.pg_class AS relation
                      ON relation.relnamespace = namespace.oid
                    WHERE namespace.nspname NOT LIKE 'pg_%'
                      AND namespace.nspname <> 'information_schema'
                      AND relation.relkind IN ('r', 'p', 'f')
                      AND relation.relname <> :excluded_table
                    ORDER BY namespace.nspname, relation.relname
                    """
                    ),
                    {'excluded_table': next(iter(_INTERNAL_POSTGRES_EXCLUDED_TABLES))},
                )
                .tuples()
                .all()
            ]
        else:
            physical_tables = [
                (schema_name, table_name)
                for schema_name in sorted(self.inspector.get_schema_names())
                if not schema_name.startswith('pg_') and schema_name != 'information_schema'
                for table_name in sorted(self.inspector.get_table_names(schema=schema_name))
                if table_name not in _INTERNAL_POSTGRES_EXCLUDED_TABLES
            ]
        for schema_name, table_name in physical_tables:
            rows.append(
                InternalPostgresTable(
                    schema_name=schema_name,
                    table_name=table_name,
                    is_onboarded=(self.datasource_name_for(schema_name, table_name) in canonical_names or (schema_name, table_name) in query_sources),
                ),
            )
        return rows

    def table_query(self, schema_name: str, table_name: str) -> str:
        if schema_name.startswith('pg_') or schema_name == 'information_schema':
            raise ValueError('System schemas cannot be onboarded')
        if table_name in _INTERNAL_POSTGRES_EXCLUDED_TABLES:
            raise ValueError(f'Table {schema_name}.{table_name} cannot be onboarded')
        if not self.inspector.has_table(table_name, schema=schema_name):
            raise ValueError(f'Internal Postgres table {schema_name}.{table_name} does not exist')
        return self.query_for(schema_name, table_name)

    def is_onboarded(self, schema_name: str, table_name: str) -> bool:
        self.table_query(schema_name, table_name)
        return bool(self.matching_datasources(schema_name, table_name))

    def set_onboarded(self, schema_name: str, table_name: str, *, enabled: bool) -> InternalPostgresTable:
        self.table_query(schema_name, table_name)
        matches = self.matching_datasources(schema_name, table_name)
        if enabled:
            return InternalPostgresTable(
                schema_name=schema_name,
                table_name=table_name,
                is_onboarded=bool(matches),
            )
        for datasource in matches:
            delete_datasource(self.session, datasource.id)
        return InternalPostgresTable(schema_name=schema_name, table_name=table_name, is_onboarded=False)


def internal_postgres_connection_string() -> str:
    return InternalPostgresOnboarding.connection_string()


def _canonical_internal_postgres_name(datasource: DataSource) -> str | None:
    query, connection_string = datasource.query_and_connection()
    if connection_string != internal_postgres_connection_string():
        return None
    source = InternalPostgresOnboarding.query_schema_and_table(query)
    if source is None:
        return None
    schema_name, table_name = source
    canonical = InternalPostgresOnboarding.datasource_name_for(schema_name, table_name)
    if datasource.name != canonical:
        return None
    return canonical


def _apply_display_name[DatasourceResponseT: (DataSourceResponse, DataSourceListItem)](
    response: DatasourceResponseT, datasource: DataSource
) -> DatasourceResponseT:
    canonical = _canonical_internal_postgres_name(datasource)
    if canonical is not None:
        response.name = canonical
    return response


_SECRET_CONFIG_KEYS = ('connection_string', 'catalog_uri')


def _masked_config(config: dict) -> dict:
    masked = {**config}
    for key in _SECRET_CONFIG_KEYS:
        value = masked.get(key)
        if isinstance(value, str) and value:
            masked[key] = MASKED_SECRET
    source = masked.get('source')
    if isinstance(source, dict):
        source_value = source.get('connection_string')
        if isinstance(source_value, str) and source_value:
            masked['source'] = {**source, 'connection_string': MASKED_SECRET}
    return masked


_SNAPSHOT_TIMESTAMP_KEYS = ('current_snapshot_timestamp_ms', 'snapshot_timestamp_ms')


def _snapshot_timestamp_ms(config: object) -> int | None:
    """Latest Iceberg snapshot timestamp (epoch ms) stored on the datasource config."""
    if not isinstance(config, dict):
        return None
    for key in _SNAPSHOT_TIMESTAMP_KEYS:
        value = config.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            timestamp_ms = value
        elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
            # Protobuf Struct decodes every numeric value as a float.
            timestamp_ms = int(value)
        else:
            continue
        if timestamp_ms > 0:
            return timestamp_ms
    return None


def _last_data_update_from_config(datasource: DataSource) -> datetime | None:
    timestamp_ms = _snapshot_timestamp_ms(datasource.config)
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).replace(tzinfo=None)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _last_build_completed_at_map(session: Session, analysis_ids: set[str]) -> dict[str, datetime]:
    """Latest successful build completion per analysis, for analysis-generated outputs."""
    if not analysis_ids:
        return {}
    rows = session.execute(
        select(col(BuildRun.analysis_id), col(BuildRun.completed_at))
        .where(col(BuildRun.analysis_id).in_(sorted(analysis_ids)))
        .where(col(BuildRun.status) == BuildRunStatus.COMPLETED)
    ).all()
    latest: dict[str, datetime] = {}
    for analysis_id, completed_at in rows:
        if completed_at is None:
            continue
        completed_at = _naive_utc(completed_at)
        previous = latest.get(analysis_id)
        if previous is None or completed_at > previous:
            latest[analysis_id] = completed_at
    return latest


def _apply_last_data_update[DatasourceResponseT: (DataSourceResponse, DataSourceListItem)](
    response: DatasourceResponseT,
    datasource: DataSource,
    last_build_completed_at: datetime | None,
) -> DatasourceResponseT:
    response.last_data_update = _last_data_update_from_config(datasource)
    if response.last_data_update is None and last_build_completed_at is not None:
        response.last_data_update = last_build_completed_at
    return response


def _coerce_row_count(raw: object | None) -> int | None:
    """Normalize a projected schema_cache.row_count value to a finite int."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if not raw.is_integer():
            return None
        return int(raw)
    if isinstance(raw, str):
        cleaned = raw.strip()
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            return None
    return None


def list_internal_postgres_tables(session: Session) -> list[InternalPostgresTable]:
    return InternalPostgresOnboarding(session).list_tables()


def internal_postgres_table_query(session: Session, schema_name: str, table_name: str) -> str:
    return InternalPostgresOnboarding(session).table_query(schema_name, table_name)


def internal_postgres_table_is_onboarded(
    session: Session,
    schema_name: str,
    table_name: str,
) -> bool:
    return InternalPostgresOnboarding(session).is_onboarded(schema_name, table_name)


def set_internal_postgres_table_onboarded(
    session: Session,
    schema_name: str,
    table_name: str,
    *,
    enabled: bool,
) -> InternalPostgresTable:
    return InternalPostgresOnboarding(session).set_onboarded(schema_name, table_name, enabled=enabled)


def create_placeholder_output_datasource(
    session: Session,
    result_id: str,
    analysis_id: str,
    analysis_tab_id: str,
    name: str | None = None,
    source_type: DataSourceType = DataSourceType.ANALYSIS,
    config: dict[str, Any] | None = None,
) -> None:
    try:
        uuid.UUID(result_id)
    except ValueError:
        raise ValueError(f'result_id must be a valid UUID, got: {result_id!r}') from None
    existing = session.get(DataSource, result_id)
    if existing:
        existing_owner = existing.created_by_analysis_id
        if existing_owner is not None and str(existing_owner) != analysis_id:
            raise ValueError(
                f"Output result_id '{result_id}' is already owned by analysis '{existing_owner}', cannot reuse it in analysis '{analysis_id}'",
            )
        if existing_owner is None and existing.created_by != DataSourceCreatedBy.ANALYSIS.value:
            raise ValueError(
                f"Output result_id '{result_id}' conflicts with an existing datasource not managed by analysis outputs",
            )
        next_config = dict(existing.config) if isinstance(existing.config, dict) else {}
        if config is not None:
            next_config = {**config, **next_config}
        next_config['analysis_tab_id'] = analysis_tab_id
        next_source_type = DataSourceType.require(source_type).value
        changed = (
            next_config != existing.config
            or existing.source_type != next_source_type
            or existing.created_by_analysis_id != analysis_id
            or existing.created_by != DataSourceCreatedBy.ANALYSIS.value
        )
        if changed:
            existing.revision += 1
        existing.config = next_config
        existing.source_type = next_source_type
        existing.created_by_analysis_id = analysis_id
        existing.created_by = DataSourceCreatedBy.ANALYSIS.value
        session.add(existing)
        session.flush()
        return
    datasource = DataSource(
        id=result_id,
        name=name or result_id,
        source_type=DataSourceType.require(source_type).value,
        config={**(config or {}), 'analysis_tab_id': analysis_tab_id},
        created_by_analysis_id=analysis_id,
        created_by=DataSourceCreatedBy.ANALYSIS.value,
        is_hidden=True,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(datasource)
    session.flush()


def create_database_datasource_record(
    session: Session,
    *,
    name: str,
    description: str | None,
    connection_string: str,
    query: str,
    branch: str,
    owner_id: str | None = None,
) -> DataSourceResponse:
    datasource = DataSource(
        id=str(uuid.uuid4()),
        name=name,
        description=DataSourceDescriptionModel.normalize_description(description),
        source_type=DataSourceType.DATABASE.value,
        config={
            'connection_string': connection_string,
            'query': query,
            'branch': branch,
        },
        owner_id=owner_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )

    session.add(datasource)
    session.commit()
    session.refresh(datasource)

    return DataSourceResponse.model_validate(datasource)


def create_analysis_datasource(
    session: Session,
    name: str,
    description: str | None,
    analysis_id: str,
    analysis_tab_id: str | None = None,
    is_hidden: bool = False,
    source_type: DataSourceType = DataSourceType.ANALYSIS,
) -> DataSourceResponse:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')
    datasource_id = str(uuid.uuid4())
    config = {}
    if analysis_tab_id:
        config['analysis_tab_id'] = analysis_tab_id

    datasource = DataSource(
        id=datasource_id,
        name=name,
        description=DataSourceDescriptionModel.normalize_description(description),
        source_type=source_type,
        config=config,
        created_by_analysis_id=analysis_id,
        created_by=DataSourceCreatedBy.ANALYSIS.value,
        is_hidden=is_hidden,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )

    session.add(datasource)
    session.commit()
    session.refresh(datasource)

    return DataSourceResponse.model_validate(datasource)


def _get_column_metadata_map(session: Session, datasource_id: str) -> dict[str, str | None]:
    rows = session.execute(
        select(DataSourceColumnMetadata).where(sa(DataSourceColumnMetadata.datasource_id == datasource_id)),
    ).scalars()
    return {row.column_name: row.description for row in rows}


def attach_column_descriptions(
    session: Session,
    datasource_id: str,
    schema_info: datasource_pb2.SchemaInfo,
) -> datasource_pb2.SchemaInfo:
    descriptions = _get_column_metadata_map(session, datasource_id)
    for column in schema_info.columns:
        description = descriptions.get(column.name)
        if description is not None:
            column.description = description
    return schema_info


def cached_schema(session: Session, datasource_id: str) -> datasource_pb2.SchemaInfo | None:
    """Return the DB-cached schema when it is present and well-formed.

    Cache writes are always complete extraction payloads (the worker is the
    only writer and only publishes full schemas), so a parseable entry is
    trusted as-is; otherwise ``None`` lets the caller fall back to the runtime.
    """
    datasource = session.get(DataSource, datasource_id)
    if datasource is None or not isinstance(datasource.schema_cache, dict):
        return None
    columns = datasource.schema_cache.get('columns')
    if not isinstance(columns, list) or not columns:
        return None
    if not all(
        isinstance(column, dict) and isinstance(column.get('name'), str) and isinstance(column.get('dtype'), str) and isinstance(column.get('nullable'), bool)
        for column in columns
    ):
        return None
    return schema_info_proto(datasource.schema_cache)


def update_column_descriptions(
    session: Session,
    datasource_id: str,
    payload: BatchColumnDescriptionUpdate,
    schema_info: datasource_pb2.SchemaInfo,
) -> datasource_pb2.SchemaInfo:
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        raise datasource_not_found(datasource_id)

    active_columns = {column.name for column in schema_info.columns}

    for patch in payload.columns:
        if patch.column_name not in active_columns:
            raise DataSourceValidationError(
                f'Column not found in active schema: {patch.column_name}',
                details={
                    'datasource_id': datasource_id,
                    'column_name': patch.column_name,
                },
            )

    existing = session.execute(
        select(DataSourceColumnMetadata).where(sa(DataSourceColumnMetadata.datasource_id == datasource_id)),
    ).scalars()
    existing_by_name = {row.column_name: row for row in existing}
    now = datetime.now(UTC).replace(tzinfo=None)

    for patch in payload.columns:
        description = ColumnDescriptionPatch.normalize_description(patch.description)
        row = existing_by_name.get(patch.column_name)
        if description is None:
            if row is not None:
                session.delete(row)
            continue
        if row is None:
            session.add(
                DataSourceColumnMetadata(
                    id=str(uuid.uuid4()),
                    datasource_id=datasource_id,
                    column_name=patch.column_name,
                    description=description,
                    created_at=now,
                    updated_at=now,
                ),
            )
            continue
        row.description = description
        row.updated_at = now
        session.add(row)

    session.commit()
    return attach_column_descriptions(session, datasource_id, schema_info)


def get_datasource(session: Session, datasource_id: str) -> DataSourceResponse:
    datasource = datasource_delete_service.get_active_datasource(session, datasource_id)
    response = _apply_display_name(DataSourceResponse.model_validate(datasource), datasource)
    response.config = _masked_config(response.config)
    response.output_of_tab_id = datasource.config.get('analysis_tab_id') if isinstance(datasource.config, dict) else None
    analysis_id = datasource.created_by_analysis_id
    last_build_completed_at = _last_build_completed_at_map(session, {analysis_id}).get(analysis_id) if analysis_id else None
    return _apply_last_data_update(response, datasource, last_build_completed_at)


def list_datasources(session: Session, include_hidden: bool = False) -> list[DataSourceListItem]:
    # Project only the scalar row_count path so list stays lightweight while
    # still deferring the full schema_cache (column metadata) payload.
    row_count_expr = sa(DataSource.schema_cache)['row_count'].as_string().label('list_row_count')
    query = select(DataSource, row_count_expr).options(defer(sa(DataSource.schema_cache))).where(col(DataSource.is_pending_delete).is_(False))
    if not include_hidden:
        query = query.where(col(DataSource.is_hidden).is_(False))
    rows = session.execute(query).all()
    pending_analysis_ids: set[str] = set()
    for ds, _ in rows:
        if _last_data_update_from_config(ds) is None and ds.created_by_analysis_id is not None:
            pending_analysis_ids.add(ds.created_by_analysis_id)
    last_build_completed_at = _last_build_completed_at_map(session, pending_analysis_ids)
    results: list[DataSourceListItem] = []
    for ds, list_row_count in rows:
        item = _apply_display_name(DataSourceListItem.model_validate(ds), ds)
        item.config = _masked_config(item.config)
        item.row_count = _coerce_row_count(list_row_count)
        item.output_of_tab_id = ds.config.get('analysis_tab_id') if isinstance(ds.config, dict) else None
        analysis_id = ds.created_by_analysis_id
        item = _apply_last_data_update(
            item,
            ds,
            last_build_completed_at.get(analysis_id) if analysis_id else None,
        )
        results.append(item)
    return results


def update_datasource(
    session: Session,
    datasource_id: str,
    update: DataSourceUpdate,
    *,
    resolved_excel_selection: tuple[str, int, int, int, int] | None = None,
    expected_revision: int | None = None,
) -> DataSourceResponse:
    datasource = datasource_delete_service.get_active_datasource(session, datasource_id, for_update=True)
    if expected_revision is not None and datasource.revision != expected_revision:
        raise DataSourceValidationError('Datasource changed while Excel selection was being resolved', details={'datasource_id': datasource_id})
    changed = False

    # Update name if provided
    if update.name is not None and update.name != datasource.name:
        datasource.name = update.name
        changed = True

    if 'description' in update.model_fields_set:
        description = DataSourceDescriptionModel.normalize_description(update.description)
        if description != datasource.description:
            datasource.description = description
            changed = True

    # Update is_hidden if provided
    if update.is_hidden is not None and update.is_hidden != datasource.is_hidden:
        datasource.is_hidden = update.is_hidden
        changed = True

    # Update config if provided
    if update.config is not None:
        if 'column_schema' in update.config:
            raise DataSourceValidationError(
                'Datasource schemas are read-only and cannot be modified',
                details={'datasource_id': datasource_id},
            )

        protected_snapshot_keys = {
            'snapshot_id',
            'snapshot_timestamp_ms',
            'current_snapshot_id',
            'current_snapshot_timestamp_ms',
            'time_travel_snapshot_id',
            'time_travel_snapshot_timestamp_ms',
            'time_travel_ui',
        }
        for key in protected_snapshot_keys:
            if key not in update.config:
                continue
            raise DataSourceValidationError(
                'Snapshot metadata fields are system-managed and cannot be modified',
                details={'datasource_id': datasource_id, 'field': key},
            )

        source_type = datasource.source_type_kind()
        immutable_keys = {
            DataSourceType.FILE: ['file_path'],
            DataSourceType.DATABASE: ['connection_string'],
            DataSourceType.ICEBERG: ['metadata_path'],
        }
        for key in immutable_keys.get(source_type, []):
            if key not in update.config:
                continue
            if update.config.get(key) == datasource.config.get(key):
                continue
            raise DataSourceValidationError(
                'Datasource location is immutable. Create a new datasource to change location.',
                details={'datasource_id': datasource_id, 'field': key},
            )

        # Check if parsing options changed (requires schema re-extraction)
        parsing_keys = [
            'csv_options',
            'sheet_name',
            'start_row',
            'start_col',
            'end_col',
            'end_row',
            'has_header',
            'skip_rows',
            'table_name',
            'named_range',
            'cell_range',
        ]
        parsing_changed = any(key in update.config for key in parsing_keys)

        next_config = {**datasource.config, **update.config}
        has_excel_bounds = any(
            key in update.config
            for key in [
                'sheet_name',
                'start_row',
                'start_col',
                'end_col',
                'end_row',
                'table_name',
                'named_range',
                'cell_range',
            ]
        )
        is_excel_file = DataSourceFileType.read(next_config.get('file_type'), default=None) == DataSourceFileType.EXCEL
        if source_type == DataSourceType.FILE and is_excel_file and has_excel_bounds:
            file_path = next_config.get('file_path')
            if not file_path:
                raise DataSourceValidationError(
                    'Excel datasource requires file_path',
                    details={'datasource_id': datasource_id},
                )
            if resolved_excel_selection is None:
                raise DataSourceValidationError(
                    'Excel selection must be resolved by the datasource compute worker',
                    details={'datasource_id': datasource_id},
                )
            resolved_sheet, resolved_start_row, resolved_start_col, resolved_end_col, resolved_end_row = resolved_excel_selection
            next_config = {
                **next_config,
                'sheet_name': resolved_sheet,
                'start_row': resolved_start_row,
                'start_col': resolved_start_col,
                'end_col': resolved_end_col,
                'end_row': resolved_end_row,
            }

        # Merge new config with existing config
        config_changed = next_config != datasource.config
        if config_changed:
            datasource.config = next_config
            changed = True
        if parsing_changed and config_changed:
            datasource.schema_cache = None

    if changed:
        datasource.revision += 1
        session.add(datasource)
        storage_cleanup_service.settle_publication(session, datasource.config)
    session.commit()
    session.refresh(datasource)

    logger.info(f'Updated datasource {datasource_id}')
    response = _apply_display_name(DataSourceResponse.model_validate(datasource), datasource)
    response.output_of_tab_id = datasource.config.get('analysis_tab_id') if isinstance(datasource.config, dict) else None
    analysis_id = datasource.created_by_analysis_id
    last_build_completed_at = _last_build_completed_at_map(session, {analysis_id}).get(analysis_id) if analysis_id else None
    return _apply_last_data_update(response, datasource, last_build_completed_at)


def delete_datasource(session: Session, datasource_id: str) -> None:
    # Keep internal onboarding deletion on the same tombstone/drain path as
    # the datasource API. The worker finalizes the row after active RID work
    # has settled and atomically records managed-storage cleanup intents.
    datasource_delete_service.request_delete(session, datasource_id)
    logger.info(f'Deleted datasource {datasource_id}')
