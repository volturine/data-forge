import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EngineRunCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str | None = None
    datasource_id: str
    kind: str
    status: str
    request_json: dict
    result_json: dict | None = None
    error_message: str | None = None
    created_at: dt.datetime
    completed_at: dt.datetime | None = None
    duration_ms: int | None = None
    step_timings: dict = Field(default_factory=dict)
    query_plan: str | None = None
    progress: float = 0.0
    current_step: str | None = None
    triggered_by: str | None = None


class EngineRunResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str | None
    datasource_id: str
    kind: str
    status: str
    request_json: dict
    result_json: dict | None
    error_message: str | None
    created_at: dt.datetime
    completed_at: dt.datetime | None
    duration_ms: int | None
    step_timings: dict
    query_plan: str | None
    progress: float = 0.0
    current_step: str | None
    triggered_by: str | None = None


class ColumnDiff(BaseModel):
    column: str
    status: str  # 'added', 'removed', 'type_changed'
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
    kind: str
    status: str
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
