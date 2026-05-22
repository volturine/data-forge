from contracts.datasource.models import DataSource, DataSourceCreatedBy
from contracts.datasource.source_types import DataSourceType

from backend_core.dependencies import get_manager, get_runtime_availability_probe
from main import app
from modules.compute import routes as compute_routes


class _StubEngine:
    current_job_id = None

    @staticmethod
    def is_process_alive() -> bool:
        return False


class _StubManager:
    def __init__(self) -> None:
        self.shutdown_calls: list[str] = []
        self.spawn_calls: list[tuple[str, dict | None]] = []
        self.restart_calls: list[tuple[str, dict]] = []

    @staticmethod
    def get_engine(engine_id: str):
        return _StubEngine() if engine_id == "analysis-1:build:build-1" else None

    @staticmethod
    def get_engine_status(engine_id: str) -> dict[str, object]:
        return {"analysis_id": engine_id, "status": "healthy"}

    def spawn_engine(self, engine_id: str, resource_config: dict | None = None) -> None:
        self.spawn_calls.append((engine_id, resource_config))

    def restart_engine_with_config(self, engine_id: str, resource_config: dict) -> None:
        self.restart_calls.append((engine_id, resource_config))

    def shutdown_engine(self, engine_id: str) -> None:
        self.shutdown_calls.append(engine_id)


class _AvailableRuntimeProbe:
    @staticmethod
    def available(*, kind) -> bool:
        del kind
        return True


def test_spawn_engine_accepts_datasource_preview_analysis_id(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.post("/api/v1/compute/engine/spawn/__preview__datasource-1")
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 200
    assert response.json()["analysis_id"] == "__preview__datasource-1"
    assert manager.spawn_calls == [("__preview__datasource-1", None)]


def test_configure_engine_accepts_datasource_preview_analysis_id(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.post(
            "/api/v1/compute/engine/configure/__preview__datasource-1",
            json={"max_threads": 4},
        )
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 200
    assert response.json()["analysis_id"] == "__preview__datasource-1"
    assert manager.restart_calls == [("__preview__datasource-1", {"max_threads": 4, "max_memory_mb": None, "streaming_chunk_size": None})]


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


def test_get_engine_defaults_resolves_auto_values(client, monkeypatch) -> None:
    monkeypatch.setattr(compute_routes.settings, "polars_max_threads", 0)
    monkeypatch.setattr(compute_routes.settings, "polars_max_memory_mb", 0)
    monkeypatch.setattr(compute_routes.settings, "polars_streaming_chunk_size", 4096)
    monkeypatch.setattr(compute_routes.os, "cpu_count", lambda: 12)

    def fake_sysconf(name: str) -> int:
        if name == "SC_PHYS_PAGES":
            return 2_097_152
        if name == "SC_PAGE_SIZE":
            return 4096
        raise AssertionError(f"unexpected sysconf key: {name}")

    monkeypatch.setattr(compute_routes.os, "sysconf", fake_sysconf)

    response = client.get("/api/v1/compute/defaults")

    assert response.status_code == 200
    assert response.json() == {
        "max_threads": 12,
        "max_memory_mb": 8192,
        "streaming_chunk_size": 4096,
    }


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
