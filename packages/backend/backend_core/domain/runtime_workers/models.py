from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.api_enums import ApiEnumValue, api_token
from dataforge_protocol import enums_pb2


class RuntimeWorkerKind(ApiEnumValue):
    API: ClassVar[Self]
    BUILD_MANAGER: ClassVar[Self]
    BUILD_WORKER: ClassVar[Self]
    SCHEDULER: ClassVar[Self]


RuntimeWorkerKind.API = RuntimeWorkerKind(enums_pb2.RUNTIME_WORKER_KIND_API, api_token('RuntimeWorkerKind', enums_pb2.RUNTIME_WORKER_KIND_API))
RuntimeWorkerKind.BUILD_MANAGER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_BUILD_MANAGER, api_token('RuntimeWorkerKind', enums_pb2.RUNTIME_WORKER_KIND_BUILD_MANAGER)
)
RuntimeWorkerKind.BUILD_WORKER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_BUILD_WORKER, api_token('RuntimeWorkerKind', enums_pb2.RUNTIME_WORKER_KIND_BUILD_WORKER)
)
RuntimeWorkerKind.SCHEDULER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_SCHEDULER, api_token('RuntimeWorkerKind', enums_pb2.RUNTIME_WORKER_KIND_SCHEDULER)
)
