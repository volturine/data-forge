from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.mutable import MutableDict
from sqlmodel import Field, SQLModel


class AnalysisVersion(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'analysis_versions'

    id: str = Field(sa_column=Column(String, primary_key=True))
    analysis_id: str = Field(sa_column=Column(String, ForeignKey('analyses.id', ondelete='CASCADE'), nullable=False))
    version: int = Field(sa_column=Column(Integer, nullable=False))
    name: str = Field(sa_column=Column(String, nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    pipeline_definition: dict[str, Any] = Field(sa_column=Column(MutableDict.as_mutable(JSON), nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
