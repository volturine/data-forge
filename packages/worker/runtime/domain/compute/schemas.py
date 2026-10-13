from datetime import datetime
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from dataforge_protocol import enums_pb2
from runtime.domain.compute_worker_runs.schemas import ComputeWorkerRunKind
from runtime.domain.domain_enums import DomainEnumValue, domain_token


class ComputeWorkerStatus(DomainEnumValue):
    HEALTHY: ClassVar[Self]
    TERMINATED: ClassVar[Self]


ComputeWorkerStatus.HEALTHY = ComputeWorkerStatus(
    enums_pb2.COMPUTE_WORKER_STATUS_HEALTHY, domain_token("ComputeWorkerStatus", enums_pb2.COMPUTE_WORKER_STATUS_HEALTHY)
)
ComputeWorkerStatus.TERMINATED = ComputeWorkerStatus(
    enums_pb2.COMPUTE_WORKER_STATUS_TERMINATED, domain_token("ComputeWorkerStatus", enums_pb2.COMPUTE_WORKER_STATUS_TERMINATED)
)


class ComputeWorkerScope(DomainEnumValue):
    DATASOURCE_PREVIEW: ClassVar[Self]
    ANALYSIS_INTERACTIVE: ClassVar[Self]
    BUILD: ClassVar[Self]


ComputeWorkerScope.DATASOURCE_PREVIEW = ComputeWorkerScope(
    enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW, domain_token("ComputeWorkerScope", enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW)
)
ComputeWorkerScope.ANALYSIS_INTERACTIVE = ComputeWorkerScope(
    enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE, domain_token("ComputeWorkerScope", enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE)
)
ComputeWorkerScope.BUILD = ComputeWorkerScope(enums_pb2.COMPUTE_WORKER_SCOPE_BUILD, domain_token("ComputeWorkerScope", enums_pb2.COMPUTE_WORKER_SCOPE_BUILD))


class ComputeWorkerReusePolicy(DomainEnumValue):
    SHARED: ClassVar[Self]
    EXCLUSIVE: ClassVar[Self]


ComputeWorkerReusePolicy.SHARED = ComputeWorkerReusePolicy(
    enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED, domain_token("ComputeWorkerReusePolicy", enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED)
)
ComputeWorkerReusePolicy.EXCLUSIVE = ComputeWorkerReusePolicy(
    enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE, domain_token("ComputeWorkerReusePolicy", enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE)
)


class ComputeWorkerResourceConfig(BaseModel):
    """Optional resource overrides for compute engine.

    All fields are optional - None means use default from settings/env vars.
    Value of 0 means auto-detect/unlimited (same as settings).
    """

    model_config = ConfigDict(from_attributes=True)

    max_threads: int | None = None  # CPU threads per engine (0 = auto-detect)
    max_memory_mb: int | None = None  # Memory limit in MB (0 = unlimited)
    streaming_chunk_size: int | None = None  # Streaming chunk size (0 = auto)

    @field_validator("max_threads")
    @classmethod
    def validate_max_threads(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("max_threads must be non-negative (0 = auto)")
        if v is not None and v > 64:
            raise ValueError("max_threads must be at most 64")
        return v

    @field_validator("max_memory_mb")
    @classmethod
    def validate_max_memory(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("max_memory_mb must be non-negative (0 = unlimited)")
        if v is not None and v > 0 and v < 256:
            raise ValueError("max_memory_mb must be at least 256 MB when set")
        return v

    @field_validator("streaming_chunk_size")
    @classmethod
    def validate_streaming_chunk_size(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("streaming_chunk_size must be non-negative (0 = auto)")
        return v


class ComputeWorkerDefaults(BaseModel):
    """Default engine resource settings from environment."""

    model_config = ConfigDict(from_attributes=True)

    max_threads: int  # 0 = auto-detect
    max_memory_mb: int  # 0 = unlimited
    streaming_chunk_size: int  # 0 = auto


class ComputeWorkerStatusSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    resource_id: str
    status: ComputeWorkerStatus
    container_id: str | None = None
    image_digest: str | None = None
    lifecycle_status: str | None = None
    termination_reason: str | None = None
    exit_code: int | None = None
    oom_killed: bool | None = None
    supervisor_id: str | None = None
    owner_id: str | None = None
    last_activity: str | None = None
    current_job_id: str | None = None
    resource_config: ComputeWorkerResourceConfig | None = None  # Overrides provided by user
    effective_resources: ComputeWorkerResourceConfig | None = None  # Actual values being used
    defaults: ComputeWorkerDefaults | None = None  # Default values from env vars
    scope: ComputeWorkerScope | None = None
    reuse_policy: ComputeWorkerReusePolicy | None = None
    datasource_id: str | None = None
    build_id: str | None = None
    current_build_id: str | None = None
    current_compute_worker_run_id: str | None = None


class StepPreviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_id: str
    columns: list[str]
    column_types: dict[str, str] | None = None
    data: list[dict]
    total_rows: int
    page: int
    page_size: int
    metadata: dict | None = None


class IcebergSnapshotInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_id: str
    timestamp_ms: int
    parent_snapshot_id: str | None = None
    operation: str | None = None
    is_current: bool | None = None


class IcebergSnapshotsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datasource_id: str
    table_path: str
    snapshots: list[IcebergSnapshotInfo]


class IcebergSnapshotDeleteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datasource_id: str
    snapshot_id: str


class StepSchemaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_id: str
    columns: list[str]
    column_types: dict[str, str]


class StepRowCountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_id: str
    row_count: int


class BuildStatus(DomainEnumValue):
    SUCCESS: ClassVar[Self]
    WARNING: ClassVar[Self]

    @classmethod
    def coerce(cls, value: object) -> BuildStatus:
        return cls.read(value, default=cls.SUCCESS) or cls.SUCCESS


BuildStatus.SUCCESS = BuildStatus(enums_pb2.BUILD_STATUS_SUCCESS, domain_token("BuildStatus", enums_pb2.BUILD_STATUS_SUCCESS))
BuildStatus.WARNING = BuildStatus(enums_pb2.BUILD_STATUS_WARNING, domain_token("BuildStatus", enums_pb2.BUILD_STATUS_WARNING))


class BuildTabStatus(DomainEnumValue):
    SUCCESS: ClassVar[Self]
    FAILED: ClassVar[Self]


BuildTabStatus.SUCCESS = BuildTabStatus(enums_pb2.BUILD_TAB_STATUS_SUCCESS, domain_token("BuildTabStatus", enums_pb2.BUILD_TAB_STATUS_SUCCESS))
BuildTabStatus.FAILED = BuildTabStatus(enums_pb2.BUILD_TAB_STATUS_FAILED, domain_token("BuildTabStatus", enums_pb2.BUILD_TAB_STATUS_FAILED))


class ComputeRunStatus(DomainEnumValue):
    SUCCESS: ClassVar[Self]
    FAILED: ClassVar[Self]


ComputeRunStatus.SUCCESS = ComputeRunStatus(enums_pb2.COMPUTE_RUN_STATUS_SUCCESS, domain_token("ComputeRunStatus", enums_pb2.COMPUTE_RUN_STATUS_SUCCESS))
ComputeRunStatus.FAILED = ComputeRunStatus(enums_pb2.COMPUTE_RUN_STATUS_FAILED, domain_token("ComputeRunStatus", enums_pb2.COMPUTE_RUN_STATUS_FAILED))


class BuildTabResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tab_id: str
    tab_name: str
    status: BuildTabStatus
    output_id: str | None = None
    output_name: str | None = None
    error: str | None = None


class BuildLifecycleStatus(DomainEnumValue):
    QUEUED: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]


BuildLifecycleStatus.QUEUED = BuildLifecycleStatus(
    enums_pb2.BUILD_LIFECYCLE_STATUS_QUEUED,
    domain_token("BuildLifecycleStatus", enums_pb2.BUILD_LIFECYCLE_STATUS_QUEUED),
)
BuildLifecycleStatus.RUNNING = BuildLifecycleStatus(
    enums_pb2.BUILD_LIFECYCLE_STATUS_RUNNING,
    domain_token("BuildLifecycleStatus", enums_pb2.BUILD_LIFECYCLE_STATUS_RUNNING),
)
BuildLifecycleStatus.COMPLETED = BuildLifecycleStatus(
    enums_pb2.BUILD_LIFECYCLE_STATUS_COMPLETED,
    domain_token("BuildLifecycleStatus", enums_pb2.BUILD_LIFECYCLE_STATUS_COMPLETED),
)
BuildLifecycleStatus.FAILED = BuildLifecycleStatus(
    enums_pb2.BUILD_LIFECYCLE_STATUS_FAILED,
    domain_token("BuildLifecycleStatus", enums_pb2.BUILD_LIFECYCLE_STATUS_FAILED),
)
BuildLifecycleStatus.CANCELLED = BuildLifecycleStatus(
    enums_pb2.BUILD_LIFECYCLE_STATUS_CANCELLED,
    domain_token("BuildLifecycleStatus", enums_pb2.BUILD_LIFECYCLE_STATUS_CANCELLED),
)


class BuildStepState(DomainEnumValue):
    PENDING: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    FAILED: ClassVar[Self]
    SKIPPED: ClassVar[Self]


BuildStepState.PENDING = BuildStepState(enums_pb2.BUILD_STEP_STATE_PENDING, domain_token("BuildStepState", enums_pb2.BUILD_STEP_STATE_PENDING))
BuildStepState.RUNNING = BuildStepState(enums_pb2.BUILD_STEP_STATE_RUNNING, domain_token("BuildStepState", enums_pb2.BUILD_STEP_STATE_RUNNING))
BuildStepState.COMPLETED = BuildStepState(enums_pb2.BUILD_STEP_STATE_COMPLETED, domain_token("BuildStepState", enums_pb2.BUILD_STEP_STATE_COMPLETED))
BuildStepState.FAILED = BuildStepState(enums_pb2.BUILD_STEP_STATE_FAILED, domain_token("BuildStepState", enums_pb2.BUILD_STEP_STATE_FAILED))
BuildStepState.SKIPPED = BuildStepState(enums_pb2.BUILD_STEP_STATE_SKIPPED, domain_token("BuildStepState", enums_pb2.BUILD_STEP_STATE_SKIPPED))


class BuildLogLevel(DomainEnumValue):
    INFO: ClassVar[Self]
    WARNING: ClassVar[Self]
    ERROR: ClassVar[Self]


BuildLogLevel.INFO = BuildLogLevel(enums_pb2.BUILD_LOG_LEVEL_INFO, domain_token("BuildLogLevel", enums_pb2.BUILD_LOG_LEVEL_INFO))
BuildLogLevel.WARNING = BuildLogLevel(enums_pb2.BUILD_LOG_LEVEL_WARNING, domain_token("BuildLogLevel", enums_pb2.BUILD_LOG_LEVEL_WARNING))
BuildLogLevel.ERROR = BuildLogLevel(enums_pb2.BUILD_LOG_LEVEL_ERROR, domain_token("BuildLogLevel", enums_pb2.BUILD_LOG_LEVEL_ERROR))


class BuildStarter(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str | None = None
    display_name: str | None = None
    email: str | None = None
    triggered_by: str | None = None

    def is_schedule_trigger(self) -> bool:
        return isinstance(self.triggered_by, str) and (self.triggered_by == "schedule" or self.triggered_by.startswith("schedule:"))


class BuildResourceConfigSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    max_threads: int | None = None
    max_memory_mb: int | None = None
    streaming_chunk_size: int | None = None


class BuildEventType(DomainEnumValue):
    PLAN: ClassVar[Self]
    STEP_START: ClassVar[Self]
    STEP_COMPLETE: ClassVar[Self]
    STEP_FAILED: ClassVar[Self]
    PROGRESS: ClassVar[Self]
    RESOURCES: ClassVar[Self]
    LOG: ClassVar[Self]
    COMPLETE: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]


BuildEventType.PLAN = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_PLAN, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_PLAN))
BuildEventType.STEP_START = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_STEP_START, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_STEP_START))
BuildEventType.STEP_COMPLETE = BuildEventType(
    enums_pb2.BUILD_EVENT_TYPE_STEP_COMPLETE, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_STEP_COMPLETE)
)
BuildEventType.STEP_FAILED = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_STEP_FAILED, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_STEP_FAILED))
BuildEventType.PROGRESS = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_PROGRESS, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_PROGRESS))
BuildEventType.RESOURCES = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_RESOURCES, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_RESOURCES))
BuildEventType.LOG = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_LOG, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_LOG))
BuildEventType.COMPLETE = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_COMPLETE, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_COMPLETE))
BuildEventType.FAILED = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_FAILED, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_FAILED))
BuildEventType.CANCELLED = BuildEventType(enums_pb2.BUILD_EVENT_TYPE_CANCELLED, domain_token("BuildEventType", enums_pb2.BUILD_EVENT_TYPE_CANCELLED))


class BuildStreamEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    build_id: str
    analysis_id: str
    emitted_at: datetime
    sequence: int | None = None
    current_kind: ComputeWorkerRunKind | None = None
    current_datasource_id: str | None = None
    tab_id: str | None = None
    tab_name: str | None = None
    current_output_id: str | None = None
    current_output_name: str | None = None
    compute_worker_run_id: str | None = None


class BuildPlanEvent(BuildStreamEvent):
    type: Literal["plan"] = "plan"
    optimized_plan: str
    unoptimized_plan: str


class BuildStepStartEvent(BuildStreamEvent):
    type: Literal["step_start"] = "step_start"
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    step_type: str
    total_steps: int


class BuildStepCompleteEvent(BuildStreamEvent):
    type: Literal["step_complete"] = "step_complete"
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    step_type: str
    duration_ms: int
    row_count: int | None = None
    total_steps: int


class BuildStepFailedEvent(BuildStreamEvent):
    type: Literal["step_failed"] = "step_failed"
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    step_type: str
    error: str
    total_steps: int


class BuildProgressEvent(BuildStreamEvent):
    type: Literal["progress"] = "progress"
    progress: float
    elapsed_ms: int
    estimated_remaining_ms: int | None = None
    current_step: str | None = None
    current_step_index: int | None = None
    total_steps: int


class BuildResourceEvent(BuildStreamEvent):
    type: Literal["resources"] = "resources"
    cpu_percent: float
    memory_mb: float
    memory_limit_mb: float | None = None
    active_threads: int
    max_threads: int | None = None


class BuildLogEvent(BuildStreamEvent):
    type: Literal["log"] = "log"
    level: BuildLogLevel
    message: str
    step_name: str | None = None
    step_id: str | None = None


class BuildCompleteEvent(BuildStreamEvent):
    type: Literal["complete"] = "complete"
    progress: float = 1.0
    elapsed_ms: int
    total_steps: int
    tabs_built: int
    results: list[BuildTabResult]
    duration_ms: int


class BuildFailedEvent(BuildStreamEvent):
    type: Literal["failed"] = "failed"
    progress: float
    elapsed_ms: int
    total_steps: int
    tabs_built: int
    results: list[BuildTabResult]
    duration_ms: int
    error: str | None = None


class BuildCancelledEvent(BuildStreamEvent):
    type: Literal["cancelled"] = "cancelled"
    progress: float
    elapsed_ms: int
    total_steps: int
    tabs_built: int
    results: list[BuildTabResult]
    duration_ms: int
    cancelled_at: datetime
    cancelled_by: str | None = None


BuildEvent = Annotated[
    BuildPlanEvent
    | BuildStepStartEvent
    | BuildStepCompleteEvent
    | BuildStepFailedEvent
    | BuildProgressEvent
    | BuildResourceEvent
    | BuildLogEvent
    | BuildCompleteEvent
    | BuildFailedEvent
    | BuildCancelledEvent,
    Field(discriminator="type"),
]

BuildEventAdapter: TypeAdapter[BuildEvent] = TypeAdapter(BuildEvent)
