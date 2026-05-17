from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator

from contracts.analysis.step_types import is_step_type
from contracts.engine_runs.schemas import EngineRunKind
from contracts.enums import DataForgeStrEnum


class EngineStatus(DataForgeStrEnum):
    HEALTHY = 'healthy'
    TERMINATED = 'terminated'


class EngineResourceConfig(BaseModel):
    """Optional resource overrides for compute engine.

    All fields are optional - None means use default from settings/env vars.
    Value of 0 means auto-detect/unlimited (same as settings).
    """

    model_config = ConfigDict(from_attributes=True)

    max_threads: int | None = None  # CPU threads per engine (0 = auto-detect)
    max_memory_mb: int | None = None  # Memory limit in MB (0 = unlimited)
    streaming_chunk_size: int | None = None  # Streaming chunk size (0 = auto)

    @field_validator('max_threads')
    @classmethod
    def validate_max_threads(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError('max_threads must be non-negative (0 = auto)')
        if v is not None and v > 64:
            raise ValueError('max_threads must be at most 64')
        return v

    @field_validator('max_memory_mb')
    @classmethod
    def validate_max_memory(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError('max_memory_mb must be non-negative (0 = unlimited)')
        if v is not None and v > 0 and v < 256:
            raise ValueError('max_memory_mb must be at least 256 MB when set')
        return v

    @field_validator('streaming_chunk_size')
    @classmethod
    def validate_streaming_chunk_size(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError('streaming_chunk_size must be non-negative (0 = auto)')
        return v


class EngineDefaults(BaseModel):
    """Default engine resource settings from environment."""

    model_config = ConfigDict(from_attributes=True)

    max_threads: int  # 0 = auto-detect
    max_memory_mb: int  # 0 = unlimited
    streaming_chunk_size: int  # 0 = auto


class AnalysisPipelineDatasourceConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='allow')

    branch: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class AnalysisPipelineDatasource(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    analysis_tab_id: str | None
    source_type: str | None = None
    config: AnalysisPipelineDatasourceConfig


class AnalysisPipelineTab(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None = None
    datasource: AnalysisPipelineDatasource
    output: dict
    steps: list[dict]

    @field_validator('steps')
    @classmethod
    def validate_steps(cls, value: list[dict]) -> list[dict]:
        if not isinstance(value, list):
            raise ValueError('Analysis pipeline tab steps must be a list')
        allowed_keys = {'id', 'type', 'config', 'depends_on', 'is_applied'}
        for index, step in enumerate(value):
            if not isinstance(step, dict):
                raise ValueError(f'Analysis pipeline step {index} must be a dict')
            unknown_keys = sorted(set(step) - allowed_keys)
            if unknown_keys:
                raise ValueError(f'Analysis pipeline step {index} has unknown field(s): {", ".join(unknown_keys)}')
            step_id = step.get('id')
            if not isinstance(step_id, str) or not step_id.strip():
                raise ValueError(f'Analysis pipeline step {index} id is required')
            step_type = step.get('type')
            if not isinstance(step_type, str) or not step_type.strip():
                raise ValueError(f'Analysis pipeline step {index} type is required')
            if not is_step_type(step_type):
                raise ValueError(f"Analysis pipeline step {index} has unknown type '{step_type}'")
            config = step.get('config')
            if config is not None and not isinstance(config, dict):
                raise ValueError(f'Analysis pipeline step {index} config must be a dict')
            depends_on = step.get('depends_on')
            if depends_on is not None and not (isinstance(depends_on, list) and all(isinstance(dep, str) and dep.strip() for dep in depends_on)):
                raise ValueError(f'Analysis pipeline step {index} depends_on must be a list of step ids')
            is_applied = step.get('is_applied')
            if is_applied is not None and not isinstance(is_applied, bool):
                raise ValueError(f'Analysis pipeline step {index} is_applied must be a boolean')
        return value

    @field_validator('output')
    @classmethod
    def validate_output(cls, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ValueError('Analysis pipeline tab output must be a dict')
        output_id = value.get('result_id')
        if not isinstance(output_id, str) or not output_id.strip():
            raise ValueError('Analysis pipeline tab output.result_id is required')
        filename = value.get('filename')
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError('Analysis pipeline tab output.filename is required')
        export_format = value.get('format')
        if not isinstance(export_format, str) or not export_format.strip():
            raise ValueError('Analysis pipeline tab output.format is required')
        return value


class AnalysisPipelinePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    tabs: list[AnalysisPipelineTab]

    @field_validator('tabs')
    @classmethod
    def validate_tabs(cls, value: list[AnalysisPipelineTab]) -> list[AnalysisPipelineTab]:
        if not isinstance(value, list) or not value:
            raise ValueError('analysis_pipeline.tabs must include at least one tab')
        return value


class EngineStatusSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    status: EngineStatus
    process_id: int | None = None
    last_activity: str | None = None
    current_job_id: str | None = None
    resource_config: EngineResourceConfig | None = None  # Overrides provided by user
    effective_resources: EngineResourceConfig | None = None  # Actual values being used
    defaults: EngineDefaults | None = None  # Default values from env vars


class EngineListSnapshotMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal['snapshot'] = 'snapshot'
    engines: list[EngineStatusSchema]
    total: int


class EngineWebsocketErrorMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal['error'] = 'error'
    error: str
    status_code: int = 500


class SpawnEngineRequest(BaseModel):
    """Request body for spawning an engine with optional resource config."""

    model_config = ConfigDict(from_attributes=True)

    resource_config: EngineResourceConfig | None = None


class StepPreviewRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    target_step_id: str
    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None
    row_limit: int = Field(default=1000, ge=1, le=5000)
    page: int = Field(default=1, ge=1)
    resource_config: EngineResourceConfig | None = None


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


StepPreviewRequest.model_rebuild()


class ExportFormat(DataForgeStrEnum):
    CSV = 'csv'
    PARQUET = 'parquet'
    JSON = 'json'
    NDJSON = 'ndjson'
    DUCKDB = 'duckdb'
    EXCEL = 'excel'


class ExportDestination(DataForgeStrEnum):
    DOWNLOAD = 'download'
    DATASOURCE = 'datasource'


class IcebergExportOptions(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    table_name: str = 'exported_data'
    namespace: str = 'outputs'
    branch: str = 'master'


class ExportRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    target_step_id: str
    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None
    format: ExportFormat = ExportFormat.CSV
    filename: str = 'export'
    destination: ExportDestination = ExportDestination.DOWNLOAD
    iceberg_options: IcebergExportOptions | None = None
    result_id: str | None = None

    @field_validator('result_id')
    @classmethod
    def validate_result_id(cls, value: str | None, info):
        if not info.data:
            return value
        destination = info.data.get('destination')
        if destination == ExportDestination.DATASOURCE and (not isinstance(value, str) or not value.strip()):
            raise ValueError('Output exports require result_id')
        return value


class ExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    filename: str
    format: str
    destination: str
    message: str | None = None
    datasource_id: str | None = None
    datasource_name: str | None = None


class DownloadRequest(BaseModel):
    """Request to download the result of a pipeline step in a specific format."""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    target_step_id: str
    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None
    format: ExportFormat = ExportFormat.CSV
    filename: str = 'download'


class StepSchemaRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    target_step_id: str
    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None


class StepRowCountRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    target_step_id: str
    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None


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


class BuildStatus(DataForgeStrEnum):
    SUCCESS = 'success'
    WARNING = 'warning'

    @classmethod
    def coerce(cls, value: object) -> 'BuildStatus':
        return cls.read(value, default=cls.SUCCESS) or cls.SUCCESS


class BuildTabStatus(DataForgeStrEnum):
    SUCCESS = 'success'
    FAILED = 'failed'


class ComputeRunStatus(DataForgeStrEnum):
    SUCCESS = 'success'
    FAILED = 'failed'


class BuildTabResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tab_id: str
    tab_name: str
    status: BuildTabStatus
    output_id: str | None = None
    output_name: str | None = None
    error: str | None = None


class BuildRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None

    def pipeline_payload(self) -> dict[str, object]:
        pipeline = self.analysis_pipeline.model_dump(mode='json')
        if not isinstance(pipeline, dict):
            raise ValueError('analysis_pipeline is required')
        return {**pipeline, 'tab_id': self.tab_id}


class ActiveBuildStatus(DataForgeStrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'

    @property
    def is_terminal(self) -> bool:
        return self in {ActiveBuildStatus.COMPLETED, ActiveBuildStatus.FAILED, ActiveBuildStatus.CANCELLED}

    @classmethod
    def coerce(cls, value: object) -> 'ActiveBuildStatus':
        return cls.read(value, default=cls.QUEUED) or cls.QUEUED


class BuildStepState(DataForgeStrEnum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    SKIPPED = 'skipped'


class BuildLogLevel(DataForgeStrEnum):
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'

    @classmethod
    def coerce(cls, value: object) -> 'BuildLogLevel':
        return cls.read(value, default=cls.INFO) or cls.INFO


class BuildStarter(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str | None = None
    display_name: str | None = None
    email: str | None = None
    triggered_by: str | None = None

    @classmethod
    def for_user(cls, user: object | None) -> 'BuildStarter':
        if user is None:
            return cls(triggered_by='user')
        return cls(user_id=getattr(user, 'id', None), display_name=getattr(user, 'display_name', None), email=getattr(user, 'email', None), triggered_by='user')

    @classmethod
    def for_schedule(cls, schedule_id: str) -> 'BuildStarter':
        return cls(triggered_by=f'schedule:{schedule_id}')


class BuildResourceConfigSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    max_threads: int | None = None
    max_memory_mb: int | None = None
    streaming_chunk_size: int | None = None


class BuildStepSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    step_type: str
    tab_id: str | None = None
    tab_name: str | None = None
    state: BuildStepState = BuildStepState.PENDING
    duration_ms: int | None = None
    row_count: int | None = None
    error: str | None = None


class BuildQueryPlanSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tab_id: str | None = None
    tab_name: str | None = None
    optimized_plan: str
    unoptimized_plan: str


class BuildResourceSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sampled_at: datetime
    cpu_percent: float
    memory_mb: float
    memory_limit_mb: float | None = None
    active_threads: int
    max_threads: int | None = None


class BuildLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    level: BuildLogLevel
    message: str
    step_name: str | None = None
    step_id: str | None = None
    tab_id: str | None = None
    tab_name: str | None = None


class ActiveBuildSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    build_id: str
    analysis_id: str
    analysis_name: str
    namespace: str
    status: ActiveBuildStatus
    started_at: datetime
    starter: BuildStarter
    resource_config: BuildResourceConfigSummary | None = None
    progress: float = 0.0
    elapsed_ms: int = 0
    estimated_remaining_ms: int | None = None
    current_step: str | None = None
    current_step_index: int | None = None
    total_steps: int = 0
    current_kind: EngineRunKind | None = None
    current_datasource_id: str | None = None
    current_tab_id: str | None = None
    current_tab_name: str | None = None
    current_output_id: str | None = None
    current_output_name: str | None = None
    current_engine_run_id: str | None = None
    total_tabs: int = 0
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None
    result_json: dict[str, object] | None = None


class ActiveBuildDetail(ActiveBuildSummary):
    steps: list[BuildStepSnapshot] = Field(default_factory=list)
    query_plans: list[BuildQueryPlanSnapshot] = Field(default_factory=list)
    latest_resources: BuildResourceSnapshot | None = None
    resources: list[BuildResourceSnapshot] = Field(default_factory=list)
    logs: list[BuildLogEntry] = Field(default_factory=list)
    results: list[BuildTabResult] = Field(default_factory=list)
    duration_ms: int | None = None
    error: str | None = None
    request_json: dict[str, object] | None = None

    def cancel_duration_ms(self, *, cancelled_at: datetime) -> int:
        started_at = self.started_at if self.started_at.tzinfo is not None else self.started_at.replace(tzinfo=UTC)
        elapsed_from_start = max(int((cancelled_at - started_at).total_seconds() * 1000), 0)
        return max(self.elapsed_ms, elapsed_from_start)

    def cancelled_event(self, *, cancelled_at: datetime, cancelled_by: str | None, duration_ms: int, emitted_at: datetime) -> 'BuildCancelledEvent':
        return BuildCancelledEvent(
            build_id=self.build_id,
            analysis_id=self.analysis_id,
            emitted_at=emitted_at,
            current_kind=self.current_kind,
            current_datasource_id=self.current_datasource_id,
            tab_id=self.current_tab_id,
            tab_name=self.current_tab_name,
            current_output_id=self.current_output_id,
            current_output_name=self.current_output_name,
            engine_run_id=self.current_engine_run_id,
            progress=self.progress,
            elapsed_ms=duration_ms,
            total_steps=self.total_steps,
            tabs_built=len(self.results),
            results=self.results,
            duration_ms=duration_ms,
            cancelled_at=cancelled_at,
            cancelled_by=cancelled_by,
        )


class ActiveBuildListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    builds: list[ActiveBuildSummary]
    total: int


class BuildEventType(DataForgeStrEnum):
    PLAN = 'plan'
    STEP_START = 'step_start'
    STEP_COMPLETE = 'step_complete'
    STEP_FAILED = 'step_failed'
    PROGRESS = 'progress'
    RESOURCES = 'resources'
    LOG = 'log'
    COMPLETE = 'complete'
    FAILED = 'failed'
    CANCELLED = 'cancelled'

    @property
    def is_terminal(self) -> bool:
        return self in {BuildEventType.COMPLETE, BuildEventType.FAILED, BuildEventType.CANCELLED}

    @property
    def step_state(self) -> BuildStepState | None:
        match self:
            case BuildEventType.STEP_START:
                return BuildStepState.RUNNING
            case BuildEventType.STEP_COMPLETE:
                return BuildStepState.COMPLETED
            case BuildEventType.STEP_FAILED:
                return BuildStepState.FAILED
            case _:
                return None

    @property
    def terminal_build_status(self) -> ActiveBuildStatus | None:
        match self:
            case BuildEventType.COMPLETE:
                return ActiveBuildStatus.COMPLETED
            case BuildEventType.FAILED:
                return ActiveBuildStatus.FAILED
            case BuildEventType.CANCELLED:
                return ActiveBuildStatus.CANCELLED
            case _:
                return None

    @property
    def terminal_error_message(self) -> str | None:
        if self == BuildEventType.CANCELLED:
            return 'Build cancelled'
        return None

    @property
    def throttle_seconds(self) -> float | None:
        if self == BuildEventType.PROGRESS:
            return 0.1
        if self == BuildEventType.RESOURCES:
            return 0.5
        if self == BuildEventType.LOG:
            return 0.05
        return None


class BuildStreamEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: BuildEventType
    build_id: str
    analysis_id: str
    emitted_at: datetime
    sequence: int | None = None
    current_kind: EngineRunKind | None = None
    current_datasource_id: str | None = None
    tab_id: str | None = None
    tab_name: str | None = None
    current_output_id: str | None = None
    current_output_name: str | None = None
    engine_run_id: str | None = None


class BuildPlanEvent(BuildStreamEvent):
    type: Literal[BuildEventType.PLAN] = BuildEventType.PLAN
    optimized_plan: str
    unoptimized_plan: str


class BuildStepStartEvent(BuildStreamEvent):
    type: Literal[BuildEventType.STEP_START] = BuildEventType.STEP_START
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    step_type: str
    total_steps: int


class BuildStepCompleteEvent(BuildStreamEvent):
    type: Literal[BuildEventType.STEP_COMPLETE] = BuildEventType.STEP_COMPLETE
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    step_type: str
    duration_ms: int
    row_count: int | None = None
    total_steps: int


class BuildStepFailedEvent(BuildStreamEvent):
    type: Literal[BuildEventType.STEP_FAILED] = BuildEventType.STEP_FAILED
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    step_type: str
    error: str
    total_steps: int


class BuildProgressEvent(BuildStreamEvent):
    type: Literal[BuildEventType.PROGRESS] = BuildEventType.PROGRESS
    progress: float
    elapsed_ms: int
    estimated_remaining_ms: int | None = None
    current_step: str | None = None
    current_step_index: int | None = None
    total_steps: int


class BuildResourceEvent(BuildStreamEvent):
    type: Literal[BuildEventType.RESOURCES] = BuildEventType.RESOURCES
    cpu_percent: float
    memory_mb: float
    memory_limit_mb: float | None = None
    active_threads: int
    max_threads: int | None = None


class BuildLogEvent(BuildStreamEvent):
    type: Literal[BuildEventType.LOG] = BuildEventType.LOG
    level: BuildLogLevel
    message: str
    step_name: str | None = None
    step_id: str | None = None


class BuildCompleteEvent(BuildStreamEvent):
    type: Literal[BuildEventType.COMPLETE] = BuildEventType.COMPLETE
    progress: float = 1.0
    elapsed_ms: int
    total_steps: int
    tabs_built: int
    results: list[BuildTabResult]
    duration_ms: int


class BuildFailedEvent(BuildStreamEvent):
    type: Literal[BuildEventType.FAILED] = BuildEventType.FAILED
    progress: float
    elapsed_ms: int
    total_steps: int
    tabs_built: int
    results: list[BuildTabResult]
    duration_ms: int
    error: str | None = None


class BuildCancelledEvent(BuildStreamEvent):
    type: Literal[BuildEventType.CANCELLED] = BuildEventType.CANCELLED
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
    Field(discriminator='type'),
]

BuildEventAdapter: TypeAdapter[BuildEvent] = TypeAdapter(BuildEvent)


class CancelBuildResponse(BaseModel):
    id: str
    build_id: str | None = None
    engine_run_id: str | None = None
    status: Literal['cancelled'] = 'cancelled'
    duration_ms: int | None = None
    cancelled_at: datetime
    cancelled_by: str | None = None


class BuildSnapshotMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal['snapshot'] = 'snapshot'
    build: ActiveBuildDetail
    last_sequence: int = 0


class BuildListSnapshotMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal['snapshot'] = 'snapshot'
    builds: list[ActiveBuildSummary]


class BuildWebsocketErrorMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal['error'] = 'error'
    error: str
    status_code: int = 500
