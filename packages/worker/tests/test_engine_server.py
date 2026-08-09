from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest

from dataforge_protocol import engine_runtime_pb2, engine_runtime_pb2_grpc
from runtime.domain.compute.base import EngineResult
from runtime.engine_server import ENGINE_PROTOCOL_VERSION, PolarsEngineServicer
from runtime.json_values import dict_to_struct


@pytest.fixture
def engine_stub(monkeypatch):
    import runtime.engine_server as engine_server

    def execute(*, job_id: str, kind: str, payload: dict, progress_callback):
        assert kind == "preview"
        assert payload == {"datasource_config": {}, "steps": []}
        progress_callback({"type": "compute_start"})
        return EngineResult(job_id=job_id, data={"rows": []}, error=None)

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
            payload=dict_to_struct({"datasource_config": {}, "steps": []}),
        ),
        metadata=metadata,
    )
    assert submitted.job_id == "job-1"

    events = list(engine_stub.WatchJob(engine_runtime_pb2.EngineWatchJobRequest(job_id="job-1"), metadata=metadata))
    assert events[0].progress.fields["type"].string_value == "compute_start"
    assert events[1].result.job_id == "job-1"
    assert events[1].result.data.fields["rows"].list_value.values == []


def test_engine_server_rejects_invalid_token(engine_stub) -> None:
    with pytest.raises(grpc.RpcError) as exc_info:
        engine_stub.Health(engine_runtime_pb2.EngineHealthRequest(), metadata=(("x-engine-token", "invalid"),))
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED
