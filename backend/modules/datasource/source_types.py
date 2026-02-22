from enum import StrEnum


class DataSourceType(StrEnum):
    FILE = 'file'
    DATABASE = 'database'
    ICEBERG = 'iceberg'
    ANALYSIS = 'analysis'


class DataSourceCategory(StrEnum):
    FILE = 'file'
    DATABASE = 'database'
    ANALYSIS = 'analysis'


SOURCE_TYPE_CATEGORY: dict[DataSourceType, DataSourceCategory] = {
    DataSourceType.FILE: DataSourceCategory.FILE,
    DataSourceType.ICEBERG: DataSourceCategory.FILE,
    DataSourceType.DATABASE: DataSourceCategory.DATABASE,
    DataSourceType.ANALYSIS: DataSourceCategory.ANALYSIS,
}

FILE_BASED_CATEGORIES = {DataSourceCategory.FILE}

FILE_BASED_SOURCE_TYPES = {
    DataSourceType.FILE,
    DataSourceType.ICEBERG,
}
