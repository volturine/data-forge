from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.api_enums import ApiEnumValue, api_token
from backend_core.domain.compute import schemas as compute_schemas
from dataforge_protocol import enums_pb2


class BuildRunStatus(ApiEnumValue):
    QUEUED: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]
    ORPHANED: ClassVar[Self]

    @property
    def is_terminal(self) -> bool:
        return self in {BuildRunStatus.COMPLETED, BuildRunStatus.FAILED, BuildRunStatus.CANCELLED, BuildRunStatus.ORPHANED}

    def to_build_lifecycle_status(self) -> tuple[compute_schemas.BuildLifecycleStatus, str | None]:
        if self == BuildRunStatus.QUEUED:
            return compute_schemas.BuildLifecycleStatus.QUEUED, None
        if self == BuildRunStatus.RUNNING:
            return compute_schemas.BuildLifecycleStatus.RUNNING, None
        if self == BuildRunStatus.COMPLETED:
            return compute_schemas.BuildLifecycleStatus.COMPLETED, None
        if self == BuildRunStatus.CANCELLED:
            return compute_schemas.BuildLifecycleStatus.CANCELLED, None
        if self == BuildRunStatus.FAILED:
            return compute_schemas.BuildLifecycleStatus.FAILED, None
        return compute_schemas.BuildLifecycleStatus.FAILED, 'Build orphaned during startup recovery'


BuildRunStatus.QUEUED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_QUEUED, api_token('BuildRunStatus', enums_pb2.BUILD_RUN_STATUS_QUEUED))
BuildRunStatus.RUNNING = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_RUNNING, api_token('BuildRunStatus', enums_pb2.BUILD_RUN_STATUS_RUNNING))
BuildRunStatus.COMPLETED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_COMPLETED, api_token('BuildRunStatus', enums_pb2.BUILD_RUN_STATUS_COMPLETED))
BuildRunStatus.FAILED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_FAILED, api_token('BuildRunStatus', enums_pb2.BUILD_RUN_STATUS_FAILED))
BuildRunStatus.CANCELLED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_CANCELLED, api_token('BuildRunStatus', enums_pb2.BUILD_RUN_STATUS_CANCELLED))
BuildRunStatus.ORPHANED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_ORPHANED, api_token('BuildRunStatus', enums_pb2.BUILD_RUN_STATUS_ORPHANED))
