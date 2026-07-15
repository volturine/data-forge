import json
import time
import uuid
from unittest.mock import MagicMock, patch

from dataforge_protocol import compute_pb2, enums_pb2
from runtime import compute_service
from runtime.compute_manager import ProcessManager


def _measure(func, *args, **kwargs):
    started = time.perf_counter()
    result = func(*args, **kwargs)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return result, duration_ms


def test_performance_baseline(sample_datasource):
    analysis_id = f"perf-{uuid.uuid4()}"
    pipeline = {
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
                    "filename": "perf_out",
                },
                "steps": [],
            },
        ],
    }

    manager = ProcessManager()
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id=analysis_id,
        resource_id=analysis_id,
    )
    internal_client = MagicMock()
    internal_client.create_engine_run.return_value = "run-1"
    internal_client.engine_run_state.return_value = {"result_json": {}}
    try:
        with patch("runtime.compute_service.client_from_env", return_value=internal_client):
            preview_result, preview_ms = _measure(
                compute_service.preview_step,
                session=None,
                manager=manager,
                target_step_id="source",
                analysis_pipeline=pipeline,
                row_limit=100,
                page=1,
                analysis_id=analysis_id,
                request_json={
                    "analysis_id": analysis_id,
                    "analysis_pipeline": pipeline,
                    "target_step_id": "source",
                },
            )

            schema_result, schema_ms = _measure(
                compute_service.get_step_schema,
                session=None,
                manager=manager,
                target_step_id="source",
                analysis_id=analysis_id,
                analysis_pipeline=pipeline,
            )

            export_result, export_ms = _measure(
                compute_service.download_step,
                session=None,
                manager=manager,
                target_step_id="source",
                analysis_pipeline=pipeline,
                export_format="csv",
                analysis_id=analysis_id,
            )
    finally:
        if manager.get_engine(identity):
            manager.shutdown_engine(identity)

    file_bytes, _name, _content_type = export_result

    assert preview_result.total_rows == 5
    assert schema_result.columns
    assert file_bytes is not None

    print(
        json.dumps(
            {
                "preview_duration_ms": preview_ms,
                "schema_duration_ms": schema_ms,
                "export_duration_ms": export_ms,
                "preview_rows": preview_result.total_rows,
            },
        ),
    )
