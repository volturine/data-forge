from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from modules.datasource.source_types import DataSourceType


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


class SnapshotCompareRequest(BaseModel):
    snapshot_a: str
    snapshot_b: str
    row_limit: int = 100


class SnapshotPreview(BaseModel):
    columns: list[str]
    column_types: dict[str, str]
    data: list[dict[str, object]]
    row_count: int


class ColumnStats(BaseModel):
    column: str
    dtype: str
    null_count: int
    unique_count: int | None = None
    min: object | None = None
    max: object | None = None


class SchemaDiff(BaseModel):
    column: str
    status: Literal['added', 'removed', 'type_changed']
    type_a: str | None = None
    type_b: str | None = None


class SnapshotCompareResponse(BaseModel):
    datasource_id: str
    snapshot_a: str
    snapshot_b: str
    row_count_a: int
    row_count_b: int
    row_count_delta: int
    schema_diff: list[SchemaDiff]
    stats_a: list[ColumnStats]
    stats_b: list[ColumnStats]
    preview_a: SnapshotPreview
    preview_b: SnapshotPreview


class HistogramBin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: float
    end: float
    count: int


class ColumnStatsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    column: str
    dtype: str
    count: int
    null_count: int
    null_percentage: float
    unique: int | None = None
    mean: float | None = None
    std: float | None = None
    min: float | str | None = None
    max: float | str | None = None
    median: float | None = None
    q25: float | None = None
    q75: float | None = None
    true_count: int | None = None
    false_count: int | None = None
    min_length: int | None = None
    max_length: int | None = None
    avg_length: float | None = None
    top_values: list[dict[str, object]] | None = None
    histogram: list[HistogramBin] | None = None


class ColumnStatsRequest(BaseModel):
    datasource_config: dict | None = None


class ExcelPreflightPathRequest(BaseModel):
    file_path: str
    sheet_name: str | None = None
    start_row: int = 0
    start_col: int = 0
    end_col: int = 0
    end_row: int | None = None
    has_header: bool = True
    table_name: str | None = None
    named_range: str | None = None
    cell_range: str | None = None


class ExcelPreflightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    preflight_id: str
    sheet_name: str | None = None
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
    sheet_name: str | None = None
    start_row: int
    start_col: int
    end_col: int
    detected_end_row: int | None


class CSVOptions(BaseModel):
    delimiter: str = ','
    quote_char: str = '"'
    has_header: bool = True
    skip_rows: int = 0
    encoding: str = 'utf8'

    model_config = ConfigDict(from_attributes=True)


class FileDataSourceConfig(BaseModel):
    file_path: str
    file_type: str
    options: dict = Field(default_factory=dict)
    csv_options: CSVOptions | None = None
    sheet_name: str | None = None
    start_row: int | None = None
    start_col: int | None = None
    end_col: int | None = None
    end_row: int | None = None
    has_header: bool | None = None
    table_name: str | None = None
    named_range: str | None = None
    cell_range: str | None = None


class DatabaseDataSourceConfig(BaseModel):
    connection_string: str
    query: str
    branch: str | None = None


class IcebergDataSourceConfig(BaseModel):
    metadata_path: str
    branch: str | None = None
    snapshot_id: str | None = None
    snapshot_timestamp_ms: int | None = None
    storage_options: dict | None = None
    reader: str | None = None
    catalog_type: str | None = None
    catalog_uri: str | None = None
    warehouse: str | None = None
    namespace: str | None = None
    table: str | None = None
    source: dict | None = None
    refresh: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class DataSourceCreate(BaseModel):
    name: str
    source_type: DataSourceType
    config: dict


class DataSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: DataSourceType
    config: dict
    schema_cache: dict | None
    created_by_analysis_id: str | None = None
    created_by: str = 'import'
    is_hidden: bool = False
    created_at: datetime
    output_of_tab_id: str | None = None


class DataSourceUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    config: dict | None = None
    is_hidden: bool | None = None


class FileListItem(BaseModel):
    name: str
    path: str
    is_dir: bool


class FileListResponse(BaseModel):
    base_path: str
    entries: list[FileListItem]


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
