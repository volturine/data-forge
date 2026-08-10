import uuid
from unittest.mock import MagicMock, patch

from dataforge_protocol import compute_pb2, enums_pb2
from runtime import compute_service
from runtime.compute_engine import PolarsComputeEngine
from runtime.compute_manager import ProcessManager


def _pipeline(sample_datasource, analysis_id: str) -> dict[str, object]:
    return {
        "analysis_id": analysis_id,
        "tabs": [
            {
                "id": "tab1",
                "datasource": {
                    "id": sample_datasource.id,
                    "analysis_tab_id": None,
                    "source_type": sample_datasource.source_type,
                    "config": {**sample_datasource.config, "branch": "master"},
                },
                "output": {
                    "result_id": "out-1",
                    "format": "parquet",
                    "filename": "preview_out",
                },
                "steps": [],
            }
        ],
    }


def _internal_client_mock() -> MagicMock:
    client = MagicMock()
    client.create_engine_run.return_value = "run-1"
    client.engine_run_state.return_value = {"result_json": {}}
    return client


def _preview_request(analysis_id: str, pipeline: dict[str, object]) -> dict[str, object]:
    return {
        "analysis_id": analysis_id,
        "analysis_pipeline": pipeline,
        "target_step_id": "source",
    }


def _analysis_identity(analysis_id: str) -> compute_pb2.EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id=analysis_id,
        resource_id=analysis_id,
    )


def test_preview_step_persists_engine_run_by_default(sample_datasource, monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", True)
    analysis_id = f"preview-log-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    manager = ProcessManager(engine_factory=lambda identity, config: PolarsComputeEngine(identity.resource_id, config))
    identity = _analysis_identity(analysis_id)
    internal_client = _internal_client_mock()
    try:
        with patch("runtime.compute_service.client_from_env", return_value=internal_client):
            result = compute_service.preview_step(
                session=None,
                manager=manager,
                target_step_id="source",
                analysis_pipeline=pipeline,
                row_limit=100,
                page=1,
                analysis_id=analysis_id,
                request_json=_preview_request(analysis_id, pipeline),
            )
    finally:
        if manager.get_engine(identity):
            manager.shutdown_engine(identity)

    assert result.total_rows == 5
    internal_client.create_engine_run.assert_called_once()
    create_kwargs = internal_client.create_engine_run.call_args.kwargs
    assert create_kwargs["datasource_id"] == sample_datasource.id
    assert create_kwargs["kind"] == "preview"
    assert create_kwargs["status"] == "running"
    internal_client.update_engine_run.assert_called_once()
    update_kwargs = internal_client.update_engine_run.call_args.kwargs
    assert update_kwargs["run_id"] == "run-1"
    assert update_kwargs["fields"]["status"] == "success"


def test_preview_step_skips_engine_run_persistence_when_disabled(sample_datasource, monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", False)
    analysis_id = f"preview-no-log-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    manager = ProcessManager(engine_factory=lambda identity, config: PolarsComputeEngine(identity.resource_id, config))
    identity = _analysis_identity(analysis_id)
    internal_client = _internal_client_mock()
    try:
        with patch("runtime.compute_service.client_from_env", return_value=internal_client):
            result = compute_service.preview_step(
                session=None,
                manager=manager,
                target_step_id="source",
                analysis_pipeline=pipeline,
                row_limit=100,
                page=1,
                analysis_id=analysis_id,
                request_json=_preview_request(analysis_id, pipeline),
            )
    finally:
        if manager.get_engine(identity):
            manager.shutdown_engine(identity)

    assert result.total_rows == 5
    internal_client.create_engine_run.assert_not_called()
    internal_client.update_engine_run.assert_not_called()
