import json
import tempfile
import time
import uuid
from pathlib import Path

from runtime import polars_compute


def _measure(func, *args, **kwargs):
    started = time.perf_counter()
    result = func(*args, **kwargs)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return result, duration_ms


def test_direct_polars_execution_baseline(sample_datasource):
    job_id = f"perf-{uuid.uuid4()}"
    datasource_config = {
        "source_type": sample_datasource.source_type,
        **sample_datasource.config,
        "branch": "master",
    }
    steps: list[dict] = []

    preview_result, preview_ms = _measure(
        polars_compute.execute_preview,
        datasource_config,
        steps,
        100,
        0,
        job_id,
    )
    schema_result, schema_ms = _measure(
        polars_compute.execute_schema,
        datasource_config,
        steps,
        job_id,
    )
    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / "perf_out.csv"
        export_result, export_ms = _measure(
            polars_compute.execute_export,
            datasource_config,
            steps,
            str(output_path),
            "csv",
            job_id,
        )
        file_bytes = output_path.read_bytes()

    assert preview_result["row_count"] == 5
    assert schema_result["columns"]
    assert export_result["row_count"] == 5
    assert file_bytes

    print(
        json.dumps(
            {
                "execution_path": "direct_polars_compute",
                "preview_duration_ms": preview_ms,
                "schema_duration_ms": schema_ms,
                "export_duration_ms": export_ms,
                "preview_rows": preview_result["row_count"],
            },
        ),
    )
