import datetime as dt

from sqlalchemy import JSON, Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel

from backend_core.domain.enums import DataForgeStrEnum


class RuntimeOutboxStatus(DataForgeStrEnum):
    PENDING = 'pending'
    DISPATCHING = 'dispatching'
    DISPATCHED = 'dispatched'
    FAILED = 'failed'
    POISONED = 'poisoned'


class RuntimeOutboxEvent(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'runtime_outbox_events'  # type: ignore[assignment]

    id: str = Field(sa_column=Column(String, primary_key=True))
    kind: str = Field(sa_column=Column(String, nullable=False, index=True))
    status: RuntimeOutboxStatus = Field(
        sa_column=Column(SAEnum(RuntimeOutboxStatus, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False, index=True)
    )
    payload_json: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    claim_token: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    lease_generation: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    lease_expires_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True, index=True))
    last_error: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    available_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    dispatched_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class NotificationDeliveryReceipt(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'notification_delivery_receipts'  # type: ignore[assignment]

    event_id: str = Field(sa_column=Column(String, ForeignKey('runtime_outbox_events.id', ondelete='CASCADE'), primary_key=True))
    kind: str = Field(sa_column=Column(String, nullable=False))
    delivered_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
