from datetime import UTC, datetime

import pytest

from dataforge_protocol import datasource_pb2, enums_pb2, worker_runtime_pb2
from runtime.worker_runtime_client import WorkerRuntimeClient


class _Stub:
    def __init__(self, *, create=None, ingest=None) -> None:
        self.create_response = create
        self.ingest_response = ingest
        self.create_request = None
        self.ingest_request = None

    def PublishDatasourceCreate(self, request, **_kwargs):
        self.create_request = request
        return self.create_response

    def PublishDatasourceIngest(self, request, **_kwargs):
        self.ingest_request = request
        return self.ingest_response


def _client(stub: _Stub) -> WorkerRuntimeClient:
    client = object.__new__(WorkerRuntimeClient)
    client._stub = stub
    client._timeout_seconds = 1.0
    client._target = "fake-worker-runtime"
    client._call = lambda operation: operation()
    client._metadata = lambda: ()
    return client


def _record(*, optional_fields: bool) -> datasource_pb2.DataSourceRecord:
    record = datasource_pb2.DataSourceRecord(
        id="source-1",
        name="Source",
        source_type=enums_pb2.DATA_SOURCE_TYPE_ICEBERG,
        created_by=enums_pb2.DATA_SOURCE_CREATED_BY_IMPORT,
    )
    record.config.update({"branch": "main", "snapshot_id": "17"})
    if optional_fields:
        record.description = "Input dataset"
        record.created_by_analysis_id = "analysis-1"
        record.output_of_tab_id = "tab-1"
        record.created_at.FromDatetime(datetime(2026, 10, 13, tzinfo=UTC))
        record.schema_info.columns.add(name="id", dtype="Int64", nullable=False, sample_value="1", description="Key")
        record.schema_info.row_count = 1
        record.schema_info.sheet_names.append("Sheet1")
    return record


def test_publish_datasource_create_returns_the_exact_proto_record() -> None:
    record = _record(optional_fields=True)
    # Include an unknown field to prove the client does not decode and rebuild
    # the message while routing a publication result.
    record.ParseFromString(record.SerializeToString() + b"\xa0\x06\x07")
    response = worker_runtime_pb2.WorkerPublishDatasourceCreateResponse(datasource=record)
    stub = _Stub(create=response)

    published = _client(stub).publish_datasource_create(
        namespace="default",
        datasource_id="source-1",
        name="Source",
        description="Input dataset",
        source_type="iceberg",
        config={"branch": "main"},
        compute_request_id="request-1",
        worker_id="worker-1",
        claim_token="claim-1",
        lease_generation=2,
        owner_id="user-1",
        schema_info=record.schema_info,
    )

    assert published == record
    assert published.SerializeToString(deterministic=True) == record.SerializeToString(deterministic=True)
    assert published.HasField("description")
    assert published.HasField("created_by_analysis_id")
    assert published.HasField("created_at")
    assert published.HasField("schema_info")
    assert stub.create_request.source_type == enums_pb2.DATA_SOURCE_TYPE_ICEBERG
    assert stub.create_request.HasField("description")
    assert stub.create_request.HasField("owner_id")


def test_publish_datasource_ingest_preserves_absent_optional_fields() -> None:
    record = _record(optional_fields=False)
    response = worker_runtime_pb2.WorkerPublishDatasourceIngestResponse(datasource=record)
    stub = _Stub(ingest=response)

    published = _client(stub).publish_datasource_ingest(
        namespace="default",
        datasource_id="source-1",
        config={"branch": "main"},
        expected_revision=3,
        worker_id="worker-1",
        claim_token="claim-1",
        lease_generation=2,
    )

    assert published == record
    assert published.SerializeToString(deterministic=True) == record.SerializeToString(deterministic=True)
    assert not published.HasField("description")
    assert not published.HasField("created_by_analysis_id")
    assert not published.HasField("created_at")
    assert not published.HasField("schema_info")
    assert not stub.ingest_request.HasField("compute_request_id")
    assert not stub.ingest_request.HasField("job_id")
    assert not stub.ingest_request.HasField("build_id")


@pytest.mark.parametrize(
    ("method", "invalid_field"),
    [("PublishDatasourceCreate", "source_type"), ("PublishDatasourceIngest", "created_by")],
)
def test_publication_rejects_unspecified_enum_values(method: str, invalid_field: str) -> None:
    record = _record(optional_fields=False)
    setattr(record, invalid_field, 0)
    response_type = (
        worker_runtime_pb2.WorkerPublishDatasourceCreateResponse
        if method == "PublishDatasourceCreate"
        else worker_runtime_pb2.WorkerPublishDatasourceIngestResponse
    )
    response = response_type(datasource=record)
    stub = _Stub(create=response) if method == "PublishDatasourceCreate" else _Stub(ingest=response)
    client = _client(stub)

    with pytest.raises(ValueError, match="UNSPECIFIED"):
        if method == "PublishDatasourceCreate":
            client.publish_datasource_create(
                namespace="default",
                datasource_id="source-1",
                name="Source",
                description=None,
                source_type="iceberg",
                config={},
                compute_request_id="request-1",
                worker_id="worker-1",
                claim_token="claim-1",
                lease_generation=1,
            )
        else:
            client.publish_datasource_ingest(
                namespace="default",
                datasource_id="source-1",
                config={},
                expected_revision=1,
                worker_id="worker-1",
                claim_token="claim-1",
                lease_generation=1,
            )


def test_publish_datasource_create_rejects_unknown_source_type_before_rpc() -> None:
    stub = _Stub(create=worker_runtime_pb2.WorkerPublishDatasourceCreateResponse(datasource=_record(optional_fields=False)))

    with pytest.raises(AttributeError):
        _client(stub).publish_datasource_create(
            namespace="default",
            datasource_id="source-1",
            name="Source",
            description=None,
            source_type="invalid-source",
            config={},
            compute_request_id="request-1",
            worker_id="worker-1",
            claim_token="claim-1",
            lease_generation=1,
        )

    assert stub.create_request is None
