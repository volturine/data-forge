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

    datasource_id: str
    pipeline_steps: list[dict]
    target_step_id: str
    row_limit: int = 1000
    page: int = 1


class StepPreviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_id: str
    columns: list[str]
    data: list[dict]
    total_rows: int
    page: int
    page_size: int
