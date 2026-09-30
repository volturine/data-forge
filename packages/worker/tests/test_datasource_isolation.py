from __future__ import annotations

import io
import json
import multiprocessing
import os
import shutil
import socket
from types import SimpleNamespace

import grpc
import polars as pl
import pyarrow as pa
import pytest
from openpyxl import Workbook

from dataforge_protocol import compute_pb2, engine_runtime_pb2, engine_runtime_pb2_grpc, enums_pb2
from datasources import execution
from datasources.excel_batches import iter_excel_batches
from runtime import compute_request_runtime
from runtime.engine_server import ENGINE_PROTOCOL_VERSION, run_engine_server
from runtime.exceptions import StaleComputeInputError
from runtime.worker_runtime_client import DatasourceMetadata

MAC_HOST = "rolands-mac-mini.bee-justice.ts.net"


def _run_engine(port: int) -> None:
    run_engine_server(host="0.0.0.0", port=port, engine_identity="source-1", token="engine-test-token", heartbeat_timeout_seconds=60)


def test_datasource_schema_executes_in_separate_engine_pid_and_survives_engine_crash(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")

    def fail_manager_schema(*_args, **_kwargs):
        raise AssertionError("Manager parsed user data")

    monkeypatch.setattr(execution, "get_datasource_schema_from_metadata", fail_manager_schema)
    with socket.socket() as listener:
        listener.bind(("0.0.0.0", 0))
        port = listener.getsockname()[1]
    process = multiprocessing.get_context("spawn").Process(target=_run_engine, args=(port,))
    process.start()
    channel = grpc.insecure_channel(f"{MAC_HOST}:{port}")
    try:
        grpc.channel_ready_future(channel).result(timeout=30)
        stub = engine_runtime_pb2_grpc.PolarsEngineServiceStub(channel)
        payload = {
            "resource_id": "source-1",
            "datasource_metadata": {"id": "source-1", "source_type": "file", "revision": 1, "config": {"file_path": str(source), "file_type": "csv"}},
        }
        stub.SubmitJob(
            engine_runtime_pb2.EngineSubmitJobRequest(
                protocol_version=ENGINE_PROTOCOL_VERSION,
                job_id="schema-1",
                kind="datasource_schema",
                payload_json=json.dumps(payload).encode(),
            ),
            metadata=(("x-engine-token", "engine-test-token"),),
            timeout=10,
        )
        events = list(
            stub.WatchJob(engine_runtime_pb2.EngineWatchJobRequest(job_id="schema-1"), metadata=(("x-engine-token", "engine-test-token"),), timeout=30)
        )
        result = json.loads(events[-1].result.data_json)
        assert process.pid != os.getpid()
        assert result["columns"][0]["name"] == "value"
        assert result["row_count"] == 2
        process.kill()
        process.join(timeout=10)
        with pytest.raises(grpc.RpcError):
            stub.Health(engine_runtime_pb2.EngineHealthRequest(), metadata=(("x-engine-token", "engine-test-token"),), timeout=1)
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
def test_staging_streams_multiple_arrow_batches_without_whole_source_collection(monkeypatch, empty_first_batch: bool) -> None:
    uploads = []

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
    result = execution.stage_datasource_to_object_store(
        {"source_type": "file"},
        artifact_url="s3://default/runtime-staging/job/data.arrow",
        progress_callback=lambda _event: None,
    )
    reader = pa.ipc.open_stream(uploads[0].buffer.getvalue())
    chunks = list(reader)
    expected_schema = pl.DataFrame(schema={"value": pl.Null}).with_columns(pl.col("value").cast(pl.String)).to_arrow().schema
    assert uploads[0].committed
    assert reader.schema.equals(expected_schema, check_metadata=True)
    assert all(chunk.schema.equals(reader.schema, check_metadata=True) for chunk in chunks)
    assert reader.schema.field("value").type == pa.large_string()
    assert [chunk.num_rows for chunk in chunks] == ([] if empty_first_batch else [1]) + [16, 16]
    assert chunks[-2].column("value").to_pylist()[0] == "0"
    assert result["row_count"] == (32 if empty_first_batch else 33)


def test_manager_atomically_replaces_existing_table_one_record_batch_at_a_time(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.arrow"
    schema = pa.schema([pa.field("value", pa.int64()), pa.field("added", pa.string())])
    with pa.ipc.new_stream(source, schema) as writer:
        for batch_index in range(3):
            batch_rows = range(batch_index * 32, (batch_index + 1) * 32)
            writer.write_batch(pa.record_batch([list(batch_rows), [f"new-{row}" for row in batch_rows]], schema=schema))

    class Table:
        def __init__(self):
            self.rows = pa.table({"value": pa.array([-1], type=pa.int32()), "removed": ["old"]})
            self.arrow_schema = pa.schema([pa.field("value", pa.int32()), pa.field("removed", pa.string())])
            self.commits = 0
            self.refreshes = 0

        def transaction(self):
            return Transaction(self)

        def refresh(self):
            self.refreshes += 1

    class Transaction:
        def __init__(self, table):
            self.table = table
            self.appended = []
            self.deleted = False
            self.table_metadata = self

        def schema(self):
            return SimpleNamespace(fields=[SimpleNamespace(name=name) for name in self.table.arrow_schema.names])

        def update_schema(self):
            return UpdateSchema(self)

        def delete(self, *, delete_filter):
            assert str(delete_filter) == "AlwaysTrue()"
            self.deleted = True

        def append(self, batch):
            assert self.table.rows.column("value").to_pylist() == [-1]
            assert batch.num_rows == 32
            self.appended.append(batch)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, _exc_value, _traceback):
            if exc_type is None:
                assert self.deleted
                self.table.rows = pa.concat_tables(self.appended)
                self.table.arrow_schema = self.appended[0].schema
                self.table.commits += 1

    class UpdateSchema:
        def __init__(self, transaction):
            self.transaction = transaction
            self.deleted_columns = []
            self.new_schema = None

        def delete_column(self, name):
            self.deleted_columns.append(name)
            return self

        def union_by_name(self, new_schema):
            self.new_schema = new_schema
            return self

        def commit(self):
            assert self.deleted_columns == ["removed"]
            assert self.new_schema == schema

    table = Table()

    class Catalog:
        def create_namespace_if_not_exists(self, _namespace):
            pass

        def table_exists(self, identifier):
            assert identifier == "clean.source_claim_1"
            return True

        def load_table(self, identifier):
            assert identifier == "clean.source_claim_1"
            return table

        def create_table(self, _identifier, **_kwargs):
            pytest.fail("An existing output table must be replaced, not recreated")

    monkeypatch.setattr(execution, "download_file", lambda _url, target: shutil.copyfile(source, target))
    monkeypatch.setattr(execution, "load_runtime_catalog", lambda *_args, **_kwargs: Catalog())
    result = execution.import_staged_arrow_artifact(
        "s3://default/runtime-staging/data.arrow", table_path="s3://default/clean/source_claim_1/master", database_url="catalog-credentials-stay-in-manager"
    )
    assert result is table
    assert table.commits == 1
    assert table.refreshes == 1
    assert table.arrow_schema == schema
    assert table.rows.to_pylist() == [{"value": row, "added": f"new-{row}"} for row in range(96)]


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
