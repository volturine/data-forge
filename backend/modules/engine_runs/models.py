import datetime as dt

from sqlalchemy import JSON, Column, DateTime, Enum as SAEnum, Float, Integer, String
from sqlmodel import Field, SQLModel

from modules.engine_runs.schemas import EngineRunKind, EngineRunStatus


class EngineRun(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'engine_runs'  # type: ignore[assignment]

    id: str = Field(sa_column=Column(String, primary_key=True))
    analysis_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    datasource_id: str = Field(sa_column=Column(String, nullable=False))
    kind: EngineRunKind = Field(
        sa_column=Column(
            SAEnum(EngineRunKind, native_enum=False, values_callable=lambda enum_cls: [item.value for item in enum_cls]),
            nullable=False,
        ),
    )
    status: EngineRunStatus = Field(
        sa_column=Column(
            SAEnum(EngineRunStatus, native_enum=False, values_callable=lambda enum_cls: [item.value for item in enum_cls]),
            nullable=False,
        ),
    )
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
