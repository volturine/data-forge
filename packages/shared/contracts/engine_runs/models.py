import datetime as dt

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from sqlmodel import Field, SQLModel

from contracts.engine_runs.schemas import EngineRunKind, EngineRunStatus


class EngineRun(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'engine_runs'  # type: ignore[assignment]

    def kind_kind(self) -> EngineRunKind:
        return EngineRunKind.require(self.kind)

    def status_kind(self) -> EngineRunStatus:
        return EngineRunStatus.require(self.status)

    id: str = Field(sa_column=Column(String, primary_key=True))
    analysis_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    datasource_id: str = Field(sa_column=Column(String, nullable=False))
    kind: str = Field(sa_column=Column(String, nullable=False))
    status: str = Field(sa_column=Column(String, nullable=False))
    request_json: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    result_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error_message: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    duration_ms: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    step_timings: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    query_plan: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    progress: float = Field(default=0.0, sa_column=Column(Float, nullable=False))
    current_step: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    triggered_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))
