from backend_contracts.compute.schemas import EngineStatus
from backend_contracts.enums import DataForgeStrEnum


class EngineInstanceStatus(DataForgeStrEnum):
    STARTING = 'starting'
    IDLE = 'idle'
    RUNNING = 'running'
    STOPPING = 'stopping'
    STOPPED = 'stopped'
    FAILED = 'failed'

    @property
    def is_active(self) -> bool:
        return self in {EngineInstanceStatus.IDLE, EngineInstanceStatus.RUNNING, EngineInstanceStatus.STARTING, EngineInstanceStatus.STOPPING}

    @property
    def overview_status(self) -> str:
        if self in {EngineInstanceStatus.IDLE, EngineInstanceStatus.RUNNING, EngineInstanceStatus.STARTING}:
            return 'healthy'
        return 'terminated'

    @classmethod
    def from_engine_status(cls, value: str, current_job_id: str | None) -> EngineInstanceStatus:
        engine_status = EngineStatus.require(value)
        if engine_status == EngineStatus.HEALTHY and current_job_id:
            return cls.RUNNING
        if engine_status == EngineStatus.HEALTHY:
            return cls.IDLE
        return cls.STOPPED
