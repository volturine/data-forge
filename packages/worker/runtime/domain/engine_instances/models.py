from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.compute.schemas import EngineStatus
from runtime.domain.protocol_enums import ProtocolEnumValue, protocol_token


class EngineInstanceStatus(ProtocolEnumValue):
    STARTING: ClassVar[Self]
    IDLE: ClassVar[Self]
    RUNNING: ClassVar[Self]
    STOPPING: ClassVar[Self]
    STOPPED: ClassVar[Self]
    FAILED: ClassVar[Self]

    @property
    def is_active(self) -> bool:
        return self in {EngineInstanceStatus.IDLE, EngineInstanceStatus.RUNNING, EngineInstanceStatus.STARTING, EngineInstanceStatus.STOPPING}

    @property
    def overview_status(self) -> str:
        if self in {EngineInstanceStatus.IDLE, EngineInstanceStatus.RUNNING, EngineInstanceStatus.STARTING}:
            return "healthy"
        return "terminated"

    @classmethod
    def from_engine_status(cls, value: str, current_job_id: str | None) -> EngineInstanceStatus:
        engine_status = EngineStatus.require(value)
        if engine_status == EngineStatus.HEALTHY and current_job_id:
            return cls.RUNNING
        if engine_status == EngineStatus.HEALTHY:
            return cls.IDLE
        return cls.STOPPED


EngineInstanceStatus.STARTING = EngineInstanceStatus(
    enums_pb2.ENGINE_INSTANCE_STATUS_STARTING, protocol_token("EngineInstanceStatus", enums_pb2.ENGINE_INSTANCE_STATUS_STARTING)
)
EngineInstanceStatus.IDLE = EngineInstanceStatus(
    enums_pb2.ENGINE_INSTANCE_STATUS_IDLE, protocol_token("EngineInstanceStatus", enums_pb2.ENGINE_INSTANCE_STATUS_IDLE)
)
EngineInstanceStatus.RUNNING = EngineInstanceStatus(
    enums_pb2.ENGINE_INSTANCE_STATUS_RUNNING, protocol_token("EngineInstanceStatus", enums_pb2.ENGINE_INSTANCE_STATUS_RUNNING)
)
EngineInstanceStatus.STOPPING = EngineInstanceStatus(
    enums_pb2.ENGINE_INSTANCE_STATUS_STOPPING, protocol_token("EngineInstanceStatus", enums_pb2.ENGINE_INSTANCE_STATUS_STOPPING)
)
EngineInstanceStatus.STOPPED = EngineInstanceStatus(
    enums_pb2.ENGINE_INSTANCE_STATUS_STOPPED, protocol_token("EngineInstanceStatus", enums_pb2.ENGINE_INSTANCE_STATUS_STOPPED)
)
EngineInstanceStatus.FAILED = EngineInstanceStatus(
    enums_pb2.ENGINE_INSTANCE_STATUS_FAILED, protocol_token("EngineInstanceStatus", enums_pb2.ENGINE_INSTANCE_STATUS_FAILED)
)
