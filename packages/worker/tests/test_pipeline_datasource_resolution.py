"""Request pipelines may only select a branch/snapshot of stored datasources, never repoint them."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from worker_test_support import FakeEngine

from runtime import compute_service
from runtime.compute_manager import ProcessManager
from runtime.domain.compute.result import ComputeWorkerResult
from runtime.namespace import get_namespace
from runtime.worker_runtime_client import DatasourceMetadata, reset_datasource_metadata_snapshot, set_datasource_metadata_snapshot

_STORED_ID = "stored-internal-table"
_JOINED_ID = "stored-joined-file"
_STORED_CONFIG = {"connection_string": "postgresql://app@db/app", "query": 'SELECT * FROM "public"."orders"', "branch": "master"}
_JOINED_CONFIG = {"file_path": "s3://default/uploads/joined.csv", "file_type": "csv"}
# A request trying to repoint the onboarded table at another application table and file.
_REQUEST_OVERRIDES = {
    "branch": "feature",
    "snapshot_id": "snap-7",
    "source_type": "file",
    "query": 'SELECT * FROM "public"."user"',
    "connection_string": "postgresql://attacker@evil/app",
    "file_path": "s3://other-tenant/secret.csv",
}


def _metadata(datasource_id: str) -> DatasourceMetadata:
    stored = {
        _STORED_ID: ("database", _STORED_CONFIG),
        _JOINED_ID: ("file", _JOINED_CONFIG),
    }
    if datasource_id not in stored:
        return DatasourceMetadata(found=False, id=None, name=None, source_type=None, config=None, schema_cache=None, is_hidden=None)
    source_type, config = stored[datasource_id]
    return DatasourceMetadata(
        found=True, id=datasource_id, name=datasource_id, source_type=source_type, config=dict(config), schema_cache=None, is_hidden=False
    )


def _client() -> MagicMock:
    client = MagicMock()
    client.datasource_metadata.side_effect = lambda *, namespace, datasource_id: _metadata(datasource_id)
    return client


def _tab(tab_id: str, datasource_id: str, output_id: str, *, steps: list | None = None, analysis_tab_id: str | None = None) -> dict:
    return {
        "id": tab_id,
        "datasource": {
            "id": datasource_id,
            "analysis_tab_id": analysis_tab_id,
            "source_type": "file",
            "config": dict(_REQUEST_OVERRIDES),
        },
        "output": {"result_id": output_id, "format": "parquet", "filename": tab_id},
        "steps": steps or [],
    }


def _pipeline() -> dict:
    join = {"id": "join-1", "type": "join", "config": {"right_source": _JOINED_ID, "how": "left", "join_columns": []}}
    return {
        "analysis_id": f"analysis-{uuid.uuid4()}",
        "tabs": [
            _tab("tab1", _STORED_ID, "out-1"),
            # Reads tab1's output; its request config must not turn it into a file read.
            _tab("tab2", "out-1", "out-2", steps=[join]),
            _tab("tab3", _JOINED_ID, "out-3"),
            # The same stored datasource again must not cost another metadata lookup.
            _tab("tab4", _STORED_ID, "out-4"),
        ],
    }


def _assert_stored(config: dict) -> None:
    assert config["source_type"] == "database"
    assert config["connection_string"] == _STORED_CONFIG["connection_string"]
    assert config["query"] == _STORED_CONFIG["query"]
    assert "file_path" not in config
    # Read selectors still come from the request.
    assert config["branch"] == "feature"
    assert config["snapshot_id"] == "snap-7"


def _assert_execution_pipeline(pipeline: dict) -> None:
    tabs = {tab["id"]: tab["datasource"] for tab in pipeline["tabs"]}
    for tab_id in ("tab1", "tab4"):
        _assert_stored({"source_type": tabs[tab_id]["source_type"], **tabs[tab_id]["config"]})
    assert tabs["tab2"] == {
        "id": "out-1",
        "analysis_tab_id": "tab1",
        "source_type": "analysis",
        "config": {"branch": "feature", "snapshot_id": "snap-7"},
    }
    assert tabs["tab3"]["source_type"] == "file"
    assert tabs["tab3"]["config"] == {**_JOINED_CONFIG, "branch": "feature", "snapshot_id": "snap-7"}


def test_build_path_resolves_stored_config_once_per_datasource() -> None:
    client = _client()
    pipeline = _pipeline()
    with patch("runtime.compute_service.client_from_env", return_value=client):
        request = compute_service._resolve_pipeline_request(pipeline, "tab1", "source", analysis_id=None, operation="export")
        additional = compute_service._get_additional_datasources(pipeline["tabs"][1]["steps"], request.pipeline)

    _assert_stored(request.datasource_config)
    _assert_execution_pipeline(request.pipeline)
    assert additional[_JOINED_ID] == {"source_type": "file", **_JOINED_CONFIG, "branch": "feature", "snapshot_id": "snap-7"}
    looked_up = [call.kwargs["datasource_id"] for call in client.datasource_metadata.call_args_list]
    assert sorted(looked_up) == sorted([_STORED_ID, _JOINED_ID])


def test_analysis_tab_source_embeds_only_worker_resolved_tabs() -> None:
    pipeline = _pipeline()
    with patch("runtime.compute_service.client_from_env", return_value=_client()):
        request = compute_service._resolve_pipeline_request(pipeline, "tab2", "join-1", analysis_id=None, operation="export")

    config = request.datasource_config
    assert config["source_type"] == "analysis"
    assert config["analysis_tab_id"] == "tab1"
    assert "file_path" not in config
    assert "connection_string" not in config
    _assert_execution_pipeline(config["analysis_pipeline"])


def test_missing_stored_datasource_fails_explicitly() -> None:
    pipeline = _pipeline()
    pipeline["tabs"][0]["datasource"]["id"] = "deleted-datasource"
    with (
        patch("runtime.compute_service.client_from_env", return_value=_client()),
        pytest.raises(ValueError, match="missing datasource config for deleted-datasource"),
    ):
        compute_service._resolve_pipeline_request(pipeline, "tab1", "source", analysis_id=None, operation="export")


def test_frozen_inputs_ignore_request_location_and_tolerate_unrelated_missing_tabs() -> None:
    pipeline = _pipeline()
    pipeline["tabs"][3]["datasource"]["id"] = "deleted-datasource"
    namespace = get_namespace()
    # The backend freezes only datasources that existed when the request was queued.
    token = set_datasource_metadata_snapshot({(namespace, ds_id): _metadata(ds_id) for ds_id in (_STORED_ID, _JOINED_ID)})
    client = _client()
    try:
        with patch("runtime.compute_service.client_from_env", return_value=client):
            request = compute_service._resolve_pipeline_request(pipeline, "tab1", "source", analysis_id=None, operation="preview")
    finally:
        reset_datasource_metadata_snapshot(token)

    _assert_stored(request.datasource_config)
    assert request.pipeline["tabs"][3]["datasource"]["source_type"] is None
    client.datasource_metadata.assert_not_called()


class _CapturingPreviewEngine(FakeEngine):
    previews: list[dict] = []

    def __init__(self, identity, resource_config) -> None:
        super().__init__(identity.resource_id, resource_config)
        self.effective_resources = {"max_threads": 1}
        self._result: ComputeWorkerResult | None = None

    @property
    def process_id(self) -> int | None:
        return None

    def preview(self, *_args, **kwargs) -> str:
        type(self).previews.append(kwargs)
        self.current_job_id = "preview-job"
        self._result = ComputeWorkerResult(
            job_id="preview-job",
            data={"schema": {"value": "Int64"}, "row_count": 0, "data": [], "step_timings": {}},
            error=None,
        )
        return "preview-job"

    def get_result(self, *, timeout: float = 1.0, job_id: str | None = None) -> ComputeWorkerResult | None:
        result, self._result = self._result, None
        self.current_job_id = None
        if self._capacity_notifier is not None:
            self._capacity_notifier()
        return result

    def get_progress_event(self, *_args, **_kwargs):
        return None


def test_preview_engine_receives_stored_config_not_request_overrides(monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", False)
    _CapturingPreviewEngine.previews = []
    pipeline = _pipeline()
    analysis_id = pipeline["analysis_id"]
    manager = ProcessManager(engine_factory=_CapturingPreviewEngine)
    try:
        with patch("runtime.compute_service.client_from_env", return_value=_client()):
            compute_service.preview_step(
                manager=manager,
                target_step_id="source",
                analysis_pipeline=pipeline,
                row_limit=10,
                page=1,
                analysis_id=analysis_id,
                tab_id="tab1",
                request_json={"analysis_id": analysis_id, "analysis_pipeline": pipeline, "target_step_id": "source", "tab_id": "tab1"},
            )
    finally:
        manager.shutdown_all()

    assert len(_CapturingPreviewEngine.previews) == 1
    _assert_stored(_CapturingPreviewEngine.previews[0]["datasource_config"])
