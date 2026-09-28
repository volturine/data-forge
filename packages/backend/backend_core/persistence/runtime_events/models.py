import datetime as dt

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, text
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


class RuntimeNamespaceWork(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    """Durable cross-schema wake state for runtime recovery queues."""

    __tablename__ = 'runtime_namespace_work'  # type: ignore[assignment]
    __table_args__ = (
        Index('ix_runtime_namespace_work_pending', 'kind', 'pending', 'updated_at', 'namespace'),
        Index(
            'ix_runtime_namespace_work_due_at',
            'kind',
            'due_at',
            'namespace',
            postgresql_where=text('due_at IS NOT NULL'),
        ),
    )

    namespace: str = Field(sa_column=Column(String, primary_key=True))
    kind: str = Field(sa_column=Column(String, primary_key=True))
    pending: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    generation: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default='0'))
    processed_generation: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default='0'))
    due_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class RuntimeNamespaceWorkWake(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    """Append-only durable signals; producers never contend on a namespace row."""

    __tablename__ = 'runtime_namespace_work_wakes'  # type: ignore[assignment]
    __table_args__ = (
        Index('ix_runtime_namespace_work_wakes_kind_created', 'kind', 'created_at', 'namespace'),
        Index('ix_runtime_namespace_work_wakes_namespace_kind_id', 'namespace', 'kind', 'id'),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True),
    )
    namespace: str = Field(sa_column=Column(String, nullable=False))
    kind: str = Field(sa_column=Column(String, nullable=False))
    created_at: dt.datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
    )


class RuntimeCoordinatorState(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    """Monotonic fencing epoch for the single active runtime coordinator."""

    __tablename__ = 'runtime_coordinator_state'  # type: ignore[assignment]

    singleton_id: int = Field(default=1, primary_key=True)
    generation: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default='0'))
