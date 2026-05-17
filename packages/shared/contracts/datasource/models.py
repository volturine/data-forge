from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from contracts.datasource.source_types import DataSourceType
from contracts.enums import DataForgeStrEnum


class DataSourceCreatedBy(DataForgeStrEnum):
    IMPORT = 'import'
    ANALYSIS = 'analysis'


class DataSourceTargetKind(DataForgeStrEnum):
    ANALYSIS = 'analysis'
    RAW = 'raw'
    DATASOURCE = 'datasource'


class DataSource(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'datasources'

    def source_type_kind(self) -> DataSourceType:
        return DataSourceType.require(self.source_type)

    def created_by_kind(self) -> DataSourceCreatedBy:
        return DataSourceCreatedBy.require(self.created_by)

    @property
    def is_analysis_output(self) -> bool:
        return self.created_by_kind() == DataSourceCreatedBy.ANALYSIS

    @property
    def is_analysis_source(self) -> bool:
        return self.source_type_kind() == DataSourceType.ANALYSIS

    @property
    def is_iceberg(self) -> bool:
        return self.source_type_kind() == DataSourceType.ICEBERG

    def analysis_source_id(self) -> str:
        analysis_id = self.created_by_analysis_id
        if not analysis_id:
            raise ValueError(f'Analysis datasource {self.id} missing created_by_analysis_id')
        return str(analysis_id)

    def external_source_config(self) -> dict[str, object] | None:
        if not self.is_iceberg or not isinstance(self.config, dict):
            return None
        source = self.config.get('source')
        return source if isinstance(source, dict) else None

    def external_source_type(self) -> DataSourceType | None:
        source = self.external_source_config()
        if source is None:
            return None
        return DataSourceType.read(source.get('source_type'), default=None)

    @property
    def is_refreshable_external(self) -> bool:
        source_type = self.external_source_type()
        return source_type.supports_external_ingestion if source_type is not None else False

    def is_reingestable_raw(self) -> bool:
        if not self.is_iceberg:
            return False
        if self.is_analysis_output:
            return False
        return self.is_refreshable_external

    def target_kind(self) -> DataSourceTargetKind:
        if self.is_analysis_output and self.created_by_analysis_id:
            return DataSourceTargetKind.ANALYSIS
        if self.is_reingestable_raw():
            return DataSourceTargetKind.RAW
        return DataSourceTargetKind.DATASOURCE

    id: str = Field(sa_column=Column(String, primary_key=True))
    name: str = Field(sa_column=Column(String, nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String(4000), nullable=True))
    source_type: str = Field(sa_column=Column(String, nullable=False))
    config: dict = Field(sa_column=Column(JSON, nullable=False))
    schema_cache: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_by_analysis_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_by: str = Field(default=DataSourceCreatedBy.IMPORT.value, sa_column=Column(String, nullable=False, server_default=DataSourceCreatedBy.IMPORT.value))
    is_hidden: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default='0'))
    owner_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class DataSourceColumnMetadata(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'datasource_column_metadata'
    __table_args__ = (UniqueConstraint('datasource_id', 'column_name', name='uq_datasource_column_metadata_name'),)

    id: str = Field(sa_column=Column(String, primary_key=True))
    datasource_id: str = Field(sa_column=Column(String, ForeignKey('datasources.id', ondelete='CASCADE'), nullable=False, index=True))
    column_name: str = Field(sa_column=Column(String, nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String(2000), nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
