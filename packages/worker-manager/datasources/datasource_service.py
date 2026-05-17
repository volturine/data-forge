import logging
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl
import psycopg
from contracts.datasource.models import DataSource, DataSourceColumnMetadata
from contracts.datasource.source_types import DataSourceFileType, DataSourceType
from core.config import settings
from core.exceptions import (
    DataSourceConnectionError,
    DataSourceNotFoundError,
    DataSourceValidationError,
)
from core.iceberg_metadata import sync_iceberg_schema
from core.namespace import get_namespace, namespace_paths
from pyiceberg.catalog import load_catalog
from pyiceberg.table import Table
from sqlmodel import Session, select

from datasources.datasource_schemas import (
    ColumnSchema,
    ColumnStats,
    ColumnStatsResponse,
    CSVOptions,
    DataSourceDescriptionModel,
    DataSourceResponse,
    SchemaDiff,
    SchemaDiffStatus,
    SchemaInfo,
    SnapshotCompareResponse,
    SnapshotPreview,
)
from operations.datasource import load_datasource

logger = logging.getLogger(__name__)


def _prepare_clean_target(clean_dir: Path, datasource_id: str, branch: str) -> Path:
    target = clean_dir / datasource_id / branch
    target.mkdir(parents=True, exist_ok=True)
    return target


def _write_iceberg_table(lazy: pl.LazyFrame, table_path: Path, build_mode: str) -> Table:
    catalog = load_catalog(
        "local",
        type="sql",
        uri=settings.database_url,
        warehouse=f"file://{table_path.parent}",
    )
    namespace = "clean"
    catalog.create_namespace_if_not_exists(namespace)
    identifier = f"{namespace}.{table_path.parent.name}"
    arrow_table = lazy.collect().to_arrow()
    if build_mode == "recreate" and catalog.table_exists(identifier):
        catalog.drop_table(identifier)
    if catalog.table_exists(identifier):
        table = catalog.load_table(identifier)
        if build_mode == "incremental":
            table.append(arrow_table)
        else:
            _sync_iceberg_schema(table, arrow_table.schema)
            table.overwrite(arrow_table)
        return table
    table = catalog.create_table(identifier, schema=arrow_table.schema, location=str(table_path))
    table.append(arrow_table)
    return table


def _build_iceberg_config(
    paths,
    target_path: Path,
    branch: str,
    source_config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "catalog_type": "sql",
        "catalog_uri": settings.database_url,
        "warehouse": f"file://{paths.clean_dir}",
        "namespace": "clean",
        "table": target_path.parent.name,
        "metadata_path": str(target_path.parent),
        "branch": branch,
        "source": dict(source_config) if source_config is not None else None,
        "namespace_name": get_namespace(),
        "refresh": None,
    }


def _sync_iceberg_schema(table: Table, new_schema: Any) -> None:
    sync_iceberg_schema(table, new_schema)


def _set_snapshot_metadata(config: dict[str, object], snapshot: Any | None) -> None:
    if snapshot is None:
        return
    config["current_snapshot_id"] = str(snapshot.snapshot_id)
    config["current_snapshot_timestamp_ms"] = int(snapshot.timestamp_ms)
    config["snapshot_id"] = str(snapshot.snapshot_id)
    config["snapshot_timestamp_ms"] = int(snapshot.timestamp_ms)


def _schema_cache_payload(schema_info: SchemaInfo) -> dict[str, Any]:
    columns = [column.model_dump(exclude={"description"}) for column in schema_info.columns]
    return schema_info.model_dump(exclude={"columns"}) | {"columns": columns}


def _get_first_non_null_samples(lazy: pl.LazyFrame, max_rows: int = 1000) -> dict[str, str | None]:
    columns = lazy.collect_schema().names()
    exprs = [pl.col(column).drop_nulls().first().alias(column) for column in columns]
    result = lazy.head(max_rows).select(exprs).collect()
    if result.height == 0:
        return dict.fromkeys(columns)
    return {column: (str(result[column][0]) if result[column][0] is not None else None) for column in columns}


def _schema_from_analysis(datasource: DataSource, sheet_name: str | None) -> SchemaInfo:
    del sheet_name
    raise DataSourceValidationError(
        "Schema extraction not supported for analysis datasources",
        details={"datasource_id": datasource.id},
    )


def _schema_from_database(datasource: DataSource, sheet_name: str | None) -> SchemaInfo:
    del sheet_name
    connection_string = datasource.config["connection_string"]
    query = datasource.config["query"]
    if not connection_string.lower().startswith("postgresql://"):
        raise DataSourceConnectionError("Database datasource connection string must be PostgreSQL")
    try:
        with psycopg.connect(connection_string, autocommit=True) as connection:
            frame = pl.read_database(query, connection)
    except Exception as exc:
        raise DataSourceConnectionError(
            DataSourceType.DATABASE.ingestion_error_message,
            details={
                "datasource_id": datasource.id,
                "source_type": datasource.source_type,
            },
        ) from exc
    sample_values = _get_first_non_null_samples(frame.lazy())
    columns = [
        ColumnSchema(
            name=name,
            dtype=str(dtype),
            nullable=True,
            sample_value=sample_values.get(name),
        )
        for name, dtype in frame.schema.items()
    ]
    return SchemaInfo(columns=columns, row_count=frame.height)


def _schema_from_file(datasource: DataSource, sheet_name: str | None) -> SchemaInfo:
    config = {"source_type": datasource.source_type, **datasource.config}
    if sheet_name:
        config = {**config, "sheet_name": sheet_name}
    try:
        lazy = load_datasource(config)
    except Exception as exc:
        label = DataSourceType.require(datasource.source_type).category.value
        raise DataSourceConnectionError(
            f"Failed to load {label} datasource",
            details={
                "datasource_id": datasource.id,
                "source_type": datasource.source_type,
            },
        ) from exc
    sample_values = _get_first_non_null_samples(lazy)
    columns = [
        ColumnSchema(
            name=name,
            dtype=str(dtype),
            nullable=True,
            sample_value=sample_values.get(name),
        )
        for name, dtype in lazy.collect_schema().items()
    ]
    return SchemaInfo(columns=columns, row_count=lazy.select(pl.len()).collect().item())


_SCHEMA_HANDLERS: dict[DataSourceType, Callable[[DataSource, str | None], SchemaInfo]] = {
    DataSourceType.ANALYSIS: _schema_from_analysis,
    DataSourceType.DATABASE: _schema_from_database,
    **{
        source_type: _schema_from_file
        for source_type in DataSourceType
        if source_type.is_file_based and source_type not in {DataSourceType.ANALYSIS, DataSourceType.DATABASE}
    },
}


def _extract_schema(datasource: DataSource, sheet_name: str | None = None) -> SchemaInfo:
    try:
        source_type = DataSourceType(datasource.source_type)
    except ValueError as exc:
        raise DataSourceConnectionError(
            "Unsupported datasource type for schema extraction",
            details={
                "datasource_id": datasource.id,
                "source_type": datasource.source_type,
            },
        ) from exc
    handler = _SCHEMA_HANDLERS.get(source_type)
    if handler is None:
        raise DataSourceConnectionError(
            "Unsupported datasource type for schema extraction",
            details={
                "datasource_id": datasource.id,
                "source_type": datasource.source_type,
            },
        )
    return handler(datasource, sheet_name)


def _persist_schema_cache(session: Session, datasource: DataSource) -> None:
    schema_info = _extract_schema(datasource)
    datasource.schema_cache = _schema_cache_payload(schema_info)
    session.add(datasource)
    session.commit()
    session.refresh(datasource)


def create_file_datasource(
    session: Session,
    name: str,
    description: str | None,
    file_path: str,
    file_type: str,
    options: dict | None = None,
    csv_options: CSVOptions | None = None,
    sheet_name: str | None = None,
    start_row: int | None = None,
    start_col: int | None = None,
    end_col: int | None = None,
    end_row: int | None = None,
    has_header: bool | None = None,
    table_name: str | None = None,
    named_range: str | None = None,
    cell_range: str | None = None,
    owner_id: str | None = None,
) -> DataSourceResponse:
    datasource_id = str(uuid.uuid4())
    resolved_path = Path(os.path.realpath(Path(file_path).resolve()))
    paths = namespace_paths()
    data_root = Path(os.path.realpath(paths.base_dir.resolve()))
    upload_root = Path(os.path.realpath(paths.upload_dir.resolve()))
    within_data_root = data_root in resolved_path.parents or data_root == resolved_path
    within_upload_root = upload_root in resolved_path.parents or upload_root == resolved_path
    if not (within_data_root or within_upload_root):
        raise ValueError(f"Path must be inside data directory: {data_root}")
    resolved_file_type = DataSourceFileType.require(file_type)
    resolved_file_type.validate_local_path(resolved_path)

    source_config = {
        "source_type": DataSourceType.FILE,
        "file_path": str(resolved_path),
        "file_type": resolved_file_type.value,
        "options": options or {},
        "csv_options": csv_options.model_dump() if csv_options else None,
        "sheet_name": sheet_name,
        "start_row": start_row,
        "start_col": start_col,
        "end_col": end_col,
        "end_row": end_row,
        "has_header": has_header,
        "table_name": table_name,
        "named_range": named_range,
        "cell_range": cell_range,
    }
    try:
        lazy = load_datasource(source_config)
    except Exception as exc:
        raise DataSourceValidationError(
            f"Failed to load file datasource for ingestion: {exc}",
            details={"file_path": str(resolved_path), "file_type": resolved_file_type.value},
        ) from exc
    target_path = _prepare_clean_target(paths.clean_dir, datasource_id, "master")
    snapshot = _write_iceberg_table(lazy, target_path, build_mode="recreate")
    config = _build_iceberg_config(paths, target_path, branch="master", source_config=source_config)
    _set_snapshot_metadata(config, snapshot.current_snapshot() if snapshot else None)
    datasource = DataSource(
        id=datasource_id,
        name=name,
        description=DataSourceDescriptionModel.normalize_description(description),
        source_type=DataSourceType.ICEBERG,
        config=config,
        owner_id=owner_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    try:
        _persist_schema_cache(session, datasource)
    except Exception as exc:
        session.rollback()
        raise DataSourceValidationError(
            f"Failed to extract schema for datasource {datasource_id}: {exc}",
            details={"datasource_id": datasource_id},
        ) from exc
    return DataSourceResponse.model_validate(datasource)


def create_database_datasource(
    session: Session,
    name: str,
    description: str | None,
    connection_string: str,
    query: str,
    branch: str = "master",
    owner_id: str | None = None,
) -> DataSourceResponse:
    datasource_id = str(uuid.uuid4())
    source_config = {
        "connection_string": connection_string,
        "query": query,
        "branch": branch,
    }
    try:
        lazy = load_datasource(
            {
                "source_type": DataSourceType.DATABASE,
                "connection_string": connection_string,
                "query": query,
            },
        )
    except Exception as exc:
        if connection_string.startswith("postgresql://"):
            datasource = DataSource(
                id=datasource_id,
                name=name,
                description=DataSourceDescriptionModel.normalize_description(description),
                source_type=DataSourceType.DATABASE,
                config=source_config,
                owner_id=owner_id,
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(datasource)
            session.commit()
            session.refresh(datasource)
            return DataSourceResponse.model_validate(datasource)
        raise DataSourceConnectionError(
            DataSourceType.DATABASE.ingestion_error_message,
            details={"connection_string": connection_string},
        ) from exc
    paths = namespace_paths()
    target_path = _prepare_clean_target(paths.clean_dir, datasource_id, branch)
    snapshot = _write_iceberg_table(lazy, target_path, build_mode="recreate")
    config = _build_iceberg_config(paths, target_path, branch=branch, source_config=source_config)
    _set_snapshot_metadata(config, snapshot.current_snapshot() if snapshot else None)
    datasource = DataSource(
        id=datasource_id,
        name=name,
        description=DataSourceDescriptionModel.normalize_description(description),
        source_type=DataSourceType.ICEBERG,
        config=config,
        owner_id=owner_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    try:
        _persist_schema_cache(session, datasource)
    except Exception as exc:
        session.rollback()
        raise DataSourceValidationError(
            f"Failed to extract schema for datasource {datasource_id}: {exc}",
            details={"datasource_id": datasource_id},
        ) from exc
    return DataSourceResponse.model_validate(datasource)


def create_iceberg_datasource(
    session: Session,
    name: str,
    description: str | None,
    source: dict,
    branch: str = "master",
    owner_id: str | None = None,
) -> DataSourceResponse:
    source_type = DataSourceType.read(source.get("source_type") if isinstance(source, dict) else None, default=None)
    if source_type is None or not source_type.supports_external_ingestion:
        raise DataSourceValidationError(
            "Iceberg datasource source_type is not supported for ingestion",
            details={"source_type": source_type},
        )
    if not isinstance(branch, str) or not branch.strip():
        raise DataSourceValidationError("Branch is required", details={"source_type": source_type})
    branch_name = branch.strip()
    try:
        if source_type == DataSourceType.DATABASE:
            connection_string = source.get("connection_string")
            query = source.get("query")
            if not connection_string or not query:
                raise DataSourceValidationError(
                    "Datasource source is missing connection details",
                    details={"source_type": source_type},
                )
            lazy = load_datasource(
                {
                    "source_type": DataSourceType.DATABASE,
                    "connection_string": connection_string,
                    "query": query,
                },
            )
        else:
            lazy = load_datasource(source)
    except DataSourceValidationError:
        raise
    except Exception as exc:
        raise DataSourceConnectionError(source_type.ingestion_error_message, details={"source_type": source_type}) from exc
    datasource_id = str(uuid.uuid4())
    paths = namespace_paths()
    target_path = _prepare_clean_target(paths.clean_dir, datasource_id, branch_name)
    snapshot = _write_iceberg_table(lazy, target_path, build_mode="recreate")
    config = _build_iceberg_config(paths, target_path, branch=branch_name, source_config=source)
    _set_snapshot_metadata(config, snapshot.current_snapshot() if snapshot else None)
    datasource = DataSource(
        id=datasource_id,
        name=name,
        description=DataSourceDescriptionModel.normalize_description(description),
        source_type=DataSourceType.ICEBERG,
        config=config,
        owner_id=owner_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    try:
        _persist_schema_cache(session, datasource)
    except Exception as exc:
        session.rollback()
        raise DataSourceValidationError(
            f"Failed to extract schema for datasource {datasource_id}: {exc}",
            details={"datasource_id": datasource_id},
        ) from exc
    return DataSourceResponse.model_validate(datasource)


def refresh_external_datasource(session: Session, datasource_id: str) -> DataSourceResponse:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(datasource_id)
    if not datasource.is_iceberg:
        raise DataSourceValidationError(
            "Refresh is only available for Iceberg datasources",
            details={"datasource_id": datasource_id},
        )
    source = datasource.external_source_config()
    if source is None:
        raise DataSourceValidationError(
            "Datasource has no external source configuration",
            details={"datasource_id": datasource_id},
        )
    source_type = datasource.external_source_type()
    if source_type is None or not datasource.is_refreshable_external:
        raise DataSourceValidationError(
            "Datasource source is not refreshable",
            details={"datasource_id": datasource_id, "source_type": source_type},
        )
    branch_raw = datasource.config.get("branch", source.get("branch"))
    if not isinstance(branch_raw, str) or not branch_raw.strip():
        raise DataSourceValidationError(
            "Datasource branch is required",
            details={"datasource_id": datasource_id},
        )
    try:
        if source_type == DataSourceType.DATABASE:
            connection_string = source.get("connection_string")
            query = source.get("query")
            if not connection_string or not query:
                raise DataSourceValidationError(
                    "Datasource source is missing connection details",
                    details={"datasource_id": datasource_id},
                )
            lazy = load_datasource(
                {
                    "source_type": DataSourceType.DATABASE,
                    "connection_string": connection_string,
                    "query": query,
                },
            )
        else:
            lazy = load_datasource(source)
    except DataSourceValidationError:
        raise
    except Exception as exc:
        raise DataSourceConnectionError(source_type.ingestion_error_message, details={"datasource_id": datasource_id}) from exc
    metadata_path = datasource.config.get("metadata_path")
    if not isinstance(metadata_path, str) or not metadata_path:
        raise DataSourceValidationError(
            "Datasource missing metadata_path",
            details={"datasource_id": datasource_id},
        )
    branch = branch_raw.strip()
    target_path = Path(metadata_path)
    if target_path.name != branch:
        target_path = _prepare_clean_target(namespace_paths().clean_dir, datasource_id, branch)
    snapshot = _write_iceberg_table(lazy, target_path, build_mode="full")
    next_config = dict(datasource.config)
    _set_snapshot_metadata(next_config, snapshot.current_snapshot() if snapshot else None)
    next_config["branch"] = branch
    next_config["metadata_path"] = str(target_path)
    next_config["source"] = source
    next_config["refresh"] = {"refreshed_at": datetime.now(UTC).replace(tzinfo=None).isoformat()}
    datasource.config = next_config
    datasource.schema_cache = None
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    return DataSourceResponse.model_validate(datasource)


def is_reingestable_raw_datasource(datasource: DataSource) -> bool:
    return datasource.is_reingestable_raw()


def refresh_datasource_for_schedule(session: Session, datasource_id: str) -> DataSourceResponse:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(datasource_id)
    if is_reingestable_raw_datasource(datasource):
        return refresh_external_datasource(session, datasource_id)
    schema = _extract_schema(datasource)
    next_config = dict(datasource.config) if isinstance(datasource.config, dict) else {}
    next_config["refresh"] = {
        "refreshed_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "mode": "schedule_schema_refresh",
    }
    datasource.config = next_config
    datasource.schema_cache = _schema_cache_payload(schema)
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    return DataSourceResponse.model_validate(datasource)


def _get_column_metadata_map(session: Session, datasource_id: str) -> dict[str, str | None]:
    rows = session.exec(
        select(DataSourceColumnMetadata).where(DataSourceColumnMetadata.datasource_id == datasource_id)  # type: ignore[arg-type]
    ).all()
    return {row.column_name: row.description for row in rows}


def _attach_column_descriptions(session: Session, datasource_id: str, schema_info: SchemaInfo) -> SchemaInfo:
    descriptions = _get_column_metadata_map(session, datasource_id)
    columns = [column.model_copy(update={"description": descriptions.get(column.name)}) for column in schema_info.columns]
    return schema_info.model_copy(update={"columns": columns})


def get_datasource_schema(
    session: Session,
    datasource_id: str,
    sheet_name: str | None = None,
    refresh: bool = False,
) -> SchemaInfo:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(datasource_id)
    if datasource.schema_cache and sheet_name is None and not refresh:
        try:
            cached = SchemaInfo.model_validate(datasource.schema_cache)
        except Exception:
            cached = None
        if cached is not None:
            has_samples = cached.columns and any(column.sample_value is not None for column in cached.columns)
            if cached.row_count is not None and has_samples:
                return _attach_column_descriptions(session, datasource_id, cached)
    schema_info = _extract_schema(datasource, sheet_name=sheet_name)
    if sheet_name is None:
        datasource.schema_cache = _schema_cache_payload(schema_info)
        session.add(datasource)
        session.commit()
        session.refresh(datasource)
    return _attach_column_descriptions(session, datasource_id, schema_info)


def _build_snapshot_preview(lazy: pl.LazyFrame, schema: pl.Schema, row_limit: int) -> SnapshotPreview:
    data = lazy.limit(row_limit).collect().to_dicts()
    return SnapshotPreview(
        columns=list(schema.keys()),
        column_types={name: str(dtype) for name, dtype in schema.items()},
        data=data,
        row_count=len(data),
    )


def _supports_min_max(dtype: pl.DataType) -> bool:
    return isinstance(
        dtype,
        (
            pl.Int8,
            pl.Int16,
            pl.Int32,
            pl.Int64,
            pl.UInt8,
            pl.UInt16,
            pl.UInt32,
            pl.UInt64,
            pl.Float32,
            pl.Float64,
            pl.Utf8,
            pl.Date,
            pl.Datetime,
            pl.Time,
        ),
    )


def _supports_unique(dtype: pl.DataType) -> bool:
    return isinstance(
        dtype,
        (
            pl.Int8,
            pl.Int16,
            pl.Int32,
            pl.Int64,
            pl.UInt8,
            pl.UInt16,
            pl.UInt32,
            pl.UInt64,
            pl.Float32,
            pl.Float64,
            pl.Utf8,
            pl.Boolean,
            pl.Date,
            pl.Datetime,
            pl.Time,
        ),
    )


def _build_snapshot_stats(lazy: pl.LazyFrame, schema: pl.Schema) -> list[ColumnStats]:
    exprs: list[pl.Expr] = []
    for name, dtype in schema.items():
        exprs.append(pl.col(name).null_count().alias(f"{name}__null_count"))
        if _supports_unique(dtype):
            exprs.append(pl.col(name).drop_nulls().n_unique().alias(f"{name}__unique_count"))
        if _supports_min_max(dtype):
            exprs.append(pl.col(name).min().alias(f"{name}__min"))
            exprs.append(pl.col(name).max().alias(f"{name}__max"))

    stats_frame = lazy.select(exprs).collect()
    results: list[ColumnStats] = []
    for name, dtype in schema.items():
        null_count = int(stats_frame[f"{name}__null_count"][0])
        unique_count = int(stats_frame[f"{name}__unique_count"][0]) if f"{name}__unique_count" in stats_frame.columns else None
        min_val = stats_frame[f"{name}__min"][0] if f"{name}__min" in stats_frame.columns else None
        max_val = stats_frame[f"{name}__max"][0] if f"{name}__max" in stats_frame.columns else None
        results.append(
            ColumnStats(
                column=name,
                dtype=str(dtype),
                null_count=null_count,
                unique_count=unique_count,
                min=min_val,
                max=max_val,
            )
        )
    return results


def _build_schema_diff(schema_a: pl.Schema, schema_b: pl.Schema) -> list[SchemaDiff]:
    diffs: list[SchemaDiff] = []
    cols_a = set(schema_a.keys())
    cols_b = set(schema_b.keys())
    for name in sorted(cols_a - cols_b):
        diffs.append(
            SchemaDiff(
                column=name,
                status=SchemaDiffStatus.REMOVED,
                type_a=str(schema_a[name]),
                type_b=None,
            )
        )
    for name in sorted(cols_b - cols_a):
        diffs.append(
            SchemaDiff(
                column=name,
                status=SchemaDiffStatus.ADDED,
                type_a=None,
                type_b=str(schema_b[name]),
            )
        )
    for name in sorted(cols_a & cols_b):
        dtype_a = str(schema_a[name])
        dtype_b = str(schema_b[name])
        if dtype_a != dtype_b:
            diffs.append(
                SchemaDiff(
                    column=name,
                    status=SchemaDiffStatus.TYPE_CHANGED,
                    type_a=dtype_a,
                    type_b=dtype_b,
                )
            )
    return diffs


def compare_iceberg_snapshots(
    session: Session,
    datasource_id: str,
    snapshot_a: str,
    snapshot_b: str,
    row_limit: int,
) -> SnapshotCompareResponse:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(datasource_id)
    if not datasource.is_iceberg:
        raise DataSourceValidationError(
            "Snapshot comparison is only available for Iceberg datasources",
            details={"datasource_id": datasource_id},
        )
    config_base = {"source_type": datasource.source_type, **datasource.config}
    config_a = {**config_base, "snapshot_id": snapshot_a}
    config_b = {**config_base, "snapshot_id": snapshot_b}
    lf_a = load_datasource(config_a)
    lf_b = load_datasource(config_b)
    schema_a = lf_a.collect_schema()
    schema_b = lf_b.collect_schema()
    row_count_a = lf_a.select(pl.len()).collect().item()
    row_count_b = lf_b.select(pl.len()).collect().item()
    return SnapshotCompareResponse(
        datasource_id=datasource_id,
        snapshot_a=snapshot_a,
        snapshot_b=snapshot_b,
        row_count_a=row_count_a,
        row_count_b=row_count_b,
        row_count_delta=row_count_b - row_count_a,
        schema_diff=_build_schema_diff(schema_a, schema_b),
        stats_a=_build_snapshot_stats(lf_a, schema_a),
        stats_b=_build_snapshot_stats(lf_b, schema_b),
        preview_a=_build_snapshot_preview(lf_a, schema_a, row_limit),
        preview_b=_build_snapshot_preview(lf_b, schema_b, row_limit),
    )


def _compute_histogram(series: pl.Series, bins: int = 20) -> list[dict[str, object]]:
    if series.is_empty():
        return []
    stats = series.drop_nulls()
    if stats.is_empty():
        return []
    stats = stats.cast(pl.Float64, strict=False)
    min_raw = stats.min()
    max_raw = stats.max()
    if min_raw is None or max_raw is None:
        return []
    min_val = float(cast(Any, min_raw))
    max_val = float(cast(Any, max_raw))
    if min_val == max_val:
        return [{"start": min_val, "end": max_val, "count": stats.len()}]
    width = (max_val - min_val) / bins
    result: list[dict[str, object]] = []
    for index in range(bins):
        start = min_val + index * width
        end = min_val + (index + 1) * width
        if index == bins - 1:
            count = series.filter((series >= start) & (series <= end)).len()
        else:
            count = series.filter((series >= start) & (series < end)).len()
        result.append({"start": round(start, 4), "end": round(end, 4), "count": count})
    return result


def get_column_stats(
    session: Session,
    datasource_id: str,
    column_name: str,
    use_sample: bool = True,
    sample_size: int = 10000,
    datasource_config: dict[str, object] | None = None,
) -> ColumnStatsResponse:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(datasource_id)
    config = {"source_type": datasource.source_type, **datasource.config}
    if datasource_config:
        config = {**config, **datasource_config}
    lazy = load_datasource(config)
    schema = lazy.collect_schema()
    if column_name not in schema:
        raise ValueError(f"Column not found: {column_name}")
    if use_sample:
        lazy = lazy.head(sample_size)  # type: ignore[attr-defined]
    frame = lazy.select([pl.col(column_name)]).collect()
    series = frame[column_name]
    dtype = schema[column_name]
    count = series.len()
    null_count = series.null_count()
    stats: dict[str, object] = {
        "column": column_name,
        "dtype": str(dtype),
        "count": count,
        "null_count": null_count,
        "null_percentage": (null_count / count * 100.0) if count > 0 else 0.0,
    }
    if isinstance(
        dtype,
        (
            pl.Int8,
            pl.Int16,
            pl.Int32,
            pl.Int64,
            pl.UInt8,
            pl.UInt16,
            pl.UInt32,
            pl.UInt64,
            pl.Float32,
            pl.Float64,
        ),
    ):
        non_null = series.drop_nulls()
        stats.update(
            {
                "mean": series.mean(),
                "std": series.std(),
                "min": series.min(),
                "max": series.max(),
                "median": series.median(),
                "q25": series.quantile(0.25),
                "q75": series.quantile(0.75),
                "histogram": _compute_histogram(non_null),
            }
        )
        return ColumnStatsResponse.model_validate(stats)
    if isinstance(dtype, pl.Utf8):
        length_series = series.str.len_chars()  # type: ignore[attr-defined]
        stats.update(
            {
                "unique": series.n_unique(),
                "min_length": length_series.min(),
                "max_length": length_series.max(),
                "avg_length": length_series.mean(),
                "top_values": series.value_counts().sort("count", descending=True).head(5).to_dicts(),
            }
        )
        return ColumnStatsResponse.model_validate(stats)
    if isinstance(dtype, pl.Boolean):
        value_counts = series.value_counts().sort("count", descending=True).to_dicts()
        stats.update({"unique": series.n_unique(), "top_values": value_counts})
        return ColumnStatsResponse.model_validate(stats)
    stats.update({"unique": series.n_unique()})
    return ColumnStatsResponse.model_validate(stats)
