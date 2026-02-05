from datetime import datetime

from sqlalchemy import Column, DateTime, JSON, String
from sqlmodel import Field, SQLModel


class DataSource(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'datasources'

    id: str = Field(sa_column=Column(String, primary_key=True))
    name: str = Field(sa_column=Column(String, nullable=False))
    source_type: str = Field(sa_column=Column(String, nullable=False))
    config: dict = Field(sa_column=Column(JSON, nullable=False))
    schema_cache: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
