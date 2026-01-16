from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ColumnSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    dtype: str


class ResultMetadataSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    row_count: int
    column_count: int
    columns_schema: list[ColumnSchema]
    created_at: datetime


class ResultDataSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    columns: list[str]
    data: list[dict]
    total_count: int
    page: int
    page_size: int


class ExportRequestSchema(BaseModel):
    format: str = Field(..., pattern='^(csv|parquet|excel|json)$')
