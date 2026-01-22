from enum import Enum

from pydantic import BaseModel, ConfigDict


class ExecuteMode(str, Enum):
    FULL = 'full'
    PREVIEW = 'preview'


class JobStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class EngineStatus(str, Enum):
    IDLE = 'idle'
    RUNNING = 'running'
    ERROR = 'error'
    TERMINATED = 'terminated'


class EngineStatusSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    status: EngineStatus
    process_id: int | None = None
    last_activity: str | None = None
    current_job_id: str | None = None


class EngineListSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    engines: list[EngineStatusSchema]
    total: int


class ComputeExecuteSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    execute_mode: ExecuteMode = ExecuteMode.FULL
    step_id: str | None = None


class ComputeStatusSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: JobStatus
    progress: float
    current_step: str | None = None
    error_message: str | None = None
    process_id: int | None = None


class ComputeResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: JobStatus
    data: dict | None = None
    error: str | None = None


class StepPreviewRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    datasource_id: str
    pipeline_steps: list[dict]
    target_step_id: str
    row_limit: int = 1000
    page: int = 1


class StepPreviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_id: str
    columns: list[str]
    column_types: dict[str, str] | None = None
    data: list[dict]
    total_rows: int
    page: int
    page_size: int


class ExportFormat(str, Enum):
    CSV = 'csv'
    PARQUET = 'parquet'
    JSON = 'json'
    NDJSON = 'ndjson'


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
