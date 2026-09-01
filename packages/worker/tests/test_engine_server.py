from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import grpc
import pytest

from dataforge_protocol import engine_runtime_pb2, engine_runtime_pb2_grpc
from runtime import engine_server
from runtime.domain.compute.base import EngineResult
from runtime.engine_server import ENGINE_PROTOCOL_VERSION, PolarsEngineServicer, _EngineJobs


@pytest.fixture
def engine_stub(monkeypatch):
    def execute(*, job_id: str, kind: str, payload: dict, progress_callback):
        assert kind == "preview"
        assert payload == {"datasource_config": {}, "steps": [], "row_limit": 100, "offset": 0}
        assert isinstance(payload["row_limit"], int)
        assert isinstance(payload["offset"], int)
        progress_callback({"type": "compute_start"})
        return EngineResult(job_id=job_id, data={"rows": [], "as_of": date(2026, 8, 10)}, error=None)

    monkeypatch.setattr(engine_server, "_execute_job", execute)
    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    engine_runtime_pb2_grpc.add_PolarsEngineServiceServicer_to_server(
        PolarsEngineServicer(engine_identity="analysis-1", application_version="test", token="token", on_shutdown=lambda: None), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield engine_runtime_pb2_grpc.PolarsEngineServiceStub(channel)
    finally:
        channel.close()
        server.stop(grace=0)


def test_engine_server_submits_and_streams_progress_and_result(engine_stub) -> None:
    metadata = (("x-engine-token", "token"),)
    health = engine_stub.Health(engine_runtime_pb2.EngineHealthRequest(), metadata=metadata)
    assert health.ready
    assert health.engine_identity == "analysis-1"
    assert health.protocol_version == ENGINE_PROTOCOL_VERSION

    submitted = engine_stub.SubmitJob(
        engine_runtime_pb2.EngineSubmitJobRequest(
            protocol_version=ENGINE_PROTOCOL_VERSION,
            job_id="job-1",
            kind="preview",
            payload_json=json.dumps({"datasource_config": {}, "steps": [], "row_limit": 100, "offset": 0}).encode(),
        ),
        metadata=metadata,
    )
    assert submitted.job_id == "job-1"

    events = list(engine_stub.WatchJob(engine_runtime_pb2.EngineWatchJobRequest(job_id="job-1"), metadata=metadata))
    assert json.loads(events[0].progress_json)["type"] == "compute_start"
    assert events[1].result.job_id == "job-1"
    assert json.loads(events[1].result.data_json) == {"rows": [], "as_of": "2026-08-10"}


def test_engine_server_rejects_invalid_token(engine_stub) -> None:
    with pytest.raises(grpc.RpcError) as exc_info:
        engine_stub.Health(engine_runtime_pb2.EngineHealthRequest(), metadata=(("x-engine-token", "invalid"),))
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


def test_export_stages_artifact_in_object_store(monkeypatch, tmp_path) -> None:
    staged: dict[str, object] = {}

    def execute_export(_datasource, _steps, output_path, export_format, _job_id, _additional, _progress):
        assert export_format == "parquet"
        with open(output_path, "wb") as output:
            output.write(b"parquet")
        return {"row_count": 1, "step_timings": {}}

    class Response:
        def raise_for_status(self) -> None:
            return None

    def put(url, *, data, headers, timeout):
        staged.update(url=url, content_type=headers["Content-Type"], data=data.read(), timeout=timeout)
        return Response()

    monkeypatch.setattr(engine_server.PolarsComputeEngine, "execute_export", execute_export)
    monkeypatch.setattr(engine_server.requests, "put", put)

    result = engine_server._execute_job(
        job_id="job-1",
        kind="export",
        payload={
            "datasource_config": {},
            "steps": [],
            "artifact_url": "s3://tenant-a/runtime-staging/engine/job-1/output.parquet",
            "artifact_upload_url": "http://object-store/presigned-put",
            "export_format": "parquet",
        },
        progress_callback=lambda _event: None,
    )

    assert staged["data"] == b"parquet"
    assert staged["url"] == "http://object-store/presigned-put"
    assert result.data is not None
    assert result.data["output_path"] == "s3://tenant-a/runtime-staging/engine/job-1/output.parquet"


def test_engine_job_retention_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(
        engine_server,
        "_execute_job",
        lambda *, job_id, **_kwargs: EngineResult(job_id=job_id, data={}, error=None),
    )
    jobs = _EngineJobs()
    try:
        for index in range(105):
            state = jobs.submit(job_id=f"job-{index}", kind="preview", payload={})
            with state.condition:
                state.condition.wait_for(lambda state=state: state.done, timeout=1)
        assert len(jobs._jobs) == 8
        assert "job-0" not in jobs._jobs
        assert "job-104" in jobs._jobs
    finally:
        jobs.shutdown()
