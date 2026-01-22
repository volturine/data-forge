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


class CSVOptions(BaseModel):
    """CSV-specific parsing options."""

    delimiter: str = ','
    quote_char: str = '"'
    has_header: bool = True
    skip_rows: int = 0
    encoding: str = 'utf8'

    model_config = ConfigDict(from_attributes=True)


class FileDataSourceConfig(BaseModel):
    file_path: str
    file_type: str
    options: dict = {}
    csv_options: CSVOptions | None = None


class DatabaseDataSourceConfig(BaseModel):
    connection_string: str
    query: str


class DuckDBDataSourceConfig(BaseModel):
    """DuckDB-specific datasource configuration."""

    db_path: str | None = None
    query: str
    read_only: bool = True

    model_config = ConfigDict(from_attributes=True)


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
