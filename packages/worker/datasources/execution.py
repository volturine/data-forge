from __future__ import annotations

import base64
import contextlib
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from itertools import chain
from time import monotonic
from typing import Any
from urllib.parse import unquote, urlsplit

import polars as pl
from polars.datatypes import Array, List, Struct
from pyiceberg.expressions import AlwaysTrue
from pyiceberg.table import Table

from dataforge_protocol import datasource_pb2
from datasources.datasource_loading import iter_datasource_batches, load_datasource
from datasources.schemas import (
    ColumnStats,
    ColumnStatsResponse,
    DataSourceRecord,
    SchemaDiff,
    SnapshotCompareResponse,
    SnapshotPreview,
)
from runtime.compute_manager import ProcessManager
from runtime.domain.datasource.source_types import DataSourceType
from runtime.domain.engine_runs.schemas import EngineRunKind, EngineRunStatus, SchemaDiffStatus
from runtime.exceptions import DataSourceConnectionError, DataSourceValidationError
from runtime.iceberg_catalog import ensure_catalog_namespace, load_runtime_catalog
from runtime.namespace import get_namespace
from runtime.object_store import (
    MultipartObjectUpload,
    is_object_store_url,
    join_object_store_url,
    object_store_storage_options,
    object_store_url,
    upload_bytes,
)
from runtime.worker_runtime_client import BackendWorkerRpcError, DatasourceMetadata, WorkerRuntimeClient

logger = logging.getLogger(__name__)
_MAX_DATASOURCE_MANIFEST_BYTES = 1024 * 1024


class DatasourcePublicationClaimLost(RuntimeError):
    """Raised when fenced publication loses ownership before commit."""


class DatasourceNotFound(RuntimeError):
    """Raised when a datasource metadata lookup fails."""


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


class _MultipartObjectSink:
    def __init__(self, upload: MultipartObjectUpload) -> None:
        self._upload = upload
        self._position = 0
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.closed:
            raise ValueError("Parquet staging stream is closed")
        view = memoryview(data)
        for offset in range(0, len(view), 1024 * 1024):
            chunk = view[offset : offset + 1024 * 1024]
            self._upload.write(bytes(chunk))
        self._position += len(data)
        return len(data)

    def tell(self) -> int:
        return self._position

    def flush(self) -> None:
        return None

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


def stage_datasource_to_object_store(
    source_config: Mapping[str, object],
    *,
    table_path: str,
    manifest_url: str,
    progress_callback: Callable[[dict[str, object]], None],
) -> dict[str, object]:
    import pyarrow.parquet as pq  # type: ignore[import-untyped]  # PyArrow does not ship typing metadata.

    if not is_object_store_url(table_path):
        raise ValueError("Datasource staging output must be an object-store table path")
    if not is_object_store_url(manifest_url):
        raise ValueError("Datasource staging manifest must be an object-store URL")
    batches = iter_datasource_batches(dict(source_config), batch_size=65_536)
    first = next(batches, None)
    if first is None:
        first = load_datasource(dict(source_config)).limit(0).collect(engine="streaming")
    coerce = _coerce_database_iceberg_compatible_lazyframe if source_config.get("source_type") == "database" else _coerce_iceberg_compatible_lazyframe
    first = coerce(first.lazy()).collect(engine="streaming")
    schema = first.schema
    arrow_schema = first.to_arrow().schema
    upload: MultipartObjectUpload | None = None
    sink: _MultipartObjectSink | None = None
    writer: Any = None
    file_paths: list[str] = []
    row_count = 0
    try:
        for batch in chain((first,), batches):
            progress_callback({"type": "datasource_batch", "row_count": row_count})
            batch = coerce(batch.lazy()).collect(engine="streaming")
            batch = batch.cast(schema, strict=False)
            for record_batch in batch.to_arrow().to_batches():
                if not record_batch.num_rows:
                    continue
                if writer is None:
                    parquet_url = join_object_store_url(table_path, "data.parquet")
                    upload = MultipartObjectUpload(parquet_url, content_type="application/vnd.apache.parquet")
                    sink = _MultipartObjectSink(upload)
                    writer = pq.ParquetWriter(sink, arrow_schema, compression="zstd")
                    file_paths.append(parquet_url)
                writer.write_batch(record_batch.cast(arrow_schema))
                row_count += record_batch.num_rows
        if writer is not None and upload is not None:
            writer.close()
            upload.commit()
        manifest = {
            "file_paths": file_paths,
            "arrow_schema": base64.b64encode(arrow_schema.serialize().to_pybytes()).decode("ascii"),
            "row_count": row_count,
            "columns": [{"name": name, "dtype": str(dtype), "nullable": True} for name, dtype in schema.items()],
        }
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
        if len(manifest_bytes) > _MAX_DATASOURCE_MANIFEST_BYTES:
            raise ValueError("Datasource staging manifest exceeds 1 MiB")
        upload_bytes(manifest_bytes, manifest_url, content_type="application/json")
    except BaseException:
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
        if upload is not None:
            upload.abort()
        raise
    finally:
        if sink is not None:
            sink.closed = True
        batches.close()
    return manifest


def import_staged_parquet_files(manifest: Mapping[str, object], *, staged_prefix: str, table_path: str, database_url: str) -> tuple[Table, str]:
    """Commit staged Parquet files as one snapshot on the published table.

    ``staged_prefix`` is the claim-scoped prefix holding the staged files
    (validation target); ``table_path`` is the stable published table location
    that accumulates one snapshot per ingest. When the existing table's schema
    cannot absorb the new schema, a fresh revision table is published instead
    (mirroring the build path) and its location is returned.
    """
    import pyarrow as pa  # type: ignore[import-untyped]  # PyArrow does not ship typing metadata.

    encoded_schema = manifest.get("arrow_schema")
    raw_paths = manifest.get("file_paths")
    if not isinstance(encoded_schema, str) or not isinstance(raw_paths, list):
        raise ValueError("Datasource Parquet manifest is incomplete")
    if len(encoded_schema) > _MAX_DATASOURCE_MANIFEST_BYTES:
        raise ValueError("Datasource Parquet manifest exceeds 1 MiB")
    try:
        schema_bytes = base64.b64decode(encoded_schema, validate=True)
        schema = pa.ipc.read_schema(pa.BufferReader(schema_bytes))
    except (ValueError, pa.ArrowException) as exc:
        raise ValueError("Datasource Parquet manifest contains an invalid Arrow schema") from exc

    expected = urlsplit(staged_prefix)
    expected_key_prefix = expected.path.rstrip("/") + "/"
    file_paths = [path for path in raw_paths if isinstance(path, str)]
    if len(file_paths) != len(raw_paths) or len(file_paths) != len(set(file_paths)):
        raise ValueError("Datasource Parquet manifest contains invalid file paths")
    for path in file_paths:
        parsed = urlsplit(path)
        path_segments = unquote(parsed.path).split("/")
        if (
            parsed.scheme != expected.scheme
            or parsed.netloc != expected.netloc
            or not parsed.path.startswith(expected_key_prefix)
            or any(segment in {".", ".."} for segment in path_segments)
            or parsed.query
            or parsed.fragment
            or not parsed.path.endswith(".parquet")
        ):
            raise ValueError("Datasource Parquet files must be inside the claim-scoped staging prefix")

    catalog = load_runtime_catalog(
        "local",
        type="sql",
        uri=database_url,
        warehouse=object_store_url("clean", namespace=get_namespace()),
        **object_store_storage_options(),
    )
    ensure_catalog_namespace(catalog, "clean")
    table_name = table_path.rstrip("/").split("/")[-2]
    identifier = f"clean.{table_name}"
    if catalog.table_exists(identifier):
        table = catalog.load_table(identifier)
        try:
            with table.transaction() as transaction:
                current_names = {field.name for field in transaction.table_metadata.schema().fields}
                new_names = set(schema.names)
                update = transaction.update_schema()
                for name in sorted(current_names - new_names):
                    update.delete_column(name)
                update.union_by_name(schema).commit()
                transaction.delete(delete_filter=AlwaysTrue())
                if file_paths:
                    transaction.add_files(file_paths)
            table.refresh()
            return table, table_path
        except Exception:
            # Incompatible schema evolution (e.g. a conflicting column type
            # change) cannot be applied in place. Publish a fresh revision
            # table exactly like the build path so re-ingest still succeeds;
            # snapshot history restarts only in this rare case.
            parent, branch_segment = table_path.rsplit("/", 1)
            revision_path = f"{parent}_rev{uuid.uuid4().hex[:8]}/{branch_segment}"
            revision_name = revision_path.rstrip("/").split("/")[-2]
            table = catalog.create_table(f"clean.{revision_name}", schema=schema, location=revision_path)
            if file_paths:
                with table.transaction() as transaction:
                    transaction.add_files(file_paths)
            table.refresh()
            return table, revision_path
    else:
        table = catalog.create_table(identifier, schema=schema, location=table_path)
        if file_paths:
            with table.transaction() as transaction:
                transaction.add_files(file_paths)
        table.refresh()
        return table, table_path


def _build_iceberg_config(
    target_path: str,
    branch: str,
    *,
    source_config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    cleaned = target_path.rstrip("/")
    parts = cleaned.split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid Iceberg table location: {target_path}")
    return {
        "catalog_type": "sql",
        "warehouse": object_store_url("clean", namespace=get_namespace()),
        "namespace": "clean",
        "table": parts[-2],
        "metadata_path": cleaned,
        "branch": branch,
        "source": dict(source_config) if source_config is not None else None,
        "namespace_name": get_namespace(),
        "reader": "native",
        "ingest": None,
    }


def _published_datasource_table_path(
    datasource_id: str,
    branch: str,
    *,
    namespace: str,
    existing_config: Mapping[str, object] | None = None,
) -> str:
    current_path = existing_config.get("metadata_path") if existing_config is not None else None
    if isinstance(current_path, str) and current_path.strip():
        return current_path
    return object_store_url("clean", datasource_id, branch, namespace=namespace)


def _set_snapshot_metadata(config: dict[str, object], table: Any | None) -> None:
    if table is None:
        return
    snapshot = table.current_snapshot()
    if snapshot is not None:
        config["current_snapshot_id"] = str(snapshot.snapshot_id)
        config["current_snapshot_timestamp_ms"] = int(snapshot.timestamp_ms)
        config["snapshot_id"] = str(snapshot.snapshot_id)
        config["snapshot_timestamp_ms"] = int(snapshot.timestamp_ms)
    # Readers resolve this exact file instead of listing the prefix: S-style
    # stores guarantee single-object read-after-write, prefix listings do not.
    metadata_location = table.metadata_location
    if metadata_location:
        config["metadata_file"] = metadata_location


def _get_first_non_null_samples(lazy: pl.LazyFrame, max_rows: int = 1000) -> dict[str, str | None]:
    columns = lazy.collect_schema().names()
    exprs = [pl.col(column).drop_nulls().first().alias(column) for column in columns]
    result = lazy.head(max_rows).select(exprs).collect()
    if result.height == 0:
        return dict.fromkeys(columns)
    return {column: (str(result[column][0]) if result[column][0] is not None else None) for column in columns}


def _require_metadata(client: WorkerRuntimeClient, *, namespace: str, datasource_id: str) -> DatasourceMetadata:
    from runtime.worker_runtime_client import frozen_datasource_metadata

    metadata = frozen_datasource_metadata(namespace, datasource_id)
    if metadata is None:
        metadata = client.datasource_metadata(namespace=namespace, datasource_id=datasource_id)
    if not metadata.found or metadata.id is None or metadata.source_type is None or metadata.config is None:
        raise DatasourceNotFound(datasource_id)
    return metadata


def _create_ingest_run(
    client: WorkerRuntimeClient,
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
    client: WorkerRuntimeClient,
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


def _fail_ingest_run(client: WorkerRuntimeClient, *, namespace: str, run_id: str, started: float, exc: Exception) -> None:
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
    client: WorkerRuntimeClient,
    *,
    manager: ProcessManager,
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
    from dataforge_protocol import compute_pb2, enums_pb2
    from runtime.compute_utils import await_engine_result

    metadata = _require_metadata(client, namespace=namespace, datasource_id=datasource_id)
    if metadata.revision is None:
        raise ValueError("Scheduled datasource snapshot is missing its revision")
    if not is_reingestable_raw(metadata):
        raise DataSourceValidationError(
            "This datasource has no external source to re-ingest. Schedule an analysis output instead.",
            details={"datasource_id": datasource_id},
        )
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id=datasource_id,
        resource_id=datasource_id,
    )
    config = dict(metadata.config or {})
    manifest_url = object_store_url("runtime-staging", "schedule-ingest", job_id, str(lease_generation), "manifest.json", namespace=namespace)
    try:
        with manager.acquire_engine(identity) as engine:
            branch = config.get("branch")
            if not isinstance(branch, str) or not branch:
                raise DataSourceValidationError("Datasource branch is required")
            branch_name = branch
            staging_id = f"{datasource_id}__claim_{staging_key.replace('-', '_')}"
            target = object_store_url("clean", staging_id, branch, namespace=namespace)
            client.register_datasource_stage(
                namespace=namespace,
                datasource_id=datasource_id,
                job_id=job_id,
                build_id=build_id,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_generation=lease_generation,
                prefix_url=target,
                manifest_url=manifest_url,
                catalog_identifier=f"clean.{target.rstrip('/').split('/')[-2]}",
            )
            source, _source_type = _external_source(metadata)
            engine_job = engine.datasource_job("datasource_stage", {"source_config": source, "table_path": target, "manifest_url": manifest_url})
            result = await_engine_result(engine, job_id=engine_job)
            if result.get("error") or not isinstance(result.get("data"), dict):
                raise DataSourceConnectionError("Scheduled datasource computation failed", details={"datasource_id": datasource_id})
            # Reuse the published table identity so snapshots from earlier
            # ingests remain readable; new datasources fall back to clean.<RID>.
            table_path = _published_datasource_table_path(datasource_id, branch, namespace=namespace, existing_config=config)
            table, published_table_path = import_staged_parquet_files(result["data"], staged_prefix=target, table_path=table_path, database_url=database_url)
            config.update(_build_iceberg_config(published_table_path, branch_name, source_config=source))
            _set_snapshot_metadata(config, table)
            config["ingest"] = {
                "ingested_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
                "mode": "schedule_ingest",
                "claim_prefix": target,
            }
            return client.publish_datasource_ingest(
                namespace=namespace,
                datasource_id=datasource_id,
                config=config,
                expected_revision=metadata.revision,
                schema_info=None,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_generation=lease_generation,
                job_id=job_id,
                build_id=build_id,
            )
    except BackendWorkerRpcError as exc:
        if exc.error_code == "FAILED_PRECONDITION":
            raise DatasourcePublicationClaimLost("Datasource publication claim is no longer active") from exc
        raise


def _schema_from_batches(config: dict[str, object]) -> datasource_pb2.SchemaInfo:
    result = datasource_pb2.SchemaInfo(row_count=0)
    samples: dict[str, str | None] = {}
    batches = iter_datasource_batches(config, batch_size=65_536)
    try:
        for batch in batches:
            if not result.columns:
                for name, dtype in batch.schema.items():
                    result.columns.add(name=name, dtype=str(dtype), nullable=True)
                samples = _get_first_non_null_samples(batch.head(1000).lazy())
            result.row_count += batch.height
        for column in result.columns:
            sample = samples.get(column.name)
            if sample is not None:
                column.sample_value = sample
        return result
    finally:
        batches.close()


def _schema_from_database(metadata: DatasourceMetadata, sheet_name: str | None) -> datasource_pb2.SchemaInfo:
    del sheet_name
    config = dict(metadata.config or {})
    if not isinstance(config.get("connection_string"), str) or not isinstance(config.get("query"), str):
        source = config.get("source")
        if isinstance(source, dict):
            config = dict(source)
    config["source_type"] = "database"
    try:
        return _schema_from_batches(config)
    except Exception as exc:
        raise DataSourceConnectionError(
            "Failed to read database datasource schema",
            details={"datasource_id": metadata.id},
        ) from exc


def _schema_from_file(metadata: DatasourceMetadata, sheet_name: str | None) -> datasource_pb2.SchemaInfo:
    config = {"source_type": metadata.source_type, **(metadata.config or {})}
    if sheet_name:
        config = {**config, "sheet_name": sheet_name}
    if metadata.source_type == "file" and config.get("file_type") == "excel":
        return _schema_from_batches(config)
    try:
        lazy = load_datasource(config)
    except Exception as exc:
        label = DataSourceType.require(metadata.source_type).category.value if metadata.source_type else "datasource"
        raise DataSourceConnectionError(
            f"Failed to load {label} datasource",
            details={"datasource_id": metadata.id, "source_type": metadata.source_type},
        ) from exc
    sample_values = _get_first_non_null_samples(lazy)
    schema = datasource_pb2.SchemaInfo(row_count=lazy.select(pl.len()).collect(engine="streaming").item())
    for name, dtype in lazy.collect_schema().items():
        column = schema.columns.add(name=name, dtype=str(dtype), nullable=True)
        sample_value = sample_values.get(name)
        if sample_value is not None:
            column.sample_value = sample_value
    return schema


def _extract_schema_from_metadata(metadata: DatasourceMetadata, sheet_name: str | None = None) -> datasource_pb2.SchemaInfo:
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


def get_datasource_schema_from_metadata(metadata: DatasourceMetadata, *, sheet_name: str | None = None) -> datasource_pb2.SchemaInfo:
    return _extract_schema_from_metadata(metadata, sheet_name=sheet_name)


def _attach_column_descriptions(metadata: DatasourceMetadata, schema_info: datasource_pb2.SchemaInfo) -> datasource_pb2.SchemaInfo:
    descriptions = metadata.column_descriptions or {}
    for column in schema_info.columns:
        description = descriptions.get(column.name)
        if description is not None:
            column.description = description
    return schema_info


def _build_snapshot_preview(lazy: pl.LazyFrame, schema: pl.Schema, row_limit: int) -> SnapshotPreview:
    data = lazy.limit(row_limit).collect(engine="streaming").to_dicts()
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
    stats_frame = lazy.select(exprs).collect(engine="streaming")
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


def compare_iceberg_snapshots_from_metadata(
    metadata: DatasourceMetadata,
    *,
    snapshot_a: str,
    snapshot_b: str,
    row_limit: int,
) -> SnapshotCompareResponse:
    if metadata.source_type != DataSourceType.ICEBERG.value:
        raise DataSourceValidationError(
            "Snapshot comparison is only available for Iceberg datasources",
            details={"datasource_id": metadata.id},
        )
    config_base = {"source_type": metadata.source_type, **(metadata.config or {})}
    config_a = {**config_base, "snapshot_id": snapshot_a}
    config_b = {**config_base, "snapshot_id": snapshot_b}
    lf_a = load_datasource(config_a)
    lf_b = load_datasource(config_b)
    schema_a = lf_a.collect_schema()
    schema_b = lf_b.collect_schema()
    row_count_a = lf_a.select(pl.len()).collect(engine="streaming").item()
    row_count_b = lf_b.select(pl.len()).collect(engine="streaming").item()
    return SnapshotCompareResponse(
        datasource_id=metadata.id or "",
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


def get_column_stats_from_metadata(
    metadata: DatasourceMetadata,
    *,
    column_name: str,
    use_sample: bool = True,
    sample_size: int = 10000,
    datasource_config: dict[str, object] | None = None,
) -> ColumnStatsResponse:
    config = {"source_type": metadata.source_type, **(metadata.config or {}), **(datasource_config or {})}
    lazy = load_datasource(config)
    schema = lazy.collect_schema()
    if column_name not in schema:
        raise ValueError(f"Column not found: {column_name}")
    if use_sample:
        lazy = lazy.limit(sample_size)
    column = pl.col(column_name)
    dtype = schema[column_name]
    expressions = [pl.len().alias("count"), column.null_count().alias("null_count")]
    if dtype.is_numeric():
        expressions.extend(
            [
                column.mean().alias("mean"),
                column.std().alias("std"),
                column.min().alias("min"),
                column.max().alias("max"),
                column.median().alias("median"),
                column.quantile(0.25).alias("q25"),
                column.quantile(0.75).alias("q75"),
            ]
        )
    else:
        expressions.append(column.n_unique().alias("unique"))
    if dtype == pl.String:
        length = column.str.len_chars()
        expressions.extend([length.min().alias("min_length"), length.max().alias("max_length"), length.mean().alias("avg_length")])
    stats = lazy.select(expressions).collect(engine="streaming").row(0, named=True)
    count = stats["count"]
    stats.update({"column": column_name, "dtype": str(dtype), "null_percentage": stats["null_count"] / count * 100.0 if count else 0.0})
    if dtype.is_numeric():
        minimum, maximum = stats["min"], stats["max"]
        histogram = []
        if minimum is not None and maximum is not None:
            if minimum == maximum:
                histogram = [{"start": float(minimum), "end": float(maximum), "count": count - stats["null_count"]}]
            else:
                width = (float(maximum) - float(minimum)) / 20
                bins = [(float(minimum) + index * width, float(minimum) + (index + 1) * width) for index in range(20)]
                counts = (
                    lazy.select(
                        [
                            ((column >= start) & (column <= end if index == 19 else column < end)).sum().alias(f"bin_{index}")
                            for index, (start, end) in enumerate(bins)
                        ]
                    )
                    .collect(engine="streaming")
                    .row(0)
                )
                histogram = [{"start": round(start, 4), "end": round(end, 4), "count": int(counts[index])} for index, (start, end) in enumerate(bins)]
        stats["histogram"] = histogram
    if dtype in (pl.String, pl.Boolean):
        stats["top_values"] = lazy.group_by(column_name).len(name="count").sort("count", descending=True).limit(5).collect(engine="streaming").to_dicts()
    return ColumnStatsResponse.model_validate(stats)
