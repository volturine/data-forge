from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class EngineStatus(str, Enum):
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


class EngineListSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    engines: list[EngineStatusSchema]
    total: int


class SpawnEngineRequest(BaseModel):
    """Request body for spawning an engine with optional resource config."""

    model_config = ConfigDict(from_attributes=True)

    resource_config: EngineResourceConfig | None = None


EngineDefaultsResponse = EngineDefaults  # Alias for backwards compatibility


class StepPreviewRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    datasource_id: str
    pipeline_steps: list[dict]
    target_step_id: str
    row_limit: int = 1000
    page: int = 1
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


StepPreviewRequest.model_rebuild()


class ExportFormat(str, Enum):
    CSV = 'csv'
    PARQUET = 'parquet'
    JSON = 'json'
    NDJSON = 'ndjson'
    DUCKDB = 'duckdb'


class ExportDestination(str, Enum):
    DOWNLOAD = 'download'
    FILESYSTEM = 'filesystem'


class ExportRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    datasource_id: str
    pipeline_steps: list[dict]
    target_step_id: str
    format: ExportFormat = ExportFormat.CSV
    filename: str = 'export'
    destination: ExportDestination = ExportDestination.DOWNLOAD


class ExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    filename: str
    format: str
    destination: str
    file_path: str | None = None
    message: str | None = None


class StepSchemaRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    datasource_id: str
    pipeline_steps: list[dict]
    target_step_id: str


class StepSchemaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_id: str
    columns: list[str]
    column_types: dict[str, str]
