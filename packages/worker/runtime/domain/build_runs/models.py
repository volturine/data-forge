from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.domain_enums import DomainEnumValue, domain_token


class BuildRunStatus(DomainEnumValue):
    QUEUED: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]
    ORPHANED: ClassVar[Self]


BuildRunStatus.QUEUED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_QUEUED, domain_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_QUEUED))
BuildRunStatus.RUNNING = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_RUNNING, domain_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_RUNNING))
BuildRunStatus.COMPLETED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_COMPLETED, domain_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_COMPLETED))
BuildRunStatus.FAILED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_FAILED, domain_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_FAILED))
BuildRunStatus.CANCELLED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_CANCELLED, domain_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_CANCELLED))
BuildRunStatus.ORPHANED = BuildRunStatus(enums_pb2.BUILD_RUN_STATUS_ORPHANED, domain_token("BuildRunStatus", enums_pb2.BUILD_RUN_STATUS_ORPHANED))
