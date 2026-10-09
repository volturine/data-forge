from __future__ import annotations

import contextlib
import io
import json
import multiprocessing
import os
import socket

import grpc
import polars as pl
import pyarrow as pa
import pytest
from openpyxl import Workbook

from dataforge_protocol import compute_pb2, compute_worker_runtime_pb2, compute_worker_runtime_pb2_grpc, enums_pb2
from datasources import execution
from datasources.excel_batches import iter_excel_batches
from runtime import compute_request_runtime
from runtime.compute_worker_server import COMPUTE_WORKER_PROTOCOL_VERSION, run_compute_worker_server
from runtime.exceptions import StaleComputeInputError
from runtime.worker_runtime_client import DatasourceMetadata


def _run_engine(port: int) -> None:
    run_compute_worker_server(host="127.0.0.1", port=port, compute_worker_identity="source-1", token="engine-test-token", heartbeat_timeout_seconds=60)


def test_datasource_schema_executes_in_separate_engine_pid_and_survives_engine_crash(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")

    def fail_manager_schema(*_args, **_kwargs):
        raise AssertionError("Manager parsed user data")

    monkeypatch.setattr(execution, "get_datasource_schema_from_metadata", fail_manager_schema)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = multiprocessing.get_context("spawn").Process(target=_run_engine, args=(port,))
    process.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        grpc.channel_ready_future(channel).result(timeout=30)
        stub = compute_worker_runtime_pb2_grpc.PolarsComputeWorkerServiceStub(channel)
        payload = {
            "resource_id": "source-1",
            "datasource_metadata": {"id": "source-1", "source_type": "file", "revision": 1, "config": {"file_path": str(source), "file_type": "csv"}},
        }
        stub.SubmitJob(
            compute_worker_runtime_pb2.ComputeWorkerSubmitJobRequest(
                protocol_version=COMPUTE_WORKER_PROTOCOL_VERSION,
                job_id="schema-1",
                kind="datasource_schema",
                payload_json=json.dumps(payload).encode(),
            ),
            metadata=(("x-compute-worker-token", "engine-test-token"),),
            timeout=10,
        )
        events = list(
            stub.WatchJob(
                compute_worker_runtime_pb2.ComputeWorkerWatchJobRequest(job_id="schema-1"),
                metadata=(("x-compute-worker-token", "engine-test-token"),),
                timeout=30,
            )
        )
        result = json.loads(events[-1].result.data_json)
        assert process.pid != os.getpid()
        assert result["columns"][0]["name"] == "value"
        assert result["row_count"] == 2
        process.kill()
        process.join(timeout=10)
        with pytest.raises(grpc.RpcError):
            stub.Health(compute_worker_runtime_pb2.ComputeWorkerHealthRequest(), metadata=(("x-compute-worker-token", "engine-test-token"),), timeout=1)
        assert pl.DataFrame({"manager": [1]}).height == 1
    finally:
        channel.close()
        if process.is_alive():
            process.kill()
        process.join(timeout=10)


def test_frozen_revision_change_fails_before_any_engine_submission() -> None:
    command = compute_pb2.ComputeCommand()
    command.input_revisions.add(datasource_id="source-1", revision=1)
    claimed = compute_request_runtime.ClaimedComputeRequest(
        id="request-1",
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command_envelope=compute_pb2.ComputeCommandEnvelope(command=command),
        worker_id="worker-1",
        claim_token="claim-1",
        lease_generation=1,
        lease_ttl_seconds=300,
    )

    class Client:
        def datasource_metadata(self, **_kwargs):
            return DatasourceMetadata(
                found=True,
                id="source-1",
                name="Current",
                source_type="file",
                config={"file_path": "s3://default/uploads/new.csv"},
                schema_cache=None,
                is_hidden=False,
                revision=2,
            )

    with pytest.raises(StaleComputeInputError):
        compute_request_runtime._freeze_claimed_input_metadata(Client(), claimed)


@pytest.mark.parametrize("empty_first_batch", [False, True])
def test_staging_streams_multiple_parquet_batches_without_whole_source_collection(monkeypatch, empty_first_batch: bool) -> None:
    import pyarrow.parquet as pq

    uploads = []
    saved_manifests = []

    class Upload:
        def __init__(self, *_args, **_kwargs):
            self.buffer = io.BytesIO()
            self.committed = False
            uploads.append(self)

        def write(self, data):
            self.buffer.write(data)

        def commit(self):
            self.committed = True

        def abort(self):
            raise AssertionError("Valid staging unexpectedly aborted")

    def batches(*_args, **_kwargs):
        yield pl.DataFrame(schema={"value": pl.Null}) if empty_first_batch else pl.DataFrame({"value": [None]})
        for index in range(2):
            yield pl.DataFrame({"value": list(range(index * 16, (index + 1) * 16))})

    monkeypatch.setattr(execution, "MultipartObjectUpload", Upload)
    monkeypatch.setattr(execution, "iter_datasource_batches", batches)
    monkeypatch.setattr(execution, "load_datasource", lambda *_args: pytest.fail("Whole source loaded"))
    monkeypatch.setattr(execution, "upload_bytes", lambda data, url, **_kwargs: saved_manifests.append((data, url)))
    result = execution.stage_datasource_to_object_store(
        {"source_type": "file"},
        table_path="s3://default/clean/source__claim_attempt/master",
        manifest_url="s3://default/runtime-staging/datasource-stage/request-1/1/manifest.json",
        progress_callback=lambda _event: None,
    )
    parquet = pq.read_table(pa.BufferReader(uploads[0].buffer.getvalue()))
    assert uploads[0].committed
    assert parquet.schema.names == ["value"]
    assert parquet.num_rows == (32 if empty_first_batch else 33)
    assert "0" in parquet.column("value").to_pylist()
    assert result["row_count"] == (32 if empty_first_batch else 33)
    assert result["file_paths"] == ["s3://default/clean/source__claim_attempt/master/data.parquet"]
    assert isinstance(result["arrow_schema"], str)
    assert saved_manifests[0][1].endswith("/manifest.json")
    assert json.loads(saved_manifests[0][0]) == result


def test_empty_datasource_writes_schema_manifest_without_zero_row_parquet(monkeypatch) -> None:
    saved_manifests = []

    class UnexpectedUpload:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("Empty datasource must not upload a zero-row Parquet object")

    monkeypatch.setattr(execution, "MultipartObjectUpload", UnexpectedUpload)

    def no_batches(*_args, **_kwargs):
        yield from ()

    monkeypatch.setattr(execution, "iter_datasource_batches", no_batches)
    monkeypatch.setattr(execution, "load_datasource", lambda *_args: pl.DataFrame(schema={"empty": pl.String}).lazy())
    monkeypatch.setattr(execution, "upload_bytes", lambda data, url, **_kwargs: saved_manifests.append((json.loads(data), url)))

    manifest = execution.stage_datasource_to_object_store(
        {"source_type": "file"},
        table_path="s3://default/clean/empty__claim_attempt/master",
        manifest_url="s3://default/runtime-staging/datasource-stage/request-1/1/manifest.json",
        progress_callback=lambda _event: None,
    )

    assert manifest["row_count"] == 0
    assert manifest["file_paths"] == []
    assert manifest["columns"] == [{"name": "empty", "dtype": "String", "nullable": True}]
    assert saved_manifests[0][0] == manifest


@pytest.mark.parametrize("existing_table", [False, True])
def test_manager_commits_staged_parquet_files_and_replaces_existing_table_atomically(tmp_path, monkeypatch, existing_table: bool) -> None:
    import base64

    import pyarrow.parquet as pq
    from pyiceberg.catalog.memory import InMemoryCatalog

    schema = pa.schema([pa.field("value", pa.int64()), pa.field("added", pa.string())])
    table_path = (tmp_path / "source_claim_1" / "master").as_uri()
    parquet_path = tmp_path / "source_claim_1" / "master" / "data.parquet"
    parquet_path.parent.mkdir(parents=True)
    rows = pa.table({"value": list(range(96)), "added": [f"new-{row}" for row in range(96)]}, schema=schema)
    pq.write_table(rows, parquet_path)
    catalog = InMemoryCatalog("datasource-import-tests", warehouse=(tmp_path / "warehouse").as_uri())
    catalog.create_namespace("clean")
    monkeypatch.setattr(execution, "load_runtime_catalog", lambda *_args, **_kwargs: catalog)
    monkeypatch.setattr(execution, "object_store_storage_options", lambda: {})
    monkeypatch.setattr(execution, "object_store_url", lambda *_args, **_kwargs: (tmp_path / "warehouse").as_uri())
    monkeypatch.setattr(execution, "get_namespace", lambda: "default")

    if existing_table:
        old_schema = pa.schema([pa.field("value", pa.int32()), pa.field("removed", pa.string())])
        old_path = tmp_path / "source_claim_1" / "master" / "old.parquet"
        pq.write_table(pa.table({"value": [-1], "removed": ["old"]}, schema=old_schema), old_path)
        old_table = catalog.create_table("clean.source_claim_1", schema=old_schema, location=table_path)
        old_table.append(pa.table({"value": [-1], "removed": ["old"]}, schema=old_schema))
        previous_snapshot_id = old_table.current_snapshot().snapshot_id

    manifest = {
        "file_paths": [parquet_path.as_uri()],
        "arrow_schema": base64.b64encode(schema.serialize().to_pybytes()).decode("ascii"),
        "row_count": 96,
    }
    table, published_path = execution.import_staged_parquet_files(
        manifest, staged_prefix=table_path, table_path=table_path, database_url="catalog-credentials-stay-in-manager"
    )

    assert published_path == table_path
    assert table.current_snapshot() is not None
    assert table.current_snapshot().summary["added-records"] == "96"
    assert table.scan().to_arrow().to_pylist() == rows.to_pylist()
    committed_schema = table.schema().as_arrow()
    assert committed_schema.names == schema.names
    assert pa.types.is_int64(committed_schema.field("value").type)
    assert pa.types.is_large_string(committed_schema.field("added").type)
    if existing_table:
        assert table.current_snapshot().snapshot_id != previous_snapshot_id
        assert "removed" not in committed_schema.names


@pytest.mark.parametrize(
    "invalid_path",
    [
        "s3://default/clean/another_claim/master/data.parquet",
        "s3://default/clean/current_claim/master/../published/data.parquet",
    ],
)
def test_manager_rejects_stale_manifest_outside_claim_prefix_before_catalog_access(monkeypatch, invalid_path: str) -> None:
    import base64

    schema = pa.schema([pa.field("value", pa.int64())])
    manifest = {
        "file_paths": ["s3://default/clean/current_claim/master/valid.parquet", invalid_path],
        "arrow_schema": base64.b64encode(schema.serialize().to_pybytes()).decode("ascii"),
    }
    monkeypatch.setattr(
        execution,
        "load_runtime_catalog",
        lambda *_args, **_kwargs: pytest.fail("A stale manifest must be rejected before catalog access"),
    )

    with pytest.raises(ValueError, match="claim-scoped staging prefix"):
        execution.import_staged_parquet_files(
            manifest,
            staged_prefix="s3://default/clean/current_claim/master",
            table_path="s3://default/clean/current_claim/master",
            database_url="catalog-credentials-stay-in-manager",
        )


def test_scheduled_ingest_uses_the_same_manifest_commit_path_as_manual_ingest(monkeypatch) -> None:
    from runtime.domain.datasource.source_types import DataSourceType
    from runtime.worker_runtime_client import DatasourceMetadata

    manifest = {"file_paths": ["s3://default/clean/source__claim_schedule/master/data.parquet"], "row_count": 4, "columns": []}
    metadata = DatasourceMetadata(
        found=True,
        id="source",
        name="Source",
        source_type="iceberg",
        config={
            "source": {"source_type": "file"},
            "branch": "master",
            "metadata_path": "s3://default/clean/source__claim_previous/master",
        },
        schema_cache=None,
        is_hidden=False,
        revision=3,
        created_by="import",
    )
    calls = []

    class Engine:
        def datasource_job(self, kind, payload):
            assert kind == "datasource_stage"
            assert payload["table_path"] == "s3://default/clean/source__claim_claim_schedule/master"
            assert payload["manifest_url"].endswith("/manifest.json")
            return "stage-job"

    class Manager:
        @contextlib.contextmanager
        def acquire_engine(self, _identity):
            yield Engine()

    class Client:
        def register_datasource_stage(self, **kwargs):
            calls.append(("register", kwargs))

        def publish_datasource_ingest(self, **kwargs):
            calls.append(("publish", kwargs))
            return execution.DataSourceRecord(id="source", name="Source", source_type="iceberg", config=kwargs["config"])

        def update_compute_worker_run(self, **_kwargs):
            return None

    table = type("Table", (), {"current_snapshot": lambda _self: None, "metadata_location": None})()
    monkeypatch.setattr(execution, "_require_metadata", lambda *_args, **_kwargs: metadata)
    monkeypatch.setattr(execution, "_external_source", lambda _metadata: ({"source_type": "file"}, DataSourceType.FILE))
    monkeypatch.setattr(
        execution, "import_staged_parquet_files", lambda received, **kwargs: (calls.append(("import", received, kwargs)), (table, kwargs["table_path"]))[1]
    )
    monkeypatch.setattr("runtime.compute_utils.await_compute_worker_result", lambda *_args, **_kwargs: {"data": manifest})
    monkeypatch.setattr("runtime.object_store.delete_object", lambda _path: None)

    execution.ingest_datasource_for_schedule(
        Client(),
        manager=Manager(),
        namespace="default",
        database_url="catalog-credentials-stay-in-manager",
        datasource_id="source",
        staging_key="claim-schedule",
        worker_id="worker",
        claim_token="claim-schedule",
        lease_generation=4,
        job_id="job-1",
        build_id="build-1",
    )

    registration = calls[0][1]
    imported_manifest, import_kwargs = calls[1][1:]
    assert registration["prefix_url"] == "s3://default/clean/source__claim_claim_schedule/master"
    assert imported_manifest == manifest
    assert import_kwargs == {
        "staged_prefix": registration["prefix_url"],
        "table_path": "s3://default/clean/source__claim_previous/master",
        "database_url": "catalog-credentials-stay-in-manager",
    }
    assert calls[-1][0] == "publish"


@pytest.mark.parametrize("published_table_name", ["ds-1", "ds-1__claim_previous"])
def test_reingest_accumulates_snapshots_on_the_published_table(tmp_path, monkeypatch, published_table_name: str) -> None:
    """Time travel keeps history on both new and already-published table paths."""
    import base64

    import pyarrow.parquet as pq
    from pyiceberg.catalog.memory import InMemoryCatalog

    schema = pa.schema([pa.field("value", pa.int64())])
    published_table_path = (tmp_path / published_table_name / "master").as_uri()
    catalog = InMemoryCatalog("reingest-history-tests", warehouse=(tmp_path / "warehouse").as_uri())
    catalog.create_namespace("clean")
    monkeypatch.setattr(execution, "load_runtime_catalog", lambda *_args, **_kwargs: catalog)
    monkeypatch.setattr(execution, "object_store_storage_options", lambda: {})
    monkeypatch.setattr(execution, "object_store_url", lambda *_args, **_kwargs: (tmp_path / "warehouse").as_uri())
    monkeypatch.setattr(execution, "get_namespace", lambda: "default")

    snapshot_ids: list[int] = []
    for attempt in range(2):
        claim_prefix = (tmp_path / f"ds-1__claim_attempt_{attempt}" / "master").as_uri()
        parquet_path = tmp_path / f"ds-1__claim_attempt_{attempt}" / "master" / "data.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({"value": [attempt] * 4}, schema=schema), parquet_path)
        manifest = {
            "file_paths": [parquet_path.as_uri()],
            "arrow_schema": base64.b64encode(schema.serialize().to_pybytes()).decode("ascii"),
            "row_count": 4,
        }
        table, returned_path = execution.import_staged_parquet_files(manifest, staged_prefix=claim_prefix, table_path=published_table_path, database_url="x")
        assert returned_path == published_table_path
        snapshot_ids.append(table.current_snapshot().snapshot_id)

    assert snapshot_ids[0] != snapshot_ids[1]
    # pyiceberg commits the overwrite as a chained DELETE + APPEND pair (the
    # same shape the build path produces); the picker lists only the append
    # snapshots recorded per ingest run, so users see one version per ingest.
    assert len(table.snapshots()) == 3
    assert len({snapshot.snapshot_id for snapshot in table.snapshots()}) == 3
    # Old snapshots stay readable: time travel returns the ingested generation.
    assert [row["value"] for row in table.scan(snapshot_id=snapshot_ids[0]).to_arrow().to_pylist()] == [0] * 4
    assert [row["value"] for row in table.scan(snapshot_id=snapshot_ids[1]).to_arrow().to_pylist()] == [1] * 4


def test_schedule_ingest_rejects_datasource_without_external_source(monkeypatch) -> None:
    from runtime.exceptions import DataSourceValidationError
    from runtime.worker_runtime_client import DatasourceMetadata

    metadata = DatasourceMetadata(
        found=True,
        id="source",
        name="iot-sensor-100k",
        source_type="iceberg",
        config={"branch": "master"},
        schema_cache=None,
        is_hidden=False,
        revision=3,
        created_by="import",
    )
    monkeypatch.setattr(execution, "_require_metadata", lambda *_args, **_kwargs: metadata)

    with pytest.raises(DataSourceValidationError, match="no external source"):
        execution.ingest_datasource_for_schedule(
            object(),
            manager=None,  # type: ignore[arg-type]
            namespace="default",
            database_url="unused",
            datasource_id="source",
            staging_key="claim",
            worker_id="worker",
            claim_token="claim",
            lease_generation=1,
            job_id="job-1",
            build_id="build-1",
        )


def test_excel_ingestion_uses_bounded_batches_with_consistent_mixed_column_types(tmp_path) -> None:
    path = tmp_path / "source.xlsx"
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Data")
    sheet.append(["value", "mixed"])
    for index in range(5000):
        sheet.append([index, "late-string" if index == 4999 else index])
    workbook.save(path)
    sizes = []
    last = None
    for batch in iter_excel_batches(
        {"file_path": str(path), "sheet_name": "Data", "start_row": 0, "start_col": 0, "end_col": 1, "end_row": 5000, "has_header": True}, batch_size=256
    ):
        sizes.append(batch.height)
        assert batch.schema["mixed"] == pl.String
        last = batch["mixed"][-1]
    assert max(sizes) <= 256
    assert sum(sizes) == 5000
    assert last == "late-string"
