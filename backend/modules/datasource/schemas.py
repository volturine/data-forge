from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ColumnSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    dtype: str
    nullable: bool


class SchemaInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    columns: list[ColumnSchema]
    row_count: int | None = None


class FileDataSourceConfig(BaseModel):
    file_path: str
    file_type: str
    options: dict = {}


class DatabaseDataSourceConfig(BaseModel):
    connection_string: str
    query: str


class APIDataSourceConfig(BaseModel):
    url: str
    method: str = 'GET'
    headers: dict | None = None
    auth: dict | None = None


class DataSourceCreate(BaseModel):
    name: str
    source_type: str
    config: dict


class DataSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: str
    config: dict
    schema_cache: dict | None
    created_at: datetime
