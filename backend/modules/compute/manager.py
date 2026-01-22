import logging
import threading
from datetime import UTC, datetime

from modules.compute.engine import PolarsComputeEngine
from modules.compute.schemas import EngineStatus

logger = logging.getLogger(__name__)


class EngineInfo:
    """Tracks engine state and activity."""

    def __init__(self, engine: PolarsComputeEngine):
        self.engine = engine
        self.last_activity = datetime.now(UTC)
        self.status = EngineStatus.IDLE

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.now(UTC)

    def is_idle_for(self, seconds: int) -> bool:
        """Check if engine has been idle for more than N seconds."""
        elapsed = (datetime.now(UTC) - self.last_activity).total_seconds()
        return elapsed > seconds


class ProcessManager:
    _instance: 'ProcessManager | None' = None
    _engines: dict[str, EngineInfo]
    _lock = threading.Lock()

    def __new__(cls) -> 'ProcessManager':
        if cls._instance is None:
            with cls._lock:
                # Double-check pattern to ensure thread safety
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._engines = {}
                    cls._instance._engines_lock = threading.Lock()
        return cls._instance

    def spawn_engine(self, analysis_id: str) -> EngineInfo:
        """
        Spawn a new compute engine for an analysis or return existing one.

        This method is thread-safe and will reuse an existing engine if one
        is already running for the given analysis_id.

        Args:
            analysis_id: Unique identifier for the analysis

        Returns:
            EngineInfo containing the engine and metadata

        Raises:
            RuntimeError: If max concurrent engines limit is reached
        """
        from core.config import settings

        with self._engines_lock:
            if analysis_id in self._engines:
                info = self._engines[analysis_id]
                info.touch()
                logger.debug(f'Reusing existing engine for analysis {analysis_id}')
                return info

            # Check if we've reached max concurrent engines
            if len(self._engines) >= settings.max_concurrent_engines:
                logger.warning(
                    f'Max concurrent engines limit reached ({settings.max_concurrent_engines}), cannot spawn engine for {analysis_id}'
                )
                raise RuntimeError(
                    f'Maximum concurrent engines limit ({settings.max_concurrent_engines}) reached. '
                    f'Please wait for existing analyses to complete or increase MAX_CONCURRENT_ENGINES.'
                )

            logger.info(f'Spawning new engine for analysis {analysis_id} ({len(self._engines) + 1}/{settings.max_concurrent_engines})')
            engine = PolarsComputeEngine(analysis_id)
            engine.start()
            info = EngineInfo(engine)
            self._engines[analysis_id] = info
            logger.info(f'Engine spawned successfully for analysis {analysis_id}')
            return info

    def get_or_create_engine(self, analysis_id: str) -> PolarsComputeEngine:
        """Get existing engine or create a new one for the analysis."""
        info = self.spawn_engine(analysis_id)
        return info.engine

    def get_engine(self, analysis_id: str) -> PolarsComputeEngine | None:
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

    def get_engine_status(self, analysis_id: str) -> dict:
        """Get status info for an engine."""
        with self._engines_lock:
            info = self._engines.get(analysis_id)
            if not info:
                return {
                    'analysis_id': analysis_id,
                    'status': EngineStatus.TERMINATED,
                    'process_id': None,
                    'last_activity': None,
                    'current_job_id': None,
                }

            pid = None
            current_job_id = None
            if info.engine.process and info.engine.process.is_alive():
                pid = info.engine.process.pid
                current_job_id = info.engine.current_job_id
                status = EngineStatus.RUNNING if current_job_id else EngineStatus.IDLE
            else:
                status = EngineStatus.TERMINATED

            return {
                'analysis_id': analysis_id,
                'status': status,
                'process_id': pid,
                'last_activity': info.last_activity.isoformat(),
                'current_job_id': current_job_id,
            }

    def mark_running(self, analysis_id: str) -> None:
        """Mark engine as running a job."""
        with self._engines_lock:
            info = self._engines.get(analysis_id)
            if info:
                info.status = EngineStatus.RUNNING
                info.touch()

    def mark_idle(self, analysis_id: str) -> None:
        """Mark engine as idle."""
        with self._engines_lock:
            info = self._engines.get(analysis_id)
            if info:
                info.status = EngineStatus.IDLE
                info.touch()

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
        with self._engines_lock:
            analysis_ids = list(self._engines.keys())

        for analysis_id in analysis_ids:
            with self._engines_lock:
                info = self._engines.get(analysis_id)
                if not info:
                    continue

                # Skip engines with running jobs
                if info.engine.current_job_id and info.engine.process and info.engine.process.is_alive():
                    continue

                should_cleanup = info.is_idle_for(settings.engine_idle_timeout)

            if should_cleanup:
                self.shutdown_engine(analysis_id)
                cleaned.append(analysis_id)
        return cleaned

    def list_engines(self) -> list[str]:
        """List all active engine analysis_ids."""
        with self._engines_lock:
            return list(self._engines.keys())

    def list_all_engine_statuses(self) -> list[dict]:
        """Get status info for all engines."""
        with self._engines_lock:
            analysis_ids = list(self._engines.keys())
        return [self.get_engine_status(aid) for aid in analysis_ids]


def get_manager() -> ProcessManager:
    """Get the singleton ProcessManager instance."""
    return ProcessManager()
