import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


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
