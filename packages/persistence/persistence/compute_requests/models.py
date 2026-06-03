import datetime as dt

from contracts.compute_requests.models import ComputeRequestKind, ComputeRequestStatus
from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class ComputeRequest(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = "compute_requests"  # type: ignore[assignment]

    id: str = Field(sa_column=Column(String, primary_key=True))
    namespace: str = Field(sa_column=Column(String, nullable=False, index=True))
    kind: ComputeRequestKind = Field(
        sa_column=Column(SAEnum(ComputeRequestKind, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False, index=True)
    )
    status: ComputeRequestStatus = Field(
        sa_column=Column(SAEnum(ComputeRequestStatus, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False, index=True)
    )
    request_json: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    response_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error_message: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    artifact_path: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    artifact_name: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    artifact_content_type: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    lease_owner: str | None = Field(default=None, sa_column=Column(String, nullable=True, index=True))
    lease_expires_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
