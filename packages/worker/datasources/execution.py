from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, cast
from urllib.parse import urlparse

import polars as pl
import psycopg
from polars.datatypes import Array, List, Struct
from pyiceberg.table import Table
from sqlalchemy.exc import IntegrityError

from datasources.datasource_loading import load_datasource
from datasources.schemas import (
    ColumnSchema,
    ColumnStats,
    ColumnStatsResponse,
    CSVOptions,
    DataSourceDescriptionModel,
    DataSourceRecord,
    SchemaDiff,
    SchemaInfo,
    SnapshotCompareResponse,
    SnapshotPreview,
)
from runtime.domain.datasource.source_types import DataSourceFileType, DataSourceType
from runtime.domain.engine_runs.schemas import EngineRunKind, EngineRunStatus, SchemaDiffStatus
from runtime.exceptions import DataSourceConnectionError, DataSourceValidationError
from runtime.iceberg_catalog import load_runtime_catalog
from runtime.internal_api import BackendWorkerRpcError, DatasourceMetadata, WorkerInternalApiClient
from runtime.namespace import get_namespace
from runtime.object_store import (
    download_file,
    is_object_store_url,
    object_store_storage_options,
    object_store_url,
)

logger = logging.getLogger(__name__)


class DatasourcePublicationClaimLost(RuntimeError):
    """Raised when fenced publication loses ownership before commit."""


class DatasourceNotFound(RuntimeError):
    """Raised when a datasource metadata lookup fails."""


def _ensure_catalog_namespace(catalog, namespace: str) -> None:
    try:
        catalog.create_namespace_if_not_exists(namespace)
    except IntegrityError:
        logger.info("Namespace %s was created concurrently; continuing", namespace)


def _prepare_clean_target(datasource_id: str, branch: str) -> str:
    return object_store_url("namespaces", get_namespace(), "clean", datasource_id, branch)


def _coerce_iceberg_compatible_lazyframe(lazy: pl.LazyFrame) -> pl.LazyFrame:
    null_columns = [name for name, dtype in lazy.collect_schema().items() if dtype == pl.Null]
    if not null_columns:
        return lazy
    return lazy.with_columns([pl.col(name).cast(pl.String).alias(name) for name in null_columns])


def _normalize_iceberg_incompatible_value(value: Any) -> Any:
    if isinstance(value, pl.Series):
        return [_normalize_iceberg_incompatible_value(item) for item in value.to_list()]
    if isinstance(value, dict):
        return {key: _normalize_iceberg_incompatible_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_iceberg_incompatible_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_iceberg_incompatible_value(item) for item in value]
    return value


def _stringify_iceberg_incompatible_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    normalized = _normalize_iceberg_incompatible_value(value)
    try:
        return json.dumps(normalized, default=str, sort_keys=True)
    except TypeError:
        return str(normalized)


def _coerce_database_iceberg_compatible_lazyframe(lazy: pl.LazyFrame) -> pl.LazyFrame:
    schema = lazy.collect_schema()
    null_columns = [name for name, dtype in schema.items() if dtype == pl.Null]
    stringify_columns = [name for name, dtype in schema.items() if dtype == pl.Object or isinstance(dtype, (Struct, List, Array))]
    timezone_columns = [name for name, dtype in schema.items() if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None and dtype.time_zone != "UTC"]
    if not null_columns and not stringify_columns and not timezone_columns:
        return lazy
    expressions: list[pl.Expr] = [pl.col(name).cast(pl.String).alias(name) for name in null_columns]
    expressions.extend(pl.col(name).map_elements(_stringify_iceberg_incompatible_value, return_dtype=pl.String).alias(name) for name in stringify_columns)
    expressions.extend(pl.col(name).dt.convert_time_zone("UTC").alias(name) for name in timezone_columns)
    return lazy.with_columns(expressions)


@contextlib.contextmanager
def _materialized_file_source(source_config: dict[str, Any]):
    file_path = source_config.get("file_path")
    if not isinstance(file_path, str) or not is_object_store_url(file_path):
        yield source_config
        return
    suffix = Path(urlparse(file_path).path).suffix or f".{source_config.get('file_type') or 'dat'}"
    fd, temp_name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        download_file(file_path, temp_path)
        yield {**source_config, "file_path": str(temp_path)}
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()


def _validate_source_file_path(file_path: str, file_type: DataSourceFileType) -> str:
    del file_type
    from runtime.object_store import object_exists

    normalized = file_path.strip()
    if not is_object_store_url(normalized):
        raise ValueError("file_path must be an s3:// URL")
    if not object_exists(normalized):
        raise ValueError(f"Object not found: {normalized}")
    return normalized


def _validated_file_source_config(source: Mapping[str, object]) -> dict[str, object]:
    file_path = source.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise DataSourceValidationError("Datasource source is missing file_path")
    file_type = DataSourceFileType.read(source.get("file_type"), default=None)
    if file_type is None:
        raise DataSourceValidationError("Datasource source is missing file_type")
    return {
        **dict(source),
        "file_path": _validate_source_file_path(file_path, file_type),
        "file_type": file_type.value,
    }


def _write_iceberg_table(lazy: pl.LazyFrame, table_path: str, build_mode: str, *, database_url: str) -> Table:
    table_location = table_path.rstrip("/")
    location_parts = table_location.split("/")
    if len(location_parts) < 2:
        raise ValueError(f"Invalid Iceberg table location: {table_path}")
    table_name = location_parts[-2]
    catalog = load_runtime_catalog(
        "local",
        type="sql",
        uri=database_url,
        warehouse=object_store_url("namespaces", get_namespace(), "clean"),
        **object_store_storage_options(),
    )
    namespace = "clean"
    _ensure_catalog_namespace(catalog, namespace)
    identifier = f"{namespace}.{table_name}"
    arrow_table = _coerce_iceberg_compatible_lazyframe(lazy).collect().to_arrow()
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
    table = catalog.create_table(identifier, schema=arrow_table.schema, location=table_location)
    table.append(arrow_table)
    return table


def _build_iceberg_config(
    target_path: str,
    branch: str,
    *,
    database_url: str,
    source_config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    cleaned = target_path.rstrip("/")
    parts = cleaned.split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid Iceberg table location: {target_path}")
    return {
        "catalog_type": "sql",
        "catalog_uri": database_url,
        "warehouse": object_store_url("namespaces", get_namespace(), "clean"),
        "namespace": "clean",
        "table": parts[-2],
        "metadata_path": cleaned,
        "branch": branch,
        "source": dict(source_config) if source_config is not None else None,
        "namespace_name": get_namespace(),
        "reader": "native",
        "ingest": None,
    }


def _sync_iceberg_schema(table: Table, new_schema: Any) -> None:
    current = table.schema()
    current_names = {field.name for field in current.fields}
    new_names = set(new_schema.names)
    to_delete = current_names - new_names
    has_additions = bool(new_names - current_names)
    if not to_delete and not has_additions:
        return
    update = table.update_schema()
    for name in sorted(to_delete):
        update.delete_column(name)
    if has_additions:
        update.union_by_name(new_schema)
    update.commit()


def _set_snapshot_metadata(config: dict[str, object], snapshot: Any | None) -> None:
    if snapshot is None:
        return
    config["current_snapshot_id"] = str(snapshot.snapshot_id)
    config["current_snapshot_timestamp_ms"] = int(snapshot.timestamp_ms)
    config["snapshot_id"] = str(snapshot.snapshot_id)
    config["snapshot_timestamp_ms"] = int(snapshot.timestamp_ms)


def _get_first_non_null_samples(lazy: pl.LazyFrame, max_rows: int = 1000) -> dict[str, str | None]:
    columns = lazy.collect_schema().names()
    exprs = [pl.col(column).drop_nulls().first().alias(column) for column in columns]
    result = lazy.head(max_rows).select(exprs).collect()
    if result.height == 0:
        return dict.fromkeys(columns)
    return {column: (str(result[column][0]) if result[column][0] is not None else None) for column in columns}


def _require_metadata(client: WorkerInternalApiClient, *, namespace: str, datasource_id: str) -> DatasourceMetadata:
    metadata = client.datasource_metadata(namespace=namespace, datasource_id=datasource_id)
    if not metadata.found or metadata.id is None or metadata.source_type is None or metadata.config is None:
        raise DatasourceNotFound(datasource_id)
    return metadata


def _create_ingest_run(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    datasource_id: str,
    source_type: DataSourceType,
    branch: str,
    mode: str,
    triggered_by: str,
    request_json: Mapping[str, object] | None = None,
) -> str:
    payload: dict[str, object] = {
        "kind": EngineRunKind.INGEST.value,
        "mode": mode,
        "source_type": source_type.value,
        "branch": branch,
    }
    if request_json is not None:
        payload.update(dict(request_json))
    return client.create_engine_run(
        namespace=namespace,
        analysis_id=None,
        datasource_id=datasource_id,
        kind=EngineRunKind.INGEST.value,
        status=EngineRunStatus.RUNNING.value,
        request_json=payload,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        current_step="Reading source",
        triggered_by=triggered_by,
    )


def _complete_ingest_run(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    run_id: str,
    started: float,
    record: DataSourceRecord,
    original_source_type: DataSourceType,
    metadata_path: object | None = None,
) -> None:
    result_json: dict[str, object] = {
        "datasource_name": record.name,
        "storage_type": record.source_type,
        "original_source_type": original_source_type.value,
    }
    config = record.config if isinstance(record.config, dict) else {}
    snapshot_id = config.get("snapshot_id")
    if isinstance(snapshot_id, (str, int)) and str(snapshot_id):
        result_json["snapshot_id"] = str(snapshot_id)
    snapshot_timestamp_ms = config.get("snapshot_timestamp_ms")
    if isinstance(snapshot_timestamp_ms, int):
        result_json["snapshot_timestamp_ms"] = snapshot_timestamp_ms
    branch = config.get("branch")
    if isinstance(branch, str) and branch:
        result_json["branch"] = branch
    if metadata_path is not None:
        result_json["metadata_path"] = metadata_path
    client.update_engine_run(
        namespace=namespace,
        run_id=run_id,
        fields={
            "status": EngineRunStatus.SUCCESS.value,
            "completed_at": datetime.now(UTC).replace(tzinfo=None),
            "duration_ms": int((monotonic() - started) * 1000),
            "progress": 1.0,
            "current_step": None,
            "result_json": result_json,
        },
    )


def _fail_ingest_run(client: WorkerInternalApiClient, *, namespace: str, run_id: str, started: float, exc: Exception) -> None:
    with contextlib.suppress(Exception):
        client.update_engine_run(
            namespace=namespace,
            run_id=run_id,
            fields={
                "status": EngineRunStatus.FAILED.value,
                "completed_at": datetime.now(UTC).replace(tzinfo=None),
                "duration_ms": int((monotonic() - started) * 1000),
                "progress": 1.0,
                "current_step": None,
                "error_message": str(exc),
            },
        )


def _record_from_proto_dict(payload: dict[str, object]) -> DataSourceRecord:
    return DataSourceRecord.model_validate(payload)


def create_file_datasource(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    database_url: str,
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
) -> DataSourceRecord:
    datasource_id = str(uuid.uuid4())
    resolved_file_type = DataSourceFileType.require(file_type)
    resolved_file_path = _validate_source_file_path(file_path, resolved_file_type)
    source_config = _validated_file_source_config(
        {
            "source_type": DataSourceType.FILE.value,
            "file_path": resolved_file_path,
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
    )
    run_id = _create_ingest_run(
        client,
        namespace=namespace,
        datasource_id=datasource_id,
        source_type=DataSourceType.FILE,
        branch="master",
        mode="initial_ingest",
        triggered_by="manual",
        request_json={"file_type": resolved_file_type.value},
    )
    started = monotonic()
    try:
        try:
            with _materialized_file_source(dict(source_config)) as load_config:
                lazy = load_datasource(load_config)
                client.update_engine_run(
                    namespace=namespace,
                    run_id=run_id,
                    fields={"current_step": "Writing Iceberg", "progress": 0.6},
                )
                target_path = _prepare_clean_target(datasource_id, "master")
                snapshot = _write_iceberg_table(lazy, target_path, build_mode="recreate", database_url=database_url)
        except Exception as exc:
            raise DataSourceValidationError(
                f"Failed to load file datasource for ingestion: {exc}",
                details={"file_path": resolved_file_path, "file_type": resolved_file_type.value},
            ) from exc
        config = _build_iceberg_config(target_path, "master", database_url=database_url, source_config=source_config)
        _set_snapshot_metadata(config, snapshot.current_snapshot() if snapshot else None)
        record = client.publish_datasource_create(
            namespace=namespace,
            datasource_id=datasource_id,
            name=name,
            description=DataSourceDescriptionModel.normalize_description(description),
            source_type=DataSourceType.ICEBERG.value,
            config=config,
            owner_id=owner_id,
        )
        _complete_ingest_run(
            client,
            namespace=namespace,
            run_id=run_id,
            started=started,
            record=record,
            original_source_type=DataSourceType.FILE,
            metadata_path=config.get("metadata_path"),
        )
        return record
    except Exception as exc:
        _fail_ingest_run(client, namespace=namespace, run_id=run_id, started=started, exc=exc)
        raise


def create_database_datasource(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    database_url: str,
    name: str,
    description: str | None,
    connection_string: str,
    query: str,
    branch: str = "master",
    owner_id: str | None = None,
) -> DataSourceRecord:
    datasource_id = str(uuid.uuid4())
    source_config = {
        "source_type": DataSourceType.DATABASE.value,
        "connection_string": connection_string,
        "query": query,
        "branch": branch,
    }
    run_id = _create_ingest_run(
        client,
        namespace=namespace,
        datasource_id=datasource_id,
        source_type=DataSourceType.DATABASE,
        branch=branch,
        mode="initial_ingest",
        triggered_by="manual",
        request_json={"query": query},
    )
    started = monotonic()
    try:
        try:
            lazy = load_datasource(
                {
                    "source_type": DataSourceType.DATABASE.value,
                    "connection_string": connection_string,
                    "query": query,
                },
            )
        except Exception as exc:
            raise DataSourceConnectionError(
                DataSourceType.DATABASE.ingestion_error_message,
                details={"connection_string": connection_string},
            ) from exc
        client.update_engine_run(
            namespace=namespace,
            run_id=run_id,
            fields={"current_step": "Writing Iceberg", "progress": 0.6},
        )
        lazy = _coerce_database_iceberg_compatible_lazyframe(lazy)
        target_path = _prepare_clean_target(datasource_id, branch)
        snapshot = _write_iceberg_table(lazy, target_path, build_mode="recreate", database_url=database_url)
        config = _build_iceberg_config(target_path, branch, database_url=database_url, source_config=source_config)
        _set_snapshot_metadata(config, snapshot.current_snapshot() if snapshot else None)
        record = client.publish_datasource_create(
            namespace=namespace,
            datasource_id=datasource_id,
            name=name,
            description=DataSourceDescriptionModel.normalize_description(description),
            source_type=DataSourceType.ICEBERG.value,
            config=config,
            owner_id=owner_id,
        )
        _complete_ingest_run(
            client,
            namespace=namespace,
            run_id=run_id,
            started=started,
            record=record,
            original_source_type=DataSourceType.DATABASE,
            metadata_path=config.get("metadata_path"),
        )
        return record
    except Exception as exc:
        _fail_ingest_run(client, namespace=namespace, run_id=run_id, started=started, exc=exc)
        raise


def create_iceberg_datasource(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    database_url: str,
    name: str,
    description: str | None,
    source: dict,
    branch: str = "master",
    owner_id: str | None = None,
) -> DataSourceRecord:
    source_type = DataSourceType.read(source.get("source_type") if isinstance(source, dict) else None, default=None)
    if source_type is None or not source_type.supports_external_ingestion:
        raise DataSourceValidationError(
            "Iceberg datasource source_type is not supported for ingestion",
            details={"source_type": source_type},
        )
    if not isinstance(branch, str) or not branch.strip():
        raise DataSourceValidationError("Branch is required", details={"source_type": source_type})
    branch_name = branch.strip()
    datasource_id = str(uuid.uuid4())
    run_id = _create_ingest_run(
        client,
        namespace=namespace,
        datasource_id=datasource_id,
        source_type=source_type,
        branch=branch_name,
        mode="initial_ingest",
        triggered_by="manual",
        request_json={"query": source.get("query")} if source_type == DataSourceType.DATABASE else None,
    )
    started = monotonic()
    try:
        try:
            target_path = _prepare_clean_target(datasource_id, branch_name)
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
                        "source_type": DataSourceType.DATABASE.value,
                        "connection_string": connection_string,
                        "query": query,
                    },
                )
                lazy = _coerce_database_iceberg_compatible_lazyframe(lazy)
                client.update_engine_run(
                    namespace=namespace,
                    run_id=run_id,
                    fields={"current_step": "Writing Iceberg", "progress": 0.6},
                )
                snapshot = _write_iceberg_table(lazy, target_path, build_mode="recreate", database_url=database_url)
            else:
                file_source = _validated_file_source_config(source)
                with _materialized_file_source(dict(file_source)) as load_source:
                    lazy = load_datasource(load_source)
                    client.update_engine_run(
                        namespace=namespace,
                        run_id=run_id,
                        fields={"current_step": "Writing Iceberg", "progress": 0.6},
                    )
                    snapshot = _write_iceberg_table(lazy, target_path, build_mode="recreate", database_url=database_url)
        except DataSourceValidationError:
            raise
        except Exception as exc:
            raise DataSourceConnectionError(source_type.ingestion_error_message, details={"source_type": source_type}) from exc
        persisted_source = _validated_file_source_config(source) if source_type == DataSourceType.FILE else source
        config = _build_iceberg_config(target_path, branch_name, database_url=database_url, source_config=persisted_source)
        _set_snapshot_metadata(config, snapshot.current_snapshot() if snapshot else None)
        record = client.publish_datasource_create(
            namespace=namespace,
            datasource_id=datasource_id,
            name=name,
            description=DataSourceDescriptionModel.normalize_description(description),
            source_type=DataSourceType.ICEBERG.value,
            config=config,
            owner_id=owner_id,
        )
        _complete_ingest_run(
            client,
            namespace=namespace,
            run_id=run_id,
            started=started,
            record=record,
            original_source_type=source_type,
            metadata_path=config.get("metadata_path"),
        )
        return record
    except Exception as exc:
        _fail_ingest_run(client, namespace=namespace, run_id=run_id, started=started, exc=exc)
        raise


def _external_source(metadata: DatasourceMetadata) -> tuple[dict[str, object], DataSourceType]:
    if metadata.source_type != DataSourceType.ICEBERG.value:
        raise DataSourceValidationError(
            "Ingest is only available for Iceberg datasources",
            details={"datasource_id": metadata.id},
        )
    config = metadata.config or {}
    source = config.get("source")
    if not isinstance(source, dict):
        raise DataSourceValidationError(
            "Datasource has no external source configuration",
            details={"datasource_id": metadata.id},
        )
    source_type = DataSourceType.read(source.get("source_type"), default=None)
    if source_type is None or not source_type.supports_external_ingestion:
        raise DataSourceValidationError(
            "Datasource source is not ingestable",
            details={"datasource_id": metadata.id, "source_type": source_type},
        )
    return source, source_type


def ingest_external_datasource(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    database_url: str,
    datasource_id: str,
    staging_key: str,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    compute_request_id: str | None = None,
    job_id: str | None = None,
    build_id: str | None = None,
    triggered_by: str = "manual",
    mode: str = "manual_ingest",
) -> DataSourceRecord:
    metadata = _require_metadata(client, namespace=namespace, datasource_id=datasource_id)
    source, source_type = _external_source(metadata)
    config = dict(metadata.config or {})
    branch_raw = config.get("branch", source.get("branch"))
    if not isinstance(branch_raw, str) or not branch_raw.strip():
        raise DataSourceValidationError(
            "Datasource branch is required",
            details={"datasource_id": datasource_id},
        )
    expected_revision = int(metadata.revision or 1)
    run_id = _create_ingest_run(
        client,
        namespace=namespace,
        datasource_id=datasource_id,
        source_type=source_type,
        branch=branch_raw.strip(),
        mode=mode,
        triggered_by=triggered_by,
        request_json={"query": source.get("query")} if source_type == DataSourceType.DATABASE else None,
    )
    started = monotonic()
    try:
        metadata_path = config.get("metadata_path")
        if not isinstance(metadata_path, str) or not metadata_path:
            raise DataSourceValidationError(
                "Datasource missing metadata_path",
                details={"datasource_id": datasource_id},
            )
        branch = branch_raw.strip()
        safe_staging_key = re.sub(r"[^a-zA-Z0-9_]+", "_", staging_key).strip("_")
        if not safe_staging_key:
            raise ValueError("Datasource staging key must contain an alphanumeric character")
        target_path = _prepare_clean_target(f"{datasource_id}__claim_{safe_staging_key}", branch)
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
                        "source_type": DataSourceType.DATABASE.value,
                        "connection_string": connection_string,
                        "query": query,
                    },
                )
                lazy = _coerce_database_iceberg_compatible_lazyframe(lazy)
                client.update_engine_run(
                    namespace=namespace,
                    run_id=run_id,
                    fields={"current_step": "Writing Iceberg", "progress": 0.6},
                )
                snapshot = _write_iceberg_table(lazy, target_path, build_mode="full", database_url=database_url)
            else:
                file_source = _validated_file_source_config(source)
                with _materialized_file_source(dict(file_source)) as load_source:
                    lazy = load_datasource(load_source)
                    client.update_engine_run(
                        namespace=namespace,
                        run_id=run_id,
                        fields={"current_step": "Writing Iceberg", "progress": 0.6},
                    )
                    snapshot = _write_iceberg_table(lazy, target_path, build_mode="full", database_url=database_url)
        except DataSourceValidationError:
            raise
        except Exception as exc:
            raise DataSourceConnectionError(source_type.ingestion_error_message, details={"datasource_id": datasource_id}) from exc
        next_config = dict(config)
        _set_snapshot_metadata(next_config, snapshot.current_snapshot() if snapshot else None)
        next_config["branch"] = branch
        next_config["metadata_path"] = target_path
        next_config["source"] = _validated_file_source_config(source) if source_type == DataSourceType.FILE else source
        next_config["ingest"] = {"ingested_at": datetime.now(UTC).replace(tzinfo=None).isoformat()}
        try:
            record = client.publish_datasource_ingest(
                namespace=namespace,
                datasource_id=datasource_id,
                config=next_config,
                expected_revision=expected_revision,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_generation=lease_generation,
                compute_request_id=compute_request_id,
                job_id=job_id,
                build_id=build_id,
            )
        except BackendWorkerRpcError as exc:
            if exc.error_code == "FAILED_PRECONDITION":
                raise DatasourcePublicationClaimLost(str(exc) or "Datasource publication claim is no longer active") from exc
            raise
        _complete_ingest_run(
            client,
            namespace=namespace,
            run_id=run_id,
            started=started,
            record=record,
            original_source_type=source_type,
            metadata_path=next_config.get("metadata_path"),
        )
        return record
    except Exception as exc:
        _fail_ingest_run(client, namespace=namespace, run_id=run_id, started=started, exc=exc)
        raise


def is_reingestable_raw(metadata: DatasourceMetadata) -> bool:
    if metadata.source_type != DataSourceType.ICEBERG.value:
        return False
    if metadata.created_by == "analysis":
        return False
    try:
        _external_source(metadata)
    except DataSourceValidationError:
        return False
    return True


def ingest_datasource_for_schedule(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    database_url: str,
    datasource_id: str,
    staging_key: str,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    job_id: str,
    build_id: str,
) -> DataSourceRecord:
    metadata = _require_metadata(client, namespace=namespace, datasource_id=datasource_id)
    if is_reingestable_raw(metadata):
        return ingest_external_datasource(
            client,
            namespace=namespace,
            database_url=database_url,
            datasource_id=datasource_id,
            staging_key=staging_key,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            job_id=job_id,
            build_id=build_id,
            triggered_by="schedule",
            mode="schedule_ingest",
        )
    schema = _extract_schema_from_metadata(metadata)
    next_config = dict(metadata.config or {})
    next_config["ingest"] = {
        "ingested_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "mode": "schedule_schema_ingest",
    }
    try:
        return client.publish_datasource_ingest(
            namespace=namespace,
            datasource_id=datasource_id,
            config=next_config,
            expected_revision=int(metadata.revision or 1),
            schema_info=schema,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            job_id=job_id,
            build_id=build_id,
        )
    except BackendWorkerRpcError as exc:
        if exc.error_code == "FAILED_PRECONDITION":
            raise DatasourcePublicationClaimLost(str(exc) or "Datasource publication claim is no longer active") from exc
        raise


def _schema_from_database(metadata: DatasourceMetadata, sheet_name: str | None) -> SchemaInfo:
    del sheet_name
    config = metadata.config or {}
    connection_string = config.get("connection_string")
    query = config.get("query")
    if not isinstance(connection_string, str) or not isinstance(query, str):
        source = config.get("source")
        if isinstance(source, dict):
            connection_string = source.get("connection_string")
            query = source.get("query")
    if not isinstance(connection_string, str) or not isinstance(query, str):
        raise DataSourceConnectionError("Datasource missing database connection details", details={"datasource_id": metadata.id})
    if not connection_string.lower().startswith("postgresql://"):
        raise DataSourceConnectionError("Database datasource connection string must be PostgreSQL")
    try:
        with psycopg.connect(connection_string, autocommit=True) as connection:
            frame = pl.read_database(query, connection)
    except Exception as exc:
        raise DataSourceConnectionError(
            DataSourceType.DATABASE.ingestion_error_message,
            details={"datasource_id": metadata.id, "source_type": metadata.source_type},
        ) from exc
    sample_values = _get_first_non_null_samples(frame.lazy())
    columns = [ColumnSchema(name=name, dtype=str(dtype), nullable=True, sample_value=sample_values.get(name)) for name, dtype in frame.schema.items()]
    return SchemaInfo(columns=columns, row_count=frame.height)


def _schema_from_file(metadata: DatasourceMetadata, sheet_name: str | None) -> SchemaInfo:
    config = {"source_type": metadata.source_type, **(metadata.config or {})}
    if sheet_name:
        config = {**config, "sheet_name": sheet_name}
    try:
        lazy = load_datasource(config)
    except Exception as exc:
        label = DataSourceType.require(metadata.source_type).category.value if metadata.source_type else "datasource"
        raise DataSourceConnectionError(
            f"Failed to load {label} datasource",
            details={"datasource_id": metadata.id, "source_type": metadata.source_type},
        ) from exc
    sample_values = _get_first_non_null_samples(lazy)
    columns = [ColumnSchema(name=name, dtype=str(dtype), nullable=True, sample_value=sample_values.get(name)) for name, dtype in lazy.collect_schema().items()]
    return SchemaInfo(columns=columns, row_count=lazy.select(pl.len()).collect().item())


def _extract_schema_from_metadata(metadata: DatasourceMetadata, sheet_name: str | None = None) -> SchemaInfo:
    try:
        if metadata.source_type is None:
            raise ValueError("Datasource metadata is missing source_type")
        source_type = DataSourceType.require(metadata.source_type)
    except ValueError as exc:
        raise DataSourceConnectionError(
            "Unsupported datasource type for schema extraction",
            details={"datasource_id": metadata.id, "source_type": metadata.source_type},
        ) from exc
    if source_type == DataSourceType.ANALYSIS:
        raise DataSourceValidationError(
            "Schema extraction not supported for analysis datasources",
            details={"datasource_id": metadata.id},
        )
    if source_type == DataSourceType.DATABASE:
        return _schema_from_database(metadata, sheet_name)
    return _schema_from_file(metadata, sheet_name)


def _attach_column_descriptions(metadata: DatasourceMetadata, schema_info: SchemaInfo) -> SchemaInfo:
    descriptions = metadata.column_descriptions or {}
    columns = [column.model_copy(update={"description": descriptions.get(column.name)}) for column in schema_info.columns]
    return schema_info.model_copy(update={"columns": columns})


def get_datasource_schema(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    datasource_id: str,
    sheet_name: str | None = None,
    refresh: bool = False,
) -> SchemaInfo:
    metadata = _require_metadata(client, namespace=namespace, datasource_id=datasource_id)
    if metadata.schema_cache and sheet_name is None and not refresh:
        try:
            cached = SchemaInfo.model_validate(metadata.schema_cache)
        except Exception:
            cached = None
        if cached is not None:
            has_samples = cached.columns and any(column.sample_value is not None for column in cached.columns)
            if cached.row_count is not None and has_samples:
                return _attach_column_descriptions(metadata, cached)
    schema_info = _extract_schema_from_metadata(metadata, sheet_name=sheet_name)
    if sheet_name is None:
        published = client.publish_datasource_schema_cache(
            namespace=namespace,
            datasource_id=datasource_id,
            schema_info=schema_info,
        )
        return published
    return _attach_column_descriptions(metadata, schema_info)


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
        diffs.append(SchemaDiff(column=name, status=SchemaDiffStatus.REMOVED.value, type_a=str(schema_a[name]), type_b=None))
    for name in sorted(cols_b - cols_a):
        diffs.append(SchemaDiff(column=name, status=SchemaDiffStatus.ADDED.value, type_a=None, type_b=str(schema_b[name])))
    for name in sorted(cols_a & cols_b):
        dtype_a = str(schema_a[name])
        dtype_b = str(schema_b[name])
        if dtype_a != dtype_b:
            diffs.append(SchemaDiff(column=name, status=SchemaDiffStatus.TYPE_CHANGED.value, type_a=dtype_a, type_b=dtype_b))
    return diffs


def compare_iceberg_snapshots(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    datasource_id: str,
    snapshot_a: str,
    snapshot_b: str,
    row_limit: int,
) -> SnapshotCompareResponse:
    metadata = _require_metadata(client, namespace=namespace, datasource_id=datasource_id)
    if metadata.source_type != DataSourceType.ICEBERG.value:
        raise DataSourceValidationError(
            "Snapshot comparison is only available for Iceberg datasources",
            details={"datasource_id": datasource_id},
        )
    config_base = {"source_type": metadata.source_type, **(metadata.config or {})}
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
        count = series.filter((series >= start) & (series <= end)).len() if index == bins - 1 else series.filter((series >= start) & (series < end)).len()
        result.append({"start": round(start, 4), "end": round(end, 4), "count": count})
    return result


def get_column_stats(
    client: WorkerInternalApiClient,
    *,
    namespace: str,
    datasource_id: str,
    column_name: str,
    use_sample: bool = True,
    sample_size: int = 10000,
    datasource_config: dict[str, object] | None = None,
) -> ColumnStatsResponse:
    metadata = _require_metadata(client, namespace=namespace, datasource_id=datasource_id)
    config = {"source_type": metadata.source_type, **(metadata.config or {})}
    if datasource_config:
        config = {**config, **datasource_config}
    lazy = load_datasource(config)
    schema = lazy.collect_schema()
    if column_name not in schema:
        raise ValueError(f"Column not found: {column_name}")
    if use_sample:
        lazy = lazy.limit(sample_size)
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
        length_series = pl.select(pl.Series(column_name, series).str.len_chars()).to_series()
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
