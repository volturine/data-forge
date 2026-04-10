import datetime as dt
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EngineRunKind(StrEnum):
    PREVIEW = 'preview'
    ROW_COUNT = 'row_count'
    DOWNLOAD = 'download'
    DATASOURCE_CREATE = 'datasource_create'
    DATASOURCE_UPDATE = 'datasource_update'


class EngineRunStatus(StrEnum):
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'


class EngineRunExecutionCategory(StrEnum):
    READ = 'read'
    STEP = 'step'
    PLAN = 'plan'
    WRITE = 'write'


class SchemaDiffStatus(StrEnum):
    ADDED = 'added'
    REMOVED = 'removed'
    TYPE_CHANGED = 'type_changed'


class EngineRunResultSummary(BaseModel):
    model_config = ConfigDict(extra='allow')

    row_count: int | str | None = None
    schema_: dict[str, str] | None = Field(default_factory=dict, alias='schema')
    data: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class EngineRunExecutionEntry(BaseModel):
    key: str
    label: str
    category: EngineRunExecutionCategory
    order: int
    duration_ms: float | None = None
    share_pct: float | None = None
    optimized_plan: str | None = None
    unoptimized_plan: str | None = None
    metadata: dict[str, Any] | None = None


class EngineRunBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str | None = None
    datasource_id: str
    kind: EngineRunKind
    status: EngineRunStatus
    request_json: dict[str, Any]
    result_json: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: dt.datetime
    completed_at: dt.datetime | None = None
    duration_ms: int | None = None
    step_timings: dict[str, float] = Field(default_factory=dict)
    query_plan: str | None = None
    progress: float = 0.0
    current_step: str | None = None
    triggered_by: str | None = None
    execution_entries: list[EngineRunExecutionEntry] = Field(default_factory=list)


class EngineRunResponseSchema(EngineRunBaseSchema):
    id: str


class EngineRunListParams(BaseModel):
    analysis_id: str | None = None
    datasource_id: str | None = None
    kind: EngineRunKind | None = None
    status: EngineRunStatus | None = None
    limit: int = 100
    offset: int = 0


class EngineRunListSnapshotMessage(BaseModel):
    type: Literal['snapshot'] = 'snapshot'
    runs: list[EngineRunResponseSchema]


class EngineRunWebsocketErrorMessage(BaseModel):
    type: Literal['error'] = 'error'
    error: str
    status_code: int = 500


class ColumnDiff(BaseModel):
    column: str
    status: SchemaDiffStatus
    type_a: str | None = None
    type_b: str | None = None


class TimingDiff(BaseModel):
    step: str
    ms_a: float | None = None
    ms_b: float | None = None
    delta_ms: float | None = None
    delta_pct: float | None = None


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: EngineRunKind
    status: EngineRunStatus
    created_at: dt.datetime
    duration_ms: int | None
    row_count: int | None = None
    schema_columns: int = 0
    triggered_by: str | None = None

    @model_validator(mode='before')
    @classmethod
    def extract_result_fields(cls, values: dict) -> dict:  # type: ignore[override]
        """Pull row_count and schema size from result_json if present."""
        if not isinstance(values, dict):
            return values
        rj = values.get('result_json') or {}
        if 'row_count' not in values or values.get('row_count') is None:
            rc = rj.get('row_count')
            if rc is not None:
                values['row_count'] = int(rc) if not isinstance(rc, int) else rc
        if values.get('schema_columns', 0) == 0:
            schema = rj.get('schema')
            if isinstance(schema, dict):
                values['schema_columns'] = len(schema)
        return values


class BuildComparisonResponse(BaseModel):
    run_a: RunSummary
    run_b: RunSummary
    row_count_a: int | None = None
    row_count_b: int | None = None
    row_count_delta: int | None = None
    schema_diff: list[ColumnDiff] = Field(default_factory=list)
    timing_diff: list[TimingDiff] = Field(default_factory=list)
    total_duration_delta_ms: int | None = None
