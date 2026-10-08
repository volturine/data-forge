import datetime

from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DatasourceRef(_message.Message):
    __slots__ = ("namespace", "datasource_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ...) -> None: ...

class DatasourceMetadata(_message.Message):
    __slots__ = ("id", "name", "source_type", "created_by", "target_kind", "config", "is_hidden", "schema_info")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    TARGET_KIND_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    IS_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_INFO_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    source_type: _enums_pb2.DataSourceType
    created_by: _enums_pb2.DataSourceCreatedBy
    target_kind: _enums_pb2.DataSourceTargetKind
    config: _struct_pb2.Struct
    is_hidden: bool
    schema_info: SchemaInfo
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., created_by: _Optional[_Union[_enums_pb2.DataSourceCreatedBy, str]] = ..., target_kind: _Optional[_Union[_enums_pb2.DataSourceTargetKind, str]] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., is_hidden: _Optional[bool] = ..., schema_info: _Optional[_Union[SchemaInfo, _Mapping]] = ...) -> None: ...

class CsvOptions(_message.Message):
    __slots__ = ("delimiter", "quote_char", "has_header", "skip_rows", "encoding")
    DELIMITER_FIELD_NUMBER: _ClassVar[int]
    QUOTE_CHAR_FIELD_NUMBER: _ClassVar[int]
    HAS_HEADER_FIELD_NUMBER: _ClassVar[int]
    SKIP_ROWS_FIELD_NUMBER: _ClassVar[int]
    ENCODING_FIELD_NUMBER: _ClassVar[int]
    delimiter: str
    quote_char: str
    has_header: bool
    skip_rows: int
    encoding: str
    def __init__(self, delimiter: _Optional[str] = ..., quote_char: _Optional[str] = ..., has_header: _Optional[bool] = ..., skip_rows: _Optional[int] = ..., encoding: _Optional[str] = ...) -> None: ...

class CreateFileDatasourceCommand(_message.Message):
    __slots__ = ("name", "description", "file_path", "file_type", "options", "csv_options", "sheet_name", "start_row", "start_col", "end_col", "end_row", "has_header", "table_name", "named_range", "cell_range", "owner_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    FILE_PATH_FIELD_NUMBER: _ClassVar[int]
    FILE_TYPE_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    CSV_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    SHEET_NAME_FIELD_NUMBER: _ClassVar[int]
    START_ROW_FIELD_NUMBER: _ClassVar[int]
    START_COL_FIELD_NUMBER: _ClassVar[int]
    END_COL_FIELD_NUMBER: _ClassVar[int]
    END_ROW_FIELD_NUMBER: _ClassVar[int]
    HAS_HEADER_FIELD_NUMBER: _ClassVar[int]
    TABLE_NAME_FIELD_NUMBER: _ClassVar[int]
    NAMED_RANGE_FIELD_NUMBER: _ClassVar[int]
    CELL_RANGE_FIELD_NUMBER: _ClassVar[int]
    OWNER_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    file_path: str
    file_type: _enums_pb2.DataSourceFileType
    options: _struct_pb2.Struct
    csv_options: CsvOptions
    sheet_name: str
    start_row: int
    start_col: int
    end_col: int
    end_row: int
    has_header: bool
    table_name: str
    named_range: str
    cell_range: str
    owner_id: str
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., file_path: _Optional[str] = ..., file_type: _Optional[_Union[_enums_pb2.DataSourceFileType, str]] = ..., options: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., csv_options: _Optional[_Union[CsvOptions, _Mapping]] = ..., sheet_name: _Optional[str] = ..., start_row: _Optional[int] = ..., start_col: _Optional[int] = ..., end_col: _Optional[int] = ..., end_row: _Optional[int] = ..., has_header: _Optional[bool] = ..., table_name: _Optional[str] = ..., named_range: _Optional[str] = ..., cell_range: _Optional[str] = ..., owner_id: _Optional[str] = ...) -> None: ...

class CreateDatabaseDatasourceCommand(_message.Message):
    __slots__ = ("name", "description", "connection_string", "query", "branch", "owner_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    CONNECTION_STRING_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    BRANCH_FIELD_NUMBER: _ClassVar[int]
    OWNER_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    connection_string: str
    query: str
    branch: str
    owner_id: str
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., connection_string: _Optional[str] = ..., query: _Optional[str] = ..., branch: _Optional[str] = ..., owner_id: _Optional[str] = ...) -> None: ...

class CreateIcebergDatasourceCommand(_message.Message):
    __slots__ = ("name", "description", "source", "branch", "owner_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    BRANCH_FIELD_NUMBER: _ClassVar[int]
    OWNER_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    source: _struct_pb2.Struct
    branch: str
    owner_id: str
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., source: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., branch: _Optional[str] = ..., owner_id: _Optional[str] = ...) -> None: ...

class IngestDatasourceCommand(_message.Message):
    __slots__ = ("datasource_id",)
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    def __init__(self, datasource_id: _Optional[str] = ...) -> None: ...

class DatasourceSchemaCommand(_message.Message):
    __slots__ = ("datasource_id", "sheet_name", "refresh")
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    SHEET_NAME_FIELD_NUMBER: _ClassVar[int]
    REFRESH_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    sheet_name: str
    refresh: bool
    def __init__(self, datasource_id: _Optional[str] = ..., sheet_name: _Optional[str] = ..., refresh: _Optional[bool] = ...) -> None: ...

class DatasourceColumnStatsCommand(_message.Message):
    __slots__ = ("datasource_id", "column_name", "use_sample", "sample_size", "datasource_config")
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    COLUMN_NAME_FIELD_NUMBER: _ClassVar[int]
    USE_SAMPLE_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_SIZE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    column_name: str
    use_sample: bool
    sample_size: int
    datasource_config: _struct_pb2.Struct
    def __init__(self, datasource_id: _Optional[str] = ..., column_name: _Optional[str] = ..., use_sample: _Optional[bool] = ..., sample_size: _Optional[int] = ..., datasource_config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class CompareIcebergSnapshotsCommand(_message.Message):
    __slots__ = ("datasource_id", "snapshot_a", "snapshot_b", "row_limit")
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_A_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_B_FIELD_NUMBER: _ClassVar[int]
    ROW_LIMIT_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    snapshot_a: str
    snapshot_b: str
    row_limit: int
    def __init__(self, datasource_id: _Optional[str] = ..., snapshot_a: _Optional[str] = ..., snapshot_b: _Optional[str] = ..., row_limit: _Optional[int] = ...) -> None: ...

class DatasourceInputRevision(_message.Message):
    __slots__ = ("datasource_id", "revision")
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    revision: int
    def __init__(self, datasource_id: _Optional[str] = ..., revision: _Optional[int] = ...) -> None: ...

class DatasourcePreflightCommand(_message.Message):
    __slots__ = ("preflight_id", "source_path", "action", "sheet_name", "start_row", "start_col", "end_col", "end_row", "has_header", "table_name", "named_range", "cell_range", "datasource_id", "delete_source")
    PREFLIGHT_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_PATH_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    SHEET_NAME_FIELD_NUMBER: _ClassVar[int]
    START_ROW_FIELD_NUMBER: _ClassVar[int]
    START_COL_FIELD_NUMBER: _ClassVar[int]
    END_COL_FIELD_NUMBER: _ClassVar[int]
    END_ROW_FIELD_NUMBER: _ClassVar[int]
    HAS_HEADER_FIELD_NUMBER: _ClassVar[int]
    TABLE_NAME_FIELD_NUMBER: _ClassVar[int]
    NAMED_RANGE_FIELD_NUMBER: _ClassVar[int]
    CELL_RANGE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    DELETE_SOURCE_FIELD_NUMBER: _ClassVar[int]
    preflight_id: str
    source_path: str
    action: _enums_pb2.DatasourcePreflightAction
    sheet_name: str
    start_row: int
    start_col: int
    end_col: int
    end_row: int
    has_header: bool
    table_name: str
    named_range: str
    cell_range: str
    datasource_id: str
    delete_source: bool
    def __init__(self, preflight_id: _Optional[str] = ..., source_path: _Optional[str] = ..., action: _Optional[_Union[_enums_pb2.DatasourcePreflightAction, str]] = ..., sheet_name: _Optional[str] = ..., start_row: _Optional[int] = ..., start_col: _Optional[int] = ..., end_col: _Optional[int] = ..., end_row: _Optional[int] = ..., has_header: _Optional[bool] = ..., table_name: _Optional[str] = ..., named_range: _Optional[str] = ..., cell_range: _Optional[str] = ..., datasource_id: _Optional[str] = ..., delete_source: _Optional[bool] = ...) -> None: ...

class DatasourcePreflightTable(_message.Message):
    __slots__ = ("columns",)
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    columns: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, columns: _Optional[_Iterable[str]] = ...) -> None: ...

class DatasourcePreflightResult(_message.Message):
    __slots__ = ("preflight_id", "sheets", "tables", "named_ranges", "preview_rows", "sheet_name", "start_row", "start_col", "end_col", "detected_end_row", "source_path", "delete_source")
    class TablesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: DatasourcePreflightTable
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[DatasourcePreflightTable, _Mapping]] = ...) -> None: ...
    PREFLIGHT_ID_FIELD_NUMBER: _ClassVar[int]
    SHEETS_FIELD_NUMBER: _ClassVar[int]
    TABLES_FIELD_NUMBER: _ClassVar[int]
    NAMED_RANGES_FIELD_NUMBER: _ClassVar[int]
    PREVIEW_ROWS_FIELD_NUMBER: _ClassVar[int]
    SHEET_NAME_FIELD_NUMBER: _ClassVar[int]
    START_ROW_FIELD_NUMBER: _ClassVar[int]
    START_COL_FIELD_NUMBER: _ClassVar[int]
    END_COL_FIELD_NUMBER: _ClassVar[int]
    DETECTED_END_ROW_FIELD_NUMBER: _ClassVar[int]
    SOURCE_PATH_FIELD_NUMBER: _ClassVar[int]
    DELETE_SOURCE_FIELD_NUMBER: _ClassVar[int]
    preflight_id: str
    sheets: _containers.RepeatedScalarFieldContainer[str]
    tables: _containers.MessageMap[str, DatasourcePreflightTable]
    named_ranges: _containers.RepeatedScalarFieldContainer[str]
    preview_rows: _containers.RepeatedCompositeFieldContainer[_struct_pb2.Struct]
    sheet_name: str
    start_row: int
    start_col: int
    end_col: int
    detected_end_row: int
    source_path: str
    delete_source: bool
    def __init__(self, preflight_id: _Optional[str] = ..., sheets: _Optional[_Iterable[str]] = ..., tables: _Optional[_Mapping[str, DatasourcePreflightTable]] = ..., named_ranges: _Optional[_Iterable[str]] = ..., preview_rows: _Optional[_Iterable[_Union[_struct_pb2.Struct, _Mapping]]] = ..., sheet_name: _Optional[str] = ..., start_row: _Optional[int] = ..., start_col: _Optional[int] = ..., end_col: _Optional[int] = ..., detected_end_row: _Optional[int] = ..., source_path: _Optional[str] = ..., delete_source: _Optional[bool] = ...) -> None: ...

class DatasourceCommand(_message.Message):
    __slots__ = ("create_file", "create_database", "create_iceberg", "ingest", "schema", "column_stats", "compare_iceberg_snapshots", "preflight")
    CREATE_FILE_FIELD_NUMBER: _ClassVar[int]
    CREATE_DATABASE_FIELD_NUMBER: _ClassVar[int]
    CREATE_ICEBERG_FIELD_NUMBER: _ClassVar[int]
    INGEST_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    COLUMN_STATS_FIELD_NUMBER: _ClassVar[int]
    COMPARE_ICEBERG_SNAPSHOTS_FIELD_NUMBER: _ClassVar[int]
    PREFLIGHT_FIELD_NUMBER: _ClassVar[int]
    create_file: CreateFileDatasourceCommand
    create_database: CreateDatabaseDatasourceCommand
    create_iceberg: CreateIcebergDatasourceCommand
    ingest: IngestDatasourceCommand
    schema: DatasourceSchemaCommand
    column_stats: DatasourceColumnStatsCommand
    compare_iceberg_snapshots: CompareIcebergSnapshotsCommand
    preflight: DatasourcePreflightCommand
    def __init__(self, create_file: _Optional[_Union[CreateFileDatasourceCommand, _Mapping]] = ..., create_database: _Optional[_Union[CreateDatabaseDatasourceCommand, _Mapping]] = ..., create_iceberg: _Optional[_Union[CreateIcebergDatasourceCommand, _Mapping]] = ..., ingest: _Optional[_Union[IngestDatasourceCommand, _Mapping]] = ..., schema: _Optional[_Union[DatasourceSchemaCommand, _Mapping]] = ..., column_stats: _Optional[_Union[DatasourceColumnStatsCommand, _Mapping]] = ..., compare_iceberg_snapshots: _Optional[_Union[CompareIcebergSnapshotsCommand, _Mapping]] = ..., preflight: _Optional[_Union[DatasourcePreflightCommand, _Mapping]] = ...) -> None: ...

class DataSourceRecord(_message.Message):
    __slots__ = ("id", "name", "description", "source_type", "config", "created_by_analysis_id", "created_by", "is_hidden", "created_at", "output_of_tab_id", "schema_info")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    IS_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_OF_TAB_ID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_INFO_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    description: str
    source_type: _enums_pb2.DataSourceType
    config: _struct_pb2.Struct
    created_by_analysis_id: str
    created_by: _enums_pb2.DataSourceCreatedBy
    is_hidden: bool
    created_at: _timestamp_pb2.Timestamp
    output_of_tab_id: str
    schema_info: SchemaInfo
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., description: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., created_by_analysis_id: _Optional[str] = ..., created_by: _Optional[_Union[_enums_pb2.DataSourceCreatedBy, str]] = ..., is_hidden: _Optional[bool] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., output_of_tab_id: _Optional[str] = ..., schema_info: _Optional[_Union[SchemaInfo, _Mapping]] = ...) -> None: ...

class ColumnSchema(_message.Message):
    __slots__ = ("name", "dtype", "nullable", "sample_value", "description")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DTYPE_FIELD_NUMBER: _ClassVar[int]
    NULLABLE_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_VALUE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    name: str
    dtype: str
    nullable: bool
    sample_value: str
    description: str
    def __init__(self, name: _Optional[str] = ..., dtype: _Optional[str] = ..., nullable: _Optional[bool] = ..., sample_value: _Optional[str] = ..., description: _Optional[str] = ...) -> None: ...

class SchemaInfo(_message.Message):
    __slots__ = ("columns", "row_count", "sheet_names")
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_FIELD_NUMBER: _ClassVar[int]
    SHEET_NAMES_FIELD_NUMBER: _ClassVar[int]
    columns: _containers.RepeatedCompositeFieldContainer[ColumnSchema]
    row_count: int
    sheet_names: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, columns: _Optional[_Iterable[_Union[ColumnSchema, _Mapping]]] = ..., row_count: _Optional[int] = ..., sheet_names: _Optional[_Iterable[str]] = ...) -> None: ...

class HistogramBin(_message.Message):
    __slots__ = ("start", "end", "count")
    START_FIELD_NUMBER: _ClassVar[int]
    END_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    start: float
    end: float
    count: int
    def __init__(self, start: _Optional[float] = ..., end: _Optional[float] = ..., count: _Optional[int] = ...) -> None: ...

class ColumnStats(_message.Message):
    __slots__ = ("column", "dtype", "null_count", "unique_count", "min", "max")
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    DTYPE_FIELD_NUMBER: _ClassVar[int]
    NULL_COUNT_FIELD_NUMBER: _ClassVar[int]
    UNIQUE_COUNT_FIELD_NUMBER: _ClassVar[int]
    MIN_FIELD_NUMBER: _ClassVar[int]
    MAX_FIELD_NUMBER: _ClassVar[int]
    column: str
    dtype: str
    null_count: int
    unique_count: int
    min: _struct_pb2.Value
    max: _struct_pb2.Value
    def __init__(self, column: _Optional[str] = ..., dtype: _Optional[str] = ..., null_count: _Optional[int] = ..., unique_count: _Optional[int] = ..., min: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ..., max: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ...) -> None: ...

class SchemaDiff(_message.Message):
    __slots__ = ("column", "status", "type_a", "type_b")
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    TYPE_A_FIELD_NUMBER: _ClassVar[int]
    TYPE_B_FIELD_NUMBER: _ClassVar[int]
    column: str
    status: _enums_pb2.SchemaDiffStatus
    type_a: str
    type_b: str
    def __init__(self, column: _Optional[str] = ..., status: _Optional[_Union[_enums_pb2.SchemaDiffStatus, str]] = ..., type_a: _Optional[str] = ..., type_b: _Optional[str] = ...) -> None: ...

class SnapshotPreview(_message.Message):
    __slots__ = ("columns", "column_types", "rows", "row_count")
    class ColumnTypesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    COLUMN_TYPES_FIELD_NUMBER: _ClassVar[int]
    ROWS_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_FIELD_NUMBER: _ClassVar[int]
    columns: _containers.RepeatedScalarFieldContainer[str]
    column_types: _containers.ScalarMap[str, str]
    rows: _containers.RepeatedCompositeFieldContainer[_struct_pb2.Struct]
    row_count: int
    def __init__(self, columns: _Optional[_Iterable[str]] = ..., column_types: _Optional[_Mapping[str, str]] = ..., rows: _Optional[_Iterable[_Union[_struct_pb2.Struct, _Mapping]]] = ..., row_count: _Optional[int] = ...) -> None: ...

class SnapshotCompareResult(_message.Message):
    __slots__ = ("datasource_id", "snapshot_a", "snapshot_b", "row_count_a", "row_count_b", "row_count_delta", "schema_diff", "stats_a", "stats_b", "preview_a", "preview_b")
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_A_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_B_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_A_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_B_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_DELTA_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_DIFF_FIELD_NUMBER: _ClassVar[int]
    STATS_A_FIELD_NUMBER: _ClassVar[int]
    STATS_B_FIELD_NUMBER: _ClassVar[int]
    PREVIEW_A_FIELD_NUMBER: _ClassVar[int]
    PREVIEW_B_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    snapshot_a: str
    snapshot_b: str
    row_count_a: int
    row_count_b: int
    row_count_delta: int
    schema_diff: _containers.RepeatedCompositeFieldContainer[SchemaDiff]
    stats_a: _containers.RepeatedCompositeFieldContainer[ColumnStats]
    stats_b: _containers.RepeatedCompositeFieldContainer[ColumnStats]
    preview_a: SnapshotPreview
    preview_b: SnapshotPreview
    def __init__(self, datasource_id: _Optional[str] = ..., snapshot_a: _Optional[str] = ..., snapshot_b: _Optional[str] = ..., row_count_a: _Optional[int] = ..., row_count_b: _Optional[int] = ..., row_count_delta: _Optional[int] = ..., schema_diff: _Optional[_Iterable[_Union[SchemaDiff, _Mapping]]] = ..., stats_a: _Optional[_Iterable[_Union[ColumnStats, _Mapping]]] = ..., stats_b: _Optional[_Iterable[_Union[ColumnStats, _Mapping]]] = ..., preview_a: _Optional[_Union[SnapshotPreview, _Mapping]] = ..., preview_b: _Optional[_Union[SnapshotPreview, _Mapping]] = ...) -> None: ...

class ColumnStatsResult(_message.Message):
    __slots__ = ("column", "dtype", "count", "null_count", "null_percentage", "unique", "mean", "std", "min", "max", "median", "q25", "q75", "true_count", "false_count", "min_length", "max_length", "avg_length", "top_values", "histogram")
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    DTYPE_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    NULL_COUNT_FIELD_NUMBER: _ClassVar[int]
    NULL_PERCENTAGE_FIELD_NUMBER: _ClassVar[int]
    UNIQUE_FIELD_NUMBER: _ClassVar[int]
    MEAN_FIELD_NUMBER: _ClassVar[int]
    STD_FIELD_NUMBER: _ClassVar[int]
    MIN_FIELD_NUMBER: _ClassVar[int]
    MAX_FIELD_NUMBER: _ClassVar[int]
    MEDIAN_FIELD_NUMBER: _ClassVar[int]
    Q25_FIELD_NUMBER: _ClassVar[int]
    Q75_FIELD_NUMBER: _ClassVar[int]
    TRUE_COUNT_FIELD_NUMBER: _ClassVar[int]
    FALSE_COUNT_FIELD_NUMBER: _ClassVar[int]
    MIN_LENGTH_FIELD_NUMBER: _ClassVar[int]
    MAX_LENGTH_FIELD_NUMBER: _ClassVar[int]
    AVG_LENGTH_FIELD_NUMBER: _ClassVar[int]
    TOP_VALUES_FIELD_NUMBER: _ClassVar[int]
    HISTOGRAM_FIELD_NUMBER: _ClassVar[int]
    column: str
    dtype: str
    count: int
    null_count: int
    null_percentage: float
    unique: int
    mean: float
    std: float
    min: _struct_pb2.Value
    max: _struct_pb2.Value
    median: float
    q25: float
    q75: float
    true_count: int
    false_count: int
    min_length: int
    max_length: int
    avg_length: float
    top_values: _containers.RepeatedCompositeFieldContainer[_struct_pb2.Struct]
    histogram: _containers.RepeatedCompositeFieldContainer[HistogramBin]
    def __init__(self, column: _Optional[str] = ..., dtype: _Optional[str] = ..., count: _Optional[int] = ..., null_count: _Optional[int] = ..., null_percentage: _Optional[float] = ..., unique: _Optional[int] = ..., mean: _Optional[float] = ..., std: _Optional[float] = ..., min: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ..., max: _Optional[_Union[_struct_pb2.Value, _Mapping]] = ..., median: _Optional[float] = ..., q25: _Optional[float] = ..., q75: _Optional[float] = ..., true_count: _Optional[int] = ..., false_count: _Optional[int] = ..., min_length: _Optional[int] = ..., max_length: _Optional[int] = ..., avg_length: _Optional[float] = ..., top_values: _Optional[_Iterable[_Union[_struct_pb2.Struct, _Mapping]]] = ..., histogram: _Optional[_Iterable[_Union[HistogramBin, _Mapping]]] = ...) -> None: ...

class DatasourceErrorResult(_message.Message):
    __slots__ = ("error", "message")
    ERROR_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    error: str
    message: str
    def __init__(self, error: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class DatasourceResult(_message.Message):
    __slots__ = ("datasource", "schema", "column_stats", "snapshot_compare", "error", "preflight")
    DATASOURCE_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    COLUMN_STATS_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_COMPARE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    PREFLIGHT_FIELD_NUMBER: _ClassVar[int]
    datasource: DataSourceRecord
    schema: SchemaInfo
    column_stats: ColumnStatsResult
    snapshot_compare: SnapshotCompareResult
    error: DatasourceErrorResult
    preflight: DatasourcePreflightResult
    def __init__(self, datasource: _Optional[_Union[DataSourceRecord, _Mapping]] = ..., schema: _Optional[_Union[SchemaInfo, _Mapping]] = ..., column_stats: _Optional[_Union[ColumnStatsResult, _Mapping]] = ..., snapshot_compare: _Optional[_Union[SnapshotCompareResult, _Mapping]] = ..., error: _Optional[_Union[DatasourceErrorResult, _Mapping]] = ..., preflight: _Optional[_Union[DatasourcePreflightResult, _Mapping]] = ...) -> None: ...
