from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.domain_enums import DomainEnumValue


class ComputeWorkerRunKind(DomainEnumValue):
    BUILD: ClassVar[Self]
    PREVIEW: ClassVar[Self]
    ROW_COUNT: ClassVar[Self]
    DOWNLOAD: ClassVar[Self]
    INGEST: ClassVar[Self]


ComputeWorkerRunKind.BUILD = ComputeWorkerRunKind(enums_pb2.COMPUTE_WORKER_RUN_KIND_BUILD)
ComputeWorkerRunKind.PREVIEW = ComputeWorkerRunKind(enums_pb2.COMPUTE_WORKER_RUN_KIND_PREVIEW)
ComputeWorkerRunKind.ROW_COUNT = ComputeWorkerRunKind(enums_pb2.COMPUTE_WORKER_RUN_KIND_ROW_COUNT)
ComputeWorkerRunKind.DOWNLOAD = ComputeWorkerRunKind(enums_pb2.COMPUTE_WORKER_RUN_KIND_DOWNLOAD)
ComputeWorkerRunKind.INGEST = ComputeWorkerRunKind(enums_pb2.COMPUTE_WORKER_RUN_KIND_INGEST)


class ComputeWorkerRunStatus(DomainEnumValue):
    RUNNING: ClassVar[Self]
    SUCCESS: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]


ComputeWorkerRunStatus.RUNNING = ComputeWorkerRunStatus(enums_pb2.COMPUTE_WORKER_RUN_STATUS_RUNNING)
ComputeWorkerRunStatus.SUCCESS = ComputeWorkerRunStatus(enums_pb2.COMPUTE_WORKER_RUN_STATUS_SUCCESS)
ComputeWorkerRunStatus.FAILED = ComputeWorkerRunStatus(enums_pb2.COMPUTE_WORKER_RUN_STATUS_FAILED)
ComputeWorkerRunStatus.CANCELLED = ComputeWorkerRunStatus(enums_pb2.COMPUTE_WORKER_RUN_STATUS_CANCELLED)


class ComputeWorkerRunExecutionCategory(DomainEnumValue):
    READ: ClassVar[Self]
    STEP: ClassVar[Self]
    PLAN: ClassVar[Self]
    COMPUTE: ClassVar[Self]
    WRITE: ClassVar[Self]

    @property
    def default_step_type(self) -> str:
        match self:
            case ComputeWorkerRunExecutionCategory.READ | ComputeWorkerRunExecutionCategory.WRITE:
                return self.value
            case _:
                return "unknown"


ComputeWorkerRunExecutionCategory.READ = ComputeWorkerRunExecutionCategory(enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_READ)
ComputeWorkerRunExecutionCategory.STEP = ComputeWorkerRunExecutionCategory(enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_STEP)
ComputeWorkerRunExecutionCategory.PLAN = ComputeWorkerRunExecutionCategory(enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_PLAN)
ComputeWorkerRunExecutionCategory.COMPUTE = ComputeWorkerRunExecutionCategory(enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_COMPUTE)
ComputeWorkerRunExecutionCategory.WRITE = ComputeWorkerRunExecutionCategory(enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_WRITE)


class SchemaDiffStatus(DomainEnumValue):
    ADDED: ClassVar[Self]
    REMOVED: ClassVar[Self]
    TYPE_CHANGED: ClassVar[Self]


SchemaDiffStatus.ADDED = SchemaDiffStatus(enums_pb2.SCHEMA_DIFF_STATUS_ADDED)
SchemaDiffStatus.REMOVED = SchemaDiffStatus(enums_pb2.SCHEMA_DIFF_STATUS_REMOVED)
SchemaDiffStatus.TYPE_CHANGED = SchemaDiffStatus(enums_pb2.SCHEMA_DIFF_STATUS_TYPE_CHANGED)
