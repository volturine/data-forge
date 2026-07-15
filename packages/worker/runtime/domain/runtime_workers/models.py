from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.domain_enums import DomainEnumValue, domain_token


class RuntimeWorkerKind(DomainEnumValue):
    API: ClassVar[Self]
    BUILD_MANAGER: ClassVar[Self]
    BUILD_WORKER: ClassVar[Self]
    SCHEDULER: ClassVar[Self]


RuntimeWorkerKind.API = RuntimeWorkerKind(enums_pb2.RUNTIME_WORKER_KIND_API, domain_token("RuntimeWorkerKind", enums_pb2.RUNTIME_WORKER_KIND_API))
RuntimeWorkerKind.BUILD_MANAGER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_BUILD_MANAGER, domain_token("RuntimeWorkerKind", enums_pb2.RUNTIME_WORKER_KIND_BUILD_MANAGER)
)
RuntimeWorkerKind.BUILD_WORKER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_BUILD_WORKER, domain_token("RuntimeWorkerKind", enums_pb2.RUNTIME_WORKER_KIND_BUILD_WORKER)
)
RuntimeWorkerKind.SCHEDULER = RuntimeWorkerKind(
    enums_pb2.RUNTIME_WORKER_KIND_SCHEDULER, domain_token("RuntimeWorkerKind", enums_pb2.RUNTIME_WORKER_KIND_SCHEDULER)
)
