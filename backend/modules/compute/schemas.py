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


class AnalysisPipelineTab(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None = None
    datasource_id: str | None = None
    output_datasource_id: str | None = None
    datasource_config: dict | None = None
    steps: list[dict]


class AnalysisPipelinePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    tabs: list[AnalysisPipelineTab]
    sources: dict[str, dict]


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
    target_step_id: str
    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None
    row_limit: int = 1000
    page: int = 1
    resource_config: EngineResourceConfig | None = None
    datasource_config: dict | None = None


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
    DATASOURCE = 'datasource'


class ExportDatasourceType(str, Enum):
    ICEBERG = 'iceberg'
    DUCKDB = 'duckdb'
    FILE = 'file'


class IcebergExportOptions(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    table_name: str = 'exported_data'
    namespace: str = 'outputs'
    branch: str | None = None


class DuckDBExportOptions(BaseModel):
    """Options for DuckDB export when destination is 'datasource'."""

    model_config = ConfigDict(from_attributes=True)

    table_name: str = 'data'


class ExportRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    target_step_id: str
    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None
    format: ExportFormat = ExportFormat.CSV
    filename: str = 'export'
    destination: ExportDestination = ExportDestination.DOWNLOAD
    datasource_type: ExportDatasourceType = ExportDatasourceType.ICEBERG
    iceberg_options: IcebergExportOptions | None = None
    duckdb_options: DuckDBExportOptions | None = None
    datasource_config: dict | None = None
    output_datasource_id: str | None = None

    @field_validator('datasource_type')
    @classmethod
    def validate_datasource_type_for_output(cls, value: ExportDatasourceType, info):
        destination = info.data.get('destination') if info.data else None
        if destination == ExportDestination.DATASOURCE and value != ExportDatasourceType.ICEBERG:
            raise ValueError('Output exports must use Iceberg datasources')
        return value


class ExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    filename: str
    format: str
    destination: str
    file_path: str | None = None
    message: str | None = None
    datasource_id: str | None = None
    datasource_name: str | None = None


class StepSchemaRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    target_step_id: str
    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None
    datasource_config: dict | None = None


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


class BuildTabResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tab_id: str
    tab_name: str
    status: str
    error: str | None = None


class BuildResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    tabs_built: int
    results: list[BuildTabResult]


class BuildRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_pipeline: AnalysisPipelinePayload
    tab_id: str | None = None
