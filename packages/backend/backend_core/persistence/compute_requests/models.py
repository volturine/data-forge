import datetime as dt

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String
from sqlmodel import Field, SQLModel


class ComputeRequest(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'compute_requests'  # type: ignore[assignment]
    __table_args__ = (
        Index(
            'ix_compute_requests_engine_identity',
            'namespace',
            'status',
            'engine_scope',
            'engine_reuse_policy',
            'engine_resource_id',
        ),
    )

    id: str = Field(sa_column=Column(String, primary_key=True))
    namespace: str = Field(sa_column=Column(String, nullable=False, index=True))
    kind: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    status: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    engine_scope: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    engine_reuse_policy: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    engine_resource_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    command_envelope: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    response_envelope: bytes | None = Field(default=None, sa_column=Column(LargeBinary, nullable=True))
    error_message: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    artifact_path: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    artifact_name: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    artifact_content_type: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    lease_owner: str | None = Field(default=None, sa_column=Column(String, nullable=True, index=True))
    claim_token: str | None = Field(default=None, sa_column=Column(String, nullable=True, unique=True))
    lease_generation: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    lease_expires_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    claimed_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_renewed_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    max_attempts: int = Field(default=3, sa_column=Column(Integer, nullable=False, server_default='3'))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class ComputeRequestDatasource(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    """Relational datasource dependencies for active-request cleanup."""

    __tablename__ = 'compute_request_datasources'  # type: ignore[assignment]
    __table_args__ = (Index('ix_compute_request_datasources_datasource_id', 'datasource_id'),)

    request_id: str = Field(
        sa_column=Column(String, ForeignKey('compute_requests.id', ondelete='CASCADE'), primary_key=True),
    )
    datasource_id: str = Field(sa_column=Column(String, primary_key=True))


class ComputeRequestFlight(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    """Durable single-flight ownership for one namespace and exact command."""

    __tablename__ = 'compute_request_flights'  # type: ignore[assignment]
    namespace: str = Field(sa_column=Column(String, primary_key=True))
    flight_key: str = Field(sa_column=Column(String, primary_key=True))
    request_id: str = Field(
        sa_column=Column(String, ForeignKey('compute_requests.id', ondelete='CASCADE'), nullable=False, unique=True, index=True),
    )
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True, index=True))
