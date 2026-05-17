import datetime as dt

from sqlalchemy import BIGINT, JSON, Column, DateTime, Enum as SAEnum, String
from sqlmodel import Field, SQLModel

from contracts.compute.schemas import EngineStatus
from contracts.enums import DataForgeStrEnum


class EngineInstanceStatus(DataForgeStrEnum):
    STARTING = 'starting'
    IDLE = 'idle'
    RUNNING = 'running'
    STOPPING = 'stopping'
    STOPPED = 'stopped'
    FAILED = 'failed'

    @property
    def is_active(self) -> bool:
        return self in {EngineInstanceStatus.IDLE, EngineInstanceStatus.RUNNING, EngineInstanceStatus.STARTING, EngineInstanceStatus.STOPPING}

    @property
    def overview_status(self) -> str:
        if self in {EngineInstanceStatus.IDLE, EngineInstanceStatus.RUNNING, EngineInstanceStatus.STARTING}:
            return 'healthy'
        return 'terminated'

    @classmethod
    def from_engine_status(cls, value: str, current_job_id: str | None) -> 'EngineInstanceStatus':
        engine_status = EngineStatus.require(value)
        if engine_status == EngineStatus.HEALTHY and current_job_id:
            return cls.RUNNING
        if engine_status == EngineStatus.HEALTHY:
            return cls.IDLE
        return cls.STOPPED


class EngineInstance(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'engine_instances'  # type: ignore[assignment]

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
