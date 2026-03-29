from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class EngineStatus(StrEnum):
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
    config: AnalysisPipelineDatasourceConfig


class AnalysisPipelineTab(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None = None
    datasource: AnalysisPipelineDatasource
    output: dict
    steps: list[dict]

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
    sources: dict[str, dict]

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


class EngineListSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    engines: list[EngineStatusSchema]
    total: int


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
    metadata: dict | None = None


StepPreviewRequest.model_rebuild()


class ExportFormat(StrEnum):
    CSV = 'csv'
    PARQUET = 'parquet'
    JSON = 'json'
    NDJSON = 'ndjson'
    DUCKDB = 'duckdb'
    EXCEL = 'excel'


class ExportDestination(StrEnum):
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


class ComputeWebsocketAction(StrEnum):
    PREVIEW = 'preview'
    SCHEMA = 'schema'
    ROW_COUNT = 'row_count'
    BUILD = 'build'


class ComputeWebsocketRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: ComputeWebsocketAction
    payload: dict = Field(default_factory=dict)


class ComputeWebsocketStartedMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal['started'] = 'started'
    action: ComputeWebsocketAction


class ComputeWebsocketResultMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal['result'] = 'result'
    action: ComputeWebsocketAction
    data: dict


class ComputeWebsocketErrorMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal['error'] = 'error'
    action: ComputeWebsocketAction | None = None
    error: str
    status_code: int = 500
