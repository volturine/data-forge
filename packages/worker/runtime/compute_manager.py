import contextlib
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from runtime.compute_engine import PolarsComputeEngine
from runtime.config import settings
from runtime.engine_identity import parse_engine_identity
from runtime.namespace import get_namespace, reset_namespace, set_namespace_context
from worker_models.compute.base import ComputeEngine, EngineStatusInfo
from worker_models.compute.schemas import EngineStatus

logger = logging.getLogger(__name__)

_RESOURCE_KEYS = frozenset({"max_threads", "max_memory_mb", "streaming_chunk_size"})

EngineFactory = Callable[[str, dict | None], ComputeEngine]
EngineSnapshotListener = Callable[[list[EngineStatusInfo]], None]


def _default_engine_factory(engine_key: str, resource_config: dict | None = None) -> ComputeEngine:
    return PolarsComputeEngine(engine_key, resource_config=resource_config)


class EngineInfo:
    """Tracks engine metadata for reuse, status, and eviction decisions."""

    def __init__(self, engine: ComputeEngine):
        self.engine = engine
        self.last_activity = datetime.now(UTC)
        self.current_build_id: str | None = None
        self.current_engine_run_id: str | None = None

    def touch(self) -> None:
        self.last_activity = datetime.now(UTC)


class ProcessManager:
    def __init__(
        self,
        engine_factory: EngineFactory = _default_engine_factory,
        on_snapshot: EngineSnapshotListener | None = None,
    ) -> None:
        self._engines: dict[str, EngineInfo] = {}
        self._engines_lock = threading.Lock()
        self._engine_events: dict[str, threading.Event] = {}
        self._engine_factory = engine_factory
        self._on_snapshot = on_snapshot
        self._idle_ttl_seconds = settings.engine_idle_ttl_seconds
        self._idle_reap_interval_seconds = settings.engine_idle_reap_interval_seconds
        self._reaper_stop = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        if self._idle_ttl_seconds > 0:
            self._reaper_thread = threading.Thread(target=self._reap_idle_engines_loop, name="engine-idle-reaper", daemon=True)
            self._reaper_thread.start()

    def _key(self, engine_key: str, namespace: str | None = None) -> str:
        return f"{namespace or get_namespace()}:{engine_key}"

    def _split_key(self, key: str) -> tuple[str, str]:
        namespace, _, engine_key = key.partition(":")
        return namespace, engine_key

    def spawn_engine(self, engine_key: str, resource_config: dict | None = None) -> EngineInfo:
        """Spawn a new compute engine or reuse an existing one for the same engine key."""
        normalized_config = self._normalize_config(resource_config)
        qualified_key = self._key(engine_key)
        namespace, _ = self._split_key(qualified_key)
        wait_event: threading.Event | None = None
        reused_info: EngineInfo | None = None
        shutdown_target: ComputeEngine | None = None
        changed_namespaces: set[str] = {namespace}

        while True:
            with self._engines_lock:
                in_progress_event = self._engine_events.get(qualified_key)
                if in_progress_event is not None:
                    wait_event = in_progress_event
                else:
                    info = self._engines.get(qualified_key)
                    if info and not self._configs_differ(
                        self._normalize_config(info.engine.resource_config),
                        normalized_config,
                    ):
                        info.touch()
                        logger.debug("Reusing existing engine for key %s", engine_key)
                        reused_info = info
                        break

                    self._engine_events[qualified_key] = threading.Event()
                    if info is not None:
                        logger.info("Resource config changed for engine %s, restarting", engine_key)
                        shutdown_target = info.engine
                        info.current_build_id = None
                        info.current_engine_run_id = None
                        del self._engines[qualified_key]
                    break

            if wait_event is not None:
                wait_event.wait()
                wait_event = None

        if reused_info is not None:
            self._emit_snapshot_for_namespaces(changed_namespaces)
            return reused_info

        spawned_info: EngineInfo | None = None
        try:
            if shutdown_target is not None:
                shutdown_target.shutdown()

            evict_target: tuple[str, EngineInfo] | None = None
            with self._engines_lock:
                if len(self._engines) >= settings.max_concurrent_engines:
                    idle_key: str | None = None
                    idle_info: EngineInfo | None = None
                    for active_key, info in self._engines.items():
                        engine = info.engine
                        if engine.current_job_id and engine.is_process_alive():
                            continue
                        if idle_info is not None and info.last_activity >= idle_info.last_activity:
                            continue
                        idle_key = active_key
                        idle_info = info
                    if idle_key is not None and idle_info is not None:
                        idle_namespace, evicted_engine_key = self._split_key(idle_key)
                        logger.info(
                            "Max concurrent engines limit reached (%s), evicting idle engine %s in namespace %s to spawn %s",
                            settings.max_concurrent_engines,
                            evicted_engine_key,
                            idle_namespace,
                            engine_key,
                        )
                        evict_target = idle_key, idle_info
                        del self._engines[idle_key]
                        changed_namespaces.add(idle_namespace)
                    else:
                        logger.warning(
                            "Max concurrent engines limit reached (%s), cannot spawn engine for %s",
                            settings.max_concurrent_engines,
                            engine_key,
                        )
                        raise RuntimeError(
                            f"Maximum concurrent engines limit ({settings.max_concurrent_engines}) reached. "
                            "Please wait for existing analyses to complete or increase MAX_CONCURRENT_ENGINES.",
                        )

            if evict_target is not None:
                _, evicted_info = evict_target
                evicted_info.engine.shutdown()

            with self._engines_lock:
                logger.info(
                    "Spawning new engine for key %s (%s/%s)",
                    engine_key,
                    len(self._engines) + 1,
                    settings.max_concurrent_engines,
                )
                engine = self._engine_factory(engine_key, normalized_config)
                engine.start()
                if not engine.is_process_alive():
                    engine.shutdown()
                    raise RuntimeError(f"Failed to start engine for {engine_key}")
                info = EngineInfo(engine)
                self._engines[qualified_key] = info
                spawned_info = info
                logger.info("Engine spawned successfully for key %s", engine_key)
        finally:
            with self._engines_lock:
                in_progress_event = self._engine_events.pop(qualified_key, None)
                if in_progress_event is not None:
                    in_progress_event.set()

        if spawned_info is None:
            raise RuntimeError(f"Failed to start engine for {engine_key}")
        self._emit_snapshot_for_namespaces(changed_namespaces)
        return spawned_info

    def _configs_differ(self, old_config: dict, new_config: dict) -> bool:
        return any(old_config.get(k) != new_config.get(k) for k in _RESOURCE_KEYS)

    def _normalize_config(self, config: dict | None) -> dict:
        if not config:
            return {}
        defaults = self._get_defaults()
        return {k: v for k in _RESOURCE_KEYS if (v := config.get(k)) is not None and v != defaults.get(k)}

    def get_or_create_engine(self, engine_key: str, resource_config: dict | None = None) -> ComputeEngine:
        info = self.spawn_engine(engine_key, resource_config=resource_config)
        return info.engine

    def restart_engine_with_config(self, engine_key: str, resource_config: dict) -> EngineInfo:
        logger.info("Restarting engine for key %s with new config: %s", engine_key, resource_config)
        self.shutdown_engine(engine_key, emit_snapshot=False)
        return self.spawn_engine(engine_key, resource_config=resource_config)

    def get_engine(self, engine_key: str, *, namespace: str | None = None) -> ComputeEngine | None:
        qualified_key = self._key(engine_key, namespace=namespace)
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            return info.engine if info else None

    def get_engine_info(self, engine_key: str, *, namespace: str | None = None) -> EngineInfo | None:
        qualified_key = self._key(engine_key, namespace=namespace)
        with self._engines_lock:
            return self._engines.get(qualified_key)

    def set_engine_runtime_context(self, engine_key: str, *, current_build_id: str | None, current_engine_run_id: str | None) -> None:
        qualified_key = self._key(engine_key)
        namespace, _ = self._split_key(qualified_key)
        changed = False
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            if info is not None:
                if info.current_build_id != current_build_id:
                    info.current_build_id = current_build_id
                    changed = True
                if info.current_engine_run_id != current_engine_run_id:
                    info.current_engine_run_id = current_engine_run_id
                    changed = True
        if changed:
            self._emit_snapshot_for_namespaces({namespace})

    def _get_defaults(self) -> dict:
        return {
            "max_threads": settings.polars_max_threads,
            "max_memory_mb": settings.polars_max_memory_mb,
            "streaming_chunk_size": settings.polars_streaming_chunk_size,
        }

    def get_engine_status(self, engine_key: str, *, defaults: dict | None = None) -> EngineStatusInfo:
        if defaults is None:
            defaults = self._get_defaults()

        identity = parse_engine_identity(engine_key)
        qualified_key = self._key(engine_key)
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            if info is None:
                return EngineStatusInfo(
                    analysis_id=engine_key,
                    status=EngineStatus.TERMINATED,
                    process_id=None,
                    last_activity=None,
                    current_job_id=None,
                    resource_config=None,
                    effective_resources=None,
                    defaults=defaults,
                    scope=identity.scope.value,
                    reuse_policy=identity.reuse_policy.value,
                    datasource_id=identity.datasource_id,
                    build_id=identity.build_id,
                    current_build_id=identity.build_id,
                    current_engine_run_id=None,
                )

            engine = info.engine
            engine.check_health()
            is_alive = engine.is_process_alive()
            resource_config = (self._normalize_config(engine.resource_config) or None) if engine.resource_config else None
            effective_resources = engine.effective_resources or None

            return EngineStatusInfo(
                analysis_id=engine_key,
                status=EngineStatus.HEALTHY if is_alive else EngineStatus.TERMINATED,
                process_id=engine.process_id,
                last_activity=info.last_activity.isoformat(),
                current_job_id=engine.current_job_id,
                resource_config=resource_config,
                effective_resources=effective_resources,
                defaults=defaults,
                scope=identity.scope.value,
                reuse_policy=identity.reuse_policy.value,
                datasource_id=identity.datasource_id,
                build_id=identity.build_id,
                current_build_id=info.current_build_id or identity.build_id,
                current_engine_run_id=info.current_engine_run_id,
            )

    def shutdown_engine(self, engine_key: str, *, namespace: str | None = None, emit_snapshot: bool = True) -> None:
        qualified_key = self._key(engine_key, namespace=namespace)
        namespace, _ = self._split_key(qualified_key)
        info: EngineInfo | None = None
        with self._engines_lock:
            info = self._engines.pop(qualified_key, None)
        if info is None:
            logger.debug("No engine found to shutdown for key %s", engine_key)
            return
        logger.info("Shutting down engine for key %s", engine_key)
        info.engine.shutdown()
        logger.info("Engine shutdown complete for key %s", engine_key)
        if emit_snapshot:
            self._emit_snapshot_for_namespaces({namespace})

    def shutdown_all(self) -> None:
        self._reaper_stop.set()
        if self._reaper_thread is not None and self._reaper_thread.is_alive():
            self._reaper_thread.join(timeout=1.0)
        with self._engines_lock:
            shutdown_targets = list(self._engines.items())
            self._engines.clear()
        changed_namespaces = {self._split_key(key)[0] for key, _ in shutdown_targets}
        for key, info in shutdown_targets:
            _namespace, engine_key = self._split_key(key)
            logger.info("Shutting down engine for key %s", engine_key)
            info.engine.shutdown()
        if changed_namespaces:
            self._emit_snapshot_for_namespaces(changed_namespaces)

    def list_engines(self) -> list[str]:
        namespace = get_namespace()
        with self._engines_lock:
            return [engine_key for key in self._engines for key_namespace, engine_key in [self._split_key(key)] if key_namespace == namespace]

    def list_all_engine_statuses(self) -> list[EngineStatusInfo]:
        return self._list_engine_statuses_for_namespace(get_namespace())

    def _list_engine_statuses_for_namespace(self, namespace: str) -> list[EngineStatusInfo]:
        defaults = self._get_defaults()
        with self._engines_lock:
            engine_keys = [engine_key for key in self._engines for key_namespace, engine_key in [self._split_key(key)] if key_namespace == namespace]
        return [self.get_engine_status(engine_key, defaults=defaults) for engine_key in engine_keys]

    def _emit_snapshot_for_namespaces(self, namespaces: set[str]) -> None:
        if self._on_snapshot is None:
            return
        for namespace in sorted(namespaces):
            token = set_namespace_context(namespace)
            try:
                self._on_snapshot(self._list_engine_statuses_for_namespace(namespace))
            finally:
                reset_namespace(token)

    def _reap_idle_engines_loop(self) -> None:
        while not self._reaper_stop.wait(self._idle_reap_interval_seconds):
            self._reap_idle_engines_once()

    def _reap_idle_engines_once(self) -> None:
        now = datetime.now(UTC)
        stale: list[tuple[str, EngineInfo]] = []
        changed_namespaces: set[str] = set()
        with self._engines_lock:
            for key, info in list(self._engines.items()):
                engine = info.engine
                is_alive = engine.is_process_alive()
                is_busy = bool(engine.current_job_id and is_alive)
                idle_seconds = (now - info.last_activity).total_seconds()
                if is_alive and (is_busy or idle_seconds < self._idle_ttl_seconds):
                    continue
                stale.append((key, info))
                del self._engines[key]
                changed_namespaces.add(self._split_key(key)[0])
        for key, info in stale:
            _namespace, engine_key = self._split_key(key)
            with contextlib.suppress(Exception):
                logger.info("Reaping idle engine %s", engine_key)
                info.engine.shutdown()
        if changed_namespaces:
            self._emit_snapshot_for_namespaces(changed_namespaces)
