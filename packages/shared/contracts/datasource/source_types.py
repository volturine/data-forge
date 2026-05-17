from pathlib import Path

from contracts.enums import DataForgeStrEnum


class DataSourceCategory(DataForgeStrEnum):
    FILE = 'file'
    DATABASE = 'database'
    ANALYSIS = 'analysis'

    @property
    def is_file_based(self) -> bool:
        return self == DataSourceCategory.FILE


class DataSourceFileType(DataForgeStrEnum):
    CSV = 'csv'
    PARQUET = 'parquet'
    JSON = 'json'
    NDJSON = 'ndjson'
    EXCEL = 'excel'

    @property
    def upload_suffixes(self) -> tuple[str, ...]:
        match self:
            case DataSourceFileType.CSV:
                return ('.csv',)
            case DataSourceFileType.PARQUET:
                return ('.parquet',)
            case DataSourceFileType.JSON:
                return ('.json',)
            case DataSourceFileType.NDJSON:
                return ('.ndjson', '.jsonl')
            case DataSourceFileType.EXCEL:
                return ('.xlsx',)
        raise AssertionError(f'Unhandled datasource file type: {self}')

    @classmethod
    def from_upload_filename(cls, filename: str) -> 'DataSourceFileType | None':
        return cls.from_upload_suffix(Path(filename).suffix.lower())

    @classmethod
    def from_upload_suffix(cls, suffix: str) -> 'DataSourceFileType | None':
        normalized = suffix.lower()
        for item in cls:
            if normalized in item.upload_suffixes:
                return item
        return None

    @classmethod
    def supported_upload_suffixes(cls) -> tuple[str, ...]:
        return tuple(suffix for item in cls for suffix in item.upload_suffixes)

    @property
    def uses_csv_options(self) -> bool:
        return self == DataSourceFileType.CSV

    @property
    def requires_regular_file(self) -> bool:
        return self != DataSourceFileType.PARQUET

    def matches_magic_number(self, header: bytes) -> bool:
        match self:
            case DataSourceFileType.PARQUET:
                return header.startswith(b'PAR1')
            case DataSourceFileType.EXCEL:
                return header.startswith(b'PK')
            case _:
                return True

    def validate_local_path(self, path: Path) -> None:
        if self.requires_regular_file and not path.is_file():
            raise ValueError(f'Path must be a file for type: {self.value}')
        if self == DataSourceFileType.PARQUET and not (path.is_file() or path.is_dir()):
            raise ValueError('Parquet path must be a file or directory')


class DataSourceType(DataForgeStrEnum):
    FILE = 'file'
    DATABASE = 'database'
    ICEBERG = 'iceberg'
    ANALYSIS = 'analysis'

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
        if self == DataSourceType.FILE:
            return 'File datasource creation must use upload'
        if self == DataSourceType.ANALYSIS:
            return 'Direct creation of analysis datasources is no longer supported. Use analysis tabs with analysis_tab_id.'
        return None

    @property
    def ingestion_error_message(self) -> str:
        if self == DataSourceType.DATABASE:
            return 'Failed to query database datasource'
        if self == DataSourceType.FILE:
            return 'Failed to read file datasource'
        raise ValueError(f'Datasource type {self.value} does not define an ingestion error message')
