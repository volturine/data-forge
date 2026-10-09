from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.api_enums import ApiEnumValue, api_token
from backend_core.domain.compute.schemas import ComputeWorkerStatus
from dataforge_protocol import enums_pb2


class ComputeWorkerInstanceStatus(ApiEnumValue):
    STARTING: ClassVar[Self]
    IDLE: ClassVar[Self]
    RUNNING: ClassVar[Self]
    STOPPING: ClassVar[Self]
    STOPPED: ClassVar[Self]
    FAILED: ClassVar[Self]

    @property
    def is_active(self) -> bool:
        return self in {
            ComputeWorkerInstanceStatus.IDLE,
            ComputeWorkerInstanceStatus.RUNNING,
            ComputeWorkerInstanceStatus.STARTING,
            ComputeWorkerInstanceStatus.STOPPING,
        }

    @property
    def overview_status(self) -> str:
        if self in {ComputeWorkerInstanceStatus.IDLE, ComputeWorkerInstanceStatus.RUNNING, ComputeWorkerInstanceStatus.STARTING}:
            return 'healthy'
        return 'terminated'

    @classmethod
    def from_compute_worker_status(cls, value: str, current_job_id: str | None) -> ComputeWorkerInstanceStatus:
        compute_worker_status = ComputeWorkerStatus.require(value)
        if compute_worker_status == ComputeWorkerStatus.HEALTHY and current_job_id:
            return cls.RUNNING
        if compute_worker_status == ComputeWorkerStatus.HEALTHY:
            return cls.IDLE
        return cls.STOPPED


ComputeWorkerInstanceStatus.STARTING = ComputeWorkerInstanceStatus(
    enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_STARTING, api_token('ComputeWorkerInstanceStatus', enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_STARTING)
)
ComputeWorkerInstanceStatus.IDLE = ComputeWorkerInstanceStatus(
    enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_IDLE, api_token('ComputeWorkerInstanceStatus', enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_IDLE)
)
ComputeWorkerInstanceStatus.RUNNING = ComputeWorkerInstanceStatus(
    enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_RUNNING, api_token('ComputeWorkerInstanceStatus', enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_RUNNING)
)
ComputeWorkerInstanceStatus.STOPPING = ComputeWorkerInstanceStatus(
    enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_STOPPING, api_token('ComputeWorkerInstanceStatus', enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_STOPPING)
)
ComputeWorkerInstanceStatus.STOPPED = ComputeWorkerInstanceStatus(
    enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_STOPPED, api_token('ComputeWorkerInstanceStatus', enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_STOPPED)
)
ComputeWorkerInstanceStatus.FAILED = ComputeWorkerInstanceStatus(
    enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_FAILED, api_token('ComputeWorkerInstanceStatus', enums_pb2.COMPUTE_WORKER_INSTANCE_STATUS_FAILED)
)
