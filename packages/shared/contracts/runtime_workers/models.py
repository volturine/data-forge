import datetime as dt

from sqlalchemy import Column, DateTime, Enum as SAEnum, Integer, String
from sqlmodel import Field, SQLModel

from contracts.enums import DataForgeStrEnum


class RuntimeWorkerKind(DataForgeStrEnum):
    API = 'api'
    BUILD_MANAGER = 'build_manager'
    BUILD_WORKER = 'build_worker'
    SCHEDULER = 'scheduler'


class RuntimeWorker(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'runtime_workers'  # type: ignore[assignment]

    def heartbeat_age_seconds(self, *, now: dt.datetime) -> float:
        heartbeat = self.last_heartbeat_at.astimezone(dt.UTC) if self.last_heartbeat_at.tzinfo is not None else self.last_heartbeat_at.replace(tzinfo=dt.UTC)
        current = now.astimezone(dt.UTC) if now.tzinfo is not None else now.replace(tzinfo=dt.UTC)
        return max((current - heartbeat).total_seconds(), 0.0)

    id: str = Field(sa_column=Column(String, primary_key=True))
    kind: RuntimeWorkerKind = Field(
        sa_column=Column(SAEnum(RuntimeWorkerKind, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False, index=True)
    )
    hostname: str = Field(sa_column=Column(String, nullable=False))
    pid: int = Field(sa_column=Column(Integer, nullable=False))
    capacity: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    active_jobs: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    started_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    last_heartbeat_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    stopped_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    def is_reclaimable(self, *, now: dt.datetime, heartbeat_seconds: float) -> bool:
        if self.stopped_at is not None:
            return True
        heartbeat = self.last_heartbeat_at.astimezone(dt.UTC) if self.last_heartbeat_at.tzinfo is not None else self.last_heartbeat_at.replace(tzinfo=dt.UTC)
        return now - heartbeat > dt.timedelta(seconds=heartbeat_seconds)
