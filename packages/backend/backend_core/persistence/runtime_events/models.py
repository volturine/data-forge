import datetime as dt

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Enum as SAEnum, ForeignKey, Identity, Index, Integer, String, text
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
    __table_args__ = (
        Index(
            'ix_runtime_outbox_catalog_table',
            'catalog_namespace',
            'catalog_table',
            postgresql_where=text('catalog_namespace IS NOT NULL'),
            postgresql_ops={'catalog_table': 'varchar_pattern_ops'},
        ),
        Index(
            'ix_runtime_outbox_catalog_family',
            'catalog_namespace',
            'catalog_family_prefix',
            postgresql_where=text('catalog_namespace IS NOT NULL'),
        ),
    )

    id: str = Field(sa_column=Column(String, primary_key=True))
    kind: str = Field(sa_column=Column(String, nullable=False, index=True))
    status: RuntimeOutboxStatus = Field(
        sa_column=Column(SAEnum(RuntimeOutboxStatus, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False, index=True)
    )
    payload_json: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    catalog_namespace: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    catalog_table: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    catalog_family_prefix: str | None = Field(default=None, sa_column=Column(String, nullable=True))
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


class NotificationDeliveryPartReceipt(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    """Durable per-part progress for external deliveries that have multiple sends."""

    __tablename__ = 'notification_delivery_part_receipts'  # type: ignore[assignment]

    event_id: str = Field(
        sa_column=Column(String, ForeignKey('runtime_outbox_events.id', ondelete='CASCADE'), primary_key=True),
    )
    part_key: str = Field(sa_column=Column(String, primary_key=True))
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
    """Append-only durable pointers to namespace work, independent of marker locks."""

    __tablename__ = 'runtime_namespace_work_wakes'  # type: ignore[assignment]
    __table_args__ = (
        Index('ix_runtime_namespace_work_wakes_kind_namespace_id', 'kind', 'namespace', 'id'),
        Index('ix_runtime_namespace_work_wakes_namespace_kind_id', 'namespace', 'kind', 'id'),
    )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, Identity(), primary_key=True))
    namespace: str = Field(sa_column=Column(String, nullable=False))
    kind: str = Field(sa_column=Column(String, nullable=False))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text('statement_timestamp()')))


class RuntimeCoordinatorState(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    """Monotonic fencing epoch for the single active runtime coordinator."""

    __tablename__ = 'runtime_coordinator_state'  # type: ignore[assignment]

    singleton_id: int = Field(default=1, primary_key=True)
    generation: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default='0'))
