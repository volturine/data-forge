from worker_models.enums import DataForgeStrEnum


class BuildJobStatus(DataForgeStrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in {BuildJobStatus.LEASED, BuildJobStatus.RUNNING}

    @property
    def is_reclaimable(self) -> bool:
        return self.is_active
