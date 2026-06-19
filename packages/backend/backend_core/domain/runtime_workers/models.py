from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.protocol_enums import ProtocolEnumValue, protocol_token
from dataforge_protocol import enums_pb2


class RuntimeWorkerKind(ProtocolEnumValue):
    API: ClassVar[Self]
    BUILD_MANAGER: ClassVar[Self]
    BUILD_WORKER: ClassVar[Self]
    SCHEDULER: ClassVar[Self]


RuntimeWorkerKind.API = RuntimeWorkerKind(enums_pb2.RUNTIME_WORKER_KIND_API, protocol_token('RuntimeWorkerKind', enums_pb2.RUNTIME_WORKER_KIND_API))
RuntimeWorkerKind.BUILD_MANAGER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_BUILD_MANAGER, protocol_token('RuntimeWorkerKind', enums_pb2.RUNTIME_WORKER_KIND_BUILD_MANAGER)
)
RuntimeWorkerKind.BUILD_WORKER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_BUILD_WORKER, protocol_token('RuntimeWorkerKind', enums_pb2.RUNTIME_WORKER_KIND_BUILD_WORKER)
)
RuntimeWorkerKind.SCHEDULER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_SCHEDULER, protocol_token('RuntimeWorkerKind', enums_pb2.RUNTIME_WORKER_KIND_SCHEDULER)
)
