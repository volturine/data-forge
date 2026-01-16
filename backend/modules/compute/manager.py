from modules.compute.engine import PolarsComputeEngine


class ProcessManager:
    _instance: 'ProcessManager | None' = None
    _engines: dict[str, PolarsComputeEngine]

    def __new__(cls) -> 'ProcessManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._engines = {}
        return cls._instance

    def get_or_create_engine(self, analysis_id: str) -> PolarsComputeEngine:
        """Get existing engine or create a new one for the analysis."""
        if analysis_id not in self._engines:
            engine = PolarsComputeEngine(analysis_id)
            self._engines[analysis_id] = engine

        return self._engines[analysis_id]

    def get_engine(self, analysis_id: str) -> PolarsComputeEngine | None:
        """Get existing engine by analysis_id."""
        return self._engines.get(analysis_id)

    def shutdown_engine(self, analysis_id: str) -> None:
        """Shutdown and remove an engine."""
        if analysis_id in self._engines:
            engine = self._engines[analysis_id]
            engine.shutdown()
            del self._engines[analysis_id]

    def shutdown_all(self) -> None:
        """Shutdown all engines."""
        for analysis_id in list(self._engines.keys()):
            self.shutdown_engine(analysis_id)

    def list_engines(self) -> list[str]:
        """List all active engine analysis_ids."""
        return list(self._engines.keys())


def get_manager() -> ProcessManager:
    """Get the singleton ProcessManager instance."""
    return ProcessManager()
