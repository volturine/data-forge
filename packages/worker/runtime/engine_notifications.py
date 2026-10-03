from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import Condition, Thread

from runtime.domain.compute.base import EngineStatusInfo
from runtime.worker_runtime_client import WorkerRuntimeClient, client_from_env

logger = logging.getLogger(__name__)
_SLOW_SNAPSHOT_PUBLISH_SECONDS = 1.0


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


def persist_engine_snapshot(
    *,
    worker_id: str,
    namespace: str,
    statuses: list[EngineStatusInfo],
) -> None:
    with worker_runtime_client() as client:
        client.persist_engine_snapshot(
            worker_id=worker_id,
            namespace=namespace,
            statuses=statuses,
        )


class EngineSnapshotPublisher:
    """Persist only the latest pending snapshot for each namespace."""

    def __init__(
        self,
        namespace_provider: Callable[[], str],
        persist: Callable[[str, list[EngineStatusInfo]], None],
    ) -> None:
        self._namespace_provider = namespace_provider
        self._persist = persist
        self._condition = Condition()
        self._pending: dict[str, list[EngineStatusInfo]] = {}
        self._reported_failures: set[str] = set()
        self._closing = False
        self._thread: Thread | None = None

    def __call__(self, statuses: list[EngineStatusInfo]) -> None:
        self.publish(self._namespace_provider(), statuses)

    def publish(self, namespace: str, statuses: list[EngineStatusInfo]) -> None:
        with self._condition:
            if self._closing:
                return
            self._pending[namespace] = list(statuses)
            if self._thread is None:
                self._thread = Thread(target=self._run, name="engine-snapshot-publisher", daemon=True)
                self._thread.start()
            self._condition.notify()

    def close(self, timeout_seconds: float = 10.0) -> None:
        with self._condition:
            self._closing = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout_seconds)
        if thread is not None and thread.is_alive():
            logger.warning("Engine snapshot publisher did not stop within %.1fs", timeout_seconds)

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._closing:
                    self._condition.wait()
                if not self._pending and self._closing:
                    return
                namespace = next(iter(self._pending))
                statuses = self._pending.pop(namespace)

            started = time.perf_counter()
            try:
                self._persist(namespace, statuses)
            except Exception:
                with self._condition:
                    first_failure = namespace not in self._reported_failures
                    self._reported_failures.add(namespace)
                    if not self._closing:
                        self._pending.setdefault(namespace, statuses)
                        self._condition.wait(timeout=1.0)
                if first_failure:
                    logger.warning("Failed to publish engine snapshot for namespace %s; retrying", namespace, exc_info=True)
            else:
                elapsed = time.perf_counter() - started
                if elapsed >= _SLOW_SNAPSHOT_PUBLISH_SECONDS:
                    logger.warning(
                        "Slow engine snapshot publish namespace=%s engine_count=%s duration_ms=%.1f",
                        namespace,
                        len(statuses),
                        elapsed * 1000,
                    )
                with self._condition:
                    self._reported_failures.discard(namespace)


def create_snapshot_notifier(
    *,
    namespace_provider: Callable[[], str],
    worker_id: str | None = None,
    persist: Callable[[str, list[EngineStatusInfo]], None] | None = None,
) -> EngineSnapshotPublisher:
    if persist is None and worker_id is None:
        raise ValueError("worker_id is required when persist callback is not provided")

    def persist_snapshot(namespace: str, statuses: list[EngineStatusInfo]) -> None:
        if persist is not None:
            persist(namespace, statuses)
            return
        assert worker_id is not None
        persist_engine_snapshot(worker_id=worker_id, namespace=namespace, statuses=statuses)

    return EngineSnapshotPublisher(namespace_provider, persist_snapshot)
