import datetime as dt
import uuid
from typing import Any, cast

from sqlalchemy import JSON, Column, DateTime, String
from sqlmodel import Field, SQLModel

from contracts.enums import DataForgeStrEnum


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


class HealthCheck(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'healthchecks'

    def check_type_kind(self) -> HealthCheckType:
        return HealthCheckType.require(self.check_type)

    def metric_alias(self, suffix: str) -> str:
        if self.check_type_kind() == HealthCheckType.ROW_COUNT and suffix == 'count':
            return 'row_count__count'
        return f'{self.id}__{suffix}'

    def column_name(self) -> str | None:
        value = self.config.get('column')
        if isinstance(value, str) and value:
            return value
        return None

    def configured_columns(self, *, default: list[str]) -> list[str]:
        values = self.config.get('columns')
        if not isinstance(values, list):
            return default
        columns = [str(value) for value in values if str(value)]
        return columns or default

    def result_details(self, **actuals: object) -> dict[str, object]:
        return {**self.config, **actuals}

    def metric_value(self, values: dict[str, object], suffix: str) -> object:
        return values[self.metric_alias(suffix)]

    def metric_int(self, values: dict[str, object], suffix: str) -> int:
        return int(cast(int | float | str, self.metric_value(values, suffix)))

    def metric_float(self, values: dict[str, object], suffix: str) -> float:
        return float(cast(int | float | str, self.metric_value(values, suffix)))

    def config_int(self, key: str) -> int | None:
        value = self.config.get(key)
        return int(cast(int | float | str, value)) if value is not None else None

    def config_float(self, key: str) -> float | None:
        value = self.config.get(key)
        return float(cast(int | float | str, value)) if value is not None else None

    def missing_column_result(self, *, now: dt.datetime) -> 'HealthCheckResult':
        column_name = self.column_name() or ''
        return HealthCheckResult(
            id=str(uuid.uuid4()),
            healthcheck_id=self.id,
            passed=False,
            message=f'Column "{column_name}" not found in dataset',
            details=self.result_details(error='column_not_found'),
            checked_at=now,
        )

    def evaluate(self, *, values: dict[str, object], schema_names: set[str]) -> tuple[bool, str, dict[str, object]]:
        match self.check_type_kind():
            case HealthCheckType.ROW_COUNT:
                count = self.metric_int(values, 'count')
                min_rows = self.config_int('min_rows')
                max_rows = self.config_int('max_rows')
                passed = True
                messages: list[str] = []
                if min_rows is not None and count < int(min_rows):
                    passed = False
                    messages.append(f'Too few: {count} < {min_rows}')
                if max_rows is not None and count > int(max_rows):
                    passed = False
                    messages.append(f'Too many: {count} > {max_rows}')
                message = '; '.join(messages) if messages else f'Row count: {count}'
                return passed, message, self.result_details(actual_count=count)
            case HealthCheckType.COLUMN_COUNT:
                count = len(schema_names)
                min_cols = self.config_int('min_columns')
                max_cols = self.config_int('max_columns')
                passed = True
                messages = []
                if min_cols is not None and count < int(min_cols):
                    passed = False
                    messages.append(f'Too few: {count} < {min_cols}')
                if max_cols is not None and count > int(max_cols):
                    passed = False
                    messages.append(f'Too many: {count} > {max_cols}')
                message = '; '.join(messages) if messages else f'Column count: {count}'
                return passed, message, self.result_details(actual_count=count)
            case HealthCheckType.COLUMN_NULL | HealthCheckType.NULL_PERCENTAGE:
                pct = self.metric_float(values, 'null_pct')
                threshold = self.config_float('threshold') or 0.0
                passed = pct <= threshold
                return (
                    passed,
                    f'Nulls: {pct:.1f}% (threshold: {threshold}%)',
                    self.result_details(actual_percentage=round(pct, 2)),
                )
            case HealthCheckType.COLUMN_UNIQUE:
                unique = self.metric_int(values, 'unique')
                expected = self.config_int('expected_unique')
                if expected is None:
                    return True, f'Unique values: {unique}', self.result_details(actual_unique=unique)
                return unique == expected, f'Unique: {unique} (expected: {expected})', self.result_details(actual_unique=unique)
            case HealthCheckType.COLUMN_RANGE:
                col_min = self.metric_value(values, 'min')
                col_max = self.metric_value(values, 'max')
                col_min_number = float(cast(int | float | str, col_min))
                col_max_number = float(cast(int | float | str, col_max))
                min_value = self.config_float('min')
                max_value = self.config_float('max')
                passed = True
                messages = []
                if min_value is not None and col_min_number < min_value:
                    passed = False
                    messages.append(f'Min {col_min!r} < {min_value}')
                if max_value is not None and col_max_number > max_value:
                    passed = False
                    messages.append(f'Max {col_max!r} > {max_value}')
                message = '; '.join(messages) if messages else f'Range: [{col_min!r}, {col_max!r}]'
                return passed, message, self.result_details(actual_min=col_min, actual_max=col_max)
            case HealthCheckType.DUPLICATE_PERCENTAGE:
                total = self.metric_int(values, 'rows')
                unique = self.metric_int(values, 'unique_rows')
                threshold = self.config_float('threshold') or 0.0
                pct = 0.0 if total == 0 else (1 - unique / total) * 100.0
                return (
                    pct <= threshold,
                    f'Duplicates: {pct:.1f}% (threshold: {threshold}%)',
                    self.result_details(actual_percentage=round(pct, 2)),
                )

    id: str = Field(sa_column=Column(String, primary_key=True))
    datasource_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    name: str = Field(sa_column=Column(String, nullable=False))
    check_type: str = Field(sa_column=Column(String, nullable=False))
    config: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    enabled: bool = Field(default=True)
    critical: bool = Field(default=False)
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class HealthCheckResult(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'healthcheck_results'

    id: str = Field(sa_column=Column(String, primary_key=True))
    healthcheck_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    passed: bool = Field(default=False)
    message: str = Field(sa_column=Column(String, nullable=False))
    details: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    checked_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
