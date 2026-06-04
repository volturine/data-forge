import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class ResourceLock(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'resource_locks'

    @staticmethod
    def as_utc(value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(UTC)
        return value.replace(tzinfo=UTC)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        current = self.as_utc(now or datetime.now(UTC))
        return self.as_utc(self.expires_at) <= current

    resource_type: str = Field(sa_column=Column(String, primary_key=True, nullable=False))
    resource_id: str = Field(sa_column=Column(String, primary_key=True, nullable=False))
    owner_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    lock_token: str = Field(default_factory=lambda: uuid.uuid4().hex, sa_column=Column(String, nullable=False, unique=True, index=True))
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None), sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None), sa_column=Column(DateTime(timezone=True), nullable=False))
