from collections.abc import Callable
from enum import StrEnum

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class TimeseriesOperationType(StrEnum):
    EXTRACT = 'extract'
    TIMESTAMP = 'timestamp'
    ADD = 'add'
    SUBTRACT = 'subtract'
    OFFSET = 'offset'
    DIFF = 'diff'
    TRUNCATE = 'truncate'
    ROUND = 'round'


class TimeComponent(StrEnum):
    YEAR = 'year'
    MONTH = 'month'
    DAY = 'day'
    HOUR = 'hour'
    MINUTE = 'minute'
    SECOND = 'second'
    QUARTER = 'quarter'
    WEEK = 'week'
    DAYOFWEEK = 'dayofweek'


class TimestampUnit(StrEnum):
    NS = 'ns'
    US = 'us'
    MS = 'ms'


class DurationUnit(StrEnum):
    SECONDS = 'seconds'
    MINUTES = 'minutes'
    HOURS = 'hours'
    DAYS = 'days'
    WEEKS = 'weeks'
    MONTHS = 'months'


class TimeDirection(StrEnum):
    ADD = 'add'
    SUBTRACT = 'subtract'


class TimeseriesParams(OperationParams):
    column: str
    operation_type: TimeseriesOperationType
    new_column: str
    component: TimeComponent | None = None
    value: int | float | None = None
    unit: str | None = None
    direction: TimeDirection | None = None
    column2: str | None = None


_COMPONENT_ALIAS: dict[TimeComponent, str] = {TimeComponent.DAYOFWEEK: 'weekday'}

_DURATION_BUILDERS: dict[DurationUnit, Callable[[int], pl.Expr]] = {
    DurationUnit.SECONDS: lambda value: pl.duration(seconds=value),
    DurationUnit.MINUTES: lambda value: pl.duration(minutes=value),
    DurationUnit.HOURS: lambda value: pl.duration(hours=value),
    DurationUnit.DAYS: lambda value: pl.duration(days=value),
    DurationUnit.WEEKS: lambda value: pl.duration(weeks=value),
}

_EVERY_MAP: dict[DurationUnit, str] = {
    DurationUnit.SECONDS: '1s',
    DurationUnit.MINUTES: '1m',
    DurationUnit.HOURS: '1h',
    DurationUnit.DAYS: '1d',
    DurationUnit.WEEKS: '1w',
    DurationUnit.MONTHS: '1mo',
}


def get_extractor(component: str | TimeComponent) -> str:
    try:
        component_enum = component if isinstance(component, TimeComponent) else TimeComponent(component)
    except ValueError as exc:
        raise ValueError(f'Unsupported time component: {component}') from exc
    return _COMPONENT_ALIAS.get(component_enum, component_enum)


def get_duration(unit: str | DurationUnit, value: int) -> pl.Expr:
    try:
        unit_enum = unit if isinstance(unit, DurationUnit) else DurationUnit(unit)
    except ValueError as exc:
        raise ValueError(f'Unsupported duration unit: {unit}') from exc
    builder = _DURATION_BUILDERS.get(unit_enum)
    if not builder:
        raise ValueError(f'Unsupported duration unit: {unit}')
    return builder(value)


def _parse_duration_unit(unit: str | None) -> DurationUnit:
    if unit is None:
        raise ValueError('timeseries operation requires unit parameter')
    try:
        return DurationUnit(unit)
    except ValueError as exc:
        raise ValueError(f'Unsupported duration unit: {unit}') from exc


class TimeseriesHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = TimeseriesParams.model_validate(params)

        if validated.operation_type == TimeseriesOperationType.EXTRACT:
            if validated.component is None:
                raise ValueError('timeseries extract requires component parameter')
            method = get_extractor(validated.component)
            return lf.with_columns(getattr(pl.col(validated.column).dt, method)().alias(validated.new_column))

        if validated.operation_type == TimeseriesOperationType.TIMESTAMP:
            unit = validated.unit
            if unit == TimestampUnit.NS.value:
                return lf.with_columns(pl.col(validated.column).dt.timestamp('ns').alias(validated.new_column))
            if unit == TimestampUnit.MS.value:
                return lf.with_columns(pl.col(validated.column).dt.timestamp('ms').alias(validated.new_column))
            return lf.with_columns(pl.col(validated.column).dt.timestamp('us').alias(validated.new_column))

        if validated.operation_type in {
            TimeseriesOperationType.ADD,
            TimeseriesOperationType.SUBTRACT,
            TimeseriesOperationType.OFFSET,
        }:
            if validated.value is None:
                raise ValueError('timeseries operation requires numeric value parameter')
            duration_unit = _parse_duration_unit(validated.unit)
            subtracting = validated.operation_type == TimeseriesOperationType.SUBTRACT or validated.direction == TimeDirection.SUBTRACT

            if duration_unit == DurationUnit.MONTHS:
                offset = f'-{validated.value}mo' if subtracting else f'{validated.value}mo'
                return lf.with_columns(pl.col(validated.column).dt.offset_by(offset).alias(validated.new_column))

            value_int = int(validated.value)
            if not (-10_000_000 <= value_int <= 10_000_000):
                raise ValueError('Timeseries value must be between -10000000 and 10000000')
            duration = get_duration(duration_unit, value_int)
            expr = pl.col(validated.column) - duration if subtracting else pl.col(validated.column) + duration
            return lf.with_columns(expr.alias(validated.new_column))

        if validated.operation_type == TimeseriesOperationType.DIFF:
            if not validated.column2:
                raise ValueError('timeseries operation requires column2 parameter')
            return lf.with_columns((pl.col(validated.column2) - pl.col(validated.column)).alias(validated.new_column))

        if validated.operation_type in {TimeseriesOperationType.TRUNCATE, TimeseriesOperationType.ROUND}:
            duration_unit = _parse_duration_unit(validated.unit)
            every = _EVERY_MAP.get(duration_unit)
            if every is None:
                raise ValueError(f'Unsupported truncate/round unit: {validated.unit}')
            method = getattr(pl.col(validated.column).dt, validated.operation_type.value)
            return lf.with_columns(method(every).alias(validated.new_column))

        raise ValueError(f'Unsupported timeseries operation: {validated.operation_type}')
