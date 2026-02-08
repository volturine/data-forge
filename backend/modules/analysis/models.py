from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String
from sqlalchemy.ext.mutable import MutableDict
from sqlmodel import Field, SQLModel


class Analysis(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'analyses'

    id: str = Field(sa_column=Column(String, primary_key=True))
    name: str = Field(sa_column=Column(String, nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    pipeline_definition: dict = Field(sa_column=Column(MutableDict.as_mutable(JSON), nullable=False))
    status: str = Field(default='draft', sa_column=Column(String, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    result_path: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    thumbnail: str | None = Field(default=None, sa_column=Column(String, nullable=True))


class AnalysisDataSource(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'analysis_datasources'

    analysis_id: str = Field(sa_column=Column(String, ForeignKey('analyses.id', ondelete='CASCADE'), primary_key=True))
    datasource_id: str = Field(sa_column=Column(String, ForeignKey('datasources.id', ondelete='CASCADE'), primary_key=True))
