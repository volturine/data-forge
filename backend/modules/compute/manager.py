from datetime import UTC, datetime

from modules.compute.engine import PolarsComputeEngine
from modules.compute.schemas import EngineStatus


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
    _idle_timeout: int = 60  # seconds

    def __new__(cls) -> 'ProcessManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._engines = {}
        return cls._instance

    def spawn_engine(self, analysis_id: str) -> EngineInfo:
        """Spawn a new engine for the analysis or return existing one."""
        if analysis_id in self._engines:
            info = self._engines[analysis_id]
            info.touch()
            return info

        engine = PolarsComputeEngine(analysis_id)
        engine.start()
        info = EngineInfo(engine)
        self._engines[analysis_id] = info
        return info

    def get_or_create_engine(self, analysis_id: str) -> PolarsComputeEngine:
        """Get existing engine or create a new one for the analysis."""
        info = self.spawn_engine(analysis_id)
        return info.engine

    def get_engine(self, analysis_id: str) -> PolarsComputeEngine | None:
        """Get existing engine by analysis_id."""
        info = self._engines.get(analysis_id)
        return info.engine if info else None

    def get_engine_info(self, analysis_id: str) -> EngineInfo | None:
        """Get engine info by analysis_id."""
        return self._engines.get(analysis_id)

    def keepalive(self, analysis_id: str) -> EngineInfo | None:
        """Update last activity for an engine (keepalive ping)."""
        info = self._engines.get(analysis_id)
        if info:
            info.touch()
        return info

    def get_engine_status(self, analysis_id: str) -> dict:
        """Get status info for an engine."""
        info = self._engines.get(analysis_id)
        if not info:
            return {
                'analysis_id': analysis_id,
                'status': EngineStatus.TERMINATED,
                'process_id': None,
                'last_activity': None,
            }

        pid = None
        if info.engine.process and info.engine.process.is_alive():
            pid = info.engine.process.pid
            status = EngineStatus.RUNNING if info.engine.current_job_id else EngineStatus.IDLE
        else:
            status = EngineStatus.TERMINATED

        return {
            'analysis_id': analysis_id,
            'status': status,
            'process_id': pid,
            'last_activity': info.last_activity.isoformat(),
        }

    def mark_running(self, analysis_id: str) -> None:
        """Mark engine as running a job."""
        info = self._engines.get(analysis_id)
        if info:
            info.status = EngineStatus.RUNNING
            info.touch()

    def mark_idle(self, analysis_id: str) -> None:
        """Mark engine as idle."""
        info = self._engines.get(analysis_id)
        if info:
            info.status = EngineStatus.IDLE
            info.touch()

    def shutdown_engine(self, analysis_id: str) -> None:
        """Shutdown and remove an engine."""
        if analysis_id in self._engines:
            info = self._engines[analysis_id]
            info.engine.shutdown()
            del self._engines[analysis_id]

    def shutdown_all(self) -> None:
        """Shutdown all engines."""
        for analysis_id in list(self._engines.keys()):
            self.shutdown_engine(analysis_id)

    def cleanup_idle_engines(self) -> list[str]:
        """Shutdown engines that have been idle too long. Returns list of cleaned up analysis_ids."""
        cleaned = []
        for analysis_id in list(self._engines.keys()):
            info = self._engines[analysis_id]
            if info.is_idle_for(self._idle_timeout):
                self.shutdown_engine(analysis_id)
                cleaned.append(analysis_id)
        return cleaned

    def list_engines(self) -> list[str]:
        """List all active engine analysis_ids."""
        return list(self._engines.keys())


def get_manager() -> ProcessManager:
    """Get the singleton ProcessManager instance."""
    return ProcessManager()
