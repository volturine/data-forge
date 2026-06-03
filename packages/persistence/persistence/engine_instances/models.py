import datetime as dt

from contracts.engine_instances.models import EngineInstanceStatus
from sqlalchemy import BIGINT, JSON, Column, DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class EngineInstance(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = "engine_instances"  # type: ignore[assignment]

    id: str = Field(sa_column=Column(String, primary_key=True))
    worker_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    namespace: str = Field(sa_column=Column(String, nullable=False, index=True))
    analysis_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    process_id: int | None = Field(default=None, sa_column=Column(BIGINT, nullable=True))
    status: EngineInstanceStatus = Field(
        sa_column=Column(SAEnum(EngineInstanceStatus, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False, index=True)
    )
    current_job_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_build_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_engine_run_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    resource_config_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    effective_resources_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    last_activity_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_seen_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
