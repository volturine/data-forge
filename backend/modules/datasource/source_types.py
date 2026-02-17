from enum import Enum


class DataSourceType(str, Enum):
    FILE = 'file'
    DATABASE = 'database'
    API = 'api'
    DUCKDB = 'duckdb'
    ICEBERG = 'iceberg'
    ANALYSIS = 'analysis'


class DataSourceCategory(str, Enum):
    FILE = 'file'
    DATABASE = 'database'
    API = 'api'
    ANALYSIS = 'analysis'


SOURCE_TYPE_CATEGORY: dict[DataSourceType, DataSourceCategory] = {
    DataSourceType.FILE: DataSourceCategory.FILE,
    DataSourceType.DUCKDB: DataSourceCategory.FILE,
    DataSourceType.ICEBERG: DataSourceCategory.FILE,
    DataSourceType.DATABASE: DataSourceCategory.DATABASE,
    DataSourceType.API: DataSourceCategory.API,
    DataSourceType.ANALYSIS: DataSourceCategory.ANALYSIS,
}

FILE_BASED_CATEGORIES = {DataSourceCategory.FILE}

FILE_BASED_SOURCE_TYPES = {
    DataSourceType.FILE,
    DataSourceType.DUCKDB,
    DataSourceType.ICEBERG,
}
