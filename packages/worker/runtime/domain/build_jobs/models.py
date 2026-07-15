from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.domain_enums import DomainEnumValue, domain_token


class BuildJobStatus(DomainEnumValue):
    QUEUED: ClassVar[Self]
    LEASED: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]

    @property
    def is_active(self) -> bool:
        return self in {BuildJobStatus.LEASED, BuildJobStatus.RUNNING}

    @property
    def is_reclaimable(self) -> bool:
        return self.is_active


BuildJobStatus.QUEUED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_QUEUED, domain_token("BuildJobStatus", enums_pb2.BUILD_JOB_STATUS_QUEUED))
BuildJobStatus.LEASED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_LEASED, domain_token("BuildJobStatus", enums_pb2.BUILD_JOB_STATUS_LEASED))
BuildJobStatus.RUNNING = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_RUNNING, domain_token("BuildJobStatus", enums_pb2.BUILD_JOB_STATUS_RUNNING))
BuildJobStatus.COMPLETED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_COMPLETED, domain_token("BuildJobStatus", enums_pb2.BUILD_JOB_STATUS_COMPLETED))
BuildJobStatus.FAILED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_FAILED, domain_token("BuildJobStatus", enums_pb2.BUILD_JOB_STATUS_FAILED))
BuildJobStatus.CANCELLED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_CANCELLED, domain_token("BuildJobStatus", enums_pb2.BUILD_JOB_STATUS_CANCELLED))
