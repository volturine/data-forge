from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.domain_enums import DomainEnumValue


class DataSourceCategory(DomainEnumValue):
    FILE: ClassVar[Self]
    DATABASE: ClassVar[Self]
    ANALYSIS: ClassVar[Self]


DataSourceCategory.FILE = DataSourceCategory(enums_pb2.DATA_SOURCE_CATEGORY_FILE)
DataSourceCategory.DATABASE = DataSourceCategory(enums_pb2.DATA_SOURCE_CATEGORY_DATABASE)
DataSourceCategory.ANALYSIS = DataSourceCategory(enums_pb2.DATA_SOURCE_CATEGORY_ANALYSIS)


class DataSourceFileType(DomainEnumValue):
    CSV: ClassVar[Self]
    PARQUET: ClassVar[Self]
    JSON: ClassVar[Self]
    NDJSON: ClassVar[Self]
    EXCEL: ClassVar[Self]


DataSourceFileType.CSV = DataSourceFileType(enums_pb2.DATA_SOURCE_FILE_TYPE_CSV)
DataSourceFileType.PARQUET = DataSourceFileType(enums_pb2.DATA_SOURCE_FILE_TYPE_PARQUET)
DataSourceFileType.JSON = DataSourceFileType(enums_pb2.DATA_SOURCE_FILE_TYPE_JSON)
DataSourceFileType.NDJSON = DataSourceFileType(enums_pb2.DATA_SOURCE_FILE_TYPE_NDJSON)
DataSourceFileType.EXCEL = DataSourceFileType(enums_pb2.DATA_SOURCE_FILE_TYPE_EXCEL)


class DataSourceType(DomainEnumValue):
    FILE: ClassVar[Self]
    DATABASE: ClassVar[Self]
    ICEBERG: ClassVar[Self]
    ANALYSIS: ClassVar[Self]
    SCHEDULE: ClassVar[Self]

    @property
    def category(self) -> DataSourceCategory:
        if self in {DataSourceType.FILE, DataSourceType.ICEBERG}:
            return DataSourceCategory.FILE
        if self == DataSourceType.DATABASE:
            return DataSourceCategory.DATABASE
        return DataSourceCategory.ANALYSIS

    @property
    def supports_external_ingestion(self) -> bool:
        return self in {DataSourceType.FILE, DataSourceType.DATABASE}


DataSourceType.FILE = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_FILE)
DataSourceType.DATABASE = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_DATABASE)
DataSourceType.ICEBERG = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_ICEBERG)
DataSourceType.ANALYSIS = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_ANALYSIS)
DataSourceType.SCHEDULE = DataSourceType(enums_pb2.DATA_SOURCE_TYPE_SCHEDULE)


class DataSourceLoadType(DomainEnumValue):
    FILE: ClassVar[Self]
    DATABASE: ClassVar[Self]
    DUCKDB: ClassVar[Self]
    ICEBERG: ClassVar[Self]


DataSourceLoadType.FILE = DataSourceLoadType(enums_pb2.DATA_SOURCE_LOAD_TYPE_FILE)
DataSourceLoadType.DATABASE = DataSourceLoadType(enums_pb2.DATA_SOURCE_LOAD_TYPE_DATABASE)
DataSourceLoadType.DUCKDB = DataSourceLoadType(enums_pb2.DATA_SOURCE_LOAD_TYPE_DUCKDB)
DataSourceLoadType.ICEBERG = DataSourceLoadType(enums_pb2.DATA_SOURCE_LOAD_TYPE_ICEBERG)


class IcebergReader(DomainEnumValue):
    NATIVE: ClassVar[Self]
    PYICEBERG: ClassVar[Self]


IcebergReader.NATIVE = IcebergReader(enums_pb2.ICEBERG_READER_NATIVE)
IcebergReader.PYICEBERG = IcebergReader(enums_pb2.ICEBERG_READER_PYICEBERG)
