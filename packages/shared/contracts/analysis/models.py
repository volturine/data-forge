from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String
from sqlalchemy.ext.mutable import MutableDict
from sqlmodel import Field, SQLModel

from contracts.analysis.pipeline_types import PipelineDefinition, parse_pipeline
from contracts.enums import DataForgeStrEnum


class AnalysisStatus(DataForgeStrEnum):
    DRAFT = 'draft'
    RUNNING = 'running'
    COMPLETED = 'completed'
    ERROR = 'error'


class Analysis(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'analyses'

    id: str = Field(sa_column=Column(String, primary_key=True))
    name: str = Field(sa_column=Column(String, nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    pipeline_definition: dict[str, Any] = Field(sa_column=Column(MutableDict.as_mutable(JSON), nullable=False))

    @property
    def pipeline(self) -> PipelineDefinition:
        """Parse the raw JSON pipeline_definition into typed dataclasses."""
        return parse_pipeline(self.pipeline_definition)

    status: AnalysisStatus = Field(default=AnalysisStatus.DRAFT, sa_column=Column(String, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    result_path: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    thumbnail: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    owner_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))


class AnalysisDataSource(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'analysis_datasources'

    analysis_id: str = Field(sa_column=Column(String, ForeignKey('analyses.id', ondelete='CASCADE'), primary_key=True))
    datasource_id: str = Field(sa_column=Column(String, ForeignKey('datasources.id', ondelete='CASCADE'), primary_key=True))


class AnalysisFavorite(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'analysis_favorites'

    user_id: str = Field(sa_column=Column(String, primary_key=True))
    analysis_id: str = Field(sa_column=Column(String, ForeignKey('analyses.id', ondelete='CASCADE'), primary_key=True))
