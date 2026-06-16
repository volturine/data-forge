from runtime.models.compute import schemas as compute_schemas
from runtime.models.enums import DataForgeStrEnum


class BuildRunStatus(DataForgeStrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"

    @property
    def is_terminal(self) -> bool:
        return self in {BuildRunStatus.COMPLETED, BuildRunStatus.FAILED, BuildRunStatus.CANCELLED, BuildRunStatus.ORPHANED}

    def to_active_build_status(self) -> tuple[compute_schemas.ActiveBuildStatus, str | None]:
        if self == BuildRunStatus.QUEUED:
            return compute_schemas.ActiveBuildStatus.QUEUED, None
        if self == BuildRunStatus.RUNNING:
            return compute_schemas.ActiveBuildStatus.RUNNING, None
        if self == BuildRunStatus.COMPLETED:
            return compute_schemas.ActiveBuildStatus.COMPLETED, None
        if self == BuildRunStatus.CANCELLED:
            return compute_schemas.ActiveBuildStatus.CANCELLED, None
        if self == BuildRunStatus.FAILED:
            return compute_schemas.ActiveBuildStatus.FAILED, None
        return compute_schemas.ActiveBuildStatus.FAILED, "Build orphaned during startup recovery"
