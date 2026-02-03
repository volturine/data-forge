from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class Lock(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'locks'

    resource_id: str = Field(sa_column=Column(String, primary_key=True))
    client_id: str = Field(sa_column=Column(String, nullable=False))
    client_signature: str = Field(sa_column=Column(String, nullable=False))
    lock_token: str = Field(sa_column=Column(String, unique=True, nullable=False))
    acquired_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    last_heartbeat: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
