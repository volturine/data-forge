from __future__ import annotations

import time
from typing import Any, cast

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_engine import PolarsComputeEngine
from runtime.compute_manager import ProcessManager


class _FakeEngine:
    def __init__(self, resource_id: str, resource_config: dict | None = None) -> None:
        self.analysis_id = resource_id
        self.resource_config = resource_config or {}
        self.effective_resources: dict[str, object] = {}
        self.current_job_id: str | None = None
        self._alive = False

    @property
    def process_id(self) -> int | None:
        return 1234

    def start(self) -> None:
        self._alive = True

    def is_process_alive(self) -> bool:
        return self._alive

    def check_health(self) -> bool:
        return self._alive

    def preview(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def export(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def get_schema(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def get_row_count(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def get_result(self, timeout: float = 1.0, job_id: str | None = None):
        raise NotImplementedError

    def get_progress_event(self, timeout: float = 1.0, job_id: str | None = None):
        raise NotImplementedError

    def shutdown(self) -> None:
        self._alive = False


def test_process_manager_reaps_idle_shared_engines(monkeypatch) -> None:
    from runtime.config import settings

    monkeypatch.setattr(settings, "engine_idle_ttl_seconds", 1)
    monkeypatch.setattr(settings, "engine_idle_reap_interval_seconds", 1)

    def fake_engine_factory(identity: compute_pb2.EngineIdentity, resource_config: dict | None = None):
        return cast(Any, _FakeEngine(identity.resource_id, resource_config))

    manager = ProcessManager(engine_factory=fake_engine_factory)
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id="analysis-1",
        resource_id="analysis-1",
    )
    try:
        manager.spawn_engine(identity)
        assert manager.get_engine(identity) is not None

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and manager.get_engine(identity) is not None:
            time.sleep(0.05)

        assert manager.get_engine(identity) is None
    finally:
        manager.shutdown_all()


def test_process_manager_shutdown_stops_real_engine_subprocess() -> None:
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id="analysis-shutdown",
        resource_id="analysis-shutdown",
    )
    manager = ProcessManager(engine_factory=lambda identity, resource_config: PolarsComputeEngine(identity.resource_id, resource_config))
    engine = manager.spawn_engine(identity).engine
    try:
        assert engine.is_process_alive()

        manager.shutdown_engine(identity)

        assert manager.get_engine(identity) is None
        assert not engine.is_process_alive()
    finally:
        manager.shutdown_all()
