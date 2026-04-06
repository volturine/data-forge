import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ResourceLock(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'resource_locks'

    resource_type: str = Field(sa_column=Column(String, primary_key=True, nullable=False))
    resource_id: str = Field(sa_column=Column(String, primary_key=True, nullable=False))
    owner_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    lock_token: str = Field(default_factory=lambda: uuid.uuid4().hex, sa_column=Column(String, nullable=False, unique=True, index=True))
    acquired_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    last_heartbeat: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
