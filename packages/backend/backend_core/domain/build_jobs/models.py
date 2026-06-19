from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.protocol_enums import ProtocolEnumValue, protocol_token
from dataforge_protocol import enums_pb2


class BuildJobStatus(ProtocolEnumValue):
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


BuildJobStatus.QUEUED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_QUEUED, protocol_token('BuildJobStatus', enums_pb2.BUILD_JOB_STATUS_QUEUED))
BuildJobStatus.LEASED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_LEASED, protocol_token('BuildJobStatus', enums_pb2.BUILD_JOB_STATUS_LEASED))
BuildJobStatus.RUNNING = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_RUNNING, protocol_token('BuildJobStatus', enums_pb2.BUILD_JOB_STATUS_RUNNING))
BuildJobStatus.COMPLETED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_COMPLETED, protocol_token('BuildJobStatus', enums_pb2.BUILD_JOB_STATUS_COMPLETED))
BuildJobStatus.FAILED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_FAILED, protocol_token('BuildJobStatus', enums_pb2.BUILD_JOB_STATUS_FAILED))
BuildJobStatus.CANCELLED = BuildJobStatus(enums_pb2.BUILD_JOB_STATUS_CANCELLED, protocol_token('BuildJobStatus', enums_pb2.BUILD_JOB_STATUS_CANCELLED))
