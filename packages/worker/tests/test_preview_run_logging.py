import uuid
from unittest.mock import MagicMock, patch

import pytest

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
    return client


def _preview_request(analysis_id: str, pipeline: dict[str, object]) -> dict[str, object]:
    return {
        "analysis_id": analysis_id,
        "analysis_pipeline": pipeline,
        "target_step_id": "source",
    }


def test_preview_step_persists_engine_run_by_default(sample_datasource, monkeypatch, caplog) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", True)
    monkeypatch.setattr(compute_service, "_SLOW_PREVIEW_LOG_SECONDS", 0.0)
    caplog.set_level("WARNING", logger="runtime.compute_service")
    analysis_id = f"preview-log-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    manager = ProcessManager(engine_factory=lambda identity, config: PolarsComputeEngine(identity.resource_id, config))
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
                request_id="preview-request-1",
                command_hash="safe-command-hash",
            )
    finally:
        manager.shutdown_all()

    assert result.response.total_rows == 5
    internal_client.create_engine_run.assert_called_once()
    create_kwargs = internal_client.create_engine_run.call_args.kwargs
    assert create_kwargs["datasource_id"] == sample_datasource.id
    assert create_kwargs["kind"] == "preview"
    assert create_kwargs["status"] == "running"
    internal_client.engine_run_state.assert_not_called()
    internal_client.update_engine_run.assert_not_called()
    assert result.engine_run_finalization is not None
    assert result.engine_run_finalization.run_id == "run-1"
    assert result.engine_run_finalization.fields["status"] == "success"
    preview_log = next(record.message for record in caplog.records if "Slow preview" in record.message)
    assert "request_id=preview-request-1" in preview_log
    assert "namespace=default" in preview_log
    assert "engine_scope=analysis_interactive" in preview_log
    assert f"resource_id={analysis_id}" in preview_log
    assert "command_hash=safe-command-hash" in preview_log


def test_preview_step_skips_engine_run_persistence_when_disabled(sample_datasource, monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", False)
    analysis_id = f"preview-no-log-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    manager = ProcessManager(engine_factory=lambda identity, config: PolarsComputeEngine(identity.resource_id, config))
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
        manager.shutdown_all()

    assert result.response.total_rows == 5
    internal_client.create_engine_run.assert_not_called()
    internal_client.engine_run_state.assert_not_called()
    internal_client.update_engine_run.assert_not_called()


def test_preview_step_finalizes_run_when_engine_fails(sample_datasource, monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", True)
    analysis_id = f"preview-engine-failure-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    internal_client = _internal_client_mock()

    manager = ProcessManager(engine_factory=lambda identity, config: PolarsComputeEngine(identity.resource_id, config))
    with (
        patch("runtime.compute_service.client_from_env", return_value=internal_client),
        patch("runtime.compute_service._acquire_engine", side_effect=RuntimeError("engine failed")),
        pytest.raises(compute_service.PreviewExecutionError, match="engine failed") as raised,
    ):
        compute_service.preview_step(
            session=None,
            manager=manager,
            target_step_id="source",
            analysis_pipeline=pipeline,
            row_limit=100,
            page=1,
            analysis_id=analysis_id,
            request_json=_preview_request(analysis_id, pipeline),
        )

    internal_client.create_engine_run.assert_called_once()
    internal_client.engine_run_state.assert_not_called()
    internal_client.update_engine_run.assert_not_called()
    assert str(raised.value.error) == "engine failed"
    assert raised.value.engine_run_finalization.run_id == "run-1"
    assert raised.value.engine_run_finalization.fields["status"] == "failed"
    assert raised.value.engine_run_finalization.fields["error_message"] == "engine failed"
