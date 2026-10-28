"""Shared worker test doubles and loaders, imported by several test modules."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dataforge_protocol import compute_pb2, enums_pb2


class FakeEngine:
    # Plain class attributes keep these assignable on instances and overridable by subclass properties.
    container_id: str | None = None
    image_digest: str | None = None
    termination_reason: str | None = None
    exit_code: int | None = None
    oom_killed: bool | None = None
    docker_host: str | None = None

    def __init__(self, resource_id: str, resource_config: dict | None = None) -> None:
        self.analysis_id = resource_id
        self.resource_config = resource_config or {}
        self.effective_resources: dict[str, object] = {}
        self.current_job_id: str | None = None
        self._alive = False
        self._capacity_notifier = None
        self.cancelled_jobs: list[str | None] = []

    def bind_identity(self, identity: compute_pb2.ComputeWorkerIdentity, *, resource_config: dict | None = None, namespace: str | None = None) -> None:
        return None

    def bind_capacity_notifier(self, notifier) -> None:
        self._capacity_notifier = notifier

    @property
    def lifecycle_status(self) -> str:
        return "running" if self.current_job_id else "idle"

    @property
    def process_id(self) -> int | None:
        return 1234

    def start(self) -> None:
        self._alive = True

    def is_process_alive(self) -> bool:
        return self._alive

    @property
    def last_known_alive(self) -> bool:
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

    def cancel_job(self, job_id: str | None = None) -> bool:
        self.cancelled_jobs.append(job_id)
        return True

    def shutdown(self) -> None:
        self._alive = False
        if self._capacity_notifier is not None:
            self._capacity_notifier()


class BlockingEngine(FakeEngine):
    """Runs an optional test hook before start() or shutdown() so the test can hold that transition open."""

    def __init__(
        self,
        resource_id: str,
        resource_config: dict | None = None,
        *,
        before_start: Callable[[], object] | None = None,
        before_shutdown: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(resource_id, resource_config)
        self._before_start = before_start
        self._before_shutdown = before_shutdown

    def start(self) -> None:
        if self._before_start is not None:
            self._before_start()
        super().start()

    def shutdown(self) -> None:
        if self._before_shutdown is not None:
            self._before_shutdown()
        super().shutdown()


def fake_engine_factory(identity: compute_pb2.ComputeWorkerIdentity, resource_config: dict | None = None) -> Any:
    return FakeEngine(identity.resource_id, resource_config)


def load_runtime_process() -> Any:
    """Load the worker entry point (main.py) as a fresh module so tests can patch its globals."""
    path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("worker_main_for_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load worker runtime module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compute_worker_identity(scope: int = enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE) -> compute_pb2.ComputeWorkerIdentity:
    return compute_pb2.ComputeWorkerIdentity(
        scope=scope,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        resource_id="analysis-1",
        analysis_id="analysis-1",
    )


class ProbeClient:
    """Minimal daemon answering a host probe; ``fail`` makes it unreachable."""

    def __init__(self, *, cpus: int = 4, fail: bool = False) -> None:
        self.cpus = cpus
        self.fail = fail
        self.images = type("Images", (), {"get": staticmethod(lambda _name: type("Image", (), {"id": "sha256:img"})())})()
        self.networks = type("Networks", (), {"get": staticmethod(lambda _name: object())})()

    def ping(self) -> bool:
        if self.fail:
            raise OSError("connection refused")
        return True

    def info(self) -> dict[str, object]:
        return {"NCPU": self.cpus}

    def close(self) -> None:
        return None


class FakeDockerClient:
    """Docker client stub serving canned containers, recording label filters and removals, and failing removals per id."""

    def __init__(self, containers: list[dict[str, object]], *, remove_errors: dict[str, BaseException] | None = None) -> None:
        self.api = self  # reconciliation reads containers and removals through client.api
        self._containers = containers
        self._remove_errors = remove_errors or {}
        self.filters: list[dict[str, object]] = []
        self.removed: list[str] = []

    def containers(self, *, all: bool, filters: dict[str, object]) -> list[dict[str, object]]:
        assert all
        self.filters.append(filters)
        return self._containers

    def remove_container(self, container_id: str, *, force: bool) -> None:
        assert force
        self.removed.append(container_id)
        if container_id in self._remove_errors:
            raise self._remove_errors[container_id]

    def close(self) -> None:
        return None
