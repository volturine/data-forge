from contracts.datasource.models import DataSource, DataSourceCreatedBy
from contracts.datasource.source_types import DataSourceType

from backend_core.dependencies import get_manager, get_runtime_availability_probe
from main import app


class _StubEngine:
    current_job_id = None

    @staticmethod
    def is_process_alive() -> bool:
        return False


class _StubManager:
    def __init__(self) -> None:
        self.shutdown_calls: list[str] = []

    @staticmethod
    def get_engine(engine_id: str):
        return _StubEngine() if engine_id == "analysis-1:build:build-1" else None

    def shutdown_engine(self, engine_id: str) -> None:
        self.shutdown_calls.append(engine_id)


class _AvailableRuntimeProbe:
    @staticmethod
    def available(*, kind) -> bool:
        del kind
        return True


def test_shutdown_engine_accepts_composite_build_engine_key(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.delete("/api/v1/compute/engine/analysis-1:build:build-1")
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 204
    assert manager.shutdown_calls == ["analysis-1:build:build-1"]


def test_shutdown_engine_returns_not_found_for_unknown_engine_key(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.delete("/api/v1/compute/engine/analysis-1:build:missing")
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 404
    assert manager.shutdown_calls == []


def test_start_build_recreates_deleted_output_placeholder(client, test_db_session) -> None:
    app.dependency_overrides[get_runtime_availability_probe] = lambda: _AvailableRuntimeProbe()
    try:
        response = client.post(
            "/api/v1/compute/builds",
            json={
                "analysis_pipeline": {
                    "analysis_id": "analysis-1",
                    "tabs": [
                        {
                            "id": "tab-1",
                            "name": "Source 1",
                            "datasource": {
                                "id": "source-1",
                                "analysis_tab_id": None,
                                "source_type": "iceberg",
                                "config": {"branch": "master"},
                            },
                            "output": {
                                "result_id": "11111111-1111-4111-8111-111111111111",
                                "format": "parquet",
                                "filename": "source_1",
                                "build_mode": "full",
                                "iceberg": {
                                    "namespace": "outputs",
                                    "table_name": "source_1",
                                    "branch": "master",
                                },
                            },
                            "steps": [],
                        }
                    ],
                },
                "tab_id": "tab-1",
            },
        )
    finally:
        app.dependency_overrides.pop(get_runtime_availability_probe, None)

    assert response.status_code == 200
    datasource = test_db_session.get(DataSource, "11111111-1111-4111-8111-111111111111")
    assert datasource is not None
    assert datasource.name == "source_1"
    assert datasource.source_type == DataSourceType.ICEBERG.value
    assert datasource.config["metadata_path"].endswith("/exports/11111111-1111-4111-8111-111111111111")
    assert datasource.config["table"] == "11111111-1111-4111-8111-111111111111_master"
    assert datasource.config["table_name"] == "source_1"
    assert datasource.config["branch"] == "master"
    assert datasource.config["analysis_tab_id"] == "tab-1"
    assert datasource.created_by == DataSourceCreatedBy.ANALYSIS.value
    assert datasource.created_by_analysis_id == "analysis-1"
    assert datasource.is_hidden is True
