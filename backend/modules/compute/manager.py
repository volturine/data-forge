import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from core.namespace import get_namespace, reset_namespace, set_namespace_context
from modules.compute.core.base import ComputeEngine, EngineStatusInfo
from modules.compute.engine import PolarsComputeEngine
from modules.compute.schemas import EngineStatus

logger = logging.getLogger(__name__)

_RESOURCE_KEYS = frozenset({'max_threads', 'max_memory_mb', 'streaming_chunk_size'})
_SPAWN_WAIT_TIMEOUT_SECONDS = 30

EngineFactory = Callable[[str, dict | None], ComputeEngine]
EngineSnapshotListener = Callable[[list[EngineStatusInfo]], None]


def _default_engine_factory(analysis_id: str, resource_config: dict | None = None) -> ComputeEngine:
    return PolarsComputeEngine(analysis_id, resource_config=resource_config)


class EngineInfo:
    """Tracks engine and activity timestamp."""

    def __init__(self, engine: ComputeEngine):
        self.engine = engine
        self.last_activity = datetime.now(UTC)

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.now(UTC)

    def is_idle_for(self, seconds: int) -> bool:
        """Check if engine has been idle for more than N seconds."""
        elapsed = (datetime.now(UTC) - self.last_activity).total_seconds()
        return elapsed > seconds

    def seconds_until_idle(self, seconds: int) -> float:
        """Return seconds remaining before this engine becomes idle."""
        elapsed = (datetime.now(UTC) - self.last_activity).total_seconds()
        return max(0.0, seconds - elapsed)


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

    def _key(self, analysis_id: str, namespace: str | None = None) -> str:
        return f'{namespace or get_namespace()}:{analysis_id}'

    def _split_key(self, key: str) -> tuple[str, str]:
        namespace, _, analysis_id = key.partition(':')
        return namespace, analysis_id

    def spawn_engine(self, analysis_id: str, resource_config: dict | None = None) -> EngineInfo:
        """Spawn a new compute engine for an analysis or return existing one.

        This method is thread-safe and will reuse an existing engine if one
        is already running for the given analysis_id with the same config.
        If the config differs, the existing engine will be restarted.

        Args:
            analysis_id: Unique identifier for the analysis
            resource_config: Optional resource overrides (max_threads, max_memory_mb, streaming_chunk_size)

        Returns:
            EngineInfo containing the engine and metadata

        Raises:
            RuntimeError: If max concurrent engines limit is reached
        """
        from core.config import settings

        key = self._key(analysis_id)
        normalized_config = self._normalize_config(resource_config)
        wait_event: threading.Event | None = None
        reused_info: EngineInfo | None = None

        while True:
            shutdown_target: ComputeEngine | None = None
            with self._engines_lock:
                in_progress_event = self._engine_events.get(key)
                if in_progress_event is not None:
                    wait_event = in_progress_event
                else:
                    info = self._engines.get(key)
                    if info and not self._configs_differ(self._normalize_config(info.engine.resource_config), normalized_config):
                        info.touch()
                        logger.debug(f'Reusing existing engine for analysis {analysis_id}')
                        reused_info = info
                        break

                    self._engine_events[key] = threading.Event()
                    wait_event = None
                    if info:
                        logger.info(f'Resource config changed for analysis {analysis_id}, restarting engine')
                        shutdown_target = info.engine
                        del self._engines[key]
                    break

            if wait_event is not None and not wait_event.wait(timeout=_SPAWN_WAIT_TIMEOUT_SECONDS):
                raise RuntimeError(f'Timed out waiting for engine spawn to finish for analysis {analysis_id}')

        if reused_info is not None:
            self._emit_snapshot()
            return reused_info

        spawned_info: EngineInfo | None = None
        try:
            if shutdown_target:
                shutdown_target.shutdown()

            evict_engine: ComputeEngine | None = None
            with self._engines_lock:
                if len(self._engines) >= settings.max_concurrent_engines:
                    idle_key: str | None = None
                    idle_info: EngineInfo | None = None
                    for engine_key, info in self._engines.items():
                        if info.engine.current_job_id and info.engine.is_process_alive():
                            continue
                        if idle_info is not None and info.last_activity >= idle_info.last_activity:
                            continue
                        idle_key = engine_key
                        idle_info = info
                    if idle_key and idle_info:
                        idle_namespace, idle_analysis_id = self._split_key(idle_key)
                        logger.warning(
                            f'Max concurrent engines limit reached ({settings.max_concurrent_engines}), '
                            f'evicting idle engine {idle_analysis_id} in namespace {idle_namespace} to spawn {analysis_id}',
                        )
                        evict_engine = idle_info.engine
                        del self._engines[idle_key]
                    else:
                        logger.warning(
                            f'Max concurrent engines limit reached ({settings.max_concurrent_engines}), '
                            f'cannot spawn engine for {analysis_id}',
                        )
                        raise RuntimeError(
                            f'Maximum concurrent engines limit ({settings.max_concurrent_engines}) reached. '
                            f'Please wait for existing analyses to complete or increase MAX_CONCURRENT_ENGINES.',
                        )

            if evict_engine is not None:
                evict_engine.shutdown()

            with self._engines_lock:
                logger.info(f'Spawning new engine for analysis {analysis_id} ({len(self._engines) + 1}/{settings.max_concurrent_engines})')
                engine = self._engine_factory(analysis_id, normalized_config)
                engine.start()
                if not engine.is_process_alive():
                    engine.shutdown()
                    raise RuntimeError(f'Failed to start engine for analysis {analysis_id}')
                info = EngineInfo(engine)
                self._engines[key] = info
                logger.info(f'Engine spawned successfully for analysis {analysis_id}')
                spawned_info = info
        finally:
            with self._engines_lock:
                in_progress_event = self._engine_events.pop(key, None)
                if in_progress_event is not None:
                    in_progress_event.set()
        if spawned_info is None:
            raise RuntimeError(f'Failed to start engine for analysis {analysis_id}')
        self._emit_snapshot()
        return spawned_info

    def _configs_differ(self, old_config: dict, new_config: dict) -> bool:
        return any(old_config.get(k) != new_config.get(k) for k in _RESOURCE_KEYS)

    def _normalize_config(self, config: dict | None) -> dict:
        if not config:
            return {}
        defaults = self._get_defaults()
        return {k: v for k in _RESOURCE_KEYS if (v := config.get(k)) is not None and v != defaults.get(k)}

    def get_or_create_engine(self, analysis_id: str, resource_config: dict | None = None) -> ComputeEngine:
        """Get existing engine or create a new one for the analysis."""
        info = self.spawn_engine(analysis_id, resource_config=resource_config)
        return info.engine

    def restart_engine_with_config(self, analysis_id: str, resource_config: dict) -> EngineInfo:
        """Restart engine with new resource configuration.

        This will shutdown any existing engine and spawn a new one with the
        provided resource configuration. Any in-progress jobs will be terminated.

        Args:
            analysis_id: Unique identifier for the analysis
            resource_config: Resource overrides (max_threads, max_memory_mb, streaming_chunk_size)

        Returns:
            EngineInfo containing the new engine
        """
        logger.info(f'Restarting engine for analysis {analysis_id} with new config: {resource_config}')
        self.shutdown_engine(analysis_id, emit_snapshot=False)
        return self.spawn_engine(analysis_id, resource_config=resource_config)

    def get_engine(self, analysis_id: str) -> ComputeEngine | None:
        """Get existing engine by analysis_id."""
        key = self._key(analysis_id)
        with self._engines_lock:
            info = self._engines.get(key)
            return info.engine if info else None

    def get_engine_info(self, analysis_id: str) -> EngineInfo | None:
        """Get engine info by analysis_id."""
        key = self._key(analysis_id)
        with self._engines_lock:
            return self._engines.get(key)

    def keepalive(self, analysis_id: str) -> EngineInfo | None:
        """Update last activity for an engine (keepalive ping)."""
        key = self._key(analysis_id)
        with self._engines_lock:
            info = self._engines.get(key)
            if info:
                info.touch()
        if info:
            self._emit_snapshot()
        return info

    def _get_defaults(self) -> dict:
        """Get default resource settings from environment."""
        from core.config import settings

        return {
            'max_threads': settings.polars_max_threads,
            'max_memory_mb': settings.polars_max_memory_mb,
            'streaming_chunk_size': settings.polars_streaming_chunk_size,
        }

    def get_engine_status(self, analysis_id: str, *, defaults: dict | None = None) -> EngineStatusInfo:
        """Get status info for an engine - non-blocking."""
        if defaults is None:
            defaults = self._get_defaults()

        key = self._key(analysis_id)
        with self._engines_lock:
            info = self._engines.get(key)
            if not info:
                return EngineStatusInfo(
                    analysis_id=analysis_id,
                    status=EngineStatus.TERMINATED,
                    process_id=None,
                    last_activity=None,
                    current_job_id=None,
                    resource_config=None,
                    effective_resources=None,
                    defaults=defaults,
                )

            engine = info.engine
            engine.check_health()

            is_alive = engine.is_process_alive()
            resource_config = (self._normalize_config(engine.resource_config) or None) if engine.resource_config else None
            effective_resources = engine.effective_resources or None

            return EngineStatusInfo(
                analysis_id=analysis_id,
                status=EngineStatus.HEALTHY if is_alive else EngineStatus.TERMINATED,
                process_id=engine.process_id,
                last_activity=info.last_activity.isoformat(),
                current_job_id=engine.current_job_id,
                resource_config=resource_config,
                effective_resources=effective_resources,
                defaults=defaults,
            )

    def shutdown_engine(self, analysis_id: str, *, emit_snapshot: bool = True) -> None:
        """Shutdown and remove an engine."""
        removed = False
        key = self._key(analysis_id)
        with self._engines_lock:
            if key in self._engines:
                logger.info(f'Shutting down engine for analysis {analysis_id}')
                info = self._engines[key]
                info.engine.shutdown()
                del self._engines[key]
                removed = True
                logger.info(f'Engine shutdown complete for analysis {analysis_id}')
            else:
                logger.debug(f'No engine found to shutdown for analysis {analysis_id}')
        if removed and emit_snapshot:
            self._emit_snapshot()

    def shutdown_all(self) -> None:
        """Shutdown all engines."""
        with self._engines_lock:
            shutdown_targets = [(analysis_id, info.engine) for analysis_id, info in self._engines.items()]
            self._engines.clear()

        for key, engine in shutdown_targets:
            _namespace, analysis_id = self._split_key(key)
            logger.info(f'Shutting down engine for analysis {analysis_id}')
            engine.shutdown()
        if shutdown_targets:
            self._emit_snapshot()

    def cleanup_idle_engines(self) -> list[str]:
        """Shutdown idle engines across namespaces. Returns namespaced engine keys."""
        from core.config import settings  # Import here to avoid circular import

        cleaned = []
        shutdown_targets: list[tuple[str, str, ComputeEngine]] = []
        with self._engines_lock:
            for key, info in list(self._engines.items()):
                namespace, analysis_id = self._split_key(key)
                info.engine.check_health()

                if info.engine.current_job_id and info.engine.is_process_alive():
                    continue

                if not info.is_idle_for(settings.engine_idle_timeout):
                    continue

                shutdown_targets.append((namespace, analysis_id, info.engine))
                del self._engines[key]
                cleaned.append(key)

        for namespace, analysis_id, engine in shutdown_targets:
            logger.info(f'Shutting down engine for analysis {analysis_id} in namespace {namespace}')
            engine.shutdown()
        changed_namespaces = {namespace for namespace, _analysis_id, _engine in shutdown_targets}
        for namespace in changed_namespaces:
            token = set_namespace_context(namespace)
            try:
                self._emit_snapshot()
            finally:
                reset_namespace(token)
        return cleaned

    def next_idle_deadline_seconds(self, idle_timeout: int) -> float:
        """Return the nearest idle deadline across engines, or idle_timeout when none exist."""
        with self._engines_lock:
            if not self._engines:
                return float(idle_timeout)
            return min(info.seconds_until_idle(idle_timeout) for info in self._engines.values())

    def list_engines(self) -> list[str]:
        """List all active engine analysis_ids."""
        with self._engines_lock:
            return [
                analysis_id for key in self._engines for namespace, analysis_id in [self._split_key(key)] if namespace == get_namespace()
            ]

    def list_all_engine_statuses(self) -> list[EngineStatusInfo]:
        """Get status info for all engines."""
        defaults = self._get_defaults()
        with self._engines_lock:
            analysis_ids = [
                analysis_id for key in self._engines for namespace, analysis_id in [self._split_key(key)] if namespace == get_namespace()
            ]
        return [self.get_engine_status(aid, defaults=defaults) for aid in analysis_ids]

    def _emit_snapshot(self) -> None:
        if self._on_snapshot is None:
            return
        self._on_snapshot(self.list_all_engine_statuses())
