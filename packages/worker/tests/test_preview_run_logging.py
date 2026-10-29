import uuid
from unittest.mock import MagicMock, patch

import pytest
from worker_test_support import FakeEngine

from runtime import compute_service
from runtime.compute_manager import ProcessManager
from runtime.domain.compute.result import ComputeWorkerResult


class _PreviewEngine(FakeEngine):
    """A fake engine whose preview job completes with a five-row result."""

    def __init__(self, identity, resource_config) -> None:
        super().__init__(identity.resource_id, resource_config)
        self.effective_resources = {"max_threads": 1}
        self._result: ComputeWorkerResult | None = None

    @property
    def process_id(self) -> int | None:
        return None

    def preview(self, *_args, **_kwargs) -> str:
        job_id = "preview-job"
        self.current_job_id = job_id
        self._result = ComputeWorkerResult(
            job_id=job_id,
            data={
                "schema": {"value": "Int64"},
                "row_count": 5,
                "data": [{"value": value} for value in range(5)],
                "step_timings": {},
            },
            error=None,
        )
        return job_id

    def get_result(self, *, timeout: float = 1.0, job_id: str | None = None) -> ComputeWorkerResult | None:
        result = self._result
        self._result = None
        self.current_job_id = None
        if self._capacity_notifier is not None:
            self._capacity_notifier()
        return result

    def get_progress_event(self, *_args, **_kwargs):
        return None


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
    client.create_compute_worker_run.return_value = "run-1"
    return client


def _preview_request(analysis_id: str, pipeline: dict[str, object]) -> dict[str, object]:
    return {
        "analysis_id": analysis_id,
        "analysis_pipeline": pipeline,
        "target_step_id": "source",
    }


def test_preview_step_persists_compute_worker_run_by_default(sample_datasource, monkeypatch, caplog) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", True)
    monkeypatch.setattr(compute_service, "_SLOW_PREVIEW_LOG_SECONDS", 0.0)
    caplog.set_level("WARNING", logger="runtime.compute_service")
    analysis_id = f"preview-log-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    manager = ProcessManager(engine_factory=_PreviewEngine)
    internal_client = _internal_client_mock()
    try:
        with patch("runtime.compute_service.client_from_env", return_value=internal_client):
            result = compute_service.preview_step(
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
    internal_client.create_compute_worker_run.assert_called_once()
    create_kwargs = internal_client.create_compute_worker_run.call_args.kwargs
    assert create_kwargs["datasource_id"] == sample_datasource.id
    assert create_kwargs["kind"] == "preview"
    assert create_kwargs["status"] == "running"
    internal_client.compute_worker_run_state.assert_not_called()
    internal_client.update_compute_worker_run.assert_not_called()
    assert result.compute_worker_run_finalization is not None
    assert result.compute_worker_run_finalization.run_id == "run-1"
    assert result.compute_worker_run_finalization.fields["status"] == "success"
    preview_log = next(record.message for record in caplog.records if "Slow preview" in record.message)
    assert "request_id=preview-request-1" in preview_log
    assert "namespace=default" in preview_log
    assert "compute_worker_scope=analysis_interactive" in preview_log
    assert f"resource_id={analysis_id}" in preview_log
    assert "command_hash=safe-command-hash" in preview_log


def test_preview_step_skips_compute_worker_run_persistence_when_disabled(sample_datasource, monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", False)
    analysis_id = f"preview-no-log-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    manager = ProcessManager(engine_factory=_PreviewEngine)
    internal_client = _internal_client_mock()
    try:
        with patch("runtime.compute_service.client_from_env", return_value=internal_client):
            result = compute_service.preview_step(
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
    internal_client.create_compute_worker_run.assert_not_called()
    internal_client.compute_worker_run_state.assert_not_called()
    internal_client.update_compute_worker_run.assert_not_called()


def test_preview_step_finalizes_run_when_engine_fails(sample_datasource, monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", True)
    analysis_id = f"preview-engine-failure-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    internal_client = _internal_client_mock()

    manager = ProcessManager(engine_factory=_PreviewEngine)
    with (
        patch("runtime.compute_service.client_from_env", return_value=internal_client),
        patch.object(manager, "acquire_engine", side_effect=RuntimeError("engine failed")),
        pytest.raises(compute_service.PreviewExecutionError, match="engine failed") as raised,
    ):
        compute_service.preview_step(
            manager=manager,
            target_step_id="source",
            analysis_pipeline=pipeline,
            row_limit=100,
            page=1,
            analysis_id=analysis_id,
            request_json=_preview_request(analysis_id, pipeline),
        )

    internal_client.create_compute_worker_run.assert_called_once()
    internal_client.compute_worker_run_state.assert_not_called()
    internal_client.update_compute_worker_run.assert_not_called()
    assert str(raised.value.error) == "engine failed"
    assert raised.value.compute_worker_run_finalization.run_id == "run-1"
    assert raised.value.compute_worker_run_finalization.fields["status"] == "failed"
    assert raised.value.compute_worker_run_finalization.fields["error_message"] == "engine failed"


def test_hydrate_udfs_loads_code_for_protocol_enum_number(monkeypatch) -> None:
    client = MagicMock()
    client.udf_codes.return_value = {"udf-1": "def udf(value):\n    return value\n"}
    monkeypatch.setattr(compute_service, "client_from_env", lambda: client)
    monkeypatch.setattr(compute_service, "get_namespace", lambda: "default")

    hydrated = compute_service._hydrate_udfs(
        [
            {
                "type": "with_columns",
                "config": {
                    "expressions": [
                        {"name": "value_f", "type": 3, "udf_id": "udf-1", "args": ["value"]},
                    ]
                },
            }
        ],
    )

    expression = hydrated[0]["config"]["expressions"][0]
    assert expression["code"].startswith("def udf")
    client.udf_codes.assert_called_once()


def test_hydrate_udfs_missing_library_udf_fails(monkeypatch) -> None:
    client = MagicMock()
    client.udf_codes.return_value = {}
    monkeypatch.setattr(compute_service, "client_from_env", lambda: client)
    monkeypatch.setattr(compute_service, "get_namespace", lambda: "default")

    with pytest.raises(ValueError, match="not found"):
        compute_service._hydrate_udfs(
            [
                {
                    "type": "with_columns",
                    "config": {"expressions": [{"name": "value_f", "type": "udf", "udf_id": "missing"}]},
                }
            ],
        )


def test_row_count_records_run_when_engine_acquire_fails(sample_datasource) -> None:
    from runtime.exceptions import PipelineExecutionError

    analysis_id = f"row-count-failure-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    internal_client = _internal_client_mock()
    internal_client.compute_worker_run_state.return_value = None
    manager = ProcessManager(engine_factory=_PreviewEngine)

    with (
        patch("runtime.compute_service.client_from_env", return_value=internal_client),
        patch.object(manager, "acquire_engine", side_effect=RuntimeError("Timed out waiting for engine listener")),
        pytest.raises(PipelineExecutionError, match="Timed out waiting for engine listener"),
    ):
        compute_service.get_step_row_count(
            manager=manager,
            target_step_id="source",
            analysis_id=analysis_id,
            analysis_pipeline=pipeline,
            tab_id="tab1",
            request_json={"analysis_id": analysis_id, "analysis_pipeline": pipeline, "target_step_id": "source"},
        )

    create_kwargs = internal_client.create_compute_worker_run.call_args.kwargs
    assert create_kwargs["kind"] == "row_count"
    assert create_kwargs["status"] == "running"
    fields = internal_client.update_compute_worker_run.call_args.kwargs["fields"]
    assert fields["status"] == "failed"
    assert fields["error_message"] == "Timed out waiting for engine listener"


def test_download_step_finalizes_validation_failure_without_query_plan(sample_datasource) -> None:
    from runtime.exceptions import PipelineValidationError

    class _ValidationFailureEngine(_PreviewEngine):
        def preview(self, *_args, **_kwargs) -> str:
            job_id = "download-job"
            self.current_job_id = job_id
            self._result = ComputeWorkerResult(
                job_id=job_id,
                data=None,
                error="boom",
                error_kind="value_error",
            )
            return job_id

    analysis_id = f"download-failure-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource, analysis_id)
    internal_client = _internal_client_mock()
    internal_client.compute_worker_run_state.return_value = None
    manager = ProcessManager(engine_factory=_ValidationFailureEngine)

    try:
        with (
            patch("runtime.compute_service.client_from_env", return_value=internal_client),
            pytest.raises(PipelineValidationError, match="boom"),
        ):
            compute_service.download_step(
                manager=manager,
                target_step_id="source",
                analysis_pipeline=pipeline,
                analysis_id=analysis_id,
                tab_id="tab1",
            )
    finally:
        manager.shutdown_all()

    internal_client.create_compute_worker_run.assert_called_once()
    internal_client.update_compute_worker_run.assert_called_once()
    fields = internal_client.update_compute_worker_run.call_args.kwargs["fields"]
    assert fields["status"] == "failed"
    assert fields["error_message"] == "boom"
    assert "query_plan" not in fields
