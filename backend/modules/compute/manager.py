import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from modules.compute.core.base import ComputeEngine, EngineStatusInfo
from modules.compute.engine import PolarsComputeEngine
from modules.compute.schemas import EngineStatus

logger = logging.getLogger(__name__)

_RESOURCE_KEYS = frozenset({'max_threads', 'max_memory_mb', 'streaming_chunk_size'})
_SPAWN_WAIT_TIMEOUT_SECONDS = 30

EngineFactory = Callable[[str, dict | None], ComputeEngine]


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


class ProcessManager:
    def __init__(self, engine_factory: EngineFactory = _default_engine_factory) -> None:
        self._engines: dict[str, EngineInfo] = {}
        self._engines_lock = threading.Lock()
        self._engine_events: dict[str, threading.Event] = {}
        self._engine_factory = engine_factory

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

        normalized_config = self._normalize_config(resource_config)
        wait_event: threading.Event | None = None

        while True:
            shutdown_target: ComputeEngine | None = None
            with self._engines_lock:
                in_progress_event = self._engine_events.get(analysis_id)
                if in_progress_event is not None:
                    wait_event = in_progress_event
                else:
                    info = self._engines.get(analysis_id)
                    if info and not self._configs_differ(self._normalize_config(info.engine.resource_config), normalized_config):
                        info.touch()
                        logger.debug(f'Reusing existing engine for analysis {analysis_id}')
                        return info

                    self._engine_events[analysis_id] = threading.Event()
                    wait_event = None
                    if info:
                        logger.info(f'Resource config changed for analysis {analysis_id}, restarting engine')
                        shutdown_target = info.engine
                        del self._engines[analysis_id]
                    break

            if wait_event is not None and not wait_event.wait(timeout=_SPAWN_WAIT_TIMEOUT_SECONDS):
                raise RuntimeError(f'Timed out waiting for engine spawn to finish for analysis {analysis_id}')

        try:
            if shutdown_target:
                shutdown_target.shutdown()

            with self._engines_lock:
                if len(self._engines) >= settings.max_concurrent_engines:
                    idle_id: str | None = None
                    idle_info: EngineInfo | None = None
                    for engine_id, info in self._engines.items():
                        if info.engine.current_job_id and info.engine.is_process_alive():
                            continue
                        if idle_info is not None and info.last_activity >= idle_info.last_activity:
                            continue
                        idle_id = engine_id
                        idle_info = info
                    if idle_id and idle_info:
                        logger.warning(
                            f'Max concurrent engines limit reached ({settings.max_concurrent_engines}), '
                            f'evicting idle engine {idle_id} to spawn {analysis_id}',
                        )
                        idle_info.engine.shutdown()
                        del self._engines[idle_id]
                    else:
                        logger.warning(
                            f'Max concurrent engines limit reached ({settings.max_concurrent_engines}), '
                            f'cannot spawn engine for {analysis_id}',
                        )
                        raise RuntimeError(
                            f'Maximum concurrent engines limit ({settings.max_concurrent_engines}) reached. '
                            f'Please wait for existing analyses to complete or increase MAX_CONCURRENT_ENGINES.',
                        )

                logger.info(f'Spawning new engine for analysis {analysis_id} ({len(self._engines) + 1}/{settings.max_concurrent_engines})')
                engine = self._engine_factory(analysis_id, normalized_config)
                engine.start()
                if not engine.is_process_alive():
                    engine.shutdown()
                    raise RuntimeError(f'Failed to start engine for analysis {analysis_id}')
                info = EngineInfo(engine)
                self._engines[analysis_id] = info
                logger.info(f'Engine spawned successfully for analysis {analysis_id}')
                return info
        finally:
            with self._engines_lock:
                in_progress_event = self._engine_events.pop(analysis_id, None)
                if in_progress_event is not None:
                    in_progress_event.set()

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
        self.shutdown_engine(analysis_id)
        return self.spawn_engine(analysis_id, resource_config=resource_config)

    def get_engine(self, analysis_id: str) -> ComputeEngine | None:
        """Get existing engine by analysis_id."""
        with self._engines_lock:
            info = self._engines.get(analysis_id)
            return info.engine if info else None

    def get_engine_info(self, analysis_id: str) -> EngineInfo | None:
        """Get engine info by analysis_id."""
        with self._engines_lock:
            return self._engines.get(analysis_id)

    def keepalive(self, analysis_id: str) -> EngineInfo | None:
        """Update last activity for an engine (keepalive ping)."""
        with self._engines_lock:
            info = self._engines.get(analysis_id)
            if info:
                info.touch()
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

        with self._engines_lock:
            info = self._engines.get(analysis_id)
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

    def shutdown_engine(self, analysis_id: str) -> None:
        """Shutdown and remove an engine."""
        with self._engines_lock:
            if analysis_id in self._engines:
                logger.info(f'Shutting down engine for analysis {analysis_id}')
                info = self._engines[analysis_id]
                info.engine.shutdown()
                del self._engines[analysis_id]
                logger.info(f'Engine shutdown complete for analysis {analysis_id}')
            else:
                logger.debug(f'No engine found to shutdown for analysis {analysis_id}')

    def shutdown_all(self) -> None:
        """Shutdown all engines."""
        with self._engines_lock:
            analysis_ids = list(self._engines.keys())

        for analysis_id in analysis_ids:
            self.shutdown_engine(analysis_id)

    def cleanup_idle_engines(self) -> list[str]:
        """Shutdown engines that have been idle too long. Returns list of cleaned up analysis_ids."""
        from core.config import settings  # Import here to avoid circular import

        cleaned = []
        shutdown_targets: list[tuple[str, ComputeEngine]] = []
        with self._engines_lock:
            for analysis_id, info in list(self._engines.items()):
                info.engine.check_health()

                if info.engine.current_job_id and info.engine.is_process_alive():
                    continue

                if not info.is_idle_for(settings.engine_idle_timeout):
                    continue

                shutdown_targets.append((analysis_id, info.engine))
                del self._engines[analysis_id]
                cleaned.append(analysis_id)

        for analysis_id, engine in shutdown_targets:
            logger.info(f'Shutting down engine for analysis {analysis_id}')
            engine.shutdown()
        return cleaned

    def list_engines(self) -> list[str]:
        """List all active engine analysis_ids."""
        with self._engines_lock:
            return list(self._engines.keys())

    def list_all_engine_statuses(self) -> list[EngineStatusInfo]:
        """Get status info for all engines."""
        defaults = self._get_defaults()
        with self._engines_lock:
            analysis_ids = list(self._engines.keys())
        return [self.get_engine_status(aid, defaults=defaults) for aid in analysis_ids]
