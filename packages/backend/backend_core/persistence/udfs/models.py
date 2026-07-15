from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, String
from sqlmodel import Field, SQLModel


class Udf(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'udfs'

    id: str = Field(sa_column=Column(String, primary_key=True))
    name: str = Field(sa_column=Column(String, nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    signature: dict = Field(sa_column=Column(JSON, nullable=False))
    code: str = Field(sa_column=Column(String, nullable=False))
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    source: str = Field(default='user', sa_column=Column(String, nullable=False))
    owner_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
