import datetime as dt

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel

from backend_core.domain.engine_instances.models import EngineInstanceStatus


class EngineInstance(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'engine_instances'  # type: ignore[assignment]

    id: str = Field(sa_column=Column(String, primary_key=True))
    worker_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    namespace: str = Field(sa_column=Column(String, nullable=False, index=True))
    analysis_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    engine_scope: str = Field(sa_column=Column(String, nullable=False, index=True))
    engine_reuse_policy: str = Field(sa_column=Column(String, nullable=False))
    datasource_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    build_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    container_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    image_digest: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    termination_reason: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    exit_code: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    oom_killed: bool | None = Field(default=None, sa_column=Column(Boolean, nullable=True))
    supervisor_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    owner_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    status: EngineInstanceStatus = Field(sa_column=Column(String, nullable=False, index=True))
    current_job_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_build_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_engine_run_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    resource_config_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    effective_resources_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    last_activity_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_seen_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))

    def status_kind(self) -> EngineInstanceStatus:
        return EngineInstanceStatus.require(self.status)
