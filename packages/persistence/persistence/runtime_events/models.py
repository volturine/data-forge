import datetime as dt

from contracts.enums import DataForgeStrEnum
from sqlalchemy import JSON, Column, DateTime, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class RuntimeOutboxStatus(DataForgeStrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class RuntimeOutboxEvent(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = "runtime_outbox_events"  # type: ignore[assignment]

    id: str = Field(sa_column=Column(String, primary_key=True))
    kind: str = Field(sa_column=Column(String, nullable=False, index=True))
    status: RuntimeOutboxStatus = Field(
        sa_column=Column(SAEnum(RuntimeOutboxStatus, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False, index=True)
    )
    payload_json: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    last_error: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    available_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    dispatched_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
