from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.compute import schemas as compute_schemas
from runtime.domain.protocol_enums import ProtocolEnumValue, protocol_token


class BuildRunStatus(ProtocolEnumValue):
    QUEUED: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]
    ORPHANED: ClassVar[Self]

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


BuildRunStatus.QUEUED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_QUEUED, protocol_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_QUEUED))
BuildRunStatus.RUNNING = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_RUNNING, protocol_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_RUNNING))
BuildRunStatus.COMPLETED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_COMPLETED, protocol_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_COMPLETED))
BuildRunStatus.FAILED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_FAILED, protocol_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_FAILED))
BuildRunStatus.CANCELLED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_CANCELLED, protocol_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_CANCELLED))
BuildRunStatus.ORPHANED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_ORPHANED, protocol_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_ORPHANED))
