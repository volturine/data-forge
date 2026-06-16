from backend_core.contracts.enums import DataForgeStrEnum


class HealthCheckType(DataForgeStrEnum):
    ROW_COUNT = 'row_count'
    COLUMN_NULL = 'column_null'
    COLUMN_UNIQUE = 'column_unique'
    COLUMN_RANGE = 'column_range'
    COLUMN_COUNT = 'column_count'
    NULL_PERCENTAGE = 'null_percentage'
    DUPLICATE_PERCENTAGE = 'duplicate_percentage'

    @property
    def requires_unique_per_datasource(self) -> bool:
        return self == HealthCheckType.ROW_COUNT

    @property
    def requires_column(self) -> bool:
        return self in {HealthCheckType.COLUMN_NULL, HealthCheckType.COLUMN_UNIQUE, HealthCheckType.COLUMN_RANGE}
