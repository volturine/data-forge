from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.protocol_enums import ProtocolEnumValue, protocol_token


class DataSourceCategory(ProtocolEnumValue):
    FILE: ClassVar[Self]
    DATABASE: ClassVar[Self]
    ANALYSIS: ClassVar[Self]

    @property
    def is_file_based(self) -> bool:
        return self == DataSourceCategory.FILE


DataSourceCategory.FILE = DataSourceCategory(enums_pb2.DATA_SOURCE_CATEGORY_FILE, protocol_token("DataSourceCategory", enums_pb2.DATA_SOURCE_CATEGORY_FILE))
DataSourceCategory.DATABASE = DataSourceCategory(
    enums_pb2.DATA_SOURCE_CATEGORY_DATABASE, protocol_token("DataSourceCategory", enums_pb2.DATA_SOURCE_CATEGORY_DATABASE)
)
DataSourceCategory.ANALYSIS = DataSourceCategory(
    enums_pb2.DATA_SOURCE_CATEGORY_ANALYSIS, protocol_token("DataSourceCategory", enums_pb2.DATA_SOURCE_CATEGORY_ANALYSIS)
)


class DataSourceFileType(ProtocolEnumValue):
    CSV: ClassVar[Self]
    PARQUET: ClassVar[Self]
    JSON: ClassVar[Self]
    NDJSON: ClassVar[Self]
    EXCEL: ClassVar[Self]

    @property
    def upload_suffixes(self) -> tuple[str, ...]:
        match self:
            case DataSourceFileType.CSV:
                return (".csv",)
            case DataSourceFileType.PARQUET:
                return (".parquet",)
            case DataSourceFileType.JSON:
                return (".json",)
            case DataSourceFileType.NDJSON:
                return (".ndjson", ".jsonl")
            case DataSourceFileType.EXCEL:
                return (".xlsx",)
        raise AssertionError(f"Unhandled datasource file type: {self}")

    @classmethod
    def from_upload_filename(cls, filename: str) -> DataSourceFileType | None:
        return cls.from_upload_suffix(Path(filename).suffix.lower())

    @classmethod
    def from_upload_suffix(cls, suffix: str) -> DataSourceFileType | None:
        normalized = suffix.lower()
        for item in cls.members():
            if normalized in item.upload_suffixes:
                return item
        return None

    @classmethod
    def supported_upload_suffixes(cls) -> tuple[str, ...]:
        return tuple(suffix for item in cls.members() for suffix in item.upload_suffixes)

    @property
    def uses_csv_options(self) -> bool:
        return self == DataSourceFileType.CSV

    @property
    def requires_regular_file(self) -> bool:
        return self != DataSourceFileType.PARQUET

    def matches_magic_number(self, header: bytes) -> bool:
        match self:
            case DataSourceFileType.PARQUET:
                return header.startswith(b"PAR1")
            case DataSourceFileType.EXCEL:
                return header.startswith(b"PK")
            case _:
                return True

    def validate_local_path(self, path: Path) -> None:
        if self.requires_regular_file and not path.is_file():
            raise ValueError(f"Path must be a file for type: {self.value}")
        if self == DataSourceFileType.PARQUET and not (path.is_file() or path.is_dir()):
            raise ValueError("Parquet path must be a file or directory")


DataSourceFileType.CSV = DataSourceFileType(enums_pb2.DATA_SOURCE_FILE_TYPE_CSV, protocol_token("DataSourceFileType", enums_pb2.DATA_SOURCE_FILE_TYPE_CSV))
DataSourceFileType.PARQUET = DataSourceFileType(
    enums_pb2.DATA_SOURCE_FILE_TYPE_PARQUET, protocol_token("DataSourceFileType", enums_pb2.DATA_SOURCE_FILE_TYPE_PARQUET)
)
DataSourceFileType.JSON = DataSourceFileType(enums_pb2.DATA_SOURCE_FILE_TYPE_JSON, protocol_token("DataSourceFileType", enums_pb2.DATA_SOURCE_FILE_TYPE_JSON))
DataSourceFileType.NDJSON = DataSourceFileType(
    enums_pb2.DATA_SOURCE_FILE_TYPE_NDJSON, protocol_token("DataSourceFileType", enums_pb2.DATA_SOURCE_FILE_TYPE_NDJSON)
)
DataSourceFileType.EXCEL = DataSourceFileType(
    enums_pb2.DATA_SOURCE_FILE_TYPE_EXCEL, protocol_token("DataSourceFileType", enums_pb2.DATA_SOURCE_FILE_TYPE_EXCEL)
)


class DataSourceType(ProtocolEnumValue):
    FILE: ClassVar[Self]
    DATABASE: ClassVar[Self]
    ICEBERG: ClassVar[Self]
    ANALYSIS: ClassVar[Self]

    @property
    def category(self) -> DataSourceCategory:
        if self in {DataSourceType.FILE, DataSourceType.ICEBERG}:
            return DataSourceCategory.FILE
        if self == DataSourceType.DATABASE:
            return DataSourceCategory.DATABASE
        return DataSourceCategory.ANALYSIS

    @property
    def is_file_based(self) -> bool:
        return self.category.is_file_based

    @property
    def supports_external_ingestion(self) -> bool:
        return self in {DataSourceType.FILE, DataSourceType.DATABASE}

    @property
    def connect_api_error_message(self) -> str | None:
        if self == DataSourceType.ANALYSIS:
            return "Direct creation of analysis datasources is no longer supported. Use analysis tabs with analysis_tab_id."
        return None

    @property
    def ingestion_error_message(self) -> str:
        if self == DataSourceType.DATABASE:
            return "Failed to query database datasource"
        if self == DataSourceType.FILE:
            return "Failed to read file datasource"
        raise ValueError(f"Datasource type {self.value} does not define an ingestion error message")


DataSourceType.FILE = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_FILE, protocol_token("DataSourceType", enums_pb2.DATA_SOURCE_TYPE_FILE))
DataSourceType.DATABASE = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_DATABASE, protocol_token("DataSourceType", enums_pb2.DATA_SOURCE_TYPE_DATABASE))
DataSourceType.ICEBERG = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_ICEBERG, protocol_token("DataSourceType", enums_pb2.DATA_SOURCE_TYPE_ICEBERG))
DataSourceType.ANALYSIS = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_ANALYSIS, protocol_token("DataSourceType", enums_pb2.DATA_SOURCE_TYPE_ANALYSIS))


class DataSourceLoadType(ProtocolEnumValue):
    FILE: ClassVar[Self]
    DATABASE: ClassVar[Self]
    DUCKDB: ClassVar[Self]
    ICEBERG: ClassVar[Self]


DataSourceLoadType.FILE = DataSourceLoadType(enums_pb2.DATA_SOURCE_LOAD_TYPE_FILE, protocol_token("DataSourceLoadType", enums_pb2.DATA_SOURCE_LOAD_TYPE_FILE))
DataSourceLoadType.DATABASE = DataSourceLoadType(
    enums_pb2.DATA_SOURCE_LOAD_TYPE_DATABASE, protocol_token("DataSourceLoadType", enums_pb2.DATA_SOURCE_LOAD_TYPE_DATABASE)
)
DataSourceLoadType.DUCKDB = DataSourceLoadType(
    enums_pb2.DATA_SOURCE_LOAD_TYPE_DUCKDB, protocol_token("DataSourceLoadType", enums_pb2.DATA_SOURCE_LOAD_TYPE_DUCKDB)
)
DataSourceLoadType.ICEBERG = DataSourceLoadType(
    enums_pb2.DATA_SOURCE_LOAD_TYPE_ICEBERG, protocol_token("DataSourceLoadType", enums_pb2.DATA_SOURCE_LOAD_TYPE_ICEBERG)
)


class IcebergReader(ProtocolEnumValue):
    NATIVE: ClassVar[Self]
    PYICEBERG: ClassVar[Self]


IcebergReader.NATIVE = IcebergReader(enums_pb2.ICEBERG_READER_NATIVE, protocol_token("IcebergReader", enums_pb2.ICEBERG_READER_NATIVE))
IcebergReader.PYICEBERG = IcebergReader(enums_pb2.ICEBERG_READER_PYICEBERG, protocol_token("IcebergReader", enums_pb2.ICEBERG_READER_PYICEBERG))
