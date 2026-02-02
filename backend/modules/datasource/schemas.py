from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ColumnSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    dtype: str
    nullable: bool
    sample_value: str | None = None


class SchemaInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    columns: list[ColumnSchema]
    row_count: int | None = None
    sheet_names: list[str] | None = None


class ExcelPreflightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    preflight_id: str
    sheet_names: list[str]
    tables: dict[str, list[str]]
    named_ranges: list[str]
    preview: list[list[str | None]]
    start_row: int
    start_col: int
    end_col: int
    detected_end_row: int | None


class ExcelPreflightPreviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    preview: list[list[str | None]]
    start_row: int
    start_col: int
    end_col: int
    detected_end_row: int | None


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
    sheet_name: str | None = None
    start_row: int | None = None
    start_col: int | None = None
    end_col: int | None = None
    end_row: int | None = None
    has_header: bool | None = None
    table_name: str | None = None
    named_range: str | None = None


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


class DataSourceUpdate(BaseModel):
    """Update a datasource configuration."""

    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    config: dict | None = None


class BulkUploadResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    success: bool
    datasource: DataSourceResponse | None = None
    error: str | None = None


class BulkUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    results: list[BulkUploadResult]
    total: int
    successful: int
    failed: int
